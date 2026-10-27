"""zibens: a scale-stepped synth voice with an MS-style resonant filter (M7). An extra
voice-map engine: "zibens" in voices.json puts it on an output. Needs voice_map in the same
build. See docs/design.md."""
import os

from perkons.patch import PatchError

TARGET = 'v1.3.0'
SUMMARY = 'ZIBENS synth voice for voice-map ("zibens" in voices.json): scale-stepped saw/square/sine'
RISK = 'medium'

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(MOD, 'src', 'm7')
NUMBER = 5                  # voice-map engine number; voices.json selects it by name


def apply(p, arg=None):
    vm = p.shared.setdefault('voice_map', {'engines': {}})
    if NUMBER in vm['engines']:
        raise PatchError(f'voice-map engine {NUMBER} already taken by {vm["engines"][NUMBER]["name"]}')
    vm['engines'][NUMBER] = {'name': 'zibens', 'sources': [os.path.join(SRC, 'zibens.c')],
                             'include_dirs': [SRC], 'build': 'pk_zb_build'}

    def needs_voice_map():
        if not p.shared['voice_map'].get('m7'):
            raise PatchError('zibens is a voice-map engine: build it together with voice_map')
    p.on_finish(needs_voice_map)
