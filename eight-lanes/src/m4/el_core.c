/* eight-lanes: lanes 5-8 run through the stock sequencer core.
 *
 * At boot (after the M4 host zeroed our RAM, before any bank loads) the four stock track
 * states move to an 8-entry array in AXI SRAM, lanes 5-8 are added, the current pattern
 * gets an 8-track working block and the track count becomes 8. The per-track note
 * records are already 8 entries (their three references point at pk_el_notes).
 *
 * The stock core then advances, triggers and prepares notes for all 8 tracks; the stock
 * outputs (M7 triggers, MIDI) stay 4-track. After every sequencer tick, el_lanes_tick
 * sends lanes 5-8 as MIDI: note on when the core fired the lane, note off when the gate
 * (from DECAY, evaluated live) runs out. */
#include "el.h"


/* device_config (stock MIDI settings) */

#define GATE_TIE        0xffffffffu
#define STEP_TIE        3

PK_AXI uint8_t pk_el_states[TRACKS * 0x10c] __attribute__((aligned(4)));
PK_AXI uint8_t pk_el_notes[TRACKS * 0xc] __attribute__((aligned(4)));

void el_config_defaults(void);       /* el_config.c */
uint8_t el_lane_channel(int l);
uint8_t el_lane_trig_note(int l);

typedef struct {
    uint8_t sounding;       /* a note is on */
    uint8_t note, channel;
    uint8_t last_step_valid;
    uint16_t last_step;
    int8_t shift;           /* TUNE semitone shift, held for hysteresis */
    uint32_t age;           /* sub-ticks since note on */
    uint32_t since_step;    /* sub-ticks since the lane's step changed */
    uint32_t step_len;      /* measured sub-ticks per lane step */
} lane_t;

PK_AXI static lane_t lanes[NLANES];

#define DC(off)         FW_U8(SYM_device_config + (off))

void el_copy(void *dst, const void *src, uint32_t n)
{
    uint8_t *d = dst;
    const uint8_t *s = src;
    while (n--)
        *d++ = *s++;
}

uint32_t el_irq_off(void)
{
    uint32_t primask;
    __asm volatile("mrs %0, primask\n cpsid i" : "=r"(primask));
    return primask;
}

void el_irq_restore(uint32_t primask)
{
    __asm volatile("msr primask, %0" : : "r"(primask));
}

void pk_el_init(void)
{
    uint8_t *s = el_seq();
    uint32_t pm = el_irq_off();

    /* states: the 4 set up by the firmware, lanes as copies of track 4 */
    el_copy(pk_el_states, PTR(U32(s + FW_SEQ_STATES)), 4 * STATE);
    for (int t = FIRST_LANE; t < TRACKS; t++) {
        el_copy(el_state(t), el_state(3), STATE);
        el_state(t)[FW_VS_INDEX] = (uint8_t)t;
    }
    /* note records: stock initial values, twice */
    el_copy(pk_el_notes, PTR(SYM_seq_notes), 4 * NOTE_REC);
    el_copy(pk_el_notes + 4 * NOTE_REC, pk_el_notes, 4 * NOTE_REC);

    el_config_defaults();           /* before system/mods.json loads */
    for (int l = 0; l < NLANES; l++)
        lanes[l].step_len = 288;

    U32(s + FW_SEQ_STATES) = ADDR(pk_el_states);
    el_patterns_init();             /* the current pattern gets an 8-track working block */
    s[FW_SEQ_COUNT] = TRACKS;
    el_irq_restore(pm);
}

/* ---- lane MIDI -------------------------------------------------------------------- */

static void midi(uint8_t status, uint8_t d1, uint8_t d2)
{
    fw_midi_out(0, (uint32_t)status | (uint32_t)d1 << 8 | (uint32_t)d2 << 16 | 3u << 24);
}

static void note_off(lane_t *ln)
{
    if (ln->sounding) {
        midi((uint8_t)(0x80 | ln->channel), ln->note, 0);
        ln->sounding = 0;
    }
}

