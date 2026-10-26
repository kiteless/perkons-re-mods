#!/usr/bin/env python3
"""Render ZIBENS demo phrases through the emulated M7 (real message loop and audio
callback) to WAV files for listening.

  cd ../perkons && .venv/bin/python ../perkons-re-mods/zibens/tools/render_demo.py [out_dir]

Writes <out_dir>/NN_name.wav (default ../perkons/out/zibens). Each phrase is a short
sequence of triggers with TONE stepping through the scale, like a sequenced bassline.
"""
import os
import sys
import tempfile

FRAMEWORK = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'perkons'))
sys.path[:0] = [os.path.join(FRAMEWORK, 'tests'), os.path.join(FRAMEWORK, 'tools'), FRAMEWORK]
os.environ.setdefault('PERKONS_MODS', os.path.join(FRAMEWORK, '..', 'perkons-re-mods'))

from fixtures import SYMBOLS_V130, build_patched, require_image  # noqa: E402
from perkons import verify  # noqa: E402
from perkons.emu import Symbols, write_wav  # noqa: E402
from perkons.fwimage import Image  # noqa: E402

SAW, SQUARE, SINE = 1, 0, 2
PENT, DORIAN, PHRYGIAN = 1, 0, 2
STEP = 6000                      # frames per sequencer step (1/16 at 120 BPM)

# (name, scale, wave, [TONE steps], DECAY, PARAM1, PARAM2 start, PARAM2 end, MIDI notes)
PHRASES = [
    ('saw_pent_dry',        PENT,     SAW,    [0, 2, 5, 3, 0, 5, 7, 4], 1300, 0,    0.0,  0.0, None),
    ('saw_pent_res_sweep',  PENT,     SAW,    [0, 2, 5, 3, 0, 5, 7, 4], 1300, 0,    0.0,  1.0, None),
    ('saw_phrygian_acid',   PHRYGIAN, SAW,    [0, 0, 7, 0, 1, 0, 8, 7], 1100, 0,    0.85, 0.85, None),
    ('square_dorian_pwm',   DORIAN,   SQUARE, [7, 9, 10, 7, 12, 10, 9, 5], 1500, 0, 0.0,  1.0, None),
    ('square_pent_narrow',  PENT,     SQUARE, [0, 2, 5, 3, 0, 5, 7, 4], 1300, 0,    0.8,  0.8, None),
    ('sine_pent_fold',      PENT,     SINE,   [5, 7, 10, 7, 5, 8, 10, 12], 1800, 0, 0.0,  1.0, None),
    ('sine_pad_slow_attack', DORIAN,  SINE,   [14, 16, 17, 14], 3000, 2600, 0.2, 0.2, None),
    # the same line three times, in C, F and G: MIDI notes 36 / 41 / 43 move the key
    ('saw_midi_key_c_f_g',  PENT,     SAW,    [0, 2, 5, 3, 0, 5, 7, 4], 1300, 0,    0.5,  0.5,
     [36] * 8 + [41] * 8 + [43] * 8),
]


def render_phrase(img, sym, scale, wave, steps, decay, p1, r0, r1, notes, steps_total=20):
    e = verify.boot(img, sym)
    e.send(3, 4, bytes([4, 1, 2, 3]))          # ZIBENS on output 1
    e.pump()
    out = []
    n = max(len(steps) * 2, len(notes or []))
    for i in range(n):
        st = steps[i % len(steps)]
        p2 = r0 + (r1 - r0) * i / max(1, n - 1)
        tone = round(min(st, steps_total) / steps_total * 4095)
        params = [tone, decay, p1, round(p2 * 4095)]
        voices = [{'params': [2048] * 4} for _ in range(4)]
        voices[0] = {'params': params, 'algo': scale, 'mode': wave}
        e.send_voice_state(voices)
        e.pump()
        note = notes[i % len(notes)] if notes else 36
        e.send_triggers([True, False, False, False], [(scale, wave), (0, 0), (0, 0), (0, 0)], 0x7f, note)
        out += e.audio(STEP)[0]
    return out


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(FRAMEWORK, 'out', 'zibens')
    stock = Image.load(require_image('v1.3.0'))
    sym = Symbols(SYMBOLS_V130)
    img, _ = build_patched(stock, ['voice_map:bank', 'zibens'], tempfile.mkdtemp(prefix='pk-zb-demo-'))
    for i, (name, scale, wave, steps, decay, p1, r0, r1, notes) in enumerate(PHRASES, 1):
        x = render_phrase(img, sym, scale, wave, steps, decay, p1, r0, r1, notes)
        path = os.path.join(out_dir, f'{i:02d}_{name}.wav')
        write_wav(path, x)
        print(f'{path}  peak {max(map(abs, x))}')


if __name__ == '__main__':
    main()
