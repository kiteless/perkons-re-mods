# perkons-re-mods: notes for Claude Code

Firmware mods for the Erica Synths Pērkons HD-01, built with the framework in the sibling
repo `../perkons` (GitHub `kiteless/perkons-re`). **Read `../perkons/CLAUDE.md` first**
(the owner's rules: ask before installing, no Claude attribution in commits, commit/push
only when asked, never commit Erica content, repos private), and
`../perkons/docs/writing-mods.md` for how to make a new mod.

Run everything from the framework folder (`cd ../perkons`): `make test`, `make build
PATCHES=...`, `make ui`.

## Mods

| mod | core | config | status | open |
|---|---|---|---|---|
| `voice-map` | M7 + M4 | `voices.json` (SD root, `BANKS/NN/`) | hardware-tested (F1 fixed map, F3 per bank, 3333 physical modelling) | sample overlap, bank switch while busy, P2 toggle, quantize/MIDI not yet confirmed; kiteless 0.1 `INFO.TXT` stamp not verified on hardware |
| `fx-reverb` | M4 (M4 host) | row 3 step 15 (key 46), `"fx-reverb"` | emulator-tested; renders approved by ear | hardware test |
| `fx-freeze` | M4 (M4 host) | row 3 step 16 (key 47), `"fx-switch-freeze"` | emulator-tested | hardware test |
| `zibens` | M7, a voice-map engine (requires voice-map) | `voices.json` value 5 | in development (design agreed 2026-10-25, see `zibens/docs/design.md`) | listening/tuning, then hardware |

Next steps the owner has in mind: hardware-test `make build PATCHES='fx_reverb
fx_freeze'` (check: delay↔reverb switch silent with no old tail, delay looper and
reverb hold at LONG, power-on at LONG starts frozen, LFO LED follows MOD DEPTH in reverb
mode, settings survive a power cycle), then a release `kiteless 0.2` (voice-map +
fx-reverb + fx-freeze) in `releases/`.

## Conventions

* One folder per mod: `mod.json`, `patches/`, `src/<core>/`, `lib/`, `tests/`, `docs/`
  (`design.md`, `hardware-log.md` once flashed).
* `mod.json` codes taken: `vm`, `rv`, `fz`, `zb`. Config keys taken: 46, 47. voice-map engine
  numbers taken: 1-4 stock, 5 zibens (extra engines register in `p.shared['voice_map']`).
* M4 mods register with the framework's M4 host; FX mods meet through its weak hooks.
* Update the README table and `mod.json` `status` when a mod's test state changes.
