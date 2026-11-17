"""off-grid recording: the trigger keys and MIDI notes record on the nearest step, early or
late, as played (based on seq-unquantized's tests)."""
import math
import os
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PERKONS = os.environ.get('PERKONS_RE') or next(
    (p for p in (os.path.join(HERE, '..', '..', '..', d) for d in ('perkons', 'perkons-re'))
     if os.path.isdir(p)), '')
sys.path[:0] = [os.path.join(PERKONS, 'tools'), os.path.join(PERKONS, 'tests')]
os.environ.setdefault('PERKONS_MODS', os.path.join(HERE, '..', '..'))

from fixtures import build_patched, require_image  # noqa: E402
from perkons.emu import Symbols  # noqa: E402
from perkons.fwimage import Image  # noqa: E402
from perkons.rig import M4Rig  # noqa: E402

SYM = Symbols(os.path.join(PERKONS, 'symbols', 'v1.3.0-m4.json'))
REC = SYM.g['rec_flags'] + 1
TRIG = 0x4b                   # trigger key 1
DC = SYM.g['device_config']
MIDI_MSG = 0x2407fe00         # scratch for a MIDI message
STEP_TICKS = 24
_image = []


def image():
    if not _image:
        img, p = build_patched(Image.load(require_image('v1.3.0')), ['off_grid'], tempfile.mkdtemp())
        _image.append((img, p.cave_symbols['m4host']))
    return _image[0]


def placed(step, tick):
    """Where a hit at `tick` of `step` goes, and its delay: this step late in its first part
    (stock's choice: sub-tick < 12, ticks 0-10), else the next step early."""
    if tick <= 10:
        return step, math.ceil(100 * tick / STEP_TICKS)
    return (step + 1) % 16, -math.ceil(100 * (STEP_TICKS - tick) / STEP_TICKS)


class Rig(M4Rig):
    """Clocked one sub-tick at a time, so a key can land anywhere in a step."""

    def __init__(self, on=True):
        super().__init__(*image())
        self.e.w8(self.cave['pk_cfg_unquantized'], 1 if on else 0)
        self.sub = 0
        self.fired = []           # (step, tick) of each trigger the sequencer sent for track 1
        # the MIDI input as the firmware sets it up at init: channels and callbacks
        self.e.call(self.sym.fn['midi_in_init'], self.sym.g['midi_channels'], 4, self.sym.g['midi_callbacks'],
                    max_insns=5_000_000)

    def tick(self):
        c = self.clock
        n = self.r16(c + 0x1c) * self.r16(c + 0x1e)
        if self.sub % n == 0:
            self.w16(c + 0x22, 0)
            self.w16(c + 0x20, self.r16(c + 0x20) + 1)
            self.e.call(self.e.r32(c + 0x3c) & ~1, 1, max_insns=5_000_000)
        else:
            self.subtick()
        self.sub += 1
        vs = self.voice_state(0)
        if any(p[0] for typ, p in self.e.sent(2) if typ == 0):
            self.fired.append((self.r16(vs + 0x1c), self.r16(vs + 0x24)))

    def to(self, step, tick):
        """Clock until track 1 reaches `tick` ticks into `step` (the next time it gets there)."""
        vs = self.voice_state(0)
        for _ in range(288 * 40):
            was = (self.r16(vs + 0x1c), self.r16(vs + 0x24))
            self.tick()
            if was != (step, tick) == (self.r16(vs + 0x1c), self.r16(vs + 0x24)):
                return
        raise AssertionError(f'never reached step {step} tick {tick}')

    def hit(self, track=0):
        """A trigger key tap. The voice plays at once (sent on the next sub-tick): that
        one isn't counted in `fired`."""
        self.event(TRIG + track, True)
        self.event(TRIG + track, False)
        self.e.sent(2)
        n = len(self.fired)
        self.tick()
        del self.fired[n:]

    def note(self, note, vel=100, ch=0):
        """A MIDI note-on through the MIDI input (the voice plays at once, not counted in `fired`)."""
        self.e.uc.mem_write(MIDI_MSG, bytes([0x90 | ch, note, vel, 0]))
        self.e.call(self.sym.fn['midi_dispatch'], MIDI_MSG, max_insns=5_000_000)
        self.e.sent(2)
        n = len(self.fired)
        self.tick()
        del self.fired[n:]

    def rec(self, on=True):
        self.e.w8(REC, 2 if on else 0)

    def step_rec(self, step, track=0):
        a = self.block(track) + 8 * step
        delay = struct.unpack('<h', bytes(self.e.uc.mem_read(a + 2, 2)))[0]
        return {'on': self.e.r8(a), 'delay': delay, 'vel': self.e.r8(a + 7)}

    def step_note(self, step, track=0):
        return self.e.r8(self.block(track) + 8 * step + 6)

    def set_delay(self, step, d, track=0):
        self.e.uc.mem_write(self.block(track) + 8 * step + 2, struct.pack('<h', d))

    def ons(self, track=0):
        return [s for s in range(16) if self.step_rec(s, track)['on']]

    def start(self):
        self.play()
        self.tick()

    def a_pass(self):
        """Clock a whole pass from where the track is: what track 1 fired."""
        self.fired.clear()
        for _ in range(STEP_TICKS * 12 * 16):
            self.tick()
        return self.fired


