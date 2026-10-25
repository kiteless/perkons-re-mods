#!/usr/bin/env python3
"""Simulate the voice-remap feature in the M7 emulator (no firmware patch involved).

  remap_sim.py <img> <symbols.json> <outdir> --map 4,4,4,4 [--algo 0] [--mode 0] [--seconds 1]

--map gives, for outputs 1..4, which original voice engine to run (1=kick slot,
2=snare/fold slot, 3=resonant/slap/karplus slot, 4=hats/sample slot).
Each output is triggered in turn and written to <outdir>/out{n}.wav. Every remapped
output is also checked against the same engine rendered in its home slot; they must
be bit-identical.
"""
import argparse
import os
import sys

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(MOD, 'lib'))
sys.path.insert(0, os.path.join(os.environ.get('PERKONS_ROOT', os.path.join(MOD, '..', '..', 'perkons')), 'tools'))
from perkons.emu import M7Emu, Symbols, write_wav  # noqa: E402
from perkons.fwimage import Image  # noqa: E402
from vm_model import boot_remapped  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('img')
    ap.add_argument('symbols')
    ap.add_argument('outdir')
    ap.add_argument('--map', required=True)
    ap.add_argument('--algo', type=int, default=0)
    ap.add_argument('--mode', type=int, default=0)
    ap.add_argument('--params', default='2048,2048,2048,2048')
    ap.add_argument('--seconds', type=float, default=1.0)
    a = ap.parse_args()
    vmap = [int(x) - 1 for x in a.map.split(',')]
    params = [int(x) for x in a.params.split(',')]
    img, sym = Image.load(a.img), Symbols(a.symbols)
    m7, m4 = img.segment('m7').data, img.segment('m4').data
    n = int(a.seconds * 48000)

    e = boot_remapped(M7Emu(m7, sym, m4), vmap)
    print(f'instances: {[hex(x) for x in e.instances]}')
    ok = True
    for out, src in enumerate(vmap):
        # fresh machine per output: some engines share global state (e.g. a noise PRNG), so
        # rendering one output first would otherwise shift the next one's noise sequence
        e = boot_remapped(M7Emu(m7, sym, m4), vmap)
        e.set_params(out, params)
        e.set_algo_mode(out, a.algo, a.mode)
        e.trigger(out)
        got = e.render(out, n)
        write_wav(os.path.join(a.outdir, f'out{out + 1}.wav'), got)
        ref = M7Emu(m7, sym, m4).boot_voices()
        ref.set_params(src, params)
        ref.set_algo_mode(src, a.algo, a.mode)
        ref.trigger(src)
        same = ref.render(src, n) == got
        ok &= same
        print(f'output {out + 1}: {e.class_of(e.slot(out)):12s} @0x{e.slot(out):08x}  '
              f'peak={max(map(abs, got)):6d}  matches home-slot render: {same}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
