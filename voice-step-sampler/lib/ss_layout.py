"""STEP SAMPLER's shared RAM (src/common/ss_shared.h), for tests and tools: the addresses
(read from the header's #defines) and the control block's fields; helpers to read and write
it in an emulator, to copy it between an M4 and an M7 emulator, and to make WAV files."""
import os
import re
import struct

HEADER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src', 'common', 'ss_shared.h')


def _defines():
    env = {}
    with open(HEADER) as f:
        for name, expr in re.findall(r'^#define (SS_[A-Z_]+)\s+([^/\n]+?)\s*(?:/\*.*)?$', f.read(), re.M):
            if '(' in name:
                continue
            try:
                env[name] = eval(re.sub(r'(0x[0-9a-fA-F]+|\d+)u\b', r'\1', expr), {}, dict(env))
            except (NameError, SyntaxError):
                pass
    return env


D = _defines()
SAMPLES, OUTPUTS, HEAD_FRAMES, NEXT_FRAMES, RING_FRAMES = (D[k] for k in (
    'SS_SAMPLES', 'SS_OUTPUTS', 'SS_HEAD_FRAMES', 'SS_NEXT_FRAMES', 'SS_RING_FRAMES'))
BASE, CTRL, HEADS, FILS, NEXT, RING, END = (D[k] for k in (
    'SS_BASE', 'SS_CTRL', 'SS_HEADS', 'SS_FILS', 'SS_NEXT', 'SS_RING', 'SS_END'))
MAGIC = D['SS_MAGIC']
FWD, REV = 0, 1
SRC_HEAD, SRC_NEXT = 0, 1
PLAY_ONCE, PLAY_LOOP, PLAY_GRAINS = 0, 1, 2
GRAIN_FRAMES = D['SS_GRAIN_FRAMES']

# ss_ctrl_t / ss_sample_t / ss_out_t (all naturally aligned u32, four u8 together)
SAMPLE_SIZE = 16
OUT_FIELDS = ['gen', ('sample', 'dir', 'src', 'loop'), 'rstart', 'rend', 'a_len', 'ring_gen', 'ring_from',
              'ring_to', 'seen_gen', 't_read', 'm7_active', 'next_gen', 'next_sample', 'next_dir', 'next_first',
              'next_len', 'cover']
OUT_SIZE = 4 * len(OUT_FIELDS)
CTRL_OUT = CTRL + 16 + SAMPLES * SAMPLE_SIZE
CTRL_LEN = CTRL_OUT + OUTPUTS * OUT_SIZE - CTRL


def out_addr(o, field):
    for i, f in enumerate(OUT_FIELDS):
        if f == field:
            return CTRL_OUT + OUT_SIZE * o + 4 * i
        if isinstance(f, tuple) and field in f:
            return CTRL_OUT + OUT_SIZE * o + 4 * i + f.index(field)
    raise KeyError(field)


def head(s):
    return HEADS + 2 * HEAD_FRAMES * s


def nextbuf(o):
    return NEXT + 2 * NEXT_FRAMES * o


def ringbuf(o):
    return RING + 2 * RING_FRAMES * o


class View:
    """The shared control in one emulator (anything with r32 / w32 / uc)."""

    def __init__(self, emu):
        self.e = emu

    def r(self, o, field):
        a = out_addr(o, field)
        return self.e.uc.mem_read(a, 1)[0] if field in OUT_FIELDS[1] else self.e.r32(a)

    def w(self, o, field, v):
        a = out_addr(o, field)
        if field in OUT_FIELDS[1]:
            self.e.uc.mem_write(a, bytes([v]))
        else:
            self.e.w32(a, v)

    def sample(self, s):
        frames, rate, head_frames, _ = struct.unpack('<4I', bytes(self.e.uc.mem_read(CTRL + 16 + SAMPLE_SIZE * s, 16)))
        return {'frames': frames, 'rate': rate, 'head': head_frames}

    def set_sample(self, s, frames, rate, head_frames):
        self.e.uc.mem_write(CTRL + 16 + SAMPLE_SIZE * s, struct.pack('<4I', frames, rate, head_frames, 0))

    @property
    def magic(self):
        return self.e.r32(CTRL)


def copy(src, dst, lo=BASE, hi=END):
    """Shared RAM from one emulator to the other (the two cores see the same AXI SRAM)."""
    dst.uc.mem_write(lo, bytes(src.uc.mem_read(lo, hi - lo)))


def wav(frames, rate=48000, channels=1, bits=16, cues=(), extra_chunks=b''):
    """A WAV file: frames (ints, interleaved if channels > 1), PCM, with a cue chunk."""
    width = bits // 8
    data = b''.join(int(v).to_bytes(width, 'little', signed=True) for v in frames)
    fmt = struct.pack('<HHIIHH', 1, channels, rate, rate * channels * width, channels * width, bits)
    out = b'fmt ' + struct.pack('<I', len(fmt)) + fmt + extra_chunks
    if cues:
        body = struct.pack('<I', len(cues)) + b''.join(
            struct.pack('<II4sIII', i + 1, c, b'data', 0, 0, c) for i, c in enumerate(cues))
        out += b'cue ' + struct.pack('<I', len(body)) + body
    out += b'data' + struct.pack('<I', len(data)) + data + (b'\0' if len(data) & 1 else b'')
    return b'RIFF' + struct.pack('<I', 4 + len(out)) + b'WAVE' + out
