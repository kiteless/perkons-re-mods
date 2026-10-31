/* fx-reverb, M4 side: a reverb in place of the BBD delay, switchable in config.
 *
 * Built by the M4 host (tools/perkons/m4host.py in the framework). It provides the FX
 * engine, pk_fx_engine: the delay (pk_fx_delay: stock BBD, or fx-freeze's looper) or the
 * reverb, with a silent switch-over that clears the lines in between. Controls come from
 * the effective values the stock fx_update computes (after kit recall and pot catch), so
 * kit FX saving, pot catch and MIDI behave exactly as for the delay.
 *
 * The reverb's tank runs at 24 kHz (half the line memory: the shared FX buffer is 32 KB):
 * the pre-delay runs at 48 kHz, then a halfband filter decimates into the tank and
 * interpolates out of it.
 *
 * The LFO LED follows the reverb's modulation LFO while the reverb runs.
 *
 * Freeze is a separate mod (fx-freeze); the reverb follows pk_fx_freeze_engaged() and
 * pk_fx_switch_is_freeze(), whose weak defaults (no fx-freeze) are 0.
 */
#include <stdint.h>
#include "pk_host.h"
#include "reverb.h"

#define NF              PK_FX_NF
#define CLEAR_CHUNK     2048        /* int16 cleared per block during a switch-over */
#define PREDELAY_LEN    8192        /* int16 samples in the BBD's 16 KB float line */
#define PREDELAY        ((int16_t *)FW_BBD_LINE)
#define TANK_RATE       24000.0f

/* 31-tap halfband (Blackman-windowed sinc): the centre tap is 0.5 and every other tap
 * is 0, so only these, the taps at even positions 0..30, are needed (the end ones are 0) */
static const float HB[16] = {
    0.0f, 0.000410319065f, -0.00223026483f, 0.00710079127f, -0.0179168642f, 0.0401070457f,
    -0.0901060863f, 0.312630422f, 0.312630422f, -0.0901060863f, 0.0401070457f,
    -0.0179168642f, 0.00710079127f, -0.00223026483f, 0.000410319065f, 0.0f,
};

_Static_assert(RV_SIZE == PK_FX_BUF_LEN, "reverb lines are the shared FX buffer");

/* settings and control state: AXI SRAM; what the audio loop walks: patch RAM */
PK_AXI uint8_t pk_cfg_reverb;       /* system/mods.json "fx-reverb", config row 3 step 15 */
PK_AXI uint8_t pk_reverb_active;    /* engine currently running */
PK_AXI static int32_t clear_pos;    /* >= 0 while clearing buffers for a switch-over */

static rv_t rv;
static int32_t pd_w;
static float pd_delay;              /* current pre-delay, samples (slewed); < 0: snap */
/* rate change histories, each stored twice so a window of the newest samples is contiguous */
static float dec_h[64];             /* 48 kHz in, newest first from dec_h[dec_i] */
static float int_h[32];             /* 24 kHz tank out, newest first from int_h[int_i] */
static int32_t dec_i, int_i;

static inline int16_t sat16(float x)
{
    return (int16_t)(x > 32767.0f ? 32767 : (x < -32768.0f ? -32768 : (int32_t)x));
}

static void zero16(int16_t *p, int32_t n)
{
    for (int32_t i = 0; i < n; i++)
        p[i] = 0;
}

static float clampf(float x, float lo, float hi)
{
    return x < lo ? lo : (x > hi ? hi : x);
}

/* boot, before the settings files load (state is already zeroed) */
void pk_reverb_init(void)
{
    clear_pos = -1;
    pd_delay = -1.0f;
    rv_init(&rv, pk_fx_buf);
}

