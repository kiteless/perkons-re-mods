"""The reference model itself: a remapped output (engine copy in an arena) renders
bit-identical to that engine in its home slot."""
import unittest

from fixtures import SYMBOLS_V130, require_image
from perkons.emu import M7Emu, Symbols
from perkons.fwimage import Image
from vm_model import boot_remapped

PARAMS = [1500, 2500, 1800, 3000]
N = 6000


class TestRemapModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        img = Image.load(require_image('v1.3.0'))
        cls.m7, cls.m4 = img.segment('m7').data, img.segment('m4').data
        cls.sym = Symbols(SYMBOLS_V130)

    def emu(self):
        return M7Emu(self.m7, self.sym, self.m4)

    def render(self, e, voice, algo, mode):
        e.set_params(voice, PARAMS)
        e.set_algo_mode(voice, algo, mode)
        e.trigger(voice)
        return e.render(voice, N)

    def test_remap_matches_home_slot(self):
        """Every remapped output must render bit-identical to that engine in its home slot."""
        for vmap, algo, mode in (([3, 3, 3, 3], 0, 0), ([0, 0, 2, 2], 1, 1),
                                 ([2, 2, 2, 2], 2, 2), ([1, 3, 0, 2], 1, 0)):
            ref = {}
            for out, src in enumerate(vmap):
                with self.subTest(map=vmap, output=out + 1):
                    e = boot_remapped(self.emu(), vmap)
                    if src not in ref:
                        ref[src] = self.render(self.emu().boot_voices(), src, algo, mode)
                    self.assertEqual(self.render(e, out, algo, mode), ref[src])
