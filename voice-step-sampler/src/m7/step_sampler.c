/* STEP SAMPLER, M7 side: a sample voice that plays what the M4 tells each hit to play.
 *
 * An extra voice-map engine ("step_sampler"): voice-map builds one in an output's arena
 * with pk_ss_build(). The object is cVoice-compatible: the fields the firmware writes
 * (algo, mode, velocity, note, param pointers, mute, gain) sit at the stock offsets, and
 * the vtable has the four methods the firmware calls (trigger, init, update, render).
 *
 * The M4 decides what each hit plays (the sample, its stretch, the direction: from ALGO,
 * MODE, PARAM2 and the step) and writes it into the shared control just before the
 * trigger goes out (ss_shared.h); this side plays it: pitch, grit, envelope, level.
 *
 *   TUNE (param 0)    pitch: 512 per octave, 12 o'clock = the sample's own speed, + the
 *                     trigger note (note - 36 semitones); each sample at its own rate
 *   DECAY (param 1)   decay, the stock voices' range (fully right holds)
 *   PARAM1 (param 2)  grit: clean, to 12-bit ~26 kHz at 12 o'clock, to ~6-bit ~2 kHz
 *   PARAM2 (param 3)  ALGO 1: attack, instant to ~2 s (ALGO 2 / 3: the M4's start / slice)
 *   ALGO, MODE        read by the M4 (what to play); here only ALGO 1 = attack on PARAM2
 *
 * At the end of its stretch a hit goes round again while the envelope is still open, unless
 * it's choked (MODE 2): then it stops there, fading out over its last CUT_FADE frames. */
#include <stdint.h>
#include "fw_m7.h"
#include "ss_shared.h"

#define SR              48000.0f
#define NOTE_REF        36
#define TUNE_CENTRE     2048
#define TUNE_OCTAVE     512.0f
#define GAIN            0.25f       /* a full-scale sample peaks near the stock tonal voices */
#define MAX_INC         8.0f        /* three octaves up at most: the card keeps up */
#define MAGIC           0x53535356u /* 'VSSS' */
#define ENV_OPEN        0.001f      /* the envelope still open: loop at the end */
#define CUT_FADE        64u         /* a choked hit's fade into its cut, tape frames */

enum { POS1 = 1, POS2 = 0, POS3 = 2 };
enum { IDLE, ATTACK, DECAY };

typedef struct {
    const cVoice_vtbl *vtbl;            /* +0x00 */
    uint8_t algo, mode, velocity, note; /* +0x04 .. +0x07 (written by the firmware) */
    uint32_t magic;                     /* +0x08 */
    int32_t *param[4];                  /* +0x0c TUNE, DECAY, PARAM1, PARAM2 */
    uint8_t base_pad[0xb8 - 0x1c];
    uint8_t mute;                       /* +0xb8 (written by the firmware) */
    uint8_t pad[3];
    int32_t gain;                       /* +0xbc mute fade, cVoice_tick_mute_fade */
    /* ---- ours ---- */
    uint32_t out;                       /* which output (the shared control's index) */
    uint32_t gen;                       /* the hit playing */
    uint32_t bank_gen;                  /* the bank it's from */
    uint32_t sample, dir, loop, src, rstart, rend, len, a_len, head;   /* copied at the trigger */
    uint32_t t;                         /* tape frame */
    float frac, inc;                    /* position within it, step per output sample */
    float env, att, dec, amp;
    int32_t stage;
    float hold_acc, held, grit_rate, grit_step;
} ss_t;

_Static_assert(__builtin_offsetof(ss_t, algo) == OFF_cVoice_algo, "algo");
_Static_assert(__builtin_offsetof(ss_t, mode) == OFF_cVoice_mode, "mode");
_Static_assert(__builtin_offsetof(ss_t, velocity) == OFF_cVoice_velocity, "velocity");
_Static_assert(__builtin_offsetof(ss_t, note) == OFF_cVoice_accent, "note (accent)");
_Static_assert(__builtin_offsetof(ss_t, param) == OFF_cVoice_param_ptrs, "param pointers");
_Static_assert(__builtin_offsetof(ss_t, mute) == OFF_cVoice_mute, "mute");
_Static_assert(__builtin_offsetof(ss_t, gain) == OFF_cVoice_gain, "gain");
_Static_assert(sizeof(ss_t) <= 0x4000, "fits a voice-map arena");

/* ---- small maths (no libm) --------------------------------------------------------- */

static inline float clampf(float x, float lo, float hi)
{
    return x < lo ? lo : (x > hi ? hi : x);
}

