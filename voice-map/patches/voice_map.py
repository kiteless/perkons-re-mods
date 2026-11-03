"""Voice map: each kit chooses the engine each voice runs, on the engine page (KIT + MOD).
M4 + M7; see README.md."""
from _voice_map_common import apply_m4, apply_m7

TARGET = 'v1.3.0'
SUMMARY = 'Any engine on any voice, chosen per kit on the engine page (KIT + MOD)'
RISK = 'medium'


def apply(p, arg=None):
    """arg: ignored (older release definitions name `voice_map:bank`)."""
    apply_m7(p, [0, 1, 2, 3])
    apply_m4(p)
