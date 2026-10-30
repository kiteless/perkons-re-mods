"""Eight-lanes: the stock core running 8 lanes (state + notes in AXI)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'harness'))
from eight import eight_lanes, lane_fired, lane_note  # noqa: E402
from seq_harness import SeqHarness  # noqa: E402
from unicorn import UC_HOOK_MEM_WRITE  # noqa: E402


class TestEightLaneCore(unittest.TestCase):
    def run_steps(self, h, n):
        got = []
        for i in range(n):
            h.step()
            trig = [h.decode_trigger(p) for t, p in h.sent(2) if t == 0]
            lanes = [(lane, lane_note(h, lane)) for lane in range(4, 8) if lane_fired(h, lane)]
            got.append((i, trig, lanes))
        return got

    def test_lanes_fire_with_their_notes_and_velocities(self):
        h = eight_lanes(SeqHarness())
        h.set_step(5, 2, 60, 90)
        h.set_step(7, 3, 72, 50)
        h.set_step(4, 5, 30, 127)
        h.play()
        lanes = {i: ln for i, _, ln in self.run_steps(h, 8) if ln}
        self.assertEqual(lanes, {2: [(5, (60, 90))], 3: [(7, (72, 50))], 5: [(4, (30, 127))]})

    def test_tracks_1_to_4_unchanged_and_lanes_never_reach_the_m7(self):
        h = eight_lanes(SeqHarness())
        h.set_step(0, 2, 40)
        h.set_step(4, 2, 50)
        h.play()
        trig = [t for _, t, _ in self.run_steps(h, 4) if t]
        self.assertEqual(trig, [[[(0, 40)], []]])

    def test_no_writes_past_the_stock_4_track_arrays(self):
        h = eight_lanes(SeqHarness())
        bad = []
        ok = ((0x100000ec, 0x1000011c), (0x10001d40, 0x10001d5c))

        def hook(uc, acc, addr, size, val, _):
            if (0x100000e0 <= addr < 0x10000180 or 0x10001d40 <= addr < 0x10001d80) and \
                    not any(lo <= addr < hi for lo, hi in ok):
                bad.append(addr)
        h.e.uc.hook_add(UC_HOOK_MEM_WRITE, hook)
        for lane in range(8):
            h.set_step(lane, lane, 40 + lane)
        h.play()
        self.run_steps(h, 10)
        self.assertEqual(bad, [])


if __name__ == '__main__':
    unittest.main()
