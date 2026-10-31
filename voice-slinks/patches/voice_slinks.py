"""voice-slinks: a scale-stepped synth voice with an MS-style resonant filter (M7). An extra
voice-map engine: "slinks" in voices.json puts it on an output. Needs voice_map in the same
build."""
import os

from perkons.patch import PatchError

TARGET = 'v1.3.0'
SUMMARY = 'voice-slinks synth voice for voice-map ("slinks" in voices.json): scale-stepped saw/square/sine'
RISK = 'medium'

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(MOD, 'src', 'm7')


def apply(p, arg=None):
    vm = p.shared.setdefault('voice_map', {'engines': {}})
    if 'slinks' in vm['engines']:
        raise PatchError('voice-map engine name slinks already taken')
    vm['engines']['slinks'] = {'sources': [os.path.join(SRC, 'slinks.c')], 'include_dirs': [SRC],
                               'build': 'pk_sl_build'}

    def needs_voice_map():
        if not p.shared['voice_map'].get('m7'):
            raise PatchError('voice-slinks is a voice-map engine: build it together with voice_map')
    p.on_finish(needs_voice_map)
