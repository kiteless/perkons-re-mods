"""Eight-lanes: page B, driven through the patched key handler."""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'harness'))
from lanes_build import UI, lanes_harness  # noqa: E402

SHIFT, PATTERN, KIT, CLEAR = 0x47, 0x40, 0x41, 0x4a
TRIG1 = 0x4b
LED_PATTERN = 0x49
DEVICE = 0x10000784


def to_page_b(ui):
    ui.event(SHIFT, True)
    ui.event(PATTERN, True)
    ui.event(PATTERN, False)
    ui.event(SHIFT, False)


class TestPageB(unittest.TestCase):
    def setUp(self):
        self.h = lanes_harness()
        self.ui = UI(self.h)
        self.e = self.h.e

    def test_page_a_at_power_on(self):
        self.assertEqual(self.ui.page(), 0)

    def test_shift_pattern_flips_and_swallows_the_key_ups(self):
        to_page_b(self.ui)
        self.assertEqual((self.ui.page(), self.ui.mode()), (1, 0))   # no pattern/SHIFT menu
        to_page_b(self.ui)
        self.assertEqual(self.ui.page(), 0)

    def test_again_while_shift_held_flips_back(self):
        self.ui.event(SHIFT, True)
        self.ui.press(PATTERN)
        self.ui.press(PATTERN)
        self.ui.event(SHIFT, False)
        self.assertEqual(self.ui.page(), 0)

    def test_not_a_clean_press_is_stock(self):
        self.ui.event(SHIFT, True)
        self.ui.press(KIT)
        self.ui.event(PATTERN, True)
        self.assertEqual(self.ui.page(), 0)

    def test_step_keys_edit_the_page(self):
        self.ui.press(0x10 + 3)                                      # page A: track 2 step 4
        self.assertEqual((self.e.r8(self.h.block(1) + 24), self.e.r8(self.h.block(5) + 24)), (1, 0))
        to_page_b(self.ui)
        self.ui.press(0x30 + 9)                                      # page B: lane 8 step 10
        self.assertEqual((self.e.r8(self.h.block(7) + 72), self.e.r8(self.h.block(3) + 72)), (1, 0))

    def test_grid_leds_show_the_page(self):
        self.h.set_step(6, 5, 60, 100)                               # lane 7 step 6
        self.h.set_step(2, 9, 60, 100)                               # track 3 step 10
        render = self.h.cave['pk_el_page0_render']
        self.e.call(render, max_insns=5_000_000)
        a = (self.ui.leds.get(0x20 + 9), self.ui.leds.get(0x20 + 5), self.ui.leds.get(LED_PATTERN))
        to_page_b(self.ui)
        self.ui.leds.clear()
        self.e.call(render, max_insns=5_000_000)
        b = (self.ui.leds.get(0x20 + 9), self.ui.leds.get(0x20 + 5), self.ui.leds.get(LED_PATTERN))
        self.assertEqual(a, (0x20, 0, 0))                            # track 3 lit, PATTERN off
        self.assertEqual(b, (0, 0x20, 0x10))                         # lane 7 lit, PATTERN dim

    def test_trigger_keys_play_lanes_live(self):
        self.e.w8(DEVICE + 0x1d, 1)                                  # multi-channel
        midi = []
        self.e.stub(self.h.sym.fn['midi_out_bytes'], lambda emu, port, packed, *_: midi.append(
            self.h.decode_midi((port, packed)).hex()))
        self.ui.press(TRIG1 + 1)                                     # page A: voice 2, no MIDI
        page_a = list(midi)
        to_page_b(self.ui)
        self.ui.press(TRIG1 + 1)                                     # page B: lane 6, ch 6
        self.assertEqual(page_a, [])
        self.assertEqual([m[:2] for m in midi], ['95', '85'])

    def test_engine_controls_follow_the_page_analog_stays(self):
        rec = self.h.cave['pk_el_record']
        vs0, vs4 = self.h.voice_state(0), self.h.voice_state(4)
        to_page_b(self.ui)
        # stock slots: 0 TUNE, 1 PARAM1, 4 DECAY, 5 PARAM2, 8 ALGO (engine: the lane);
        # 2, 3, 6, 7 analog knobs, 10 filter switch (the voice)
        engine = ((0, 0x1234), (1, 0x2345), (4, 0x3456), (5, 0x4567), (8, 2))
        analog = ((2, 0x5678), (3, 0x6789), (6, 0x789a), (7, 0x89ab), (10, 1))
        for slot, val in engine + analog:
            self.e.call(rec, vs0 + 0x4c, slot, val, 0, 0, max_insns=5_000_000)
        for slot, val in engine:
            self.assertEqual(self.h.r16(vs4 + 0x6a + 2 * slot), val, f'slot {slot} -> lane')
            self.assertNotEqual(self.h.r16(vs0 + 0x6a + 2 * slot), val, f'slot {slot} not the voice')
        for slot, val in analog:
            self.assertEqual(self.h.r16(vs0 + 0x6a + 2 * slot), val, f'slot {slot} -> voice')
            self.assertNotEqual(self.h.r16(vs4 + 0x6a + 2 * slot), val, f'slot {slot} not the lane')

    def test_mod_page_shows_lane_values_on_page_b(self):
        self.e.uc.mem_write(self.h.voice_state(5) + 0x50, struct.pack('<H', 0xab00))
        to_page_b(self.ui)
        ptr = self.e.call(self.h.cave['pk_el_mod_values'], 1, max_insns=100_000)
        self.assertEqual(ptr, self.h.voice_state(5) + 0x50)

    def test_shift_trigger_mutes_the_lane(self):
        to_page_b(self.ui)
        self.ui.event(SHIFT, True)
        self.ui.set_mode(1)                                          # SHIFT page (mode 1)
        self.ui.press(TRIG1 + 2)
        self.assertEqual((self.e.r8(self.h.voice_state(6) + 0x108), self.e.r8(self.h.voice_state(2) + 0x108)), (1, 0))


