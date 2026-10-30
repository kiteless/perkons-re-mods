"""Eight-lanes test harness: the stock M4 sequencer driven in the emulator.

Boot the M4, run the sequencer setup, then clock it the way the firmware does. The
clock's main interrupt (TIM2, internal clock; EXTI for clock in) starts each step: it
resets clock+0x22, counts clock+0x20 and calls the sequencer tick clock+0x3c with 1. The
sub-tick timer interrupt (IRQ50) then advances clock+0x22 and calls tick(0), 24 x 12 =
288 sub-ticks per step. Captures what the sequencer sends: trigger messages to the M7
(IPC stream 2) and MIDI out (midi_out_bytes).

Found so far (v1.3.0):
* step record (8 B, 64 per track at the start of the track's 0x22c block): +0 on,
  +1 = 0x0a by default, +6 note (36 = no shift), +7 velocity
* voice_state(t) +4 -> track block, +0x1c step counter
* trigger message (stream 2, type 0): 4 x {on, ?, note, ?}; a release message follows
* midi_out_bytes(port, packed): packed = status | data1 << 8 | data2 << 16 | length << 24
"""
import os
import struct
import sys

PERKONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'perkons')
sys.path[:0] = [os.path.join(PERKONS, 'tools'), os.path.join(PERKONS, 'tests')]

from fixtures import require_image  # noqa: E402
from perkons.emu import M4Emu, Symbols  # noqa: E402
from perkons.fwimage import Image  # noqa: E402

# v1.3.0 addresses found in phase 0 / 1 (to move into the symbols file when this is real)
SEQ_SETUP = 0x081019f0
IRQ50 = 0x0810a4a0          # filled in below from the vector table if needed
SEQ_PTR = 0x1002e6e4        # -> sequencer object: [0] play state, [1] previous, [3] track count
CLOCK = 0x1000068c          # +0x1c, +0x1e: sub-tick divisions; +0x20 beat count; +0x22 sub-tick
TIMER_OBJ_PTR = 0x1002e270  # -> {clock, ?, ?, TIM handle}; handle -> TIM registers (SR +0x10)


def irq_handler(img, n):
    """Address of exception handler for external IRQ n (from the M4 vector table)."""
    seg = img.segment('m4')
    return struct.unpack_from('<I', seg.data, 4 * (16 + n))[0] & ~1


class SeqHarness:
    def __init__(self, img=None, sd=None, boot_hook=None):
        """img: an image (stock by default); boot_hook: the M4 host's pk4_boot in a patched
        image, run after the sequencer setup as the firmware does (main, then boot_init)."""
        self.img = img or Image.load(require_image('v1.3.0'))
        self.sym = Symbols(os.path.join(PERKONS, 'symbols', 'v1.3.0-m4.json'))
        self.e = M4Emu(self.img.segment('m4').data, self.sym, self.img.segment('m7').data, sd=sd or {}).boot()
        self.irq50 = irq_handler(self.img, 50)
        self.midi = []
        self.e.stub(self.sym.fn['midi_out_bytes'], self._midi)
        self.e.call(SEQ_SETUP, max_insns=20_000_000)
        if boot_hook:
            self.e.call(boot_hook, max_insns=50_000_000)
        self.seq = self.e.r32(SEQ_PTR)
        obj = self.e.r32(TIMER_OBJ_PTR)
        self.tim = self.e.r32(self.e.r32(obj + 12))        # TIM register block

    def _midi(self, emu, *args):
        self.midi.append(args)

    def r16(self, a):
        return struct.unpack('<H', bytes(self.e.uc.mem_read(a, 2)))[0]

    def play(self):
        self.e.w8(self.seq, 1)
        self.e.w8(self.seq + 1, 1)

    def subtick(self):
        self.e.w32(self.tim + 0x10, 1)                       # TIM SR: update interrupt pending
        self.e.call(self.irq50, max_insns=5_000_000)

    def w16(self, a, v):
        self.e.uc.mem_write(a, struct.pack('<H', v & 0xffff))

    def step(self):
        """What the clock interrupt does at a step, then the step's sub-ticks."""
        self.w16(CLOCK + 0x22, 0)
        self.w16(CLOCK + 0x20, self.r16(CLOCK + 0x20) + 1)
        self.e.call(self.e.r32(CLOCK + 0x3c) & ~1, 1, max_insns=5_000_000)
        for _ in range(self.r16(CLOCK + 0x1c) * self.r16(CLOCK + 0x1e) - 1):
            self.subtick()

    def run(self, steps):
        """Run `steps` steps; returns [(step, triggers, midi)] for steps that sent anything."""
        out = []
        for i in range(steps):
            self.step()
            trig = [self.decode_trigger(p) for typ, p in self.sent(2) if typ == 0]
            midi = [self.decode_midi(m) for m in self.midi]
            self.midi.clear()
            if trig or midi:
                out.append((i, trig, midi))
        return out

    # -- patterns ---------------------------------------------------------------------
    def voice_state(self, track):
        return self.e.r32(self.seq + 4) + track * 0x10c

    def block(self, track):
        return self.e.r32(self.voice_state(track) + 4)

    def set_step(self, track, step, note=36, velocity=100, on=True):
        a = self.block(track) + 8 * step
        self.e.w8(a, 1 if on else 0)
        self.e.w8(a + 6, note)
        self.e.w8(a + 7, velocity)

    # -- outputs ----------------------------------------------------------------------
    @staticmethod
    def decode_trigger(payload):
        """[(track, note)] for the tracks this trigger message turns on."""
        return [(t, payload[4 * t + 2]) for t in range(len(payload) // 4) if payload[4 * t]]

    @staticmethod
    def decode_midi(args):
        packed = args[1]
        n = packed >> 24
        return bytes((packed >> (8 * i)) & 0xff for i in range(min(n, 3)))

    def sent(self, stream):
        return self.e.sent(stream)
