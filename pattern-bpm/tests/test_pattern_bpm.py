"""pattern-bpm: tempo saved with a pattern, set again when the pattern starts playing."""
import os
import struct
import sys
import tempfile
import unittest

PERKONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'perkons')
sys.path[:0] = [os.path.join(PERKONS, 'tools'), os.path.join(PERKONS, 'tests')]
os.environ.setdefault('PERKONS_MODS', os.path.join(PERKONS, '..', 'perkons-re-mods'))

from fixtures import build_patched, require_image  # noqa: E402
from perkons.emu import Symbols  # noqa: E402
from perkons.fwimage import Image  # noqa: E402
from perkons.rig import M4Rig  # noqa: E402

SYM = Symbols(os.path.join(PERKONS, 'symbols', 'v1.3.0-m4.json'))
TEMPO = SYM.g['tempo_state']
HEADERS = SYM.g['pat_headers']
CATCH = 0x0d                  # tempo_state: the TEMPO knob holds the set tempo until it gets near
_image = {}


def image(extra=()):
    if extra not in _image:
        img, p = build_patched(Image.load(require_image('v1.3.0')), ['pattern_bpm', *extra], tempfile.mkdtemp())
        _image[extra] = (img, p.cave_symbols['m4host'])
    return _image[extra]


def card():
    return {'BANKS/00/00.PAT': b''}           # a bank folder the firmware writes into


class Rig(M4Rig):
    def __init__(self, sd=None, on=True, extra=()):
        super().__init__(*image(extra), sd=sd if sd is not None else card())
        self.e.w8(self.cave['pk_cfg_pattern_bpm'], 1 if on else 0)

    def tempo(self, bpm=None):
        if bpm is not None:
            self.e.uc.mem_write(TEMPO, struct.pack('<f', bpm))
            self.e.w8(TEMPO + CATCH, 0)
        return round(struct.unpack('<f', bytes(self.e.uc.mem_read(TEMPO, 4)))[0], 2)

    def save(self, p, bank=0):
        """The PATTERN page's save of the playing pattern into slot p (through the chain)."""
        self.e.call(self.cave['pk4_store_pat_save'], HEADERS, bank, p, max_insns=200_000_000)

    def switch(self, p):
        """Queue pattern p, switch now, then the main loop's switch-done step."""
        f = self.sym.fn
        self.e.call(f['seq_queue'], HEADERS + 0x20 * p, max_insns=5_000_000)
        self.e.call(f['seq_switch_now'], max_insns=5_000_000)
        self.e.call(f['pat_switch_done'], max_insns=50_000_000)


class TestPatternBpm(unittest.TestCase):
    def test_saved_tempo_comes_back_with_the_pattern(self):
        r = Rig()
        r.tempo(123.4)
        r.save(3)
        pax = r.e.sd_written['banks/00/03.pax']
        self.assertEqual(pax, b'PKX1BPM1' + struct.pack('<IH', 2, 1234))
        r.tempo(90.0)
        r.switch(3)
        self.assertEqual(r.tempo(), 123.4)
        self.assertEqual(r.e.r8(TEMPO + CATCH), 1, 'the knob catches it, as after the tempo page')

    def test_with_eight_lanes(self):
        r = Rig(extra=('eight_lanes',))
        r.tempo(123.4)
        r.save(3)
        r.tempo(90.0)
        r.switch(3)
        self.assertEqual(r.tempo(), 123.4)
        self.assertIn(b'BPM1', r.e.sd_written['banks/00/03.pax'])

    def test_pattern_without_a_tempo_leaves_it(self):
        r = Rig()
        r.tempo(90.0)
        r.switch(5)
        self.assertEqual(r.tempo(), 90.0)

    def test_off_saves_nothing_and_changes_nothing(self):
        r = Rig(on=False)
        r.tempo(123.4)
        r.save(3)
        self.assertNotIn('banks/00/03.pax', r.e.sd_written)
        r2 = Rig()
        r2.tempo(123.4)
        r2.save(3)
        r2.e.w8(r2.cave['pk_cfg_pattern_bpm'], 0)
        r2.tempo(90.0)
        r2.switch(3)
        self.assertEqual(r2.tempo(), 90.0)

    def test_external_clock_ignores_it(self):
        r = Rig()
        r.tempo(123.4)
        r.save(3)
        r.e.w8(SYM.g['device_config'] + 0x00, 2)                    # MIDI clock
        r.tempo(90.0)
        r.switch(3)
        self.assertEqual(r.tempo(), 90.0)

    def test_bank_load_brings_the_tempos_and_plays_the_saved_pattern_at_its_tempo(self):
        r = Rig()
        r.tempo(140.0)
        r.save(2, bank=1)
        sd = {k: v for k, v in r.e.sd_written.items() if k.startswith('banks/')}
        sd['BANKS/01/state.dat'] = struct.pack('<HH', 2, 0)         # bank 2's saved pattern: 3
        r2 = Rig(sd=sd)
        r2.tempo(90.0)
        r2.e.w8(SYM.g['tempo_state'] + CATCH, 0)
        r2.e.uc.mem_write(0x100283d0 + 1, b'\x01')                  # bank 2 seen by the boot listing
        r2.e.call(r2.sym.fn['switch_bank'], 1, max_insns=900_000_000)
        r2.e.call(r2.sym.fn['pat_switch_done'], max_insns=50_000_000)
        self.assertEqual(r2.tempo(), 140.0)

    def test_clear_forgets_it(self):
        r = Rig()
        r.tempo(123.4)
        r.save(3)
        r.e.stub(SYM.fn['pat_clear'], lambda *a: 0)
        r.e.call(r.cave['pk4_store_pat_clear'], 0, 3, max_insns=50_000_000)
        r.tempo(90.0)
        r.switch(3)
        self.assertEqual(r.tempo(), 90.0)


if __name__ == '__main__':
    unittest.main()
