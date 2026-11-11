"""STEP SAMPLER: the M7 engine (the shared control set up by hand), the M4's bank load, hits
and streams (on the rig, with a virtual card), and both together (their shared RAM copied
between the two emulators as they run). Needs arm-none-eabi-gcc."""
import os
import shutil
import struct
import sys
import tempfile
import unittest

from fixtures import SYMBOLS_V130, build_patched, require_image
from perkons import verify
from perkons.emu import Symbols
from perkons.fwimage import Image
from perkons.patch import PatchError
from perkons.rig import M4Rig
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'lib'))
import ss_layout as L  # noqa: E402
from perkons.voicemap import remap  # noqa: E402

POS1, POS2, POS3 = 1, 0, 2                  # switch values for panel positions 1, 2, 3
ATTACK, START, SLICE = POS1, POS2, POS3     # ALGO
FWD, CHOKE, REV = POS1, POS2, POS3          # MODE
DRONE = 4095
VS_VALUE, VS_BASE = 0x50, 0x6a              # voice_state: the values playing, the knobs
SLOT_PARAM2, SLOT_ALGO, SLOT_MODE = 5, 8, 9
SCRATCH = 0x1003f000                        # M4 RAM for the test's trigger records
M7_FIELDS = ('seen_gen', 't_read', 'm7_active')


def pattern(n, k=7):
    """A recognisable sample: every frame different."""
    return [((i * k) % 30000) - 15000 for i in range(n)]


def build():
    stock = Image.load(require_image('v1.3.0'))
    img, p = build_patched(stock, ['voice_map', 'voice_step_sampler:5'], tempfile.mkdtemp(prefix='pk-ss-'))
    return stock, img, p.cave_symbols


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock, cls.img, cls.cave = build()
        cls.s7 = Symbols(SYMBOLS_V130)

    # -- the M7 ---------------------------------------------------------------------------
    def m7(self):
        e = verify.boot(self.img, self.s7)
        remap(e, [4, 1, 2, 3], self.cave['m7host'])          # engine 5 (map value 4) on output 1
        e.audio(960)
        return e

    def play(self, e, params=(2048, DRONE, 0, 0), algo=START, mode=FWD, vel=127, note=36, n=4800, trig=True):
        voices = [{'params': [2048] * 4} for _ in range(4)]
        voices[0] = {'params': list(params), 'algo': algo, 'mode': mode}
        e.send_voice_state(voices)
        e.pump()
        if trig:
            e.send_triggers([1, 0, 0, 0], [(algo, mode), (0, 0), (0, 0), (0, 0)], vel, note)
        return e.audio(n)[0]

    # -- the M4 ---------------------------------------------------------------------------
    def m4(self, sd=None, bank=0):
        r = M4Rig(self.img, self.cave['m4host'], sd=sd or {})
        f = r.sym.fn
        r.e.stub(f['key_poll'], lambda *a: 0)
        r.e.stub(f['kit_load'], lambda *a: 0)
        r.ipc = []

        def ipc(uc, *_):
            n = uc.reg_read(UC_ARM_REG_R2)
            r.ipc.append((uc.reg_read(UC_ARM_REG_R0), uc.reg_read(UC_ARM_REG_R3),
                          bytes(uc.mem_read(uc.reg_read(UC_ARM_REG_R1), min(n, 64)))))
        r.e.uc.hook_add(UC_HOOK_CODE, ipc, begin=f['ipc_send'], end=f['ipc_send'])
        # STEP SAMPLER on voice 1, as a kit load puts it there (voice-map's kit record)
        kit = r.r16(r.sym.g['current_kit'])
        r.e.uc.mem_write(SCRATCH, struct.pack('<H', 0x3214))
        r.e.call(self.cave['m4host']['pk_vm_kit_restore'], 0, kit, SCRATCH, 2, max_insns=1_000_000)
        r.e.call(self.cave['m4host']['pk_vm_kit_load'], kit, max_insns=1_000_000)
        r.v = L.View(r.e)
        r.e.call(self.cave['m4host']['pk_ss_load_samples'], bank, max_insns=900_000_000)
        return r

    def knobs(self, r, v=0, p2=0, algo=START, mode=FWD, playing=True):
        """Voice v's PARAM2 (0..4095), ALGO and MODE: the values playing (and the knobs)."""
        vs = r.voice_state(v)
        for base in ((VS_VALUE, VS_BASE) if playing else (VS_BASE,)):
            for slot, val in ((SLOT_PARAM2, p2 << 4), (SLOT_ALGO, algo), (SLOT_MODE, mode)):
                r.e.uc.mem_write(vs + base + 2 * slot, struct.pack('<H', val))

    def hit(self, r, voices=(0,), note=36, vel=127):
        """Trigger records on their way to the M7, through the hook (then stock ipc_send)."""
        rec = b''.join(bytes([1 if v in voices else 0, 0, note, vel]) for v in range(4))
        r.e.uc.mem_write(SCRATCH, rec)
        r.e.call(self.cave['m4host']['pk_ss_triggers'], 2, SCRATCH, 16, 0, max_insns=5_000_000)

    def seen(self, r, o=0, t_read=0, active=0):
        """What the M7 reports once it has the hit (here: done with it, unless active)."""
        r.v.w(o, 'seen_gen', r.v.r(o, 'gen'))
        r.v.w(o, 't_read', t_read)
        r.v.w(o, 'm7_active', active)

    def poll(self, r, n=1):
        for _ in range(n):
            r.e.call(self.cave['m4host']['pk_ss_poll'], max_insns=50_000_000)


