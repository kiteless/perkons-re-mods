/* ZIBENS: a scale-stepped synth voice with an MS-style resonant filter (M7).
 *
 * An extra voice-map engine ("zibens" in voices.json): voice-map builds one in an output's
 * arena with pk_zb_build(). The object is cVoice-compatible: the fields the firmware
 * writes (algo, mode, velocity, note, param pointers, mute, gain) sit at the stock
 * offsets, and the vtable has the four methods the firmware calls (trigger, init,
 * update, render). See docs/design.md.
 *
 *   TONE (param 0)    note, stepped through the scale (ALGO), 4 octaves from C1
 *   DECAY (param 1)   amplitude decay, the stock voices' curve (max = no decay)
 *   PARAM1 (param 2)  attack, ~0.5 ms .. ~2 s
 *   PARAM2 (param 3)  saw: resonance of the digital MS filter (only saw has it);
 *                     square: pulse width; sine: fold macro (depth and symmetry)
 *   ALGO              minor pentatonic / Dorian / Phrygian (positions 1 / 2 / 3)
 *   MODE              saw / square / sine (positions 1 / 2 / 3)
 *   trigger note      transposes: + (note - 36) semitones, as on the stock voices
 */
#include <stdint.h>
#include "fw_m7.h"

#define SR              48000.0f
#define NOTE_REF        36          /* trigger note meaning "no transposition" */
#define BASE_NOTE       24          /* TONE at minimum: C1 */
#define OCTAVES         4
#define HYST            0.2f        /* TONE hysteresis, fraction of a step each side */
#define LEVEL           8000.0f     /* peak at velocity 127, like the stock tonal voices */
#define PI              3.14159265f
#define MAGIC           0x5a49424eu /* 'ZIBN' */

/* switch values are 1, 0, 2 for panel positions 1, 2, 3 */
enum { POS1 = 1, POS2 = 0, POS3 = 2 };
enum { WAVE_SAW, WAVE_SQUARE, WAVE_SINE };
enum { IDLE, ATTACK, DECAY };

static const int8_t SCALE_PENT[] = {0, 3, 5, 7, 10};
static const int8_t SCALE_DORIAN[] = {0, 2, 3, 5, 7, 9, 10};
static const int8_t SCALE_PHRYGIAN[] = {0, 1, 3, 5, 7, 8, 10};

typedef struct {
    float a, z1;            /* TPT one-pole: coefficient G, state */
} pole_t;

typedef struct {
    const cVoice_vtbl *vtbl;            /* +0x00 */
    uint8_t algo, mode, velocity, note; /* +0x04 .. +0x07 (written by the firmware) */
    uint32_t magic;                     /* +0x08 */
    int32_t *param[4];                  /* +0x0c TONE, DECAY, PARAM1, PARAM2 */
    uint8_t base_pad[0xb8 - 0x1c];
    uint8_t mute;                       /* +0xb8 (written by the firmware) */
    uint8_t pad[3];
    int32_t gain;                       /* +0xbc mute fade, cVoice_tick_mute_fade */
    /* ---- ours ---- */
    float phase;                        /* oscillator, 0..1 */
    float inc;                          /* phase increment of the note */
    float env;                          /* amplitude envelope 0..1 */
    float att, dec;                     /* per-sample attack coefficient, decay multiplier */
    float amp;                          /* velocity scale */
    float k;                            /* saw: filter resonance (Korg-35 K, 0..~2) */
    float extra;                        /* square: pulse width, sine: fold, 0..1 */
    float step_pos;                     /* quantised TONE step (hysteresis memory) */
    int32_t scale_id;                   /* scale the step belongs to */
    int32_t wave;
    int32_t stage;
    pole_t lp1, lp2, hp1;               /* Korg-35 low-pass */
    float fold_prev;                    /* sine folder: last 2x sub-sample */
    float dc_x, dc_y;                   /* sine folder: DC blocker */
} zb_t;

