"""Phases F2/F3: M4 reads voices.json and sends the map; M7 remaps live.
Runs the patched M4 code against a virtual SD card and the patched M7 through main()'s
message loop and the audio callback. Needs arm-none-eabi-gcc; ~1-2 min."""
import json
import shutil
import tempfile
import unittest

from fixtures import SYMBOLS_V130, require_image
from perkons import verify
from perkons.emu import M4Emu, Symbols
from perkons.fwimage import Image
from perkons.mods import load_patch
from perkons.patch import Patcher

vm = load_patch('voice_map')
vmf = load_patch('voice_map_fixed')

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
        cls.root, cls.root_syms = build(cls.stock, vm, 'root', cls.tmp)
        cls.bank, cls.bank_syms = build(cls.stock, vm, 'bank', cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- M4 ---------------------------------------------------------------------------
    def m4_run(self, img, syms, sd, bank=7):
        e = M4Emu(img.segment('m4').data, self.sym4, img.segment('m7').data, sd=sd).boot()
        loaded = []
        e.stub(self.sym4.fn['load_samples'], lambda emu, b, *_: loaded.append(b))
        e.call(syms['m4']['pk4_load_samples'], bank)
        self.assertEqual(loaded, [bank], 'original load_samples must run first, with the same bank')
        msgs = e.sent(3)
        self.assertEqual(len(msgs), 1)
        mtype, payload = msgs[0]
        self.assertEqual(mtype, 4)
        return list(payload), e.sd_log

    def test_m4_map_from_root_file(self):
        cases = [
            (None, [0, 1, 2, 3]),                                                         # no file: stock
            ({'voice1': 'voice4', 'voice2': 'voice4', 'voice3': 'voice3', 'voice4': 'voice4'}, [3, 3, 2, 3]),
            ({'voice2': 'voice1'}, [0, 0, 2, 3]),                                         # missing keys: stock
            ({'voice1': 'Voice2', 'voice2': 'zibens', 'voice3': '', 'voice4': 'x'}, [0, 1, 2, 3]),  # unknown: stock
            ({'voice1': 4, 'voice2': '3'}, [0, 1, 2, 3]),                                 # numbers: stock
            ({'voice1': 'voice2', 'VOICE2': 'voice1', 'other': 'voice3'}, [1, 1, 2, 3]),  # keys case-sensitive
        ]
        for content, want in cases:
            with self.subTest(content=content):
                sd = {} if content is None else {'voices.json': json.dumps(content).encode()}
                self.assertEqual(self.m4_run(self.root, self.root_syms, sd)[0], want)
        got, _ = self.m4_run(self.root, self.root_syms, {'voices.json': b'garbage{'})
        self.assertEqual(got, [0, 1, 2, 3])

    def test_m4_root_build_ignores_bank_file(self):
        sd = {'BANKS/07/voices.json': b'{"voice1": "voice2"}', 'voices.json': b'{"voice1": "voice3"}'}
        self.assertEqual(self.m4_run(self.root, self.root_syms, sd)[0], [2, 1, 2, 3])

    def test_m4_bank_file_overrides_root(self):
        sd = {'BANKS/07/voices.json': b'{"voice1": "voice2"}', 'voices.json': b'{"voice1": "voice3", "voice2": "voice4"}'}
        got, log = self.m4_run(self.bank, self.bank_syms, sd, bank=7)
        self.assertEqual(got, [1, 1, 2, 3], 'bank file wins outright (root keys not merged)')
        self.assertIn(('stat', 'BANKS/07/voices.json'), log)

    def test_m4_bank_falls_back_to_root(self):
        sd = {'BANKS/03/voices.json': b'{"voice1": "voice2"}', 'voices.json': b'{"voice4": "voice1"}'}
        self.assertEqual(self.m4_run(self.bank, self.bank_syms, sd, bank=12)[0], [0, 1, 2, 0])
        self.assertEqual(self.m4_run(self.bank, self.bank_syms, {}, bank=12)[0], [0, 1, 2, 3])

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
        fixed, _ = build(self.stock, vmf, '4434', self.tmp)
        for out in range(4):
            for algo, mode in ((0, 0), (1, 1), (2, 2)):
                with self.subTest(output=out + 1, algo=algo, mode=mode):
                    live = verify.boot(self.root, self.sym7)
                    live.audio(512)                        # audio already running
                    live.send(3, 4, bytes([3, 3, 2, 3]))
                    live.pump()
                    self.assertEqual(verify.HOME[live.class_of(live.slot(out))], [3, 3, 2, 3][out])
                    ref = verify.boot(fixed, self.sym7)
                    if [3, 3, 2, 3][out] == out:         # not remapped: live engine is 512 frames older
                        ref.audio(512)
                    self.assertEqual(self.play(live, out, algo, mode), self.play(ref, out, algo, mode))

    def test_remap_keeps_output_state(self):
        e = verify.boot(self.root, self.sym7)
        voices = [{'params': [2048] * 4, 'algo': 1, 'mode': 2, 'mute': o == 1} for o in range(4)]
        e.send_voice_state(voices)
        e.pump()
        e.audio(256)
        e.send(3, 4, bytes([3, 3, 3, 3]))
        e.pump()
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
        e.send(3, 4, bytes([3, 3, 3, 3]))
        e.pump()
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
        e.send(3, 4, bytes([9, 3, 255, 0]))
        e.pump()
        self.assertEqual(verify.engine_map_of(e), [0, 3, 2, 0])

    def test_end_to_end_m4_message_drives_m7(self):
        sd = {'voices.json': b'{"voice1": "voice3", "voice2": "voice3", "voice3": "voice4", "voice4": "voice1"}'}
        payload, _ = self.m4_run(self.root, self.root_syms, sd)
        e = verify.boot(self.root, self.sym7)
        e.send(3, 4, bytes(payload))
        e.pump()
        self.assertEqual(verify.engine_map_of(e), [2, 2, 3, 0])
