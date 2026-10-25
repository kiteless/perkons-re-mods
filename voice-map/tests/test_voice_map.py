"""Phase F1 (fixed voice map) checks: patched firmware vs the reference model and vs
stock behaviour. Needs arm-none-eabi-gcc; ~1-2 min."""
import os
import re
import shutil
import struct
import tempfile
import unittest

from fixtures import SYMBOLS_V130, require_image
from perkons import verify
from perkons.emu import M7Emu, M7System, Symbols
from perkons.fwimage import Image
from perkons.mods import load_patch
from perkons.patch import Patcher

import vm_model
from vm_model import boot_remapped, crosstalk

vmf = load_patch('voice_map_fixed')
import _voice_map_common as vmc  # noqa: E402  (on sys.path once a mod patch is loaded)

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARENAS = (vm_model.PK_ARENA_BASE, vm_model.PK_ARENA_BASE + 4 * vm_model.PK_ARENA_SIZE)

OFF = Symbols(SYMBOLS_V130).off


def build_f1(stock, sym, digits, tmp):
    p = Patcher(stock)
    p.symbols = {'m7': sym, 'm4': Symbols(SYMBOLS_V130.replace('-m7.json', '-m4.json'))}
    p.build_dir = os.path.join(tmp, digits)
    vmf.apply(p, digits)
    return p.result()


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestVoiceMapF1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = Image.load(require_image('v1.3.0'))
        cls.sym = Symbols(SYMBOLS_V130)
        cls.tmp = tempfile.mkdtemp(prefix='pk-f1-')
        cls.images = {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def image(self, digits):
        if digits not in self.images:
            self.images[digits] = build_f1(self.stock, self.sym, digits, self.tmp)
        return self.images[digits]

    def system(self, img):
        return M7System(img.segment('m7').data, self.sym, img.segment('m4').data).boot()

    def test_header_constants_match_python(self):
        with open(os.path.join(MOD, 'src', 'm7', 'pk_ram.h')) as f:
            h = f.read()
        self.assertEqual(int(re.search(r'#define PK_RAM_BASE\s+(0x[0-9a-f]+)', h).group(1), 16), vm_model.PK_RAM_BASE)
        self.assertEqual(int(re.search(r'#define PK_ARENA_SIZE\s+(0x[0-9a-f]+)', h).group(1), 16), vm_model.PK_ARENA_SIZE)
        self.assertEqual(vmc.PK_RAM_BASE, vm_model.PK_RAM_BASE)

    def test_boot_ram_matches_reference_model(self):
        m7, m4 = self.stock.segment('m7').data, self.stock.segment('m4').data
        for digits in ('4434', '1111', '2222', '3333', '4444', '2413', '1133', '3412'):
            with self.subTest(map=digits):
                e = self.system(self.image(digits))
                ref = boot_remapped(M7Emu(m7, self.sym, m4), [int(c) - 1 for c in digits])
                regions = [(int(a, 16), int(b, 16)) for a, b in self.sym.raw['slot_extents']]
                regions += [ARENAS, (self.sym.g['slots'], self.sym.g['slots'] + 16)]
                for lo, hi in regions:
                    self.assertEqual(bytes(e.uc.mem_read(lo, hi - lo)), bytes(ref.uc.mem_read(lo, hi - lo)),
                                     f'RAM differs in {lo:08x}-{hi:08x}')

    def test_templates_stay_pristine(self):
        """The original engine objects are templates: playing must never modify them."""
        img = self.image('4434')
        e = verify.boot(img, self.sym)
        extents = [(int(a, 16), int(b, 16)) for a, b in self.sym.raw['slot_extents']]
        before = [bytes(e.uc.mem_read(lo, hi - lo)) for lo, hi in extents]
        e.send_voice_state([{'params': verify.DEFAULT_PARAMS, 'algo': 2, 'mode': 1} for _ in range(4)])
        e.pump()
        e.send_triggers([1, 1, 1, 1], [(2, 1)] * 4)
        e.audio(2048)
        e.send(3, 2, b'\x00\x01')
        e.send(3, 4, bytes([0, 1, 2, 3]))
        e.pump()
        e.audio(512)
        after = [bytes(e.uc.mem_read(lo, hi - lo)) for lo, hi in extents]
        self.assertEqual(before, after)

    def test_outputs_sound_like_their_stock_engine(self):
        cases = {'4434': (range(3), range(3)), '1133': ((1,), (1,)), '3333': ((0, 2), (0, 2)), '2413': ((1,), (0,))}
        for digits, (algos, modes) in cases.items():
            img = self.image(digits)
            self.assertEqual(verify.engine_map(img, self.sym), [int(c) - 1 for c in digits])
            for out, algo, mode, eng, ok in verify.compare_to_stock(self.stock, img, self.sym, algos, modes):
                with self.subTest(map=digits, output=out + 1, algo=algo, mode=mode):
                    self.assertTrue(ok, f'output {out + 1} differs from stock voice {eng + 1}')

    def test_p2_config_reaches_every_sampler(self):
        e = self.system(self.image('4344'))
        e.send(3, 2, b'\x00\x01')
        e.pump()
        for out in (0, 2, 3):
            self.assertEqual(e.r8(e.slot(out) + OFF['cFourthSlot.p2cfg']), 1, f'output {out + 1}')
        self.assertNotEqual(e.class_of(e.slot(1)), 'cFourthSlot')

    def test_sample_load_reaches_every_sampler(self):
        e = self.system(self.image('4444'))
        e.send(3, 3, b'\x01')
        e.pump()
        ptrs = [e.r32(e.slot(o) + OFF['cFourthSlot.sampler'] + OFF['cSamplePlayer.sample_ptr']) for o in range(4)]
        self.assertTrue(all(ptrs), [hex(x) for x in ptrs])
        self.assertEqual(len(set(ptrs)), 1, 'all instances should share the same sample data')

    def test_heap_capped_below_patch_ram(self):
        img = self.image('4434')
        lit = self.sym.site('sbrk.limit_literal')['addr']
        seg = img.segment('m7')
        val = struct.unpack_from('<I', seg.data, lit - seg.addr)[0]
        self.assertEqual(val - 0x400, vm_model.PK_RAM_BASE)


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestNoCrosstalk(unittest.TestCase):
    """Copies of an engine must not affect each other (function statics are swapped per
    output by pk_sampler_render / pk_crush_render)."""

    def test_duplicated_engines_are_independent(self):
        stock = Image.load(require_image('v1.3.0'))
        sym = Symbols(SYMBOLS_V130)
        tmp = tempfile.mkdtemp(prefix='pk-xt-')
        try:
            for digits in ('1111', '2222', '3333', '4444'):
                img = build_f1(stock, sym, digits, tmp)
                for algo in range(3):
                    for mode in range(3):
                        with self.subTest(map=digits, algo=algo, mode=mode):
                            self.assertEqual(crosstalk(img, sym, algo, mode, n=3000), 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
