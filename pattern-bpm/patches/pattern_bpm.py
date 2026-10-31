"""pattern-bpm: each pattern keeps the tempo it was saved at (config row 3 step 14).
Built by the framework's M4 host: a config toggle, a pattern sidecar record and the
pattern_switched event; no hook points of its own."""
import os

from perkons import m4host

TARGET = 'v1.3.0'
SUMMARY = 'Pattern BPM: each pattern plays at the tempo it was saved at (config row 3 step 14)'
RISK = 'low'

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(MOD, 'src', 'm4')
KEY = 45                    # config row 3 step 14


def apply(p, arg=None):
    h = m4host.host(p)
    h.add([os.path.join(SRC, 'pattern_bpm.c')], [SRC])
    h.toggle(KEY, 'pattern-bpm', 'pk_cfg_pattern_bpm')
    h.store('pattern', 'BPM1', 'pk_pb_save', 'pk_pb_load')
    h.on('pattern_switched', 'pk_pb_switched')
