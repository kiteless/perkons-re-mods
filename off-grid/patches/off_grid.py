"""off-grid: hits recorded as played, on the nearest step early or late (config row 3 step 13),
and hold a step + turn TEMPO to move it early or late (config row 3 step 12). Built by the
framework's M4 host; hook sites are in ../symbols/<version>-m4.json (merged into the
framework's symbols)."""
import os

from perkons import m4host

TARGET = 'v1.3.0'
SUMMARY = 'Off-grid: record hits as played, and move steps early/late with TEMPO (config row 3 steps 12, 13)'

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(MOD, 'src', 'm4')
KEY_EDIT = 43               # config row 3 step 12
KEY_RECORD = 44             # config row 3 step 13 (seq-unquantized's, and its setting)


def apply(p, arg=None):
    h = m4host.host(p)
    h.add([os.path.join(SRC, 'record.c'), os.path.join(SRC, 'tempo_edit.c')], [SRC])
    h.toggle(KEY_RECORD, 'unquantized', 'pk_cfg_unquantized')
    h.toggle(KEY_EDIT, 'microtiming', 'pk_cfg_microtiming')
    h.replace_word('keys.handler_lit', 'pk_og_rec_key_event', 'key events: which trigger key is handled')
    h.redirect_call('og.playing.081039ec', 'pk_og_playing', 'trigger key while recording: the delay as played')
    h.replace_word('og.midi_note_lit', 'pk_og_midi_note', 'MIDI notes while recording: the delay as played')
    h.redirect_call('og.tempo.08103bd6', 'pk_og_tempo', 'TEMPO with one step held: that step\'s timing')
    h.replace_word('og.page0_render.0812bf68', 'pk_og_render', 'main page LEDs: the division view')
    h.replace_word('keys.handler_lit', 'pk_og_key_event', 'key events: a step turned off loses its timing')
