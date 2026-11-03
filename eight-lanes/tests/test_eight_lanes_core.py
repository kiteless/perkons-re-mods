"""Eight-lanes: the stock core running 8 tracks (states and note records in STORE)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
from el_rig import SYM, lanes_rig  # noqa: E402
from unicorn import UC_HOOK_MEM_WRITE  # noqa: E402

NOTE_REC, PENDING = 0xc, 6          # per-track note record, pending-trigger entry (bytes)


class TestEightLaneCore(unittest.TestCase):
    def test_tracks_1_to_4_unchanged_and_lanes_never_reach_the_m7(self):
        h = lanes_rig()
        h.set_step(0, 2, 40)
        h.set_step(4, 2, 50)
        h.play()
        trig = [t for _, t, _ in h.run(4) if t]
        self.assertEqual(trig, [[[(0, 40)], []]])

    def test_no_writes_past_the_stock_4_track_arrays(self):
        """Tracks 5-8 never spill into what follows the stock 4-entry arrays."""
        h = lanes_rig()
        guard = [(SYM.g['seq_notes'] + 4 * NOTE_REC, SYM.g['seq_notes'] + 8 * NOTE_REC),
                 (SYM.g['pending_triggers'] + 4 * PENDING, SYM.g['pending_triggers'] + 8 * PENDING)]
        bad = []

        def hook(uc, acc, addr, size, val, _):
            if any(lo <= addr < hi for lo, hi in guard):
                bad.append(addr)
        h.e.uc.hook_add(UC_HOOK_MEM_WRITE, hook)
        for lane in range(8):
            h.set_step(lane, lane, 40 + lane)
        h.play()
        h.run(10)
        self.assertEqual(bad, [])


if __name__ == '__main__':
    unittest.main()
