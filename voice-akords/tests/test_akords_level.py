"""Akords: velocity, preset levels, mute, extremes, CPU."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
from ak_rig import *  # noqa: E402,F401,F403


@unittest.skipUnless(HAVE_GCC, 'arm-none-eabi-gcc not installed')
class TestAkordsLevel(AkordsCase):
    # -- level ----------------------------------------------------------------------------------
    def test_velocity_is_linear(self):
        peaks = {}
        for v in (127, 64):
            e = self.machine(preset=8)
            peaks[v] = max(map(abs, self.play(e, 2048, vel=v, n=4800)))
        self.assertAlmostEqual(peaks[64] / peaks[127], 64 / 127, delta=0.03)

    def test_presets_peak_alike(self):
        peaks = []
        for p in range(len(PRESETS)):
            e = self.machine(preset=p)
            peaks.append(self.peak(e, 2048))
        self.assertLess(max(peaks) / min(peaks), 1.6, dict(zip(PRESETS, peaks)))

    def test_formant_peaks_like_the_presets(self):
        peaks = []
        for p in (0, 1, 8, 10):
            e = self.machine(preset=p)
            ref = self.peak(self.machine(preset=p), 2048)
            self.state(e, e.knobs, POS2, FORMANT)
            peaks.append(self.peak(e, 2048) / ref)
        self.assertTrue(all(0.5 < r < 2.0 for r in peaks), dict(zip(('Bass', 'Pad', 'Organ', 'Air'), peaks)))

    def test_mute_fades_like_a_stock_slot(self):
        e = self.machine()
        self.play(e, 2048, n=960)
        self.state(e, e.knobs, *e.sw, mute=1)
        x = e.audio(1440)[0]
        self.assertGreater(max(map(abs, x[:96])), 500, 'fades, not cuts')
        self.assertEqual(max(map(abs, x[720:])), 0, 'silent ~10 ms after mute')

    def test_extremes_stay_bounded(self):
        for p in range(len(PRESETS)):
            e = self.machine(preset=p, chord='quartal')
            x = []
            for mode in (LP24, HP, FORMANT):
                self.state(e, e.knobs, POS2, mode)
                for algo in (POS1, POS2, POS3):
                    self.turn(e, mode, 4095, 4095, algo=algo)
                for tune in (0, 4095, 0, 4095):
                    x += self.play(e, tune, decay=DRONE, n=2400)
            with self.subTest(preset=PRESETS[p]):
                self.assertLessEqual(max(map(abs, x)), 9001, 'the limiter holds the peaks')

    def test_the_level_follows_drive(self):
        """+3 dB with no DRIVE, as before at half, -3 dB at full; smoothly."""
        def level(d):
            e = self.machine(preset=8)
            self.drive(e, d)
            x = self.play(e, tune_for(14, MAJOR), decay=DRONE, n=19200)[9600:]
            return rms(x, len(x))[0], e
        mid, _ = level(128)
        for d, db in ((0, 3.0), (64, 1.5), (192, -1.5), (255, -3.0)):
            with self.subTest(drive=d):
                x, _ = level(d)
                self.assertAlmostEqual(20 * math.log10(x / mid), db, delta=0.15)
        e = self.machine(preset=8)
        self.play(e, tune_for(14, MAJOR), decay=DRONE, n=9600)
        self.drive(e, 255)
        x = e.audio(1920)[e.out]
        steps = [abs(b - a) for a, b in zip(x, x[1:])]
        y = self.machine(preset=8)
        self.play(y, tune_for(14, MAJOR), decay=DRONE, n=9600)
        ref = y.audio(1920)[y.out]
        self.assertLess(max(steps), 1.2 * max(abs(b - a) for a, b in zip(ref, ref[1:])), 'no step')

    def test_cpu(self):
        worst = 0
        for p, mode in ((1, PLAY), (6, PLAY), (7, PLAY), (10, PLAY), (7, FORMANT)):   # cut: two chords
            e = self.machine(preset=p, chord='dia9')                                    # 5 notes
            if mode != PLAY:
                self.state(e, e.knobs, POS2, HP)
                self.state(e, e.knobs, POS2, mode)
            self.play(e, tune_for(0, MAJOR), n=960)
            self.play(e, tune_for(3, MAJOR), n=960)
            base = verify.boot(self.img, self.sym)
            v = [{'params': [2048] * 4} for _ in range(4)]
            v[0] = {'params': [2048, DRONE, 0, 4095], 'algo': POS1, 'mode': POS1}
            base.send_voice_state(v)
            base.pump()
            base.send_triggers([1, 0, 0, 0], [(POS1, POS1)] + [(0, 0)] * 3)
            base.audio(960)
            counts = []
            for m in (e, base):
                m.count_insns(True)
                m.insn_count = 0
                m.audio(960)
                counts.append(m.insn_count / 960)
                m.count_insns(False)
            worst = max(worst, counts[0] - counts[1])
        print(f'\nAkords: ~{worst:.0f} instructions per sample more than stock output 1')
        self.assertLess(worst, 800)


if __name__ == '__main__':
    unittest.main()
