/* per-track-lfo: LFO groups.
 *
 * Stock has one LFO (the object at SYM_mod_lfo), computed once per block by the stream-1
 * sender and applied to every voice through its MOD page depths. Here every voice is in
 * exactly one LFO group: at power-on all four are in the main group (the stock LFO,
 * saved with the kit), so the unit behaves as stock. Hold trigger keys and turn RATE,
 * WAVE or MOD LVL (or press SYNC): the held voices leave their groups and form one of
 * their own, starting as a copy of the first held voice's LFO, and that group becomes the
 * selection. With no trigger key held the knobs edit the selection (the stock LFO while
 * it is the main group). RESET held + turning RATE merges everything back into the main
 * group with the selection's settings; clearing a track, its automation or a pattern
 * merges back to the main group as it is. Groups live until then or power-off.
 * Trigger LEDs, when groups exist: dim for a voice in a group of its own, pulsing with the
 * LFO for the selection (hits and mutes show full as stock).
 * The MIDI-only lanes of eight-lanes have no LFO: the sender only modulates voices 1-4. */
#include <stdint.h>
#include "pk_host.h"

#define VOICES          4
#define MAIN            0           /* group 0: the stock LFO; 1-4: lfo[g - 1] */
#define THRESH          0.02f       /* knob travel (0..1) that counts as a turn */
#define CATCH           0.02f       /* pot catch: the knob this close to the value takes it */
#define LED_DIM         0x10

#define U8(p)           (*(volatile uint8_t *)(p))
#define U32(p)          (*(volatile uint32_t *)(p))
#define F32(p)          (*(volatile float *)(p))

typedef void (*setter_t)(float value, uint8_t *lfo);
#define fw_lfo_update   FW_CALL(SYM_lfo_update, float (*)(uint8_t *lfo))
#define fw_lfo_sync_tick FW_CALL(SYM_lfo_sync_tick, void (*)(float tempo, uint8_t *lfo))
#define fw_lfo_reset    FW_CALL(SYM_lfo_reset, void (*)(uint8_t *lfo))
#define fw_lfo_sync_toggle FW_CALL(SYM_lfo_sync_toggle, void (*)(uint8_t *lfo))

static const uint32_t setters[3] = {SYM_lfo_set_rate | 1u, SYM_lfo_set_wave | 1u, SYM_lfo_set_level | 1u};

static uint8_t lfo[VOICES][FW_LFO_SIZE] __attribute__((aligned(4)));
static uint8_t wavetable[VOICES][FW_LFO_WAVETABLE_SIZE] __attribute__((aligned(4)));
static float knob[VOICES][3];       /* each group LFO's knob values (rate also for SYNC) */
static float out[VOICES];           /* what each voice gets this block (output x level) */
static uint8_t group[VOICES];       /* each voice's group */
static uint8_t sel;                 /* the group the knobs edit with no trigger key held */
static uint8_t armed;               /* bit i: knob i has picked up the selection's value */

static float anchor[3];             /* knob value when the held keys last changed */
static uint8_t anchor_keys[3];      /* held trigger keys (bits), RESET (bit 7) at that time */
static uint8_t turning;             /* bit i: knob i passed THRESH since */

static uint8_t *main_lfo(void)
{
    return (uint8_t *)(uintptr_t)SYM_mod_lfo;
}

static uint8_t *obj(int g)
{
    return g == MAIN ? main_lfo() : lfo[g - 1];
}

static void copy(uint8_t *dst, const uint8_t *src, int n)
{
    for (int i = 0; i < n; i++)
        dst[i] = src[i];
}

static void set(int i, float value, uint8_t *l)
{
    ((setter_t)setters[i])(value, l);
}

static int held_triggers(void)
{
    int m = 0;
    for (int v = 0; v < VOICES; v++)
        if (fw_key_held(FW_KEY_TRIG(v)))
            m |= 1 << v;
    return m;
}

static int members(int g)
{
    int m = 0;
    for (int v = 0; v < VOICES; v++)
        if (group[v] == g)
            m |= 1 << v;
    return m;
}

static int grouped(void)
{
    return members(MAIN) != (1 << VOICES) - 1;
}

/* a group's knob values: the kit's stored ones for the main group */
static float knob_of(int g, int i)
{
    if (g != MAIN)
        return knob[g - 1][i];
    uint8_t *stored = (uint8_t *)U32(main_lfo() + FW_LFO_STORED);
    return stored ? F32(stored + 4 * i) : 0.5f;
}

