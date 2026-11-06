"""Akords: the settings from the M4 (preset, chord type, scale, root), MODE's filter and
the PLAY knobs."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
from ak_rig import *  # noqa: E402,F401,F403


def brightness(seg):
    d = [y - x for x, y in zip(seg, seg[1:])]
    return (sum(v * v for v in d) / len(d)) ** .5 / ((sum(v * v for v in seg) / len(seg)) ** .5 or 1)


@unittest.skipUnless(HAVE_GCC, 'arm-none-eabi-gcc not installed')
class TestAkordsSettings(AkordsCase):
    # -- the settings message -------------------------------------------------------------
    def test_the_message_sets_preset_chord_scale_root(self):
        for preset, chord, scale, root in ((3, 'quartal', 4, 7), (10, 'power', 10, 11), (0, 'dia', 0, 0)):
            with self.subTest(preset=preset, chord=chord, scale=scale, root=root):
                e = self.machine(preset=preset, chord=chord, scale=scale, root=root)
                self.assertEqual(self.info(e)['set'], [preset, CHORDS.index(chord), scale, ROOTS.index(root)])

    def test_each_output_takes_its_own_row(self):
        e = self.machine(out=2)
        self.settings(e, [[1, 1, 1, 1], [2, 2, 2, 2], [7, 4, 3, 5], [9, 9, 9, 9]])
        self.assertEqual(self.info(e)['set'], [7, 4, 3, 5])

    def test_out_of_range_values_are_0(self):
        e = self.machine()
        self.settings(e, [[14, 10, 11, 12]] + [[0] * 4] * 3)
        self.assertEqual(self.info(e)['set'], [0, 0, 0, 0])
        self.settings(e, [[13, 9, 10, 11]] + [[0] * 4] * 3)
        self.assertEqual(self.info(e)['set'], [13, 9, 10, 11])

    def test_settings_survive_rebuilding_the_engine(self):
        """voice-map rebuilds an engine when a voice comes back to it: the settings stay."""
        e = self.machine(preset=6, chord='dia9_s', scale=2, root=4)
        remap(e, [0, 1, 2, 3], self.cave, MSG_VOICE_MAP)
        remap(e, [4, 1, 2, 3], self.cave, MSG_VOICE_MAP)
        self.state(e, e.knobs, *e.sw)
        self.assertEqual(self.info(e)['set'], [6, CHORDS.index('dia9_s'), 2, ROOTS.index(4)])

    # -- MODE: the filter -----------------------------------------------------------------
    def test_the_preset_keeps_its_own_filter_until_mode_moves(self):
        """Air (a high-pass preset) chosen with MODE at the top (24 dB low-pass) stays
        high-pass; moving MODE then sets the filter, as the switch says."""
        air = self.machine(preset=10)
        same = self.machine(preset=10)
        self.assertEqual(self.play(air, 2048, n=4800), self.play(same, 2048, n=4800), 'its own filter')
        lp = self.machine(preset=10)
        self.state(lp, lp.knobs, POS2, HP)
        self.state(lp, lp.knobs, POS2, LP24)                     # MODE moved: now low-pass
        a = self.play(air, 2048, n=4800)[960:]
        b = self.play(lp, 2048, n=4800)[960:]
        self.assertGreater(brightness(a), 1.5 * brightness(b), 'high-pass brighter than low-pass')

    def test_a_new_preset_goes_back_to_its_own_filter(self):
        e = self.machine(preset=0)
        self.state(e, e.knobs, POS2, HP)                         # MODE moved: high-pass
        hp = self.play(e, 2048, n=4800)[960:]
        self.setup(e, 1, 'dia', MAJOR, 0)
        self.setup(e, 0, 'dia', MAJOR, 0)                        # chosen again: its own (LP24)
        own = self.play(e, 2048, n=4800)[960:]
        self.assertGreater(brightness(hp), 1.5 * brightness(own))

    def test_mode_changes_the_sounding_chord(self):
        e = self.machine(preset=1)
        self.play(e, 2048, decay=DRONE, n=24000)
        a = self.play(e, 2048, trig=False, n=4800)[960:]
        self.state(e, e.knobs, POS2, HP)
        b = self.play(e, 2048, trig=False, n=9600)[4800:]
        self.assertGreater(brightness(b), 1.5 * brightness(a))

    def test_formant_vowels_move_with_param1(self):
        """Formant: PARAM1 sweeps the vowel, dark (U: F2 ~870 Hz) to bright (I: F2 ~2290 Hz)."""
        def bands(cut):
            m = self.machine(preset=1, chord='power')
            self.state(m, m.knobs, POS2, FORMANT)
            self.turn(m, FORMANT, cut, 2048, algo=POS2)
            x = self.play(m, tune_for(0, MAJOR), n=24000)[4800:]
            self.assertGreater(max(map(abs, x)), 1000)
            f0, lo, hi = note_hz(36), 0, 0
            for h in range(1, 55):                              # the C2 power chord's harmonics
                g = goertzel(x, f0 * h)
                lo += g if 700 <= f0 * h < 1100 else 0          # U's F2
                hi += g if 1900 <= f0 * h < 2700 else 0         # I's F2
            return 10 * math.log10(hi / lo)
        self.assertGreater(bands(4095), bands(0) + 10)

    def test_formant_shift_in_resonances_place(self):
        """Formant, ALGO 1: PARAM2 shifts the formants (down: a bigger voice, up: smaller)."""
        def high_share(p2):
            m = self.machine(preset=11, chord='power')          # Choir: its own filter is formant
            self.turn(m, PLAY, 2048, p2, algo=POS1)
            x = self.play(m, tune_for(0, MAJOR), n=48000)[24000:]
            f0, lo, hi = note_hz(36), 0, 0
            for h in range(1, 55):
                g = goertzel(x, f0 * h)
                lo += g if f0 * h < 1200 else 0
                hi += g if f0 * h >= 1200 else 0
            return 10 * math.log10(hi / lo)
        self.assertGreater(high_share(4095), high_share(0) + 6)

    # -- the PLAY knobs -------------------------------------------------------------------
    def test_param2_keeps_its_value_until_it_moves_after_algo_changes(self):
        a = self.machine(preset=0)
        b = self.machine(preset=0)
        for m in (a, b):
            self.turn(m, PLAY, 2048, 4095, algo=POS1)            # resonance up
        self.state(a, a.knobs, POS3, PLAY)                       # ALGO 3: PARAM2 = attack, unmoved
        self.state(a, a.knobs, POS1, PLAY)                       # back to resonance, unmoved
        self.assertEqual(self.play(a, 2048, n=4800), self.play(b, 2048, n=4800))

    def test_play_knobs_are_relative_to_the_preset(self):
        """12 o'clock is the preset's own sound; PARAM1 then opens or closes from there."""
        mid = self.machine(preset=0)
        self.turn(mid, PLAY, 2048, 2048, algo=POS1)
        fresh = self.machine(preset=0)                          # PLAY values untouched
        self.assertEqual(self.play(mid, 2048, n=4800), self.play(fresh, 2048, n=4800))

    def press_preset(self, e, preset):
        """The page's preset press: the settings, then the output's bit (all the preset again)."""
        rows = [[0, 0, 0, 0] for _ in range(4)]
        rows[e.out] = [preset, 0, MAJOR, 0]
        e.send(2, MSG_AKORDS, bytes(x for r in rows for x in r) + bytes([1 << e.out]))
        e.audio(32)

    def test_pressing_a_preset_brings_back_all_its_sound(self):
        """The knobs' tweaks and MODE's filter go; the knobs set again once they move."""
        e = self.machine(preset=0)
        fresh = self.machine(preset=0)
        self.turn(e, PLAY, 300, 4095, algo=POS1)                # cutoff down, resonance up
        self.state(e, e.knobs, POS1, POS3)                      # MODE: formant
        self.assertNotEqual(self.play(e, 2048, n=4800), self.play(fresh, 2048, n=4800))
        e, fresh = self.machine(preset=0), self.machine(preset=0)
        self.turn(e, PLAY, 300, 4095, algo=POS1)
        self.state(e, e.knobs, POS1, POS3)
        self.state(fresh, fresh.knobs, POS1, PLAY)
        self.press_preset(e, 0)                                 # the same preset, pressed again
        self.assertEqual(self.play(e, 2048, n=4800), self.play(fresh, 2048, n=4800))
        k = list(e.knobs)
        k[2] = 300 + 200                                        # PARAM1 moves: it sets again
        self.state(e, k, *e.sw)
        self.assertNotEqual(self.play(e, 2048, n=4800), self.play(fresh, 2048, n=4800))

    def test_a_kit_load_keeps_the_knobs(self):
        """The settings without a press (a kit load): the knobs' values stay."""
        e = self.machine(preset=0)
        ref = self.machine(preset=0)
        for m in (e, ref):
            self.turn(m, PLAY, 300, 4095, algo=POS1)
        self.setup(e, 0, 'dia', MAJOR, 0)
        self.assertEqual(self.play(e, 2048, n=4800), self.play(ref, 2048, n=4800))

    def test_play_mode_knobs_change_the_sound(self):
        e = self.machine(preset=0)
        dull = self.machine(preset=0)
        for m, cut in ((e, 4095), (dull, 300)):
            self.turn(m, PLAY, cut, 0, algo=POS1)
        a = self.play(e, 2048, n=4800)[960:]
        b = self.play(dull, 2048, n=4800)[960:]
        self.assertGreater(brightness(a), 2 * brightness(b), 'PARAM1 = cutoff')
