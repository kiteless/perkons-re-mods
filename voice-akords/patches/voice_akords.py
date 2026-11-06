"""voice-akords: a chord synth voice after a poly synth built on iOS (M7). An extra voice-map
engine (the engine page column of its slot), with a settings page of its own (a long press
on its step on the engine page). Needs voice_map in the same build."""
import os

from perkons.patch import PatchError

TARGET = 'v1.3.0'
SUMMARY = 'voice-akords chord synth voice for voice-map: chords of up to 5 notes, progressions, 14 presets'
RISK = 'medium'

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(MOD, 'src', 'm7')
SRC_M4 = os.path.join(MOD, 'src', 'm4')


def apply(p, arg=None):
    """arg: the voice slot (engine number, 5-16) it's installed in; none: the next free one."""
    from perkons import m4host, m7host

    def needs_voice_map():
        if not p.shared['voice_map'].get('m7'):
            raise PatchError('voice-akords is a voice-map engine: build it together with voice_map')
    p.on_finish(needs_voice_map)        # first: before the hosts' builds (finishers run in order)
    vm = p.shared.setdefault('voice_map', {'engines': {}})
    if 'akords' in vm['engines']:
        raise PatchError('voice-map engine name akords already taken')
    vm['engines']['akords'] = {'sources': [os.path.join(SRC, 'akords.c')], 'include_dirs': [SRC],
                               'build': 'pk_ak_build', 'slot': int(arg) if arg else None,
                               'page': 'akords'}
    # M7: each voice's settings (preset, chord type, scale, root), in order with the triggers
    m7host.host(p).message('akords', 'pk_ak_on_settings', ordered=True)
    # M7: each voice's DRIVE (the engine's level follows it)
    m7host.host(p).message('akords-drive', 'pk_ak_on_drive', ordered=True)
    # M7: each voice's progression offset (scale degrees), before the step's triggers
    m7host.host(p).message('akords-prog', 'pk_ak_on_prog', ordered=True)
    # M4: the settings of each kit's voices (kit sidecar record AKRD), the settings page
    h = m4host.host(p)
    h.add([os.path.join(SRC_M4, 'akords_m4.c')], [SRC_M4])
    h.store('kit', 'AKRD', 'pk_ak_kit_save', 'pk_ak_kit_restore')
    for site in sorted(k for k in p.symbols['m4'].sites if k.startswith('kits.load.')):
        if p.symbols['m4'].site(site).get('branch'):
            h.redirect_branch(site, 'pk_ak_kit_load', 'kit load: Akords settings')
        else:
            h.redirect_call(site, 'pk_ak_kit_load', 'kit load: Akords settings')
    h.redirect_call('main.call_switch_done', 'pk_ak_main_loop', 'main loop: Akords DRIVE to the M7')
    for site in ('akords.send_triggers.08101e28', 'akords.send_triggers.08102ad0'):
        h.redirect_branch(site, 'pk_ak_send_triggers', 'triggers: Akords progressions first')
    h.page('akords', key='pk_ak_page_key', draw='pk_ak_page_draw', enter='pk_ak_page_enter',
           leave='pk_ak_page_leave')