_Static_assert(__builtin_offsetof(zb_t, algo) == OFF_cVoice_algo, "algo");
_Static_assert(__builtin_offsetof(zb_t, mode) == OFF_cVoice_mode, "mode");
_Static_assert(__builtin_offsetof(zb_t, velocity) == OFF_cVoice_velocity, "velocity");
_Static_assert(__builtin_offsetof(zb_t, note) == OFF_cVoice_accent, "note (accent)");
_Static_assert(__builtin_offsetof(zb_t, param) == OFF_cVoice_param_ptrs, "param pointers");
_Static_assert(__builtin_offsetof(zb_t, mute) == OFF_cVoice_mute, "mute");
_Static_assert(__builtin_offsetof(zb_t, gain) == OFF_cVoice_gain, "gain");
_Static_assert(sizeof(zb_t) <= 0x4000, "fits a voice-map arena");

/* ---- small maths (no libm) --------------------------------------------------------- */

static inline float clampf(float x, float lo, float hi)
{
    return x < lo ? lo : (x > hi ? hi : x);
}

/* 2^x, |x| < 100: exponent by bits, the fraction (reduced to [-0.5, 0.5] around the
 * nearest integer, so tiny exponents such as per-sample decay factors stay exact) by a
 * 7th-order series (~1e-7 relative) */
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

/* sin(2*pi*p), p in [0, 1) */
static float sin2pi(float p)
{
    float x = p < 0.5f ? p : p - 1.0f;          /* -0.5 .. 0.5 */
    x *= 2.0f * PI;                              /* -pi .. pi */
    if (x > 0.5f * PI)
        x = PI - x;
    else if (x < -0.5f * PI)
        x = -PI - x;
    float x2 = x * x;
    return x * (1.0f - x2 * (1.0f / 6 - x2 * (1.0f / 120 - x2 * (1.0f / 5040))));
}

/* tan(x) for 0 <= x <= ~1.2 (Pade) */
static inline float tanf_(float x)
{
    float x2 = x * x;
    return x * (15.0f - x2) / (15.0f - 6.0f * x2);
}

static inline float tanh_(float x)
{
    if (x > 3.0f)
        return 1.0f;
    if (x < -3.0f)
        return -1.0f;
    float x2 = x * x;
    return x * (27.0f + x2) / (27.0f + 9.0f * x2);
}

static inline float blep(float t, float dt)
{
    if (t < dt) {
        t /= dt;
        return t + t - t * t - 1.0f;
    }
    if (t > 1.0f - dt) {
        t = (t - 1.0f) / dt;
        return t * t + t + t + 1.0f;
    }
    return 0.0f;
}

/* smooth folder (Serge / Buchla style): sin(pi/2 * x). Gentle saturation within
 * [-1, 1], smooth folds beyond it, any number of them */
static inline float sfold(float x)
{
    float p = x * 0.25f;                        /* sin(pi/2 x) = sin(2 pi * x/4) */
    p -= (float)(int32_t)p;
    if (p < 0.0f)
        p += 1.0f;
    return sin2pi(p);
}

static inline float knob(const zb_t *z, int k)
{
    return clampf((float)*z->param[k] * (1.0f / 4095.0f), 0.0f, 1.0f);
}

/* ---- control (per block) ------------------------------------------------------------ */

static const int8_t *scale_of(int id, int *len)
{
    if (id == POS1) {
        *len = sizeof SCALE_PENT;
        return SCALE_PENT;
    }
    if (id == POS3) {
        *len = sizeof SCALE_PHRYGIAN;
        return SCALE_PHRYGIAN;
    }
    *len = sizeof SCALE_DORIAN;
    return SCALE_DORIAN;
}

/* DECAY knob -> T60 seconds, the stock voices' curve (measured on Simple / Wavetable):
 * log-linear between 0.077 s, 0.39 s, 2 s, 12 s at 0, 1/4, 1/2, 3/4; on to ~200 s near the
 * top, and the top of the knob doesn't decay (returns 0 = hold) */
static float decay_t60(float d)
{
    static const float t0[4] = {0.077f, 0.39f, 2.0f, 12.0f};
    static const float oct[4] = {2.3405f, 2.3584f, 2.5850f, 4.0f};   /* log2 of each span's ratio */
    if (d >= 0.99f)
        return 0.0f;
    float x = d * 4.0f;
    int i = x >= 3.0f ? 3 : (int)x;
    float t = x - (float)i;
    if (i == 3)
        t = (d - 0.75f) / 0.24f;
    return t0[i] * exp2f_(t * oct[i]);
}

