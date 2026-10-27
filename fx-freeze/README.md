# FX freeze

The FX section's SHORT / LONG switch as a **freeze** switch. On the factory delay it loops
the last repeat; with [FX reverb](../fx-reverb/) it holds the reverb tail.

Based on official Pērkons firmware **1.3.0**. Unofficial; not affiliated with Erica Synths.

## Getting it

Build Pērkons firmware with **FX FREEZE** ticked in the **Mod Matrix**, from your own
official firmware 1.3.0: follow [Get modded firmware](https://github.com/kiteless/perkons-re#get-modded-firmware)
in perkons-re. No firmware files are provided here. It works on its own or together with
FX reverb. To remove it, flash the official firmware again.

## Turning it on

1. Hold **SHIFT** and press **MOD** to open the config menu.
2. Press **step 16 on the third row** of step buttons. Its LED on = the switch is freeze,
   off = SHORT / LONG as usual.
3. Leave the config menu as usual; the choice is saved on the SD card.

## Using it

| switch | delay | reverb (with FX reverb) |
|---|---|---|
| SHORT | the delay plays (as SHORT) | the reverb plays |
| **LONG** | **freeze**: the last delay repeat loops, new sound is kept out | **freeze**: the tail holds, new sound is kept out |

* Flip back to SHORT to release: the delay picks up again, and the reverb tail decays at
  the FEEDBACK setting.
* While freeze is on in the config, the switch doesn't choose SHORT / LONG delay any
  more: the delay stays on SHORT, and the reverb on its hall size.
* The voices themselves keep playing dry while the effect is frozen.
* If the Pērkons is switched on with the switch at LONG, it starts frozen (on silence).
