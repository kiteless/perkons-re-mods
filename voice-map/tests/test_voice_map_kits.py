"""voice-map on the M4: each kit's engines (kit sidecar record VMAP), the engine page (a page
of its own: KIT + MOD), the map sent to the M7 on the trigger stream."""
import os
import shutil
import struct
import tempfile
import unittest

from fixtures import build_patched, require_image
from perkons.fwimage import Image
from perkons.rig import M4Rig

SHIFT, KIT, MOD, TRIG1 = 0x47, 0x41, 0x43, 0x4b
MAIN_MODE, MOD_MODE, KIT_MODE, CONFIG_MODE = 0, 3, 5, 7
ENGINES_PAGE = 17                             # PK_PAGE_ENGINES: the first page after the stock 0-16
MSG = 4                                       # PK_MSG_VOICE_MAP
_images = {}


def image(patches):
    if patches not in _images:
        img, p = build_patched(Image.load(require_image('v1.3.0')), list(patches), tempfile.mkdtemp())
        _images[patches] = (img, p.cave_symbols['m4host'])
    return _images[patches]


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestEnginePage(unittest.TestCase):
    patches = ('voice_map', 'voice_zibens')

    def rig(self, sd=None):
        img, cave = image(self.patches)
        r = M4Rig(img, cave, sd=sd if sd is not None else {'BANKS/00/KITS/00.KIT': b''})
        seg = img.segment('m4')
        site = r.sym.site('keys.handler_lit')['addr']
        r.handler = struct.unpack_from('<I', seg.data, site - seg.addr)[0] & ~1     # the chained key handler
        r.e.sent(2)
        return r

    def key(self, r, k, down):
        r.event(k, down, handler=r.handler)

    def press(self, r, k):
        self.key(r, k, True)
        self.key(r, k, False)

    def apply(self, r):
        r.e.call(r.sym.fn['apply_mode'], max_insns=5_000_000)

    def open_page(self, r, from_mode=KIT_MODE):
        r.set_mode(from_mode)
        self.key(r, KIT, True)
        self.apply(r)                                 # KIT changes page before MOD comes
        self.press(r, MOD)
        self.key(r, KIT, False)
        self.apply(r)
        self.assertEqual(r.mode(), ENGINES_PAGE)

    def maps(self, r):
        return [list(p) for t, p in r.e.sent(2) if t == MSG]

    def leds(self, r):
        r.leds.clear()
        r.e.call(r.sym.fn['ui_update'], max_insns=20_000_000)
        return [[r.leds.get(16 * v + e, 0) for e in range(16)] for v in range(4)]

    def test_defaults_and_leds(self):
        r = self.rig()
        self.open_page(r)
        rows = self.leds(r)
        for v in range(4):
            self.assertEqual(rows[v][v], 0x80, f'voice {v + 1}: engine {v + 1}')
            self.assertEqual([x for e, x in enumerate(rows[v][:5]) if e != v], [0x10] * 4)   # 5 engines
            self.assertEqual(rows[v][5:], [0] * 11)

    def test_a_step_chooses_and_sends(self):
        r = self.rig()
        self.open_page(r)
        self.press(r, 16 * 2 + 4)                     # voice 3 -> engine 5 (zibens)
        self.assertEqual(self.maps(r), [[0, 1, 4, 3]])
        self.press(r, 16 * 0 + 7)                     # no engine 8: nothing
        self.assertEqual(self.maps(r), [])
        self.assertEqual(self.leds(r)[2][4], 0x80)

    def test_opens_from_any_page(self):
        for mode in (MAIN_MODE, KIT_MODE, MOD_MODE, CONFIG_MODE):
            with self.subTest(page=mode):
                self.open_page(self.rig(), from_mode=mode)

    def test_trigger_keys_play_the_voices(self):
        r = self.rig()
        self.open_page(r)
        played = []
        r.e.stub(r.sym.fn['voice_play'], lambda e, voice, on, *a: played.append((voice, on)))
        self.press(r, TRIG1 + 2)
        self.assertEqual(played, [(2, 1), (2, 0)], 'voice 3 played, as on the config page')
        self.assertEqual(r.mode(), ENGINES_PAGE)

    def test_leaving_keeps_it_in_the_kit(self):
        r = self.rig()
        self.open_page(r)
        self.press(r, 16 * 1 + 3)                     # voice 2 -> engine 4
        self.press(r, MOD)                            # a page button leaves (saves: changed)
        self.apply(r)
        self.assertEqual(r.mode(), MOD_MODE)
        kix = r.e.sd_written['banks/00/kits/00.kix']
        self.assertEqual(kix, b'PKX1VMAP' + struct.pack('<IH', 2, 0x3230))

    def test_a_long_hold_stays_on_the_page(self):
        r = self.rig()
        r.set_mode(MAIN_MODE)
        self.key(r, KIT, True)
        self.apply(r)
        self.press(r, MOD)
        self.apply(r)
        r.e.stub(r.sym.fn['key_held_ms'], lambda *a: 1000)    # stock: a long hold's release goes to MAIN
        self.key(r, KIT, False)
        self.apply(r)
        self.assertEqual(r.mode(), ENGINES_PAGE)

    def test_leaving_unchanged_writes_nothing(self):
        r = self.rig()
        self.open_page(r)
        self.press(r, KIT)
        self.apply(r)
        self.assertEqual(r.mode(), KIT_MODE)
        self.assertNotIn('banks/00/kits/00.kix', r.e.sd_written)

    def test_kit_load_sends_its_engines(self):
        r = self.rig()
        self.open_page(r)
        self.press(r, 16 * 3 + 0)                     # voice 4 -> engine 1
        self.press(r, MOD)
        self.apply(r)
        r.e.sent(2)
        r.e.call(r.cave['pk_vm_kit_load'], 0, max_insns=50_000_000)
        self.assertEqual(self.maps(r), [[0, 1, 2, 0]])
        r.e.call(r.cave['pk_vm_kit_load'], 1, max_insns=50_000_000)
        self.assertEqual(self.maps(r), [[0, 1, 2, 3]], 'a kit without a record: stock engines')

    def test_bank_load_reads_the_kits(self):
        rec = b'PKX1VMAP' + struct.pack('<IH', 2, 0x0123)
        r = self.rig(sd={'BANKS/02/KITS/05.KIX': rec, 'BANKS/02/00.PAT': b''})
        r.e.call(r.cave['pk4_store_bank_load'], 2, max_insns=900_000_000)
        r.e.call(r.cave['pk_vm_kit_load'], 5, max_insns=50_000_000)
        self.assertEqual(self.maps(r), [[3, 2, 1, 0]])

    def test_shift_mod_is_the_stock_config_menu(self):
        r = self.rig()
        r.set_mode(KIT_MODE)
        self.key(r, SHIFT, True)
        self.apply(r)
        self.press(r, MOD)
        self.key(r, SHIFT, False)
        self.apply(r)
        self.assertEqual(r.mode(), CONFIG_MODE)
        self.press(r, 16 * 2 + 4)
        self.assertEqual(self.maps(r), [])

    def test_kit_save_stores_the_engines_playing(self):
        r = self.rig()
        self.open_page(r)
        self.press(r, 16 * 0 + 4)                     # voice 1 -> zibens
        r.e.stub(r.sym.fn['kit_save'], lambda *a: 0)
        r.e.call(r.cave['pk4_store_kit_save'], 0, 9, max_insns=50_000_000)   # KIT + REC into kit 10
        self.assertEqual(r.e.sd_written['banks/00/kits/09.kix'], b'PKX1VMAP' + struct.pack('<IH', 2, 0x3214))


