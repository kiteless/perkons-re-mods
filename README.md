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

| mod | what | status |
|---|---|---|
| [voice-map](voice-map/) | any voice can run any of the four voice engines; layout per bank from `voices.json` | 0.1, hardware-tested on 1.3.0 |
| [fx-reverb](fx-reverb/) | reverb instead of the BBD delay (config switch) | emulator-tested, hardware next |
| [fx-freeze](fx-freeze/) | 2-way FX switch as freeze: delay looper, reverb hold with fx-reverb | emulator-tested, hardware next |

The FX mods build alone or together (the framework's M4 host joins them).

## Use

Clone next to `perkons-re` and point the framework at this repo (in `perkons-re/local.mk`):

```make
PERKONS_MODS = ../perkons-re-mods
```

```sh
cd ../perkons-re
make test                                              # framework + mod tests
make build PATCHES=voice_map:bank                      # one-off build
make ui                                                # Mod Matrix: pick mods, build in the browser
make release REL=../perkons-re-mods/releases/kiteless-0.1.json   # versioned release
```

A mod folder has `patches/` (patch modules), `src/<core>/` (C), `lib/` (Python helpers),
`tests/`, `docs/` and `mod.json` (what the framework's Mod Matrix, `make ui`, offers);
`releases/` holds release definitions. See the framework's README
and `docs/porting.md` for moving mods to a new official firmware.

## License

MIT, see [LICENSE](LICENSE). Covers the code and documentation in this repository only.