static void update(cVoice *v)
{
    zb_t *z = (zb_t *)v;
    if (z->magic != MAGIC)
        return;

    /* TONE: position along the scale, quantised with hysteresis */
    int len;
    const int8_t *sc = scale_of(z->algo, &len);
    int steps = OCTAVES * len;                                  /* top C included: steps + 1 notes */
    float pos = knob(z, 0) * (float)steps;
    if (z->scale_id != z->algo || z->step_pos < 0.0f) {
        z->scale_id = z->algo;
        z->step_pos = (float)(int32_t)(pos + 0.5f);
    } else if (pos > z->step_pos + 0.5f + HYST || pos < z->step_pos - 0.5f - HYST) {
        z->step_pos = (float)(int32_t)(pos + 0.5f);
    }
    int step = (int)z->step_pos;
    int semis = 12 * (step / len) + sc[step % len];
    int note = z->note ? z->note : NOTE_REF;
    float midi = (float)(BASE_NOTE + semis + note - NOTE_REF);
    float hz = 440.0f * exp2f_((midi - 69.0f) * (1.0f / 12.0f));
    z->inc = clampf(hz, 8.0f, 12000.0f) / SR;

    z->wave = z->mode == POS1 ? WAVE_SAW : (z->mode == POS3 ? WAVE_SINE : WAVE_SQUARE);

    /* envelope coefficients */
    float t60 = decay_t60(knob(z, 1));
    z->dec = t60 > 0.0f ? exp2f_(-9.965784f / (t60 * SR)) : 1.0f;       /* 10^-3 over T60 */
    float ta = 0.0005f * exp2f_(knob(z, 2) * 11.965784f);               /* 0.5 ms .. 2 s */
    z->att = 1.0f - exp2f_(-2.5849625f / (ta * SR));                    /* reach 1 of 1.2 in ta */

    /* PARAM2: the saw's filter resonance, or the square's / sine's extra */
    float p2 = knob(z, 3);
    z->k = 0.05f + 1.9f * p2 * p2;
    z->extra = p2;
}

static void trigger(cVoice *v)
{
    zb_t *z = (zb_t *)v;
    if (z->magic != MAGIC)
        return;
    if (z->stage == IDLE || z->env < 1e-4f) {
        z->phase = 0.0f;
        z->lp1.z1 = z->lp2.z1 = z->hp1.z1 = 0.0f;
        z->fold_prev = z->dc_x = z->dc_y = 0.0f;
    }
    z->amp = (float)z->velocity * (1.0f / 127.0f);
    z->stage = ATTACK;                  /* from the current level: no click on retrigger */
}

static void init(cVoice *v)
{
    zb_t *z = (zb_t *)v;
    z->magic = MAGIC;
    z->phase = z->env = 0.0f;
    z->stage = IDLE;
    z->amp = 1.0f;
    z->step_pos = -1.0f;
    z->scale_id = -1;
    z->lp1.z1 = z->lp2.z1 = z->hp1.z1 = 0.0f;
    update(v);
}

/* ---- audio (per sample) ---------------------------------------------------------------- */

static inline float pole_lp(pole_t *p, float x)
{
    float vn = (x - p->z1) * p->a;
    float lp = vn + p->z1;
    p->z1 = vn + lp;
    return lp;
}

/* The sine's fold macro (PARAM2 = z->extra): fold depth and, rising with it, symmetry
 * (a bias before the fold: even harmonics). Two smooth stages, up to ~16x; 2x
 * oversampled. */
static float folded_sine(zb_t *z, float p, float dt)
{
    if (z->extra <= 0.0f) {                     /* PARAM2 at 0: a pure sine, folder idle */
        z->fold_prev = z->dc_x = z->dc_y = 0.0f;
        return sin2pi(p);
    }
    float a = z->extra;                         /* fold amount: PARAM2 (static) */
    float g1 = 1.0f + 7.0f * a, g2 = 1.0f + a;  /* stage gains: 8x then 2x at the peak */
    float bias = 0.35f * a;                     /* symmetry */
    float h = p - 0.5f * dt;                    /* the 2x sub-sample half a step back */
    if (h < 0.0f)
        h += 1.0f;
    float s = sin2pi(p);
    float f0 = sfold(g2 * sfold(g1 * sin2pi(h) + bias));
    float f1 = sfold(g2 * sfold(g1 * s + bias));
    float y = 0.25f * z->fold_prev + 0.5f * f0 + 0.25f * f1;   /* decimate 2x -> 1x */
    z->fold_prev = f1;
    float wet = clampf(z->extra * 10.0f, 0.0f, 1.0f);          /* fade in over the knob's first 10% */
    y = s + (y - s) * wet;
    float o = y - z->dc_x + 0.99869f * z->dc_y;                /* DC blocker, ~10 Hz */
    z->dc_x = y;
    z->dc_y = o;
    return o;
}