# ---- the M7 engine, the control set up by hand -----------------------------------------
class TestEngine(Base):
    def setup_sample(self, e, data, s=0, rate=48000, head=None):
        head = len(data) if head is None else head
        e.uc.mem_write(L.head(s), struct.pack(f'<{min(head, L.HEAD_FRAMES)}h', *data[:L.HEAD_FRAMES]))
        L.View(e).set_sample(s, len(data), rate, min(head, L.HEAD_FRAMES, len(data)))
        e.w32(L.CTRL, L.MAGIC)

    def hit7(self, e, s=0, rstart=0, rend=None, d=L.FWD, src=L.SRC_HEAD, a_len=0, gen=None, loop=1):
        v = L.View(e)
        rend = rend if rend is not None else L.View(e).sample(s)['frames']
        for f, val in (('sample', s), ('dir', d), ('loop', loop), ('src', src), ('rstart', rstart), ('rend', rend),
                       ('a_len', a_len)):
            v.w(0, f, val)
        v.w(0, 'gen', gen if gen is not None else v.r(0, 'gen') + 1)

    def start(self, x):
        return next(i for i, s in enumerate(x) if s)

    def test_plays_the_head_at_a_quarter_level_and_loops_while_open(self):
        e = self.m7()
        data = pattern(2000)
        self.setup_sample(e, data)
        self.hit7(e)
        x = self.play(e)
        s0 = self.start(x)
        self.assertEqual(e.class_of(e.slot(0)), 'cStepSampler')
        self.assertLessEqual(max(abs(x[s0 + i] - data[i % 2000] * 0.25) for i in range(200, 4000)), 2)

    def test_reverse(self):
        e = self.m7()
        data = pattern(2000)
        self.setup_sample(e, data)
        self.hit7(e, d=L.REV)
        x = self.play(e)
        s0 = self.start(x)
        self.assertLessEqual(max(abs(x[s0 + i] - data[1999 - i % 2000] * 0.25) for i in range(200, 1900)), 2)

    def test_choked_stops_at_its_end_with_a_fade(self):
        e = self.m7()
        data = [12000] * 2000
        self.setup_sample(e, data)
        self.hit7(e, rstart=0, rend=1000, loop=0)
        x = self.play(e)                                      # DECAY fully right: it would go round
        s0 = self.start(x)
        self.assertLessEqual(max(abs(x[s0 + i] - 3000) for i in range(200, 900)), 2)
        self.assertTrue(0 < abs(x[s0 + 1000 - 32]) < 2000, 'fading into the cut')
        self.assertEqual(max(map(abs, x[s0 + 1000:])), 0, 'stopped: no going round')

    def test_tune_and_the_samples_own_rate(self):
        for tune, rate, speed in ((2048 + 512, 48000, 2.0), (2048, 24000, 0.5), (2048 - 512, 96000, 1.0)):
            with self.subTest(tune=tune, rate=rate):
                e = self.m7()
                self.setup_sample(e, pattern(2000), rate=rate)
                self.hit7(e, rend=2000)
                self.play(e, params=(tune, DRONE, 0, 0), n=4800)      # it loops: the tape goes on
                t = L.View(e).r(0, 't_read')
                self.assertAlmostEqual(t / 4800, speed, delta=0.05)

    def test_the_ring_then_silence_past_it(self):
        e = self.m7()
        data = pattern(8000)
        self.setup_sample(e, data, head=L.HEAD_FRAMES)
        v = L.View(e)
        self.hit7(e)
        n = 2400                                             # the ring holds tape frames 2560 .. 4960
        e.uc.mem_write(L.ringbuf(0) + 2 * (L.HEAD_FRAMES % L.RING_FRAMES),
                       struct.pack(f'<{n}h', *data[L.HEAD_FRAMES:L.HEAD_FRAMES + n]))
        v.w(0, 'ring_gen', v.r(0, 'gen'))
        v.w(0, 'ring_from', L.HEAD_FRAMES)
        v.w(0, 'ring_to', L.HEAD_FRAMES + n)
        x = self.play(e, n=7000)
        s0 = self.start(x)
        self.assertLessEqual(max(abs(x[s0 + i] - data[i] * 0.25) for i in range(200, L.HEAD_FRAMES + n - 2)), 2)
        self.assertEqual(max(map(abs, x[s0 + L.HEAD_FRAMES + n + 2:s0 + 6500])), 0, 'not loaded: silent')

    def test_prepared_start(self):
        e = self.m7()
        data = pattern(20000)
        self.setup_sample(e, data, head=L.HEAD_FRAMES)
        first = 12000
        e.uc.mem_write(L.nextbuf(0), struct.pack(f'<{L.NEXT_FRAMES}h', *data[first:first + L.NEXT_FRAMES]))
        self.hit7(e, rstart=first, rend=20000, src=L.SRC_NEXT, a_len=L.NEXT_FRAMES)
        x = self.play(e, n=2400)
        s0 = self.start(x)
        self.assertLessEqual(max(abs(x[s0 + i] - data[first + i] * 0.25) for i in range(200, 2300)), 2)

    def test_grit(self):
        e = self.m7()
        data = pattern(2000, k=13)
        self.setup_sample(e, data)
        self.hit7(e)
        x = self.play(e, params=(2048, DRONE, 2048, 0))      # 12 o'clock: 12-bit, ~26 kHz
        s0 = self.start(x)
        seg = x[s0 + 200:s0 + 1800]
        repeats = sum(1 for a, b in zip(seg, seg[1:]) if a == b) / len(seg)
        self.assertTrue(0.3 < repeats < 0.6, repeats)          # each value held ~1.85 samples
        self.hit7(e)
        x = self.play(e, params=(2048, DRONE, 3071, 0))      # 3/4: ~9-bit: steps of 128, x 0.25 = 32
        s0 = self.start(x)
        seg = x[s0 + 200:s0 + 1800]
        jumps = [abs(b - a) for a, b in zip(seg, seg[1:]) if a != b]
        self.assertGreater(min(jumps), 28, 'quantised: values move in steps of ~32 (128 before the 0.25 gain)')
        clean = self.play(e, params=(2048, DRONE, 0, 0))[400:2000]
        self.assertLess(min(abs(b - a) for a, b in zip(clean, clean[1:]) if a != b), 8, 'fully left: clean')

    def test_empty_slot_and_bank_load_are_silent(self):
        e = self.m7()
        self.setup_sample(e, pattern(2000))
        L.View(e).set_sample(1, 0, 0, 0)
        self.hit7(e, s=1, rend=100)
        self.assertEqual(max(map(abs, self.play(e, n=960))), 0)
        self.hit7(e)
        self.play(e, n=480)
        e.w32(L.CTRL + 8, 1)                                  # loading
        self.assertEqual(max(map(abs, e.audio(480)[0][96:])), 0)

    def test_velocity_and_decay(self):
        e = self.m7()
        self.setup_sample(e, [20000] * 2000)
        peaks = {}
        for vel in (127, 64):
            self.hit7(e)
            peaks[vel] = abs(self.play(e, vel=vel, n=480)[-1])   # after the hit (the old note ends first)
        self.assertAlmostEqual(peaks[64] / peaks[127], 64 / 127, delta=0.03)
        self.hit7(e)
        x = self.play(e, params=(2048, 0, 0, 0), n=9600)        # DECAY fully left: ~0.08 s
        self.assertLess(max(map(abs, x[-2400:])), 0.01 * peaks[127])

    def test_cpu(self):
        e = self.m7()
        self.setup_sample(e, pattern(2000))
        self.hit7(e)
        self.play(e, params=(2048 + 300, DRONE, 3000, 0), n=960)
        base = verify.boot(self.img, self.s7)
        self.play(base, n=960)
        counts = []
        for m in (e, base):
            m.count_insns(True)
            m.insn_count = 0
            m.audio(960)
            counts.append(m.insn_count / 960)
            m.count_insns(False)
        print(f'\nSTEP SAMPLER: ~{counts[0] - counts[1]:.0f} instructions per sample more than stock output 1')
        self.assertLess(counts[0] - counts[1], 600)


