/* off-grid recording: the trigger keys and MIDI notes record where they were played, on the
 * nearest step, early or late. Based on seq-unquantized (kiteless/perkons-re-mods, MIT).
 *
 * On (config row 3 step 13), while playing with REC on, a hit goes in a step with the delay
 * (the signed % of a step it plays off the grid, the value shuffle sets) that plays it at
 * the tick it came:
 * - the step playing, late, in its first half, or when its own (late) time is still ahead:
 *   that step's hit is replaced, so nothing plays twice or crosses;
 * - else the next step, early; it's marked not to play again this pass, as stock does;
 * - while the next step has already started early (the player moves on at an early step's
 *   time), that step, early: the ticks still count from the step before it.
 * The delay is in the track's own clock ticks (24 per step at every rate), so the timing
 * holds at other tempos and rates. Off: stock (the nearest step, on the grid). */
#include <stdint.h>
#include "pk_host.h"
#include "fw_m4_seq.h"

/* fw_m4_seq.h has these from perkons-re 0c6e58e on; earlier checkouts get them here */
#ifndef FW_VS_STEP_STATE
#define FW_VS_STEP_STATE    0x28    /* u8: 0 the step's time is ahead, 1 it came, 2 the next step started early */
#endif
#ifndef FW_DC_VELOCITY
#define FW_DC_VELOCITY      0x1b    /* MIDI velocity on */
#endif
#ifndef fw_seq_play_state
#define fw_seq_play_state   FW_CALL(SYM_seq_play_state, int (*)(void))  /* 1: playing */
#endif

PK_AXI uint8_t pk_cfg_unquantized;          /* system/mods.json "unquantized" (seq-unquantized's) */
PK_AXI static uint8_t played;               /* the trigger key being handled: row + 1, 0 none */

static int recording(void)
{
    return pk_cfg_unquantized && FW_U8(SYM_rec_flags + FW_REC_ON);
}

static uint8_t *step_rec(uint8_t *vs, int step)
{
    return (uint8_t *)(uintptr_t)FW_U32(vs + FW_VS_BLOCK) + step * FW_STEP_SIZE;
}

/* where a hit now on track `vs` goes: its step (0-15, -1 none) and delay */
static int place(uint8_t *vs, int *delay)
{
    uint32_t per = FW_U16(FW_U32(vs + FW_VS_CLOCK) + FW_CLK_STEP_TICKS);
    uint32_t tick = FW_U16(vs + FW_VS_TICK);
    int step = (int16_t)FW_U16(vs + FW_VS_STEP);
    int next = (int16_t)FW_U16(vs + FW_VS_NEXT);
    if (per == 0 || step < 0 || step >= FW_STEPS)
        return -1;
    if (tick >= per)
        tick = per - 1;
    uint8_t state = FW_U8(vs + FW_VS_STEP_STATE);
    int late = state == 0 || (state == 1 && FW_U16(vs + FW_VS_SUBTICK) < per / 2);
    int at = late || state == 2 ? step : next;
    if (at < 0 || at >= FW_STEPS)
        return -1;
    /* the player: delay * per / 100 ticks, truncated towards 0, so round away from it */
    int ticks = late ? (int)tick : (int)(per - tick);
    int d = (100 * ticks + (int)per - 1) / (int)per;
    if (d > 99)
        d = 99;
    *delay = late ? d : -d;
    return at;
}

/* write the hit into step `at`: the delay before `on` (a clock tick in between finds the
 * step's time already passed); the next step doesn't play again this pass */
static void write_hit(uint8_t *vs, int at, int delay, int note, int vel)
{
    uint8_t *rec = step_rec(vs, at);
    *(volatile int16_t *)(rec + FW_STEP_DELAY) = (int16_t)delay;
    if (note >= 0)
        rec[6] = (uint8_t)note;
    rec[7] = (uint8_t)vel;
    rec[0] = 1;
    if (at != (int16_t)FW_U16(vs + FW_VS_STEP))
        FW_U8(vs + FW_VS_PLAY_NEXT) = 0;
}

