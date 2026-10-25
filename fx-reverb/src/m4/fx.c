/* fx-reverb, M4 side: switchable delay / reverb effect, freeze, config page toggles.
 *
 * Installed as the FX processing function (fx_process_fnptr), called by the stock SAI3
 * DMA callbacks for every 16-frame block. Controls come from the effective values the
 * stock fx_update computes (after kit recall and pot catch), so kit FX saving, pot
 * catch and MIDI behave exactly as for the delay.
 *
 * Hooks (patches/fx_reverb.py):
 *   fx_process_fnptr (initial + normal-mode literal)  -> pk4_fx_process
 *   fx_update: bl HAL_GPIO_ReadPin (SHORT/LONG)       -> pk4_fx_read_switch
 *   config page table: event, render                 -> pk4_cfg_event, pk4_cfg_render
 *   boot_init: bl config_files_init                   -> pk4_boot (defaults, then load)
 *   device.json schema literals (x3)                  -> extended schema (+2 keys)
 *   _sbrk limit                                       -> heap capped below PK4_STATE
 */
#include <stdint.h>
#include "fw_m4.h"
#include "pk4_ram.h"
#include "reverb.h"

#define KEY_FX_TYPE     46          /* config row 3 step 15 */
#define KEY_SWITCH_MODE 47          /* config row 3 step 16 */
#define LED_ON          0x80

#define PK4_MAGIC       0x52565842u /* 'RVXB' */
#define XFADE           64          /* samples */
#define CLEAR_CHUNK     2048        /* int16 cleared per block during a switch-over */
#define NF              ((int)CONST_fx_block_frames)   /* frames per block */

typedef struct {
    uint32_t magic;
    uint8_t cfg_reverb;             /* device.json "fx-reverb" */
    uint8_t cfg_freeze;             /* device.json "fx-switch-freeze" */
    uint8_t switch_level;           /* physical SHORT/LONG level, last read */
    uint8_t active_reverb;          /* engine currently running */
    int32_t clear_pos;              /* >= 0 while clearing buffers for a switch-over */
    uint8_t frozen;                 /* delay looper / reverb freeze engaged */
    uint8_t pad[3];
    /* delay looper (records the delay's wet output into the reverb buffer) */
    int32_t rec_w;
    int32_t loop_start, loop_len, loop_pos;
    int32_t release;                /* crossfade counter after unfreezing */
    /* reverb */
    rv_t rv;
    int32_t pd_w;
    float pd_delay;                 /* current pre-delay, samples (slewed) */
} pk4_state_t;

_Static_assert(sizeof(pk4_state_t) <= PK4_STATE_SIZE, "state overflows its slot");
/* offsets the patch module (device.json keys) and tests rely on; see lib/fxr.py */
_Static_assert(__builtin_offsetof(pk4_state_t, cfg_reverb) == 4, "fxr.OFF_CFG_REVERB");
_Static_assert(__builtin_offsetof(pk4_state_t, cfg_freeze) == 5, "fxr.OFF_CFG_FREEZE");
_Static_assert(__builtin_offsetof(pk4_state_t, active_reverb) == 7, "fxr.OFF_ACTIVE_REVERB");
_Static_assert(__builtin_offsetof(pk4_state_t, frozen) == 12, "fxr.OFF_FROZEN");
_Static_assert(__builtin_offsetof(pk4_state_t, loop_len) == 24, "fxr.OFF_LOOP_LEN");

#define ST ((pk4_state_t *)PK4_STATE_ADDR)
#define RING ((int16_t *)PK4_REVERB_BUF)
#define PREDELAY ((int16_t *)FW_BBD_LINE)

static inline int16_t sat16(float x)
{
    return (int16_t)(x > 32767.0f ? 32767 : (x < -32768.0f ? -32768 : (int32_t)x));
}

static void zero16(int16_t *p, int32_t n)
{
    for (int32_t i = 0; i < n; i++)
        p[i] = 0;
}

/* ---- boot: defaults before device.json loads ----------------------------------- */

void pk4_boot(void)
{
    ST->magic = PK4_MAGIC;
    ST->cfg_reverb = 0;
    ST->cfg_freeze = 0;
    ST->switch_level = 0;
    ST->active_reverb = 0;
    ST->clear_pos = -1;
    ST->frozen = 0;
    ST->rec_w = 0;
    ST->release = 0;
    ST->pd_w = 0;
    ST->pd_delay = -1.0f;
    rv_init(&ST->rv, RING);         /* clears the 64 KB buffer */
    fw_config_files_init();         /* loads device.json, including our two keys */
}

/* ---- SHORT/LONG switch: in freeze mode the delay always sees LONG ---------------- */

