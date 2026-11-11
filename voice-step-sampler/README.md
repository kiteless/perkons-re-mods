# voice-step-sampler

**STEP SAMPLER**: a sample voice for the Pērkons. Up to 64 samples per bank, of any length,
streamed from the SD card, and each step can play its own. With the top switch on attack
and the bottom on forward it plays like the stock sampler (voice 4, ALGO 3); the other
positions add start points, slices (chopping on the .WAV's cue points), choke and reverse.

Based on official Pērkons firmware **1.3.0**. Unofficial; not affiliated with Erica Synths.

## Getting it

Build Pērkons firmware with the **Mod Matrix**, from your own official firmware 1.3.0:
follow [Get modded firmware](https://github.com/kiteless/perkons-re#get-modded-firmware)
in perkons-re. No firmware files are provided here. To remove it, flash the official
firmware again.

## Putting it on a voice

On the voice-map engine page (KIT + MOD), press STEP SAMPLER's column (its slot) in the
voice's row to change to this engine. Selected engines are saved with kits, see
[the voice map](https://github.com/kiteless/perkons-re/blob/main/docs/voice-map.md).

## Samples on the card

For each bank, sample *n* (1 to 64) is:

1. `BANKS/NN/SAMPLES/n.wav`, if the bank has it (bank 1 is `BANKS/00`)
2. otherwise `SAMPLES/n.wav` in the card's root
3. otherwise slot *n* is empty (silent, and unlit on the sample page)

So a bank can replace just a few of the card's samples with its own. The files are read
each time a bank loads. Bank loading will take a bit longer with big samples!

* **Format:** WAV, **mono, 16-bit**, at any sample rate. This is similar to the stock sampler voice, except sample rates other than 48k will play their original pitch.  Other files (stereo, 24-bit, ...) will be ignored and show up as empty slots.
* **Length:** any length supported; samples stream from the card as they play.
* **Cue points** in the WAV (most audio editors can add markers that save as cue points)
  mark slices for the slice setting (PARAM 2 with switch 1 in 3rd position)

While STEP SAMPLER is installed, the stock sampler (voice 4, ALGO 3) plays its factory
closed hat, open hat and ride.

## Choosing samples

On the main page, **hold one or more steps** of a STEP SAMPLER track and press **SHUFFLE**.
The 64 step buttons are now samples 1 to 64 (in rows of 16): available samples are dimly lit,
selected sample is highlighted.

* **Press a step button** to choose that sample: every step you held plays it, and it
  becomes the sample for future programmed steps. You can audition with the triggers.
* **SHUFFLE** closes the page when you press it again.

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
| **DECAY** | how long a hit rings, the same range as the stock voices |
| **PARAM1** | grit: fully left is clean; up to 12 o'clock is 12 bit-ish; past 12 o'clock it carries on to heavy bit and rate reduction (~6-bit, ~2 kHz) |
| **PARAM2** | set by the top switch: attack, start point or slice |
| **ALGO** (top switch) | what PARAM2 does (see below) |
| **MODE** (bottom switch) | forward / choke / reverse (see below) |
| velocity | the level, as on every voice |
| CUTOFF, filter switch, DRIVE, FX SEND, LEVEL | the Pērkons's analog stages, exactly as on every voice |

### ALGO: what PARAM2 does

| ALGO | PARAM2 | each hit plays |
|---|---|---|
| position 1: **attack** | how quickly each hit fades in, from instant to about 2s | This is stock voice 4 behavior
| position 2: **start** | where in the sample each hit begins: fully left is the beginning | from there to the end. Stock behavior with 'sample start' config on |
| position 3: **slice** | which slice: the WAV's cue points (up to 16), or 16 equal slices if it has none | from that slice on |

### MODE: how it plays

| MODE | each hit |
|---|---|
| position 1: **forward** | plays forwards to the end of the sample (like the stock sampler) |
| position 2: **choke** | plays forwards and stops at the next cue point (or the next of the 16 equal slices): just that chop, then silence until the next hit |
| position 3: **reverse** | plays the same stretch backwards, from its end: the slice, or from the end of the sample back to the start point |

Forward and reverse go round again if a hit is still sounding (DECAY long enough) when it
reaches the end of its stretch; choke doesn't. A new hit on the voice always cuts the one
before.

## MIDI and the sequencer

STEP SAMPLER follows MIDI as the stock voices do: note 36 (what the trigger keys and pads
send) plays at TUNE's pitch, each note above or below a semitone higher or lower. In
multi-channel mode a keyboard on the voice's channel plays the track's sample chromatically.
