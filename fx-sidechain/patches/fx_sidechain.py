"""fx-sidechain: the master voice's triggers duck the other three voices (M7), with its
controls (KIT + SYNC, its page) and each kit's settings (M4)."""
import os
import sys

from perkons.patch import PatchError

TARGET = 'v1.3.0'
SUMMARY = 'Sidechain: the master voice ducks the other voices (depth, attack, hold, release)'
RISK = 'medium'

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_M7 = os.path.join(MOD, 'src', 'm7')
SRC_M4 = os.path.join(MOD, 'src', 'm4')
sys.path.insert(0, os.path.join(MOD, 'lib'))
import sc_model  # noqa: E402


def apply(p, arg=None):
    """arg 'test' (development): the M7 part alone, on from boot with the default settings
    (no M4 part: no page, nothing saved)."""
    if arg not in (None, '', 'test'):
        raise PatchError(f'fx_sidechain: unknown argument {arg!r}')
    from perkons import m7host
    h = m7host.host(p)
    d = sc_model.DEFAULTS
    defines = {'PK_SC_DEFAULT_ON': '1' if arg == 'test' else '0',
               **{f'PK_SC_DEFAULT_{k.upper()}': str(v) for k, v in d.items()}}
    h.add([os.path.join(SRC_M7, 'sidechain.c')], [SRC_M7], init='pk_sc_init', defines=defines,
          headers={'sc_tables.h': sc_model.tables_header()})
    h.message('fx-sidechain', 'pk_sc_on_msg', ordered=True)
    # after voice-map's hook (order 0), which may rebuild the output's object
    h.redirect_call('trigger_dispatch.call_set_velocity', 'pk_sc_velocity',
                    'trigger dispatch: wrap the output\'s render, the master starts the duck', order=1)
    if arg == 'test':
        return                      # the M7 part alone, on from boot

    # M4: KIT + SYNC, the page, each kit's settings (kit sidecar record SCHN)
    from perkons import m4host
    m4 = m4host.host(p)
    m4.add([os.path.join(SRC_M4, 'sidechain_m4.c')], [SRC_M4], init='pk_sc_m4_init', defines=defines)
    m4.store('kit', 'SCHN', 'pk_sc_kit_save', 'pk_sc_kit_restore')
    for site in sorted(k for k in p.symbols['m4'].sites if k.startswith('kits.load.')):
        if p.symbols['m4'].site(site).get('branch'):
            m4.redirect_branch(site, 'pk_sc_kit_load', 'kit load: the kit\'s sidechain')
        else:
            m4.redirect_call(site, 'pk_sc_kit_load', 'kit load: the kit\'s sidechain')
    m4.replace_word('keys.handler_lit', 'pk_sc_key_event', 'KIT + SYNC: sidechain on/off, hold: its page')
    m4.redirect_call('main.call_switch_done', 'pk_sc_main_loop', 'main loop: KIT + SYNC held opens the page')
    for site in ('sidechain.trig_led.08103c6a', 'sidechain.sync_led.08103ca6'):
        m4.redirect_call(site, 'pk_sc_led', 'ui_update: the master and on / off on the page')
    m4.page('sidechain', key='pk_sc_page_key', draw='pk_sc_page_draw', enter='pk_sc_page_enter',
            leave='pk_sc_page_leave')