class TestRecord(unittest.TestCase):
    def test_config_key_led_off_quantized_on_off_grid(self):
        """Row 3 step 13 on the config page: off at power-on (quantized, as stock), a press
        turns it on with its LED lit, another press off again."""
        r = M4Rig(*image())
        key = 0x20 + 12
        evt = 0x2407ff40

        def press():
            r.e.uc.mem_write(evt, bytes([key, 0x11, 0, 0, 0, 0, 0, 0]))
            r.e.call(r.cave['pk4_cfg_event'], evt, max_insns=5_000_000)

        def led():
            r.e.call(r.cave['pk4_cfg_render'], 0, 0, 0, 0, max_insns=5_000_000)
            return r.leds.get(key)

        self.assertEqual((r.e.r8(r.cave['pk_cfg_unquantized']), led()), (0, 0))
        press()
        self.assertEqual((r.e.r8(r.cave['pk_cfg_unquantized']), led()), (1, 0x80))
        press()
        self.assertEqual((r.e.r8(r.cave['pk_cfg_unquantized']), led()), (0, 0))

    def test_early_in_a_step_records_it_late(self):
        r = Rig()
        r.start()
        r.rec()
        r.to(5, 7)
        r.hit()
        self.assertEqual((r.ons(), r.step_rec(5)), ([5], {'on': 1, 'delay': 30, 'vel': 0x7f}))   # 30 % of 24: tick 7
        r.fired.clear()
        r.to(5, 23)                       # the rest of this pass: it doesn't play again
        self.assertEqual(r.fired, [])
        self.assertEqual(r.a_pass(), [(5, 7)])

    def test_late_in_a_step_records_the_next_step_early(self):
        r = Rig()
        r.start()
        r.rec()
        r.to(5, 20)
        r.hit()
        self.assertEqual((r.ons(), r.step_rec(6)), ([6], {'on': 1, 'delay': -17, 'vel': 0x7f}))  # 4 ticks early
        r.fired.clear()
        r.to(6, 23)                       # the rest of this pass: it doesn't play again
        self.assertEqual(r.fired, [])
        self.assertEqual(r.a_pass(), [(6, 20)])                    # 20 ticks into step 6: 4 before step 7

    def test_every_tick_plays_back_where_it_was_played(self):
        """A hit at each tick (12 steps apart, so they don't share a step) plays back at that
        tick, every time round."""
        for tick in range(STEP_TICKS):
            with self.subTest(tick=tick):
                r = Rig()
                r.start()
                r.rec()
                r.to(4, tick)
                r.hit()
                step, delay = placed(4, tick)
                self.assertEqual((r.ons(), r.step_rec(step)['delay']), ([step], delay))
                self.assertEqual(r.a_pass(), [(step, tick)])   # an early step starts at its hit's tick

    def test_the_last_step_wraps_to_the_first(self):
        r = Rig()
        r.start()
        r.rec()
        r.to(15, 18)
        r.hit()
        self.assertEqual((r.ons(), r.step_rec(0)['delay']), ([0], -25))
        self.assertEqual(r.a_pass(), [(0, 18)])

    def test_backwards(self):
        """Reverse: the next step is the one before."""
        r = Rig()
        r.e.w8(r.block(0) + 0x82, 1)    # play mode BWD
        r.start()
        r.rec()
        r.to(9, 17)
        r.hit()
        self.assertEqual((r.ons(), r.step_rec(8)['delay']), ([8], -30))
        self.assertEqual(r.a_pass(), [(8, 17)])

    def test_other_track_rates(self):
        for rate in (2, 5, 7):          # /2, x2, x4
            with self.subTest(rate=rate):
                r = Rig()
                r.e.w8(r.block(0) + 0x86, rate)
                r.start()
                r.rec()
                r.to(2, 13)
                r.hit()
                self.assertEqual(r.step_rec(3)['delay'], -46)
                at = r.sub
                r.to(4, 0)
                pass_len = (r.sub - at) * 16 // 2       # about two steps went by: a pass at this rate
                r.fired.clear()
                while not r.fired and r.sub - at < 3 * pass_len:
                    r.tick()
                # the first time it plays is next pass, at the tick it was played
                self.assertEqual(r.fired, [(3, 13)])
                self.assertGreater(r.sub - at, pass_len // 2)

    def test_off_is_stock(self):
        r = Rig(on=False)
        r.start()
        r.rec()
        r.to(3, 20)
        r.hit()
        self.assertEqual((r.ons(), r.step_rec(4)), ([4], {'on': 1, 'delay': 0, 'vel': 0x7f}))
        r.to(6, 3)
        r.hit()
        self.assertEqual(r.step_rec(6), {'on': 1, 'delay': 0, 'vel': 0x7f})

    def test_without_rec_nothing_is_written(self):
        r = Rig()
        r.start()
        r.to(5, 7)
        r.hit()
        self.assertEqual(r.ons(), [])

    def test_stopped_plays_the_voice_and_writes_nothing(self):
        r = Rig()
        r.rec()
        r.hit()
        self.assertEqual(r.ons(), [])

    def test_other_tracks(self):
        r = Rig()
        r.start()
        r.rec()
        r.to(9, 9)
        r.hit(track=3)
        self.assertEqual(r.step_rec(9, track=3), {'on': 1, 'delay': 38, 'vel': 0x7f})
        self.assertEqual(r.ons(), [])


class TestNextToOffGridSteps(unittest.TestCase):
    """Recording next to steps already off the grid (moved with TEMPO, or recorded early or
    late): every hit plays at the tick it was played, and nothing is left on an off step."""

    def test_a_late_step_not_played_yet_is_replaced(self):
        """Step 5 is 20 ticks late; a hit at tick 15 goes in step 5 (its hit hadn't come yet),
        not early in step 6, where it would cross step 5 and one of them would be lost."""
        r = Rig()
        r.set_step(0, 5)
        r.set_delay(5, 84)
        r.start()
        r.rec()
        r.to(5, 15)
        r.hit()
        self.assertEqual((r.ons(), r.step_rec(5)['delay'], r.step_rec(6)['delay']), ([5], 63, 0))
        self.assertEqual(r.a_pass(), [(5, 15)])

    def test_while_the_next_step_has_started_early(self):
        """Step 6 is 20 ticks early, so the track is on step 6 from tick 4 of step 5: hits
        then go in step 6, early by what's left of step 5."""
        for tick, delay in ((8, -67), (15, -38)):
            with self.subTest(tick=tick):
                r = Rig()
                r.set_step(0, 6)
                r.set_delay(6, -84)
                r.start()
                r.rec()
                r.to(6, tick)             # step 6 playing early, `tick` ticks into step 5's time
                r.hit()
                self.assertEqual((r.ons(), r.step_rec(6)['delay'], r.step_rec(7)['delay']), ([6], delay, 0))
                self.assertEqual(r.a_pass(), [(6, tick)])

    def test_midi_while_the_next_step_has_started_early(self):
        r = Rig()
        r.set_step(0, 6)
        r.set_delay(6, -84)
        r.start()
        r.rec()
        r.to(6, 15)
        r.note(36)
        self.assertEqual((r.ons(), r.step_rec(6)['delay'], r.step_rec(7)), ([6], -38, {'on': 0, 'delay': 0, 'vel': 0}))
        self.assertEqual(r.a_pass(), [(6, 15)])

    def test_overdub_next_to_recorded_early_hits(self):
        """Early hits, then hits just after the same beats: each beat's later hit replaces its
        early one (one hit per step), plays where it was played, and the steps before stay
        empty."""
        r = Rig()
        r.start()
        r.rec()
        for step in (4, 8, 12):
            r.to(step - 1, 20)            # 4 ticks before each
            r.hit()
        for step in (4, 8, 12):
            r.to(step, 2)                 # then 2 ticks after each beat
            r.hit()
        self.assertEqual(r.ons(), [4, 8, 12])   # one hit per step: the later ones replace them
        self.assertEqual([r.step_rec(s)['delay'] for s in (3, 7, 11)], [0, 0, 0])
        self.assertEqual(r.a_pass(), [(4, 2), (8, 2), (12, 2)])


class TestMidiSameHit(unittest.TestCase):
    def test_the_same_hit_again_still_gets_its_timing(self):
        """Stock rewrites a step as it was (same note, same velocity): the timing is set all
        the same."""
        r = Rig()
        r.set_step(0, 5, velocity=0x7f)
        r.start()
        r.rec()
        r.to(5, 7)
        r.note(36)
        self.assertEqual(r.step_rec(5), {'on': 1, 'delay': 30, 'vel': 0x7f})

    """MIDI notes record through the MIDI input's own path (single channel by default:
    notes 36-39 play voices 1-4)."""

    def test_a_note_records_on_the_nearest_step(self):
        for tick in (7, 20):            # this step late / the next early
            with self.subTest(tick=tick):
                r = Rig()
                r.start()
                r.rec()
                r.to(5, tick)
                r.note(36)
                step, delay = placed(5, tick)
                self.assertEqual((r.ons(), r.step_rec(step)), ([step], {'on': 1, 'delay': delay, 'vel': 0x7f}))
                r.fired.clear()
                r.to(6, 23)
                self.assertEqual(r.fired, [])
                self.assertEqual(r.a_pass(), [(step, tick)])

    def test_multi_channel_note_and_velocity(self):
        r = Rig()
        r.e.w8(DC + 0x1d, 1)                            # multi channel: voice n on channel n
        r.e.w8(DC + 0x1b, 1)                            # midi-velocity
        for v in range(4):
            r.e.call(r.sym.fn['midi_in_channel'], v, v, max_insns=100_000)
        r.start()
        r.rec()
        for step, tick in ((3, 5), (8, 18)):
            r.to(step, tick)
            r.note(48 + step, vel=90, ch=1)
        for step, delay, note in ((3, 21, 51), (9, -25, 56)):
            self.assertEqual(r.step_rec(step, track=1), {'on': 1, 'delay': delay, 'vel': 90})
            self.assertEqual(r.step_note(step, track=1), note)
        self.assertEqual(r.ons(track=1), [3, 9])

    def test_the_note_picks_the_voice(self):
        r = Rig()
        r.start()
        r.rec()
        r.to(9, 22)
        r.note(38)
        self.assertEqual(r.step_rec(10, track=2)['delay'], -9)
        self.assertEqual((r.ons(track=0), r.ons(track=2)), ([], [10]))

    def test_other_notes_record_nothing(self):
        r = Rig()
        r.start()
        r.rec()
        r.to(5, 20)
        r.note(60)
        self.assertEqual([r.ons(track=t) for t in range(4)], [[]] * 4)

    def test_off_is_stock(self):
        r = Rig(on=False)
        r.start()
        r.rec()
        r.to(5, 20)
        r.note(36)
        self.assertEqual((r.ons(), r.step_rec(6)), ([6], {'on': 1, 'delay': 0, 'vel': 0x7f}))

    def test_without_rec_nothing_is_written(self):
        r = Rig()
        r.start()
        r.to(5, 7)
        r.note(36)
        self.assertEqual(r.ons(), [])


if __name__ == '__main__':
    unittest.main()
