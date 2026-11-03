"""Saving a pattern or a kit flashes the key it was saved with, as stock: the pages flash
only when the stock save returns non-zero, so every save hook passes that result back."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
from el_rig import lanes_rig, stock_image  # noqa: E402

PATTERN, KIT, REC = 0x40, 0x41, 0x46
STEP = 4                                        # step 5


def rigs():
    yield 'stock', lanes_rig(img=stock_image())
    yield 'eight-lanes', lanes_rig()
    yield 'every store mod', lanes_rig(extra=('voice_map', 'pattern_bpm', 'per_track_lfo'))


class TestSaveFlash(unittest.TestCase):
    def check(self, flash, held, key):
        """Hold `held` (from the main page: it opens its page), then press `key` there."""
        for name, h in rigs():
            with self.subTest(name):
                h.event(held, True)
                h.e.call(h.sym.fn['apply_mode'], max_insns=5_000_000)
                h.w16(h.sym.g[flash], 0xffff)
                h.press(key)
                h.event(held, False)
                self.assertEqual(h.r16(h.sym.g[flash]), key)

    def test_rec_step_on_the_pattern_page(self):
        for name, h in rigs():
            with self.subTest(name):
                h.set_mode(4)
                h.w16(h.sym.g['pat_save_flash'], 0xffff)
                h.event(REC, True)
                h.press(STEP)
                h.event(REC, False)
                self.assertEqual(h.r16(h.sym.g['pat_save_flash']), STEP)

    def test_pattern_rec(self):
        self.check('pat_save_flash', PATTERN, REC)

    def test_rec_step_on_the_kit_page(self):
        for name, h in rigs():
            with self.subTest(name):
                h.set_mode(5)
                h.w16(h.sym.g['kit_save_flash'], 0xffff)
                h.event(REC, True)
                h.press(STEP)
                h.event(REC, False)
                self.assertEqual(h.r16(h.sym.g['kit_save_flash']), STEP)

    def test_kit_rec(self):
        self.check('kit_save_flash', KIT, REC)


if __name__ == '__main__':
    unittest.main()
