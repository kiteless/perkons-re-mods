"""Akords: a kit brings back the sound that was saved: the values not on the knobs, from the
panel's events on the M4 through the kit's record to the M7's audio."""
import os
import shutil
import struct
import sys
import tempfile
import unittest

from fixtures import SYMBOLS_V130, build_patched, require_image
from perkons import verify
from perkons.emu import Symbols
from perkons.fwimage import Image
from perkons.rig import EVT, M4Rig

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
from ak_rig import AkordsCase, DRONE, HAVE_GCC, MSG_AKORDS_SOUND, MSG_VOICE_MAP, PLAY, POS1, POS2, POS3, goertzel, remap  # noqa: E402

KIT, MOD, SHIFT = 0x41, 0x43, 0x47
KIT_MODE, AKORDS_PAGE, ENGINES_PAGE = 5, 17, 18
COL = 4                                 # Akords' column (engine 5)
PARAM1, PARAM2 = 1, 5                   # the knobs' slots
MODE_SW, ALGO_SW = 1, 2                  # the switch events (track * 3 + these)
KEPT, KEPT_MODE, KEPT_CUT_OWN = 0x08, 0x10, 0x20    # the record's flags
APPLY, HOLD, OWN, ARM2, ARM1 = 0x40, 0x20, 0x10, 0x08, 0x04     # the message's flags
RES, ENV, ATTACK = 1, 2, 3
RES_I, ENV_I, ATT_I = 6, 7, 8           # the values in a voice's record
RECORD = 9
_image = {}


def image():
    if not _image:
        img, p = build_patched(Image.load(require_image('v1.3.0')), ['voice_map', 'voice_akords:5'],
                               tempfile.mkdtemp())
        _image['x'] = (img, p.cave_symbols['m4host'])
    return _image['x']


