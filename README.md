# perkons-mods (local only)

Out-of-tree mods for the [perkons-re](../perkons) framework. **Not pushed anywhere.**

Use from the framework checkout, with `PERKONS_MODS = ../perkons-mods` in its untracked
`local.mk`:

```sh
cd ../perkons
make test                                          # framework + these mods' tests
make build PATCHES=voice_map:bank                  # -> builds/voice_map-bank.img
make build PATCHES=voice_map_fixed:4444            # fixed layout, M7 only
```

| mod | what |
|---|---|
| [voice-map](voice-map/) | any output can run any of the four stock voice engines; layout from `voices.json` (root or per bank). See `voice-map/docs/`. |
