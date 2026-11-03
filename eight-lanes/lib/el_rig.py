"""eight-lanes tests: the built image (once per process) on the framework's M4Rig."""
import os
import sys
import tempfile

PERKONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'perkons')
for d in ('tools', 'tests'):
    if os.path.join(PERKONS, d) not in sys.path:
        sys.path.insert(0, os.path.join(PERKONS, d))
os.environ.setdefault('PERKONS_MODS', os.path.join(PERKONS, '..', 'perkons-re-mods'))

from fixtures import build_patched, require_image  # noqa: E402
from perkons.fwimage import Image  # noqa: E402
from perkons.rig import M4Rig  # noqa: E402

_cache = {}


def lanes_image(extra=()):
    key = tuple(extra)
    if key not in _cache:
        img, p = build_patched(Image.load(require_image('v1.3.0')), ['eight_lanes', *extra], tempfile.mkdtemp())
        _cache[key] = (img, p.cave_symbols['m4host'])
    return _cache[key]


def stock_image():
    return Image.load(require_image('v1.3.0'))


class LanesRig(M4Rig):
    def page(self):
        """0 = page A (tracks 1-4), 1 = page B (lanes 5-8)."""
        return self.e.r8(self.cave['pk_el_page'])

    def header(self, p):
        return self.sym.g['pat_headers'] + 0x20 * p


def lanes_rig(extra=(), sd=None, img=None):
    """The eight-lanes image (or `img`, e.g. stock) booted on the rig."""
    if img is None:
        img, cave = lanes_image(extra)
    else:
        cave = None
    return LanesRig(img, cave, sd=sd)


from perkons.emu import Symbols  # noqa: E402

SYM = Symbols(os.path.join(PERKONS, 'symbols', 'v1.3.0-m4.json'))      # names for the tests
DEVICE = SYM.g['device_config']
