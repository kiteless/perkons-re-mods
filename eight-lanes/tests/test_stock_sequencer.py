"""Eight-lanes: the stock 4-track sequencer as the harness sees it.
The baseline the 8-track build must keep for tracks 1-4.
Run: cd eight-lanes && ../../perkons/.venv/bin/python -m unittest discover -s tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'harness'))
from seq_harness import SeqHarness  # noqa: E402


class TestStockSequencer(unittest.TestCase):
    def test_steps_trigger_the_m7_with_the_step_note(self):
        h = SeqHarness()
        for st, n in ((4, 40), (8, 43)):
            h.set_step(0, st, n, 100)
        h.play()
        got = {s: trig[0] for s, trig, _ in h.run(12)}
        self.assertEqual(got, {4: [(0, 40)], 8: [(0, 43)]})

    def test_single_channel_midi_sends_the_track_trigger_note(self):
        h = SeqHarness()
        h.set_step(2, 3, 50, 64)
        h.play()
        (s, _, midi), = h.run(6)
        self.assertEqual((s, [m.hex() for m in midi]), (3, ['902640', '802600']))

    def test_pattern_loops_at_16_steps(self):
        h = SeqHarness()
        h.set_step(1, 1, 36, 100)
        h.play()
        self.assertEqual([s for s, _, _ in h.run(34)], [1, 17, 33])

    def test_track_count_is_4(self):
        h = SeqHarness()
        self.assertEqual(h.e.r8(h.seq + 3), 4)


if __name__ == '__main__':
    unittest.main()