int pk4_fx_read_switch(void *port, uint16_t pin)
{
    int level = fw_gpio_read(port, pin);
    ST->switch_level = (uint8_t)level;
    if (ST->magic == PK4_MAGIC && ST->cfg_freeze)
        return !CONST_fx_switch_short_level;    /* LONG */
    return level;
}

static int freeze_engaged(void)
{
    return ST->cfg_freeze && ST->switch_level == CONST_fx_switch_short_level;
}

/* ---- delay mode: stock BBD, plus a looper freeze --------------------------------- */

static int16_t ring_at(int32_t i)
{
    return RING[i & (RV_SIZE - 1)];
}

static void delay_block(const int16_t *in, int16_t *out)
{
    static const int16_t silence[2 * NF];
    int frz = freeze_engaged();

    if (frz && !ST->frozen) {
        /* capture: loop the last delay-time of the delay's output */
        float ticks = FW_BBD_TICKS;
        int32_t len = ticks > 0.0f ? (int32_t)((float)FW_BBD_STAGES / ticks) : 4800;
        if (len < 2 * XFADE)
            len = 2 * XFADE;
        if (len > RV_SIZE - 2 * XFADE)
            len = RV_SIZE - 2 * XFADE;
        ST->loop_len = len;
        ST->loop_start = ST->rec_w - len;
        ST->loop_pos = 0;
        ST->frozen = 1;
    } else if (!frz && ST->frozen) {
        ST->frozen = 0;
        ST->release = XFADE;
    }

    /* the BBD keeps running (input muted while frozen) so release continues naturally */
    fw_fx_bbd_process(frz ? silence : in, out);

    for (int f = 0; f < NF; f++) {
        int16_t bbd = out[2 * f];
        if (!ST->frozen) {
            RING[ST->rec_w & (RV_SIZE - 1)] = bbd;
            ST->rec_w++;
        }
        if (ST->frozen || ST->release > 0) {
            int32_t p = ST->loop_pos, len = ST->loop_len;
            float loop = ring_at(ST->loop_start + p);
            if (p >= len - XFADE) {            /* seam: fade into the audio before the start */
                float a = (float)(len - p) / XFADE;
                loop = loop * a + (float)ring_at(ST->loop_start + p - len) * (1.0f - a);
            }
            if (++ST->loop_pos >= len)
                ST->loop_pos = 0;
            if (ST->frozen) {
                out[2 * f] = sat16(loop);
            } else {                            /* release: crossfade loop -> live delay */
                float a = (float)ST->release / XFADE;
                out[2 * f] = sat16(loop * a + (float)bbd * (1.0f - a));
                ST->release--;
            }
        }
    }
}

/* ---- reverb mode ------------------------------------------------------------------ */

static float clampf(float x, float lo, float hi)
{
    return x < lo ? lo : (x > hi ? hi : x);
}

static void reverb_params(rv_params_t *p, float *pd_target)
{
    float fb = clampf(FW_FX_FEEDBACK / 1.02f, 0.0f, 1.0f);
    float rate = clampf((FW_FX_LFO_RATE * 3000.0f - 0.1f) / 20.0f, 0.0f, 1.0f);
    float depth = clampf(FW_FX_LFO_DEPTH / 0.3f, 0.0f, 1.0f);
    int room = !ST->cfg_freeze && FW_FX_SWITCH == CONST_fx_switch_short_level;

    p->input_gain = 0.2f;
    p->time = room ? 0.30f + 0.55f * fb : 0.35f + 0.63f * fb;   /* full right: very long */
    p->size = room ? 0.6f : 1.0f;
    p->diffusion = 0.40f + 0.35f * rate;                        /* LFO RATE knob */
    p->lp = 0.7f;                                               /* fixed damping (Rings) */
    p->hp = 0.0156f;                                            /* ~120 Hz, 2 poles */
    p->mod_depth = 2.0f * depth;                                /* MOD DEPTH knob */
    p->lfo_freq[0] = (0.5f + depth) * 0.5f / 48000.0f;
    p->lfo_freq[1] = (0.5f + depth) * 0.3f / 48000.0f;

    if (freeze_engaged()) {                                     /* as Elements */
        p->input_gain = 0.0f;
        p->time = 1.0f;
        p->lp = 1.0f;
    }

    /* pre-delay: TIME, or a tempo division when BBD sync is on */
    float seconds = FW_FX_TIME * 0.170f;
    if (FW_SYNC_ON && FW_CLOCK_BPM > 1.0f) {
        int idx = (int)(FW_FX_TIME * 16.99f);
        seconds = 60.0f / FW_CLOCK_BPM * FW_SYNC_TABLE[idx];
    }
    *pd_target = clampf(seconds * 48000.0f, 0.0f, (float)(PK4_PREDELAY_LEN - 2));
}

