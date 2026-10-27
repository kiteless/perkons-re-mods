# Voice map (kiteless 0.1)

Run any of the Pērkons' four voice engines on any of its four voices: four sample
voices, two kicks and two snares, whatever you like. Choose the layout per bank with a
small text file on the SD card, the same way per-bank samples work in firmware 1.3.

Based on official Pērkons firmware **1.3.0**. Unofficial; not affiliated with Erica Synths.

## Install

Flash `perkons_v1.3.0-0-force.img` from the release folder like any official update:

1. Copy it to the root of the SD card (it should be the only `.img` file there).
2. Power off, hold all four voice trigger keys, power on. Release the keys when the first
   row of steps starts lighting.
3. Rows light 1 → 3 → 2 → 4, then the Pērkons boots.

To check it's installed, look at `INFO.TXT` on the SD card:

```
Current Controller   (CM4) version: 1.3.0 - kiteless0.1
Current Voice Engine (CM7) version: 1.3.0 - kiteless0.1
```

To uninstall, flash the official `perkons_v1.3.0-0-force.img` the same way.

## Choosing engines: `voices.json`

```json
{
  "voice1": "voice4",
  "voice2": "voice4",
  "voice3": "zibens",
  "voice4": "voice4"
}
```

Each key is a voice (track/output 1-4). Each value names the engine it should run:

| value | engine | ALGO 1 / 2 / 3 |
|---|---|---|
| `"voice1"` | stock voice 1's engine | Fold Drum 1 / Wavetable / Simple |
| `"voice2"` | stock voice 2's engine | Fold Drum 2 / Wavetable / Complex |
| `"voice3"` | stock voice 3's engine | Resonant drums / Slap / Karplus–Chord |
| `"voice4"` | stock voice 4's engine | Noise hat / Noise–tone / Acoustic hats (samples) |
| `"zibens"` | the [ZIBENS](../zibens/) synth voice (builds that include it) | scale: minor pentatonic / Dorian / Phrygian |

The ALGO and MODE switches, knobs, trigger input, output jack, filter and drive of each
voice work as usual; only the sound engine behind them changes.

* A voice you leave out, or give a name that isn't installed (e.g. `"zibens"` in a build
  without it), keeps its normal engine.
* Keys and names are lowercase and exact (`"voice1"`, not `"Voice1"`).

### Where to put it

| file | applies to |
|---|---|
| `BANKS/NN/voices.json` | bank NN only |
| `voices.json` in the card's root | every bank without its own file |
| neither | stock layout |

**Bank folders count from 00:** the first bank on the grid (row 1, step 1) is
`BANKS/00`, row 1 step 4 is `BANKS/03`, and the last bank (row 4, step 16) is `BANKS/63`.
A bank's own file replaces the root file entirely; they're not merged. **If a voice
won't change, look for a `voices.json` in the bank you're on**: it wins over the root one. To keep one bank
stock while the root file changes others, give it
`{"voice1": "voice1", "voice2": "voice2", "voice3": "voice3", "voice4": "voice4"}`.

The file is read every time a bank loads (at power-on and when you switch banks), so
after editing it on your computer, power-cycle or switch banks.

## Behaviour notes

* **Switching banks** changes engines instantly; a voice that was ringing is cut and the
  new engine is silent until its next trigger. Mute, ALGO and MODE stay as they were.
* **Sample voices** (engine 4, ALGO 3) all play the current bank's samples, the same
  three files as stock voice 4 (`BANKS/NN/SAMPLES/` or the root `SAMPLES/`). The
  *Sampler P2 config* setting applies to all of them.
* Each voice's sound is identical to that engine on its home voice. Noise engines draw
  from one shared random source, so two noise voices never produce the exact same noise
  (as on stock firmware).
* Kits store knob positions per voice, so loading a kit made for a kick onto a voice now
  running the hats engine gives the hats engine those knob positions.

## Known limits (0.1)

* The layout comes from the SD card only; there's no way to change it from the panel yet.
* All sample voices share one set of samples.

## Version history

* **unreleased**: engines are chosen by name (`"voice1"`-`"voice4"`, replacing the numbers
  1-4); other mods can add engines, the first being `"zibens"`.
* **0.1**: first release. Per-voice engine choice from `voices.json`, per bank or global.