/* 2^x, |x| < 100: exponent by bits, the fraction by a 7th-order series */
static float exp2f_(float x)
{
    float r = x + 0.5f;
    float fi = (float)(int32_t)r;
    if (fi > r)
        fi -= 1.0f;
    float f = x - fi;
    float p = 1.0f + f * (0.69314718f + f * (0.24022651f + f * (0.05550411f + f * (0.00961813f +
              f * (0.00133336f + f * (0.00015404f + f * 0.00001525f))))));
    union { uint32_t u; float v; } e = {(uint32_t)((int32_t)fi + 127) << 23};
    return p * e.v;
}

static inline float knob(const ss_t *z, int k)
{
    return clampf((float)*z->param[k] * (1.0f / 4095.0f), 0.0f, 1.0f);
}

/* DECAY knob -> T60 seconds, the stock voices' range: log-linear between 0.077 s, 0.39 s,
 * 2 s, 12 s at 0, 1/4, 1/2, 3/4, on to ~200 s; the top of the knob holds (0) */
static float decay_t60(float d)
{
    static const float t0[4] = {0.077f, 0.39f, 2.0f, 12.0f};
    static const float oct[4] = {2.3405f, 2.3584f, 2.5850f, 4.0f};
    if (d >= 0.99f)
        return 0.0f;
    float x = d * 4.0f;
    int i = x >= 3.0f ? 3 : (int)x;
    float t = x - (float)i;
    if (i == 3)
        t = (d - 0.75f) / 0.24f;
    return t0[i] * exp2f_(t * oct[i]);
}

/* grit (PARAM1, 0..1): bit depth and sample rate. The first half goes from clean to the
 * 12-bit, ~26 kHz sampler sound; the second on to ~6-bit, ~2 kHz. */
static void grit(ss_t *z, float k)
{
    float bits, rate;
    if (k <= 0.5f) {
        bits = 16.0f - 8.0f * k;                            /* 16 -> 12 */
        rate = SR * exp2f_(k * 2.0f * -0.8845f);            /* 48 k -> 26 k (log2 26/48) */
    } else {
        bits = 12.0f - 12.0f * (k - 0.5f);                  /* 12 -> 6 */
        rate = 26000.0f * exp2f_((k - 0.5f) * 2.0f * -3.7004f);   /* 26 k -> 2 k (log2 2/26) */
    }
    z->grit_rate = k > 0.0f ? rate / SR : 1.0f;
    z->grit_step = k > 0.0f ? exp2f_(16.0f - bits) : 0.0f;  /* quantisation step, int16 scale */
}

/* ---- control (per block) ------------------------------------------------------------ */

static void update(cVoice *v)
{
    ss_t *z = (ss_t *)v;
    if (z->magic != MAGIC)
        return;
    int note = z->note ? z->note : NOTE_REF;
    float oct = ((float)*z->param[0] - TUNE_CENTRE) * (1.0f / TUNE_OCTAVE) + (float)(note - NOTE_REF) * (1.0f / 12.0f);
    uint32_t rate = z->gen && z->sample < SS_SAMPLES ? SS->sample[z->sample].rate : 48000u;
    z->inc = clampf((float)rate * (1.0f / SR) * exp2f_(oct), 0.0f, MAX_INC);
    float t60 = decay_t60(knob(z, 1));
    z->dec = t60 > 0.0f ? exp2f_(-9.965784f / (t60 * SR)) : 1.0f;
    float ta = z->algo == POS1 ? 0.0005f * exp2f_(knob(z, 3) * 11.965784f) : 0.0005f;   /* 0.5 ms .. 2 s */
    z->att = 1.0f - exp2f_(-2.5849625f / (ta * SR));
    grit(z, knob(z, 2));
}

static void trigger(cVoice *v)
{
    ss_t *z = (ss_t *)v;
    if (z->magic != MAGIC)
        return;
    ss_out_t *o = &SS->out[z->out];
    uint32_t gen = o->gen;
    if (SS->magic != SS_MAGIC || SS->loading || !gen || o->sample >= SS_SAMPLES ||
        !SS->sample[o->sample].frames || o->rend <= o->rstart) {
        z->gen = 0;                     /* nothing to play: an empty slot */
        z->stage = IDLE;
        o->m7_active = 0;
        o->seen_gen = gen;              /* seen all the same: the M4 may prepare the next */
        return;
    }
    z->gen = gen;
    z->bank_gen = SS->bank_gen;
    z->sample = o->sample;
    z->dir = o->dir;
    z->loop = o->loop;
    z->src = o->src;
    z->rstart = o->rstart;
    z->rend = o->rend;
    z->len = o->rend - o->rstart;
    z->a_len = o->a_len;
    z->head = SS->sample[o->sample].head_frames;
    z->t = 0;
    z->frac = 0.0f;
    z->hold_acc = 1.0f;                 /* the first output sample takes a fresh value */
    o->seen_gen = gen;
    o->t_read = 0;
    o->m7_active = 1;
    z->amp = (float)z->velocity * (1.0f / 127.0f);
    z->stage = ATTACK;                  /* from the current level: no click on retrigger */
    update(v);
}