# ---- the M4: bank load ---------------------------------------------------------------------
class TestBankLoad(Base):
    def test_files_found_checked_and_loaded(self):
        a, b, c = pattern(3000), pattern(1000, k=11), pattern(500, k=3)
        card = {'BANKS/00/SAMPLES/1.wav': L.wav(a), 'SAMPLES/1.wav': L.wav(b),     # the bank's wins
                'SAMPLES/2.wav': L.wav(b, rate=44100),                             # any rate
                'SAMPLES/3.wav': L.wav(c * 2, channels=2),                         # stereo: no
                'SAMPLES/4.wav': L.wav(c, bits=24),                                # 24-bit: no
                'BANKS/00/SAMPLES/7.wav': L.wav(c, cues=[300, 100, 200, 100, 999]),
                'SAMPLES/65.wav': L.wav(c), 'SAMPLES/05.wav': L.wav(c)}            # not 1-64 / leading 0
        r = self.m4(card)
        v = r.v
        self.assertEqual(v.magic, L.MAGIC)
        self.assertEqual(v.sample(0), {'frames': 3000, 'rate': 48000, 'head': L.HEAD_FRAMES})
        self.assertEqual(list(struct.unpack(f'<{L.HEAD_FRAMES}h', bytes(r.e.uc.mem_read(L.head(0), 2 * L.HEAD_FRAMES)))),
                         a[:L.HEAD_FRAMES])
        self.assertEqual(v.sample(1), {'frames': 1000, 'rate': 44100, 'head': 1000})
        for s in (2, 3, 4, 63):
            self.assertEqual(v.sample(s)['frames'], 0, f'slot {s + 1}: empty')
        self.assertEqual(v.sample(6)['frames'], 500)
        stock = bytes(r.e.uc.mem_read(r.sym.g['sample_table'], r.sym.g['sample_data'] - r.sym.g['sample_table']))
        self.assertEqual(stock, bytes(len(stock)), 'the stock table: empty (factory samples)')
        loads = [(s, t, m) for s, t, m in r.ipc if s == 3 and t == 3]
        self.assertEqual([m[:1] for _, _, m in loads], [b'\0', b'\1'], 'samples changing, then ready')

    def test_extensible_format_and_extra_chunks(self):
        c = pattern(800)
        ext = struct.pack('<HHIIHHHHI', 0xfffe, 1, 48000, 96000, 2, 16, 22, 16, 4) + struct.pack('<H', 1) + bytes(14)
        body = b'fmt ' + struct.pack('<I', len(ext)) + ext + b'LIST' + struct.pack('<I', 5) + b'hello\0'
        data = struct.pack(f'<{len(c)}h', *c)
        body += b'data' + struct.pack('<I', len(data)) + data
        r = self.m4({'SAMPLES/1.wav': b'RIFF' + struct.pack('<I', 4 + len(body)) + b'WAVE' + body})
        self.assertEqual(r.v.sample(0)['frames'], 800)


