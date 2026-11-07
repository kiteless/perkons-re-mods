"""Akords: GATE, drone, attack, a new chord taking over."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
from ak_rig import *  # noqa: E402,F401,F403


@unittest.skipUnless(HAVE_GCC, 'arm-none-eabi-gcc not installed')
class TestAkordsGate(AkordsCase):
    # -- gate, overlap -------------------------------------------------------------------------
    def test_gate_releases(self):
        e = self.machine(preset=8)                              # Organ: sustain .95, release 60 ms
        x = self.play(e, 2048, decay=gate_knob(0.39), n=48000)
        r = rms(x, 2400)
        self.assertGreater(r[6], 0.8 * max(r), 'holds through the gate (at 0.3 s)')
        self.assertEqual(max(map(abs, x[28800:])), 0, 'silent after the gate and release')
        self.assertEqual([s['stage'] for s in self.info(e)['slots']], [0])

    def test_gate_range(self):
        def half_time(decay, n):                # Organ: when it falls to half its level (in n samples)
            r = rms(self.play(self.machine(preset=8), 2048, decay=decay, n=n), 480)
            return next(i for i, v in enumerate(r) if i > 5 and v < 0.5 * max(r)) * 0.01
        self.assertLess(half_time(0, 24000), 0.15)                   # ~0.05 s + release
        t = half_time(3808, 110400)                                  # (rendered to 2.3 s)
        self.assertTrue(1.7 < t < 2.1, t)                            # ~1.85 s at 93%

    def test_decay_acts_on_the_sounding_chords(self):
        """As on voice-zibens, DECAY acts on what is sounding: turned down from drone, the
        droning chord releases."""
        e = self.machine(preset=8)
        self.play(e, tune_for(0, MAJOR), decay=DRONE, n=24000)
        self.play(e, tune_for(3, MAJOR), decay=DRONE, n=24000)
        x = self.play(e, tune_for(3, MAJOR), decay=gate_knob(0.1), trig=False, n=24000)
        self.assertEqual(max(map(abs, x[-4800:])), 0)
        self.assertEqual([s['stage'] for s in self.info(e)['slots']], [0])

    def test_attack_follows_its_knob_while_attacking(self):
        """ALGO 3: a slow attack shortened while it rises (a late lock) takes effect at once."""
        level = []
        for shorten in (False, True):
            e = self.machine(preset=1)                          # Pad
            self.turn(e, PLAY, 2048, 4095, algo=POS3)           # attack 3 s
            self.play(e, 2048, decay=DRONE, n=2400)
            k = list(e.knobs)
            if shorten:
                k[3] = 0                                        # attack 1 ms
            self.state(e, k, *e.sw)
            level.append(max(rms(e.audio(4800)[e.out], 2400)))
        self.assertGreater(level[1], 5 * level[0])

    def test_drone_holds(self):
        e = self.machine(preset=8)
        r = rms(self.play(e, 2048, decay=round(0.96 * 4095), n=144000))   # from 95%
        self.assertGreater(min(r[1:]), 0.85 * max(r))

    def test_a_new_chord_cuts_the_last_without_a_click(self):
        e = self.machine(preset=1)                              # Pad: a long release
        self.play(e, tune_for(0, MAJOR), decay=DRONE, n=4800)
        x = self.play(e, tune_for(3, MAJOR), decay=DRONE, n=4800)
        sl = self.info(e)['slots']
        self.assertEqual([(s['stage'] > 0, s['notes']) for s in sl], [(True, [41, 45, 48])])
        d = [abs(b - a) for a, b in zip(x, x[1:])]
        self.assertLess(max(d[:480]), 2 * max(d[2400:]) + 50, 'no click at the cut')
        for _ in range(4):                                      # fast retriggers: one chord
            self.play(e, tune_for(4, MAJOR), decay=DRONE, n=64)
        self.assertEqual(self.info(e)['slots'][0]['notes'], [43, 47, 50])

    def test_the_next_chord_takes_the_new_preset(self):
        e = self.machine(preset=8)
        self.play(e, tune_for(0, MAJOR), n=960)
        self.setup(e, 1, 'dia', MAJOR, 0)                      # the page chooses Pad
        self.assertEqual(self.info(e)['slots'][0]['preset'], 8, 'the chord playing keeps its own')
        self.play(e, tune_for(3, MAJOR), n=960)
        self.assertEqual(self.info(e)['slots'][0]['preset'], 1)
