/* Mono reverb (port of the Mutable Instruments Rings/Elements reverb, MIT), run at 24 kHz.
 * See reverb.c. */
#pragma once
#include <stdint.h>

#define RV_SIZE 16384            /* 16-bit samples: 32 KB, must be a power of two */

typedef struct {
    int16_t *buf;
    int32_t write_ptr;
    float lp1, lp2;              /* tank damping filter states */
    float hp1, hp2;              /* input high-pass states */
    float lfo_phase[2], lfo_val[2];
} rv_t;

typedef struct {
    float input_gain;            /* Rings: 0.2 */
    float time;                  /* loop gain (decay), 0..~0.98 */
    float diffusion;             /* allpass coefficient, Rings 0.625 */
    float lp;                    /* tank damping one-pole coefficient (1 = off), Rings 0.7 */
    float hp;                    /* input high-pass one-pole coefficient */
    float size;                  /* long delay read scale (room < 1 <= hall) */
    float mod_depth;             /* 1 = Rings' modulation amplitude */
    float lfo_freq[2];           /* cycles per sample */
} rv_params_t;

void rv_init(rv_t *r, int16_t *buffer);
void rv_clear(rv_t *r);
void rv_process(rv_t *r, const rv_params_t *p, const float *in, float *out, int n);