# ---- the M4: what hits play, streams, prepared starts ----------------------------------------
class TestHits(Base):
    def setUp(self):
        self.data = pattern(40000)
        self.r = self.m4({'SAMPLES/1.wav': L.wav(self.data),
                          'SAMPLES/2.wav': L.wav(pattern(9000), cues=[1000, 5000, 3000])})

    def out(self, *fields):
        return tuple(self.r.v.r(0, f) for f in fields)

    def test_attack_plays_from_the_beginning(self):
        self.knobs(self.r, p2=3000, algo=ATTACK)
        self.hit(self.r)
        self.assertEqual(self.out('sample', 'dir', 'src', 'rstart', 'rend'), (0, L.FWD, L.SRC_HEAD, 0, 40000))
        self.assertEqual(self.r.v.r(0, 'cover'), L.HEAD_FRAMES)

    def test_start_point_late_start_plays_from_the_beginning(self):
        self.knobs(self.r, p2=2048, algo=START)                # 20000: not in the head, not prepared
        self.hit(self.r)
        self.assertEqual(self.out('rstart', 'rend', 'src'), (0, 40000, L.SRC_HEAD))

    def test_start_point_prepared(self):
        self.knobs(self.r, p2=2048, algo=START, playing=False)
        self.knobs(self.r, p2=2048, algo=START)
        self.poll(self.r)                                     # the main loop prepares the knobs' start
        self.assertEqual((self.r.v.r(0, 'next_first'), self.r.v.r(0, 'next_len')), (20000, L.NEXT_FRAMES))
        got = struct.unpack(f'<{L.NEXT_FRAMES}h', bytes(self.r.e.uc.mem_read(L.nextbuf(0), 2 * L.NEXT_FRAMES)))
        self.assertEqual(list(got), self.data[20000:20000 + L.NEXT_FRAMES])
        self.hit(self.r)
        self.assertEqual(self.out('rstart', 'rend', 'src', 'a_len'), (20000, 40000, L.SRC_NEXT, L.NEXT_FRAMES))

    def test_slices_from_cues_and_equal(self):
        kit = self.r.r16(self.r.sym.g['current_kit'])
        self.r.e.uc.mem_write(self.cave['m4host']['pk_ss_kit_sample'] + 4 * kit, bytes([1, 0, 0, 0]))   # sample 2
        for p2, mode, want in ((0, CHOKE, (1000, 3000, 0)), (2048, CHOKE, (3000, 5000, 0)),
                               (4095, CHOKE, (5000, 9000, 0)), (2048, FWD, (3000, 9000, 1)),
                               (2048, REV, (3000, 5000, 1))):
            with self.subTest(p2=p2, mode=mode):
                self.knobs(self.r, p2=p2, algo=SLICE, mode=mode, playing=False)
                self.knobs(self.r, p2=p2, algo=SLICE, mode=mode)
                self.poll(self.r)                             # slices past the head: prepared
                self.hit(self.r)
                self.assertEqual(self.out('sample', 'rstart', 'rend', 'loop'), (1, *want))
                past_head = (want[1] if mode == REV else want[0]) > L.HEAD_FRAMES
                self.assertEqual(self.r.v.r(0, 'src'), L.SRC_NEXT if past_head else L.SRC_HEAD)
                self.seen(self.r)
        self.r.e.uc.mem_write(self.cave['m4host']['pk_ss_kit_sample'] + 4 * kit, bytes([0, 0, 0, 0]))
        self.knobs(self.r, p2=4096 * 3 // 16, algo=SLICE, mode=CHOKE, playing=False)   # no cues: 16 equal, the 4th
        self.knobs(self.r, p2=4096 * 3 // 16, algo=SLICE, mode=CHOKE)
        self.poll(self.r)
        self.hit(self.r)
        self.assertEqual(self.out('rstart', 'rend'), (7500, 10000))

    def test_reverse_from_the_end_of_its_stretch(self):
        self.knobs(self.r, p2=0, algo=ATTACK, mode=REV)
        self.hit(self.r)                                      # its end (40000) isn't in the head: late
        self.assertEqual(self.out('dir', 'rstart'), (L.FWD, 0))
        self.knobs(self.r, p2=0, algo=ATTACK, mode=REV, playing=False)
        self.poll(self.r)                                     # prepared: the last frames, reversed
        self.hit(self.r)
        self.assertEqual(self.out('dir', 'src', 'rend'), (L.REV, L.SRC_NEXT, 40000))
        got = struct.unpack('<8h', bytes(self.r.e.uc.mem_read(L.nextbuf(0), 16)))
        self.assertEqual(list(got), self.data[39999:39991:-1])

    def test_choke_stops_at_the_next_cut(self):
        kit = self.r.r16(self.r.sym.g['current_kit'])
        for sample, algo, p2, want in ((1, ATTACK, 0, (0, 1000)),          # cues 1000, 3000, 5000
                                       (1, START, 2048, (4500, 5000)),
                                       (1, START, 4000, (8789, 9000)),     # after the last cue: the end
                                       (0, START, 1024, (10000, 12500))):  # no cues: the next 16th
            with self.subTest(sample=sample, algo=algo, p2=p2):
                self.r.e.uc.mem_write(self.cave['m4host']['pk_ss_kit_sample'] + 4 * kit, bytes([sample, 0, 0, 0]))
                self.knobs(self.r, p2=p2, algo=algo, mode=CHOKE, playing=False)
                self.knobs(self.r, p2=p2, algo=algo, mode=CHOKE)
                self.poll(self.r)
                self.hit(self.r)
                self.assertEqual(self.out('rstart', 'rend', 'loop', 'dir'), (*want, 0, L.FWD))
                self.seen(self.r)

    def test_late_choked_start_plays_the_first_cut(self):
        self.knobs(self.r, p2=2048, algo=START, mode=CHOKE)  # 20000: not prepared
        self.hit(self.r)
        self.assertEqual(self.out('rstart', 'rend', 'loop'), (0, 2500, 0))

    def test_other_voices_left_alone(self):
        g = self.r.v.r(1, 'gen')
        self.hit(self.r, voices=(1,))
        self.assertEqual(self.r.v.r(1, 'gen'), g)


class TestStream(Base):
    def test_ring_follows_the_tape_and_the_reader(self):
        data = pattern(30000)
        r = self.m4({'SAMPLES/1.wav': L.wav(data)})
        self.knobs(r, algo=ATTACK)
        self.hit(r)
        v = r.v
        self.poll(r, 4)
        self.assertEqual(v.r(0, 'ring_gen'), v.r(0, 'gen'))
        frm, to = v.r(0, 'ring_from'), v.r(0, 'ring_to')
        self.assertEqual(frm, L.HEAD_FRAMES)
        self.assertEqual(to, L.RING_FRAMES - 2, 'filled up to the window (t_read 0)')
        ring = struct.unpack(f'<{L.RING_FRAMES}h', bytes(r.e.uc.mem_read(L.ringbuf(0), 2 * L.RING_FRAMES)))
        self.assertEqual([ring[t % L.RING_FRAMES] for t in range(frm, to)], data[frm:to])
        v.w(0, 'seen_gen', v.r(0, 'gen'))                     # the M7 plays it, and has read 4000
        v.w(0, 'm7_active', 1)
        v.w(0, 't_read', 4000)
        self.poll(r, 4)
        to2 = v.r(0, 'ring_to')
        self.assertEqual(to2, 4000 + L.RING_FRAMES - 2)
        ring = struct.unpack(f'<{L.RING_FRAMES}h', bytes(r.e.uc.mem_read(L.ringbuf(0), 2 * L.RING_FRAMES)))
        self.assertEqual([ring[t % L.RING_FRAMES] for t in range(4000, to2)], data[4000:to2])
        v.w(0, 'm7_active', 0)                                # the note ended: no more reading
        v.w(0, 't_read', 8000)
        self.poll(r, 2)
        self.assertEqual(v.r(0, 'ring_to'), to2)

    def test_loops_round_its_stretch(self):
        data = pattern(30000)
        r = self.m4({'SAMPLES/1.wav': L.wav(data)})
        p2 = 4096 * 10 // 16                                  # 16 equal slices: the 11th, 18750-20625
        self.knobs(r, p2=p2, algo=SLICE, mode=REV)
        self.hit(r)                                           # late (not prepared): from the beginning
        self.knobs(r, p2=p2, algo=SLICE, mode=REV, playing=False)
        self.poll(r)
        self.hit(r)                                           # prepared
        v = r.v
        self.assertEqual((v.r(0, 'rstart'), v.r(0, 'rend'), v.r(0, 'src')), (18750, 20625, L.SRC_NEXT))
        v.w(0, 'seen_gen', v.r(0, 'gen'))
        v.w(0, 'm7_active', 1)
        self.poll(r, 6)
        ring = struct.unpack(f'<{L.RING_FRAMES}h', bytes(r.e.uc.mem_read(L.ringbuf(0), 2 * L.RING_FRAMES)))
        frm, to = v.r(0, 'ring_from'), v.r(0, 'ring_to')
        self.assertEqual(frm, 1875, 'after the prepared start (the whole slice)')
        want = [data[20624 - t % 1875] for t in range(frm, to)]     # backwards, round and round
        self.assertEqual([ring[t % L.RING_FRAMES] for t in range(frm, to)], want)


# ---- the sample page and the step edits ---------------------------------------------------------
SHUFFLE, CLEAR, REC, SHIFT = 0x48, 0x4a, 0x46, 0x47
MAIN, SHUFFLE_PAGE = 0, 8


class TestPage(Base):
    def setUp(self):
        self.r = self.m4({'SAMPLES/1.wav': L.wav(pattern(500)), 'SAMPLES/5.wav': L.wav(pattern(500)),
                          'SAMPLES/12.wav': L.wav(pattern(500))})
        r = self.r
        self.played = []
        r.e.stub(r.sym.fn['voice_play'], lambda emu, v, on, *_: self.played.append((v, on)))
        self.kit = r.r16(r.sym.g['current_kit'])
        self.steps = self.cave['m4host']['pk_ss_step_sample']
        self.kits = self.cave['m4host']['pk_ss_kit_sample']
        self.pat = r.e.call(self.cave['m4host']['pk_ss_pattern'], max_insns=100_000)

    def apply(self):
        self.r.e.call(self.r.sym.fn['apply_mode'], max_insns=5_000_000)
        return self.r.mode()

    def choice(self, track, step):
        return self.r.e.uc.mem_read(self.steps + 64 * self.pat + 16 * track + step, 1)[0]

    def open_page(self, *steps):
        for k in steps:
            self.r.event(k, True)
        self.r.event(SHUFFLE, True)
        return self.apply()

    def test_step_shuffle_opens_it_on_a_sampler_track_only(self):
        self.assertEqual(self.open_page(3), 18, 'the sample page (after voice-map\'s engines, 17)')
        r = self.m4()
        r.event(16 + 3, True)                                 # row 2: voice 2 runs a stock engine
        r.event(SHUFFLE, True)
        r.e.call(r.sym.fn['apply_mode'], max_insns=5_000_000)
        self.assertEqual(r.mode(), SHUFFLE_PAGE)

    def test_choosing_sets_the_steps_and_the_track_and_sounds(self):
        self.open_page(3, 7)
        self.r.e.stub(self.r.sym.fn['key_held_ms'], lambda *a: 50)   # a tap: it stays
        self.r.event(SHUFFLE, False)
        self.assertEqual(self.apply(), 18)
        for k in (3, 7):                                      # the held steps let go: no toggle
            self.r.event(k, False)
        self.r.press(4)                                       # sample 5
        self.assertEqual((self.choice(0, 3), self.choice(0, 7), self.choice(0, 4)), (5, 5, 0))
        self.assertEqual(self.r.e.uc.mem_read(self.kits + 4 * self.kit, 1)[0], 4, 'the track\'s sample')
        self.assertEqual(self.played, [(0, 1), (0, 0)])
        blk = self.r.block(0)
        self.assertEqual([self.r.e.uc.mem_read(blk + 8 * k, 1)[0] for k in (3, 7)], [0, 0], 'steps not toggled')

    def test_leds(self):
        self.open_page(3)
        self.r.press(11)                                      # sample 12
        self.r.e.call(self.cave['m4host']['pk_ss_page_draw'], max_insns=1_000_000)
        lit = {k: v for k, v in self.r.leds.items() if k < 64 and v}
        self.assertEqual(lit, {0: 0x10, 4: 0x10, 11: 0x80})

    def test_shuffle_closes_it_tapped_again_or_on_release_after_a_hold(self):
        self.open_page(3)
        self.r.event(3, False)
        self.r.event(SHUFFLE, True)                           # tapped again
        self.assertEqual(self.apply(), MAIN)
        self.open_page(3)
        self.r.e.stub(self.r.sym.fn['key_held_ms'], lambda *a: 600)
        self.r.event(SHUFFLE, False)                          # released after a hold
        self.assertEqual(self.apply(), MAIN)

    def test_clear_copy_paste(self):
        self.open_page(2)
        self.r.press(4)
        self.r.event(SHUFFLE, True)
        self.apply()
        self.r.event(2, False)
        self.assertEqual(self.choice(0, 2), 5)
        self.r.event(2, True)                                 # copy step 3 (REC with it held)
        self.r.press(REC)
        self.r.event(2, False)
        self.r.event(9, True)                                 # paste into step 10 (SHIFT with it held)
        self.r.press(SHIFT)
        self.r.event(9, False)
        self.assertEqual(self.choice(0, 9), 5)
        self.r.event(CLEAR, True)                             # CLEAR + step
        self.r.press(2)
        self.r.event(CLEAR, False)
        self.assertEqual((self.choice(0, 2), self.choice(0, 9)), (0, 5))


# ---- both cores: a long sample, played through ------------------------------------------------
class TestBothCores(Base):
    def sync(self, m4, m7):
        """The shared RAM, M4 -> M7 (the M7's own fields kept), then the M7's fields -> M4."""
        keep = {(o, f): L.View(m7).r(o, f) for o in range(4) for f in M7_FIELDS}
        L.copy(m4, m7)
        for (o, f), val in keep.items():
            L.View(m7).w(o, f, val)
            L.View(m4).w(o, f, val)

    def test_long_sample_streams_without_a_gap(self):
        data = pattern(60000)
        r = self.m4({'SAMPLES/1.wav': L.wav(data)})
        e = self.m7()
        self.knobs(r, algo=ATTACK)
        self.hit(r)
        self.sync(r.e, e)
        x = self.play(e, params=(2048, DRONE, 0, 0), algo=ATTACK, n=256)
        for _ in range(40):                                   # ~0.2 s: well past the head (53 ms)
            self.sync(r.e, e)
            self.poll(r, 3)
            self.sync(r.e, e)
            x += e.audio(256)[0]
        s0 = next(i for i, s in enumerate(x) if s)
        n = len(x) - s0
        self.assertGreater(n, 3 * L.HEAD_FRAMES)
        self.assertLessEqual(max(abs(x[s0 + i] - data[i] * 0.25) for i in range(200, n)), 2)

    def test_needs_voice_map(self):
        with self.assertRaises(PatchError):
            build_patched(self.stock, ['voice_step_sampler'], tempfile.mkdtemp())


if __name__ == '__main__':
    unittest.main()
