# Eight tracks

Four more sequencer tracks for the Pērkons, 5–8, on a second page of the step grid. They
have no sound of their own: they send MIDI notes, to drive other gear from the same
patterns as the four voices.

Based on official Pērkons firmware **1.3.0**. Unofficial; not affiliated with Erica Synths.

## Getting it

Build Pērkons firmware with **8 TRACKS** ticked in the **Mod Matrix**, from your own
official firmware 1.3.0: follow [Get modded firmware](https://github.com/kiteless/perkons-re#get-modded-firmware)
in perkons-re. No firmware files are provided here. To remove it, flash the official
firmware again (see [Files](#files) for what stays on the card).

## The second page

Hold **SHIFT** and press **PATTERN** to flip the step grid between tracks 1–4 (page A)
and tracks 5–8 (page B). Do it again to flip back. While page B is shown, the PATTERN
LED is dim. The unit always starts on page A, and changing patterns keeps the page you're
on.

It only flips on a clean press: if you pressed another key since SHIFT went down,
SHIFT + PATTERN does what it always did.

On page B, everything that works per track on page A works on tracks 5–8, in the same
places: steps, ties, LAST and the other SHIFT settings, play modes and speeds,
probability and ratchets, micro-timing, parameter locks, the MOD page, note repeat,
mutes (SHIFT + trigger key, or as set by *trig mute*), live recording and step entry.
The trigger keys play tracks 5–8 live.

The knobs and switches split with the page:

| on page B, these control tracks 5–8 | these always stay with voices 1–4 |
|---|---|
| TUNE, DECAY, PARAM1, PARAM2, the two 3-way switches | CUTOFF, DRIVE, FX SEND, LEVEL, the filter switch |

## What tracks 5–8 send

**Note.** In multi-channel mode a step plays its note, moved by TUNE and the switches:

* **TUNE** shifts the note in semitones around its centre position. The **top switch**
  sets how far: middle ±2 octaves, up ±1 octave, down ±4 octaves.
* The **bottom switch** sets the octave: middle as is, up +1, down −1.

Both are worked out as each note plays, so locks and knob moves on TUNE and the switches
change the pitch the way they change a voice's.

**Length.** DECAY sets how long each note is held (stock MIDI notes are very short):
fully left a short blip, centre one step, then up to eight steps, and fully right the
note is held until the next one (a tie). Tie steps hold the note as on the voices.

**Velocity** is the step's, as for the voices, and *MIDI velocity* applies.

**CCs.** In multi-channel mode, moving a knob or switch for a track on page B sends the
CC that row sends for a voice, on the track's channel (with *MIDI CC out* on).

*MIDI seq out* off means tracks 5–8 send nothing, and muted tracks are silent.

## MIDI channels

**Use multi-channel mode** (config: SHIFT + MOD, then row 3 step 2). Each of tracks 5–8
then sends on its own channel, 5–8 unless you change them:

1. Open the config page (SHIFT + MOD) and press **row 1, step 15** (multi MIDI channel
   config).
2. As in stock, each row of steps is a track and the step you press is its channel.
3. **Hold SHIFT** and the four rows show tracks 5–8 instead of 1–4. Release it to see
   tracks 1–4 again.
4. Leave the page as usual; the channels are saved.

In **single-channel mode** all eight tracks share the one channel, and each of tracks 5–8
sends a fixed trigger note instead, 40–43 by default (after voices 1–4's 36–39). TUNE and
the switches don't change them there, as on the voices, and there are no CCs for tracks
5–8. Stock has no editor for trigger notes on the unit, and neither does this: change them
in `system/mods.json` on the card (`lane5-trig-note` … `lane8-trig-note`, 0–127). The
channels are there too (`lane5-midi-channel` … `lane8-midi-channel`, 0–15 for channels
1–16).

## MIDI in

As for the voices: in multi-channel mode a note on a track's channel plays that track
(and records it while recording, or enters it in step entry); in single-channel mode its
trigger note does. CCs on a track's channel record into its parameter locks, with its
row's CC numbers.

## Patterns and kits

Tracks 5–8 are part of every pattern and follow the same rules as tracks 1–4: saved with
the pattern, edits you didn't save are dropped when you leave the pattern, CLEAR clears
them, and every bank has its own. Their knob and switch values are saved with kits too,
including kit link.

## Files

Your stock files are never changed. Tracks 5–8 go in files beside them on the card:

| file | holds |
|---|---|
| `BANKS/NN/PP.PA2` | tracks 5–8 of pattern PP (beside the stock `PP.PAT`) |
| `BANKS/NN/KITS/PP.KI2` | tracks 5–8's values in kit PP (beside the stock `PP.KIT`) |
| `system/mods.json` | tracks 5–8's channels and trigger notes |

Official firmware ignores these files, so going back to it leaves your patterns and kits
as they were; flash this mod again and tracks 5–8 are back.

## Limits

* Note repeat on tracks 5–8 starts when you press the key; on voices 1–4 it lines up with
  the clock.
* It uses almost all of the free AXI SRAM (STORE in the Mod Matrix's memory meters), for
  four more tracks in all 64 patterns.

Design and firmware notes: [docs/design.md](docs/design.md).