@unittest.skipUnless(HAVE_GCC, 'arm-none-eabi-gcc not installed')
class TestM4FollowsTheSound(unittest.TestCase):
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

    def apply(self, r):
        r.e.call(r.sym.fn['apply_mode'], max_insns=5_000_000)

    def press(self, r, k):
        self.key(r, k, True)
        self.key(r, k, False)

    def engines(self, r):
        r.set_mode(KIT_MODE)
        self.key(r, KIT, True)
        self.apply(r)
        self.press(r, MOD)
        self.key(r, KIT, False)
        self.apply(r)
        self.assertEqual(r.mode(), ENGINES_PAGE)

    def choose_akords(self, r, voice=0):
        self.engines(r)
        self.press(r, 16 * voice + COL)
        self.loop(r)

    def open_page(self, r, voice=0):
        self.key(r, 16 * voice + COL, True)
        r.e.call(r.sym.fn['ui_update'], max_insns=20_000_000)
        r.ms += 800
        r.e.call(r.sym.fn['ui_update'], max_insns=20_000_000)
        self.apply(r)
        self.key(r, 16 * voice + COL, False)
        self.apply(r)
        self.assertEqual(r.mode(), AKORDS_PAGE)

    def loop(self, r):
        r.ms += 10
        r.e.call(r.cave['pk_ak_main_loop'], max_insns=5_000_000)

    def knob(self, r, slot, x, voice=0):
        poll = r.sym.fn['lfo_knob_poll']
        r.turn(8 * voice + slot, x, lambda: r.e.call(poll, max_insns=5_000_000), steps=6)
        for _ in range(4):
            r.e.call(poll, max_insns=5_000_000)
        self.loop(r)

    def switch(self, r, which, pos, voice=0):
        r.e.uc.mem_write(EVT, bytes([3 * voice + which, 0x15]) + struct.pack('<H', pos) + bytes(4))
        r.e.call(r.key_handler, EVT, max_insns=50_000_000)
        self.loop(r)

    def record(self, r):
        buf = r.sym.g['json_buf']
        n = r.e.call(r.cave['pk_ak_kit_save'], 0, 0, buf, 64, max_insns=5_000_000)
        return bytes(r.e.uc.mem_read(buf, n))

    def sounds(self, r):
        return [p for t, p in r.e.sent(2) if t == MSG_AKORDS_SOUND]

    def reload(self, r, rec, kit=5):
        """A bank holding `rec` as kit `kit`'s record, with `r`'s knobs: kit `kit` loaded."""
        r2 = self.rig(sd={f'BANKS/02/KITS/{kit:02d}.KIX': b'PKX1AKRD' + struct.pack('<I', len(rec)) + rec,
                          'BANKS/02/00.PAT': b''})
        r2.e.call(r2.cave['pk4_store_bank_load'], 2, max_insns=900_000_000)
        return r2

    def load(self, r, kit=5):
        r.e.sent(2)
        r.e.call(r.cave['pk_ak_kit_load'], kit, max_insns=50_000_000)
        s = self.sounds(r)
        self.assertEqual(len(s), 1)
        return s[0]

    # -- saving ------------------------------------------------------------------------------
    def test_all_three_param2_values_are_saved(self):
        r = self.rig()
        self.choose_akords(r)
        for pos, x in ((POS1, 0.9), (POS2, 0.2), (POS3, 0.6)):
            self.switch(r, ALGO_SW, pos)
            self.knob(r, PARAM2, x)
        self.knob(r, PARAM1, 0.3)
        rec = self.record(r)
        self.assertEqual(len(rec), 4 * RECORD)
        self.assertEqual(rec[5] & (KEPT | KEPT_CUT_OWN), KEPT, 'the cutoff is on its knob')
        for i, x in ((RES_I, 0.9), (ENV_I, 0.2), (ATT_I, 0.6)):
            self.assertAlmostEqual(rec[i] / 255, x, delta=0.01, msg=f'value {i}')

    def test_a_value_keeps_its_setting_until_its_knob_moves(self):
        r = self.rig()
        self.choose_akords(r)
        self.switch(r, ALGO_SW, POS1)
        self.knob(r, PARAM2, 0.9)
        self.switch(r, ALGO_SW, POS2)                   # the knob's new job: not moved yet
        rec = self.record(r)
        self.assertAlmostEqual(rec[RES_I] / 255, 0.9, delta=0.01)
        self.assertEqual(rec[ENV_I], 0, 'what the knob last set it to (the rig starts at 0)')

    def test_a_preset_press_gives_the_presets_values(self):
        r = self.rig()
        self.choose_akords(r)
        self.knob(r, PARAM1, 0.2)
        self.switch(r, MODE_SW, POS3)
        self.open_page(r)
        self.press(r, 3)                                # preset 4
        self.loop(r)
        rec = self.record(r)
        self.assertEqual(rec[0], 3)
        self.assertEqual(list(rec[RES_I:ATT_I + 1]), [128] * 3)
        self.assertTrue(rec[5] & KEPT_CUT_OWN, 'the preset\'s cutoff')
        self.assertEqual(rec[5] & KEPT_MODE, 0, 'the preset\'s own filter')

    def test_mode_moved_keeps_modes_filter(self):
        r = self.rig()
        self.choose_akords(r)
        self.assertEqual(self.record(r)[5] & KEPT_MODE, 0)
        self.switch(r, MODE_SW, POS3)
        self.assertEqual(self.record(r)[5] & KEPT_MODE, KEPT_MODE)

    def test_a_voice_without_akords_keeps_no_sound(self):
        r = self.rig()
        self.choose_akords(r, voice=0)
        rec = self.record(r)
        self.assertEqual(rec[RECORD + 5], 0)
        self.assertEqual(list(rec[RECORD + RES_I:RECORD + ATT_I + 1]), [0] * 3)

    # -- loading -----------------------------------------------------------------------------
    def test_a_saved_sound_is_sent_and_saved_again(self):
        rec = bytes([2, 3, 4, 5, 1, KEPT | KEPT_MODE | KEPT_CUT_OWN, 20, 30, 40] + [0] * 27)
        r = self.reload(self.rig(), rec)
        m = self.load(r)
        self.assertEqual(list(m[1:5]), [128, 20, 30, 40])
        self.assertEqual(m[0] & (APPLY | OWN), APPLY, 'MODE\'s filter')
        self.assertEqual(m[0] & 3, ENV, 'ALGO at its middle position')
        self.assertEqual(m[0] & (ARM1 | ARM2), 0, 'off the knobs')
        self.assertEqual(m[5] & OWN, OWN, 'no sound kept: the preset\'s own filter')

    def test_a_value_on_its_knob_follows_it(self):
        r = self.rig()
        self.choose_akords(r)
        self.knob(r, PARAM1, 0.3)
        self.knob(r, PARAM2, 0.8)
        self.switch(r, ALGO_SW, POS1)                   # resonance: the preset's, the knob elsewhere
        r2 = self.reload(r, self.record(r))
        self.knob(r2, PARAM1, 0.3)                      # the kit's positions
        self.knob(r2, PARAM2, 0.8)
        self.switch(r2, ALGO_SW, POS1)
        m = self.load(r2)
        self.assertEqual(m[0] & 3, RES)
        self.assertTrue(m[0] & ARM1, 'cutoff is on its knob')
        self.assertFalse(m[0] & ARM2, 'resonance is not')
        self.assertEqual(m[2], 128)

    def test_older_records_play_their_knobs(self):
        for rec in (bytes([1, 2, 3, 4, 5] * 4), bytes([1, 2, 3, 4] * 4)):
            m = self.load(self.reload(self.rig(), rec))
            for v in range(4):
                f = m[5 * v]
                self.assertEqual(f & (APPLY | OWN | ARM1 | ARM2), APPLY | OWN | ARM1 | ARM2)

    def test_it_holds_until_the_positions_have_arrived(self):
        r = self.reload(self.rig(), bytes([0, 0, 0, 0, 0, KEPT, 20, 30, 40] + [0] * 27))
        m = self.load(r)
        self.assertTrue(m[0] & HOLD)
        self.assertEqual(self.sounds(r), [])
        r.ms += 25                              # stopped: the kit's values play at once
        r.e.call(r.cave['pk_ak_main_loop'], max_insns=5_000_000)
        s = self.sounds(r)
        self.assertEqual(len(s), 1, 'let go')
        self.assertFalse(s[0][0] & HOLD)
        self.assertEqual(list(s[0][2:5]), [20, 30, 40])
        self.loop(r)
        self.assertEqual(self.sounds(r), [], 'once')

    def test_a_lock_or_lfo_cant_hold_it_for_ever(self):
        r = self.rig()
        self.choose_akords(r)
        r.play()                                # (stopped, the firmware puts the value back)
        r.e.call(r.cave['pk4_store_kit_save'], 0, 0, max_insns=90_000_000)      # keeps Akords on it
        self.load(r, 0)
        vs = r.voice_state(0)
        for ms in (10, 500, 1000, 400):         # the playing value kept off the kit's
            r.w16(vs + 0x50 + 2 * PARAM2, r.r16(vs + 0x6a + 2 * PARAM2) ^ 0x4000)
            r.ms += ms
            r.e.call(r.cave['pk_ak_main_loop'], max_insns=5_000_000)
            self.assertEqual(self.sounds(r), [], f'after {ms}')
        r.ms += 200
        r.e.call(r.cave['pk_ak_main_loop'], max_insns=5_000_000)
        self.assertEqual(len(self.sounds(r)), 1, 'let go after 2 s')

    def test_a_voice_that_starts_running_akords_gets_its_values(self):
        r = self.rig()
        r.e.sent(2)
        self.loop(r)
        self.assertEqual(self.sounds(r), [])
        self.choose_akords(r, voice=2)
        s = self.sounds(r)
        self.assertEqual(len(s), 1)
        self.assertEqual([bool(s[0][5 * v] & APPLY) for v in range(4)], [False, False, True, False])
        self.loop(r)
        self.assertEqual(self.sounds(r), [], 'once')

    def test_leaving_the_page_without_a_change_writes_nothing(self):
        r = self.rig()
        self.choose_akords(r)
        self.open_page(r)
        self.knob(r, PARAM1, 0.3)
        r.e.sd_written.clear()
        self.press(r, SHIFT)
        self.apply(r)
        self.assertEqual(dict(r.e.sd_written), {}, 'a turned knob is saved with the kit')