/* TUNE -> semitone shift: centre = 0, range from the top switch, held with hysteresis */
static int tune_shift(lane_t *ln, const uint8_t *vs)
{
    static const uint8_t octaves[3] = {2, 1, 4};      /* switch value 0 middle, 1 up, 2 down */
    uint32_t range = octaves[U16(vs + FW_VS_VALUE + 2 * SLOT_RANGE) % 3] * 12u;
    int32_t pos = (int32_t)U16(vs + FW_VS_VALUE + 2 * FW_SLOT_TUNE) - 32768;
    /* position in semitones x 4 (quarter-semitone resolution for the hysteresis) */
    int32_t q = pos * (int32_t)range * 4 / 32768;
    int32_t cur = ln->shift * 4;
    if (q > cur + 3 || q < cur - 3)                    /* moved more than ~0.75 semitone */
        ln->shift = (int8_t)((q + (q >= 0 ? 2 : -2)) / 4);
    return ln->shift;
}

static int octave(const uint8_t *vs)
{
    static const int8_t oct[3] = {0, 1, -1};          /* 0 middle, 1 up, 2 down */
    return oct[U16(vs + FW_VS_VALUE + 2 * SLOT_OCTAVE) % 3];
}

/* gate length in sub-ticks from DECAY: left = blip, centre = one step, right = tie */
static uint32_t gate(const lane_t *ln, const uint8_t *vs)
{
    uint32_t d = U16(vs + FW_VS_VALUE + 2 * FW_SLOT_DECAY);
    uint32_t step = ln->step_len ? ln->step_len : 288;
    if (d >= 63570)                                    /* top 3%: tie */
        return GATE_TIE;
    if (d <= 32768) {                                  /* blip .. one step, square law */
        uint32_t x = d >> 7;                           /* 0..256 */
        return 1 + (step - 1) * x * x / 65536;
    }
    /* one step .. eight steps, exponential-ish: 2^(3 * x) */
    uint32_t x = (d - 32768) * 256 / (63570 - 32768); /* 0..256 */
    uint32_t len = step;
    for (uint32_t i = 0; i < 3; i++)                   /* three doublings over the range */
        if (x > 85 * (i + 1))
            len *= 2;
    uint32_t frac = x % 85;
    return len + len * frac / 85;
}

static void lane_fire(int l, lane_t *ln, const uint8_t *vs)
{
    const uint8_t *rec = pk_el_notes + (FIRST_LANE + l) * NOTE_REC;
    uint8_t vel = (uint8_t)((rec[3] * rec[5] + rec[5]) >> 7);
    uint8_t note, ch;
    if (DC(FW_DC_MULTI)) {
        int n = rec[4] + tune_shift(ln, vs) + 12 * octave(vs);
        note = (uint8_t)(n < 0 ? 0 : n > 127 ? 127 : n);
        ch = el_lane_channel(l);
    } else {
        note = el_lane_trig_note(l);
        ch = DC(FW_DC_CH_SINGLE) & 15;
    }
    note_off(ln);
    if (!DC(FW_DC_SEQ_OUT) || !vel)
        return;
    midi((uint8_t)(0x90 | ch), note, vel);
    ln->sounding = 1;
    ln->note = note;
    ln->channel = ch;
    ln->age = 0;
}

/* trigger keys on page B: play the lane live, as a step with note 36 would */
PK_AXI static uint8_t live_note[NLANES], live_ch[NLANES], live_on[NLANES];

/* play a lane live (trigger keys on page B, MIDI in): note = the given step note
 * + TUNE + octave (multi-channel), or the lane's trigger note (single-channel) */
void el_lane_live_note(int l, int on, int step_note, int vel)
{
    if (l < 0 || l >= NLANES)
        return;
    if (live_on[l]) {
        midi((uint8_t)(0x80 | live_ch[l]), live_note[l], 0);
        live_on[l] = 0;
    }
    if (!on || !DC(FW_DC_SEQ_OUT))
        return;
    const uint8_t *vs = el_state(FIRST_LANE + l);
    uint8_t note, ch;
    if (DC(FW_DC_MULTI)) {
        int n = step_note + tune_shift(&lanes[l], vs) + 12 * octave(vs);
        note = (uint8_t)(n < 0 ? 0 : n > 127 ? 127 : n);
        ch = el_lane_channel(l);
    } else {
        note = el_lane_trig_note(l);
        ch = DC(FW_DC_CH_SINGLE) & 15;
    }
    midi((uint8_t)(0x90 | ch), note, (uint8_t)(vel ? vel : 0x7f));
    live_on[l] = 1;
    live_note[l] = note;
    live_ch[l] = ch;
}