if __name__ == '__main__':
    unittest.main()


class TestSlots(unittest.TestCase):
    """Extra engines take the slot they're installed in (the engine page's column)."""

    def p(self, **slots):
        class P:
            shared = {}
        p = P()
        import _voice_map_common as vmc
        for name, slot in slots.items():
            vmc.engines(p)[name] = {'sources': [], 'build': f'pk_{name}_build', 'slot': slot}
        return p, vmc

    def test_slots_and_free_ones(self):
        p, vmc = self.p(b=7, a=None, c=None)
        self.assertEqual({k: n for k, (n, _) in vmc.numbered(p).items()}, {5: 'a', 6: 'c', 7: 'b'})
        self.assertEqual(vmc.engine_names(p)[5:], ['a', 'c', 'b'])

    def test_a_gap_is_an_empty_column(self):
        p, vmc = self.p(x=6)
        self.assertEqual(vmc.engine_names(p)[5:], ['', 'x'])

    def test_clashes_and_range(self):
        p, vmc = self.p(a=5, b=5)
        with self.assertRaises(ValueError):
            vmc.numbered(p)
        p, vmc = self.p(a=17)
        with self.assertRaises(ValueError):
            vmc.numbered(p)

    def test_the_last_column(self):
        p, vmc = self.p(a=16)
        self.assertEqual(vmc.engine_names(p)[16], 'a')
