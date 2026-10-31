"""per-track-lfo: the stock LFO knob poll and stream-1 sender, driven in the emulator."""
import os
import struct
import sys
import tempfile
import unittest

PERKONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'perkons')
sys.path[:0] = [os.path.join(PERKONS, 'tools'), os.path.join(PERKONS, 'tests')]
os.environ.setdefault('PERKONS_MODS', os.path.join(PERKONS, '..', 'perkons-re-mods'))

from fixtures import build_patched, require_image  # noqa: E402
from perkons.emu import M4Emu, Symbols  # noqa: E402
from perkons.rig import M4Rig, stub_hardware  # noqa: E402
from perkons.fwimage import Image  # noqa: E402
from unicorn.arm_const import UC_ARM_REG_S0  # noqa: E402

SYM = Symbols(os.path.join(PERKONS, 'symbols', 'v1.3.0-m4.json'))
KNOB_POLL = SYM.fn['lfo_knob_poll']       # LFO knobs -> setters, then the stream-1 sender
LFO = SYM.g['mod_lfo']
LFO_SIZE, LFO_SYNC = 0x30, 0x24
KITS = SYM.g['kits']
KIT_INDEX = SYM.g['current_kit']
DEPTH = 0x5c                  # kit: 4 x 8 modulation depths (slot 0-7)
RATE, WAVE, LEVEL = 0x21, 0x22, 0x23
TRIG1, RESET = 0x4b, 0x44

_images = {}


def image(mod):
    """mod: False = stock, True = this mod, or a tuple of patches to build with it."""
    if mod not in _images:
        stock = Image.load(require_image('v1.3.0'))
        if mod:
            extra = mod if isinstance(mod, tuple) else ()
            img, p = build_patched(stock, ['per_track_lfo', *extra], tempfile.mkdtemp())
            _images[mod] = (img, p.cave_symbols['m4host'])
        else:
            _images[mod] = (stock, {})
    return _images[mod]


class Rig(M4Rig):
    """The panel rig, with every voice's TUNE modulated (kit depth 100) and the voice
    knobs' handler (first in the poll, not under test) silent."""

    def __init__(self, mod=True):
        super().__init__(*image(mod))
        e = self.e
        e.stub(SYM.fn['knob_handler'], lambda *a: 0)
        kit = KITS + 0xa0 * struct.unpack('<H', bytes(e.uc.mem_read(KIT_INDEX, 2)))[0]
        for v in range(4):
            e.w8(kit + DEPTH + 8 * v, 100)
        self.knob(RATE, 0.3)
        self.knob(WAVE, 0.0)
        self.knob(LEVEL, 1.0)
        self.moving = {RATE, WAVE, LEVEL}                         # the main LFO takes them
        self.poll(2)
        self.moving = set()
        e.sent(1)

    def poll(self, n=1):
        for _ in range(n):
            self.e.call(KNOB_POLL, max_insns=5_000_000)

    def turn(self, pot, to, steps=8):
        super().turn(pot, to, self.poll, steps)

    def tunes(self, n):
        """TUNE (slot 0) sent to the M7 for each voice over the next n polls."""
        self.e.sent(1)
        out = []
        for _ in range(n):
            self.poll()
            for typ, p in self.e.sent(1):
                out.append(tuple(struct.unpack_from('<H', p, 12 * v)[0] for v in range(4)))
        return out

    def inc(self, obj=LFO):
        return struct.unpack('<f', bytes(self.e.uc.mem_read(obj + 4, 4)))[0]

    def led(self):
        self.e.call(self.cave['pk_lf_led'], LFO, max_insns=100_000)
        return struct.unpack('<f', struct.pack('<I', self.e.uc.reg_read(UC_ARM_REG_S0)))[0]

    def group_obj(self, v):
        """The LFO object voice v runs (the main LFO for the main group)."""
        g = self.e.r8(self.cave['group'] + v)
        return LFO if g == 0 else self.cave['lfo'] + (g - 1) * LFO_SIZE

    def trig_led(self, v, level):
        """What the trigger-LED hook makes of `level` for voice v."""
        self.leds.clear()
        self.e.call(self.cave['pk_lf_trig_led'], 0x4f - v, level, max_insns=100_000)
        return self.leds[0x4f - v]

    def sync_key(self):
        self.e.call(self.cave['pk_lf_sync_key'], LFO, max_insns=1_000_000)


