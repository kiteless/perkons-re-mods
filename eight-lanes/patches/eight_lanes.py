"""eight-lanes: four MIDI-only sequencer lanes (5-8) beside tracks 1-4.
Built by the framework's M4 host; hook sites are in
../symbols/<version>-m4.json (merged into the framework's symbols)."""
import os

from perkons import m4host
from perkons.patch import thumb_bl

TARGET = 'v1.3.0'
SUMMARY = 'Eight lanes: four MIDI-only sequencer lanes on a second page'
RISK = 'high'

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(MOD, 'src', 'm4')
NOTES_SITES = ('notes.lit_prepare', 'notes.lit_send_triggers', 'notes.lit_fn_08102134')


def apply(p, arg=None):
    h = m4host.host(p)
    h.add([os.path.join(SRC, f) for f in ('el_core.c', 'el_patterns.c', 'el_page.c', 'el_config.c', 'el_kits.c', 'el_midi_in.c')], [SRC], init='pk_el_init')
    h.store('pattern', 'EL8P', 'pk_el_pat_save', 'pk_el_pat_load')       # lanes 5-8: PP.PAX
    h.store('kit', 'EL8K', 'pk_el_kit_rec_save', 'pk_el_kit_rec_load')    # lanes' kit values: KITS/PP.KIX
    h.replace_word('clock.tick_fnptr', 'pk_el_tick', 'sequencer tick -> lanes 5-8 after the stock tick')
    for site, sym, why in (
            ('main.call_switch_done', 'pk_el_switch_done', 'pattern switched: lanes follow the revert'),
            ('patpage.call_save_a', 'pk_el_save', 'save pattern: lanes too (.PA2)'),
            ('patpage.call_save_b', 'pk_el_save', 'save pattern: lanes too (.PA2)'),
            ('patpage.call_clear', 'pk_el_clear', 'clear pattern: lanes too'),
            ('switch_bank.call_bank_prepare', 'pk_el_bank_prepare', 'bank load: lanes from .PA2'),
            ('boot_load_last_bank.call_bank_prepare', 'pk_el_bank_prepare', 'bank load: lanes from .PA2'),
            ('keys.call_after_store_values', 'pk_el_after_store_values', 'knob values stored: lanes too')):
        h.redirect_call(site, sym, why)
    # page B: every UI call site found by the RE (symbols overlay, pageb.<group>.<addr>)
    hooks = {'ui_vs': ('pk_el_ui_vs', 'UI track from key row: lanes on page B'),
             'record': ('pk_el_record', 'knob/switch recording: engine controls follow the page'),
             'clear_slot': ('pk_el_clear_slot', 'CLEAR + control: follows the page'),
             'play': ('pk_el_play', 'trigger keys play the lane live on page B'),
             'trig_active': ('pk_el_trig_active', 'trigger LEDs show lanes on page B'),
             'ui_update': ('pk_el_ui_update', 'PATTERN LED dim on page B'),
             'mod_values': ('pk_el_mod_values', 'MOD page values: lanes on page B'),
             'roll_hold': ('pk_el_roll_hold', 'note repeat: lanes on page B'),
             'roll_rate_set': ('pk_el_roll_rate_set', 'note repeat rate: lanes on page B'),
             'roll_rate_get': ('pk_el_roll_rate_get', 'note repeat rate LEDs: lanes on page B'),
             'cc_out': ('pk_el_cc_out', 'knob/switch CC out: on the lane channel on page B'),
             'shift_vs': ('pk_el_shift_vs', 'SHIFT + knob: engine controls move the lanes on page B'),
             'restore_vs': ('pk_el_restore_vs', 'SHIFT released: lanes spring back too')}
    for site in sorted(k for k in p.symbols['m4'].sites if k.startswith('pageb.')):
        sym, why = hooks[site.split('.')[1]]
        h.redirect_call(site, sym, why)
    for site in sorted(k for k in p.symbols['m4'].sites if k.startswith('kits.')):
        kind = site.split('.')[1]
        if p.symbols['m4'].site(site).get('branch'):
            h.redirect_branch(site, f'pk_el_kit_{kind}', 'kit-link load: lanes too')
        else:
            h.redirect_call(site, f'pk_el_kit_{kind}', f'kit {kind}: lanes too (.KI2)')
    for n in range(5, 9):
        h.setting(f'lane{n}-midi-channel', f'pk_el_ch{n}')
        h.setting(f'lane{n}-trig-note', f'pk_el_tn{n}')
    h.replace_word('midi_page.event_word', 'pk_el_midi_page_event', 'MIDI channel page: lanes with SHIFT')
    h.replace_word('midi_page.render_word', 'pk_el_midi_page_render', 'MIDI channel page: lanes with SHIFT')
    h.replace_word('midi_in.dispatch_lit', 'pk_el_midi_in', 'MIDI in: lanes on their channels')
    h.replace_word('midi_in.dispatch_data', 'pk_el_midi_in', 'MIDI in: lanes on their channels')
    h.replace_word('midi_in.note_on_word', 'pk_el_note_on', 'MIDI note on: lanes by trigger note')
    h.replace_word('midi_in.note_off_word', 'pk_el_note_off', 'MIDI note off: lanes by trigger note')
    h.replace_word('keys.handler_lit', 'pk_el_key_event', 'key events: SHIFT + PATTERN flips the page')
    h.replace_word('page0.render_word', 'pk_el_page0_render', 'main page render: PATTERN LED dim on page B')

    def data_pointers():
        s = p.cave_symbols['m4host']
        for site in NOTES_SITES:
            p.replace_word('m4', site, s['pk_el_notes'], f'{site}: note records for 8 tracks')
        q = p.site('m4', 'seq_queue.entry')
        p.write('m4', q['addr'], thumb_bl(q['addr'], s['pk_el_queue'], link=False), q['bytes'],
                'queue next pattern -> pk_el_queue (expands the lanes)')
    p.on_finish(data_pointers)
