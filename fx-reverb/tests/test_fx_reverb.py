"""fx-reverb on the M4, through the real FX path (fx_init, SAI3 DMA callbacks, fx_update)
in the emulator. Needs arm-none-eabi-gcc. Freeze is tested in fx-freeze."""
import shutil
import tempfile
import unittest

from fixtures import SYMBOLS_V130, build_patched, require_image
from perkons import verify
from perkons.emu import M4FX, Symbols
from perkons.fwimage import Image

SYMBOLS_M4 = SYMBOLS_V130.replace('-m7.json', '-m4.json')


def energy(x, seg=4800):
    return [sum(abs(v) for v in x[i:i + seg]) / seg for i in range(0, len(x) - seg + 1, seg)]


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestFxReverb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = Image.load(require_image('v1.3.0'))
        cls.s4, cls.s7 = Symbols(SYMBOLS_M4), Symbols(SYMBOLS_V130)
        cls.tmp = tempfile.mkdtemp(prefix='pk-fxr-')
        cls.img, p = build_patched(cls.stock, ['fx_reverb'], cls.tmp)
        cls.syms = p.cave_symbols['m4host']
        cls.hit = verify.render_output(cls.stock, cls.s7, 1, 1, 0, n=6000)   # a real voice-2 hit

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def fx(self, image=None, reverb=0):
        image = image or self.img
        s = self.syms

        def pre(e):
            e.call(s['pk4_boot'], max_insns=50_000_000)
            e.w8(s['pk_cfg_reverb'], reverb)
        return M4FX(image.segment('m4').data, self.s4, image.segment('m7').data).boot(
            pre if image is self.img else None)

    def run_seq(self, fx, send, seq):
        out, chunk = [], len(send) // len(seq)
        for i, (knobs, switch) in enumerate(seq):
            fx.knobs, fx.switch = knobs, switch
            out += fx.process(send[i * chunk:(i + 1) * chunk])
        return out

    def test_delay_mode_bit_identical_to_stock(self):
        send = (self.hit + [0] * 18000) * 3
        seq = [(dict(time=.3, feedback=.5, rate=0, depth=0), 0),
               (dict(time=.7, feedback=.8, rate=.5, depth=.6), 1),
               (dict(time=.1, feedback=.2, rate=1, depth=.2), 0)]
        self.assertEqual(self.run_seq(self.fx(self.stock), send, seq), self.run_seq(self.fx(), send, seq))

    def reverb(self, knobs, switch=0, send=None):
        fx = self.fx(reverb=1)
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

    def test_switch_over_is_silent_then_clean(self):
        s = self.syms
        fx = self.fx()
        fx.knobs = dict(time=.3, feedback=.6, rate=0, depth=0)
        fx.process(self.hit + [0] * 4000)                   # delay has history
        for to in (1, 0):
            fx.w8(s['pk_cfg_reverb'], to)
            gap = fx.process([0] * 320)
            self.assertEqual(max(map(abs, gap)), 0, 'muted while clearing')
            quiet = fx.process([0] * 4800)
            self.assertEqual(max(map(abs, quiet)), 0, 'no leftovers from the other engine')
            self.assertEqual(fx.r8(s['pk_reverb_active']), to)
            fx.process(self.hit + [0] * 4000)               # this engine has history now

    def leds(self, fx):
        vals = []
        fx.stub(self.s4.fn['fx_lfo_led_pwm'], lambda emu, v, *_: vals.append(v & 0xffff))
        return vals

    def test_lfo_led_delay_mode_is_stock(self):
        knobs = dict(time=.4, feedback=.4, rate=.6, depth=.5)
        got = []
        for fx in (self.fx(self.stock), self.fx()):
            fx.knobs, vals = knobs, self.leds(fx)
            fx.process([0] * 24000)
            got.append(vals)
        self.assertEqual(got[0], got[1])
        self.assertGreater(max(got[0]) - min(got[0]), 20000, 'LED moves')

    def test_lfo_led_follows_reverb_modulation(self):
        seqs = {}
        for rate in (0, 1):
            fx = self.fx(reverb=1)
            fx.knobs = dict(time=0, feedback=.5, rate=rate, depth=1)
            vals = self.leds(fx)
            fx.process([0] * 96000)                          # 2 s: > 1 cycle at 0.75 Hz
            seqs[rate] = vals[-4000:]
        self.assertEqual(seqs[0], seqs[1], 'LFO RATE (diffusion in reverb mode) does not move it')
        v = seqs[1]
        self.assertGreater(max(v) - min(v), 50000, 'full sweep')
        rises = sum(1 for a, b in zip(v, v[1:]) if b > a)
        falls = sum(1 for a, b in zip(v, v[1:]) if b < a)   # the LFO steps every 4th block
        self.assertTrue(0.2 < rises / (rises + falls) < 0.8, 'goes up and down')

    def test_setting_loads_from_mods_json(self):
        from perkons.emu import M4Emu
        sd = {'system/device.json': b'{"vintage-bbd": true}', 'system/mods.json': b'{"fx-reverb": true}'}
        e = M4Emu(self.img.segment('m4').data, self.s4, self.img.segment('m7').data, sd=sd).boot()
        e.call(self.syms['pk4_boot'], max_insns=50_000_000)
        self.assertEqual(e.r8(self.syms['pk_cfg_reverb']), 1)
