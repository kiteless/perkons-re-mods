"""Shared builders for the voice-map patches (not a patch itself)."""
import os
import struct

from perkons import cbuild
from perkons.patch import thumb_bl
from vm_model import PK_RAM_BASE, gen_slot_layout_header

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_M7 = os.path.join(MOD, 'src', 'm7')
SRC_M4 = os.path.join(MOD, 'src', 'm4')


def _cave_origin(p, seg_name):
    seg = p.img.segment(seg_name)
    return (seg.addr + len(p.read(seg_name, seg.addr, 0x7fffffff)) + 15) & ~15


def _hooker(p, seg_name, syms):
    def hook(site, old_target, new_fn, why):
        p.write(seg_name, site, thumb_bl(site, syms[new_fn]), thumb_bl(site, old_target), why)
    return hook


def apply_m7(p, initial_map):
    """M7: engine copies per output, live remap via config message type 4.
    initial_map: 4 ints 0-3 (engine per output at boot)."""
    packed = sum(v << (4 * i) for i, v in enumerate(initial_map))
    sym = p.symbols['m7']
    origin = _cave_origin(p, 'm7')
    layout = gen_slot_layout_header(p.img.segment('m7').data, sym, p.img.segment('m4').data)
    blob, syms = cbuild.build('m7', [os.path.join(SRC_M7, 'voice_map.c')], [SRC_M7],
                              os.path.join(p.build_dir, 'm7'), origin, 'pk_boot', sym,
                              extra_headers={'slot_layout.h': layout},
                              defines={'PK_MAP': f'0x{packed:04x}u'})
    assert p.append('m7', blob, f'M7 voice_map code ({len(blob)} B)', align=16) == origin
    hook = _hooker(p, 'm7', syms)
    hook(0x08027c9e, 0x080241d8, 'pk_boot', 'main: wire_voices -> pk_boot')
    hook(0x08027d08, 0x0802874c, 'pk_cfg_recv', 'main: unknown config msg -> pk_cfg_recv (voice map)')
    hook(0x08027dd8, 0x08026eb0, 'pk_sample_load_a', 'main: sample load_a -> all sampler instances')
    hook(0x08027e1e, 0x080270bc, 'pk_sample_load_b', 'main: sample load_b -> all sampler instances')
    p.write('m7', 0x08027d30, thumb_bl(0x08027d30, syms['pk_p2cfg']), bytes.fromhex('82f86d3c'),
            'main: P2-config store -> all sampler instances')
    hook(0x0802583a, 0x08026d98, 'pk_sampler_render', 'cFourthSlot: sampler render -> per-output static')
    hook(0x08025856, 0x080258b0, 'pk_crush_render', 'cFourthSlot: noise-crush render -> per-output static')
    p.write('m7', 0x0802870c, struct.pack('<I', PK_RAM_BASE + 0x400), struct.pack('<I', 0x20020000),
            '_sbrk: cap heap below patch RAM')
    p.cave_symbols = getattr(p, 'cave_symbols', {})
    p.cave_symbols['m7'] = syms


def apply_m4(p, per_bank):
    """M4: read voices.json after each bank's samples load and send the map to the M7."""
    sym = p.symbols['m4']
    origin = _cave_origin(p, 'm4')
    blob, syms = cbuild.build('m4', [os.path.join(SRC_M4, 'voice_map_m4.c')], [SRC_M4],
                              os.path.join(p.build_dir, 'm4'), origin, 'pk4_load_samples', sym,
                              defines={'PK_PER_BANK': '1' if per_bank else '0'})
    assert p.append('m4', blob, f'M4 voice_map code ({len(blob)} B)', align=16) == origin
    hook = _hooker(p, 'm4', syms)
    for site, where in ((0x081016e0, 'boot_init'), (0x081025b6, 'switch_bank'), (0x081026c0, 'boot_load_last_bank')):
        hook(site, 0x08101540, 'pk4_load_samples', f'{where}: load_samples -> pk4_load_samples')
    p.cave_symbols = getattr(p, 'cave_symbols', {})
    p.cave_symbols['m4'] = syms
