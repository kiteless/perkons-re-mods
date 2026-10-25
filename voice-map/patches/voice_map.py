"""Voice map from the SD card (phases F2/F3, M4 + M7).

  voice_map        (= voice_map:root) F2: voices.json in the SD root, read at every bank load
  voice_map:bank   F3: BANKS/NN/voices.json if present, else the root voices.json

Boots with the stock layout; the M4 sends the map after each bank's samples load and the
M7 switches engines live (instant cut). See patches/src/m4/voice_map_m4.c and
patches/src/m7/voice_map.c.
"""
from _voice_map_common import apply_m4, apply_m7

TARGET = 'v1.3.0'
SUMMARY = 'Per-output voice engines from voices.json (F2 root / F3 per bank)'
RISK = 'medium'


def apply(p, arg='root'):
    if arg not in ('root', 'bank'):
        raise ValueError("voice_map takes 'root' or 'bank'")
    apply_m7(p, [0, 1, 2, 3])
    apply_m4(p, per_bank=(arg == 'bank'))
