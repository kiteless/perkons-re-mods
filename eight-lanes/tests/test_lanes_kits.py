"""Eight-lanes: lanes in kits (the host's kit sidecar BANKS/NN/KITS/PP.KIX, record EL8K)."""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
from el_rig import DEVICE, SYM, lanes_rig, stock_image  # noqa: E402,F401


def set_base(h, track, slot, v):
    h.e.uc.mem_write(h.voice_state(track) + 0x6a + 2 * slot, struct.pack('<H', v))


def base(h, track, slot):
    return h.r16(h.voice_state(track) + 0x6a + 2 * slot)


class TestLaneKits(unittest.TestCase):
    def save_kit(self, h, kit, bank=0):
        h.e.call(h.cave['pk4_store_kit_save'], bank, kit, max_insns=200_000_000)

    def load_kit(self, h, kit):
        h.e.call(h.cave['pk_el_kit_load'], kit, max_insns=200_000_000)

    def test_save_writes_kix_and_load_restores_lanes(self):
        h = lanes_rig()
        set_base(h, 4, 0, 0x1111)                    # lane 5 TUNE
        set_base(h, 7, 9, 2)                         # lane 8 octave switch
        set_base(h, 0, 0, 0x2222)                    # voice 1 TUNE
        self.save_kit(h, 3)
        self.assertIn('banks/00/kits/03.kit', h.e.sd_written)
        kix = h.e.sd_written['banks/00/kits/03.kix']
        self.assertEqual((kix[:4], kix[4:8], int.from_bytes(kix[8:12], 'little')), (b'PKX1', b'EL8K', 48))
        set_base(h, 4, 0, 0)
        set_base(h, 7, 9, 0)
        self.load_kit(h, 3)
        self.assertEqual((base(h, 4, 0), base(h, 7, 9)), (0x1111, 2))
        self.assertEqual(h.r16(h.voice_state(4) + 0x50), 0x1111, 'stopped: plays the kit value now')

    def test_bank_load_reads_kix_and_kit_without_one_leaves_lanes(self):
        h = lanes_rig()
        set_base(h, 5, 1, 0x3333)
        self.save_kit(h, 7, bank=1)
        card = dict(h.e.sd_written)
        h2 = lanes_rig(sd=card)
        h2.e.call(h2.cave['pk4_store_bank_load'], 1, max_insns=900_000_000)
        set_base(h2, 5, 1, 0x0101)
        self.load_kit(h2, 8)                          # no record
        self.assertEqual(base(h2, 5, 1), 0x0101)
        self.load_kit(h2, 7)
        self.assertEqual(base(h2, 5, 1), 0x3333)


if __name__ == '__main__':
    unittest.main()
