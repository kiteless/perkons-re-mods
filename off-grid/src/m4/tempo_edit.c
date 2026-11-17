/* off-grid TEMPO editing: hold one step and turn TEMPO to play that step early or late.
 *
 * On (config row 3 step 12), in the main page, with exactly one step held:
 * - TEMPO no longer changes the tempo.
 * - Past a 20 degree dead zone, each further 10 degrees moves the step one division:
 *   1/6 of a step (4 of its 24 ticks), up to 5 divisions earlier or later.
 * - The held step's row shows the division LEDs: +-5 around the step dim, the step's
 *   current position bright, everything else in the row off.
 * On release, the tempo knob's catch is armed (as the tempo page does), so TEMPO takes
 * over again only when it gets back near the tempo. It never jumps.
 *
 * The offset is stored in the stock per-step delay (FW_STEP_DELAY), a signed % of a step.
 * The stock player fires a step with a negative delay early, during the step before it
 * (FUN_0810d248). So the timing is saved with the pattern and moves with rotate, copy and
 * clear, and the official firmware plays it the same way. SHUFFLE writes the same field:
 * setting a track's shuffle again replaces its microtiming.
 *
 * Only steps that are on take microtiming, and a step turned off goes back to the track's
 * shuffle grid. A step can't be moved onto or past the step played before or after it: the
 * stock player would drop one of the two hits. */
#include <stdint.h>
#include "pk_host.h"
#include "fw_m4_seq.h"

#define fw_held_first   FW_CALL(SYM_held_first, void (*)(uint32_t *it))
#define fw_held_next    FW_CALL(SYM_held_next, int (*)(uint32_t *it))   /* key, -1 at the end */

/* TEMPO's knob_value (0..1) per degree. shortcut: assumes a 300 degree pot, so measure the
 * real travel on hardware and change DEG if the divisions feel too wide or too narrow. */
#define DEG             (1.0f / 300.0f)
#define NOISE           0.02f           /* knob travel that opens the view (as per-track-lfo's THRESH) */
#define DEAD            (20 * DEG)
#define DIV             (10 * DEG)
#define MAX_DIV         5
#define STEP_TICKS      24              /* FW_CLK_STEP_TICKS's value; a division is 4 */
#define LED_RANGE       0x08            /* stock: an unaccented step */
#define LED_POS         0xff            /* stock: the playhead */

PK_AXI uint8_t pk_cfg_microtiming;      /* system/mods.json "microtiming" */
PK_AXI static int8_t held = -1;         /* the held step's key while TEMPO is ours, else -1 */
PK_AXI static uint8_t shown;            /* TEMPO moved this hold: the view is up */
PK_AXI static int8_t base;              /* the step's divisions when the hold began */
PK_AXI static float anchor;             /* TEMPO's position when the hold began */
PK_AXI static float last;               /* TEMPO's position at the last UI update */
PK_AXI static float turned;             /* travel since the hold began, kept inside the range */

/* the travel that puts the step k divisions from where the hold began: the middle of that
 * division's 10 degrees (0: the hold's start) */
static float travel(int k)
{
    if (k == 0)
        return 0;
    float t = DEAD + ((k < 0 ? -k : k) - 0.5f) * DIV;
    return k < 0 ? -t : t;
}

/* divisions <-> the step's delay (% of a step). 24 ticks per step, so n divisions is 4n ticks:
 * the player's delay * 24 / 100 (truncated) lands on 4n for these percentages. */
static int div_to_delay(int n)
{
    int a = n < 0 ? -n : n;
    a = (50 * a + 2) / 3;                       /* 17, 34, 50, 67, 84 */
    return n < 0 ? -a : a;
}

static int delay_to_div(int d)
{
    int a = d < 0 ? -d : d;
    a = (6 * a + 50) / 100;                     /* nearest division (shuffle's values too) */
    return d < 0 ? -a : a;
}

static uint8_t *block(int key)
{
    return (uint8_t *)(uintptr_t)FW_U32(fw_voice_state(key >> 4) + FW_VS_BLOCK);
}

static volatile int16_t *step_delay(int key)
{
    return (volatile int16_t *)(block(key) + (key & 15) * FW_STEP_SIZE + FW_STEP_DELAY);
}

static int step_on(int key)
{
    return block(key)[(key & 15) * FW_STEP_SIZE] != 0;
}

/* the divisions the step can take without reaching the step played before or after it.
 * shortcut: forward play mode only, the other modes play in another order and aren't
 * limited; upgrade if lost hits are reported there. */
