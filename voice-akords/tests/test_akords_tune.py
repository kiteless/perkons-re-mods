"""Akords: TUNE and GATE arriving around a trigger, smooth voicing, the chord sounding."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
from ak_rig import *  # noqa: E402,F401,F403


@unittest.skipUnless(HAVE_GCC, 'arm-none-eabi-gcc not installed')
class TestAkordsTune(AkordsCase):
    def test_tune_arriving_after_the_trigger_sets_the_chord(self):
        """The M4 can send a step's TUNE a moment after its trigger: the new chord follows."""
        e = self.machine()
        self.play(e, tune_for(0, MAJOR), n=2400)
        self.play(e, tune_for(0, MAJOR), n=64)                  # the next step's trigger ...
        self.play(e, tune_for(3, MAJOR), trig=False, n=2400)    # ... then its TUNE
        self.assertEqual(self.info(e)['slots'][0]['notes'], [41, 45, 48])

    def test_tune_just_before_the_trigger_leaves_the_ringing_chord(self):
        e = self.machine()
        self.play(e, tune_for(0, MAJOR), n=4800)
        self.play(e, tune_for(3, MAJOR), trig=False, n=192)     # the next step's TUNE first
        self.play(e, tune_for(3, MAJOR), n=4800)
        self.assertEqual(self.info(e)['slots'][0]['notes'], [41, 45, 48])

    def test_tune_retunes_the_newest_chord_as_on_zibens(self):
        """Turning TUNE retunes the sounding chord at any time."""
        e = self.machine()
        self.play(e, tune_for(0, MAJOR), n=4800)                # C
        self.play(e, tune_for(3, MAJOR), n=4800)                # F
        self.play(e, tune_for(4, MAJOR), trig=False, n=4800)    # turned to G, 0.1 s on
        self.assertEqual(self.info(e)['slots'][0]['notes'], [43, 47, 50])

    def test_gate_arriving_after_the_trigger_sets_the_gate(self):
        e = self.machine(preset=8)
        self.play(e, 2048, decay=DRONE, n=64)
        x = self.play(e, 2048, decay=gate_knob(0.1), trig=False, n=24000)
        self.assertEqual(max(map(abs, x[-4800:])), 0, 'released after its (late) 0.1 s gate')

    def test_smooth_types_take_the_nearest_inversion(self):
        e = self.machine(chord='dia_s')
        self.play(e, tune_for(0, MAJOR), n=2400)                # C E G
        self.play(e, tune_for(3, MAJOR), n=2400)                # F: C F A, not F A C
        self.assertEqual(self.info(e)['last'], [36, 41, 45])
        self.play(e, tune_for(4, MAJOR), n=2400)                # G: D G B (each note up a step)
        self.assertEqual(self.info(e)['last'], [38, 43, 47])

    def test_smooth_restarts_in_root_position_after_silence(self):
        e = self.machine(chord='dia_s')
        self.play(e, tune_for(0, MAJOR), decay=0, n=960)
        e.audio(19200)
        self.play(e, tune_for(3, MAJOR), decay=0, n=64)
        self.assertEqual(self.info(e)['last'], [41, 45, 48])

    def test_smooth_never_drifts(self):
        e = self.machine(chord='dia_s')
        for _ in range(4):
            for step in (0, 3, 4, 0, 5, 1, 4):
                self.play(e, tune_for(step, MAJOR), n=1440)
                root = 36 + degree(MAJOR, step)
                self.assertTrue(all(root - 12 <= n <= root + 24 for n in self.info(e)['last']))

    def test_chord_notes_sound(self):
        e = self.machine(preset=8)                              # Organ: triangle + sine
        x = self.play(e, tune_for(7, MAJOR), n=52800)[4800:]    # C3 E3 G3, 1 s analysed
        for n in (48, 52, 55):
            with self.subTest(note=n):
                on = goertzel(x, note_hz(n))
                for off in (n - 1, n + 1):                      # the semitones either side
                    self.assertGreater(on, 50 * goertzel(x, note_hz(off)))