static void select(int g)
{
    if (sel != g)
        armed = 0;
    sel = (uint8_t)g;
}

/* the held voices `keys` as one group: an existing group that is exactly them, else a
 * group of their own, starting as a copy of the first held voice's LFO (phase included,
 * own sample-and-hold value, no kit storage or pot catch) */
static int take(int keys)
{
    for (int g = 1; g <= VOICES; g++)
        if (members(g) == keys)
            return g;
    int first = 0;
    while (!(keys >> first & 1))
        first++;
    int src = group[first];
    int g = 0;
    if (src != MAIN && !(members(src) & ~keys))
        g = src;                            /* their group loses only them: keep it */
    for (int k = 1; k <= VOICES && !g; k++)
        if (!(members(k) & ~keys))
            g = k;                          /* free once they leave */
    if (g != src) {
        uint8_t *dst = lfo[g - 1];
        copy(dst, obj(src), FW_LFO_SIZE);
        copy(wavetable[g - 1], (uint8_t *)U32(obj(src) + FW_LFO_WAVETABLE), FW_LFO_WAVETABLE_SIZE);
        U32(dst + FW_LFO_WAVETABLE) = (uint32_t)(uintptr_t)wavetable[g - 1];
        U32(dst + FW_LFO_STORED) = 0;
        U8(dst + FW_LFO_CATCH) = 0;
        for (int i = 0; i < 3; i++)
            knob[g - 1][i] = knob_of(src, i);
    }
    for (int v = 0; v < VOICES; v++)
        if (keys >> v & 1)
            group[v] = (uint8_t)g;
    return g;
}

/* everyone back in the main group; with `settings`, it takes the selection's */
static void merge(int settings)
{
    uint8_t *m = main_lfo();
    if (settings && sel != MAIN) {
        U8(m + FW_LFO_CATCH) = 0;
        for (int i = 0; i < 3; i++)
            set(i, knob[sel - 1][i], m);
        if (U8(m + FW_LFO_SYNC) != U8(lfo[sel - 1] + FW_LFO_SYNC))
            fw_lfo_sync_toggle(m);
        set(0, knob[sel - 1][0], m);
        U8(m + FW_LFO_CATCH) = 7;           /* the knobs take it again as stock pot catch does */
    }
    for (int v = 0; v < VOICES; v++)
        group[v] = MAIN;
    select(MAIN);
}

/* the knob poll calls RATE, WAVE, MOD LVL setters with the main LFO every pass */
static void knob_poll(int i, float value, uint8_t *main, setter_t next)
{
    int keys = held_triggers();
    int reset = fw_key_held(FW_KEY_RESET) ? 0x80 : 0;
    if ((keys | reset) != anchor_keys[i]) {
        anchor_keys[i] = (uint8_t)(keys | reset);
        anchor[i] = value;
        turning &= ~(1 << i);
    }
    float d = value - anchor[i];
    if (d < 0)
        d = -d;
    if (d > THRESH)
        turning |= 1 << i;
    if (reset && i == 0 && (turning & 1) && grouped()) {
        merge(1);                           /* RESET + RATE: one LFO, the selection's */
        return;
    }
    if (keys && !reset) {
        if (turning & (1 << i)) {
            int g = take(keys);
            select(g);
            armed |= 1 << i;
            knob[g - 1][i] = value;
            set(i, value, lfo[g - 1]);
        }
        U8(main + FW_LFO_CATCH) |= 1 << i;   /* the main group keeps its value */
        return;
    }
    if (sel == MAIN) {
        next(value, main);                  /* stock */
        return;
    }
    /* the selection: picks the knob up (pot catch: once the knob reaches its value; else
     * once the knob moves), then follows it */
    if (!(armed & (1 << i))) {
        float c = value - knob[sel - 1][i];
        if (c < 0)
            c = -c;
        int catch_on = FW_U8(SYM_device_config + FW_DC_POT_CATCH);
        if (catch_on ? c < CATCH : (turning & (1 << i)) != 0)
            armed |= 1 << i;
    }
    if (armed & (1 << i)) {
        knob[sel - 1][i] = value;
        set(i, value, lfo[sel - 1]);
    }
    U8(main + FW_LFO_CATCH) |= 1 << i;
}

void PK_NEXT(pk_lf_rate)(float value, uint8_t *lfo);
void PK_NEXT(pk_lf_wave)(float value, uint8_t *lfo);
void PK_NEXT(pk_lf_level)(float value, uint8_t *lfo);
void pk_lf_rate(float value, uint8_t *main) { knob_poll(0, value, main, PK_NEXT(pk_lf_rate)); }
void pk_lf_wave(float value, uint8_t *main) { knob_poll(1, value, main, PK_NEXT(pk_lf_wave)); }
void pk_lf_level(float value, uint8_t *main) { knob_poll(2, value, main, PK_NEXT(pk_lf_level)); }

