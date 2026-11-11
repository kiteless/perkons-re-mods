# voice-step-sampler

**STEP SAMPLER**: a sample voice for the Pērkons. Up to 64 samples per bank, of any length,
streamed from the SD card, and each step can play its own. With the top switch on attack
and the bottom on forward it plays like the stock sampler (voice 4, ALGO 3); the other
positions add start points, slices (chopping on the WAV's cue points), choke and reverse. It runs on any of the
four voices.

Based on official Pērkons firmware **1.3.0**. Unofficial; not affiliated with Erica Synths.

## Getting it

Build Pērkons firmware with the **Mod Matrix**, from your own official firmware 1.3.0:
follow [Get modded firmware](https://github.com/kiteless/perkons-re#get-modded-firmware)
in perkons-re. No firmware files are provided here. To remove it, flash the official
firmware again.

voice-step-sampler runs as a [voice map](https://github.com/kiteless/perkons-re/blob/main/docs/voice-map.md) engine: in the Mod Matrix, on the
**ENGINES** tab, install STEP SAMPLER. It takes the slot you
install it in: its place in TO BE INSTALLED, from slot 5.

## Putting it on a voice

On the voice-map engine page (KIT + MOD), press STEP SAMPLER's column (its slot) in the
voice's row; its next note plays STEP SAMPLER. The choice is kept with the kit: see
[the voice map](https://github.com/kiteless/perkons-re/blob/main/docs/voice-map.md). The voice's knobs, switches, trigger key and input, output
jack, and the analog filter, drive, FX send and level all stay with the voice; only the
sound engine changes.

## Samples on the card

For each bank, sample *n* (1 to 64) is:

1. `BANKS/NN/SAMPLES/n.wav`, if the bank has it (bank 1 is `BANKS/00`)
2. otherwise `SAMPLES/n.wav` in the card's root
3. otherwise slot *n* is empty (silent, and unlit on the sample page)

So a bank can replace just a few of the card's samples with its own. The files are read
each time a bank loads.

* **Format:** WAV, **mono, 16-bit**, at any sample rate (each plays at its own rate, so it
  stays in tune). Other files (stereo, 24-bit, ...) count as empty slots.
* **Length:** anything; samples stream from the card as they play.
* **Cue points** in the WAV (most audio editors can add markers that save as cue points)
  mark slices for the slice setting.
* The files the stock sampler uses (`1.wav` to `3.wav`) are samples 1 to 3.

While STEP SAMPLER is installed, the stock sampler (voice 4, ALGO 3) plays its factory
closed hat, open hat and ride: STEP SAMPLER uses the memory that held your three custom
samples. Without STEP SAMPLER in the build, the stock sampler plays them again.

## Choosing samples: the sample page

On the main page, **hold one or more steps** of a STEP SAMPLER track and press **SHUFFLE**.
The 64 step buttons are now samples 1 to 64 (in rows of 16): a loaded sample is dimly lit,
the held steps' sample brightly. You can let go of the steps.

* **Press a step button** to choose that sample: every step you held plays it, and it
  becomes the track's sample. It plays as you choose it, on the track's voice.
* **SHUFFLE** closes the page when you press it again. If you hold SHUFFLE (longer than
  about half a second), the page closes when you let go, as the stock page buttons do.
  The other page buttons go to their pages; the trigger keys play the voices as usual.
* On tracks running other engines, step + SHUFFLE opens the shuffle page as always.

**The track's sample** is what a step without its own sample plays, and what the
trigger key (and MIDI) plays: the last sample chosen on that track, sample 1 until you
choose one. It's kept with the kit. **A step's own sample** is kept with the pattern.

* **CLEAR** with a step (as for clearing its parameter locks) also clears its sample: it
  plays the track's sample again.
* **Copying and pasting steps** (REC with a step held, then SHIFT with steps held) carries
  the step's sample.

## Controls

| control | what it does |
|---|---|
| **TUNE** | pitch: 12 o'clock is the sample's own speed, an octave per eighth of the knob; MIDI notes transpose it |
| **DECAY** | how long a hit rings, the same range as the stock voices; fully right holds |
| **PARAM1** | **grit**: fully left is clean; up to 12 o'clock it moves towards the 12-bit, ~26 kHz sound of old drum samplers; past 12 o'clock it carries on to heavy bit and rate reduction (~6-bit, ~2 kHz) |
| **PARAM2** | set by the top switch: attack, start point or slice |
| **ALGO** (top switch) | what PARAM2 does (below) |
| **MODE** (bottom switch) | forward / choke / reverse (below) |
| velocity | the level, as on every voice |
| CUTOFF, filter switch, DRIVE, FX SEND, LEVEL | the Pērkons's analog stages, exactly as on every voice |

Switch positions are numbered as in the Pērkons manual's voice tables (positions 1, 2, 3).

### ALGO: what PARAM2 does

| ALGO | PARAM2 | each hit plays |
|---|---|---|
| position 1: **attack** | how quickly each hit fades in, from instant to about 2 s | the sample from its beginning (the stock sampler, sample start off) |
| position 2: **start** | where in the sample each hit begins: fully left is the beginning | from there to the end (the stock sampler, sample start on) |
| position 3: **slice** | which slice: the WAV's cue points (up to 16), or 16 equal slices if it has none | from that slice on |

PARAM2 is read at each hit, so lock it on steps (hold a step, turn PARAM2), or record its
moves, for a different start or slice per step: a break played in a new order.

### MODE: how it plays

| MODE | each hit |
|---|---|
| position 1: **forward** | plays forwards to the end of the sample (the stock sampler) |
| position 2: **choke** | plays forwards and stops at the next cue point (or the next of the 16 equal slices): just that chop, then silence until the next hit |
| position 3: **reverse** | plays the same stretch backwards, from its end: the slice, or from the end of the sample back to the start point |

Forward and reverse go round again if a hit is still sounding (DECAY long enough) when it
reaches the end of its stretch; choke doesn't. A new hit on the voice always cuts the one
before.

## Streaming, in practice

STEP SAMPLER keeps the first ~50 ms of every sample in memory and reads the rest from the
card as it plays, a little ahead. For a start point, slice or reverse it
reads that part ahead of the step that plays it. A hit whose place isn't ready yet (for
example a trigger key pressed just after turning PARAM2, or just after choosing a new
sample) plays from the sample's beginning instead.

Switching banks takes a little longer than without STEP SAMPLER (it reads the start of up
to 64 files), and any sample playing stops, as the stock sampler's does.

## MIDI and the sequencer

STEP SAMPLER follows MIDI as the stock voices do: note 36 (what the trigger keys and pads
send) plays at TUNE's pitch, each note above or below a semitone higher or lower. In
multi-channel mode a keyboard on the voice's channel plays the track's sample chromatically.
