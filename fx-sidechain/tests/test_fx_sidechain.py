"""fx-sidechain on the M7: through main()'s message loop and the real audio callback, the
master's triggers duck the other outputs. Needs arm-none-eabi-gcc."""
import os
import shutil
import sys
import tempfile
import unittest

from fixtures import SYMBOLS_V130, build_patched, require_image
from perkons import verify
from perkons.emu import Symbols
from perkons.fwimage import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
import sc_model as M  # noqa: E402

HAVE_GCC = shutil.which('arm-none-eabi-gcc') is not None
# the M7 host's message types are given out in name order
MSG_SC, MSG_VOICE_MAP = 4, 5
KNOBS = [{'params': [2048, 2048, 4095, 2048]} for _ in range(4)]    # long, loud notes
LEAD = 4800                    # frames the voices sound before the master triggers (32-frame blocks)


def model(s, n):
    """The gain, sample by sample, from the master's trigger (sc_model's values)."""
    d, inc, hold, k = M.depth(s[2]), M.attack_inc(s[3]), M.hold_samples(s[4]), M.release_k(s[5])
    x, stage, left, out = 0.0, 1, 0, []
    for _ in range(n):
        if stage == 1:
            x += inc
            if x >= 1:
                x, stage, left = 1.0, 2, hold
        elif stage == 2:
            if left:
                left -= 1
            else:
                stage = 3
        elif stage == 3:
            x *= k
            if x < M.FLOOR:
                x, stage = 0.0, 0
        out.append(1 - d * x)
    return out


