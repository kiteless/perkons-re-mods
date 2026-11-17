# Off-grid: hardware test plan

Results: the full plan **passed** on a Pērkons with the off-grid build (17 Nov 2026). TEMPO editing tests 1–13 had also passed earlier as the microtiming mod.

One bug was found on the unit and fixed: with TEMPO fully up when a step was held, the step couldn't be moved later. Turning past the end of the range now doesn't count, so turning back moves the step again at once. Retested on the unit after the fix.

## Before you start

- Build the image in the Mod Matrix with only OFF-GRID ticked. Add other mods only in test 26.
- Keep the official `perkons_v1.3.0-0-force.img` on your computer so you can flash back.
- After flashing, check that `INFO.TXT` on the SD card shows a tag with `og` in it.
- Use a simple pattern: track 1 with steps on 1, 5, 9 and 13, and track 2 with the same steps as an unshifted reference. Pick short, clicky sounds so timing is easy to hear.

## TEMPO editing

Turn TEMPO editing on (config row 3 step 12) for tests 3–13.

| # | Test | Do | Expect | Result |
|---|---|---|---|---|
| 1 | Toggle off is stock | Leave TEMPO editing (row 3 step 12) off, hold a step, turn TEMPO | Tempo changes as normal, no view | pass |
| 2 | Toggle on, saved | SHIFT + MOD, press row 3 step 12, power cycle | The LED is still lit in the config menu | pass |
| 3 | Tempo is frozen | Hold step 5 on track 1, turn TEMPO a long way | The tempo doesn't change | pass |
| 4 | View opens | Same as 3 | Dim LEDs on five steps each side of step 5, one bright LED, the rest of the row dark. Other rows normal | pass |
| 5 | Dead zone and divisions | From a fresh hold, turn slowly | Nothing for about 20°, then the bright LED steps once per about 10°, stopping at 5 each way | pass |
| 6 | Direction | Turn each way | Clockwise: bright LED moves right, the hit is later than track 2. Counter-clockwise: left and earlier | pass |
| 7 | Back to zero | Turn back to where you started | Bright LED on the held step, the hit lines up with track 2 | pass |
| 8 | Release | Let go | The row goes back to normal, the step is still on | pass |
| 9 | No tempo jump | After release, turn TEMPO | No tempo change until the knob is near the current tempo (within 12 BPM), then it follows smoothly | pass |
| 10 | Re-hold shows the offset | Shift a step by 3, release, hold again, nudge TEMPO | The bright LED appears 3 steps away | pass |
| 11 | Empty step | Hold a step that's off, turn TEMPO | The tempo changes as normal | pass |
| 12 | Clear on turn-off | Shift a step, tap it off, tap it on | It plays on the grid again | pass |
| 13 | Save and reload | Shift two steps, save, switch patterns and back, power cycle | The shifts are still there | pass |

## Recording

Turn off-grid recording on (config row 3 step 13). Use a slow tempo (60–80 BPM) so early and late are easy to hear, with a metronome-like part on track 2.

| # | Test | Do | Expect | Result |
|---|---|---|---|---|
| R1 | Toggle, saved | Press row 3 step 13, power cycle | The LED is still lit | pass |
| R2 | Carry-over | On a card where UNQUANTIZED was on, flash off-grid | Row 3 step 13 is already lit | pass |
| R3 | Late hit | REC, play track 1's trigger key a little after a beat | Plays back a little after that beat, every time round. The step it lands on is the beat's step | pass |
| R4 | Early hit | REC, play a little before a beat | Plays back a little before that beat. It lands on the beat's step, not the one before | pass |
| R5 | No double | Watch R3 and R4 on the pass you record | You hear your hit once, not again from the sequencer on that pass | pass |
| R6 | Last to first | Play just before the bar line | Lands on step 1, early, and plays just before the bar line | pass |
| R7 | View | Hold a recorded early step and nudge TEMPO (TEMPO editing on) | The bright LED is to the left of the step | pass |
| R8 | MIDI | Record from MIDI notes, early and late, single and multi channel | As R3 and R4. Velocity kept with MIDI velocity on, notes kept in multi channel | pass |
| R9 | Off is stock | Recording toggle off, record early and late | Hits snap to the nearest step, on the grid | pass |
| R10 | Old recordings | Load a pattern recorded with UNQUANTIZED | Plays as before | pass |
| R11 | Overdub next to off-grid steps | Record early hits, then on the next passes record more hits just before and after them, and next to steps moved with TEMPO | Every hit plays where you played it. No hit lands a step late or goes missing, and steps you didn't record stay empty | pass |

## Worst cases

| # | Test | Do | Expect | Result |
|---|---|---|---|---|
| 14 | Knob noise | Hold a step for 10 s without touching TEMPO, and again while turning another knob for a p-lock | The view never opens by itself | pass |
| 15 | Knob travel | Turn through 5 divisions | About 70° of turn. If it's much wider or narrower, `DEG` in `src/m4/tempo_edit.c` needs changing | pass |
| 16 | Edge of the knob | TEMPO fully up, hold a step, turn down past −5, then back up | The step moves later as soon as you turn back up (the bug fixed above) | pass |
| 17 | Quick flick | Hold a step well under a second while flicking TEMPO | Note whether the step turns off on release. Stock treats holds under about a third of a second as a tap | pass |
| 18 | Neighbour limit | Steps on 7 and 8. Shift 7 to +5, then hold 8 and turn fully counter-clockwise | No dim LEDs left of step 8. Both hits sound | pass |
| 19 | First step early | Shift step 1 to −3 | Sounds just before the bar line every time round, but silent the very first time after PLAY | pass |
| 20 | Rotate and copy | With a shifted step, rotate the track (TRACK ROTATE on in the config) and copy the pattern | The shift moves with the step | pass |
| 21 | Shuffle | Set shuffle on a track with shifted steps. Then shift one step, tap it off and on | Shuffle replaces the shifts. The re-entered step is back on the shuffle grid | pass |
| 22 | Play modes and rate | A shifted step with the track in reverse and random, and with the rate on divide and multiply | No missing or doubled hits. In reverse, two neighbours moved onto each other play as one (known) | pass |
| 23 | Fast and slow tempo | Repeat test 6 at the lowest and highest tempo | No hits drop out | pass |
| 24 | Pattern switch | Queue a pattern whose step 1 is shifted early while another plays | No missing or extra hit at the switch | pass |
| 25 | External clock and MIDI | Run from MIDI clock, and from analog clock at 1 PPQN. With MIDI SEQ OUT on, watch the notes | Shifts sound the same. MIDI notes shift with the audio | pass |
| 26 | Other mods | Rebuild with your usual mods ticked too and repeat tests 3 to 9, and R3 | All pass | pass |
| 27 | Official firmware | Flash the official image and load the same pattern | Shifted steps play the same way | pass |
| 28 | Recording and editing | Record a hit, then hold its step and move it with TEMPO | It moves from where it was recorded (rounded to a sixth) | pass |
| 29 | Recording at fast tempo | Record early and late hits at the highest tempo | No doubled or missing hits | pass |

## Reporting a failure

Give the test number, what you saw, and the tempo and play mode at the time. For tests 14 and 15 a rough number is enough, such as "the view opened after 3 seconds" or "5 divisions took about half a turn".
