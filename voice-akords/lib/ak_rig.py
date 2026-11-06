"""Akords tests: the shared rig (a booted M7 running Akords on a voice-map slot, set up
through its knobs) and the music helpers. Needs arm-none-eabi-gcc."""
import math
import os
import shutil
import sys
import tempfile
import unittest

from fixtures import SYMBOLS_V130, build_patched, require_image
from perkons import verify
from perkons.emu import Symbols
from perkons.fwimage import Image
from perkons.patch import PatchError

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'voice-map', 'lib'))
from vm_live import remap  # noqa: E402

SR = 48000
POS1, POS2, POS3 = 1, 0, 2          # switch values for panel positions 1, 2, 3
LP24, HP, FORMANT = POS1, POS2, POS3    # MODE: the filter
PLAY = POS1                         # the MODE the tests play in (the presets' own filter)
DRONE = 4095
MSG_AKORDS, MSG_AKORDS_DRIVE, MSG_AKORDS_PROG, MSG_VOICE_MAP = 4, 5, 6, 7    # the M7 host's message types, in name order

PRESETS = ['Bass', 'Pad', 'Lead', 'Keys', 'Pluck', 'Stab', 'Hollow', 'Reese', 'Organ', 'Bell', 'Air',
           'Choir', 'Vox', 'Talk']
CHORDS = ['dia', 'dia_s', 'dia7', 'dia7_s', 'dia9', 'dia9_s', 'quartal',
          'quartal_s', 'power', 'power_s']
SCALES = [[0, 2, 4, 5, 7, 9, 11], [0, 2, 3, 5, 7, 8, 10], [0, 3, 5, 7, 10], [0, 2, 3, 5, 7, 8, 11],
          [0, 2, 3, 5, 7, 9, 10], [0, 1, 3, 5, 7, 8, 10], [0, 2, 4, 7, 9], [0, 2, 4, 5, 7, 9, 10],
          [0, 3, 5, 6, 7, 10], [0, 1, 4, 5, 7, 8, 10], list(range(12))]
MAJOR, MINOR, MIN_PENT, HARM_MINOR, PHRYG_DOM, CHROMATIC = 0, 1, 2, 3, 9, 10
SHAPES = {'quartal': [0, 5, 10, 15], 'power': [0, 7, 12]}
ROOTS = list(range(12))                             # semitones above C


def tune_for(step, scale):
    return round(step / (4 * len(SCALES[scale])) * 4095)


