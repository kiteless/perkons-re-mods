"""voice-zibens: a scale-stepped synth voice with an MS-style resonant filter (M7). An extra
voice-map engine (the engine page column of its slot). Needs voice_map in the same
build."""
import os

from perkons.patch import PatchError

TARGET = 'v1.3.0'
SUMMARY = 'voice-zibens synth voice for voice-map: scale-stepped saw/square/sine'
RISK = 'medium'

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(MOD, 'src', 'm7')


def apply(p, arg=None):
    """arg: the voice slot (engine number, 5-16) it's installed in; none: the next free one."""
    vm = p.shared.setdefault('voice_map', {'engines': {}})
    if 'zibens' in vm['engines']:
        raise PatchError('voice-map engine name zibens already taken')
    vm['engines']['zibens'] = {'sources': [os.path.join(SRC, 'zibens.c')], 'include_dirs': [SRC],
                               'build': 'pk_zb_build', 'slot': int(arg) if arg else None}

    def needs_voice_map():
        if not p.shared['voice_map'].get('m7'):
            raise PatchError('voice-zibens is a voice-map engine: build it together with voice_map')
    p.on_finish(needs_voice_map)