static void reverb_params(rv_params_t *p, float *pd_target)
{
    float fb = clampf(FW_FX_FEEDBACK / 1.02f, 0.0f, 1.0f);
    float rate = clampf((FW_FX_LFO_RATE * 3000.0f - 0.1f) / 20.0f, 0.0f, 1.0f);
    float depth = clampf(FW_FX_LFO_DEPTH / 0.3f, 0.0f, 1.0f);
    int room = !pk_fx_switch_is_freeze() && FW_FX_SWITCH == CONST_fx_switch_short_level;

    p->input_gain = 0.2f;
    p->time = room ? 0.30f + 0.55f * fb : 0.35f + 0.63f * fb;   /* full right: very long */
    p->size = room ? 0.6f : 1.0f;
    p->diffusion = 0.40f + 0.35f * rate;                        /* LFO RATE knob */
    p->lp = 0.91f;                                              /* fixed damping (Rings' 0.7 at 48 kHz) */
    p->hp = 0.031f;                                             /* ~120 Hz, 2 poles */
    p->mod_depth = 2.0f * depth;                                /* MOD DEPTH knob */
    p->lfo_freq[0] = (0.5f + depth) * 0.5f / TANK_RATE;
    p->lfo_freq[1] = (0.5f + depth) * 0.3f / TANK_RATE;

    if (pk_fx_freeze_engaged()) {                               /* as Elements */
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
    *pd_target = clampf(seconds * 48000.0f, 0.0f, (float)(PREDELAY_LEN - 2));
}

/* 48 kHz -> 24 kHz: one output per input pair */
static void decimate(const float *x, float *x2)
{
    for (int f = 0; f < NF; f++) {
        dec_i = (dec_i - 1) & 31;
        dec_h[dec_i] = dec_h[dec_i + 32] = x[f];
        if (f & 1) {
            const float *h = dec_h + dec_i;
            float acc = 0.5f * h[15];
            for (int j = 0; j < 16; j++)
                acc += HB[j] * h[2 * j];
            x2[f >> 1] = acc;
        }
    }
}

/* 24 kHz -> 48 kHz: zero-stuffed and filtered, as two phases */
static void interpolate(const float *y2, float *y)
{
    for (int f = 0; f < NF; f++) {
        if (f & 1) {
            y[f] = int_h[int_i + 7];
        } else {
            int_i = (int_i - 1) & 15;
            int_h[int_i] = int_h[int_i + 16] = y2[f >> 1];
            const float *h = int_h + int_i;
            float acc = 0.0f;
            for (int j = 0; j < 16; j++)
                acc += HB[j] * h[j];
            y[f] = 2.0f * acc;
        }
    }
}

static void reverb_block(const int16_t *in, int16_t *out)
{
    float x[NF], y[NF], x2[NF / 2], y2[NF / 2], pd_target;
    rv_params_t p;
    reverb_params(&p, &pd_target);
    if (pd_delay < 0.0f)                        /* engine just started: no glide from 0 */
        pd_delay = pd_target;

    for (int f = 0; f < NF; f++) {
        /* pre-delay line (int16, in the BBD's memory); delay glides toward the target */
        PREDELAY[pd_w] = in[2 * f];
        float d = pd_delay;
        d += clampf(pd_target - d, -0.5f, 0.5f);
        pd_delay = d;
        float rp = (float)pd_w - d;
        if (rp < 0.0f)
            rp += PREDELAY_LEN;
        int32_t i0 = (int32_t)rp;
        float fr = rp - (float)i0;
        int32_t i1 = i0 + 1 >= PREDELAY_LEN ? 0 : i0 + 1;
        x[f] = ((float)PREDELAY[i0] * (1.0f - fr) + (float)PREDELAY[i1] * fr) * (1.0f / 32768.0f);
        if (++pd_w >= PREDELAY_LEN)
            pd_w = 0;
    }
    decimate(x, x2);
    rv_process(&rv, &p, x2, y2, NF / 2);
    interpolate(y2, y);
    for (int f = 0; f < NF; f++)
        out[2 * f] = sat16(y[f] * 32768.0f);
}

/* replaces fx_lfo's LED write: in reverb mode the LFO LED shows the reverb's tank
 * modulation (MOD DEPTH sets its rate) instead of the idle delay LFO */
void PK_NEXT(pk_fx_lfo_led)(uint32_t pwm);

void pk_fx_lfo_led(uint32_t pwm)
{
    if (pk_reverb_active) {
        float x = 2.0f * rv.lfo_val[0] - 1.0f;              /* -1..1, as the stock LFO */
        pwm = (uint32_t)(0x7fff - (int32_t)(x * 32767.0f)) & 0xffff;
    }
    PK_NEXT(pk_fx_lfo_led)(pwm);
}

void pk_fx_engine(const int16_t *in, int16_t *out)
{
    if (pk_cfg_reverb != pk_reverb_active && clear_pos < 0)
        clear_pos = 0;
    if (clear_pos >= 0) {
        /* switch-over, silent meanwhile: clear the BBD line (the delay's history, or the
         * reverb's pre-delay) and the shared FX buffer (reverb lines, or a looper's
         * recording), as one virtual range, a chunk per block */
        const int32_t len = PREDELAY_LEN + PK_FX_BUF_LEN;
        int32_t pos = clear_pos;
        int32_t n = len - pos < CLEAR_CHUNK ? len - pos : CLEAR_CHUNK;
        if (pos < PREDELAY_LEN) {
            if (n > PREDELAY_LEN - pos)
                n = PREDELAY_LEN - pos;
            zero16(PREDELAY + pos, n);
        } else {
            zero16(pk_fx_buf + (pos - PREDELAY_LEN), n);
        }
        clear_pos += n;
        if (clear_pos >= len) {
            clear_pos = -1;
            pk_reverb_active = pk_cfg_reverb;
            pd_delay = -1.0f;               /* reverb: snap to the target on its first block */
            pd_w = 0;
            rv.write_ptr = 0;               /* lines already zeroed above: reset state only */
            rv.lp1 = rv.lp2 = rv.hp1 = rv.hp2 = 0.0f;
            for (int i = 0; i < 64; i++)
                dec_h[i] = 0.0f;
            for (int i = 0; i < 32; i++)
                int_h[i] = 0.0f;
            fw_fx_bbd_clear_state();        /* delay: no tail from before the reverb */
            pk_fx_reset();
        }
        for (int i = 0; i < 2 * NF; i++)
            out[i] = 0;
        return;
    }
    if (pk_reverb_active)
        reverb_block(in, out);
    else
        pk_fx_delay(in, out);
}
