"""Eight-lanes: lanes follow the stock pattern lifecycle (save, revert on
switch, clear, bank load) and are stored in BANKS/NN/PP.PA2 (the .PAT format)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'harness'))
from lanes_build import header, lanes_harness, queue_and_switch  # noqa: E402
from fixtures import require_image  # noqa: E402
from perkons.fwimage import Image  # noqa: E402


def varint(b, i):
    v = s = 0
    while True:
        c = b[i]
        i += 1
        v |= (c & 0x7f) << s
        s += 7
        if c < 0x80:
            return v, i


def parse(b):
    """Top-level fields of a length-prefixed .PAT-format file: [(field, value)]."""
    n, i = varint(b, 0)
    assert n == len(b) - i
    out = []
    while i < len(b):
        key, i = varint(b, i)
        if key & 7 == 0:
            v, i = varint(b, i)
        else:
            ln, i = varint(b, i)
            v, i = b[i:i + ln], i + ln
        out.append((key >> 3, v))
    return out


def step_on(h, track, step):
    return h.e.r8(h.block(track) + 8 * step)


class TestLanesPatterns(unittest.TestCase):
    def save(self, h, p=0, bank=0, src=0):
        """The pattern page's save: the playing pattern (src) into slot p of the bank."""
        h.e.call(h.cave.get('pk_el_save', 0x08102158), header(src), bank, p, max_insns=200_000_000)

    def test_save_and_revert_like_stock(self):
        """Saved edits survive leaving the pattern, unsaved ones don't: tracks and lanes."""
        results = {}
        for name, kw in (('stock', dict(img=Image.load(require_image('v1.3.0')))), ('lanes', {})):
            h = lanes_harness(**kw)
            h.set_step(0, 1, 40, 99)
            if name == 'lanes':
                h.set_step(5, 3, 62, 99)
            self.save(h)
            queue_and_switch(h, 1)
            queue_and_switch(h, 0)
            saved = step_on(h, 0, 1), step_on(h, 5, 3) if name == 'lanes' else 1
            h.set_step(0, 5, 40, 99)
            if name == 'lanes':
                h.set_step(5, 7, 70, 99)
            queue_and_switch(h, 2)
            queue_and_switch(h, 0)
            unsaved = step_on(h, 0, 5), step_on(h, 5, 7) if name == 'lanes' else 0
            results[name] = (saved, unsaved)
        self.assertEqual(results['stock'], ((1, 1), (0, 0)))
        self.assertEqual(results['lanes'], results['stock'])

    def test_pa2_is_the_pat_format_and_pat_is_stock(self):
        files = {}
        for name, kw in (('stock', dict(img=Image.load(require_image('v1.3.0')))), ('lanes', {})):
            h = lanes_harness(**kw)
            h.set_step(0, 1, 40, 99)
            if name == 'lanes':
                h.set_step(6, 2, 55, 77)
            self.save(h, p=0, bank=0)
            files[name] = dict(h.e.sd_written)
        self.assertEqual(files['lanes']['banks/00/00.pat'], files['stock']['banks/00/00.pat'])
        pa2 = parse(files['lanes']['banks/00/00.pa2'])
        self.assertEqual([f for f, _ in pa2], [1, 2, 3, 3, 3, 3])
        self.assertEqual(pa2[0][1], 1)
        tracks = [v for f, v in pa2 if f == 3]
        blocks = []
        for t in tracks:
            key, i = varint(t, 0)
            n, i = varint(t, i)
            self.assertEqual((key, n, len(t) - i), (0x0a, 0x22c, 0x22c))
            blocks.append(t[i:])
        self.assertEqual((blocks[2][2 * 8], blocks[2][2 * 8 + 6], blocks[2][2 * 8 + 7]), (1, 55, 77))
        self.assertEqual(blocks[0][16], 0)                       # lane 5 untouched

    def test_bank_load_reads_pa2(self):
        h = lanes_harness()
        h.set_step(7, 4, 50, 88)                                 # lane 8, pattern 0
        self.save(h, p=5, bank=2)                                # save to pattern 5 of bank 2
        card = dict(h.e.sd_written)
        h2 = lanes_harness(sd=card)
        h2.e.call(h2.cave['pk_el_bank_prepare'], 2, max_insns=500_000_000)
        queue_and_switch(h2, 5)
        self.assertEqual((step_on(h2, 7, 4), h2.e.r8(h2.block(7) + 4 * 8 + 6)), (1, 50))
        queue_and_switch(h2, 6)
        self.assertEqual(step_on(h2, 7, 4), 0)                   # other patterns: empty lanes

    def test_clear_removes_lanes_and_file(self):
        h = lanes_harness()
        h.set_step(4, 2, 50, 88)
        self.save(h)
        self.assertIn('banks/00/00.pa2', h.e.sd_written)
        h.e.call(h.cave['pk_el_clear'], 0, 0, max_insns=200_000_000)
        self.assertNotIn('banks/00/00.pa2', h.e.sd_written)
        self.assertEqual(step_on(h, 4, 2), 0)
        queue_and_switch(h, 1)
        queue_and_switch(h, 0)
        self.assertEqual(step_on(h, 4, 2), 0)

    def test_lanes_play_after_switching(self):
        h = lanes_harness()
        h.e.w8(0x10000784 + 0x1d, 1)
        queue_and_switch(h, 3)
        h.set_step(4, 2, 60, 90)
        h.play()
        notes = [b.hex() for _, _, midi in h.run(4) for b in midi if b[0] == 0x94]
        self.assertTrue(notes and notes[0][:2] == '94')


if __name__ == '__main__':
    unittest.main()
