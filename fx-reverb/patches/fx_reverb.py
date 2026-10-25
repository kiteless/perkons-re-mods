"""fx-reverb: reverb instead of the BBD delay (config row 3 step 15), and the SHORT/LONG
switch as freeze (row 3 step 16; delay freeze = looper). M4 only. See docs/design.md."""
import os
import struct

from perkons import cbuild
from fxr import JSON_KEY_FREEZE, JSON_KEY_REVERB, OFF_CFG_FREEZE, OFF_CFG_REVERB, PK4_STATE_ADDR

TARGET = 'v1.3.0'
SUMMARY = 'FX reverb (config switchable with the BBD delay), freeze / looper on the 2-way switch'
RISK = 'medium'

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(MOD, 'src', 'm4')
JSON_BOOL = 0x80


def extended_schema(p, sym, at):
    """The firmware's device.json schema plus our two keys, laid out at address `at`."""
    seg = p.img.segment('m4')
    rd = lambda a, n: p.read('m4', a, n)
    schema = sym.g['device_json_schema']
    entries, count = struct.unpack('<II', rd(schema, 8))
    original = rd(entries, 20 * count)
    keys = [(JSON_KEY_REVERB, OFF_CFG_REVERB), (JSON_KEY_FREEZE, OFF_CFG_FREEZE)]
    n = count + len(keys)
    entries_at = at + 8
    strings_at = entries_at + 20 * n
    blob = struct.pack('<II', entries_at, n) + original
    strings = b''
    for key, off in keys:
        rel = (PK4_STATE_ADDR + off - sym.g['device_config']) & 0xffffffff
        blob += struct.pack('<5I', strings_at + len(strings), rel, JSON_BOOL, 0, 0)
        strings += key.encode() + b'\0'
    blob += strings
    assert seg.addr <= entries and len(blob) == 8 + 20 * n + len(strings)
    return blob


def apply(p, arg=None):
    sym = p.symbols['m4']
    origin = p.cave_origin('m4')
    blob, syms = cbuild.build('m4', [os.path.join(SRC, 'fx.c'), os.path.join(SRC, 'reverb.c')], [SRC],
                              os.path.join(p.build_dir, 'fx_reverb'), origin, 'pk4_fx_process', sym)
    assert p.append('m4', blob, f'fx-reverb code ({len(blob)} B)', align=16) == origin
    at = p.cave_origin('m4', align=4)
    schema = extended_schema(p, sym, at)
    assert p.append('m4', schema, f'device.json schema + 2 keys ({len(schema)} B)', align=4) == at

    proc = syms['pk4_fx_process'] | 1
    p.replace_word('m4', 'fx.fnptr_initial', proc, 'FX process pointer (initial) -> pk4_fx_process')
    p.replace_word('m4', 'fx_set_processor.normal_literal', proc, 'FX process pointer (normal mode) -> pk4_fx_process')
    p.redirect_call('m4', 'fx_update.call_read_switch', syms['pk4_fx_read_switch'], 'fx_update: SHORT/LONG read -> freeze-aware')
    p.replace_word('m4', 'cfg_page.event_word', syms['pk4_cfg_event'] | 1, 'config page events -> +2 toggles')
    p.replace_word('m4', 'cfg_page.render_word', syms['pk4_cfg_render'] | 1, 'config page LEDs -> +2 toggles')
    p.redirect_call('m4', 'boot_init.call_config_files_init', syms['pk4_boot'], 'boot: defaults, then load device.json')
    for site in ('device_schema.load_literal', 'device_schema.create_literal', 'device_schema.save_literal'):
        p.replace_word('m4', site, at, f'{site.split(".")[1]}: device.json schema -> extended')
    p.replace_word('m4', 'sbrk.limit_literal', PK4_STATE_ADDR + int(sym.raw['heap']['min_stack'], 16),
                   '_sbrk: cap M4 heap below patch RAM')
    p.cave_symbols = getattr(p, 'cave_symbols', {})
    p.cave_symbols['m4'] = syms