static void limits(int key, int *lo, int *hi)
{
    uint8_t *blk = block(key);
    int first = blk[FW_BLK_FIRST], last = blk[FW_BLK_LAST], col = key & 15, row = key & 0x30;
    *lo = -MAX_DIV;
    *hi = MAX_DIV;
    if (blk[FW_BLK_PLAY_MODE] != 0 || col < first || col > last || first == last)
        return;
    int prev = row | (col == first ? last : col - 1), next = row | (col == last ? first : col + 1);
    if (step_on(prev))                          /* the player's ticks: delay * 24 / 100 */
        while (4 * *lo <= *step_delay(prev) * STEP_TICKS / 100 - STEP_TICKS)
            ++*lo;
    if (step_on(next))
        while (4 * *hi >= *step_delay(next) * STEP_TICKS / 100 + STEP_TICKS)
            --*hi;
}

static int clamp(int n, int lo, int hi)
{
    return n < lo ? lo : n > hi ? hi : n;
}

/* the one step held in the main page, if it's on; else -1 */
static int one_step_held(void)
{
    if (!pk_cfg_microtiming || fw_get_mode() != FW_MODE_MAIN || fw_steps_held() != 1)
        return -1;
    uint32_t it;
    fw_held_first(&it);
    int key = fw_held_next(&it);
    return key >= 0 && key < 0x40 && step_on(key) ? key : -1;
}

/* ui_update: TEMPO's position and moved flag, into tempo_knob */
void PK_NEXT(pk_og_tempo)(float pos, int moved);
void pk_og_tempo(float pos, int moved)
{
    int key = one_step_held();
    if (key < 0) {
        if (held >= 0 && shown)                 /* catch: no jump to where TEMPO is now */
            fw_tempo_set(FW_F32(SYM_tempo_state + FW_TEMPO_BPM));
        held = -1;
        shown = 0;
        PK_NEXT(pk_og_tempo)(pos, moved);
        return;
    }
    if (key != held) {
        held = (int8_t)key;
        shown = 0;
        anchor = last = pos;
        turned = 0;
        base = (int8_t)delay_to_div(*step_delay(key));
    }
    float a = pos - anchor;
    if (a >= NOISE || -a >= NOISE)
        shown = 1;
    /* travel counts from the hold's start but stops at the range's ends, so turning past an
     * end (or the pot's) and back moves the step again at once, wherever the pot started */
    turned += pos - last;
    last = pos;
    if (shown) {
        int lo, hi;
        limits(key, &lo, &hi);
        float min = travel(clamp(base, lo, hi) > lo ? lo - base : 0);
        float max = travel(clamp(base, lo, hi) < hi ? hi - base : 0);
        turned = turned < min ? min : turned > max ? max : turned;
        float d = turned;
        a = d < 0 ? -d : d;
        int n = a < DEAD ? base : base + (d < 0 ? -1 : 1) * (1 + (int)((a - DEAD) / DIV));
        n = clamp(n, lo, hi);
        if (n != delay_to_div(*step_delay(key)))    /* untouched steps keep shuffle's value */
            *step_delay(key) = (int16_t)div_to_delay(n);
    }
    PK_NEXT(pk_og_tempo)(pos, 0);               /* the tempo stays as it is */
}

/* main page LEDs: stock, then the held step's row as the division view */
void PK_NEXT(pk_og_render)(void);
void pk_og_render(void)
{
    PK_NEXT(pk_og_render)();
    if (held < 0 || !shown || one_step_held() != held)
        return;
    int row = held & 0x30, col = held & 15;
    int lo, hi;
    limits(held, &lo, &hi);
    int n = clamp(delay_to_div(*step_delay(held)), lo, hi);
    for (int i = 0; i < 16; i++)
        fw_set_led(row + i, 0);
    for (int i = lo; i <= hi; i++)
        fw_set_led(row + ((col + i) & 15), LED_RANGE);    /* wraps round the row, as the loop does */
    fw_set_led(row + ((col + n) & 15), LED_POS);
}

/* the global key handler (chained): a step that a step key left off goes back to the
 * track's shuffle grid (set_shuffle: odd steps the track's shuffle, even steps 0), so
 * microtiming doesn't outlive the step */
int PK_NEXT(pk_og_key_event)(const uint8_t *evt);
int pk_og_key_event(const uint8_t *evt)
{
    int key = evt[0];
    int r = PK_NEXT(pk_og_key_event)(evt);
    if (pk_cfg_microtiming && key < 0x40 && !step_on(key))
        *step_delay(key) = key & 1 ? block(key)[FW_BLK_SHUFFLE] : 0;
    return r;
}
