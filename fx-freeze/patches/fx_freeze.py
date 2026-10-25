"""fx-freeze: the FX 2-way switch as freeze (config row 3 step 16). Delay: looper;
with fx-reverb: reverb hold. M4 only, built by the framework's M4 host."""
import os

from perkons import m4host

TARGET = 'v1.3.0'
SUMMARY = 'FX freeze on the 2-way switch (delay looper; reverb hold with fx-reverb)'
RISK = 'medium'

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(MOD, 'src', 'm4')
KEY_SWITCH_MODE = 47        # config row 3 step 16


def apply(p, arg=None):
    h = m4host.host(p)
    h.add([os.path.join(SRC, 'fx_freeze.c')], [SRC])
    h.toggle(KEY_SWITCH_MODE, 'fx-switch-freeze', 'pk_cfg_freeze')
    h.fx()
    h.redirect_call('fx_update.call_read_switch', 'pk_fx_read_switch', 'fx_update: SHORT/LONG read -> freeze-aware')
