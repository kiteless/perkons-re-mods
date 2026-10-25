"""Voice map with a fixed map compiled in (phase F1, M7 only).

Argument: 4 digits 1-4, one per output, naming the stock voice whose engine that output
runs (same numbering as voices.json). E.g. `voice_map_fixed:4434`.
See patches/src/m7/voice_map.c for the M7 changes.
"""
from _voice_map_common import apply_m7

TARGET = 'v1.3.0'
SUMMARY = 'Fixed per-output voice-engine map applied at boot (F1, M7 only)'
RISK = 'medium'


def parse_map(arg):
    if not arg or len(arg) != 4 or any(c not in '1234' for c in arg):
        raise ValueError('voice_map_fixed needs 4 digits 1-4, e.g. voice_map_fixed:4434')
    return [int(c) - 1 for c in arg]


def apply(p, arg=None):
    apply_m7(p, parse_map(arg))