def degree(scale, d):
    sc = SCALES[scale]
    return 12 * (d // len(sc)) + sc[d % len(sc)]


def model_chord(step, scale=MAJOR, root=0, chord='dia', note=36):
    """The chord in root position, as the README describes it."""
    sc = SCALES[scale]
    r = degree(scale, step)
    base = chord[:-2] if chord.endswith('_s') else chord
    if base in SHAPES:
        iv = SHAPES[base]
    else:
        cnt = {'dia': 3, 'dia7': 4, 'dia9': 5}[base]
        if scale == CHROMATIC:
            iv = {3: [0, 4, 7], 4: [0, 3, 7, 10], 5: [0, 3, 7, 10, 14]}[cnt]
        elif len(sc) == 7:
            iv = [0] + [degree(scale, step + 2 * i) - r for i in range(1, cnt)]
        else:
            def pick(cands):
                return next((c for c in cands if (r + c) % 12 in sc), cands[0])
            cands = [[4, 3, 5, 2], [7, 6, 8, 12], [10, 11, 9, 12], [14, 13, 15, 12]]
            iv = [0] + [pick(cands[i - 1]) for i in range(1, cnt)]
    return sorted(36 + root + r + note - 36 + i for i in iv)


def gate_knob(seconds):
    """The DECAY value for a GATE time: 0.05 s .. 2 s log-linear over 95% of the knob."""
    return round(0.95 * math.log(seconds / 0.05, 40) * 4095)


def note_hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def goertzel(x, f):
    w = 2 * math.pi * f / SR
    c = 2 * math.cos(w)
    s1 = s2 = 0.0
    for v in x:
        s1, s2 = v + c * s1 - s2, s1
    return s1 * s1 + s2 * s2 - c * s1 * s2


def env(x, w=480):
    return [max(abs(v) for v in x[i:i + w]) for i in range(0, len(x) - w + 1, w)]


def rms(x, w=4800):
    """RMS per 100 ms window (a chord beats, so its peaks wobble at a steady level)."""
    return [(sum(v * v for v in x[i:i + w]) / w) ** .5 for i in range(0, len(x) - w + 1, w)]


def s8(b):
    return b - 256 if b > 127 else b


HAVE_GCC = bool(shutil.which('arm-none-eabi-gcc'))


class AkordsCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = Image.load(require_image('v1.3.0'))
        cls.sym = Symbols(SYMBOLS_V130)
        cls.tmp = tempfile.mkdtemp(prefix='pk-ak-')
        cls.img, p = build_patched(cls.stock, ['voice_map', 'voice_akords'], cls.tmp + '/a')
        cls.cave = p.cave_symbols['m7host']

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- helpers -------------------------------------------------------------------------
    def machine(self, out=0, preset=8, chord='dia', scale=MAJOR, root=0):
        """Booted M7 with akords on `out` (engine 5: map value 4), its settings sent as the
        M4 does; root in semitones above C."""
        e = verify.boot(self.img, self.sym)
        m = [0, 1, 2, 3]
        m[out] = 4
        e.out = out
        e.knobs = [0, DRONE, 2048, 2048]  # PARAM1 / PARAM2 at 12 o'clock: the preset's own
        e.sw = (POS2, PLAY)
        self.state(e, list(e.knobs), POS2, PLAY)
        self.drive(e, 128)      # DRIVE at half: the level as it was (0 dB)
        remap(e, m, self.cave, MSG_VOICE_MAP)
        e.audio(960)            # let the mute-fade gain settle (it starts at 0 after boot)
        self.setup(e, preset, chord, scale, root)
        return e

    def state(self, e, params, algo, mode, mute=0):
        voices = [{'params': [2048] * 4} for _ in range(4)]
        voices[e.out if hasattr(e, 'out') else 0] = {'params': list(params), 'algo': algo, 'mode': mode, 'mute': mute}
        e.send_voice_state(voices)
        e.pump()
        e.audio(32)             # an update() with the new values
        e.knobs, e.sw = list(params), (algo, mode)

    def turn(self, e, mode, p1, p2, algo=POS2):
        """Switch to `mode` and turn PARAM1 / PARAM2 to p1 / p2 (moving them, so they set)."""
        k = list(e.knobs)
        self.state(e, k, algo, mode)
        k[2], k[3] = (0 if p1 > 2048 else 4095), (0 if p2 > 2048 else 4095)
        self.state(e, k, algo, mode)
        k[2], k[3] = p1, p2
        self.state(e, k, algo, mode)

    def drive(self, e, d):
        """The M4's DRIVE message: every output's DRIVE at d (0-255)."""
        e.send(2, MSG_AKORDS_DRIVE, bytes([d] * 4))
        e.audio(32)

    def settings(self, e, rows):
        """The M4's settings message: rows = 4 x [preset, chord, scale, root] indices."""
        e.send(2, MSG_AKORDS, bytes(x for r in rows for x in r))
        e.audio(32)

    def setup(self, e, preset, chord, scale, root):
        rows = [[0, 0, 0, 0] for _ in range(4)]
        rows[e.out] = [preset, CHORDS.index(chord), scale, ROOTS.index(root)]
        self.settings(e, rows)

    def play(self, e, tune=None, decay=None, note=36, vel=127, n=4800, trig=True):
        k = list(e.knobs)
        if tune is not None:
            k[0] = tune
        if decay is not None:
            k[1] = decay
        self.state(e, k, *e.sw)
        if trig:
            am = [(0, 0)] * 4
            am[e.out] = e.sw
            e.send_triggers([o == e.out for o in range(4)], am, vel, note)
        return e.audio(n)[e.out]

    def info(self, e):
        """The settings, the last chord and the chord slot (notes: up to 5; unused -1)."""
        o = e.slot(e.out)
        b = o + 0xd0

        def notes(a):
            return [n for n in (s8(e.r8(a + i)) for i in range(5)) if n >= 0]
        slots = [{'stage': e.r32(b), 'notes': notes(b + 4), 'preset': e.r8(b + 9), 'count': e.r8(b + 10)}]
        return {'set': [e.r8(o + 0xc0 + i) for i in range(4)], 'last': notes(o + 0xc4), 'slots': slots}

    def chord_of(self, step, scale=MAJOR, root=0, chord='dia', note=36):
        e = self.machine(chord=chord, scale=scale, root=root)
        self.play(e, tune_for(step, scale), note=note, n=64)
        return self.info(e)['last']
