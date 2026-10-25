"""Shared builders for the voice-map patches (not a patch itself)."""
import os
from perkons import cbuild
from vm_model import PK_RAM_BASE, gen_slot_layout_header

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_M7 = os.path.join(MOD, 'src', 'm7')
SRC_M4 = os.path.join(MOD, 'src', 'm4')


def apply_m7(p, initial_map):
    """M7: engine copies per output, live remap via config message type 4.
    initial_map: 4 ints 0-3 (engine per output at boot)."""
    packed = sum(v << (4 * i) for i, v in enumerate(initial_map))
    sym = p.symbols['m7']
    origin = p.cave_origin('m7')
    layout = gen_slot_layout_header(p.img.segment('m7').data, sym, p.img.segment('m4').data)
    blob, syms = cbuild.build('m7', [os.path.join(SRC_M7, 'voice_map.c')], [SRC_M7],
                              os.path.join(p.build_dir, 'm7'), origin, 'pk_boot', sym,
                              extra_headers={'slot_layout.h': layout},
                              defines={'PK_MAP': f'0x{packed:04x}u'})
    assert p.append('m7', blob, f'M7 voice_map code ({len(blob)} B)', align=16) == origin
    p.redirect_call('m7', 'main.call_wire_voices', syms['pk_boot'], 'main: wire_voices -> pk_boot')
    p.redirect_call('m7', 'main.cfg_unknown_recv', syms['pk_cfg_recv'], 'main: unknown config msg -> pk_cfg_recv (voice map)')
    p.redirect_call('m7', 'main.call_sample_load_a', syms['pk_sample_load_a'], 'main: sample load_a -> all sampler instances')
    p.redirect_call('m7', 'main.call_sample_load_b', syms['pk_sample_load_b'], 'main: sample load_b -> all sampler instances')
    p.replace_with_call('m7', 'main.store_p2cfg', syms['pk_p2cfg'], 'main: P2-config store -> all sampler instances')
    p.redirect_call('m7', 'cFourthSlot_render.call_sampler_render', syms['pk_sampler_render'],
                    'cFourthSlot: sampler render -> per-output static')
    p.redirect_call('m7', 'cFourthSlot_render.call_crush_render', syms['pk_crush_render'],
                    'cFourthSlot: noise-crush render -> per-output static')
    p.replace_word('m7', 'sbrk.limit_literal', PK_RAM_BASE + int(sym.raw['heap']['min_stack'], 16),
                   '_sbrk: cap heap below patch RAM')
    p.cave_symbols = getattr(p, 'cave_symbols', {})
    p.cave_symbols['m7'] = syms


def apply_m4(p, per_bank):
    """M4: read voices.json after each bank's samples load and send the map to the M7."""
    sym = p.symbols['m4']
    origin = p.cave_origin('m4')
    blob, syms = cbuild.build('m4', [os.path.join(SRC_M4, 'voice_map_m4.c')], [SRC_M4],
                              os.path.join(p.build_dir, 'm4'), origin, 'pk4_load_samples', sym,
                              defines={'PK_PER_BANK': '1' if per_bank else '0'})
    assert p.append('m4', blob, f'M4 voice_map code ({len(blob)} B)', align=16) == origin
    for site in ('boot_init.call_load_samples', 'switch_bank.call_load_samples',
                 'boot_load_last_bank.call_load_samples'):
        p.redirect_call('m4', site, syms['pk4_load_samples'], f'{site.split(".")[0]}: load_samples -> pk4_load_samples')
    p.cave_symbols = getattr(p, 'cave_symbols', {})
    p.cave_symbols['m4'] = syms
