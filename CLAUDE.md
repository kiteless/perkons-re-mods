# perkons-re-mods: notes for Claude Code

Firmware mods for the Erica Synths Pērkons HD-01, built with the framework in the sibling
repo `../perkons` (GitHub `kiteless/perkons-re`). **Read `../perkons/CLAUDE.md` first**
(the owner's rules: ask before installing, no Claude attribution in commits, commit/push
only when asked, never commit Erica content, repos public), and
`../perkons/docs/writing-mods.md` for how to make a new mod.

Run everything from the framework folder (`cd ../perkons`): `make test`, `make build
PATCHES=...`, `make ui`.

## Mods

| mod | core | config |
|---|---|---|
| `voice-map` | M7 (M7 host) + M4 (M4 host) | `voices.json` (SD root, `BANKS/NN/`) |
| `fx-reverb` | M4 (M4 host) | row 3 step 15 (key 46), `"fx-reverb"` |
| `fx-freeze` | M4 (M4 host) | row 3 step 16 (key 47), `"fx-switch-freeze"` |
| `voice-slinks` | M7, a voice-map engine (requires voice-map) | `"slinks"` in `voices.json` |
| `eight-lanes` (8 TRACKS) | M4 (M4 host); takes almost all of STORE (to reduce after 0.2) | `"lane5-midi-channel"`.., `"lane5-trig-note"`.. in `system/mods.json`; lanes in the host's `PP.PAX` / `KITS/PP.KIX` (record `EL8P` / `EL8K`; older `.PA2` / `.KI2` still read) |
| `per-track-lfo` (PER TRACK LFO) | M4 (M4 host) | none (trigger key + LFO knobs) |

Next release in mind: `kiteless 0.2` (voice-map + fx-reverb + fx-freeze + voice-slinks) in
`releases/`.

## Conventions

* One folder per mod: `mod.json`, `patches/`, `src/<core>/`, `lib/`, `tests/`, and a
  user-facing `README.md`. Design notes and RE findings go in the private
  `../perkons-re-docs/mods/<mod>/`, never in this public repo.
* `mod.json` codes taken: `vm`, `rv`, `fz`, `sl`, `et`, `lf`. Config keys taken: 46, 47.
  Sidecar record tags taken: `EL8P`, `EL8K`. M7 config messages: `voice-map`. Extra
  voice-map engines register by name (`p.shared['voice_map']['engines']['slinks']`) and
  are numbered by voice-map (from 5, in name order); voices.json selects them by name.
* M4 mods register with the framework's M4 host, M7 mods with the M7 host. Hooks chain:
  continue with `PK_NEXT(hook)` (never call the stock function directly for the call you
  hook), and they only run once the host has booted. FX mods meet through the M4 host's
  weak hooks.
* A mod's hook sites go in its `symbols/<ver>-<core>.json` (`sites` only, named
  `<mod>.<hook>.<addr>`); firmware functions, globals and sites any mod could use go in
  the framework's symbols. `make test-fast` checks every mod registers with the others.
* No RAM allocation decisions without asking the owner.
* Docs, READMEs, mod.json and commit messages never say how or whether something was
  tested (no test status, hardware logs, "verified" notes): pushed means tested.