@unittest.skipUnless(HAVE_GCC, 'arm-none-eabi-gcc not installed')
class TestM7TakesTheSound(AkordsCase):
    def sound(self, e, cut, res, env, att, role=ENV, armed=0, own=True, hold=False):
        msg = bytearray(20)
        msg[5 * e.out:5 * e.out + 5] = bytes([APPLY | role | (OWN if own else 0) | (HOLD if hold else 0) | armed, cut, res, env, att])
        e.send(2, MSG_AKORDS_SOUND, bytes(msg))
        e.audio(32)

    def tweaked(self, preset=0):
        """The values as x / 255 = knob / 4095 exactly: cutoff 1/3, resonance 2/3, env amount 1/3."""
        e = self.machine(preset=preset)
        self.turn(e, PLAY, 2048, 2730, algo=POS1)
        self.turn(e, PLAY, 1365, 1365, algo=POS2)
        return e

    def assertClose(self, a, b, delta=8):
        self.assertEqual(len(a), len(b))
        worst = max(abs(x - y) for x, y in zip(a, b))
        self.assertLessEqual(worst, delta)

    def test_panel_to_kit_to_audio(self):
        """Turned on the panel (M4), saved, reloaded; its message played (M7): as it was."""
        c = TestM4FollowsTheSound()
        r = c.rig()
        c.choose_akords(r)
        c.switch(r, ALGO_SW, POS1)
        c.knob(r, PARAM2, 0.9)
        c.switch(r, ALGO_SW, POS2)
        c.knob(r, PARAM2, 0.2)
        c.knob(r, PARAM1, 0.3)
        c.switch(r, ALGO_SW, POS1)                      # PARAM2 now on resonance, not moved
        rec = c.record(r)
        r2 = c.reload(r, rec)
        c.knob(r2, PARAM1, 0.3)
        c.knob(r2, PARAM2, 0.2)
        c.switch(r2, ALGO_SW, POS1)
        m = bytearray(c.load(r2))

        ref = self.machine(preset=0)
        self.turn(ref, PLAY, 1228, 3686, algo=POS1)
        self.turn(ref, PLAY, 1228, 819, algo=POS2)
        self.state(ref, ref.knobs, POS1, PLAY)

        e = self.machine(preset=0)
        self.state(e, [0, DRONE, 3000, 3900], POS3, POS3)       # another kit before it
        for v in range(4):
            if v != e.out:
                m[5 * v] = 0
        e.send(2, MSG_AKORDS_SOUND, bytes(m))
        e.audio(32)
        self.state(e, [0, DRONE, 1228, 819], POS1, PLAY)        # then the kit's knobs
        a, b = self.play(e, 2048, n=4800), self.play(ref, 2048, n=4800)
        la, lb = (sum(v * v for v in x) for x in (a, b))
        self.assertAlmostEqual(la / lb, 1.0, delta=0.05, msg='level')
        self.assertAlmostEqual(goertzel(a, 523.25) / goertzel(b, 523.25), 1.0, delta=0.1, msg='a partial')

    def test_a_kit_sound_plays_as_it_was_saved(self):
        ref = self.tweaked()
        e = self.machine(preset=0)              # another kit: every knob elsewhere
        self.state(e, [0, DRONE, 300, 3900], POS3, PLAY)
        self.sound(e, 85, 170, 85, 128, armed=0)
        self.state(e, [0, DRONE, 1365, 1365], POS2, PLAY)
        self.assertClose(self.play(e, 2048, n=4800), self.play(ref, 2048, n=4800))

    def test_a_held_sound_ignores_the_positions_until_let_go(self):
        fresh = self.machine(preset=0)
        e = self.machine(preset=0)
        self.state(e, [0, DRONE, 1000, 3900], POS3, PLAY)       # the kit before: ALGO on attack
        self.sound(e, 128, 128, 128, 128, hold=True, armed=ARM1 | ARM2)
        for _ in range(100):                    # far past any timer: the sequencer plays on
            e.audio(64)
        self.assertClose(self.play(e, 2048, n=4800), self.play(fresh, 2048, n=4800))
        k = [0, DRONE, 2048, 2048]              # the next note: the kit's positions arrive
        self.state(e, k, POS2, PLAY)
        self.sound(e, 128, 128, 128, 128, armed=ARM1 | ARM2)    # let go
        self.state(fresh, k, POS2, PLAY)        # (each chord rings as long before the next)
        fresh.audio(32)
        self.assertClose(self.play(e, 2048, n=4800), self.play(fresh, 2048, n=4800))
        k[3] = 3000                             # a real turn afterwards: it follows
        self.state(e, k, POS2, PLAY)
        self.assertNotEqual(self.play(e, 2048, n=4800), self.play(fresh, 2048, n=4800))

    def test_a_following_knob_follows_once_let_go(self):
        e = self.machine(preset=0)
        ref = self.machine(preset=0)
        self.sound(e, 128, 128, 128, 128, armed=ARM1 | ARM2)
        self.state(e, [0, DRONE, 300, 2048], POS2, PLAY)
        self.state(ref, [0, DRONE, 300, 2048], POS2, PLAY)
        self.assertClose(self.play(e, 2048, n=4800), self.play(ref, 2048, n=4800))

    def test_a_value_off_its_knob_stays_until_the_knob_moves(self):
        fresh = self.machine(preset=0)
        e = self.machine(preset=0)
        self.state(e, [0, DRONE, 300, 3900], POS2, PLAY)
        self.sound(e, 128, 128, 128, 128)       # let go, the knobs where they are
        self.assertClose(self.play(e, 2048, n=4800), self.play(fresh, 2048, n=4800))
        k = list(e.knobs)
        k[2] += 300
        self.state(e, k, *e.sw)
        self.assertNotEqual(self.play(e, 2048, n=4800), self.play(fresh, 2048, n=4800))

    def test_the_presets_own_filter_comes_back_with_mode_elsewhere(self):
        ref = self.machine(preset=0)            # Bass: its own low-pass
        e = self.machine(preset=0)
        self.state(e, e.knobs, POS2, POS3)      # was formant
        self.sound(e, 128, 128, 128, 128, hold=True)
        self.state(e, e.knobs, POS2, POS2)      # the kit's MODE arrives: high-pass position
        self.sound(e, 128, 128, 128, 128)
        self.assertClose(self.play(e, 2048, n=4800), self.play(ref, 2048, n=4800))
        self.state(e, e.knobs, POS2, POS3)      # MODE moves now: it chooses
        self.assertNotEqual(self.play(e, 2048, n=4800)[:2400], self.play(ref, 2048, n=4800)[:2400])

    def test_modes_filter_comes_back(self):
        e = self.machine(preset=0)
        self.sound(e, 128, 128, 128, 128, own=False)
        self.state(e, e.knobs, POS2, POS3)
        ref = self.machine(preset=0)
        self.state(ref, ref.knobs, POS2, POS3)  # MODE moved after the preset: formant
        self.assertClose(self.play(e, 2048, n=4800), self.play(ref, 2048, n=4800))

    def test_a_rebuilt_engine_finds_the_sound(self):
        ref = self.tweaked()
        e = self.machine(preset=0)
        self.state(e, [0, DRONE, 1365, 1365], POS2, PLAY)
        m = [0, 1, 2, 3]
        remap(e, m, self.cave, MSG_VOICE_MAP)   # back to stock at the next note
        self.play(e, 2048, n=64)
        self.sound(e, 85, 170, 85, 128)         # waits: this output isn't Akords now
        m[e.out] = 4
        remap(e, m, self.cave, MSG_VOICE_MAP)
        self.play(e, 2048, n=64)                # rebuilt at this note
        self.play(ref, 2048, n=64)
        self.assertClose(self.play(e, 2048, n=4800), self.play(ref, 2048, n=4800))


