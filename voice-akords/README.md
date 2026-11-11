# voice-akords

A chord synth voice for the Pērkons: every note plays a chord in your scale, on any of the
four voices, with synth presets chosen on a settings page of its own. *Akords* is Latvian for "chord". Its sound
comes from a poly synth I built on iOS: two oscillators per chord note into a resonant filter
with its own envelope.

Based on official Pērkons firmware **1.3.0**. Unofficial; not affiliated with Erica Synths.

## Getting it

Build Pērkons firmware with **voice-akords** ticked in the **Mod Matrix**, from your own
official firmware 1.3.0: follow [Get modded firmware](https://github.com/kiteless/perkons-re#get-modded-firmware)
in perkons-re. No firmware files are provided here. To remove it, flash the official
firmware again.

voice-akords runs as a [voice map](https://github.com/kiteless/perkons-re/blob/main/docs/voice-map.md) engine: in the Mod Matrix, on the
**ENGINES** tab, install voice-akords. It takes the slot you install
it in (5 if it's the first).

## Putting it on a voice

On the voice-map engine page (KIT + MOD), press voice-akords' column in the voice's row; its
next note plays voice-akords. **Hold that step for half a second** to open its
[settings page](#the-settings-page) for that voice.

## At a glance

```
settings page: preset, chord type, progression, scale, root
TUNE (+ progression) ──► chord root in the scale ─┐
MIDI note ──► transpose ─────────────────────────┤
                                                 ▼
 3-5 notes × 2 oscillators (preset) ─► filter (MODE; PARAM1 cutoff, resonance,
                                       its own envelope)
     ─► amp envelope (GATE = DECAY) ─► limiter ─► level for DRIVE (±3 dB)
                                                        │
 the voice's analog stages, as on every voice:          ▼
     analog filter (CUTOFF, filter switch) ─► DRIVE ─► LEVEL ─► output jack / mix
                                                 │
                                                 └─► FX SEND ─► the Pērkons's FX ─► mix
```

One chord sounds at a time: a new note replaces the one before.

## Controls

| control | what it does |
|---|---|
| **TUNE** | the chord's root, stepping through the scale, over four octaves from the root (C2 to C6 with root C) |
| **DECAY** | **GATE**: how long the chord holds before its release, from about 0.05 s to about 2 s; fully right, the chord drones and never releases on its own |
| **PARAM1** | filter cutoff (with the formant filter: the vowel) |
| **PARAM2** | ALGO position 1: resonance (with the formant filter: the formant shift), 2: filter envelope amount, 3: amp attack |
| **MODE** | the filter: position 1 **24 dB low-pass**, 2 **12 dB high-pass**, 3 **formant** (see below) |
| CUTOFF, filter switch, DRIVE, FX SEND, LEVEL | the Pērkons's analog stages, exactly as on every voice |

Switch positions are numbered as in the Pērkons manual's voice tables.

* **The PARAM knobs are relative to the preset.** At 12 o'clock, cutoff, resonance, filter
  envelope amount and attack are the preset's own; turning left or right takes them to the
  ends of their range.
* **When ALGO gives PARAM2 another job**, that setting stays as it was until you move the knob.
* **Pressing a preset gives you its own sound**, even when it's the one already chosen:
  cutoff, resonance, filter envelope amount, attack and filter all go back to the preset's,
  whatever the knobs and MODE say. Each control takes over again when you move it.
* **Turning DECAY down from drone** releases the chord playing.

### The filter (MODE)

Each preset has its own filter (see [Presets](#presets-row-1)) until you move MODE; then the
filter follows the switch.

**Formant** shapes the chord into a vowel. PARAM1 sweeps the vowel from dark to bright,
**U O A E I**, and the filter envelope moves it on each chord. On ALGO position 1, PARAM2
is the **formant shift**: left down to an octave lower (a bigger, deeper voice), right up to
an octave higher (a smaller, brighter one).

## The settings page

Each row is one setting; bright is the one chosen.

| row | setting |
|---|---|
| 1 | [preset](#presets-row-1) |
| 2 | [chord type](#chord-types-row-2), steps 1-10; [progression](#progressions-row-2), steps 11-16 |
| 3 | [scale](#scales-row-3) |
| 4 | [root](#root-row-4) |

* The trigger keys play the voices, so you can hear changes as you make them.
* **SHIFT**, **KIT** or **MOD** go back to the engine page.
* **The settings are kept with the kit**: leaving the page after a change saves them, and the
  sound as it is then, to the card straight away, as does saving the kit. They're in
  `BANKS/NN/KITS/PP.KIX`.

### Presets (row 1)

| step | preset | oscillators | filter | sound |
|---|---|---|---|---|
| 1 | Bass | saw and pulse, an octave down | 24 dB low-pass, fairly low (1.4 kHz), some resonance; a quick filter envelope gives each chord a punchy attack | firm, round low chords |
| 2 | Pad | two detuned saws | 24 dB low-pass, mellow (2.2 kHz), little resonance; a slow filter envelope opens it over about a second | slow attack and long release: a wash |
| 3 | Lead | saw and pulse | 24 dB low-pass, bright (4.2 kHz), some resonance | bright and forward, with glide between chords |
| 4 | Keys | saw and a triangle an octave up | 24 dB low-pass (3.6 kHz), little resonance; the filter closes as the note decays | plucky electric-piano-like chords |
| 5 | Pluck | two slightly detuned saws | 24 dB low-pass (2.6 kHz), resonant; a strong, fast filter envelope snaps shut | short, no sustain |
| 6 | Stab | two detuned saws | 24 dB low-pass, low (1.5 kHz), the most resonant preset; a strong, fast filter envelope | short, resonant house and techno stabs |
| 7 | Hollow | two detuned pulses | 24 dB low-pass (2.8 kHz), gentle, little resonance | reedy and hollow, sustained |
| 8 | Reese | two saws detuned hard, an octave down | 24 dB low-pass, dark (900 Hz), a little resonance | the drum & bass Reese: thick, beating, with glide |
| 9 | Organ | triangle and a sine an octave up | 24 dB low-pass, wide open (9 kHz), no resonance, no filter envelope | clean organ chords that hold |
| 10 | Bell | sine and a triangle, one and two octaves up | 24 dB low-pass, open (6 kHz), no resonance | glassy bells with a long decay |
| 11 | Air | detuned saw and a pulse an octave up | **12 dB high-pass** (700 Hz): removes the low end; its envelope lowers the cutoff on the attack, letting a little more body through | thin, bright and airy |
| 12 | Choir | two detuned saws | **formant**, on "ah" | a slow, sung choir |
| 13 | Vox | pulse and saw | **formant**: each chord's vowel opens from "oh" to "ah" | a vocal "wow" on every chord |
| 14 | Talk | saw and a saw an octave up | **formant**: each chord's vowel dips from "eh" towards "oh" and back | talking, wah-like chords |

Glide slides each note of a new chord from the matching note of the chord before.

### Chord types (row 2)

Steps 1-10 of row 2. Each type comes plain and **smooth**.

| step | chord | notes |
|---|---|---|
| 1 | **Diatonic** | the triad the scale gives on that note: in C major, C, Dm, Em, F, G, Am, B° |
| 2 | Diatonic, smooth | |
| 3 | **Diatonic 7th** | the same with its 7th (4 notes): Cmaj7, Dm7, Em7, Fmaj7, G7, Am7, Bm7♭5 |
| 4 | Diatonic 7th, smooth | |
| 5 | **Diatonic 9th** | the 7th chord with its 9th (5 notes): Cmaj9, Dm9, G9 ... |
| 6 | Diatonic 9th, smooth | |
| 7 | **Quartal** | four notes in fourths (root, 4, ♭7, ♭10): the dub techno stab |
| 8 | Quartal, smooth | |
| 9 | **Power** | root, 5, octave: for bass and Reese |
| 10 | Power, smooth | |

* **Odd steps play in root position**: the chord moves up and down as a block.
* **Even steps are smooth**: each chord takes the inversion nearest the chord before it
  (C → F plays C F A, not F A C), staying within about an octave of TUNE. After a silence it
  starts again in root position.
* On pentatonic and blues scales, the diatonic types take the nearest notes the scale has, and
  a sus chord where it has no third. On Chromatic, Diatonic plays major chords, Diatonic 7th
  minor 7ths and Diatonic 9th minor 9ths.

### Progressions (row 2)

Steps 11-16 of row 2. The chord moves on **once every cycle of the voice's track**: every 16
steps on a 16-step track, every 9 on a 9-step one.

| step | progression | chords | style |
|---|---|---|---|
| 11 | **Off** | TUNE alone | |
| 12 | Trance | i – VI – III – VII | trance and uplifting: Cm, A♭, E♭, B♭ in C minor |
| 13 | Epic | i – VI – VII – v | epic and cinematic builds: Cm, A♭, B♭, Gm |
| 14 | Progressive | i – v – VI – iv | progressive house, melodic techno: Cm, Gm, A♭, Fm |
| 15 | Techno | i – VI | a dark, hypnotic two-chord techno vamp: Cm, A♭ (two notes stay, one moves) |
| 16 | Deep | i – iv | a two-chord deep house vamp: Cm, Fm |

* **TUNE sets the first chord**, and the progression moves from it through the scale.
* They're written for the **minor scales**. In other scales they take the same scale steps, so
  they give different chords.
* The progression restarts when the sequencer starts or stops, and when the pattern changes.
* In other play modes, the chord moves on each time the track returns to its first step; on a
  one-step track it never moves on.

### Scales (row 3)

| step | scale | notes from C | character, and where you hear it |
|---|---|---|---|
| 1 | Major | C D E F G A B | bright and resolved: pop, house, uplifting trance |
| 2 | Natural Minor | C D E♭ F G A♭ B♭ | dark and moody: the everyday minor of techno, trance, drum & bass and most dark electronic music |
| 3 | Minor Pentatonic | C E♭ F G B♭ | five notes with no semitones: rock, blues, funk, hip-hop |
| 4 | Harmonic Minor | C D E♭ F G A♭ B | minor with a raised 7th that pulls hard back to the root: classical, metal, epic trance, film music |
| 5 | Dorian | C D E♭ F G A B♭ | minor but warmer, with a bright 6th: deep house, dub techno, funk, soul, jazz |
| 6 | Phrygian | C D♭ E♭ F G A♭ B♭ | minor with a tense ♭2 a semitone above the root: dark techno, metal, flamenco |
| 7 | Major Pentatonic | C D E G A | open and sunny, five notes: folk, country, pop, chillout |
| 8 | Mixolydian | C D E F G A B♭ | major with a bluesy ♭7: rock, funk, disco, Afro house |
| 9 | Blues | C E♭ F F♯ G B♭ | the minor pentatonic plus the "blue" ♭5: blues, jazz, rock, hip-hop |
| 10 | **Phrygian Dominant** | C D♭ E F G A♭ B♭ | the Spanish / Middle-Eastern scale of flamenco, psytrance and dark techno. Its chords: C, D♭, E°, Fm, G°, A♭+, B♭m |
| 11 | Chromatic | all 12 notes | no key: TUNE steps by semitones, for experimental and atonal parts |

### Root (row 4)

| step | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| root | C | C♯ | D | E♭ | E | F | F♯ | G | A♭ | A | B♭ | B |

## Level

**The level follows DRIVE**: up to about +3 dB with little or no DRIVE, so a clean chord sits
with the voices that use DRIVE, and down to about -3 dB at full, to keep full DRIVE from
overdoing it.

## MIDI and the sequencer

* **Notes transpose the chord**: note 36 means no change; each note above or below moves the
  whole chord, scale included, by a semitone.
* Sequenced DECAY values give per-step gate lengths.
* Parameter locks and MIDI CCs on PARAM2 change whatever ALGO gives it when they play.

## Saved with the kit

Saving a kit keeps the sound you made, on top of the settings page:

* All three PARAM2 values, not only the one ALGO is on.
* The filter: the preset's own, or the one chosen with MODE.
* The preset's values after a preset press, for any knob you haven't moved since.

A kit saved with an earlier version of Akords plays from its knob positions, as it did before,
until you save it again.
