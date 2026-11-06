"""Akords: wiring: the engine slot, voice-map, the stock voices."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
from ak_rig import *  # noqa: E402,F401,F403


@unittest.skipUnless(HAVE_GCC, 'arm-none-eabi-gcc not installed')
class TestAkordsWiring(AkordsCase):
    # -- wiring ---------------------------------------------------------------------------
    def test_remap_to_akords_and_back(self):
        e = self.machine(2)
        self.assertEqual(e.class_of(e.slot(2)), 'cAkords')
        self.assertEqual([e.class_of(e.slot(o)) for o in (0, 1, 3)], ['cFirstSlot', 'cSecondSlot', 'cFourthSlot'])
        self.assertGreater(max(map(abs, self.play(e, 2048))), 1000)
        remap(e, [0, 1, 2, 3], self.cave, MSG_VOICE_MAP)
        self.assertEqual(e.class_of(e.slot(2)), 'cThirdSlot')

    def test_needs_voice_map(self):
        with self.assertRaises(PatchError):
            build_patched(self.stock, ['voice_akords'], self.tmp + '/b')

    def test_stock_outputs_unchanged(self):
        """With the stock map, every output/algo/mode renders exactly like stock."""
        bad = [r for r in verify.compare_to_stock(self.stock, self.img, self.sym) if not r[4]]
        self.assertEqual(bad, [])

    def test_with_voice_zibens(self):
        img, _ = build_patched(self.stock, ['voice_map', 'voice_zibens', 'voice_akords'], self.tmp + '/z')
        e = verify.boot(img, self.sym)
        e.send(2, MSG_VOICE_MAP, bytes([4, 5, 2, 3]))  # engines 5 and 6: akords, zibens (name order)
        e.send_triggers([1, 1, 0, 0], [(0, 0)] * 4)
        e.audio(64)
        self.assertEqual([e.class_of(e.slot(o)) for o in range(2)], ['cAkords', 'cZibens'])
