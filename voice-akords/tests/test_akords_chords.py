"""Akords: the chords each scale and chord type give."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
from ak_rig import *  # noqa: E402,F401,F403


@unittest.skipUnless(HAVE_GCC, 'arm-none-eabi-gcc not installed')
class TestAkordsChords(AkordsCase):
    def test_diatonic_triads_in_c_major(self):
        names = [[36, 40, 43], [38, 41, 45], [40, 43, 47], [41, 45, 48], [43, 47, 50], [45, 48, 52],
                 [47, 50, 53], [48, 52, 55]]                    # C Dm Em F G Am Bdim C
        for step, want in enumerate(names):
            with self.subTest(step=step):
                self.assertEqual(self.chord_of(step), want)

    def test_diatonic_sevenths_and_ninths_have_every_note(self):
        self.assertEqual(self.chord_of(0, chord='dia7'), [36, 40, 43, 47])     # Cmaj7: C E G B
        self.assertEqual(self.chord_of(1, chord='dia7'), [38, 41, 45, 48])     # Dm7: D F A C
        self.assertEqual(self.chord_of(4, chord='dia7'), [43, 47, 50, 53])     # G7: G B D F
        self.assertEqual(self.chord_of(0, chord='dia9'), [36, 40, 43, 47, 50])  # Cmaj9: + D
        self.assertEqual(self.chord_of(1, chord='dia9'), [38, 41, 45, 48, 52])  # Dm9: + E
        self.assertEqual(self.chord_of(4, chord='dia9'), [43, 47, 50, 53, 57])  # G9: + A

    def test_fixed_shapes_are_full_chords(self):
        self.assertEqual(self.chord_of(0, chord='quartal'), [36, 41, 46, 51])   # C F Bb Eb
        self.assertEqual(self.chord_of(0, chord='power'), [36, 43, 48])

    def test_a_progression_offset_moves_the_chord_in_the_scale(self):
        e = self.machine(chord='dia', scale=MINOR)
        e.send(2, MSG_AKORDS_PROG, bytes([5] * 4))              # VI
        self.play(e, tune_for(0, MINOR), n=64)
        self.assertEqual(self.info(e)['last'], model_chord(5, MINOR))      # Ab major in C minor
        e.send(2, MSG_AKORDS_PROG, bytes([2] * 4))              # III: from the next chord
        e.audio(4800)
        self.assertEqual(self.info(e)['last'], model_chord(5, MINOR), 'the chord playing keeps its own')
        self.play(e, tune_for(0, MINOR), n=64)
        self.assertEqual(self.info(e)['last'], model_chord(2, MINOR))
        e.send(2, MSG_AKORDS_PROG, bytes([0] * 4))
        self.play(e, tune_for(1, MINOR), n=64)
        self.assertEqual(self.info(e)['last'], model_chord(1, MINOR), 'off: TUNE alone')

    def test_smooth_voicing_with_four_and_five_notes(self):
        e = self.machine(chord='dia7_s')
        self.play(e, tune_for(0, MAJOR), n=2400)                # Cmaj7 C E G B
        self.play(e, tune_for(3, MAJOR), n=2400)                # Fmaj7 nearest: C E F A
        self.assertEqual(self.info(e)['last'], [36, 40, 41, 45])
        e = self.machine(chord='dia9_s')
        self.play(e, tune_for(0, MAJOR), n=2400)                # Cmaj9 C E G B D
        self.play(e, tune_for(4, MAJOR), n=2400)                # G9 G B D F A: nearest voicing
        last = self.info(e)['last']
        self.assertEqual(sorted(n % 12 for n in last), [2, 5, 7, 9, 11])
        self.assertLess(max(last) - min(last), 15, 'kept close, not spread')

    def test_harmonic_minor_stacks_its_own_thirds(self):
        self.assertEqual(self.chord_of(6, scale=HARM_MINOR), [47, 50, 53])   # B dim
        self.assertEqual(self.chord_of(2, scale=HARM_MINOR), [39, 43, 47])   # Eb aug

    def test_root_and_transposition(self):
        self.assertEqual(self.chord_of(0, scale=MINOR, root=9), [45, 48, 52])      # A minor
        self.assertEqual(self.chord_of(0, root=3), [39, 43, 46])                   # E-flat major
        self.assertEqual(self.chord_of(0, root=4), [40, 44, 47])                   # E major
        self.assertEqual(self.chord_of(0, note=48), [48, 52, 55])                  # +12

    def test_phrygian_dominant(self):
        self.assertEqual(self.chord_of(0, scale=PHRYG_DOM), [36, 40, 43])          # C
        self.assertEqual(self.chord_of(1, scale=PHRYG_DOM), [37, 41, 44])          # Db
        self.assertEqual(self.chord_of(3, scale=PHRYG_DOM), [41, 44, 48])          # Fm

    def test_power_plain_and_smooth(self):
        e = self.machine(chord='power')
        self.play(e, tune_for(0, MAJOR), n=2400)
        self.play(e, tune_for(3, MAJOR), n=2400)                # F: F C F, in root position
        self.assertEqual(self.info(e)['last'], [41, 48, 53])
        e = self.machine(chord='power_s')
        self.play(e, tune_for(0, MAJOR), n=2400)                # C G C
        self.play(e, tune_for(3, MAJOR), n=2400)                # F: C F C (the fifth below)
        self.assertEqual(self.info(e)['last'], [36, 41, 48])
        self.play(e, tune_for(4, MAJOR), n=2400)                # G: D G D
        self.assertEqual(self.info(e)['last'], [38, 43, 50])
        self.play(e, tune_for(0, MAJOR), n=2400)                # C: C G C again (no doubled notes)
        self.assertEqual(self.info(e)['last'], [36, 43, 48])

    def test_chromatic_falls_back_to_fixed_shapes(self):
        self.assertEqual(self.chord_of(5, scale=CHROMATIC), [41, 45, 48])
        self.assertEqual(self.chord_of(5, scale=CHROMATIC, chord='dia7'), [41, 44, 48, 51])        # Fm7
        self.assertEqual(self.chord_of(5, scale=CHROMATIC, chord='dia9'), [41, 44, 48, 51, 55])    # Fm9

    def test_every_scale_and_chord_type(self):
        """Root position matches the model for every scale and chord type. The plain types
        (CHORDS[::2]) don't depend on the chord before (only the smooth ones do), so the
        chords follow each other without a silence between."""
        for scale in range(11):
            for chord in CHORDS[::2]:
                e = self.machine(scale=scale, chord=chord)
                for step in (0, 1, 3, len(SCALES[scale]) + 2):
                    with self.subTest(scale=scale, chord=chord, step=step):
                        self.play(e, tune_for(step, scale), decay=0, n=64)
                        self.assertEqual(self.info(e)['last'], model_chord(step, scale, 0, chord))