static float oscillator(zb_t *z)
{
    float dt = z->inc, p = z->phase, s;
    if (z->wave == WAVE_SAW) {
        s = 2.0f * p - 1.0f - blep(p, dt);
    } else if (z->wave == WAVE_SQUARE) {
        float pw = 0.5f - 0.4f * z->extra;                      /* pulse width */
        float q = p + 1.0f - pw;
        if (q >= 1.0f)
            q -= 1.0f;
        s = (p < pw ? 1.0f : -1.0f) + blep(p, dt) - blep(q, dt);
    } else {
        s = folded_sine(z, p, dt);
    }
    p += dt;
    z->phase = p >= 1.0f ? p - 1.0f : p;
    return s;
}

/* Korg-35 low-pass (Pirkle's VA model), saturating feedback; cutoff in Hz */
static float ms_filter(zb_t *z, float x, float fc)
{
    float g = tanf_(PI * fc / SR);
    float G = g / (1.0f + g);
    float k = z->k;
    z->lp1.a = z->lp2.a = z->hp1.a = G;
    float beta_lp2 = (k - k * G) / (1.0f + g);
    float beta_hp1 = -1.0f / (1.0f + g);
    float alpha = 1.0f / (1.0f - k * G + k * G * G);

    float y1 = pole_lp(&z->lp1, x);
    float s35 = z->hp1.z1 * beta_hp1 + z->lp2.z1 * beta_lp2;
    float u = tanh_(1.5f * alpha * (y1 + s35));
    float y = k * pole_lp(&z->lp2, u);
    pole_lp(&z->hp1, y);                                        /* its high-pass output isn't needed */
    return y / k;
}

static int16_t render(cVoice *v)
{
    zb_t *z = (zb_t *)v;
    fw_tick_mute_fade(v);
    if (z->magic != MAGIC || z->stage == IDLE)
        return 0;

    if (z->stage == ATTACK) {
        z->env += (1.2f - z->env) * z->att;
        if (z->env >= 1.0f) {
            z->env = 1.0f;
            z->stage = DECAY;
        }
    } else {
        z->env *= z->dec;
        if (z->env < 1e-5f) {
            z->env = 0.0f;
            z->stage = IDLE;
            return 0;
        }
    }

    float y = oscillator(z);
    if (z->wave == WAVE_SAW) {          /* only the saw goes through the MS filter */
        float fc = clampf(z->inc * SR * exp2f_(1.0f + 4.0f * z->env), 20.0f, 0.35f * SR);
        y = ms_filter(z, y, fc);
    }
    float out = clampf(y * z->env * z->amp * LEVEL, -32767.0f, 32767.0f);
    return (int16_t)(((int32_t)out * z->gain) >> 16);
}

/* ---- vtable and construction --------------------------------------------------------- */

/* RTTI-shaped word before the vtable (tools read class names from vtable[-1]) */
static const char zb_name[] = "6cZibens";
static const struct { const void *vptr; const char *name; } zb_typeinfo = {0, zb_name};
static const struct {
    const void *typeinfo;
    cVoice_vtbl vtbl;
} zb_vtable = {&zb_typeinfo, {trigger, init, update, render}};

/* voice-map: build a ZIBENS instance in `obj` (an output's arena) for output `out` */
void pk_zb_build(uint8_t *obj, unsigned out)
{
    for (unsigned i = 0; i < sizeof(zb_t); i++)
        obj[i] = 0;
    zb_t *z = (zb_t *)obj;
    z->vtbl = &zb_vtable.vtbl;
    for (int k = 0; k < 4; k++)
        z->param[k] = &FW_PARAMS[out][k];
    z->note = NOTE_REF;
    init((cVoice *)z);
}
