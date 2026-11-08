# FX sidechain

Sidechain ducking for the Pērkons. One voice is the master: each time it triggers, the
other three voices dip in level and come back, the pumping sound of a sidechain
compressor keyed from the kick. You set the duck's shape on the four rows of step buttons:
depth, attack, hold and release.

Based on official Pērkons firmware **1.3.0**. Unofficial; not affiliated with Erica Synths.

## Getting it

Build Pērkons firmware with **FX SIDECHAIN** ticked in the **Mod Matrix**, from your own
official firmware 1.3.0: follow [Get modded firmware](https://github.com/kiteless/perkons-re#get-modded-firmware)
in perkons-re. No firmware files are provided here. To remove it, flash the official
firmware again.

## Turning it on and off

Hold **KIT** and tap **SYNC**: the sidechain turns on, or off if it was on. It's kept
with the kit at once.

Releasing KIT leaves you on the kit page, as stock.

## The sidechain page

Hold **KIT** and hold **SYNC** for half a second: the sidechain page opens, and stays open
after you let go. Every row of step buttons sets one part of the duck. A step's LED is
bright at the row's value, with a dim bar up to it. Everything is dimmer while the
sidechain is off.

| row | sets | step 1 → step 16 |
|---|---|---|
| 1 | **depth**: how far the other voices dip | 3, 4.5, 6, 7.5, 9, 10.5, 12, 13.5, 15, 16.5, 18, 21, 24, 30, 40 dB; step 16 = silent |
| 2 | **attack**: how fast they dip | 0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 13, 16, 20, 25, 35, 50 ms |
| 3 | **hold**: how long they stay down | none, 10, 25, 50, 75, 100, 125, 150, 175, 200, 225, 250, 275, 300, 400, 500 ms |
| 4 | **release**: how long until they're back to normal | 10, 25, 50, 75, 100, 125, 150, 190, 250, 300, 375, 440, 500, 625, 750, 1000 ms |

The rows are made for pumping and chopping. Most of the depth row is between 6 and 18 dB.
The voices are back after about the hold plus the release, so for the classic pump make
the two add up to just under one beat: 150 ms hold and 300 ms release at 120-130 BPM, for
example, brings the voices back just before the next kick. Deep settings with a short release and some hold chop the voices in time with the
master; the silent step gates them completely.

Also on the page:

| control | does |
|---|---|
| trigger keys 1-4 | choose the master voice (its trigger LED stays lit); the voice plays as usual, so you hear the duck at once |
| SYNC | sidechain on / off (its LED lit while on) |
| any page button | leaves the page |

A new kit starts with the sidechain off, voice 1 as the master, a 15 dB duck, 1 ms
attack, 150 ms hold, and back after 300 ms.

## How it behaves

* Every trigger of the master ducks: sequencer steps, its trigger key and MIDI notes.
* The other three voices duck together. The master itself is never ducked.
* The duck happens inside the voices, before the outputs, so it is heard on the
  individual voice outputs, the main mix and the FX send alike. Echo and reverb tails
  already in the FX don't duck.
* A new master trigger during a duck starts the duck again from wherever the level is,
  without a jump.
* Turning the sidechain off, or choosing another master, lets a duck that is under way
  finish its release.
* While the sidechain is off, the voices sound exactly as without the mod.
* It works with the factory voices and with [voice-map](../voice-map/) engines.

## Kits

Each kit keeps its own sidechain settings: on / off, the master and the four rows. They
are saved in the kit's companion file on the SD card, so the kit files themselves stay
unchanged.

* An on / off with KIT + SYNC is saved at once.
* Changes on the sidechain page are saved when you leave the page.
* Saving a kit as usual saves the settings it is playing with.
* Loading a kit or a bank brings back each kit's settings.
