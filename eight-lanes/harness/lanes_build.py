"""Build the eight-lanes image once per process."""
import os
import sys
import tempfile

from seq_harness import PERKONS, SeqHarness  # noqa: F401  (sets sys.path)

os.environ.setdefault('PERKONS_MODS', os.path.join(PERKONS, '..', 'perkons-re-mods'))
from fixtures import build_patched, require_image  # noqa: E402
from perkons.fwimage import Image  # noqa: E402
from perkons.rig import stub_hardware  # noqa: E402

_cache = {}


def lanes_image(extra=()):
    key = tuple(extra)
    if key not in _cache:
        img, p = build_patched(Image.load(require_image('v1.3.0')), ['eight_lanes', *extra], tempfile.mkdtemp())
        _cache[key] = (img, p.cave_symbols['m4host'])
    return _cache[key]


def lanes_harness(extra=(), sd=None, img=None):
    """The eight-lanes image (or `img`, e.g. stock) booted in the harness, with the
    framework rig's hardware stubs (SD card present, DMA copies, silent DAC)."""
    if img is None:
        img, s = lanes_image(extra)
        hook = s['pk4_boot']
    else:
        s, hook = {}, None
    h = SeqHarness(img, sd=sd, boot_hook=hook)
    h.cave = s
    stub_hardware(h.e, h.sym)
    return h


def header(p):
    return 0x100026d0 + 0x20 * p


def queue_and_switch(h, p):
    """What the pattern page does when stopped: queue pattern p, switch now, then the main
    loop's revert/snapshot."""
    e = h.e
    e.call(0x0810dadc, header(p), max_insns=5_000_000)            # queue (detoured)
    e.call(0x0810daf4, max_insns=5_000_000)                       # switch now
    done = h.cave.get('pk_el_switch_done', 0x08101108)
    e.call(done, max_insns=50_000_000)


# ---- UI driving (page B) ------------------------------------------------------------
KEY_HELD = 0x0810b740        # FUN_0810b740(key): key held now (scanned matrix)
STEPS_HELD = 0x0810b784      # any step key held
EVT = 0x2407ff00             # scratch for event structs (end of the sample area)
LED = 0x08109414             # set_led(key, level)


class UI:
    """Key events into the patched key handler, with held keys and LEDs simulated."""

    def __init__(self, h):
        self.h, self.e = h, h.e
        self.held = set()
        self.leds = {}
        self.e.stub(KEY_HELD, lambda emu, k, *_: 1 if k in self.held else 0)
        self.e.stub(STEPS_HELD, lambda emu, *_: 1 if any(k < 0x40 for k in self.held) else 0)
        self.e.stub(LED, lambda emu, k, lvl, *_: self.leds.__setitem__(k, lvl))

    def event(self, key, down):
        self.e.uc.mem_write(EVT, bytes([key, 0x11 if down else 0x10, 0, 0, 0, 0, 0, 0]))
        if down:
            self.held.add(key)
        else:
            self.held.discard(key)
        return self.e.call(self.h.cave['pk_el_key_event'], EVT, max_insns=50_000_000)

    def press(self, key):
        self.event(key, True)
        self.event(key, False)

    def mode(self):
        return self.e.call(0x081040a4, max_insns=100_000)

    def set_mode(self, m):
        """Request a UI mode and apply it, as the main loop does (FUN_081040c8)."""
        self.e.call(0x08104098, m, max_insns=100_000)
        self.e.call(0x081040c8, max_insns=5_000_000)

    def page(self):
        return self.e.r8(self.h.cave['pk_el_page'])
