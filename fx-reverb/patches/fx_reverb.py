"""fx-reverb: a reverb in place of the BBD delay, switchable on config row 3 step 15.
M4 only, built by the framework's M4 host. Works with fx-freeze."""
import os

from perkons import m4host

TARGET = 'v1.3.0'
SUMMARY = 'FX reverb (config switchable with the BBD delay)'
RISK = 'medium'

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(MOD, 'src', 'm4')
KEY_FX_TYPE = 46            # config row 3 step 15


def apply(p, arg=None):
    h = m4host.host(p)
    h.add([os.path.join(SRC, 'fx_reverb.c'), os.path.join(SRC, 'reverb.c')], [SRC], init='pk_reverb_init')
    h.toggle(KEY_FX_TYPE, 'fx-reverb', 'pk_cfg_reverb')
    h.fx()
    h.redirect_call('fx_lfo.call_led_pwm', 'pk_fx_lfo_led', 'fx_lfo: LFO LED -> reverb modulation in reverb mode')