def voice_differs(tunes, v):
    return any(t[v] != t[0 if v else 1] for t in tunes)


class TestPerTrackLfo(unittest.TestCase):
    def test_untouched_is_stock(self):
        """No trigger keys held: what the voices get is what stock sends."""
        runs = []
        for mod in (False, True):
            r = Rig(mod)
            r.turn(RATE, 0.8)
            r.turn(LEVEL, 0.6)
            runs.append(r.tunes(60))
        self.assertEqual(runs[0], runs[1])
        self.assertTrue(all(len(set(t)) == 1 for t in runs[0]))     # all four voices alike
        self.assertGreater(len({t[0] for t in runs[0]}), 5)         # and modulated

    def test_trigger_held_splits_that_voice(self):
        r = Rig()
        inc = r.inc()
        r.held.add(TRIG1 + 1)
        r.turn(RATE, 0.95)
        r.held.clear()
        self.assertEqual(r.inc(), inc)                              # main LFO unchanged
        t = r.tunes(200)
        self.assertTrue(voice_differs(t, 1))
        self.assertTrue(all(x[0] == x[2] == x[3] for x in t))       # the others follow main

    def test_with_eight_tracks(self):
        r = Rig(('eight_lanes',))
        r.held.add(TRIG1 + 3)
        r.turn(RATE, 0.95)
        r.held.clear()
        t = r.tunes(200)
        self.assertTrue(voice_differs(t, 3))
        self.assertTrue(all(x[0] == x[1] == x[2] for x in t))

    def test_selection_follows_the_knobs_main_keeps_its_value(self):
        r = Rig()
        inc = r.inc()
        r.held.add(TRIG1)
        r.turn(RATE, 0.9)
        r.held.clear()
        g = r.inc(r.group_obj(0))
        r.poll(20)
        r.turn(RATE, 0.5)                                           # no key: the selection
        self.assertEqual(r.inc(), inc)
        self.assertNotEqual(r.inc(r.group_obj(0)), g)

    def selection_elsewhere(self, catch):
        """Group A turned to RATE 0.9; then SYNC with voice 2 held selects a new group B,
        a copy of the main LFO (rate 0.3), with the RATE knob still at 0.9."""
        r = Rig()
        r.e.w8(SYM.g['device_config'] + 0x04, catch)                # pot-catch
        r.held.add(TRIG1)
        r.turn(RATE, 0.9)
        r.held = {TRIG1 + 1}
        r.sync_key()
        r.sync_key()                                                # SYNC back off
        r.held.clear()
        return r, r.inc(r.group_obj(1))

    def test_pot_catch_picks_the_selection_up(self):
        r, b = self.selection_elsewhere(1)
        r.turn(RATE, 0.6)
        self.assertEqual(r.inc(r.group_obj(1)), b, 'not caught yet')
        r.turn(RATE, 0.25, steps=16)                                # passes 0.3
        self.assertNotEqual(r.inc(r.group_obj(1)), b)

    def test_without_pot_catch_the_selection_jumps_once_turned(self):
        r, b = self.selection_elsewhere(0)
        r.turn(RATE, 0.6)
        self.assertNotEqual(r.inc(r.group_obj(1)), b)

    def test_held_keys_form_one_group(self):
        r = Rig()
        r.held.update({TRIG1, TRIG1 + 1})
        r.turn(RATE, 0.95)
        r.held.clear()
        self.assertEqual(r.group_obj(0), r.group_obj(1))
        t = r.tunes(200)
        self.assertTrue(all(x[0] == x[1] and x[2] == x[3] for x in t))
        self.assertTrue(any(x[0] != x[2] for x in t))

    def test_reset_rate_merges_with_the_selections_settings(self):
        r = Rig()
        r.held.add(TRIG1 + 2)
        r.turn(LEVEL, 0.0)                                          # the group: no modulation
        r.held = {RESET}
        r.turn(RATE, 0.34)
        r.held = set()
        t = r.tunes(100)
        self.assertTrue(all(len(set(x)) == 1 for x in t))
        self.assertEqual(len({x[0] for x in t}), 1)                 # everyone: level 0

    def test_trigger_leds(self):
        r = Rig()
        levels = lambda: [r.trig_led(v, 0) for v in range(4)]
        self.assertEqual(levels(), [0, 0, 0, 0])                    # one group: stock
        r.held.add(TRIG1)
        r.turn(RATE, 0.9)
        r.held = {TRIG1 + 3}
        r.turn(RATE, 0.4)                                           # the selection now
        r.held.clear()
        r.poll(30)
        lv = levels()
        self.assertEqual((lv[0], lv[1], lv[2]), (0x10, 0, 0))       # own group / main group
        self.assertGreaterEqual(lv[3], 0x10)                        # the selection: with its LFO
        self.assertEqual(r.trig_led(0, 0xff), 0xff)                 # hits and mutes: stock

    def test_level_and_wave_split_too(self):
        r = Rig()
        r.turn(RATE, 0.9)                                           # main: fast enough to see
        r.held.add(TRIG1 + 2)
        r.turn(LEVEL, 0.0)
        r.held.clear()
        t = r.tunes(100)
        self.assertEqual(len({x[2] for x in t}), 1)                 # voice 3: no modulation
        self.assertGreater(len({x[0] for x in t}), 5)               # the rest still moving
        r.held.add(TRIG1 + 3)
        r.turn(WAVE, 0.7)
        r.held.clear()
        self.assertTrue(voice_differs(r.tunes(200), 3))

    def test_small_jitter_while_playing_does_not_split(self):
        r = Rig()
        r.held.add(TRIG1 + 1)
        r.turn(RATE, 0.31)                                          # 1 %: below the threshold
        r.held.clear()
        self.assertFalse(voice_differs(r.tunes(200), 1))

    def test_reset_and_rate_rejoin_all(self):
        r = Rig()
        r.held.add(TRIG1 + 1)
        r.turn(RATE, 0.95)
        r.held = {TRIG1 + 3}
        r.turn(LEVEL, 0.2)
        r.held = {RESET}
        r.turn(RATE, 0.34)
        r.held = set()
        t = r.tunes(200)
        self.assertTrue(all(len(set(x)) == 1 for x in t))

    def test_sync_with_trigger_held_is_that_voice_only(self):
        r = Rig()
        r.held.add(TRIG1 + 2)
        r.sync_key()
        r.held.clear()
        self.assertEqual(r.e.r8(LFO + LFO_SYNC), 0)                 # main: still free
        self.assertEqual(r.e.r8(r.group_obj(2) + LFO_SYNC), 1)
        r.sync_key()                                                # no key: the selection
        self.assertEqual((r.e.r8(r.group_obj(2) + LFO_SYNC), r.e.r8(LFO + LFO_SYNC)), (0, 0))

    def test_clearing_a_track_or_pattern_rejoins_all(self):
        vs = lambda e, t: e.r32(e.r32(0x1002e6e4) + 4) + 0x10c * t + 0
        for hook, arg in (('pk_ev_track_clear', lambda e: vs(e, 2)),
                          ('pk_ev_automation_clear', lambda e: vs(e, 2) + 0x4c),
                          ('pk_ev_pattern_clear', lambda e: 0x100026d0 + 0x20 * 5)):
            r = Rig()
            r.held.add(TRIG1 + 1)
            r.turn(RATE, 0.95)
            r.held.clear()
            self.assertTrue(voice_differs(r.tunes(200), 1), hook)
            r.e.call(r.cave[hook], arg(r.e), max_insns=1_000_000)
            self.assertTrue(all(len(set(x)) == 1 for x in r.tunes(200)), hook)

    def test_restart_restarts_split_lfos(self):
        r = Rig()
        r.held.add(TRIG1 + 1)
        r.turn(RATE, 0.95)
        r.held.clear()
        r.poll(50)
        r.e.call(r.cave['pk_lf_reset'], LFO, max_insns=1_000_000)
        lfo = r.group_obj(1)
        self.assertEqual((r.e.r8(LFO + 0x27) & 1, r.e.r8(lfo + 0x27) & 1), (1, 1))

    def test_led_shows_the_held_voice_else_the_selection(self):
        r = Rig()
        r.held.add(TRIG1 + 1)
        r.turn(RATE, 0.95)
        r.poll(37)
        out = lambda a: struct.unpack('<f', bytes(r.e.uc.mem_read(a + 0x20, 4)))[0]
        self.assertEqual(r.led(), out(r.group_obj(1)))
        r.held = {TRIG1}                                            # a voice in the main group
        self.assertEqual(r.led(), out(LFO))
        r.held = set()
        self.assertEqual(r.led(), out(r.group_obj(1)))              # the selection
        self.assertNotEqual(out(r.group_obj(1)), out(LFO))


