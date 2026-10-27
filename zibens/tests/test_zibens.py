"""ZIBENS on the M7, through main()'s message loop and the real audio callback, as a
voice-map engine (config message type 4 puts it on an output). Needs arm-none-eabi-gcc."""
import math
import shutil
import tempfile
import unittest

from fixtures import SYMBOLS_V130, build_patched, require_image
from perkons import verify
from perkons.emu import M4Emu, Symbols
from perkons.fwimage import Image
from perkons.patch import PatchError

SR = 48000
POS1, POS2, POS3 = 1, 0, 2          # switch values for panel positions 1, 2, 3
SAW, SQUARE, SINE = POS1, POS2, POS3
PENT, DORIAN, PHRYGIAN = POS1, POS2, POS3
SCALES = {PENT: [0, 3, 5, 7, 10], DORIAN: [0, 2, 3, 5, 7, 9, 10], PHRYGIAN: [0, 1, 3, 5, 7, 8, 10]}
DRONE = 4095                         # DECAY at maximum: no decay


def note_hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def cents(f, ref):
    return 1200 * math.log2(f / ref)


def f0(x):
    """Frequency from interpolated upward zero crossings (for clean, periodic signals)."""
    m = sum(x) / len(x)
    t = [i + (m - a) / (b - a) for i, (a, b) in enumerate(zip(x, x[1:])) if a < m <= b]
    return SR * (len(t) - 1) / (t[-1] - t[0]) if len(t) > 2 else float('nan')


def env(x, w=480):
    return [max(abs(v) for v in x[i:i + w]) for i in range(0, len(x) - w + 1, w)]


def t60(x):
    """T60 (s) extrapolated from the decay slope after the peak."""
    e = env(x)
    pk = max(e)
    ip = e.index(pk)
    pts = [(i * 0.01, 20 * math.log10(v / pk)) for i, v in enumerate(e[ip:]) if v > pk * 1e-3]
    pts = [p for p in pts if p[1] < -3] or pts
    n = len(pts)
    mx, my = sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n
    slope = sum((p[0] - mx) * (p[1] - my) for p in pts) / (sum((p[0] - mx) ** 2 for p in pts) or 1)
    return -60 / slope if slope < 0 else float('inf')


