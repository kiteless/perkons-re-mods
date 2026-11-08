"""fx-sidechain on the M4: KIT + SYNC (a tap: on / off; a hold: the page), the page, each
kit's settings (kit sidecar record SCHN) and the messages to the M7."""
import shutil
import struct
import tempfile
import unittest

from fixtures import build_patched, require_image
from perkons.fwimage import Image
from perkons.rig import M4Rig

SHIFT, KIT, SYNC, TRIG1 = 0x47, 0x41, 0x42, 0x4b
LED_SYNC = 0x47
KIT_MODE, MAIN_MODE = 5, 0
SIDECHAIN_PAGE = 18                         # the mods' pages after the stock 0-16, in name order
MSG_SC = 4                                  # the M7 host's message types, in name order
DEFAULT = [0, 0, 8, 1, 7, 9]                # off, voice 1, the default shape
_image = {}


def image():
    if not _image:
        img, p = build_patched(Image.load(require_image('v1.3.0')), ['voice_map', 'fx_sidechain'],
                               tempfile.mkdtemp())
        _image['x'] = (img, p.cave_symbols['m4host'])
    return _image['x']


def record(b):
    return b'PKX1SCHN' + struct.pack('<I', len(b)) + bytes(b)


def schn(kix):
    i = kix.index(b'SCHN')
    n = struct.unpack_from('<I', kix, i + 4)[0]
    return list(kix[i + 8:i + 8 + n])


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestSidechainPage(unittest.TestCase):
    def rig(self, sd=None):
        img, cave = image()
        r = M4Rig(img, cave, sd=sd if sd is not None else {'BANKS/00/KITS/00.KIT': b''})
        seg = img.segment('m4')
        site = r.sym.site('keys.handler_lit')['addr']
        r.handler = struct.unpack_from('<I', seg.data, site - seg.addr)[0] & ~1
        r.ms = 1000
        r.e.stub(r.sym.fn['hal_get_tick'], lambda e, *a: r.ms)
        r.e.sent(2)
        return r

    def key(self, r, k, down):
        r.event(k, down, handler=r.handler)

    def press(self, r, k):
        self.key(r, k, True)
        self.key(r, k, False)

    def apply(self, r):
        r.e.call(r.sym.fn['apply_mode'], max_insns=5_000_000)

    def loop(self, r, ms=10):
        r.ms += ms
        r.e.call(r.cave['pk_sc_main_loop'], max_insns=5_000_000)

    def ui(self, r):
        r.leds.clear()
        r.e.call(r.sym.fn['ui_update'], max_insns=20_000_000)
        self.apply(r)
        return [[r.leds.get(16 * v + e, 0) for e in range(16)] for v in range(4)]

    def sent(self, r):
        return [list(p) for t, p in r.e.sent(2) if t == MSG_SC]

    def kit_sync(self, r, hold_ms=100):
        """KIT down, SYNC down, `hold_ms` of main loop, SYNC up, KIT up."""
        self.key(r, KIT, True)
        self.apply(r)
        self.key(r, SYNC, True)
        for _ in range(hold_ms // 10):
            self.loop(r, 10)
        self.apply(r)
        self.key(r, SYNC, False)
        self.key(r, KIT, False)
        self.apply(r)

    def open_page(self, r):
        r.set_mode(MAIN_MODE)
        self.kit_sync(r, hold_ms=600)
        self.assertEqual(r.mode(), SIDECHAIN_PAGE)
        r.e.sent(2)

    # -- KIT + SYNC -----------------------------------------------------------------------
    def test_a_tap_turns_it_on_and_off(self):
        r = self.rig()
        r.set_mode(MAIN_MODE)
        self.kit_sync(r)
        self.assertEqual(self.sent(r), [[1] + DEFAULT[1:]])
        self.assertNotEqual(r.mode(), SIDECHAIN_PAGE)
        self.assertEqual(schn(r.e.sd_written['banks/00/kits/00.kix']), [0x81, 0x18, 0x97], 'kept in the kit')
        self.kit_sync(r)
        self.assertEqual(self.sent(r), [DEFAULT])

    def test_a_hold_opens_the_page_without_switching(self):
        r = self.rig()
        r.set_mode(MAIN_MODE)
        self.key(r, KIT, True)
        self.apply(r)
        self.key(r, SYNC, True)
        self.loop(r, 400)
        self.apply(r)
        self.assertNotEqual(r.mode(), SIDECHAIN_PAGE, 'not before 0.5 s')
        self.loop(r, 150)
        self.apply(r)
        self.assertEqual(r.mode(), SIDECHAIN_PAGE, 'opens while still held')
        self.key(r, SYNC, False)
        self.key(r, KIT, False)
        self.apply(r)
        self.assertEqual(r.mode(), SIDECHAIN_PAGE, 'stays after the releases')
        self.assertEqual(self.sent(r), [], 'no on / off')

    def test_sync_alone_is_stock(self):
        r = self.rig()
        r.set_mode(MAIN_MODE)
        self.press(r, SYNC)
        self.apply(r)
        self.assertEqual(self.sent(r), [])

    # -- the page -------------------------------------------------------------------------
    def test_steps_set_the_rows(self):
        r = self.rig()
        self.open_page(r)
        self.press(r, 16 * 0 + 15)              # depth: silent
        self.press(r, 16 * 1 + 0)               # attack 1 ms
        self.press(r, 16 * 2 + 0)               # no hold
        self.press(r, 16 * 3 + 2)               # release
        self.assertEqual(self.sent(r)[-1], [0, 0, 15, 0, 0, 2])
        self.assertEqual(r.mode(), SIDECHAIN_PAGE)

    def test_the_leds_show_the_rows_and_the_state(self):
        r = self.rig()
        self.open_page(r)
        leds = self.ui(r)
        self.assertEqual([[x > 0 for x in row].index(False) if 0 in row else 16 for row in leds],
                         [9, 2, 8, 10], 'a bar up to each value')
        self.assertLess(leds[0][8], 0x80, 'off: dim')
        self.assertEqual(r.leds.get(LED_SYNC, 0), 0)
        self.press(r, SYNC)                     # on
        self.assertEqual(self.sent(r), [[1] + DEFAULT[1:]])
        leds = self.ui(r)
        self.assertEqual(leds[0][8], 0x80)
        self.assertGreater(leds[0][3], 0)
        self.assertLess(leds[0][3], 0x80)
        self.assertEqual(r.leds.get(LED_SYNC, 0), 0x80)
        self.assertEqual([r.leds.get(0x4f - v, 0) for v in range(4)], [0x80, 0, 0, 0], 'the master lit')
        self.press(r, TRIG1 + 3)
        self.ui(r)
        self.assertEqual(r.leds.get(0x4f - 3, 0), 0x80)
        self.assertEqual(r.leds.get(0x4f, 0), 0)

    def test_the_trigger_and_sync_leds_are_stock_off_the_page(self):
        r = self.rig()
        r.set_mode(MAIN_MODE)
        self.kit_sync(r)                        # on
        r.set_mode(KIT_MODE)
        self.ui(r)
        self.assertEqual([r.leds.get(0x4f - v, 0) for v in range(4)], [0, 0, 0, 0])
        self.assertEqual(r.leds.get(LED_SYNC, 0), 0)

    def test_a_trigger_key_chooses_the_master_and_plays(self):
        r = self.rig()
        self.open_page(r)
        played = []
        r.e.stub(r.sym.fn['voice_play'], lambda e, voice, on, *a: played.append((voice, on)))
        self.press(r, TRIG1 + 2)
        self.assertEqual(self.sent(r), [[0, 2, 8, 1, 7, 9]])
        self.assertEqual(played, [(2, 1), (2, 0)])
        self.assertEqual(r.mode(), SIDECHAIN_PAGE)

    # -- kits -----------------------------------------------------------------------------
    def test_leaving_keeps_the_settings_in_the_kit(self):
        r = self.rig()
        self.open_page(r)
        self.press(r, SYNC)
        self.press(r, 16 * 0 + 11)
        self.press(r, TRIG1 + 1)
        self.assertNotIn('banks/00/kits/00.kix', r.e.sd_written, 'not while on the page')
        self.press(r, SHIFT)
        self.apply(r)
        self.assertNotEqual(r.mode(), SIDECHAIN_PAGE)
        self.assertEqual(schn(r.e.sd_written['banks/00/kits/00.kix']), [0x83, 0x1b, 0x97])

    def test_kit_load_sends_its_settings(self):
        r = self.rig()
        self.open_page(r)
        self.press(r, SYNC)
        self.press(r, 16 * 3 + 15)
        self.press(r, SHIFT)
        self.apply(r)
        r.e.sent(2)
        r.e.call(r.cave['pk_sc_kit_load'], 0, max_insns=50_000_000)
        self.assertEqual(self.sent(r), [[1, 0, 8, 1, 7, 15]])
        r.e.call(r.cave['pk_sc_kit_load'], 1, max_insns=50_000_000)
        self.assertEqual(self.sent(r), [DEFAULT], 'a kit without a record: off, the defaults')

    def test_bank_load_reads_the_kits(self):
        r = self.rig(sd={'BANKS/02/KITS/05.KIX': record([0x85, 0x3f, 0xa0]), 'BANKS/02/00.PAT': b''})
        r.e.call(r.cave['pk4_store_bank_load'], 2, max_insns=900_000_000)
        r.e.sent(2)
        r.e.call(r.cave['pk_sc_kit_load'], 5, max_insns=50_000_000)
        self.assertEqual(self.sent(r), [[1, 2, 15, 3, 0, 10]])
        r.e.call(r.cave['pk_sc_kit_load'], 4, max_insns=50_000_000)
        self.assertEqual(self.sent(r), [DEFAULT])


if __name__ == '__main__':
    unittest.main()
