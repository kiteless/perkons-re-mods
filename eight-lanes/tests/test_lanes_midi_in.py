"""Eight-lanes: MIDI in to lanes 5-8."""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'harness'))
from lanes_build import UI, lanes_harness  # noqa: E402

DEVICE = 0x10000784
REC = 0x100284ad
MSG = 0x2407fe00
HELD_FIRST, HELD_NEXT = 0x0810b794, 0x0810b7a4


class TestLaneMidiIn(unittest.TestCase):
    def harness(self, multi=True):
        h = lanes_harness()
        h.e.w8(DEVICE + 0x1d, 1 if multi else 0)
        h.e.w8(DEVICE + 0x1b, 1)                                 # midi-velocity on
        for lane in range(4, 8):
            for base in (0x50, 0x6a):
                h.e.uc.mem_write(h.voice_state(lane) + base, struct.pack('<H', 32768))
                h.e.uc.mem_write(h.voice_state(lane) + base + 16, struct.pack('<H', 1))
        self.out = []
        h.e.stub(h.sym.fn['midi_out_bytes'], lambda emu, port, packed, *_: self.out.append(
            h.decode_midi((port, packed)).hex()))
        # the MIDI module's init (FUN_08103b00 registers these): channel table + callbacks
        h.e.call(0x08104410, 0x10000730, 4, 0x10000758, max_insns=5_000_000)
        for v in range(4):
            h.e.call(0x081045b8, v, h.e.r8(DEVICE + 0x1e + v), max_insns=100_000)
        h.e.call(0x081045b8, 4, h.e.r8(DEVICE + 0x22), max_insns=100_000)
        self.voice_plays = []
        h.e.stub(0x0810210c, lambda emu, v, on, note, vel, *_: self.voice_plays.append((v, on, note)))
        return h

    def send(self, h, *msg):
        h.e.uc.mem_write(MSG, bytes(msg))
        h.e.call(h.cave['pk_el_midi_in'], MSG, max_insns=20_000_000)

    def test_multi_lane_channel_plays_the_lane(self):
        h = self.harness()
        self.send(h, 0x95, 64, 90)                               # channel 6 = lane 6
        self.send(h, 0x85, 64, 0)
        self.assertEqual(self.out, ['95405a', '854000'])
        self.assertEqual(self.voice_plays, [])

    def test_multi_rec_writes_the_nearest_step(self):
        h = self.harness()
        h.play()
        h.run(3)
        h.e.w8(REC, 1)
        self.send(h, 0x94, 67, 70)                               # lane 5
        # late in the step (the run ends on its last sub-tick): the next step, as stock
        step = h.r16(h.voice_state(4) + 0x20)
        rec = bytes(h.e.uc.mem_read(h.block(4) + 8 * step, 8))
        self.assertEqual((rec[0], rec[6], rec[7]), (1, 67, 70))

    def test_single_trigger_note_plays_lane_and_others_go_to_voices(self):
        h = self.harness(multi=False)
        self.send(h, 0x90, 41, 100)                              # lane 6's trigger note
        self.send(h, 0x90, 36, 100)                              # voice 1's
        self.assertEqual(self.out, ['902964'])
        self.assertEqual([v for v, on, _ in self.voice_plays if on], [0])

    def test_step_entry_on_page_b(self):
        h = self.harness()
        ui = UI(h)
        h.e.uc.mem_write(h.cave['pk_el_page'], b'\x01')
        held = [0x10 + 2, 0x10 + 6]                              # row 1 (lane 6), steps 3 and 7
        state = {'i': 0}
        h.e.stub(0x0810b784, lambda emu, *_: 1)
        h.e.stub(HELD_FIRST, lambda emu, it, *_: state.__setitem__('i', 0))

        def nxt(emu, it, *_):
            i = state['i']
            state['i'] += 1
            return held[i] if i < len(held) else 0xffffffff
        h.e.stub(HELD_NEXT, nxt)
        self.send(h, 0x95, 50, 99)
        got = [bytes(h.e.uc.mem_read(h.block(5) + 8 * s, 8)) for s in (2, 6)]
        self.assertEqual([(r[0], r[6], r[7]) for r in got], [(1, 50, 99), (1, 50, 99)])


if __name__ == '__main__':
    unittest.main()


class TestLaneCC(TestLaneMidiIn):
    def test_cc_in_on_lane_channel_sets_the_lane(self):
        h = self.harness()
        self.send(h, 0xb6, 70, 100)                              # ch 7 = lane 7, CC 70 = TUNE
        self.assertEqual(h.r16(h.voice_state(6) + 0x6a), 100 * 0x204)
        self.assertNotEqual(h.r16(h.voice_state(2) + 0x6a), 100 * 0x204)

    def test_cc_out_for_a_lane_move_goes_on_the_lane_channel(self):
        h = self.harness()
        h.e.uc.mem_write(h.cave['pk_el_page'], b'\x01')
        h.e.call(h.cave['pk_el_record'], h.voice_state(1) + 0x4c, 1, 0x8000, 1, 0, max_insns=5_000_000)
        h.e.call(h.cave['pk_el_cc_out'], 1, 0x03404bb1, max_insns=5_000_000)   # stock: CC 75 on ch 2
        self.assertEqual(self.out[-1], 'b54b40')                 # lane 6's channel
        h.e.w8(DEVICE + 0x1d, 0)
        n = len(self.out)
        h.e.call(h.cave['pk_el_record'], h.voice_state(1) + 0x4c, 1, 0x8000, 1, 0, max_insns=5_000_000)
        h.e.call(h.cave['pk_el_cc_out'], 1, 0x03404bb1, max_insns=5_000_000)
        self.assertEqual(len(self.out), n)                       # single-channel: none
