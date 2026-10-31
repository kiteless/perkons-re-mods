# Per track LFO

LFO groups for the four voices. Out of the box all four share the main LFO, as on the
factory firmware; take any voices out into a group of their own and give it its own
rate, wave, level and SYNC.

Based on official Pērkons firmware **1.3.0**. Unofficial; not affiliated with Erica Synths.

## Getting it

Build Pērkons firmware with **PER TRACK LFO** ticked in the **Mod Matrix**, from your own
official firmware 1.3.0: follow [Get modded firmware](https://github.com/kiteless/perkons-re#get-modded-firmware)
in perkons-re. No firmware files are provided here. To remove it, flash the official
firmware again.

## Using it

Every voice is in exactly one LFO group. At power-on there is one group, the main LFO,
with all four voices: the unit behaves as the factory firmware.

| do | what happens |
|---|---|
| hold one or more **trigger keys** and turn **RATE**, **WAVE** or **MOD LVL** | the held voices leave their groups and become one group, starting as a copy of the first held voice's LFO; the turn changes it, and it becomes the **selection** |
| hold trigger keys and press **SYNC** | the same group is formed or selected, and its SYNC goes on / off |
| turn the LFO knobs with no trigger key held | the selection: the group you last turned a knob (or pressed SYNC) with |
| hold **RESET** and turn **RATE**, even slightly | everything back in one group, with the selection's settings |
| clear a track (**CLEAR** + trigger), its automation (**SHIFT** + **CLEAR** + trigger) or a pattern | everything back in the main LFO, as it is set |

* Holding exactly the voices of an existing group edits that group.
* When the selection changes, the knobs take it as the factory firmware takes a kit's
  values: with pot catch on (config), once a knob reaches the group's value; with it off,
  once you turn it.
* **Trigger LEDs**, once there is more than one group: dim for a voice in a group of its
  own, pulsing with the LFO for the selection. Hits and mutes show as on the factory
  firmware.
* While a trigger key is held, the LFO and SYNC LEDs show that voice's group; otherwise
  the selection's.
* Where the LFO goes and how much is still set per voice on the MOD page, as usual.
* Pressing a trigger key still plays the voice, and RESET still does what it does on the
  factory firmware.
* Restarting the sequencer restarts every LFO.
* Groups are not saved: they last until RESET + RATE, a clear, or power-off. Kits save and
  load the main LFO as usual.
* The MIDI tracks of [eight-lanes](../eight-lanes/) have no LFO.
