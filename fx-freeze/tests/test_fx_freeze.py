"""fx-freeze on the M4, through the real FX path in the emulator: alone (delay looper) and
with fx-reverb (reverb hold). Needs arm-none-eabi-gcc."""
import shutil
import tempfile
import unittest

from fixtures import SYMBOLS_V130, build_patched, require_image
from perkons import verify
from perkons.emu import M4Emu, M4FX, Symbols
from perkons.fwimage import Image

SYMBOLS_M4 = SYMBOLS_V130.replace('-m7.json', '-m4.json')
LONG, SHORT = 0, 1          # SHORT/LONG GPIO levels; freeze is at LONG


def energy(x, seg=4800):
    return [sum(abs(v) for v in x[i:i + seg]) / seg for i in range(0, len(x) - seg + 1, seg)]


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestFxFreeze(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = Image.load(require_image('v1.3.0'))
        cls.s4, cls.s7 = Symbols(SYMBOLS_M4), Symbols(SYMBOLS_V130)
        cls.tmp = tempfile.mkdtemp(prefix='pk-fxf-')
        cls.alone, p = build_patched(cls.stock, ['fx_freeze'], cls.tmp + '/a')
        cls.alone_syms = p.cave_symbols['m4host']
        cls.both, p = build_patched(cls.stock, ['fx_reverb', 'fx_freeze'], cls.tmp + '/b')
        cls.both_syms = p.cave_symbols['m4host']
        cls.hit = verify.render_output(cls.stock, cls.s7, 1, 1, 0, n=6000)   # a real voice-2 hit

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def fx(self, image, syms=None, cfg=None, switch=SHORT):
        """Booted with the switch at `switch` (fx_update reads it once during boot)."""
        def pre(e):
            e.call(syms['pk4_boot'], max_insns=50_000_000)
            for var, v in (cfg or {}).items():
                e.w8(syms[var], v)
        fx = M4FX(image.segment('m4').data, self.s4, image.segment('m7').data)
        fx.switch = switch
        return fx.boot(pre if syms else None)

    def run_seq(self, fx, send, seq):
        out, chunk = [], len(send) // len(seq)
        for i, (knobs, switch) in enumerate(seq):
            fx.knobs, fx.switch = knobs, switch
            out += fx.process(send[i * chunk:(i + 1) * chunk])
        return out

    def test_freeze_off_is_stock(self):
        send = (self.hit + [0] * 18000) * 3
        seq = [(dict(time=.3, feedback=.5, rate=0, depth=0), LONG),
               (dict(time=.7, feedback=.8, rate=.5, depth=.6), SHORT),
               (dict(time=.1, feedback=.2, rate=1, depth=.2), LONG)]
        ref = self.run_seq(self.fx(self.stock), send, seq)
        for img, syms in ((self.alone, self.alone_syms), (self.both, self.both_syms)):
            self.assertEqual(self.run_seq(self.fx(img, syms), send, seq), ref)

    def test_freeze_mode_delay_runs_short(self):
        """In freeze mode the switch is freeze, and the delay stays at SHORT either way."""
        send = (self.hit + [0] * 18000) * 2
        knobs = dict(time=.5, feedback=.5, rate=0, depth=0)
        ref = self.run_seq(self.fx(self.stock), send, [(knobs, SHORT)])
        got = self.run_seq(self.fx(self.alone, self.alone_syms, {'pk_cfg_freeze': 1}), send, [(knobs, SHORT)])
        self.assertEqual(got, ref)

    def test_power_on_at_long_starts_frozen(self):
        s = self.alone_syms
        fx = self.fx(self.alone, s, {'pk_cfg_freeze': 1}, switch=LONG)
        fx.process([0] * 480)
        self.assertEqual(fx.r8(s['pk_frozen']), 1)

    def test_delay_freeze_loops_last_repeat(self):
        s = self.alone_syms
        fx = self.fx(self.alone, s, {'pk_cfg_freeze': 1})
        fx.knobs = dict(time=.3, feedback=.5, rate=0, depth=0)
        fx.switch = SHORT
        fx.process(self.hit + [0] * 9000)
        fx.switch = LONG                                     # freeze
        frozen = fx.process(self.hit * 2 + [0] * 36000)     # new input must be ignored
        self.assertEqual(fx.r8(s['pk_frozen']), 1, 'frozen flag')
        length = fx.r32(s['pk_loop_len'])
        self.assertGreater(length, 0)
        tail = frozen[-4 * length:]
        same = sum(1 for i in range(length, 3 * length) if tail[i] == tail[i + length])
        self.assertGreater(same / (2 * length), 0.95, 'output repeats with the loop period')
        self.assertGreater(max(map(abs, tail)), 300, 'loop is audible')
        fx.switch = SHORT                                    # release: back to the live delay
        fx.process([0] * 480)
        self.assertEqual(fx.r8(s['pk_frozen']), 0)

    def test_reverb_freeze_holds_and_ignores_input(self):
        s = self.both_syms
        fx = self.fx(self.both, s, {'pk_cfg_freeze': 1, 'pk_cfg_reverb': 1})
        fx.knobs, fx.switch = dict(time=0, feedback=.5, rate=.5, depth=.3), SHORT
        fx.process([0] * 2400)                               # switch-over to reverb
        fx.process(self.hit + [0] * 2000)
        fx.switch = LONG
        held = fx.process(self.hit * 3 + [0] * 96000)        # hits while frozen: ignored
        e = energy(held)
        self.assertGreater(e[-1], 0.5 * e[3], 'tail held for 2 s')
        self.assertLess(max(e), 3 * e[3] + 1, 'no build-up from new input')

    def test_build_order_does_not_matter(self):
        other, _ = build_patched(self.stock, ['fx_freeze', 'fx_reverb'], self.tmp + '/c')
        self.assertEqual(other.segment('m4').data, self.both.segment('m4').data)

    def test_device_json_keys_load(self):
        s = self.both_syms
        sd = {'system/device.json': b'{"vintage-bbd": true, "fx-reverb": true, "fx-switch-freeze": true}'}
        e = M4Emu(self.both.segment('m4').data, self.s4, self.both.segment('m7').data, sd=sd).boot()
        e.call(s['pk4_boot'], max_insns=50_000_000)
        self.assertEqual((e.r8(s['pk_cfg_reverb']), e.r8(s['pk_cfg_freeze'])), (1, 1))
        self.assertEqual(e.r8(self.s4.g['device_config'] + 7), 1, 'stock keys still load')
