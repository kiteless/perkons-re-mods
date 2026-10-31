"""per-track-lfo: one modulation LFO per voice, split off with the trigger keys.
Built by the framework's M4 host; hook sites are in
../symbols/<version>-m4.json (merged into the framework's symbols)."""
import os

from perkons import m4host

TARGET = 'v1.3.0'
SUMMARY = 'LFO groups: hold trigger keys and turn the LFO knobs to give those voices their own LFO'
RISK = 'medium'

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(MOD, 'src', 'm4')

HOOKS = {'update': ('pk_lf_update', 'modulation LFO: every voice\'s LFO steps'),
         'sync_tick': ('pk_lf_sync_tick', 'synced LFO rate: split LFOs too'),
         'voice': ('pk_lf_voice', 'per-voice loop: that voice\'s LFO output'),
         'rate': ('pk_lf_rate', 'RATE knob: held trigger keys split their voices'),
         'wave': ('pk_lf_wave', 'WAVE knob: held trigger keys split their voices'),
         'level': ('pk_lf_level', 'MOD LVL knob: held trigger keys split their voices'),
         'sync_key': ('pk_lf_sync_key', 'SYNC: held trigger keys split their voices'),
         'reset': ('pk_lf_reset', 'LFO restart: split LFOs too'),
         'led': ('pk_lf_led', 'LFO LED: the held voice\'s LFO'),
         'sync_led': ('pk_lf_sync_led', 'SYNC LED: the held voice\'s LFO'),
         'trig_led': ('pk_lf_trig_led', 'trigger LEDs: LFO groups and the selection')}


def apply(p, arg=None):
    h = m4host.host(p)
    h.add([os.path.join(SRC, 'per_track_lfo.c')], [SRC])
    for site in sorted(k for k in p.symbols['m4'].sites if k.startswith('ptlfo.')):
        sym, why = HOOKS[site.split('.')[1]]
        h.redirect_call(site, sym, why)
    for event in ('track_clear', 'automation_clear', 'pattern_clear'):
        h.on(event, 'pk_lf_rejoin')         # one LFO for every voice again