class TestSenderAssumption(unittest.TestCase):
    """pk_lf_voice relies on the stock sender keeping the LFO output in s17 for its
    per-voice loop: set from the update's result before the loop, read in the loop body,
    never written in it. A new firmware that allocates registers differently fails here."""

    def test_s17_holds_the_lfo_output_through_the_loop(self):
        from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, Cs
        img, _ = image(False)
        seg = img.segment('m4')
        site = SYM.site('ptlfo.voice.0810119e')['addr']
        update = SYM.site('ptlfo.update.0810117c')['addr']
        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
        start, end = update, site + 0x2c0
        insns = list(md.disasm(seg.data[start - seg.addr:end - seg.addr], start))
        before = [i for i in insns if update < i.address < site]
        self.assertTrue(any(i.mnemonic.startswith('vmov') and i.op_str.startswith('s17, s0') for i in before))
        loop = [i for i in insns if i.address > site]
        reads = [i for i in loop if 's17' in i.op_str.split(',', 1)[-1]]
        writes = [i for i in loop if i.op_str.startswith('s17') and not i.mnemonic.startswith('vpop')]
        self.assertTrue(reads)
        self.assertEqual(writes, [])


class TestBeforeBoot(unittest.TestCase):
    """The knob poll (and the sender it runs) is registered before boot_init, where the
    host zeroes the mods' RAM: on power-up that RAM holds garbage."""

    def test_poll_before_boot_with_garbage_ram(self):
        import random
        img, _ = image(True)
        sym = Symbols(os.path.join(PERKONS, 'symbols', 'v1.3.0-m4.json'))
        e = M4Emu(img.segment('m4').data, sym, img.segment('m7').data, sd={}).boot()
        rnd = random.Random(1)
        for lo, hi in ((0x1002ff00, 0x10040000), (0x24004000, 0x24010000)):   # patch RAM, AXI gap
            e.uc.mem_write(lo, bytes(rnd.getrandbits(8) for _ in range(hi - lo)))
        stub_hardware(e, sym)
        for f in (sym.fn['knob_handler'], sym.fn['midi_out_bytes']):
            e.stub(f, lambda *a: 0)
        if not e.r32(sym.g['knobs_ptr']):
            e.w32(sym.g['knobs_ptr'], 0x2407f000)
        e.call(sym.fn['seq_setup'], max_insns=20_000_000)
        e.sent(1)
        for _ in range(20):
            e.call(KNOB_POLL, max_insns=5_000_000)
        p = e.sent(1)[-1][1]
        self.assertEqual(len({struct.unpack_from('<H', p, 12 * v)[0] for v in range(4)}), 1)


if __name__ == '__main__':
    unittest.main()
