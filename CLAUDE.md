# perkons-re-mods: notes for Claude Code

Firmware mods for the Erica Synths Pērkons HD-01, built with the framework in the sibling
repo `../perkons` (GitHub `kiteless/perkons-re`). **Read `../perkons/CLAUDE.md` first**
(the owner's rules: ask before installing, no Claude attribution in commits, commit/push
only when asked, never commit Erica content, repos private), and
`../perkons/docs/writing-mods.md` for how to make a new mod.

Run everything from the framework folder (`cd ../perkons`): `make test`, `make build
PATCHES=...`, `make ui`.

## Mods

| mod | core | config |
|---|---|---|
| `voice-map` | M7 + M4 | `voices.json` (SD root, `BANKS/NN/`) |
| `fx-reverb` | M4 (M4 host) | row 3 step 15 (key 46), `"fx-reverb"` |
| `fx-freeze` | M4 (M4 host) | row 3 step 16 (key 47), `"fx-switch-freeze"` |
| `zibens` | M7, a voice-map engine (requires voice-map) | `"zibens"` in `voices.json` |
| `eight-lanes` (8 TRACKS) | M4 (M4 host); takes almost all of STORE | `"lane5-midi-channel"`.., `"lane5-trig-note"`.. in `system/mods.json` |

Next release in mind: `kiteless 0.2` (voice-map + fx-reverb + fx-freeze + zibens) in
`releases/`.

## Conventions

* One folder per mod: `mod.json`, `patches/`, `src/<core>/`, `lib/`, `tests/`, `docs/`
  (`design.md`), and a user-facing `README.md`.
* `mod.json` codes taken: `vm`, `rv`, `fz`, `zb`, `et`. Config keys taken: 46, 47. voice-map engine
  numbers taken: 1-4 stock, 5 zibens; voices.json selects engines by name (extra engines
  register a number and a `name` in `p.shared['voice_map']`).
* M4 mods register with the framework's M4 host; FX mods meet through its weak hooks.
* Docs, READMEs, mod.json and commit messages never say how or whether something was
  tested (no test status, hardware logs, "verified" notes): pushed means tested.
