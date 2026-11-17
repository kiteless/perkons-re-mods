# Off-grid

Play steps off the grid, early or late:

* **Record off the grid.** The trigger keys and MIDI notes record your hits where you played them, on the nearest step, early or late.
* **Edit off the grid.** Hold a step and turn **TEMPO** to move it early or late, in sixths of a step.

Off-grid replaces **UNQUANTIZED** (seq-unquantized), and its recording is based on that mod. It uses the same config key, and keeps UNQUANTIZED's setting.

> **Tested on hardware.** Recording and TEMPO editing passed the hardware test plan on a Pērkons. See [TESTING.md](TESTING.md). If it misbehaves, flash the official firmware to go back.

Based on official Pērkons firmware **1.3.0**. Unofficial, and not affiliated with Erica Synths.

## Getting it

Build Pērkons firmware with **OFF-GRID** ticked in the **Mod Matrix**, from your own official 1.3.0 firmware. Follow [Get modded firmware](https://github.com/kiteless/perkons-re#get-modded-firmware) in perkons-re. No firmware files are provided here. To remove it, flash the official firmware again.

## Turning it on

The two halves are switched on separately, so you can have either or both.

1. Hold **SHIFT** and press **MOD** to open the config menu.
2. Press **step 13 on the third row** for off-grid recording. LED on means recording goes off the grid. LED off (the default) means recording snaps to the grid, as on the factory firmware. If you used UNQUANTIZED, this key and its setting carry over.
3. Press **step 12 on the third row** for TEMPO editing. LED on means hold a step + TEMPO moves the step. LED off (the default) means TEMPO is always the tempo knob.
4. Leave the config menu as usual. The settings are saved on the SD card.

## Recording off the grid

Record as usual: press **REC** while the pattern plays, and tap the **trigger keys** or play notes into **MIDI in**.

* Each hit goes into the nearest step, as on the factory firmware, but at the moment you played it:
  * in the first part of a step (up to about halfway), into that step, late by how far into it you played;
  * after that, into the next step, early by how far before it you played.
* So a hit played a little ahead of the beat stays on its beat, early, rather than going on the step before.
* It plays back at that moment every time round. The hit you played has already sounded, so the step doesn't play again on the pass you recorded it.
* The timing is kept as a share of a step (24 positions per step, as fine as 96 PPQN), so it follows tempo changes, an external clock and each track's DIVIDE / MULTIPLY.
* A step holds one hit per track: a second hit on the same step replaces the first. A hit played before a late step's own hit comes goes in that step too, replacing it, so two hits never swap places.
* Next to a step that's already early, a hit played in the gap before it goes in that step, early.
* MIDI notes keep their velocity (with MIDI velocity on in the config menu) and, in multi channel mode, their note, as when recording on the grid.
* Steps you program with the step buttons stay on the grid until you move them with TEMPO.

## Editing off the grid with TEMPO

1. Program a step, then **hold** it. Empty steps don't take a timing: with an empty step held, TEMPO is the tempo knob as usual.
2. Turn **TEMPO**. The held step's row changes to the off-grid view:
   * the 5 steps on each side of the held step light dim (unaccented), marking the range;
   * the step's current position lights bright;
   * the rest of that row goes dark. The other rows and playback carry on as normal.
3. Nothing happens for the first **20°**. After that, each **10°** moves the step one sixth of a step (4 of its 24 ticks): clockwise is later, counter-clockwise is earlier. The limit is 5 sixths either way. Turning back into the first 20° returns the step to where it started. Turning past the end of the range doesn't count: turn back and the step moves again at once. So if TEMPO is at the end of its travel when you hold a step, turn it the other way first, then back.
4. Let go of the step. To see or change its timing later, hold it again and move TEMPO slightly.

A recorded hit's timing shows rounded to the nearest sixth. It keeps its exact timing until you turn TEMPO past the dead zone.

A step can't be moved onto or past the step played before or after it. If a neighbouring step is in the way, the range in the view is shorter on that side and the step stops one division short of it. This limit applies in the forward play mode only. In the other play modes, two steps moved onto each other play as one hit.

Turning a step off clears its timing. When you turn it on again it's back on the grid (or on the track's shuffle grid, if the track has shuffle).

An early first step plays at the end of the bar before it. So the first time round after you press **PLAY**, that step is silent: there is no bar before it yet.

While you hold a step, **the tempo doesn't change**. After you let go, TEMPO does nothing until you turn it back to near the current tempo (within 12 BPM). This is the same catch the firmware uses after the tempo page, so the tempo never jumps.

With two or more steps held, TEMPO works as on the factory firmware.

Like p-locks, the hold has to last longer than a tap (about a third of a second), otherwise releasing the step turns it off. Any real turn of TEMPO takes longer than that.

## How it's stored

The timing is kept in the step's own delay value, the one **SHUFFLE** sets. The firmware itself plays that value early (negative) or late (positive). So:

* it's saved with the pattern;
* clearing a track clears it;
* it should move with the steps when you rotate or copy (not yet tested on a unit);
* the official firmware plays it back the same way.

Setting a track's **SHUFFLE** again replaces that track's timing.

## Coming from UNQUANTIZED

* The config key (row 3, step 13) and its saved setting are the same.
* Patterns recorded with UNQUANTIZED play as before.
* New recordings differ in one way: a hit in the second half of a step now goes on the next step, early, instead of on this step, late. It plays at the same moment either way.
* In the Mod Matrix, tick **OFF-GRID** instead of UNQUANTIZED. The build tag in `INFO.TXT` shows `og` instead of `uq`.
