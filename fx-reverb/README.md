# FX reverb

A reverb in place of the Pērkons's BBD delay. Switch between them in the config menu; the
delay is untouched when the reverb is off.

Based on official Pērkons firmware **1.3.0**. Unofficial; not affiliated with Erica Synths.
The reverb is a port of the Mutable Instruments Rings / Elements reverb (MIT licence).

## Getting it

Build Pērkons firmware with **FX REVERB** ticked in the **Mod Matrix**, from your own
official firmware 1.3.0: follow [Get modded firmware](https://github.com/kiteless/perkons-re#get-modded-firmware)
in perkons-re. No firmware files are provided here. To remove it, flash the official
firmware again.

## Turning it on

1. Hold **SHIFT** and press **MOD** to open the config menu.
2. Press **step 15 on the third row** of step buttons. Its LED on = reverb, off = the
   factory delay.
3. Leave the config menu as usual; the choice is saved on the SD card.

Switching is silent (a few milliseconds of quiet while the effect's memory is cleared),
and switching back to the delay brings no old echoes with it.

## Controls in reverb mode

| control | reverb |
|---|---|
| TIME | pre-delay, 0 to ~170 ms; with *BBD sync* on, tempo divisions |
| FEEDBACK | decay: short room ambience to a very long tail (fully right is long, not infinite) |
| LFO RATE | diffusion: grainy, distinct reflections ↔ smooth wash |
| MOD DEPTH | motion in the tail; the LFO LED shows it |
| SHORT / LONG switch | room / hall (or freeze, with [FX freeze](../fx-freeze/)) |
| BRIGHT / MID / DARK switch | tone of the wet signal, as for the delay (it's analog) |
| FX SEND (per voice), master send / return | as for the delay |

The reverb filters out the lowest frequencies (below ~120 Hz) at its input, so kicks and
basses don't muddy the tail. Like the delay, it's mono, heard on the main output only
(individual voice outputs stay dry), and only the wet signal comes back.

## Kits and MIDI

With *kit FX* saving on, kits store the FX knob positions as usual, and the reverb uses
them. Pot catch and the FX MIDI CCs work as for the delay.