void el_lane_live(int l, int on, int vel)
{
    el_lane_live_note(l, on, 36, vel);
}

/* note repeat (rolls, page 9): stock rolls run in the 4-track tick code; lanes roll here,
 * with the stock rate tables (periods and gates in sub-ticks), while the key is held */
#define ROLL_RATES      8
PK_AXI static uint8_t roll_held[NLANES], roll_rate[NLANES], roll_on[NLANES];
PK_AXI static uint32_t roll_phase[NLANES];

void el_roll_hold(int l, int on)
{
    if (l < 0 || l >= NLANES)
        return;
    if (on && !roll_held[l])
        roll_phase[l] = 0;
    roll_held[l] = (uint8_t)(on != 0);
    if (!on && roll_on[l]) {
        el_lane_live_note(l, 0, 36, 0);
        roll_on[l] = 0;
    }
}

void el_roll_rate_set(int l, int rate)
{
    if (l >= 0 && l < NLANES && rate >= 0 && rate < ROLL_RATES)
        roll_rate[l] = (uint8_t)rate;
}

int el_roll_rate_get(int l)
{
    return l >= 0 && l < NLANES ? roll_rate[l] : 0;
}

static void lane_roll(int l)
{
    if (!roll_held[l])
        return;
    const uint16_t *period = (const uint16_t *)(uintptr_t)SYM_roll_periods;
    const uint16_t *gate_len = (const uint16_t *)(uintptr_t)SYM_roll_gates;
    uint32_t r = roll_rate[l] % ROLL_RATES;
    if (roll_phase[l] == 0) {
        el_lane_live_note(l, 1, 36, 0x7f);
        roll_on[l] = 1;
    } else if (roll_on[l] && roll_phase[l] >= gate_len[r]) {
        el_lane_live_note(l, 0, 36, 0);
        roll_on[l] = 0;
    }
    if (++roll_phase[l] >= period[r])
        roll_phase[l] = 0;
}

static void el_lanes_tick(void)
{
    const uint8_t *s = el_seq();
    int playing = s[FW_SEQ_PLAY] == 1 && s[FW_SEQ_COUNT] == TRACKS;
    for (int l = 0; l < NLANES; l++) {
        lane_t *ln = &lanes[l];
        uint8_t *vs = el_state(FIRST_LANE + l);
        lane_roll(l);
        if (!playing) {
            note_off(ln);
            ln->last_step_valid = 0;
            vs[FW_VS_FIRED] = 0;
            continue;
        }
        /* measure the lane's step length (speed, shuffle, tempo) */
        uint16_t step = U16(vs + FW_VS_STEP);
        ln->since_step++;
        if (!ln->last_step_valid || step != ln->last_step) {
            if (ln->last_step_valid && ln->since_step > 1)
                ln->step_len = ln->since_step;
            ln->since_step = 0;
            ln->last_step = step;
            ln->last_step_valid = 1;
        }
        const uint8_t *blk = PTR(U32(vs + FW_VS_BLOCK));
        if (vs[FW_VS_FIRED]) {
            vs[FW_VS_FIRED] = 0;
            /* a tie step continues the sounding note instead of retriggering */
            if (!vs[FW_VS_MUTE] && !(blk[8 * step] == STEP_TIE && ln->sounding))
                lane_fire(l, ln, vs);
        } else if (ln->sounding) {
            /* tie steps (state 3) hold the note through them, as stock skips the note-off:
             * held while this step or the next one is a tie */
            uint32_t first = blk[0x80], last = blk[0x81];        /* the LAST page sets +0x81 */
            uint32_t next = step < last ? step + 1u : first;
            int tied = blk[8 * step] == STEP_TIE || blk[8 * next] == STEP_TIE;
            uint32_t g = gate(ln, vs);
            if (!tied && g != GATE_TIE && ++ln->age >= g)
                note_off(ln);
        }
    }
}

/* replaces the sequencer tick callback (clock_state+0x3c) */
void PK_NEXT(pk_el_tick)(int);

void pk_el_tick(int beat)
{
    PK_NEXT(pk_el_tick)(beat);
    el_lanes_tick();
}
