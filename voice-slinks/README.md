# voice-slinks

A new synth voice for the Pērkons: scale-locked resonant saw, PWM square and wavefolded
sine, on any of the four voices. *slinks* is Latvian for "something that lacks effort".

Based on official Pērkons firmware **1.3.0**. Unofficial; not affiliated with Erica Synths.

## Getting it

Build Pērkons firmware with **voice-slinks** ticked in the **Mod Matrix**, from your own official
firmware 1.3.0: follow [Get modded firmware](https://github.com/kiteless/perkons-re#get-modded-firmware)
in perkons-re. No firmware files are provided here. To remove it, flash the official
firmware again.
The Mod Matrix ticks VOICE MAP too: voice-slinks runs as a voice-map engine.

## Putting it on a voice

In `voices.json` (SD card root, or `BANKS/NN/` for one bank), give the voice the engine
`"slinks"`:

```json
{ "voice1": "voice1", "voice2": "voice2", "voice3": "slinks", "voice4": "voice4" }
```

Power-cycle or switch banks to load it. If the voice stays stock, look for a
`voices.json` in the bank you're on: a bank's own file replaces the root one entirely.
The voice's knobs, switches, trigger key and input, output jack, and the analog filter,
drive, FX send and level all stay with the voice; only the sound engine changes.

## At a glance

```
TUNE ──► note in the scale ─┐
MIDI note ──► transpose ────┤
                            ▼
            ┌─ saw ──► resonant MS filter (PARAM2) ─┐
 oscillator ┼─ square (pulse width: PARAM2) ────────┼─► envelope ─► analog VCF ─► DRIVE ─► out
            └─ sine (wavefold: PARAM2) ─────────────┘   (PARAM1     (CUTOFF,
                                                         attack,     HP/BP/LP)
                                                         DECAY)
```

## Controls

| control | what it does |
|---|---|
| **TUNE** | picks the note, stepping through the scale chosen by ALGO. No glide: notes jump. |
| **DECAY** | how long the note rings, the same range as the stock voices; fully right holds the note forever (drone) |
| **ALGO** (top switch) | the scale |
| **MODE** (bottom switch) | the waveform |
| **PARAM1** | attack: instant (fully left) to about 2 seconds (fully right) |
| **PARAM2** | the waveform's own control: saw = resonance, square = pulse width, sine = wavefold |
| CUTOFF, filter switch, DRIVE, FX SEND, LEVEL | the Pērkons's analog stages, exactly as on every voice |

Switch positions are numbered as in the Pērkons manual's voice tables (positions 1, 2, 3).

### TUNE and the scales

All three scales are rooted on C (before any MIDI transposition) and span **four
octaves, C1 to C5**. TUNE fully left is C1 (32.7 Hz), fully right is C5 (523 Hz); in
between, the knob is divided evenly into the scale's notes.

| ALGO | scale | notes in each octave | positions on TUNE | character |
|---|---|---|---|---|
| position 1 | **minor pentatonic** | C E♭ F G B♭ | 21 | no wrong notes: basslines, hooks |
| position 2 | **Dorian** | C D E♭ F G A B♭ | 29 | minor but warm: deep house, dub techno |
| position 3 | **Phrygian** | C D♭ E♭ F G A♭ B♭ | 29 | dark, flat 2nd: acid, techno, industrial |

* Each note has a small dead zone around it (about 20% of a step either side), so knob
  jitter never flips a note.
* TUNE is read continuously, as on the stock voices: turning it while a note rings
  changes the pitch at once, in steps. Sequenced TUNE values and parameter locks work as
  on any voice.
* Switching scales re-reads TUNE in the new scale, so the same knob position may give a
  different note.

### MODE: the waveforms, and what PARAM2 does on each

| MODE | waveform | PARAM2, left → right |
|---|---|---|
| position 1 | **saw**, bright and buzzy | **resonance** of the saw's MS filter: clean → squelchy → screaming (just short of self-oscillation) |
| position 2 | **square**, hollow and woody | **pulse width**: 50% (square) → about 10% (thin, nasal) |
| position 3 | **sine**, pure and round | **wavefold**: pure sine → reedy → brassy → buzzy and lopsided (up to ~16× folding) |

**The saw's filter.** Only the saw goes through voice-slinks's own resonant low-pass (an
MS-style, saturating two-pole filter). Its cutoff follows the note and the envelope: on
each hit it opens to about 32× the note's frequency and closes towards 2× as the note
decays. That's the squelch, and PARAM2 sets how much resonance rides on it. Square and
sine have no extra filter: the voice's analog filter (CUTOFF) is their only filter.

**The sine's fold.** PARAM2 sets how far the sine folds, and turning it up also makes
the fold increasingly asymmetrical (even harmonics: hollower, growlier). The folding is
smooth and done in two stages, like the classic Serge and Buchla folders, and
oversampled so heavy settings stay clean. PARAM2 fully left is a pure sine.

### PARAM1: attack

| PARAM1 | attack time |
|---|---|
| fully left | ~0.5 ms (instant, click-free) |
| 12 o'clock | ~30 ms |
| fully right | ~2 s |

The knob is exponential, so most of its travel is in the useful short range. A new
trigger restarts the attack from wherever the note currently is, so fast retriggers
don't click.

### DECAY

The same curve as the stock voices, as the time for the note to fall by 60 dB:

| DECAY (knob travel) | time |
|---|---|
| fully left | ~0.08 s |
| a quarter | ~0.4 s |
| half (12 o'clock) | ~2 s |
| three quarters | ~12 s |
| fully right | never decays (drone) |

## Velocity, mute, level

* **Velocity** scales the level linearly, as on the stock voices (velocity 64 is half as
  loud as 127).
* **Mute** fades out over about 10 ms, exactly like a stock voice.
* The peak level matches the stock tonal voices, so voice-slinks sits with the other voices at
  the same LEVEL setting. A square is denser than a filtered saw, so square mode can sound
  slightly louder at the same setting.

## MIDI and the sequencer

voice-slinks follows MIDI exactly as the stock voices do; nothing on the MIDI side is changed.

* **Notes transpose it.** Note 36 (the note the trigger keys and pads send) means no
  change; each note above or below moves it by a semitone. **Pure transposition**:
  incoming notes are not forced into the scale.
  * With TUNE on the scale's root (C), a keyboard plays voice-slinks chromatically.
  * With TUNE elsewhere, the note shifts the whole scale: playing F (note 41) moves a C
    minor-pentatonic line up to F minor pentatonic.
* **Multi-channel MIDI mode** (voice 1 = channel 1, and so on): any note on the voice's
  channel plays it at that pitch, and notes can be recorded into steps or entered with a
  held step button, as with the stock voices.
* **Single-channel MIDI mode**: notes 36/37/38/39 trigger voices 1-4, and the stock
  firmware also uses that note as the pitch. So a voice-slinks on voice 2, 3 or 4 played over
  MIDI in this mode sounds 1, 2 or 3 semitones higher than from its own trigger key
  (stock behaviour, inherited).
* A trigger with no note (note 0) keeps the previous note.
* MIDI CCs for TUNE, DECAY, PARAM1, PARAM2, ALGO and MODE work as on any voice.

## Tips

* **Acid line**: saw, Phrygian, PARAM2 most of the way up, short-to-medium DECAY, CUTOFF
  open; sequence TUNE per step.
* **Sub bass**: sine, PARAM2 fully left, TUNE low, DECAY to taste; add DRIVE for grit.
* **Nasal lead**: square, PARAM2 towards the right (narrow pulse), filter in BP mode.
* **Pad / drone**: any waveform, PARAM1 towards the right, DECAY fully right; play notes
  over MIDI to change key.
* **Live key changes**: keep TUNE patterns in the sequencer and play single MIDI notes to
  move the key.

## Details

* Tuning: A = 440 Hz equal temperament.
* Notes outside 8 Hz-12 kHz (extreme MIDI transposition) are held at those limits.