def tone_for_step(step, steps):
    return round(step / steps * 4095)


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestZibens(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = Image.load(require_image('v1.3.0'))
        cls.sym = Symbols(SYMBOLS_V130)
        cls.tmp = tempfile.mkdtemp(prefix='pk-zb-')
        cls.img, p = build_patched(cls.stock, ['voice_map:bank', 'zibens'], cls.tmp + '/a')
        cls.syms = p.cave_symbols

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- helpers -------------------------------------------------------------------------
    def machine(self, out=0):
        """Booted M7 with ZIBENS on `out` (map value 4 = voices.json 5)."""
        e = verify.boot(self.img, self.sym)
        m = [0, 1, 2, 3]
        m[out] = 4
        e.send(3, 4, bytes(m))
        e.pump()
        e.audio(960)            # let the mute-fade gain settle (it starts at 0 after boot)
        return e

    def play(self, e, params, algo=PENT, mode=SINE, note=36, vel=127, n=4800, out=0, trig=True):
        voices = [{'params': [2048] * 4} for _ in range(4)]
        voices[out] = {'params': list(params), 'algo': algo, 'mode': mode}
        e.send_voice_state(voices)
        e.pump()
        if trig:
            am = [(0, 0)] * 4
            am[out] = (algo, mode)
            e.send_triggers([o == out for o in range(4)], am, vel, note)
        return e.audio(n)[out]

    def pitch(self, tone, algo=PENT, note=36, e=None):
        e = e or self.machine()
        x = self.play(e, [tone, DRONE, 0, 0], algo=algo, note=note, n=4800)
        return f0(x[960:])

    # -- wiring ---------------------------------------------------------------------------
    def test_remap_to_zibens_and_back(self):
        e = self.machine(2)
        self.assertEqual(e.class_of(e.slot(2)), 'cZibens')
        self.assertEqual([e.class_of(e.slot(o)) for o in (0, 1, 3)], ['cFirstSlot', 'cSecondSlot', 'cFourthSlot'])
        self.assertGreater(max(map(abs, self.play(e, [2048, 2048, 0, 0], out=2))), 1000)
        e.send(3, 4, bytes([0, 1, 2, 3]))
        e.pump()
        self.assertEqual(e.class_of(e.slot(2)), 'cThirdSlot')

    def test_voices_json_name_selects_zibens(self):
        """M4: "zibens" in voices.json -> map message -> M7 runs ZIBENS on that output."""
        s4 = Symbols(SYMBOLS_V130.replace('-m7.json', '-m4.json'))
        sd = {'voices.json': b'{"voice1": "voice1", "voice2": "voice4", "voice3": "zibens"}'}
        e4 = M4Emu(self.img.segment('m4').data, s4, self.img.segment('m7').data, sd=sd).boot()
        e4.stub(s4.fn['load_samples'], lambda emu, *a: 0)
        e4.call(self.syms['m4']['pk4_load_samples'], 0, max_insns=50_000_000)
        m = [p for t, p in e4.sent(3) if t == 4][0]
        self.assertEqual(list(m), [0, 3, 4, 3])
        e = verify.boot(self.img, self.sym)
        e.send(3, 4, m)
        e.pump()
        self.assertEqual([e.class_of(e.slot(o)) for o in range(4)],
                         ['cFirstSlot', 'cFourthSlot', 'cZibens', 'cFourthSlot'])

    def test_needs_voice_map(self):
        with self.assertRaises(PatchError):
            build_patched(self.stock, ['zibens'], self.tmp + '/b')

    def test_unknown_engine_number_means_stock(self):
        img, _ = build_patched(self.stock, ['voice_map:bank'], self.tmp + '/c')   # no zibens
        e = verify.boot(img, self.sym)
        e.send(3, 4, bytes([4, 1, 2, 3]))
        e.pump()
        self.assertEqual(e.class_of(e.slot(0)), 'cFirstSlot')

    def test_stock_outputs_unchanged(self):
        """With the stock map, every output/algo/mode renders exactly like stock."""
        bad = [r for r in verify.compare_to_stock(self.stock, self.img, self.sym) if not r[4]]
        self.assertEqual(bad, [])

    # -- pitch ----------------------------------------------------------------------------
    def test_scale_steps(self):
        for algo, sc in SCALES.items():
            steps = 4 * len(sc)
            for step in (0, 1, len(sc) - 1, len(sc) + 2, steps):
                with self.subTest(scale=algo, step=step):
                    semis = 12 * (step // len(sc)) + sc[step % len(sc)]
                    f = self.pitch(tone_for_step(step, steps), algo)
                    self.assertLess(abs(cents(f, note_hz(24 + semis))), 3)

    def test_midi_note_transposes(self):
        ref = self.pitch(tone_for_step(5, 20))
        for note, st in ((24, -12), (48, 12), (60, 24), (43, 7)):
            with self.subTest(note=note):
                self.assertLess(abs(cents(self.pitch(tone_for_step(5, 20), note=note), ref) - 100 * st), 3)

    def test_note_zero_keeps_previous_note(self):
        e = self.machine()
        self.play(e, [0, DRONE, 0, 0], note=48)
        x = self.play(e, [0, DRONE, 0, 0], note=0)
        self.assertLess(abs(cents(f0(x[960:]), note_hz(36))), 3)

    def test_tone_steps_without_glide_and_holds_against_jitter(self):
        e = self.machine()
        steps = 20
        centre = tone_for_step(8, steps)
        self.play(e, [centre, DRONE, 0, 0], n=2400)
        for jitter in (-40, 40):                             # ~1% of the knob
            x = self.play(e, [centre + jitter, DRONE, 0, 0], trig=False, n=2400)
            self.assertLess(abs(cents(f0(x[480:]), note_hz(24 + 19))), 3, 'jitter must not flip the note')
        x = self.play(e, [tone_for_step(9, steps), DRONE, 0, 0], trig=False, n=2400)
        self.assertLess(abs(cents(f0(x[480:]), note_hz(24 + 22))), 3, 'next step, no glide')

    # -- sound ------------------------------------------------------------------------------
    def test_waveforms(self):
        e = self.machine()
        out = {m: self.play(e, [tone_for_step(10, 20), DRONE, 0, 0], mode=m, n=4800)[960:] for m in (SAW, SQUARE, SINE)}
        self.assertNotEqual(out[SAW], out[SQUARE])
        self.assertNotEqual(out[SQUARE], out[SINE])
        # sine: almost no harmonics; square: almost no even harmonics
        for m, x in out.items():
            self.assertGreater(max(map(abs, x)), 1500, f'mode {m} audible')

    def test_param2_changes_each_waveform(self):
        e = self.machine()
        for m in (SAW, SQUARE, SINE):          # saw: resonance, square: pulse width, sine: fold
            with self.subTest(mode=m):
                a = self.play(e, [tone_for_step(10, 20), DRONE, 0, 0], mode=m, n=2400)
                b = self.play(e, [tone_for_step(10, 20), DRONE, 0, 4095], mode=m, n=2400)
                self.assertNotEqual(a[480:], b[480:])

    def test_square_and_sine_skip_the_filter(self):
        e = self.machine()
        sq = self.play(e, [tone_for_step(10, 20), DRONE, 0, 0], mode=SQUARE, n=4800)[960:]
        pk = max(map(abs, sq))
        self.assertGreater(sum(1 for v in sq if abs(v) > 0.95 * pk) / len(sq), 0.9, 'flat-topped square')
        si = self.play(e, [tone_for_step(10, 20), DRONE, 0, 0], mode=SINE, n=4800)[960:]
        pk = max(map(abs, si))
        rms = (sum(v * v for v in si) / len(si)) ** 0.5
        self.assertAlmostEqual(rms / pk, 2 ** -0.5, delta=0.02, msg='pure sine (crest factor sqrt 2)')

    def test_decay_follows_the_stock_curve(self):
        # geometric mean of the stock Simple and Wavetable voices, measured (T60, s)
        stock = {0: (0.079 * 0.074) ** .5, 1024: (0.346 * 0.428) ** .5, 2048: (1.429 * 2.711) ** .5}
        for d, want in stock.items():
            with self.subTest(decay=d):
                x = self.play(self.machine(), [tone_for_step(10, 20), d, 0, 0], n=24000)
                self.assertLess(abs(math.log(t60(x) / want)), math.log(1.3))
        x = self.play(self.machine(), [tone_for_step(10, 20), DRONE, 0, 0], n=24000)
        e_ = env(x)
        self.assertGreater(min(e_[5:]), 0.95 * max(e_), 'maximum DECAY holds')

    def test_attack(self):
        def peak_ms(p1):
            x = self.play(self.machine(), [tone_for_step(10, 20), DRONE, p1, 0], n=4800)
            e_ = env(x, 48)
            return next(i for i, v in enumerate(e_) if v >= 0.98 * max(e_)) * 1.0
        self.assertLess(peak_ms(0), 3)
        self.assertTrue(20 < peak_ms(2048) < 45, peak_ms(2048))      # ~31 ms

    def test_velocity_is_linear(self):
        peaks = {v: max(map(abs, self.play(self.machine(), [tone_for_step(10, 20), DRONE, 0, 0], vel=v, n=2400)))
                 for v in (127, 64)}
        self.assertAlmostEqual(peaks[64] / peaks[127], 64 / 127, delta=0.03)

    def test_mute_fades_like_a_stock_slot(self):
        e = self.machine()
        self.play(e, [tone_for_step(10, 20), DRONE, 0, 0], n=960)
        voices = [{'params': [2048] * 4} for _ in range(4)]
        voices[0] = {'params': [tone_for_step(10, 20), DRONE, 0, 0], 'algo': PENT, 'mode': SINE, 'mute': 1}
        e.send_voice_state(voices)
        e.pump()
        x = e.audio(1440)[0]
        self.assertGreater(max(map(abs, x[:96])), 500, 'fades, not cuts')
        self.assertEqual(max(map(abs, x[720:])), 0, 'silent ~10 ms after mute')

    def test_extremes_stay_bounded(self):
        e = self.machine()
        for m in (SAW, SQUARE, SINE):
            for params in ([4095, DRONE, 0, 4095], [0, DRONE, 0, 4095], [4095, 0, 4095, int(0.6 * 4095)]):
                with self.subTest(mode=m, params=params):
                    x = []
                    for _ in range(4):
                        x += self.play(e, params, mode=m, n=1200)
                    self.assertLess(max(map(abs, x)), 32767, 'no clipping / runaway')

    def test_silent_after_short_decay(self):
        x = self.play(self.machine(), [tone_for_step(10, 20), 0, 0, 0], n=24000)
        self.assertEqual(max(map(abs, x[-4800:])), 0)

    def test_cpu(self):
        e = self.machine()
        self.play(e, [tone_for_step(12, 20), DRONE, 0, 4095], mode=SAW, n=960)    # sounding, detuned
        base = verify.boot(self.img, self.sym)
        self.play(base, [tone_for_step(12, 20), DRONE, 0, 4095], mode=SAW, n=960)
        counts = []
        for m in (e, base):
            m.count_insns(True)
            m.insn_count = 0
            m.audio(960)
            counts.append(m.insn_count / 960)
            m.count_insns(False)
        extra = counts[0] - counts[1]
        print(f'\nZIBENS: ~{extra:.0f} instructions per sample more than stock output 1')
        self.assertLess(extra, 800)
