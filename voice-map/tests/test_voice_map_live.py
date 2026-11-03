"""Live engine changes on the M7: the map message (ordered, on the trigger stream) makes each
output switch at its next note. Runs the patched M7 through main()'s message loop and the
audio callback. Needs arm-none-eabi-gcc."""
import shutil
import tempfile
import unittest

from fixtures import SYMBOLS_V130, require_image
from perkons import verify
from perkons.emu import M4Emu, Symbols
from perkons.fwimage import Image
from perkons.mods import load_patch
from perkons.patch import Patcher
from vm_live import remap, send_map

vm = load_patch('voice_map')

SYMBOLS_M4 = SYMBOLS_V130.replace('-m7.json', '-m4.json')

OFF = Symbols(SYMBOLS_V130).off


def build(stock, mod, arg, tmp):
    p = Patcher(stock)
    p.symbols = {'m7': Symbols(SYMBOLS_V130), 'm4': Symbols(SYMBOLS_M4)}
    p.build_dir = tempfile.mkdtemp(dir=tmp)
    mod.apply(p, arg)
    return p.result(), p.cave_symbols


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestVoiceMapLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = Image.load(require_image('v1.3.0'))
        cls.sym7, cls.sym4 = Symbols(SYMBOLS_V130), Symbols(SYMBOLS_M4)
        cls.tmp = tempfile.mkdtemp(prefix='pk-f2-')
        cls.root, cls.root_syms = build(cls.stock, vm, None, cls.tmp)
        cls.cave = cls.root_syms['m7host']

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- M7 live remap ---------------------------------------------------------------
    def play(self, e, out, algo, mode, n=4000, settle=2048, params=verify.DEFAULT_PARAMS):
        voices = [{'params': [2048] * 4} for _ in range(4)]
        voices[out] = {'params': params, 'algo': algo, 'mode': mode}
        e.send_voice_state(voices)
        e.pump()
        e.audio(settle)
        am = [(0, 0)] * 4
        am[out] = (algo, mode)
        e.send_triggers([o == out for o in range(4)], am)
        return e.audio(n)[out]

    def test_live_remap_matches_boot_time_map(self):
        """A live remap gives the same engine state as booting with that map, given equal
        engine age (some engines free-run oscillators even while idle, so a copy built
        later is at a different phase -- harmless, but it would break bit-equality)."""
        import _voice_map_common as vmc

        class Fixed:                                        # a fixed map from boot (M7 only)
            @staticmethod
            def apply(p, arg):
                vmc.apply_m7(p, [int(c) - 1 for c in arg])
        fixed, _ = build(self.stock, Fixed, '4434', self.tmp)
        for out in range(4):
            for algo, mode in ((0, 0), (1, 1), (2, 2)):
                with self.subTest(output=out + 1, algo=algo, mode=mode):
                    live = verify.boot(self.root, self.sym7)
                    live.audio(512)                        # audio already running
                    remap(live, [3, 3, 2, 3], self.cave)
                    self.assertEqual(verify.HOME[live.class_of(live.slot(out))], [3, 3, 2, 3][out])
                    ref = verify.boot(fixed, self.sym7)
                    if [3, 3, 2, 3][out] == out:         # not remapped: the live engine is older
                        ref.audio(512 + 32)              # (the audio run, then send_map's block)
                    self.assertEqual(self.play(live, out, algo, mode), self.play(ref, out, algo, mode))

    def test_remap_keeps_output_state(self):
        e = verify.boot(self.root, self.sym7)
        voices = [{'params': [2048] * 4, 'algo': 1, 'mode': 2, 'mute': o == 1} for o in range(4)]
        e.send_voice_state(voices)
        e.pump()
        e.audio(256)
        remap(e, [3, 3, 3, 3], self.cave)
        for o in range(4):
            obj = e.slot(o)
            self.assertEqual((e.r8(obj + OFF['cVoice.algo']), e.r8(obj + OFF['cVoice.mode'])), (1, 2), f'output {o + 1} algo/mode')
            self.assertEqual(e.r8(obj + OFF['cVoice.mute']), 1 if o == 1 else 0, f'output {o + 1} mute')
        e.send_triggers([1, 1, 0, 0], [(1, 2)] * 4)
        outs = e.audio(2000)
        self.assertGreater(max(map(abs, outs[0])), 500)
        self.assertEqual(max(map(abs, outs[1])), 0, 'muted output must stay muted after a remap')

    def test_remapped_samplers_get_samples_and_p2(self):
        e = verify.boot(self.root, self.sym7)               # samples already "ready"
        e.send(3, 2, b'\x00\x01')                          # P2 config on
        e.pump()
        remap(e, [3, 3, 3, 3], self.cave)
        ptrs = [e.r32(e.slot(o) + OFF['cFourthSlot.sampler'] + OFF['cSamplePlayer.sample_ptr']) for o in range(4)]
        self.assertTrue(all(ptrs) and len(set(ptrs)) == 1, [hex(x) for x in ptrs])
        self.assertEqual([e.r8(e.slot(o) + OFF['cFourthSlot.p2cfg']) for o in range(4)], [1, 1, 1, 1])
        got = self.play(e, 0, 2, 0)
        stock = verify.boot(self.stock, self.sym7)
        stock.send(3, 2, b'\x00\x01')
        stock.pump()
        self.assertEqual(got, self.play(stock, 3, 2, 0), 'output 1 sampler must sound like stock voice 4')

    def test_bad_map_bytes_ignored(self):
        e = verify.boot(self.root, self.sym7)
        remap(e, [9, 3, 255, 0], self.cave)
        self.assertEqual(verify.engine_map_of(e), [0, 3, 2, 0])

    def test_switch_at_the_next_note_only(self):
        e = verify.boot(self.root, self.sym7)
        send_map(e, [3, 3, 2, 3])
        self.assertEqual(verify.engine_map_of(e), [0, 1, 2, 3], 'nothing switches before a note')
        e.send_triggers([1, 0, 0, 0], [(0, 0)] * 4)
        e.audio(64)
        self.assertEqual(verify.engine_map_of(e), [3, 1, 2, 3], 'only the output that played')
        e.send_triggers([0, 1, 0, 0], [(0, 0)] * 4)
        e.audio(64)
        self.assertEqual(verify.engine_map_of(e), [3, 3, 2, 3])

    def test_map_then_note_in_one_block_plays_the_new_engine(self):
        """The map and the note right after it reach the same audio callback: the note
        plays the new engine (no note on the old one first)."""
        e = verify.boot(self.root, self.sym7)
        e.send(2, 4, bytes([3, 1, 2, 3]))
        e.send_triggers([1, 0, 0, 0], [(2, 0)] * 4)
        got = e.audio(2000)[0]
        self.assertEqual(verify.engine_map_of(e)[0], 3)
        ref = verify.boot(self.stock, self.sym7)
        ref.send_triggers([0, 0, 0, 1], [(2, 0)] * 4)
        self.assertGreater(max(map(abs, got)), 300)
        self.assertEqual(got, ref.audio(2000)[3], 'output 1 plays stock voice 4 from that note')

    def test_dispatch_keeps_the_record_in_r7(self):
        """pk_vm_velocity reads the trigger record from r7 at the dispatch's set_velocity
        call; a firmware that keeps it elsewhere fails here."""
        from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, Cs
        seg = self.stock.segment('m7')
        site = self.sym7.site('trigger_dispatch.call_set_velocity')['addr']
        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
        insns = list(md.disasm(seg.data[site - 0x10 - seg.addr:site + 0x30 - seg.addr], site - 0x10))
        before = [i for i in insns if i.address < site]
        after = [i for i in insns if i.address > site]
        self.assertTrue(any(i.op_str == 'r1, [r7, #4]' for i in before), 'velocity from the record in r7')
        self.assertTrue(any(i.op_str == 'r3, [r7, #1]' for i in after), 'trigger flag from the record in r7')