def floor_of(off):
    """The smallest undecked sample that's measured: a quarter of the output's peak."""
    return max(150, max(map(abs, off)) // 4)


def gains(on, off, lo=None):
    """{sample: on / off} where the undecked sample is big enough to measure (the duck
    truncates, so a gain is good to 1 / lo)."""
    lo = lo or floor_of(off)
    return {i: a / b for i, (a, b) in enumerate(zip(on, off)) if abs(b) >= lo}


@unittest.skipUnless(HAVE_GCC, 'arm-none-eabi-gcc not installed')
class TestSidechain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.stock = Image.load(require_image('v1.3.0'))
        cls.sym = Symbols(SYMBOLS_V130)
        cls.img, _ = build_patched(cls.stock, ['voice_map', 'fx_sidechain'], cls.tmp + '/vm')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def machine(self, settings, img=None):
        e = verify.boot(img or self.img, self.sym)
        e.send_voice_state(KNOBS)
        e.pump()
        e.send(2, MSG_SC, bytes(settings))
        return e

    def play(self, settings, events, img=None, before=None):
        """events: [(frames, trig)]: render `frames`, then send the triggers `trig`, ...; the
        voices that aren't the master start at 0. Returns the 4 outputs."""
        e = self.machine(settings, img)
        if before:
            before(e)
        master = settings[1]
        e.send_triggers([o != master for o in range(4)], [(0, 0)] * 4)
        outs = [[], [], [], []]
        for frames, trig in events:
            for o, x in zip(outs, e.audio(frames)):
                o += x
            if trig is not None:
                e.send_triggers(trig, [(0, 0)] * 4)
        return outs

    def pair(self, settings, events, **kw):
        """The same play with the duck on and off."""
        off = list(settings)
        off[0] = 0
        return self.play(settings, events, **kw), self.play(off, events, **kw)

    # -- off and idle: stock --------------------------------------------------------------
    def test_off_is_stock(self):
        img, _ = build_patched(self.stock, ['fx_sidechain'], self.tmp + '/off')
        bad = [r for r in verify.compare_to_stock(self.stock, img, self.sym) if not r[4]]
        self.assertEqual(bad, [])

    def test_wrapped_outputs_unchanged_until_the_master_triggers(self):
        on, off = self.pair([1, 0, 8, 1, 7, 9], [(LEAD, [1, 0, 0, 0]), (4800, None)])
        for o in range(4):
            self.assertEqual(on[o][:LEAD], off[o][:LEAD], o)
        self.assertEqual(on[0], off[0], 'the master is never ducked')

    # -- the duck's shape ------------------------------------------------------------------
    def check_shape(self, s, n=24000):
        on, off = self.pair(s, [(LEAD, [1 if o == s[1] else 0 for o in range(4)]), (n, None)])
        ref = model(s, n + 256)
        for o in range(4):
            if o == s[1]:
                self.assertEqual(on[o], off[o])
                continue
            g = gains(on[o], off[o])
            self.assertTrue(all(abs(v - 1) < 1e-3 for i, v in g.items() if i < LEAD), 'nothing before')
            after = {i - LEAD: v for i, v in g.items() if i >= LEAD}
            self.assertGreater(len(after), 300, f'output {o} too quiet to measure')
            # the envelope starts at this output's first sample after the trigger's block
            best = min(range(0, 65), key=lambda d: max(abs(v - ref[i - d]) if i >= d else abs(v - 1)
                                                       for i, v in after.items()))
            err = max(abs(v - ref[i - best]) if i >= best else abs(v - 1) for i, v in after.items())
            self.assertLess(err, 0.01 + 1 / floor_of(off[o]), f'output {o}: max gain error {err:.4f} (start +{best})')

    def test_shape_default(self):
        self.check_shape([1, 0, 8, 1, 7, 9])

    def test_shape_fast_and_full(self):
        self.check_shape([1, 0, 15, 0, 0, 0])      # silent, 0.5 ms, no hold, back after 10 ms

    def test_shape_shallow_and_slow(self):
        self.check_shape([1, 0, 2, 15, 8, 12])     # -6 dB, 50 ms, 175 ms, back after 500 ms

    def test_master_choice(self):
        self.check_shape([1, 2, 10, 3, 5, 6])

    def test_full_depth_is_silent(self):
        on, _ = self.pair([1, 0, 15, 0, 15, 15], [(LEAD, [1, 0, 0, 0]), (4800, None)])
        for o in (1, 2, 3):
            self.assertEqual(max(map(abs, on[o][LEAD + 200:LEAD + 4800])), 0, o)

    # -- no clicks -------------------------------------------------------------------------
    def assert_smooth(self, on, off, o):
        """No jump in the gain from one measured sample to the next (beyond truncation)."""
        g = gains(on, off)
        idx = sorted(g)
        steps = [abs(g[b] - g[a]) for a, b in zip(idx, idx[1:]) if b - a < 4]
        self.assertGreater(len(steps), 300, f'output {o} too quiet to measure')
        self.assertLess(max(steps), 0.01 + 2 / floor_of(off), o)

    def test_retrigger_continues_from_where_it_is(self):
        s = [1, 0, 12, 10, 0, 13]
        on, off = self.pair(s, [(LEAD, [1, 0, 0, 0]), (3200, [1, 0, 0, 0]), (6400, None)])
        for o in (1, 2):
            self.assert_smooth(on[o], off[o], o)

    def test_turning_off_lets_the_duck_finish(self):
        s = [1, 0, 12, 4, 3, 6]          # hold 50 ms, back after 125 ms
        runs = []
        for first in (1, 0):
            e = self.machine([first] + s[1:])
            e.send_triggers([0, 1, 1, 1], [(0, 0)] * 4)
            a = e.audio(LEAD)
            e.send_triggers([1, 0, 0, 0], [(0, 0)] * 4)
            b = e.audio(960)
            e.send(2, MSG_SC, bytes([0] + s[1:]))  # off during the duck
            c = e.audio(19200)                      # the duck (~320 ms) is over
            e.send_triggers([1, 0, 0, 0], [(0, 0)] * 4)
            d = e.audio(960)                        # off: the master's next trigger doesn't duck
            runs.append(([x + y + z for x, y, z in zip(a, b, c)], d))
        (on, after_on), (off, after_off) = runs
        for o in (1, 2):
            self.assert_smooth(on[o], off[o], o)
            g = gains(on[o], off[o])
            self.assertLess(min(v for i, v in g.items() if LEAD + 960 < i < LEAD + 2000), 0.5, 'still ducked')
        self.assertEqual(after_on, after_off)
        self.assertTrue(any(abs(v) > 100 for v in after_on[1]))

    # -- voice-map and other engines --------------------------------------------------------
    def test_engine_switch_keeps_the_duck(self):
        """voice-map rebuilds an output when it switches engine: it's wrapped again."""
        s = [1, 0, 15, 0, 15, 15]

        def remap(e):
            e.send(2, MSG_VOICE_MAP, bytes([0, 0, 2, 0]))   # outputs 2 and 4 run engine 1
        on = self.play(s, [(LEAD, [1, 0, 0, 0]), (4800, None)], before=remap)
        self.assertGreater(max(map(abs, on[1][:LEAD])), 1000)
        for o in (1, 2, 3):
            self.assertEqual(max(map(abs, on[o][LEAD + 200:])), 0, o)

    def test_with_zibens(self):
        img, _ = build_patched(self.stock, ['voice_map', 'voice_zibens', 'fx_sidechain'], self.tmp + '/zb')
        s = [1, 0, 15, 0, 15, 15]

        def remap(e):
            e.send(2, MSG_VOICE_MAP, bytes([0, 4, 2, 3]))   # output 2: zibens (engine 5)
        on = self.play(s, [(LEAD, [1, 0, 0, 0]), (4800, None)], img=img, before=remap)
        stock_engine = self.play(s, [(LEAD, None)], img=img)
        self.assertNotEqual(on[1][:LEAD], stock_engine[1][:LEAD], 'output 2 plays zibens')
        self.assertGreater(max(map(abs, on[1][:LEAD])), 300)
        self.assertEqual(max(map(abs, on[1][LEAD + 200:])), 0)

    def test_without_voice_map(self):
        img, _ = build_patched(self.stock, ['fx_sidechain:test'], self.tmp + '/alone')
        s = [1, 0, 15, 0, 15, 15]
        on = self.play(s, [(LEAD, [1, 0, 0, 0]), (4800, None)], img=img)
        self.assertGreater(max(map(abs, on[1][:LEAD])), 1000)
        for o in (1, 2, 3):
            self.assertEqual(max(map(abs, on[o][LEAD + 200:])), 0, o)

    def test_test_argument_starts_on(self):
        img, _ = build_patched(self.stock, ['voice_map', 'fx_sidechain:test'], self.tmp + '/test')
        e = verify.boot(img, self.sym)
        e.send_voice_state(KNOBS)
        e.pump()
        e.send_triggers([0, 1, 1, 1], [(0, 0)] * 4)
        a = e.audio(LEAD)
        e.send_triggers([1, 0, 0, 0], [(0, 0)] * 4)
        b = e.audio(4800)
        ref = self.play([0, 0, 8, 1, 7, 9], [(LEAD, [1, 0, 0, 0]), (4800, None)])
        g = gains(a[1] + b[1], ref[1])
        self.assertLess(min(g.values()), 0.2)       # about -15 dB at the bottom

    # -- cost --------------------------------------------------------------------------------
    def test_cpu(self):
        s = [1, 0, 8, 1, 15, 15]                        # all three ducking for the whole window
        counts = []
        for on in (1, 0):
            e = self.machine([on] + s[1:])
            e.send_triggers([0, 1, 1, 1], [(0, 0)] * 4)
            e.audio(LEAD)
            e.send_triggers([1, 0, 0, 0], [(0, 0)] * 4)
            e.audio(96)
            e.count_insns(True)
            e.insn_count = 0
            e.audio(960)
            counts.append(e.insn_count / 960)
            e.count_insns(False)
        vm, _ = build_patched(self.stock, ['voice_map'], self.tmp + '/vmonly')
        stock = verify.boot(vm, self.sym)
        stock.send_voice_state(KNOBS)
        stock.pump()
        stock.send_triggers([1, 1, 1, 1], [(0, 0)] * 4)
        stock.audio(LEAD + 96)
        stock.count_insns(True)
        stock.insn_count = 0
        stock.audio(960)
        base = stock.insn_count / 960
        print(f'\nfx-sidechain: ~{counts[0] - base:.0f} instructions per sample over voice-map ducking, '
              f'~{counts[1] - base:.0f} idle')
        self.assertLess(counts[0] - base, 150)
        self.assertLess(counts[1] - base, 40)


if __name__ == '__main__':
    unittest.main()
