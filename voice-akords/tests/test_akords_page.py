"""Akords on the M4: the settings page (a long press on its step on voice-map's engine
page), each kit's settings (kit sidecar record AKRD), the settings message to the M7."""
import shutil
import struct
import tempfile
import unittest

from fixtures import build_patched, require_image
from perkons.fwimage import Image
from perkons.rig import M4Rig

SHIFT, KIT, MOD, PATTERN, TRIG1 = 0x47, 0x41, 0x43, 0x40, 0x4b
MAIN_MODE, MOD_MODE, KIT_MODE = 0, 3, 5
AKORDS_PAGE, ENGINES_PAGE = 17, 18            # the mods' pages after the stock 0-16, in name order
MSG_AKORDS, MSG_AKORDS_DRIVE, MSG_AKORDS_PROG, MSG_VOICE_MAP = 4, 5, 6, 7             # the M7 host's message types, in name order
COL = 4                                       # Akords' column (engine 5)
_image = {}


def image():
    if not _image:
        img, p = build_patched(Image.load(require_image('v1.3.0')), ['voice_map', 'voice_akords:5'],
                               tempfile.mkdtemp())
        _image['x'] = (img, p.cave_symbols['m4host'])
    return _image['x']


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestSettingsPage(unittest.TestCase):
    def rig(self, sd=None):
        img, cave = image()
        r = M4Rig(img, cave, sd=sd if sd is not None else {'BANKS/00/KITS/00.KIT': b''})
        seg = img.segment('m4')
        site = r.sym.site('keys.handler_lit')['addr']
        r.handler = struct.unpack_from('<I', seg.data, site - seg.addr)[0] & ~1
        r.ms = 1000                                             # the ms clock (hal_get_tick)
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

    def ui(self, r):
        r.leds.clear()
        r.e.call(r.sym.fn['ui_update'], max_insns=20_000_000)
        self.apply(r)
        return [[r.leds.get(16 * v + e, 0) for e in range(16)] for v in range(4)]

    def open_engines(self, r):
        r.set_mode(KIT_MODE)
        self.key(r, KIT, True)
        self.apply(r)
        self.press(r, MOD)
        self.key(r, KIT, False)
        self.apply(r)
        self.assertEqual(r.mode(), ENGINES_PAGE)

    def long_press(self, r, voice, ms=800):
        """Hold the voice's Akords step for `ms` (the page draws meanwhile), then release."""
        self.key(r, 16 * voice + COL, True)
        self.ui(r)                                              # not yet
        r.ms += ms
        self.ui(r)
        self.key(r, 16 * voice + COL, False)
        self.apply(r)

    def open_page(self, r, voice=1):
        self.open_engines(r)
        self.long_press(r, voice)
        self.assertEqual(r.mode(), AKORDS_PAGE)

    def settings(self, r):
        """The settings messages sent since last asked: [4 x [preset, chord, scale, root]]."""
        return [[list(p[4 * v:4 * v + 4]) for v in range(4)] for t, p in r.e.sent(2) if t == MSG_AKORDS]

    # -- opening ------------------------------------------------------------------------
    def test_a_long_press_opens_it(self):
        r = self.rig()
        self.open_page(r, voice=2)                              # chooses Akords, then opens
        self.assertEqual([list(p) for t, p in r.e.sent(2) if t == MSG_VOICE_MAP], [[0, 1, 4, 3]])
        self.press(r, 16 * 0 + 2)
        self.assertEqual(self.settings(r)[-1][2], [2, 0, 0, 0], 'editing voice 3')

    def test_the_panel_switches_work_on_the_page(self):
        from perkons.rig import EVT
        r = self.rig()
        self.open_page(r, voice=1)
        self.press(r, 16 * 0 + 3)                               # a preset
        vs = r.voice_state(1)
        for which, pos in ((0, 2), (1, 1), (2, 2)):             # ALGO, MODE, filter: switch events
            r.e.uc.mem_write(EVT, bytes([3 + which, 0x15]) + struct.pack('<H', pos) + bytes(4))
            r.e.call(r.key_handler, EVT, max_insns=50_000_000)
        self.assertEqual([struct.unpack('<H', bytes(r.e.uc.mem_read(vs + 0x50 + 2 * s, 2)))[0] for s in (8, 9)],
                         [2, 1], 'voice 2 ALGO / MODE')
        self.assertEqual(r.mode(), AKORDS_PAGE)

    def test_a_short_press_only_chooses(self):
        r = self.rig()
        self.open_engines(r)
        self.long_press(r, 1, ms=300)
        self.assertEqual(r.mode(), ENGINES_PAGE)
        r.ms += 5000
        self.ui(r)
        self.assertEqual(r.mode(), ENGINES_PAGE, 'released: not later either')
        self.long_press(r, 1, ms=490)
        self.assertEqual(r.mode(), ENGINES_PAGE, 'just under 500 ms')
        self.long_press(r, 1, ms=510)
        self.assertEqual(r.mode(), AKORDS_PAGE)

    def test_a_long_press_on_another_engine_does_nothing(self):
        r = self.rig()
        self.open_engines(r)
        self.key(r, 16 * 0 + 0, True)                           # voice 1's own engine (stock)
        r.ms += 2000
        self.ui(r)
        self.assertEqual(r.mode(), ENGINES_PAGE)

    def test_the_releases_stay_on_the_page(self):
        """The long press's step and KIT releases arrive on the page: they don't leave it."""
        r = self.rig()
        self.open_engines(r)
        self.key(r, 16 + COL, True)
        r.ms += 900
        self.ui(r)
        self.assertEqual(r.mode(), AKORDS_PAGE)
        self.key(r, 16 + COL, False)
        self.key(r, KIT, False)
        self.apply(r)
        self.assertEqual(r.mode(), AKORDS_PAGE)

    # -- the page -----------------------------------------------------------------------
    def test_the_rows_set_the_voices_settings(self):
        r = self.rig()
        self.open_page(r, voice=1)
        r.e.sent(2)
        for row, col in ((0, 3), (1, 7), (2, 9), (3, 5)):
            self.press(r, 16 * row + col)
        sent = self.settings(r)
        self.assertEqual(len(sent), 4)
        self.assertEqual(sent[-1], [[0] * 4, [3, 7, 9, 5], [0] * 4, [0] * 4])
        rows = self.ui(r)
        for row, col in ((0, 3), (1, 7), (2, 9), (3, 5)):
            n = (14, 10, 11, 12)[row]
            self.assertEqual(rows[row][:n], [0x80 if c == col else 0x10 for c in range(n)])
        self.press(r, 16 * 2 + 11)                              # step 12: nothing
        self.assertEqual(self.settings(r), [])
        self.press(r, 16 * 1 + 7)                               # already chosen: nothing sent
        self.assertEqual(self.settings(r), [])

    def test_a_preset_press_always_sends_with_the_voices_bit(self):
        """Even the chosen one: the M7 then takes all of the preset's sound again."""
        r = self.rig()
        self.open_page(r, voice=2)
        r.e.sent(2)
        self.press(r, 16 * 0 + 5)
        self.press(r, 16 * 0 + 5)
        self.press(r, 16 * 2 + 4)
        sent = [p for t, p in r.e.sent(2) if t == MSG_AKORDS]
        self.assertEqual([len(p) for p in sent], [17] * 3)
        self.assertEqual([p[8] for p in sent], [5, 5, 5])
        self.assertEqual([p[16] for p in sent], [1 << 2, 1 << 2, 0], 'only a preset press')

    def test_the_page_edits_the_voice_it_was_opened_for(self):
        r = self.rig()
        self.open_engines(r)
        self.press(r, 16 * 3 + COL)                             # voice 4 on Akords too
        self.long_press(r, 3)
        self.press(r, 16 * 2 + 6)
        self.assertEqual(self.settings(r)[-1], [[0] * 4, [0] * 4, [0] * 4, [0, 0, 6, 0]])
        self.press(r, 16 * 0 + 13)                              # row 1 step 14: preset 14 (Talk)
        self.assertEqual(self.settings(r)[-1][3], [13, 0, 6, 0])
        self.assertEqual(self.ui(r)[2][11:], [0] * 5, 'nothing past the scales')

    def test_the_trigger_keys_play(self):
        r = self.rig()
        self.open_page(r)
        played = []
        r.e.stub(r.sym.fn['voice_play'], lambda e, voice, on, *a: played.append((voice, on)))
        self.press(r, TRIG1 + 1)
        self.assertEqual(played, [(1, 1), (1, 0)])
        self.assertEqual(r.mode(), AKORDS_PAGE)

    def test_shift_kit_mod_go_back_to_the_engine_page(self):
        for k in (SHIFT, KIT, MOD):
            with self.subTest(key=hex(k)):
                r = self.rig()
                self.open_page(r)
                self.press(r, k)
                self.apply(r)
                self.assertEqual(r.mode(), ENGINES_PAGE)
                self.ui(r)
                self.assertEqual(r.mode(), ENGINES_PAGE, 'not reopened')

    def test_another_page_button_leaves(self):
        r = self.rig()
        self.open_page(r)
        self.press(r, PATTERN)
        self.apply(r)
        self.assertNotIn(r.mode(), (AKORDS_PAGE, ENGINES_PAGE))

    # -- DRIVE --------------------------------------------------------------------------
    def test_drive_goes_to_the_m7_when_it_changes(self):
        """From the main loop, every 5 ms at most; again every 250 ms unchanged."""
        r = self.rig()
        poll = r.sym.fn['lfo_knob_poll']
        pot = 8 * 1 + 6                                         # voice 2's DRIVE
        r.moving = {pot}
        r.knob(pot, 0.8)
        for _ in range(4):
            r.e.call(poll, max_insns=5_000_000)
        r.moving = set()
        loop = r.cave['pk_ak_main_loop']

        def run(ms):
            r.ms += ms
            r.e.call(loop, max_insns=5_000_000)
            return [p for t, p in r.e.sent(2) if t == MSG_AKORDS_DRIVE]
        r.e.sent(2)
        r.e.sent(1)
        sent = run(10)
        self.assertEqual(len(sent), 1)
        self.assertEqual(len(sent[0]), 4)
        self.assertEqual(sent[0][1], 52428 >> 8)
        self.assertEqual(run(10) + run(10), [], 'unchanged: nothing')
        self.assertEqual(r.e.sent(1), [], 'nothing on the voice params stream')
        self.assertEqual(len(run(240)), 1, 'sent again after 250 ms')
        r.knob(pot, 0.2)
        r.moving = {pot}
        for _ in range(4):
            r.e.call(poll, max_insns=5_000_000)
        r.moving = set()
        r.e.sent(2)
        self.assertEqual(run(2), [], 'not within 5 ms of the last check')
        sent = run(5)
        self.assertEqual(sent[-1][1], 13107 >> 8)

    # -- kits ---------------------------------------------------------------------------
    def test_leaving_keeps_the_settings_in_the_kit(self):
        r = self.rig()
        self.open_page(r, voice=1)
        self.press(r, 16 * 0 + 7)                               # preset 7
        self.press(r, SHIFT)
        self.apply(r)
        kix = r.e.sd_written['banks/00/kits/00.kix']
        rec = bytes([0] * 5 + [7, 0, 0, 0, 0] + [0] * 10)
        self.assertEqual(kix, b'PKX1AKRD' + struct.pack('<I', 20) + rec + b'VMAP' + struct.pack('<IH', 2, 0x3240))

    def test_kit_load_sends_its_settings(self):
        r = self.rig()
        self.open_page(r, voice=1)
        self.press(r, 16 * 1 + 4)                               # chord type 4
        self.press(r, SHIFT)
        self.apply(r)
        r.e.sent(2)
        r.e.call(r.cave['pk_ak_kit_load'], 0, max_insns=50_000_000)
        self.assertEqual(self.settings(r), [[[0] * 4, [0, 4, 0, 0], [0] * 4, [0] * 4]])
        r.e.call(r.cave['pk_ak_kit_load'], 1, max_insns=50_000_000)
        self.assertEqual(self.settings(r), [[[0] * 4] * 4], 'a kit without a record: all 0')

    def test_bank_load_reads_the_kits(self):
        rec = b'PKX1AKRD' + struct.pack('<I', 16) + bytes(range(16)[:11]) + bytes([3, 2, 1, 0, 12])
        r = self.rig(sd={'BANKS/02/KITS/05.KIX': rec, 'BANKS/02/00.PAT': b''})
        r.e.call(r.cave['pk4_store_bank_load'], 2, max_insns=900_000_000)
        r.e.call(r.cave['pk_ak_kit_load'], 5, max_insns=50_000_000)
        self.assertEqual(self.settings(r), [[[0, 1, 2, 3], [4, 5, 6, 7], [8, 1, 10, 3], [2, 1, 0, 0]]],
                         'an older record (14 chord types: 9, Sus2 smooth, plays Diatonic smooth); '
                         'out of range (12): 0')

    def test_a_kit_keeps_the_progressions(self):
        rec = b'PKX1AKRD' + struct.pack('<I', 20) + bytes([1, 2, 3, 4, 5, 0, 9, 0, 0, 6] + [0] * 10)
        r = self.rig(sd={'BANKS/02/KITS/05.KIX': rec, 'BANKS/02/00.PAT': b''})
        r.e.call(r.cave['pk4_store_bank_load'], 2, max_insns=900_000_000)
        r.e.call(r.cave['pk_ak_kit_load'], 5, max_insns=50_000_000)
        self.assertEqual(self.settings(r), [[[1, 2, 3, 4], [0, 9, 0, 0], [0] * 4, [0] * 4]])
        buf = r.sym.g['json_buf']                               # the host's record buffer
        self.assertEqual(r.e.call(r.cave['pk_ak_kit_save'], 2, 5, buf, 64, max_insns=5_000_000), 20)
        self.assertEqual(list(r.e.uc.mem_read(buf, 20)), [1, 2, 3, 4, 5, 0, 9, 0, 0, 0] + [0] * 10,
                         'progression 6 out of range: 0')

    def test_the_largest_settings_survive_the_kit_table(self):
        top = [13, 9, 10, 11, 5]                                # Talk, Power smooth, Chromatic, B, Deep
        rec = b'PKX1AKRD' + struct.pack('<I', 20) + bytes(top * 4)
        r = self.rig(sd={'BANKS/02/KITS/05.KIX': rec, 'BANKS/02/00.PAT': b''})
        r.e.call(r.cave['pk4_store_bank_load'], 2, max_insns=900_000_000)
        r.e.call(r.cave['pk_ak_kit_load'], 5, max_insns=50_000_000)
        self.assertEqual(self.settings(r), [[top[:4]] * 4])
        buf = r.sym.g['json_buf']
        self.assertEqual(r.e.call(r.cave['pk_ak_kit_save'], 2, 5, buf, 64, max_insns=5_000_000), 20)
        self.assertEqual(list(r.e.uc.mem_read(buf, 20)), top * 4)

    # -- progressions ---------------------------------------------------------------------
    def test_row_2_has_the_chords_then_off_and_the_progressions(self):
        r = self.rig()
        self.open_page(r, voice=1)
        row = self.ui(r)[1]
        self.assertEqual(row, [0x80] + [0x10] * 9 + [0x80] + [0x10] * 5, 'Diatonic, progression off')
        self.press(r, 16 * 1 + 12)                              # step 13: progression 2
        row = self.ui(r)[1]
        self.assertEqual(row, [0x80] + [0x10] * 11 + [0x80] + [0x10] * 3)
        self.press(r, 16 * 1 + 8)                               # step 9: Power
        self.press(r, 16 * 1 + 10)                              # step 11: off
        self.assertEqual(self.ui(r)[1], [0x10] * 8 + [0x80, 0x10, 0x80] + [0x10] * 5)
        self.assertEqual(self.settings(r)[-1][1], [0, 8, 0, 0])

    def prog_sent(self, r):
        return [list(struct.unpack('4b', p)) for t, p in r.e.sent(2) if t == MSG_AKORDS_PROG]

    def test_a_progression_moves_once_per_track_cycle(self):
        """Trance (i VI III VII: 0 5 2 6) on voice 2, its track 9 steps long: the next
        chord at each new cycle, its offset sent before that step's triggers."""
        r = self.rig()
        self.open_page(r, voice=1)
        self.press(r, 16 * 1 + 11)                              # step 12: progression 1 (trance)
        self.press(r, SHIFT)
        self.apply(r)
        r.e.w8(r.block(1) + 0x81, 8)                            # track 2: steps 1-9
        for s in range(16):
            r.set_step(1, s)
        r.e.sent(2)
        r.play()
        seen = []
        for i in range(40):
            r.step()
            msgs = r.e.sent(2)
            for k, (t, p) in enumerate(msgs):
                if t == MSG_AKORDS_PROG:
                    seen.append((i, list(struct.unpack('4b', p))[1]))
                    self.assertTrue(any(tt == 0 for tt, _ in msgs[k + 1:]), 'before the step\'s triggers')
        self.assertEqual(seen, [(9, 5), (18, 2), (27, 6), (36, 0)])
        r.e.w8(r.seq, 0)                                        # stop: the first chord again
        r.e.call(r.cave['pk_ak_main_loop'], max_insns=5_000_000)
        self.assertEqual(self.prog_sent(r), [], 'already on the first chord')

    def test_the_techno_progression_is_two_chords(self):
        r = self.rig()
        self.open_page(r, voice=0)
        self.press(r, 16 * 1 + 14)                              # step 15: techno (i VI)
        self.press(r, SHIFT)
        self.apply(r)
        r.e.w8(r.block(0) + 0x81, 3)                            # track 1: 4 steps
        for s in range(4):
            r.set_step(0, s)
        r.play()
        r.e.sent(2)
        seen = []
        for i in range(14):
            r.step()
            seen += [(i, p[0]) for p in self.prog_sent(r)]
        self.assertEqual(seen, [(4, 5), (8, 0), (12, 5)])

    def test_a_new_pattern_starts_from_the_first_chord(self):
        r = self.rig()
        self.open_page(r, voice=0)
        self.press(r, 16 * 1 + 11)                              # step 12: trance (0 5 2 6)
        self.press(r, SHIFT)
        self.apply(r)
        for s in range(16):
            r.set_step(0, s)
        r.play()
        r.e.sent(2)
        seen = []
        for i in range(40):
            if i == 20:                                         # the next pattern, at the end of this one
                r.e.call(r.sym.fn['seq_queue'], r.sym.g['pat_headers'] + 0x20, max_insns=5_000_000)
            r.step()
            seen += [(i, p[0]) for p in self.prog_sent(r)]
        self.assertEqual(seen, [(16, 5), (32, 0)], 'the switch: the first chord, not the third')

    def test_stopping_goes_back_to_the_first_chord(self):
        r = self.rig()
        self.open_page(r, voice=0)
        self.press(r, 16 * 1 + 15)                              # step 16: progression 5 (i iv)
        self.press(r, SHIFT)
        self.apply(r)
        for s in range(16):
            r.set_step(0, s)
        r.play()
        for i in range(20):
            r.step()
        self.assertEqual([p[0] for p in self.prog_sent(r)], [3])
        r.e.w8(r.seq, 0)
        r.e.call(r.cave['pk_ak_main_loop'], max_insns=5_000_000)
        self.assertEqual([p[0] for p in self.prog_sent(r)], [0])


if __name__ == '__main__':
    unittest.main()