@unittest.skipUnless(HAVE_GCC, 'arm-none-eabi-gcc not installed')
class TestKitChangesPlaying(unittest.TestCase):
    """The M4 and the M7 running together: what the M4 sends, the M7 gets. While the sequencer
    plays, a kit's positions only reach the M7 with the track's next note."""

    def setUp(self):
        self.c = TestM4FollowsTheSound()
        self.r = self.c.rig()
        self.m = verify.boot(image()[0], Symbols(SYMBOLS_V130))
        self.t = 0
        self.m.audio(960)
        self.c.choose_akords(self.r)
        self.fwd()

    def fwd(self):
        for st in (1, 2, 3):
            for t, p in self.r.e.sent(st):
                self.m.send(st, t, p)
        self.m.pump()

    def tick(self, n=1, playing=True):
        r = self.r
        for _ in range(n):
            r.e.call(r.sym.fn['lfo_knob_poll'], max_insns=5_000_000)
            r.ms += 5
            r.e.call(r.cave['pk_ak_main_loop'], max_insns=5_000_000)
            self.fwd()
            self.m.audio(256)
            self.t += 1
            if playing and self.t % 24 == 0:
                r.step()
                self.fwd()
                self.m.audio(64)

    def values(self):
        a = self.m.slot(0)
        b = a + 0xd0 + self.m.r32(a + 0xcc)
        return [struct.unpack('<f', bytes(self.m.uc.mem_read(b + 4 * i, 4)))[0] for i in range(4)]

    def set_up_kits(self):
        c, r = self.c, self.r
        for s in range(16):
            r.set_step(0, s, on=s % 4 == 0)
        r.play()
        self.tick(60)
        kits = {}
        for kit, algo, att, res in ((0, POS3, 0.9, 0.4), (1, POS1, 0.1, 0.8)):
            c.switch(r, ALGO_SW, POS3)
            c.knob(r, PARAM2, att)
            c.switch(r, ALGO_SW, POS1)
            c.knob(r, PARAM2, res)
            c.switch(r, ALGO_SW, algo)                  # ALGO 3: the knob's at resonance's, off its job
            self.fwd()
            self.tick(30)
            r.e.call(r.cave['pk4_store_kit_save'], 0, kit, max_insns=90_000_000)
            self.fwd()
            kits[kit] = (res, att)
        return kits

    def test_changing_kits_while_playing_keeps_each_kits_values(self):
        kits = self.set_up_kits()
        for kit in (0, 1, 0, 1, 0, 1):
            self.r.e.call(self.r.cave['pk_ak_kit_load'], kit, max_insns=90_000_000)
            self.fwd()
            for _ in range(10):
                self.tick(12)
                v = self.values()
                self.assertAlmostEqual(v[1], kits[kit][0], delta=0.01, msg=f'kit {kit} resonance')
                self.assertAlmostEqual(v[3], kits[kit][1], delta=0.01, msg=f'kit {kit} attack')

    def test_changing_kits_while_stopped_keeps_each_kits_values(self):
        kits = self.set_up_kits()
        self.r.e.w8(self.r.seq, 0)
        self.tick(4, playing=False)
        for kit in (0, 1, 0, 1):
            self.r.e.call(self.r.cave['pk_ak_kit_load'], kit, max_insns=90_000_000)
            self.fwd()
            self.tick(20, playing=False)
            v = self.values()
            self.assertAlmostEqual(v[1], kits[kit][0], delta=0.01, msg=f'kit {kit} resonance')
            self.assertAlmostEqual(v[3], kits[kit][1], delta=0.01, msg=f'kit {kit} attack')


if __name__ == '__main__':
    unittest.main()
