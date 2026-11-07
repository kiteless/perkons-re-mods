/* STEP SAMPLER, M4 side: the sample page, and the step edits that carry a step's sample.
 *
 * Sample page (a page of its own, the M4 host's pages): on the main page, hold one or more
 * steps on tracks whose voice runs STEP SAMPLER and press SHUFFLE. The 64 step keys are
 * samples 1-64; a loaded sample is dimly lit, the held steps' sample brightly. A step
 * chooses: every held step (on those tracks) plays that sample, it becomes the track's
 * sample (what the track's other steps, and the trigger keys, play), and it sounds.
 * SHUFFLE as the stock page buttons: a tap leaves the page open (SHUFFLE again closes it),
 * held over 0.4 s it closes on release. Other page buttons and the trigger keys work as
 * usual. On other tracks step + SHUFFLE is stock (the shuffle page).
 *
 * Step edits (as stock does them to the steps' locks): CLEAR clears a step's sample, the
 * copy (REC with a step held) and paste (SHIFT with steps held) carry it. */
#include <stdint.h>
#include "pk_host.h"
#include "pk_vm.h"
#include "ss_shared.h"
#include "pk_ss_engine.h"

#define TRACKS          4
#define STEPS           16
#define LED_ON          0x80
#define LED_DIM         0x10
#define HOLD_MS         400                 /* stock: a page button held longer is momentary */
#define NONE            0xffffffffu

#define fw_held_first   FW_CALL(SYM_held_first, void (*)(void *it))
#define fw_held_next    FW_CALL(SYM_held_next, uint32_t (*)(void *it))   /* row << 4 | col, NONE at the end */
#define fw_key_held_ms  FW_CALL(SYM_key_held_ms, uint32_t (*)(int key))

extern uint8_t pk_ss_kit_sample[64][TRACKS];
extern uint8_t pk_ss_step_sample[64][TRACKS][STEPS];
int pk_ss_pattern(void);
int pk_ss_track_sample(int v);
extern uint8_t pk_el_page __attribute__((weak));    /* eight-lanes: 1 = the main page shows lanes 5-8 */

static uint32_t held_mask[2];               /* the steps held when the page opened (key ids) */
static uint8_t sounding;                    /* the voice auditioning a sample, + 1 (0: none) */
static uint8_t clip[TRACKS], clip_valid[TRACKS];   /* the copied step's sample, per row */

static int ours(int track)
{
    return track >= 0 && track < TRACKS && pk_vm_engine(track) == PK_SS_ENGINE;
}

static int lanes_page(void)
{
    return &pk_el_page && pk_el_page;
}

/* the held steps on STEP SAMPLER tracks, as key ids into mask[2]; their count */
static int held_ours(uint32_t mask[2])
{
    uint8_t it[8];
    int n = 0;
    mask[0] = mask[1] = 0;
    if (lanes_page() || !fw_steps_held())
        return 0;
    fw_held_first(it);
    for (uint32_t x; (x = fw_held_next(it)) != NONE;) {
        int row = (int)(x >> 4) & 0xf, col = (int)x & 0xf, key = row * STEPS + col;
        if (ours(row) && key < 64) {
            mask[key >> 5] |= 1u << (key & 31);
            n++;
        }
    }
    return n;
}

static uint8_t *step_choice(int key)
{
    int pat = pk_ss_pattern();
    return pat >= 0 ? &pk_ss_step_sample[pat][key / STEPS][key % STEPS] : 0;
}

static void set_steps(const uint32_t mask[2], int choice)        /* choice: 0 = the track's, else n + 1 */
{
    for (int key = 0; key < 64; key++)
        if (mask[key >> 5] >> (key & 31) & 1) {
            uint8_t *c = step_choice(key);
            if (c)
                *c = (uint8_t)choice;
        }
}

/* ---- the global key handler (chained): the page's way in, and the step edits ----------- */

int PK_NEXT(pk_ss_key_event)(const uint8_t *evt);

