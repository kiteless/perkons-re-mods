/* Mono reverb for the Pērkons M4.
 *
 * A C port of the reverb in Mutable Instruments Rings / Elements (rings/dsp/fx/reverb.h
 * and fx_engine.h), copyright 2014 Emilie Gillet, MIT license:
 *
 *   Permission is hereby granted, free of charge, to any person obtaining a copy of this
 *   software and associated documentation files (the "Software"), to deal in the Software
 *   without restriction, including without limitation the rights to use, copy, modify,
 *   merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
 *   permit persons to whom the Software is furnished to do so, subject to the following
 *   conditions: The above copyright notice and this permission notice shall be included
 *   in all copies or substantial portions of the Software. THE SOFTWARE IS PROVIDED
 *   "AS IS", WITHOUT WARRANTY OF ANY KIND.
 *
 * Griesinger topology from the Dattorro paper: 4 allpass diffusers on the input, then a
 * figure-eight loop of 2 x (modulated delay read, one-pole damping, 2 allpasses, delay).
 * Changes from the original: mono in and out (the two tank taps are averaged), a "size"
 * scale on the two long delay reads (room / hall), modulation depth and rate as
 * parameters, a 2-pole input high-pass, and float LFOs instead of stmlib's. It runs at
 * 24 kHz (the caller decimates and interpolates): every line, read offset and modulation
 * amplitude is half of Rings', so the times in seconds are the same in half the memory.
 */
#include "reverb.h"

/* delay line lengths (samples at 24 kHz: Rings' halved) and their bases in the shared ring */
enum {
    L_AP1 = 75, L_AP2 = 107, L_AP3 = 160, L_AP4 = 264,
    L_DAP1A = 1091, L_DAP1B = 1345, L_DEL1 = 2250,
    L_DAP2A = 1262, L_DAP2B = 1098, L_DEL2 = 3156,
};
enum {
    B_AP1 = 0,
    B_AP2 = B_AP1 + L_AP1 + 1,
    B_AP3 = B_AP2 + L_AP2 + 1,
    B_AP4 = B_AP3 + L_AP3 + 1,
    B_DAP1A = B_AP4 + L_AP4 + 1,
    B_DAP1B = B_DAP1A + L_DAP1A + 1,
    B_DEL1 = B_DAP1B + L_DAP1B + 1,
    B_DAP2A = B_DEL1 + L_DEL1 + 1,
    B_DAP2B = B_DAP2A + L_DAP2A + 1,
    B_DEL2 = B_DAP2B + L_DAP2B + 1,
    B_END = B_DEL2 + L_DEL2 + 1,
};
_Static_assert(B_END <= RV_SIZE, "reverb lines exceed the buffer");

#define MASK (RV_SIZE - 1)

static inline float clip16f(float x)
{
    return x > 32767.0f ? 32767.0f : (x < -32768.0f ? -32768.0f : x);
}

/* 16-bit storage, as FORMAT_16_BIT */
static inline float rd(const rv_t *r, int32_t i)
{
    return (float)r->buf[i & MASK] * (1.0f / 32768.0f);
}

static inline void wr(rv_t *r, int32_t i, float v)
{
    r->buf[i & MASK] = (int16_t)(int32_t)clip16f(v * 32768.0f);
}

void rv_init(rv_t *r, int16_t *buffer)
{
    r->buf = buffer;
    rv_clear(r);
    r->lfo_phase[0] = 0.0f;
    r->lfo_phase[1] = 0.25f;
    r->lfo_val[0] = r->lfo_val[1] = 0.5f;
}

void rv_clear(rv_t *r)
{
    for (int32_t i = 0; i < RV_SIZE; i++)
        r->buf[i] = 0;
    r->write_ptr = 0;
    r->lp1 = r->lp2 = 0.0f;
    r->hp1 = r->hp2 = 0.0f;
}

/* parabolic sine approximation of a 0..1 phase, output 0..1 (like the cosine LFO) */
static inline float lfo_shape(float ph)
{
    float x = ph < 0.5f ? ph * 4.0f - 1.0f : 3.0f - ph * 4.0f;   /* triangle -1..1 */
    return 0.5f + 0.5f * x * (1.5f - 0.5f * x * x);              /* soft sine */
}

