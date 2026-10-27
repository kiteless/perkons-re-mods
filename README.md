# perkons-re-mods

Firmware mods for the **Erica Synths Pērkons HD-01**, built with the
[perkons-re](https://github.com/kiteless/perkons-re) framework. One folder per mod.

> Unofficial. Not affiliated with or endorsed by Erica Synths. "Pērkons" is used only to
> say what these mods are for. Flashing modified firmware is at your own risk; reflash
> official firmware before any warranty service.
>
> **This repository contains no Erica Synths firmware, binaries, manuals or samples.**
> Mods are source code and patch definitions that are applied to the official firmware
> you download yourself from Erica Synths. Built images are never committed.

## Getting the mods onto your Pērkons

No firmware files are provided here. You build your own firmware, with the mods you
choose, from the official Erica Synths update, using the **Mod Matrix** app in the
[perkons-re](https://github.com/kiteless/perkons-re) project. It runs in your browser,
on your computer.

**Step-by-step guide: [Get modded firmware](https://github.com/kiteless/perkons-re#get-modded-firmware)**
(install three programs, run one command, tick the mods, flash the result).

## The mods

| mod | what it does | how to use it |
|---|---|---|
| **voice-map** | any of the four voices can run any of the four voice engines (or ZIBENS), chosen per bank | [voice-map/README.md](voice-map/README.md) |
| **ZIBENS** | a new synth voice: scale-locked resonant saw, PWM square, wavefolded sine (needs voice-map) | [zibens/README.md](zibens/README.md) |
| **FX reverb** | a reverb in place of the BBD delay, switched in the config menu | [fx-reverb/README.md](fx-reverb/README.md) |
| **FX freeze** | the FX section's 2-way switch as freeze: loops the delay, or holds the reverb | [fx-freeze/README.md](fx-freeze/README.md) |

All of them are for Pērkons firmware **1.3.0**, and any combination can be built together.

## For developers

Clone this repo next to `perkons-re`; the framework finds it (or set `PERKONS_MODS`, e.g.
`PERKONS_MODS = ../perkons-re-mods` in `perkons-re/local.mk`). Then, in `perkons-re`:

```sh
make test                                   # framework + mod tests
make build PATCHES='voice_map:bank zibens'  # a firmware file in builds/
make ui                                     # the Mod Matrix
```

A mod folder has `README.md` (for users), `mod.json` (what the Mod Matrix offers),
`patches/` (patch modules), `src/<core>/` (C), `lib/`, `tests/` and `docs/`.
`releases/` holds release definitions for `make release`, which builds a versioned
firmware file locally. Making a new mod: perkons-re's
[docs/writing-mods.md](https://github.com/kiteless/perkons-re/blob/main/docs/writing-mods.md).

## License

MIT, see [LICENSE](LICENSE). Covers the code and documentation in this repository only.