/* the global key handler (chained): which trigger key key_event is handling */
int PK_NEXT(pk_og_rec_key_event)(const uint8_t *evt);
int pk_og_rec_key_event(const uint8_t *evt)
{
    int trig = evt[0] - FW_KEY_TRIG(0);
    played = evt[1] == FW_EV_DOWN && trig >= 0 && trig < 4 ? (uint8_t)(trig + 1) : 0;
    int r = PK_NEXT(pk_og_rec_key_event)(evt);
    played = 0;
    return r;
}

/* key_event, right after: stock writes the nearest step when this returns 1 (playing) and
 * REC is on. Recording off the grid, write the step here and return 0: stock then stops. */
int PK_NEXT(pk_og_playing)(void);
int pk_og_playing(void)
{
    int state = PK_NEXT(pk_og_playing)();
    if (state != 1 || !recording() || !played)
        return state;
    uint8_t *vs = fw_voice_state(played - 1);
    int delay, at = place(vs, &delay);
    if (at < 0)
        return state;
    write_hit(vs, at, delay, -1, 0x7f);
    return 0;
}

/* MIDI note-on (chained; ch: the voice in multi channel mode, 4 and up in single channel
 * mode, where the note picks the voice). Stock records the nearest step (with the note's
 * velocity and, multi channel, its note), then plays it: that step is put back as it was,
 * and the hit goes where it was played. */
void PK_NEXT(pk_og_midi_note)(uint32_t ch, uint32_t note, uint32_t vel);
void pk_og_midi_note(uint32_t ch, uint32_t note, uint32_t vel)
{
    int track = ch < 4 ? (int)ch : -1;
    for (int t = 0; track < 0 && t < 4; t++)
        if (FW_U8(SYM_device_config + FW_DC_TRIG_NOTE + t) == note)
            track = t;
    uint8_t *vs = track >= 0 && recording() && fw_seq_play_state() == 1 ? fw_voice_state(track) : 0;
    int delay, at = vs ? place(vs, &delay) : -1;
    if (at < 0) {
        PK_NEXT(pk_og_midi_note)(ch, note, vel);
        return;
    }
    int step = (int16_t)FW_U16(vs + FW_VS_STEP), next = (int16_t)FW_U16(vs + FW_VS_NEXT);
    uint8_t was[2][FW_STEP_SIZE], play_next = FW_U8(vs + FW_VS_PLAY_NEXT);
    int cand[2] = {step, next >= 0 && next < FW_STEPS ? next : step};
    for (int i = 0; i < 2; i++)
        for (int j = 0; j < FW_STEP_SIZE; j++)
            was[i][j] = step_rec(vs, cand[i])[j];
    PK_NEXT(pk_og_midi_note)(ch, note, vel);
    if ((int16_t)FW_U16(vs + FW_VS_STEP) != step)
        return;                             /* the clock moved on meanwhile: as stock wrote it */
    for (int i = 1; i >= 0; i--) {          /* the step stock wrote: its note and velocity */
        uint8_t *rec = step_rec(vs, cand[i]);
        int changed = 0;
        for (int j = 0; j < FW_STEP_SIZE; j++)
            changed |= rec[j] != was[i][j];
        if (!changed)
            continue;
        int n = rec[6], v = rec[7];
        for (int j = 0; j < FW_STEP_SIZE; j++)
            rec[j] = was[i][j];
        FW_U8(vs + FW_VS_PLAY_NEXT) = play_next;
        write_hit(vs, at, delay, ch < 4 ? n : -1, v);
        return;
    }
    /* stock rewrote a step as it was (the same hit again): the note's velocity as stock gives it */
    write_hit(vs, at, delay, ch < 4 ? (int)note : -1, FW_U8(SYM_device_config + FW_DC_VELOCITY) ? (int)vel : 0x7f);
}
