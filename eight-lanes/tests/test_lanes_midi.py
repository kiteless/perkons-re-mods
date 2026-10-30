"""Eight-lanes: lanes 5-8 as MIDI, built image in the harness."""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'harness'))
from lanes_build import lanes_harness  # noqa: E402

DEVICE = 0x10000784
TUNE, DECAY, RANGE, OCT = 0, 4, 8, 9          # stock slot numbers


class TestLanesMidi(unittest.TestCase):
    def harness(self, multi=True, tune=32768, decay=0, rng=1, octave=0, lanes=range(4, 8)):
        h = lanes_harness()
        h.e.w8(DEVICE + 0x1d, 1 if multi else 0)
        for t in lanes:
            vs = h.voice_state(t)
            for slot, v in ((TUNE, tune), (DECAY, decay), (RANGE, rng), (OCT, octave)):
                for base in (0x50, 0x6a):
                    h.e.uc.mem_write(vs + base + 2 * slot, struct.pack("<H", v))
        return h

    def events(self, h, steps):
        """[(step, sub-tick, bytes)] of everything sent while running."""
        ev = []
        h.e.stub(h.sym.fn['midi_out_bytes'], lambda emu, port, packed, *_: ev.append(
            (h.r16(0x1000068c + 0x20), h.r16(0x1000068c + 0x22), h.decode_midi((port, packed)).hex())))
        h.play()
        h.run(steps)
        return ev

    def test_multi_channel_notes_on_lane_channels(self):
        h = self.harness()
        h.set_step(4, 2, 60, 90)
        h.set_step(7, 3, 48, 70)
        notes = [b for _, _, b in self.events(h, 5) if b[0] == '9']
        self.assertEqual(notes, ['943c5a', '973046'])          # ch 5 note 60, ch 8 note 48

    def test_tune_and_switches_shift_the_note(self):
        cases = [  # (tune, range switch, octave switch) -> note for step note 60
            ((32768, 1, 0), 60), ((49152, 1, 0), 66), ((65535, 1, 0), 72),   # +-1 octave
            ((49152, 0, 0), 72), ((49152, 2, 0), 84),                         # +-2, +-4
            ((32768, 1, 1), 72), ((32768, 1, 2), 48),                         # octave up/down
        ]
        for (tune, rng, octv), want in cases:
            with self.subTest(tune=tune, rng=rng, octave=octv):
                h = self.harness(tune=tune, rng=rng, octave=octv)
                h.set_step(5, 2, 60, 100)
                on = [b for _, _, b in self.events(h, 4) if b.startswith('95')]
                self.assertEqual(on, [f'95{want:02x}64'])

    def test_single_channel_sends_lane_trigger_notes(self):
        h = self.harness(multi=False)
        h.set_step(4, 2, 60, 90)
        h.set_step(6, 2, 72, 90)
        on = sorted(b for _, _, b in self.events(h, 4) if b[0] == '9')
        self.assertEqual(on, ['90285a', '902a5a'])             # notes 40 and 42, shared channel

    def test_decay_sets_the_gate(self):
        def gate_len(decay):
            h = self.harness(decay=decay)
            h.set_step(4, 2, 60, 100)
            ev = self.events(h, 8)
            on = next((s, t) for s, t, b in ev if b.startswith('94'))
            off = next(((s, t) for s, t, b in ev if b.startswith('84')), None)
            return None if off is None else (off[0] - on[0]) * 288 + off[1] - on[1]
        self.assertLessEqual(gate_len(0), 2)                    # blip
        self.assertAlmostEqual(gate_len(32768), 288, delta=3)   # one step
        self.assertGreater(gate_len(50000), 288)                 # longer
        self.assertIsNone(gate_len(65535))                       # tie: held

    def test_tie_steps_hold_the_note(self):
        h = self.harness(decay=0)                                   # blip gate
        h.set_step(4, 2, 60, 100)
        for s in (3, 4):
            h.e.w8(h.block(4) + 8 * s, 3)                           # tie steps 4 and 5
        ev = self.events(h, 8)
        on = next(i for i, (_, _, b) in enumerate(ev) if b.startswith('94'))
        off = next(s for s, _, b in ev[on:] if b.startswith('84'))
        self.assertEqual(off - ev[on][0], 3)                        # released after the ties

    def test_lane_roll_repeats_at_the_rate_while_held(self):
        h = self.harness()
        h.e.uc.mem_write(h.cave['pk_el_page'], b'\x01')
        h.e.call(h.cave['pk_el_roll_rate_set'], 1, 7, max_insns=100_000)   # 1/4 step (72)
        h.e.call(h.cave['pk_el_roll_hold'], 1, 1, max_insns=100_000)       # lane 6
        ev = self.events(h, 2)
        ons = [(s, t) for s, t, b in ev if b.startswith('95')]
        self.assertEqual(len(ons), 8)                                       # 2 steps / (1/4)
        h.e.call(h.cave['pk_el_roll_hold'], 1, 0, max_insns=100_000)
        n = len([b for _, _, b in ev if b.startswith('95')])
        h.run(1)
        self.assertEqual(len([b for _, _, b in ev if b.startswith('95')]), n)

    def test_muted_lane_and_seq_out_off_send_nothing(self):
        h = self.harness()
        h.set_step(4, 2, 60, 100)
        h.e.w8(h.voice_state(4) + 0x108, 1)
        self.assertEqual([b for _, _, b in self.events(h, 4) if b[0] in '89'], [])
        h = self.harness()
        h.set_step(4, 2, 60, 100)
        h.e.w8(DEVICE + 0x19, 0)
        self.assertEqual([b for _, _, b in self.events(h, 4) if b[0] in '89'], [])

    def test_stop_ends_held_notes(self):
        h = self.harness(decay=65535)
        h.set_step(4, 2, 60, 100)
        ev = self.events(h, 4)
        self.assertFalse(any(b.startswith('84') for _, _, b in ev))
        h.e.w8(h.seq, 0)                                         # transport stopped
        h.step()
        self.assertTrue(any(b.startswith('84') for _, _, b in ev))

    def test_tracks_1_to_4_unchanged(self):
        h = self.harness()
        h.set_step(0, 2, 40, 100)
        h.play()
        self.assertEqual([t for _, t, _ in h.run(4) if t], [[[(0, 40)], []]])


if __name__ == '__main__':
    unittest.main()
