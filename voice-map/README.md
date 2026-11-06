# Voice map

Run any of the Pērkons' four voice engines on any of its four voices (four sample
voices, two kicks and two snares, whatever you like), plus engines other mods add, such
as the [voice-zibens](../voice-zibens/) and [voice-akords](../voice-akords/) synth voices. Choose the layout per
kit, on the unit.

Based on official Pērkons firmware **1.3.0**. Unofficial; not affiliated with Erica Synths.

## Getting it

Build Pērkons firmware with **VOICE MAP** ticked in the **Mod Matrix**, from your own official
firmware 1.3.0: follow [Get modded firmware](https://github.com/kiteless/perkons-re#get-modded-firmware)
in perkons-re. No firmware files are provided here. To remove it, flash the official
firmware again.

## Choosing engines: the engine page

Each **kit** remembers which engine each of its four voices runs.

1. Hold **KIT** and press **MOD** (from any page, like PATTERN + KIT for the bank menu).
   The engine page opens.
2. **Rows 1–4 are voices 1–4; the columns are the engines.** The bright LED in each row is
   that voice's engine; the dim LEDs are the engines you can choose.
3. Press a step to choose. Press the voice's trigger key to hear it: the next note plays
   the new engine.
4. Leave with a page button (KIT, MOD, PATTERN, SHIFT). A changed choice is kept with
   the current kit and saved to the card.

| column | engine | ALGO 1 / 2 / 3 |
|---|---|---|
| 1 | stock voice 1's engine | Fold Drum 1 / Wavetable / Simple |
| 2 | stock voice 2's engine | Fold Drum 2 / Wavetable / Complex |
| 3 | stock voice 3's engine | Resonant drums / Slap / Karplus–Chord |
| 4 | stock voice 4's engine | Noise hat / Noise–tone / Acoustic hats (samples) |
| 5 | the [voice-zibens](../voice-zibens/) synth voice (builds that include it) | scale: minor pentatonic / Dorian / Phrygian |

Engines from other mods take the next columns. The ALGO and MODE switches, knobs, trigger
input, output jack, filter and drive of each voice work as usual; only the sound engine
behind them changes.

**Engine settings**: an engine with settings of its own (such as
[voice-akords](../voice-akords/)) opens its settings page for a voice when you **hold
that voice's step** of the engine for half a second (holding a dim step chooses the
engine and opens it). The engine's README describes its page.

* A kit you haven't changed plays the stock engines: voice 1 on engine 1, and so on.
* **Saving a kit** (KIT page: REC + step) saves its engines with it; **loading a kit**
  (including kit-link on a pattern change, and bank loads) brings them back.
* The engines are kept in `BANKS/NN/KITS/PP.KIX` beside the stock kit file, which stays
  unchanged; official firmware ignores it.

## Behaviour notes

* **A voice changes engine at its next note**, so a ringing sound is never cut: the new
  engine takes over when the voice plays again. Mute, ALGO and MODE stay as they were.
* **Sample voices** (engine 4, ALGO 3) all play the current bank's samples, the same
  three files as stock voice 4 (`BANKS/NN/SAMPLES/` or the root `SAMPLES/`). The
  *Sampler P2 config* setting applies to all of them.
* Each voice's sound is identical to that engine on its home voice. Noise engines draw
  from one shared random source, so two noise voices never produce the exact same noise
  (as on stock firmware).
* Kits store knob positions per voice, so loading a kit made for a kick onto a voice now
  running the hats engine gives the hats engine those knob positions.

## Limits

* All sample voices share one set of samples.