/* in/out: float samples, -1..1. out receives the wet signal only. */
void rv_process(rv_t *r, const rv_params_t *p, const float *in, float *out, int n)
{
    const float kap = p->diffusion, klp = p->lp, krt = p->time, gain = p->input_gain;
    const float amp1 = 20.0f * p->mod_depth, amp2 = 25.0f * p->mod_depth;
    /* base read offsets as Rings (4460 / 6261, halved), but never so far that offset + modulation
     * reads past the end of the line into the next one (Rings' own amplitudes fit with
     * one sample to spare; deeper modulation needs the base pulled in) */
    float off1 = 2230.0f * p->size, off2 = 3130.5f * p->size;
    if (off1 > (float)L_DEL1 - 2.0f - amp1)
        off1 = (float)L_DEL1 - 2.0f - amp1;
    if (off2 > (float)L_DEL2 - 2.0f - amp2)
        off2 = (float)L_DEL2 - 2.0f - amp2;
    float lp1 = r->lp1, lp2 = r->lp2;

    for (int s = 0; s < n; s++) {
        if (--r->write_ptr < 0)
            r->write_ptr += RV_SIZE;
        const int32_t w = r->write_ptr;
        if ((w & 31) == 0) {                     /* LFOs advance every 32 samples */
            for (int k = 0; k < 2; k++) {
                r->lfo_phase[k] += p->lfo_freq[k] * 32.0f;
                if (r->lfo_phase[k] >= 1.0f)
                    r->lfo_phase[k] -= 1.0f;
                r->lfo_val[k] = lfo_shape(r->lfo_phase[k]);
            }
        }

        /* 2-pole input high-pass (two one-poles) */
        float x = in[s];
        r->hp1 += p->hp * (x - r->hp1);
        x -= r->hp1;
        r->hp2 += p->hp * (x - r->hp2);
        x -= r->hp2;

        float acc = x * gain, prev, t;

        /* input diffusers: Read(ap TAIL, kap); WriteAllPass(ap, -kap) */
#define AP(base, len, k)                                    \
        prev = rd(r, w + (base) + (len) - 1);               \
        acc += prev * (k);                                  \
        wr(r, w + (base), acc);                             \
        acc *= -(k);                                        \
        acc += prev;
        AP(B_AP1, L_AP1, kap)
        AP(B_AP2, L_AP2, kap)
        AP(B_AP3, L_AP3, kap)
        AP(B_AP4, L_AP4, kap)
        const float apout = acc;

        /* modulated, interpolated read of a long delay into the accumulator */
#define INTERP(base, offset, amp, lfo, scale)                              \
        t = (offset) + (amp) * r->lfo_val[lfo];                            \
        {                                                                  \
            int32_t ti = (int32_t)t;                                       \
            float tf = t - (float)ti;                                      \
            float a = rd(r, w + ti + (base)), b = rd(r, w + ti + (base) + 1); \
            acc += (a + (b - a) * tf) * (scale);                          \
        }

        /* tank half 1 */
        acc = apout;
        INTERP(B_DEL2, off2, amp2, 1, krt)
        lp1 += klp * (acc - lp1);
        acc = lp1;
        AP(B_DAP1A, L_DAP1A, -kap)
        AP(B_DAP1B, L_DAP1B, kap)
        wr(r, w + B_DEL1, acc);
        const float wet1 = acc;

        /* tank half 2 */
        acc = apout;
        INTERP(B_DEL1, off1, amp1, 0, krt)
        lp2 += klp * (acc - lp2);
        acc = lp2;
        AP(B_DAP2A, L_DAP2A, kap)
        AP(B_DAP2B, L_DAP2B, -kap)
        wr(r, w + B_DEL2, acc);
        const float wet2 = acc;
#undef AP
#undef INTERP

        /* Rings takes each tap after `Write(del, 2.0f)`, i.e. doubled; mono = their mean */
        out[s] = wet1 + wet2;
    }
    r->lp1 = lp1;
    r->lp2 = lp2;
}