static void init(cVoice *v)
{
    ss_t *z = (ss_t *)v;
    z->magic = MAGIC;
    z->stage = IDLE;
    z->env = 0.0f;
    z->amp = 1.0f;
    z->gen = 0;
    update(v);
}

/* ---- audio (per sample) ---------------------------------------------------------------- */

/* tape frame t of the hit playing, or 0x7fffffff if it isn't loaded (yet) */
static int32_t frame(const ss_t *z, uint32_t t)
{
    uint32_t f = ss_frame(z->rstart, z->rend, z->dir, t);
    if (f < z->head)
        return SS_HEAD(z->sample)[f];
    if (z->src == SS_SRC_NEXT && t < z->a_len)
        return SS_NEXTBUF(z->out)[t];
    const ss_out_t *o = &SS->out[z->out];
    if (o->ring_gen == z->gen && t >= o->ring_from && t < o->ring_to)
        return SS_RINGBUF(z->out)[t % SS_RING_FRAMES];
    return 0x7fffffff;
}

static int16_t render(cVoice *v)
{
    ss_t *z = (ss_t *)v;
    fw_tick_mute_fade(v);
    if (z->magic != MAGIC || z->stage == IDLE)
        return 0;
    if (SS->loading || SS->bank_gen != z->bank_gen) {
        z->stage = IDLE;                /* a bank load: every hit ends */
        SS->out[z->out].m7_active = 0;
        return 0;
    }

    if (z->stage == ATTACK) {
        z->env += (1.2f - z->env) * z->att;
        if (z->env >= 1.0f) {
            z->env = 1.0f;
            z->stage = DECAY;
        }
    } else {
        z->env *= z->dec;
        if (z->env < 1e-5f) {
            z->stage = IDLE;
            SS->out[z->out].m7_active = 0;
            return 0;
        }
    }

    if (z->t >= z->len && (!z->loop || z->env < ENV_OPEN)) {    /* the end: choked, or the envelope closed */
        z->stage = IDLE;
        SS->out[z->out].m7_active = 0;
        return 0;
    }

    /* the sample: linear interpolation between tape frames t and t + 1 */
    int32_t a = frame(z, z->t), b = z->loop || z->t + 1 < z->len ? frame(z, z->t + 1) : a;
    float s;
    if (a == 0x7fffffff)
        s = 0.0f;                       /* not loaded: silent until the stream catches up */
    else
        s = b == 0x7fffffff ? (float)a : (float)a + ((float)b - (float)a) * z->frac;
    if (!z->loop && z->len - z->t < CUT_FADE)
        s *= (float)(z->len - z->t) * (1.0f / CUT_FADE);    /* into the cut: no click */
    z->frac += z->inc;
    uint32_t whole = (uint32_t)z->frac;
    z->t += whole;
    z->frac -= (float)whole;
    SS->out[z->out].t_read = z->t;

    /* grit: hold each value for 1 / grit_rate samples, then quantise */
    z->hold_acc += z->grit_rate;
    if (z->hold_acc >= 1.0f) {
        z->hold_acc -= (float)(uint32_t)z->hold_acc;
        z->held = s;
    }
    s = z->held;
    if (z->grit_step > 1.0f) {
        float q = s / z->grit_step;
        q = (float)(int32_t)(q + (q >= 0.0f ? 0.5f : -0.5f));
        s = q * z->grit_step;
    }

    float out = clampf(s * z->env * z->amp * GAIN, -32767.0f, 32767.0f);
    return (int16_t)(((int32_t)out * z->gain) >> 16);
}

/* ---- vtable and construction --------------------------------------------------------- */

/* RTTI-shaped word before the vtable (tools read class names from vtable[-1]) */
static const char ss_name[] = "12cStepSampler";
static const struct { const void *vptr; const char *name; } ss_typeinfo = {0, ss_name};
static const struct {
    const void *typeinfo;
    cVoice_vtbl vtbl;
} ss_vtable = {&ss_typeinfo, {trigger, init, update, render}};

/* voice-map: build a STEP SAMPLER in `obj` (an output's arena) for output `out` */
void pk_ss_build(uint8_t *obj, unsigned out)
{
    for (unsigned i = 0; i < sizeof(ss_t); i++)
        obj[i] = 0;
    ss_t *z = (ss_t *)obj;
    z->vtbl = &ss_vtable.vtbl;
    for (int k = 0; k < 4; k++)
        z->param[k] = &FW_PARAMS[out][k];
    z->note = NOTE_REF;
    z->out = out < SS_OUTPUTS ? out : 0;
    init((cVoice *)z);
}
