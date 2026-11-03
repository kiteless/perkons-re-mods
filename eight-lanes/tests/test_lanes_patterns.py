"""Eight-lanes: lanes follow the stock pattern lifecycle (save, revert on
switch, clear, bank load) and are stored in the host's pattern sidecar (BANKS/NN/PP.PAX,
record EL8P)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
from el_rig import DEVICE, SYM, lanes_rig, stock_image  # noqa: E402,F401


NLANES, LANE_REC = 4, 364


def records(b):
    """The host sidecar format: "PKX1", then {tag[4], u32 length, data}."""
    assert b[:4] == b'PKX1'
    out, i = [], 4
    while i < len(b):
        n = int.from_bytes(b[i + 4:i + 8], 'little')
        out.append((b[i:i + 4], b[i + 8:i + 8 + n]))
        i += 8 + n
    return out


def step_on(h, track, step):
    return h.e.r8(h.block(track) + 8 * step)


class TestLanesPatterns(unittest.TestCase):
    def save(self, h, p=0, bank=0, src=0):
        """The pattern page's save: the playing pattern (src) into slot p of the bank."""
        h.e.call(h.cave.get('pk4_store_pat_save', SYM.fn['pat_save']), h.header(src), bank, p, max_insns=200_000_000)

    def test_save_and_revert_like_stock(self):
        """Saved edits survive leaving the pattern, unsaved ones don't: tracks and lanes."""
        results = {}
        for name, kw in (('stock', dict(img=stock_image())), ('lanes', {})):
            h = lanes_rig(**kw)
            h.set_step(0, 1, 40, 99)
            if name == 'lanes':
                h.set_step(5, 3, 62, 99)
            self.save(h)
            h.switch_to(1)
            h.switch_to(0)
            saved = step_on(h, 0, 1), step_on(h, 5, 3) if name == 'lanes' else 1
            h.set_step(0, 5, 40, 99)
            if name == 'lanes':
                h.set_step(5, 7, 70, 99)
            h.switch_to(2)
            h.switch_to(0)
            unsaved = step_on(h, 0, 5), step_on(h, 5, 7) if name == 'lanes' else 0
            results[name] = (saved, unsaved)
        self.assertEqual(results['stock'], ((1, 1), (0, 0)))
        self.assertEqual(results['lanes'], results['stock'])

    def test_lanes_in_pax_and_pat_is_stock(self):
        files = {}
        for name, kw in (('stock', dict(img=stock_image())), ('lanes', {})):
            h = lanes_rig(**kw)
            h.set_step(0, 1, 40, 99)
            if name == 'lanes':
                h.set_step(6, 2, 55, 77)
            self.save(h, p=0, bank=0)
            files[name] = dict(h.e.sd_written)
        self.assertEqual(files['lanes']['banks/00/00.pat'], files['stock']['banks/00/00.pat'])
        tag, rec = records(files['lanes']['banks/00/00.pax'])[0]
        self.assertEqual((tag, len(rec)), (b'EL8P', NLANES * LANE_REC))
        lane = rec[2 * LANE_REC:3 * LANE_REC]                    # lane 7
        self.assertEqual((lane[2 * 8], lane[2 * 8 + 6], lane[2 * 8 + 7]), (1, 55, 77))
        self.assertEqual(rec[16], 0)                             # lane 5 untouched

    def test_empty_lanes_no_record(self):
        h = lanes_rig()
        h.set_step(0, 1, 40, 99)                                 # a voice step only
        self.save(h)
        self.assertNotIn('banks/00/00.pax', h.e.sd_written)

    def test_bank_load_reads_pax(self):
        h = lanes_rig()
        h.set_step(7, 4, 50, 88)                                 # lane 8, pattern 0
        self.save(h, p=5, bank=2)                                # save to pattern 5 of bank 2
        card = dict(h.e.sd_written)
        h2 = lanes_rig(sd=card)
        h2.e.call(h2.cave['pk4_store_bank_load'], 2, max_insns=900_000_000)
        h2.switch_to(5)
        self.assertEqual((step_on(h2, 7, 4), h2.e.r8(h2.block(7) + 4 * 8 + 6)), (1, 50))
        h2.switch_to(6)
        self.assertEqual(step_on(h2, 7, 4), 0)                   # other patterns: empty lanes

    def test_clear_removes_lanes_and_file(self):
        h = lanes_rig()
        h.set_step(4, 2, 50, 88)
        self.save(h)
        self.assertIn('banks/00/00.pax', h.e.sd_written)
        h.e.call(h.cave['pk4_store_pat_clear'], 0, 0, max_insns=200_000_000)
        self.assertNotIn('banks/00/00.pax', h.e.sd_written)
        self.assertEqual(step_on(h, 4, 2), 0)
        h.switch_to(1)
        h.switch_to(0)
        self.assertEqual(step_on(h, 4, 2), 0)

    def test_lanes_play_after_switching(self):
        h = lanes_rig()
        h.e.w8(DEVICE + 0x1d, 1)
        h.switch_to(3)
        h.set_step(4, 2, 60, 90)
        h.play()
        notes = [b.hex() for _, _, midi in h.run(4) for b in midi if b[0] == 0x94]
        self.assertTrue(notes and notes[0][:2] == '94')


if __name__ == '__main__':
    unittest.main()
