# Pattern BPM

Each pattern keeps the tempo it was saved at, and plays at it.

Based on official Pērkons firmware **1.3.0**. Unofficial; not affiliated with Erica Synths.

## Getting it

Build Pērkons firmware with **PER PATTERN BPM** ticked in the **Mod Matrix**, from your own
official firmware 1.3.0: follow [Get modded firmware](https://github.com/kiteless/perkons-re#get-modded-firmware)
in perkons-re. No firmware files are provided here. To remove it, flash the official
firmware again.

## Turning it on

1. Hold **SHIFT** and press **MOD** to open the config menu.
2. Press **step 14 on the third row** of step buttons. Its LED on = pattern BPM on.
3. Leave the config menu as usual; the choice is saved on the SD card.

## Using it

* **Saving a pattern** (PATTERN page: REC + step) also saves the current tempo with it.
* **When a pattern starts playing** (queued, in a chain, chosen on the PATTERN page, or
  when a bank loads), it sets the tempo it was saved with. The TEMPO knob then takes over
  once you turn it close to that tempo, as after the tempo page or tap tempo.
* Patterns saved before you turned it on, or while it was off, keep whatever tempo is
  playing. Clearing a pattern forgets its tempo.
* With an external clock (MIDI or analog), patterns follow the clock as usual.
* While it's off, nothing is saved and the tempo works as on the factory firmware.

The tempos are kept in `BANKS/NN/PP.PAX` beside the stock pattern files, which stay
unchanged; official firmware ignores it.