static void reverb_block(const int16_t *in, int16_t *out)
{
    float x[NF], y[NF], pd_target;
    rv_params_t p;
    reverb_params(&p, &pd_target);
    if (ST->pd_delay < 0.0f)                    /* engine just started: no glide from 0 */
        ST->pd_delay = pd_target;

    for (int f = 0; f < NF; f++) {
        /* pre-delay line (int16, in the BBD's memory); delay glides toward the target */
        PREDELAY[ST->pd_w] = in[2 * f];
        float d = ST->pd_delay;
        d += clampf(pd_target - d, -0.5f, 0.5f);
        ST->pd_delay = d;
        float rp = (float)ST->pd_w - d;
        if (rp < 0.0f)
            rp += PK4_PREDELAY_LEN;
        int32_t i0 = (int32_t)rp;
        float fr = rp - (float)i0;
        int32_t i1 = i0 + 1 >= PK4_PREDELAY_LEN ? 0 : i0 + 1;
        x[f] = ((float)PREDELAY[i0] * (1.0f - fr) + (float)PREDELAY[i1] * fr) * (1.0f / 32768.0f);
        if (++ST->pd_w >= PK4_PREDELAY_LEN)
            ST->pd_w = 0;
    }
    rv_process(&ST->rv, &p, x, y, NF);
    for (int f = 0; f < NF; f++)
        out[2 * f] = sat16(y[f] * 32768.0f);
}

/* ---- the processing function ------------------------------------------------------ */

void pk4_fx_process(const int16_t *in, int16_t *out)
{
    if (ST->magic != PK4_MAGIC) {                   /* not booted through our hook */
        fw_fx_bbd_process(in, out);
        return;
    }
    if (ST->cfg_reverb != ST->active_reverb && ST->clear_pos < 0)
        ST->clear_pos = 0;
    if (ST->clear_pos >= 0) {
        /* switch-over, silent meanwhile: clear the BBD line (16 KB = PK4_PREDELAY_LEN int16;
         * the delay's history, or the reverb's pre-delay) and, going to reverb, the
         * reverb lines too. Cleared as one virtual range, a chunk per block. */
        int32_t len = PK4_PREDELAY_LEN + (ST->cfg_reverb ? RV_SIZE : 0);
        int32_t pos = ST->clear_pos;
        int32_t n = len - pos < CLEAR_CHUNK ? len - pos : CLEAR_CHUNK;
        if (pos < PK4_PREDELAY_LEN) {
            if (n > PK4_PREDELAY_LEN - pos)
                n = PK4_PREDELAY_LEN - pos;
            zero16(PREDELAY + pos, n);
        } else {
            zero16(RING + (pos - PK4_PREDELAY_LEN), n);
        }
        ST->clear_pos += n;
        if (ST->clear_pos >= len) {
            ST->clear_pos = -1;
            ST->active_reverb = ST->cfg_reverb;
            ST->frozen = 0;
            ST->release = 0;
            ST->pd_delay = -1.0f;            /* reverb: snap to the target on its first block */
            if (ST->active_reverb) {        /* lines already zeroed above: reset state only */
                ST->rv.write_ptr = 0;
                ST->rv.lp1 = ST->rv.lp2 = ST->rv.hp1 = ST->rv.hp2 = 0.0f;
                ST->pd_w = 0;
            }
        }
        for (int i = 0; i < 2 * NF; i++)
            out[i] = 0;
        return;
    }
    if (ST->active_reverb)
        reverb_block(in, out);
    else
        delay_block(in, out);
}

/* ---- config page: row 3 steps 15/16 ------------------------------------------------ */

int pk4_cfg_event(const uint8_t *evt)
{
    if (evt[1] == CONST_cfg_key_event && (evt[0] == KEY_FX_TYPE || evt[0] == KEY_SWITCH_MODE)) {
        if (evt[0] == KEY_FX_TYPE)
            ST->cfg_reverb ^= 1;
        else
            ST->cfg_freeze ^= 1;
        FW_CFG_DIRTY = 1;                           /* saved to device.json on page exit */
        return 1;
    }
    return fw_cfg_event(evt);
}

void pk4_cfg_render(void *a, void *b, void *c, void *d)
{
    fw_cfg_render(a, b, c, d);
    fw_set_led(KEY_FX_TYPE, ST->cfg_reverb ? LED_ON : 0);
    fw_set_led(KEY_SWITCH_MODE, ST->cfg_freeze ? LED_ON : 0);
}