/* once per block: every group's LFO steps; out[v] is what voice v gets */
float PK_NEXT(pk_lf_update)(uint8_t *lfo);

float pk_lf_update(uint8_t *main)
{
    float r = PK_NEXT(pk_lf_update)(main);
    float val[VOICES + 1];
    val[MAIN] = r;
    for (int g = 1; g <= VOICES; g++)
        val[g] = members(g) ? fw_lfo_update(lfo[g - 1]) : 0.0f;
    for (int v = 0; v < VOICES; v++)
        out[v] = val[group[v]];
    return r;
}

void PK_NEXT(pk_lf_sync_tick)(float tempo, uint8_t *lfo);

void pk_lf_sync_tick(float tempo, uint8_t *main)
{
    PK_NEXT(pk_lf_sync_tick)(tempo, main);
    for (int g = 1; g <= VOICES; g++)
        if (members(g))
            fw_lfo_sync_tick(tempo, lfo[g - 1]);
}

float pk_lf_out_of(int v)
{
    return out[v & 3];
}

/* the sender's per-voice loop keeps the LFO output in s17: voice v's before its body,
 * then on to voice_state (PK_NEXT) with r0 = v */
__attribute__((naked)) void pk_lf_voice(void)
{
    __asm volatile(
        "push {r0, lr}\n"
        "bl pk_lf_out_of\n"
        "vmov.f32 s17, s0\n"
        "pop {r0, lr}\n"
        "b.w pk_next_pk_lf_voice\n");
}

/* SYNC: with trigger keys held, those voices' group (formed as by a knob) and it becomes
 * the selection; else the selection's (the stock LFO's while that is the main group) */
void PK_NEXT(pk_lf_sync_key)(uint8_t *lfo);

void pk_lf_sync_key(uint8_t *main)
{
    int keys = held_triggers();
    if (keys) {
        select(take(keys));
    } else if (sel == MAIN) {
        PK_NEXT(pk_lf_sync_key)(main);
        return;
    }
    uint8_t *l = lfo[sel - 1];
    U8(l + FW_LFO_SYNC) ^= 1;
    set(0, knob[sel - 1][0], l);            /* rate or sync multiplier from its RATE */
}

/* transport restarts (and kit load with SYNC) restart every LFO */
void PK_NEXT(pk_lf_reset)(uint8_t *lfo);

void pk_lf_reset(uint8_t *main)
{
    PK_NEXT(pk_lf_reset)(main);
    for (int g = 1; g <= VOICES; g++)
        if (members(g))
            fw_lfo_reset(lfo[g - 1]);
}

/* a track, its automation or a pattern cleared (host events): the main group again */
void pk_lf_rejoin(void)
{
    merge(0);
}

/* LFO and SYNC LEDs: the first held trigger key's group, else the selection's */
static uint8_t *shown(void)
{
    int keys = held_triggers();
    for (int v = 0; v < VOICES; v++)
        if (keys >> v & 1)
            return obj(group[v]);
    return obj(sel);
}

float PK_NEXT(pk_lf_led)(uint8_t *lfo);
int PK_NEXT(pk_lf_sync_led)(uint8_t *lfo);

float pk_lf_led(uint8_t *main)
{
    (void)main;
    return PK_NEXT(pk_lf_led)(shown());
}

int pk_lf_sync_led(uint8_t *main)
{
    (void)main;
    return PK_NEXT(pk_lf_sync_led)(shown());
}

/* trigger LEDs (ui_update; voice v = 0x4f - id): where stock leaves one off and groups
 * exist, dim for a voice in a group of its own, pulsing with the LFO for the selection */
void PK_NEXT(pk_lf_trig_led)(int id, int level);

void pk_lf_trig_led(int id, int level)
{
    int v = 0x4f - id;
    if (level == 0 && v >= 0 && v < VOICES && grouped() && group[v] != MAIN) {
        if (group[v] == sel) {
            int x = (int)F32(lfo[sel - 1] + FW_LFO_OUT) + 0x7fff;     /* 0..0xfffe */
            level = LED_DIM + (x >> 10);                              /* 0x10..0x4f */
        } else {
            level = LED_DIM;
        }
    }
    PK_NEXT(pk_lf_trig_led)(id, level);
}
