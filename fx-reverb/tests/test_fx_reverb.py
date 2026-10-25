"""fx-reverb on the M4, through the real FX path (fx_init, SAI3 DMA callbacks, fx_update)
in the emulator. Needs arm-none-eabi-gcc."""
import os
import re
import shutil
import struct
import tempfile
import unittest

from fixtures import SYMBOLS_V130, require_image
from perkons import verify
from perkons.emu import M4Emu, M4FX, Symbols
from perkons.fwimage import Image
from perkons.mods import load_patch
from perkons.patch import Patcher

import fxr

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYMBOLS_M4 = SYMBOLS_V130.replace('-m7.json', '-m4.json')
ST = fxr.PK4_STATE_ADDR


def energy(x, seg=4800):
    return [sum(abs(v) for v in x[i:i + seg]) / seg for i in range(0, len(x) - seg + 1, seg)]


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestFxReverb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = Image.load(require_image('v1.3.0'))
        cls.s4, cls.s7 = Symbols(SYMBOLS_M4), Symbols(SYMBOLS_V130)
        cls.tmp = tempfile.mkdtemp(prefix='pk-fxr-')
        p = Patcher(cls.stock)
        p.symbols = {'m7': cls.s7, 'm4': cls.s4}
        p.build_dir = cls.tmp
        load_patch('fx_reverb').apply(p)
        cls.img, cls.syms = p.result(), p.cave_symbols['m4']
        hit = verify.render_output(cls.stock, cls.s7, 1, 1, 0, n=6000)   # a real voice-2 hit
        cls.hit = hit

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def fx(self, image=None, cfg=None, sd=None):
        image = image or self.img

        def pre(e):
            e.call(self.syms['pk4_boot'], max_insns=50_000_000)
            for off, v in (cfg or {}).items():
                e.w8(ST + off, v)
        patched = image is self.img
        return M4FX(image.segment('m4').data, self.s4, image.segment('m7').data, sd=sd or {}).boot(
            pre if patched else None)

    def run_seq(self, fx, send, seq):
        out, chunk = [], len(send) // len(seq)
        for i, (knobs, switch) in enumerate(seq):
            fx.knobs, fx.switch = knobs, switch
            out += fx.process(send[i * chunk:(i + 1) * chunk])
        return out

    # -- delay mode ---------------------------------------------------------------
    def test_delay_mode_bit_identical_to_stock(self):
        send = (self.hit + [0] * 18000) * 3
        seq = [(dict(time=.3, feedback=.5, rate=0, depth=0), 0),
               (dict(time=.7, feedback=.8, rate=.5, depth=.6), 1),
               (dict(time=.1, feedback=.2, rate=1, depth=.2), 0)]
        a = self.run_seq(self.fx(self.stock), send, seq)
        b = self.run_seq(self.fx(), send, seq)
        self.assertEqual(a, b)

    def test_delay_freeze_loops_last_repeat(self):
        fx = self.fx(cfg={fxr.OFF_CFG_FREEZE: 1})
        fx.knobs = dict(time=.3, feedback=.5, rate=0, depth=0)
        fx.switch = 0
        fx.process(self.hit + [0] * 9000)
        fx.switch = 1                                       # freeze (switch at SHORT)
        frozen = fx.process(self.hit * 2 + [0] * 36000)     # new input must be ignored
        self.assertEqual(fx.r8(ST + fxr.OFF_FROZEN), 1, 'frozen flag')
        length = fx.r32(ST + fxr.OFF_LOOP_LEN)
        self.assertGreater(length, 0)
        tail = frozen[-4 * length:]
        same = sum(1 for i in range(length, 3 * length) if tail[i] == tail[i + length])
        self.assertGreater(same / (2 * length), 0.95, 'output repeats with the loop period')
        self.assertGreater(max(map(abs, tail)), 300, 'loop is audible')

    # -- reverb mode --------------------------------------------------------------
    def reverb(self, knobs, switch=0, cfg=None, send=None):
        fx = self.fx(cfg={fxr.OFF_CFG_REVERB: 1, **(cfg or {})})
        fx.knobs, fx.switch = knobs, switch
        fx.process([0] * 2400)                              # switch-over clear + knob settling
        return fx, fx.process(send or self.hit + [0] * 96000)

    def test_reverb_tail_and_decay_knob(self):
        _, short = self.reverb(dict(time=0, feedback=.1, rate=.5, depth=.3))
        _, long_ = self.reverb(dict(time=0, feedback=.95, rate=.5, depth=.3))
        es, el = energy(short), energy(long_)
        self.assertGreater(max(map(abs, long_)), 500, 'audible')
        self.assertTrue(all(v < 32767 for v in map(abs, long_)), 'no clipping')
        late = slice(10, 18)                                # 1.0-1.8 s after the hit
        self.assertGreater(sum(el[late]), 5 * sum(es[late]) + 1, 'longer FEEDBACK, longer tail')
        self.assertLess(el[-1], el[2], 'tail decays (finite at max FEEDBACK)')

    def test_reverb_stable_at_extremes(self):
        """Busy drums into every knob extreme: the tail must not build up or clip."""
        beat = (self.hit + [0] * 6000) * 8
        for kn in (dict(time=.3, feedback=1, rate=1, depth=1), dict(time=0, feedback=1, rate=0, depth=1),
                   dict(time=1, feedback=1, rate=1, depth=0)):
            for switch in (0, 1):
                with self.subTest(knobs=kn, switch=switch):
                    _, out = self.reverb(kn, switch, send=beat)
                    self.assertLess(max(map(abs, out)), 32767, 'no clipping')
                    e = energy(out)
                    self.assertLess(max(e[-6:]), 3 * max(e[:6]) + 1, 'no build-up over time')

    def test_reverb_predelay(self):
        _, a = self.reverb(dict(time=0, feedback=.5, rate=.5, depth=0))
        _, b = self.reverb(dict(time=1, feedback=.5, rate=.5, depth=0))
        first = lambda x: next(i for i, v in enumerate(x) if abs(v) > 50)
        self.assertGreater(first(b) - first(a), 0.12 * 48000, 'TIME adds ~170 ms of pre-delay')

    def test_reverb_freeze_holds_and_ignores_input(self):
        fx, _ = self.reverb(dict(time=0, feedback=.5, rate=.5, depth=.3), cfg={fxr.OFF_CFG_FREEZE: 1},
                            send=self.hit + [0] * 2000)
        fx.switch = 1
        held = fx.process(self.hit * 3 + [0] * 96000)       # hits while frozen: ignored
        e = energy(held)
        self.assertGreater(e[-1], 0.5 * e[3], 'tail held for 2 s')
        self.assertLess(max(e), 3 * e[3] + 1, 'no build-up from new input')

    def test_switch_over_is_silent_then_clean(self):
        fx = self.fx()
        fx.knobs = dict(time=.3, feedback=.6, rate=0, depth=0)
        fx.process(self.hit + [0] * 4000)                   # delay has history
        fx.w8(ST + fxr.OFF_CFG_REVERB, 1)
        gap = fx.process([0] * 640)
        self.assertEqual(max(map(abs, gap)), 0, 'muted while clearing')
        quiet = fx.process([0] * 4800)
        self.assertEqual(max(map(abs, quiet)), 0, 'no leftovers from the delay')
        self.assertEqual(fx.r8(ST + fxr.OFF_ACTIVE_REVERB), 1)

    # -- config ---------------------------------------------------------------------
    def test_config_toggles_dirty_flag_and_leds(self):
        e = M4Emu(self.img.segment('m4').data, self.s4, self.img.segment('m7').data).boot()
        e.call(self.syms['pk4_boot'], max_insns=50_000_000)
        leds = {}
        e.stub(self.s4.fn['set_led'], lambda emu, k, lvl, *_: leds.__setitem__(k, lvl))
        ev = self.s4.mem['bss_end']
        for key, off in ((fxr.KEY_FX_TYPE, fxr.OFF_CFG_REVERB), (fxr.KEY_SWITCH_MODE, fxr.OFF_CFG_FREEZE)):
            e.w8(self.s4.g['cfg_dirty'], 0)
            e.uc.mem_write(ev, bytes([key, 0x11]))
            self.assertEqual(e.call(self.syms['pk4_cfg_event'], ev), 1)
            self.assertEqual(e.r8(ST + off), 1)
            self.assertEqual(e.r8(self.s4.g['cfg_dirty']), 1, 'marked for saving')
        e.call(self.syms['pk4_cfg_render'], 0, 0, 0, 0)
        self.assertEqual((leds.get(46), leds.get(47)), (0x80, 0x80))

    def test_device_json_keys_load(self):
        sd = {'system/device.json': b'{"vintage-bbd": true, "fx-reverb": true, "fx-switch-freeze": true}'}
        e = M4Emu(self.img.segment('m4').data, self.s4, self.img.segment('m7').data, sd=sd).boot()
        e.call(self.syms['pk4_boot'], max_insns=50_000_000)        # defaults, then the real load
        self.assertEqual((e.r8(ST + fxr.OFF_CFG_REVERB), e.r8(ST + fxr.OFF_CFG_FREEZE)), (1, 1))
        self.assertEqual(e.r8(self.s4.g['device_config'] + 7), 1, 'stock keys still load')

    def test_ram_constants_match_header(self):
        with open(os.path.join(MOD, 'src', 'm4', 'pk4_ram.h')) as f:
            h = f.read()
        self.assertEqual(int(re.search(r'PK4_STATE_ADDR\s+(0x[0-9a-f]+)', h).group(1), 16), fxr.PK4_STATE_ADDR)
        self.assertEqual(int(re.search(r'PK4_REVERB_BUF\s+(0x[0-9a-f]+)', h).group(1), 16), fxr.PK4_REVERB_BUF)
        seg = self.img.segment('m4')
        lit = self.s4.site('sbrk.limit_literal')['addr']
        self.assertEqual(struct.unpack_from('<I', seg.data, lit - seg.addr)[0] - 0x400, fxr.PK4_STATE_ADDR)
