"""Eight-lanes: lane MIDI settings in system/mods.json and the MIDI page."""
import json
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'harness'))
from lanes_build import UI, lanes_harness  # noqa: E402

DEVICE = 0x10000784
SHIFT = 0x47
MIDI_VIEW_MULTI, MIDI_DIRTY = 0x1002c7e7, 0x1002c7e6


def lane_note_ons(h, lane, step=2):
    for base in (0x50, 0x6a):
        h.e.uc.mem_write(h.voice_state(lane) + base, struct.pack('<H', 32768))
    h.e.uc.mem_write(h.voice_state(lane) + 0x50 + 16, struct.pack('<H', 1))
    h.e.uc.mem_write(h.voice_state(lane) + 0x6a + 16, struct.pack('<H', 1))
    h.set_step(lane, step, 60, 100)
    out = []
    h.e.stub(h.sym.fn['midi_out_bytes'], lambda emu, port, packed, *_: out.append(h.decode_midi((port, packed)).hex()))
    h.play()
    h.run(step + 2)
    return [m for m in out if m[0] == '9']


class TestLaneConfig(unittest.TestCase):
    def test_defaults_channels_5_to_8_and_trigger_notes_40_to_43(self):
        h = lanes_harness()
        s = h.cave
        self.assertEqual([h.e.r8(s[f'pk_el_ch{n}']) for n in range(5, 9)], [4, 5, 6, 7])
        self.assertEqual([h.e.r8(s[f'pk_el_tn{n}']) for n in range(5, 9)], [40, 41, 42, 43])

    def test_settings_load_from_mods_json(self):
        mods = {'lane5-midi-channel': 9, 'lane7-trig-note': 50}
        h = lanes_harness(sd={'system/mods.json': json.dumps(mods).encode()})
        h.e.w8(DEVICE + 0x1d, 1)
        self.assertEqual(lane_note_ons(h, 4), ['993c64'])            # lane 5 on channel 10
        h = lanes_harness(sd={'system/mods.json': json.dumps(mods).encode()})
        self.assertEqual(lane_note_ons(h, 6), ['903264'])            # single: lane 7 note 50

    def test_midi_page_with_shift_sets_lane_channels_and_saves(self):
        h = lanes_harness()
        ui = UI(h)
        h.e.w8(MIDI_VIEW_MULTI, 1)
        ui.held.add(SHIFT)
        ev = 0x2407ff00
        h.e.uc.mem_write(ev, bytes([0x20 + 12, 0x11]))               # row 3 (lane 7), channel 13
        h.e.call(h.cave['pk_el_midi_page_event'], ev, max_insns=5_000_000)
        self.assertEqual((h.e.r8(h.cave['pk_el_ch7']), h.e.r8(MIDI_DIRTY)), (12, 1))
        self.assertEqual(h.e.r8(DEVICE + 0x1e + 2), 2)               # voice 3 untouched
        ui.leds.clear()
        h.e.call(h.cave['pk_el_midi_page_render'], max_insns=5_000_000)
        self.assertEqual((ui.leds.get(0x20 + 12), ui.leds.get(0x20 + 2)), (0x80, 0))
        h.e.call(h.cave['pk4_device_json_save'], max_insns=50_000_000)
        self.assertEqual(json.loads(h.e.sd_written['system/mods.json'])['lane7-midi-channel'], 12)
        self.assertNotIn('lane7-midi-channel', h.e.sd_written['system/device.json'].decode())

    def test_midi_page_without_shift_is_stock(self):
        h = lanes_harness()
        UI(h)
        h.e.w8(MIDI_VIEW_MULTI, 1)
        ev = 0x2407ff00
        h.e.uc.mem_write(ev, bytes([0x20 + 12, 0x11]))
        h.e.call(h.cave['pk_el_midi_page_event'], ev, max_insns=5_000_000)
        self.assertEqual((h.e.r8(DEVICE + 0x1e + 2), h.e.r8(h.cave['pk_el_ch7'])), (12, 6))


if __name__ == '__main__':
    unittest.main()