int pk_ss_key_event(const uint8_t *evt)
{
    if (evt[1] == FW_EV_DOWN && fw_get_mode() == FW_MODE_MAIN) {
        uint32_t m[2];
        int key = evt[0];
        if (key == FW_KEY_SHUFFLE && held_ours(m)) {
            held_mask[0] = m[0];
            held_mask[1] = m[1];
            fw_set_mode(PK_PAGE_SAMPLES);
            return 1;
        }
        if (key < 64 && fw_key_held(FW_KEY_CLEAR) && !lanes_page() && ours(key / STEPS)) {
            uint8_t *c = step_choice(key);              /* CLEAR + step: the step's sample too */
            if (c)
                *c = 0;
        } else if (key == FW_KEY_CLEAR && held_ours(m)) {
            set_steps(m, 0);                            /* steps held + CLEAR */
        } else if (key == FW_KEY_REC && held_ours(m)) {
            for (int k = 0; k < 64; k++)                /* copy: the first held step, per row */
                if (m[k >> 5] >> (k & 31) & 1) {
                    uint8_t *c = step_choice(k);
                    clip[k / STEPS] = c ? *c : 0;
                    clip_valid[k / STEPS] = 1;
                    break;
                }
        } else if (key == FW_KEY_SHIFT && held_ours(m)) {
            for (int k = 0; k < 64; k++)                /* paste: into the held steps of a copied row */
                if (m[k >> 5] >> (k & 31) & 1 && clip_valid[k / STEPS]) {
                    uint8_t *c = step_choice(k);
                    if (c)
                        *c = clip[k / STEPS];
                }
        }
    }
    return PK_NEXT(pk_ss_key_event)(evt);
}

/* ---- the sample page ------------------------------------------------------------------- */

/* the sample the page shows as chosen: the first held step's, else its track's */
static int shown(void)
{
    for (int key = 0; key < 64; key++)
        if (held_mask[key >> 5] >> (key & 31) & 1) {
            uint8_t *c = step_choice(key);
            return c && *c ? *c - 1 : pk_ss_track_sample(key / STEPS);
        }
    return -1;
}

static int row_held(int t)
{
    return (held_mask[t >> 1] >> ((t & 1) * STEPS) & 0xffffu) != 0;
}

static int first_track(void)
{
    for (int key = 0; key < 64; key++)
        if (held_mask[key >> 5] >> (key & 31) & 1)
            return key / STEPS;
    return -1;
}

int pk_ss_page_key(const uint8_t *evt)
{
    int key = evt[0];
    if (key < 64) {
        if (evt[1] == FW_EV_DOWN) {
            set_steps(held_mask, key + 1);
            int kit = FW_U16(SYM_current_kit);
            for (int t = 0; t < TRACKS; t++)
                if (row_held(t) && kit >= 0 && kit < 64)
                    pk_ss_kit_sample[kit][t] = (uint8_t)key;     /* the track's sample, too */
            int v = first_track();                      /* hear it: the track's voice plays it */
            if (v >= 0) {
                fw_voice_play(v, 1, 36, 127);
                sounding = (uint8_t)(v + 1);
            }
        } else if (evt[1] == FW_EV_UP && sounding) {
            fw_voice_play(sounding - 1, 0, 36, 0);
            sounding = 0;
        }
        return 1;                                       /* the held steps' releases too: no toggle */
    }
    if (key == FW_KEY_SHUFFLE) {
        if (evt[1] == FW_EV_DOWN || fw_key_held_ms(FW_KEY_SHUFFLE) > HOLD_MS)
            fw_set_mode(FW_MODE_MAIN);                  /* a tap again closes; a long hold, on release */
        return 1;
    }
    return 0;                                           /* page buttons, trigger keys: as stock */
}

void pk_ss_page_draw(void)
{
    int sel = shown();
    for (int i = 0; i < 64; i++)
        fw_set_led(i, i == sel ? LED_ON : SS->magic == SS_MAGIC && SS->sample[i].frames ? LED_DIM : 0);
}

void pk_ss_page_leave(void)
{
    if (sounding) {
        fw_voice_play(sounding - 1, 0, 36, 0);
        sounding = 0;
    }
}