POTS = 0x08103d58              # FUN_08103d58: pot handler (main loop)
POT_MOVED, POT_VALUE, POT_DELTA = 0x08109818, 0x081097e4, 0x081097d0


class TestShiftKnob(unittest.TestCase):
    """SHIFT + knob moves a control on every row by the knob's turn and springs back on
    release, as stock does for voices 1-4; on page B the engine controls do it on the lanes."""

    def setUp(self):
        self.h = lanes_harness()
        self.ui = UI(self.h)
        self.e = self.h.e
        self.moved = {}
        self.e.stub(POT_MOVED, lambda emu, p, *_: 1 if (p & 0xff) in self.moved else 0)
        self.e.stub(POT_VALUE, lambda emu, p, *_: self.moved.get(p & 0xff, (0, 0))[0])
        self.e.stub(POT_DELTA, lambda emu, p, *_: self.moved.get(p & 0xff, (0, 0))[1])
        for t in range(8):
            for slot in range(11):
                self.e.uc.mem_write(self.h.voice_state(t) + 0x6a + 2 * slot, struct.pack('<H', 0x1000 * (t + 1)))

    def values(self, slot):
        return [self.h.r16(self.h.voice_state(t) + 0x6a + 2 * slot) for t in range(8)]

    def turn(self, pot, value, delta):
        self.moved = {pot: (value, delta)}
        self.e.call(POTS, max_insns=50_000_000)
        self.moved = {}

    def release_shift(self):
        self.ui.event(SHIFT, False)
        self.e.call(POTS, max_insns=50_000_000)

    def test_page_a_is_stock(self):
        before = self.values(0)
        self.ui.event(SHIFT, True)
        self.turn(0, 0x2222, 0x100)                                  # column 1 TUNE
        self.assertEqual(self.values(0), [0x2222, 0x2100, 0x3100, 0x4100] + before[4:])
        self.release_shift()
        self.assertEqual(self.values(0), before)

    def test_page_b_engine_controls_move_the_lanes(self):
        before = self.values(4)
        to_page_b(self.ui)
        self.ui.event(SHIFT, True)
        self.turn(8 + 4, 0x2222, 0x100)                              # column 2 DECAY
        self.assertEqual(self.values(4), before[:4] + [0x5100, 0x2222, 0x7100, 0x8100])
        self.release_shift()
        self.assertEqual(self.values(4), before)

    def test_page_b_analog_knobs_stay_with_the_voices(self):
        before = self.values(2)
        to_page_b(self.ui)
        self.ui.event(SHIFT, True)
        self.turn(2, 0x2222, 0x100)                                  # column 1 slot 2 (CUTOFF)
        self.assertEqual(self.values(2), [0x2222, 0x2100, 0x3100, 0x4100] + before[4:])
        self.release_shift()
        self.assertEqual(self.values(2), before)

    def test_rec_during_shift_keeps_the_lanes_moved(self):
        to_page_b(self.ui)
        self.ui.event(SHIFT, True)
        self.turn(0, 0x2222, 0x100)
        self.ui.press(0x46)                                          # REC while SHIFT held
        self.release_shift()
        self.assertEqual(self.values(0)[4:], [0x2222, 0x6100, 0x7100, 0x8100])


if __name__ == '__main__':
    unittest.main()
