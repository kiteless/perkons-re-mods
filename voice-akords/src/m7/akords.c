/* Akords: a chord synth voice (M7), after a poly synth built on iOS.
 *
 * An extra voice-map engine ("akords"): voice-map builds one in an output's arena with
 * pk_ak_build(). The object is cVoice-compatible: the fields the firmware writes (algo,
 * mode, velocity, note, param pointers, mute, gain) sit at the stock offsets, and the
 * vtable has the four methods the firmware calls (trigger, init, update, render).
 *
 * Each trigger plays a chord of 3 to 5 notes; the chord before fades out in 2 ms first
 * (one chord slot). The slot is up to 5 notes x 2 oscillators into one filter (its own
 * filter envelope) and an amp envelope, then a DC blocker and a limiter.
 *
 *   TUNE (param 0)    chord root, stepped through the scale, 4 octaves from the root (C2)
 *   DECAY (param 1)   GATE: how long the chord holds before its release, ~0.05-2 s; max = drone
 *   PARAM1 (param 2)  filter cutoff (formant: the vowel)
 *   PARAM2 (param 3)  ALGO 1 resonance / 2 filter env amount / 3 amp attack
 *   MODE              the filter: 24 dB low-pass / 12 dB high-pass / formant; the preset's
 *                     own filter until MODE moves after the preset was chosen
 *   trigger note      transposes: + (note - 36) semitones, as on the stock voices
 *
 * Preset, chord type, scale and root come from the M4 (its settings page, kept with the
 * kit): the ordered message "akords", 4 voices x 4 bytes, kept here per output (an
 * engine rebuilt by voice-map finds them again). Each voice's DRIVE comes from the M4 too
 * (message "akords-drive"): the level follows it (DRIVE_BOOST_DB / DRIVE_CUT_DB). And the
 * progression's offset, in scale degrees above TUNE's (message "akords-prog", sent before
 * the triggers of the step where it changes): each chord keeps the one it started with.
 *
 * When ALGO gives PARAM2 another job, the value keeps its setting until the knob moves.
 * The PLAY knobs are relative to the preset: 12 o'clock is the preset's own value. A
 * preset pressed on the page brings back all its own values (and filter) until the knobs
 * move.
 *
 * Message "akords-sound" sets the same values from a saved kit: the four PLAY values, what
 * PARAM2 sets, which knobs follow already, and whether the filter is the preset's own. While
 * the sequencer plays, the kit's knob and switch positions only reach this core with the
 * track's next note, so the M4 first sends it marked SOUND_HOLD: the positions set nothing
 * (nor MODE the filter) until it sends it again unmarked, once they've arrived. */
#include <stdint.h>
#include "fw_m7.h"

#define SR              48000.0f
#define NOTE_REF        36          /* trigger note meaning "no transposition" */
#define BASE_NOTE       36          /* TUNE at minimum, root C: C2 */
#define OCTAVES         4
#define HYST            0.2f        /* TUNE: hysteresis, fraction of a step each side */
#define MOVED           (82.0f / 4095.0f)   /* knob travel (2%) that hands it a new job */
#define LEVEL           8000.0f     /* peak scale, as the stock tonal voices */
#define MIX             (LEVEL * 0.3f)      /* per-slot output scale (3 notes, 2 oscillators) */
#define LIM_THR         9000.0f     /* the output limiter: peaks held at this (Zibens ~8500), */
#define LIM_REL         0.999861f   /* instant attack, 150 ms release */
#define DC_R            0.9995f     /* DC blocker pole (~4 Hz) */
#define FORMANT_Q       0.08f       /* formant bands: damping (Q 12.5) */
#define FORMANT_GAIN    5.0f        /* formant level trim: peaks near the presets */
#define PI              3.14159265f
#define MAGIC           0x414b5244u /* 'AKRD' */
#define COEF_EVERY      16          /* samples between filter coefficient / filter env steps */
#define FOLLOW_SAMPLES  1200        /* 25 ms: a new chord follows TUNE at once */
#define SETTLE_SAMPLES  960         /* 20 ms: later, a new TUNE step must hold this long */
#define STEAL_SAMPLES   96          /* 2 ms fade of a slot a new chord takes */
#define NSLOT           1           /* one chord: a new one takes over after a short fade */
#define NNOTE           5           /* notes in a chord, at most (unused: -1) */
#define DRIFT_CENTS     3.0f        /* each chord note's own detune: up to this either way */
/* The level follows the voice's DRIVE (an analog stage after the voice): louder with little
 * or no DRIVE, to sit with the voices that use it, quieter at full DRIVE, so the drive
 * saturates instead of breaking up. In dB, straight lines: +DRIVE_BOOST_DB at no DRIVE,
 * 0 dB at half, -DRIVE_CUT_DB at full. After the limiter, so its threshold moves with it. */
#define DRIVE_BOOST_DB  3.0f
#define DRIVE_CUT_DB    3.0f
#define DRIVE_SMOOTH    (1.0f / 960.0f)     /* ~20 ms: a DRIVE turn doesn't step the level */

/* switch values are 1, 0, 2 for panel positions 1, 2, 3 */
enum { POS1 = 1, POS2 = 0, POS3 = 2 };
enum { W_SINE, W_TRI, W_SAW, W_PULSE };
enum { F_LP24, F_HP12, F_FORMANT };
enum { IDLE, ATTACK, DECAY, SUSTAIN, RELEASE };
/* the values the PLAY knobs set */
enum { V_CUTOFF, V_RES, V_ENV, V_ATTACK, NVAL };
enum { CH_DIA, CH_DIA_S, CH_DIA7, CH_DIA7_S, CH_DIA9, CH_DIA9_S, CH_QUARTAL, CH_QUARTAL_S,
       CH_POWER, CH_POWER_S, NCHORD };

/* the settings page's positions (steps 1-16) */
#define NPRESET 14
#define NSCALE  11
#define NROOT   12                  /* the 12 semitones from C */

/* ---- presets (the iOS synth's factory patches) --------------------------------------- */

typedef struct {
    uint8_t wave[2];
    int8_t oct[2];
    float detune[2];        /* cents */
    float level[2];
    float pw[2];
    uint8_t fmode;
    float cutoff, res, env_amt, key_track;
    float a_att, a_dec, a_sus, a_rel;   /* seconds, level */
    float f_att, f_dec, f_sus, f_rel;
    float glide;                        /* seconds, 0 = off */
    float gain;                         /* level trim: the presets peak alike */
} preset_t;

static const preset_t PRESETS[NPRESET] = {
    /* Bass */
    {{W_SAW, W_PULSE}, {-1, -1}, {0, 5}, {0.9f, 0.55f}, {0.5f, 0.35f}, F_LP24,
     1400, 0.35f, 0.45f, 0.3f, 0.003f, 0.25f, 0.55f, 0.12f, 0.004f, 0.22f, 0.15f, 0.15f, 0, 0.9f},
    /* Pad */
    {{W_SAW, W_SAW}, {0, 0}, {-6, 8}, {0.7f, 0.7f}, {0.5f, 0.5f}, F_LP24,
     2200, 0.18f, 0.35f, 0.5f, 0.6f, 0.8f, 0.85f, 1.2f, 0.9f, 0.8f, 0.6f, 1.2f, 0, 0.95f},
    /* Lead */
    {{W_SAW, W_PULSE}, {0, 0}, {0, 4}, {0.85f, 0.6f}, {0.5f, 0.3f}, F_LP24,
     4200, 0.3f, 0.4f, 0.7f, 0.006f, 0.3f, 0.75f, 0.25f, 0.006f, 0.35f, 0.5f, 0.25f, 0.08f, 0.8f},
    /* Keys */
    {{W_SAW, W_TRI}, {0, 1}, {0, 0}, {0.8f, 0.5f}, {0.5f, 0.5f}, F_LP24,
     3600, 0.15f, 0.5f, 0.6f, 0.004f, 0.5f, 0.35f, 0.35f, 0.004f, 0.45f, 0.2f, 0.35f, 0, 0.87f},
    /* Pluck */
    {{W_SAW, W_SAW}, {0, 0}, {0, 10}, {0.85f, 0.6f}, {0.5f, 0.5f}, F_LP24,
     2600, 0.4f, 0.6f, 0.5f, 0.002f, 0.22f, 0.0f, 0.18f, 0.002f, 0.18f, 0.0f, 0.18f, 0, 0.66f},
    /* Stab */
    {{W_SAW, W_SAW}, {0, 0}, {-8, 8}, {0.8f, 0.8f}, {0.5f, 0.5f}, F_LP24,
     1500, 0.42f, 0.55f, 0.4f, 0.004f, 0.28f, 0.0f, 0.12f, 0.004f, 0.18f, 0.0f, 0.12f, 0, 0.57f},
    /* Hollow */
    {{W_PULSE, W_PULSE}, {0, 0}, {-10, 10}, {0.8f, 0.7f}, {0.5f, 0.25f}, F_LP24,
     2800, 0.2f, 0.35f, 0.6f, 0.02f, 0.4f, 0.8f, 0.4f, 0.03f, 0.5f, 0.55f, 0.4f, 0, 0.61f},
    /* Reese */
    {{W_SAW, W_SAW}, {-1, -1}, {-22, 22}, {0.9f, 0.9f}, {0.5f, 0.5f}, F_LP24,
     900, 0.25f, 0.3f, 0.25f, 0.005f, 0.4f, 0.9f, 0.2f, 0.01f, 0.5f, 0.6f, 0.25f, 0.04f, 0.59f},
    /* Organ */
    {{W_TRI, W_SINE}, {0, 1}, {0, 0}, {0.8f, 0.7f}, {0.5f, 0.5f}, F_LP24,
     9000, 0.0f, 0.0f, 0.3f, 0.005f, 0.2f, 0.95f, 0.06f, 0.005f, 0.2f, 1.0f, 0.06f, 0, 1.0f},
    /* Bell */
    {{W_SINE, W_TRI}, {1, 2}, {0, 5}, {0.85f, 0.5f}, {0.5f, 0.5f}, F_LP24,
     6000, 0.0f, 0.0f, 0.6f, 0.002f, 0.9f, 0.0f, 0.5f, 0.002f, 0.6f, 0.0f, 0.5f, 0, 0.97f},
    /* Air: high-pass, thin and bright; the filter envelope dips the cutoff on the attack */
    {{W_SAW, W_PULSE}, {0, 1}, {-7, 7}, {0.75f, 0.5f}, {0.5f, 0.4f}, F_HP12,
     700, 0.3f, -0.4f, 0.5f, 0.01f, 0.6f, 0.7f, 0.5f, 0.005f, 0.4f, 0.3f, 0.4f, 0, 0.81f},
    /* Choir: detuned saws, slow, an "ah" (formant) */
    {{W_SAW, W_SAW}, {0, 0}, {-9, 9}, {0.8f, 0.8f}, {0.5f, 0.5f}, F_FORMANT,
     1342, 0.5f, 0.15f, 0.0f, 0.45f, 0.6f, 0.9f, 1.1f, 0.7f, 1.0f, 0.7f, 1.1f, 0, 1.0f},
    /* Vox: pulse and saw, the vowel opening "oh" to "ah" on each chord (formant) */
    {{W_PULSE, W_SAW}, {0, 0}, {0, 6}, {0.8f, 0.6f}, {0.3f, 0.5f}, F_FORMANT,
     369, 0.5f, 0.6f, 0.0f, 0.01f, 0.3f, 0.8f, 0.3f, 0.02f, 0.35f, 0.25f, 0.3f, 0.03f, 1.0f},
    /* Talk: saw and a saw an octave up, the vowel dipping from "eh" towards "oh" and back on
     * each chord (formant) */
    {{W_SAW, W_SAW}, {0, 1}, {0, 4}, {0.85f, 0.5f}, {0.5f, 0.5f}, F_FORMANT,
     4874, 0.5f, -0.7f, 0.0f, 0.005f, 0.4f, 0.6f, 0.25f, 0.005f, 0.25f, 0.0f, 0.2f, 0, 1.0f},
};

/* ---- scales (semitones from the root), in knob order --------------------------------- */

static const int8_t SC_MAJOR[] = {0, 2, 4, 5, 7, 9, 11};
static const int8_t SC_MINOR[] = {0, 2, 3, 5, 7, 8, 10};
static const int8_t SC_MIN_PENT[] = {0, 3, 5, 7, 10};
static const int8_t SC_HARM_MINOR[] = {0, 2, 3, 5, 7, 8, 11};
static const int8_t SC_DORIAN[] = {0, 2, 3, 5, 7, 9, 10};
static const int8_t SC_PHRYGIAN[] = {0, 1, 3, 5, 7, 8, 10};
static const int8_t SC_MAJ_PENT[] = {0, 2, 4, 7, 9};
static const int8_t SC_MIXOLYDIAN[] = {0, 2, 4, 5, 7, 9, 10};
static const int8_t SC_BLUES[] = {0, 3, 5, 6, 7, 10};
static const int8_t SC_PHRYG_DOM[] = {0, 1, 4, 5, 7, 8, 10};
static const int8_t SC_CHROMATIC[] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11};

static const struct { const int8_t *n; uint8_t len; } SCALES[NSCALE] = {
    {SC_MAJOR, 7}, {SC_MINOR, 7}, {SC_MIN_PENT, 5}, {SC_HARM_MINOR, 7}, {SC_DORIAN, 7},
    {SC_PHRYGIAN, 7}, {SC_MAJ_PENT, 5}, {SC_MIXOLYDIAN, 7}, {SC_BLUES, 6}, {SC_PHRYG_DOM, 7},
    {SC_CHROMATIC, 12},
};
#define SCALE_CHROMATIC 10

/* the roots (semitones above C) of the 11 positions: all but D# / Eb */

/* the fixed chord shapes (semitones above the chord's root) */
/* fixed shapes: the note count, then the intervals */
static const int8_t SHAPE_M7[] = {4, 0, 3, 7, 10};
static const int8_t SHAPE_QUARTAL[] = {4, 0, 5, 10, 15};
static const int8_t SHAPE_POWER[] = {3, 0, 7, 12};
static const int8_t SHAPE_MAJOR[] = {3, 0, 4, 7};          /* Diatonic on Chromatic */
static const int8_t SHAPE_M9[] = {5, 0, 3, 7, 10, 14};     /* Diatonic 9th on Chromatic */

/* ---- the object ------------------------------------------------------------------------ */

typedef struct {
    float lvl;
    float a_c, a_b;                     /* per step: lvl = b + lvl * c (attack, decay, release) */
    float d_c, d_b, r_c, r_b;
    float sus;                          /* sustain level */
    int32_t stage;
} adsr_t;

typedef struct {
    float phase, inc, target;           /* target: the glide's end (== inc when not gliding) */
} osc_t;

typedef struct {
    int32_t stage;                      /* +0: the amp envelope's stage (IDLE: free) */
    int8_t note[NNOTE];                 /* +4: MIDI notes, low to high (unused: -1) */
    uint8_t preset;                     /* +9 */
    uint8_t count;                      /* +10: notes */
    float norm;                         /* level for the note count */
    int32_t gate;                       /* gate length in samples; -1: drone */
    int32_t elapsed;                    /* samples since the chord started */
    int32_t released;
    int32_t steal;                      /* > 0: fading out for a new chord, samples left */
    uint32_t age;                       /* trigger order */
    float amp;                          /* velocity */
    float glide_a;                      /* per-sample glide coefficient; 0: none */
    int32_t gliding;
    adsr_t aenv, fenv;
    float key_track;                    /* cutoff multiplier for the chord's root */
    float u_cut, u_res, u_env;          /* the preset's cutoff / resonance / env amount, as knob positions */
    osc_t osc[NNOTE][2];
    float drift[NNOTE];                 /* each note's own detune (a frequency ratio) */
    uint8_t wave[2], fmode, pad;
    float level[2], pw[2];
    float low, band, low2, band2;       /* SVF states (formant TPT: the integrators' ic2eq / ic1eq) */
    float f, q;                         /* smoothed SVF coefficients (Chamberlin f, damping) */
    int32_t coef_age;
    float in_gain;                      /* the filter's input: less as the resonance rises */
    float low3, band3;                  /* formant: the third band's states */
    float ff[3];                        /* formant: the three bands' smoothed g */
    float fa[3][3];                     /* formant: their TPT coefficients */
} slot_t;

typedef struct {
    int8_t note[NNOTE];                 /* low to high, unused -1 */
    int8_t from[NNOTE];                 /* the chord before it (glide) */
    uint8_t count;
    int8_t root;
    uint8_t preset, has_from;
    float amp;
    int32_t gate;
} chord_t;

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
    uint8_t set[4];                     /* +0xc0 preset, chord, scale, root (indices) */
    int8_t last[NNOTE];                 /* +0xc4 the last chord played, low to high, unused -1 */
    uint8_t have_last;                  /* +0xc9 */
    uint8_t pad2[2];
    uint32_t slot_size;                 /* +0xcc sizeof(slot_t), for tools */
    slot_t slot[NSLOT];                 /* +0xd0 */
    float val[NVAL];                    /* the knob values (PLAY ones in their units) */
    int32_t role[2];                    /* what PARAM1 / PARAM2 set now (V_*), -1 none */
    float ref[2];                       /* the knob when it got that job */
    int32_t armed[2];                   /* it has moved since: it sets the value */
    float tune_pos;                     /* TUNE step (hysteresis memory) */
    int32_t tune_scale;                 /* the scale tune_pos belongs to */
    int32_t gate_samples;               /* GATE now; -1: drone */
    int32_t tune_since;                 /* the newest chord's elapsed when TUNE left it; -1 */
    uint32_t age;
    int32_t pending;                    /* slot waiting for its steal fade, -1 none */
    int32_t newest;                     /* the slot of the last chord; -1 none, -2 pending */
    int8_t prev[NNOTE];                 /* the chord before it (the smooth voicing's reference) */
    uint8_t have_prev;
    chord_t next;                       /* the chord it then plays */
    float dc_x, dc_y;                   /* the output's DC blocker */
    float lim;                          /* the output limiter's peak follower */
    uint32_t out;                       /* the output it plays on (its settings) */
    int32_t fsel;                       /* the filter MODE chose; -1: the preset's own */
    uint8_t mode_ref;                   /* MODE when the preset was chosen */
    uint8_t preset_ref;                 /* the preset fsel / mode_ref belong to */
    uint32_t rng;                       /* the notes' detune (a new one each chord) */
    float dgain, dgain_t;               /* the level for DRIVE: now (smoothed), target */
    int32_t prog;                       /* the progression offset of the newest chord */
    int32_t hold;                       /* SOUND_HOLD: the knobs set nothing yet */
} ak_t;

_Static_assert(__builtin_offsetof(ak_t, algo) == OFF_cVoice_algo, "algo");
_Static_assert(__builtin_offsetof(ak_t, mode) == OFF_cVoice_mode, "mode");
_Static_assert(__builtin_offsetof(ak_t, velocity) == OFF_cVoice_velocity, "velocity");
_Static_assert(__builtin_offsetof(ak_t, note) == OFF_cVoice_accent, "note (accent)");
_Static_assert(__builtin_offsetof(ak_t, param) == OFF_cVoice_param_ptrs, "param pointers");
_Static_assert(__builtin_offsetof(ak_t, mute) == OFF_cVoice_mute, "mute");
_Static_assert(__builtin_offsetof(ak_t, gain) == OFF_cVoice_gain, "gain");
_Static_assert(__builtin_offsetof(ak_t, set) == 0xc0, "set");
_Static_assert(__builtin_offsetof(ak_t, last) == 0xc4, "last");
_Static_assert(__builtin_offsetof(ak_t, slot_size) == 0xcc, "slot_size");
_Static_assert(__builtin_offsetof(ak_t, slot) == 0xd0, "slot");
_Static_assert(__builtin_offsetof(slot_t, note) == 4 && __builtin_offsetof(slot_t, preset) == 9 &&
               __builtin_offsetof(slot_t, count) == 10, "slot");
_Static_assert(sizeof(ak_t) <= 0x4000, "fits a voice-map arena");

/* ---- small maths (no libm) --------------------------------------------------------- */

#define INLINE static inline __attribute__((always_inline))

INLINE float clampf(float x, float lo, float hi)
{
    return x < lo ? lo : (x > hi ? hi : x);
}

INLINE float absf(float x)
{
    return x < 0.0f ? -x : x;
}

/* 2^x, |x| < 100 (as voice-zibens) */
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

/* log2(x), x > 0: exponent by bits, the mantissa by a polynomial (~1e-4) */
static float log2f_(float x)
{
    union { float f; uint32_t u; } v = {x};
    int e = (int)((v.u >> 23) & 0xff) - 127;
    v.u = (v.u & 0x7fffff) | 0x3f800000;
    float m = v.f;
    return (float)e - 1.7417939f + (2.8212026f + (-1.4699568f + (0.44717955f - 0.056570851f * m) * m) * m) * m;
}

/* tan(x) for 0 <= x <= ~1.2 (Pade) */
static inline float tanf_(float x)
{
    float x2 = x * x;
    return x * (15.0f - x2) / (15.0f - 6.0f * x2);
}

static inline float mtof(float midi)
{
    return 440.0f * exp2f_((midi - 69.0f) * (1.0f / 12.0f));
}

/* the iOS synth's fast sine for a phase in [0, 1) */
INLINE float fast_sin(float p)
{
    float x = (p - 0.5f) * (2.0f * PI);
    const float b = 4.0f / PI, c = -4.0f / (PI * PI);
    float y = b * x + c * x * absf(x);
    return 0.225f * (y * absf(y) - y) + y;
}

/* The band-limited step correction for a unit jump of -2 (a saw's wrap) at phase 0, a
 * phase step dt per sample: the cubic B-spline BLEP, spread over two samples each side of
 * the jump (the common PolyBLEP spreads it over one): aliases ~10 dB lower (15-20 below 5 kHz),
 * for a slightly softer top octave. Needs dt <= 0.25 (12 kHz). */
INLINE float blep(float t, float dt)
{
    if (t < dt + dt) {                  /* just after the jump */
        float u = t / dt;
        if (u < 1.0f) {
            float u2 = u * u;
            return (4.0f * u - 2.0f * u2 * u + 0.75f * u2 * u2) * (1.0f / 3) - 1.0f;
        }
        float w = 2.0f - u;
        w *= w;
        return w * w * (-1.0f / 12);
    }
    if (t > 1.0f - dt - dt) {           /* just before it */
        float u = (1.0f - t) / dt;
        if (u < 1.0f) {
            float u2 = u * u;
            return 1.0f - (4.0f * u - 2.0f * u2 * u + 0.75f * u2 * u2) * (1.0f / 3);
        }
        float w = 2.0f - u;
        w *= w;
        return w * w * (1.0f / 12);
    }
    return 0.0f;
}

INLINE float blamp(float t, float dt)
{
    if (t < dt) {
        float n = t / dt;
        return dt * (n * n - n * n * n * (1.0f / 3) - n);
    }
    if (t > 1.0f - dt) {
        float n = (t - 1.0f) / dt;
        return -dt * (n * n * n * (1.0f / 3) + n * n + n);
    }
    return 0.0f;
}

static inline float knob(const ak_t *a, int k)
{
    return clampf((float)*a->param[k] * (1.0f / 4095.0f), 0.0f, 1.0f);
}

/* each output's settings from the M4: preset, chord type, scale, root (VOICE RAM, kept
 * across voice-map rebuilding the arena) */
static uint8_t settings[4][4];
/* what's waiting for this output's engine: a preset pressed on the page, a kit's sound
 * (with what's in the message's own bits, below) */
#define WAIT_PRESSED    0x80
#define WAIT_SOUND      0x40
#define SOUND_HOLD      0x20        /* the kit's positions haven't arrived: they set nothing */
#define SOUND_OWN       0x10        /* the preset's own filter (not yet MODE's) */
#define SOUND_ARM2      0x08        /* PARAM2 follows the knob */
#define SOUND_ARM1      0x04        /* PARAM1 follows the knob */
#define SOUND_ROLE      0x03        /* what PARAM2 sets: V_RES, V_ENV, V_ATTACK */
static uint8_t waiting[4];
static uint8_t sound[4][NVAL];          /* a kit's PLAY values, 0-255 */
static const uint8_t LIMIT[4] = {NPRESET, NCHORD, NSCALE, NROOT};

/* each output's DRIVE from the M4 (0-255; message "akords-drive", sent when it changes) */
static uint8_t drive[4];

void pk_ak_on_drive(const uint8_t *buf, uint32_t len)
{
    if (len >= 4)
        for (int i = 0; i < 4; i++)
            drive[i] = buf[i];
}

/* each output's progression offset from the M4 (scale degrees; message "akords-prog") */
static int8_t prog_off[4];

void pk_ak_on_prog(const uint8_t *buf, uint32_t len)
{
    if (len >= 4)
        for (int i = 0; i < 4; i++)
            prog_off[i] = (int8_t)(buf[i] <= 6 ? buf[i] : 0);
}

/* the level for the output's DRIVE (a gain) */
static float drive_gain(const ak_t *a)
{
    float d = (float)drive[a->out & 3] * (1.0f / 255.0f);
    float db = d < 0.5f ? DRIVE_BOOST_DB * (1.0f - 2.0f * d) : -DRIVE_CUT_DB * (2.0f * d - 1.0f);
    return exp2f_(db * (1.0f / 6.0205999f));
}

/* 16 bytes: [output][preset, chord, scale, root]; a 17th: the outputs (bits) whose preset
 * was just pressed on the page: they take all its own settings again */
void pk_ak_on_settings(const uint8_t *buf, uint32_t len)
{
    if (len < 16)
        return;
    for (int i = 0; i < 16; i++)
        settings[i / 4][i % 4] = buf[i] < LIMIT[i % 4] ? buf[i] : 0;
    if (len > 16)
        for (int v = 0; v < 4; v++)
            if (buf[16] & (1u << v))
                waiting[v] |= WAIT_PRESSED;
}

/* 4 x [flags, cutoff, resonance, env amount, attack]: the outputs with WAIT_SOUND take it */
void pk_ak_on_sound(const uint8_t *buf, uint32_t len)
{
    if (len < 20)
        return;
    for (int v = 0; v < 4; v++, buf += 5)
        if (buf[0] & WAIT_SOUND) {
            waiting[v] = (uint8_t)((waiting[v] & WAIT_PRESSED) | buf[0]);
            for (int i = 0; i < NVAL; i++)
                sound[v][i] = buf[1 + i];
        }
}

/* ---- control ----------------------------------------------------------------------------- */

/* DECAY knob -> GATE seconds: ~0.05 s fully left to ~2 s at 95%, log-linear; above 95%
 * (the panel knobs stop short of their ends) returns 0 (drone) */
#define DRONE_AT    0.95f

static float gate_time(float d)
{
    if (d >= DRONE_AT)
        return 0.0f;
    return 0.05f * exp2f_(d * (5.3219281f / DRONE_AT));    /* 0.05 * 40^(d / 0.95) */
}

/* A PLAY knob is relative to the preset: around 12 o'clock is the preset's own value `p`
 * (as a knob position 0..1), fully left / right the ends of the range */
#define DETENT  0.02f               /* +-2% around 12 o'clock is the preset's value */

static inline float warp(float k, float p)
{
    float d = k - 0.5f;
    if (d > -DETENT && d < DETENT)
        return p;
    if (d < 0.0f)
        return p * (k / (0.5f - DETENT));
    return p + (1.0f - p) * ((d - DETENT) / (0.5f - DETENT));
}

#define CUT_MIN     100.0f          /* cutoff: 100 Hz (the iOS synth's scale: ~50 Hz) .. 18 kHz; */
#define CUT_OCT     7.4919f         /* lower, the knob's bottom was silent */
#define ATT_OCT     11.5507f        /* attack: 1 ms .. 3 s */

static float cutoff_pos(float hz)
{
    return clampf(log2f_(hz * (1.0f / CUT_MIN)) * (1.0f / CUT_OCT), 0.0f, 1.0f);
}

static float attack_time(const ak_t *a, const preset_t *pr)
{
    float p = clampf(log2f_(pr->a_att * 1000.0f) * (1.0f / ATT_OCT), 0.0f, 1.0f);
    return 0.001f * exp2f_(warp(a->val[V_ATTACK], p) * ATT_OCT);
}

/* the job of PARAM1 (k = 0) / PARAM2 (k = 1) for ALGO now */
static int role_of(const ak_t *a, int k)
{
    if (k == 0)
        return V_CUTOFF;
    return a->algo == POS1 ? V_RES : (a->algo == POS3 ? V_ATTACK : V_ENV);
}

/* MODE: the filter (top to bottom: 24 dB low-pass, 12 dB high-pass, formant) */
static int mode_filter(int mode)
{
    return mode == POS1 ? F_LP24 : (mode == POS3 ? F_FORMANT : F_HP12);
}

/* the filter: the preset's own, until MODE moves after the preset was chosen. Not from
 * init: voice-map writes ALGO / MODE back after it */
static void track_filter(ak_t *a)
{
    if (a->set[0] != a->preset_ref) {
        a->preset_ref = a->set[0];
        a->mode_ref = a->mode;
        a->fsel = -1;
    }
    if (a->hold && a->fsel < 0)         /* a kit's own filter: its MODE is still arriving */
        a->mode_ref = a->mode;
    if (a->fsel >= 0 || a->mode != a->mode_ref)
        a->fsel = mode_filter(a->mode);
}

static void read_knobs(ak_t *a)
{
    for (int i = 0; i < 4; i++)
        a->set[i] = settings[a->out & 3][i];
    uint8_t w = waiting[a->out & 3];
    waiting[a->out & 3] = 0;
    if (w & WAIT_PRESSED) {             /* a preset pressed: all its own values, its own */
        for (int i = 0; i < NVAL; i++)  /* filter; each knob takes over when it moves */
            a->val[i] = 0.5f;
        for (int k = 0; k < 2; k++) {
            a->armed[k] = 0;
            a->ref[k] = knob(a, 2 + k);
        }
        a->preset_ref = 0xff;           /* track_filter: the preset's filter, MODE now */
        a->hold = 0;
    }
    if (w & WAIT_SOUND) {               /* a kit's sound (after a press sent before it) */
        for (int i = 0; i < NVAL; i++)
            a->val[i] = (float)sound[a->out & 3][i] * (1.0f / 255.0f);
        a->role[0] = V_CUTOFF;
        a->role[1] = w & SOUND_ROLE;
        a->armed[0] = (w & SOUND_ARM1) != 0;
        a->armed[1] = (w & SOUND_ARM2) != 0;
        a->fsel = w & SOUND_OWN ? -1 : mode_filter(a->mode);
        a->preset_ref = a->set[0];
        a->mode_ref = a->mode;
        a->ref[0] = knob(a, 2);
        a->ref[1] = knob(a, 3);
        a->hold = (w & SOUND_HOLD) != 0;
    }
    for (int k = 0; k < 2; k++) {
        float x = knob(a, 2 + k);
        if (a->hold) {
            a->ref[k] = x;
            continue;
        }
        int r = role_of(a, k);
        if (r != a->role[k]) {          /* a new job: keep the value until the knob moves */
            a->armed[k] = a->role[k] < 0;   /* (just built: the knobs are the settings) */
            a->role[k] = r;
            a->ref[k] = x;
        }
        if (!a->armed[k] && absf(x - a->ref[k]) > MOVED)
            a->armed[k] = 1;
        if (a->armed[k])
            a->val[r] = x;              /* a knob position, relative to the preset (warp) */
    }
    float g = gate_time(knob(a, 1));
    a->gate_samples = g > 0.0f ? (int32_t)(g * SR) : -1;
    a->dgain_t = drive_gain(a);
}

static void follow(ak_t *a);

static void update(cVoice *v)
{
    ak_t *a = (ak_t *)v;
    if (a->magic != MAGIC)
        return;
    read_knobs(a);
    track_filter(a);
    follow(a);
}

/* ---- chords -------------------------------------------------------------------------------- */

static int in_scale(int scale, int semis)
{
    int pc = ((semis % 12) + 12) % 12;
    for (int i = 0; i < SCALES[scale].len; i++)
        if (SCALES[scale].n[i] == pc)
            return 1;
    return 0;
}

/* the scale's note at `deg` (any integer) in semitones from the root */
static int degree(int scale, int deg)
{
    int len = SCALES[scale].len;
    int o = deg >= 0 ? deg / len : -((len - 1 - deg) / len);
    return 12 * o + SCALES[scale].n[deg - o * len];
}

/* the first of the candidate intervals above `r` that is in the scale */
static int pick(int scale, int r, const int8_t *cand, int n)
{
    for (int i = 0; i < n; i++)
        if (in_scale(scale, r + cand[i]))
            return cand[i];
    return cand[0];
}

/* intervals of the in-key chord on the scale's degree `deg` (r: its semitones from the
 * root). 7-note scales stack the scale's own thirds; the others take the nearest third
 * (a sus 4th / 2nd if the scale has none), fifth or seventh the scale has. */
/* the chord the scale gives on degree `deg` (root r): 3 notes (triad), 4 (7th) or 5 (9th);
 * the 7-note scales stack their own thirds, the others take the nearest the scale has */
static void diatonic(int scale, int deg, int r, int cnt, int8_t *iv)
{
    static const int8_t THIRD[] = {4, 3, 5, 2}, FIFTH[] = {7, 6, 8, 12}, SEVENTH[] = {10, 11, 9, 12},
                        NINTH[] = {14, 13, 15, 12};
    static const int8_t *const CAND[4] = {THIRD, FIFTH, SEVENTH, NINTH};
    iv[0] = 0;
    for (int i = 1; i < cnt; i++)
        iv[i] = (int8_t)(SCALES[scale].len == 7 ? degree(scale, deg + 2 * i) - r : pick(scale, r, CAND[i - 1], 4));
}

static void sort_notes(int *n, int cnt)
{
    for (int i = 1; i < cnt; i++)
        for (int j = i; j > 0 && n[j - 1] > n[j]; j--) {
            int t = n[j];
            n[j] = n[j - 1];
            n[j - 1] = t;
        }
}

/* how far a voicing is from the chord before: with as many notes, voice by voice (each
 * voice moves to the next); else each note to the nearest of the other chord's, both ways */
static int voicing_distance(const int *c, int cnt, const int8_t *last)
{
    int d = 0, n = 0;
    while (n < NNOTE && last[n] >= 0)
        n++;
    if (n == cnt) {
        for (int i = 0; i < cnt; i++)
            d += c[i] > last[i] ? c[i] - last[i] : last[i] - c[i];
        return d;
    }
    for (int i = 0; i < cnt; i++) {
        int m = 1 << 20;
        for (int j = 0; j < NNOTE && last[j] >= 0; j++) {
            int e = c[i] > last[j] ? c[i] - last[j] : last[j] - c[i];
            m = e < m ? e : m;
        }
        d += m;
    }
    for (int j = 0; j < NNOTE && last[j] >= 0; j++) {
        int m = 1 << 20;
        for (int i = 0; i < cnt; i++) {
            int e = c[i] > last[j] ? c[i] - last[j] : last[j] - c[i];
            m = e < m ? e : m;
        }
        d += m;
    }
    return d;
}

/* the voicing of n[] (root position, low to high) nearest the last chord: one of its
 * three inversions, an octave up or down; no further, so it never drifts from TUNE */
static void nearest(const int8_t *last, int *n, int cnt)
{
    int best[NNOTE], bd = 1 << 30, bshift = 1 << 30;
    for (int inv = 0; inv < cnt; inv++)
        for (int oct = -12; oct <= 0; oct += 12) {
            int c[NNOTE];
            for (int i = 0; i < cnt; i++)
                c[i] = n[(inv + i) % cnt] + (inv + i >= cnt ? 12 : 0) + oct;
            int d = voicing_distance(c, cnt, last);
            int shift = c[0] > n[0] ? c[0] - n[0] : n[0] - c[0];
            if (d < bd || (d == bd && shift < bshift)) {
                bd = d;
                bshift = shift;
                for (int i = 0; i < cnt; i++)
                    best[i] = c[i];
            }
        }
    for (int i = 0; i < cnt; i++)
        n[i] = best[i];
}

static int any_sounding(const ak_t *a)
{
    for (int s = 0; s < NSLOT; s++)
        if (a->slot[s].stage != IDLE)
            return 1;
    return a->pending >= 0;
}

/* smooth Power: root position (1 5 8) or the fifth below (5 1 5), an octave up or down,
 * whichever is nearest the chord before (inverting would double the octave) */
static void nearest_power(const int8_t *last, int *n, int cnt)
{
    int r = n[0], best[NNOTE] = {n[0], n[1], n[2]}, bd = 1 << 30;
    static const int8_t SHAPE[2][3] = {{0, 7, 12}, {-5, 0, 7}};
    (void)cnt;
    for (int sh = 0; sh < 2; sh++)
        for (int oct = -12; oct <= 0; oct += 12) {
            int c[NNOTE];
            for (int i = 0; i < 3; i++)
                c[i] = r + SHAPE[sh][i] + oct;
            int d = voicing_distance(c, 3, last);
            if (d < bd) {
                bd = d;
                for (int i = 0; i < 3; i++)
                    best[i] = c[i];
            }
        }
    for (int i = 0; i < 3; i++)
        n[i] = best[i];
}

/* the chord a trigger plays now; `ref` / `has_ref`: the chord before (smooth types) */
static void make_chord(ak_t *a, chord_t *c, const int8_t *ref, int has_ref)
{
    int scale = a->set[2], len = SCALES[scale].len;
    int steps = OCTAVES * len;                  /* the top root included: steps + 1 roots */
    float pos = knob(a, 0) * (float)steps;
    if (a->tune_scale != scale || a->tune_pos < 0.0f) {
        a->tune_scale = scale;
        a->tune_pos = (float)(int32_t)(pos + 0.5f);
    } else if (pos > a->tune_pos + 0.5f + HYST || pos < a->tune_pos - 0.5f - HYST) {
        a->tune_pos = (float)(int32_t)(pos + 0.5f);
    }
    int step = (int)a->tune_pos + a->prog;      /* the progression: scale degrees above */
    int r = degree(scale, step);                /* the chord's root, semitones from the scale's */

    int8_t iv[NNOTE];
    const int8_t *shape = 0;
    int type = a->set[1], cnt = 3;
    switch (type) {
    case CH_DIA: case CH_DIA_S:
    case CH_DIA7: case CH_DIA7_S:
    case CH_DIA9: case CH_DIA9_S:
        cnt = type >= CH_DIA9 ? 5 : (type >= CH_DIA7 ? 4 : 3);
        if (scale == SCALE_CHROMATIC)
            shape = cnt == 5 ? SHAPE_M9 : (cnt == 4 ? SHAPE_M7 : SHAPE_MAJOR);
        else
            diatonic(scale, step, r, cnt, iv);
        break;
    case CH_QUARTAL: case CH_QUARTAL_S:
        shape = SHAPE_QUARTAL;
        break;
    default:
        shape = SHAPE_POWER;
        break;
    }
    if (shape) {
        cnt = shape[0];
        for (int i = 0; i < cnt; i++)
            iv[i] = shape[1 + i];
    }

    int note = a->note ? a->note : NOTE_REF;
    int root = BASE_NOTE + a->set[3] + r + note - NOTE_REF;
    int n[NNOTE];
    for (int i = 0; i < cnt; i++)
        n[i] = root + iv[i];
    sort_notes(n, cnt);
    if ((type & 1) && has_ref)          /* the "smooth" types (odd positions) */
        (type == CH_POWER_S ? nearest_power : nearest)(ref, n, cnt);
    sort_notes(n, cnt);
    c->count = (uint8_t)cnt;
    for (int i = 0; i < NNOTE; i++)
        c->note[i] = i < cnt ? (int8_t)clampf((float)n[i], 0.0f, 127.0f) : -1;
    c->root = (int8_t)clampf((float)root, 0.0f, 127.0f);
    c->preset = a->set[0];
    c->amp = (float)a->velocity * (1.0f / 127.0f);
    c->gate = a->gate_samples;
}

/* ---- envelopes ------------------------------------------------------------------------ */

/* Exponential (analog-style, RC) ADSR: each segment heads for a target past its end, so it
 * ends on time: attack towards 1 + ATT_RATIO (a rising curve that reaches 1 in the attack
 * time), decay and release towards their level - DR_RATIO (the RC fall). The presets'
 * decay and release times (the iOS synth's, for a linear ADSR) are stretched by DR_STRETCH, so an
 * envelope falls to -20 dB when the linear one did. `n` samples a step. */
#define ATT_RATIO   0.3f
#define DR_RATIO    0.01f
#define ATT_LOG2    2.1154772f      /* log2((1 + ATT_RATIO) / ATT_RATIO) */
#define DR_LOG2     6.6582115f      /* log2((1 + DR_RATIO) / DR_RATIO) */
#define DR_STRETCH  1.85f

/* the per-step factor of a segment lasting t seconds */
static float seg_coef(float t, float lg, float n)
{
    float steps = t * SR / n;
    return steps > 1.0f ? exp2f_(-lg / steps) : 0.0f;
}

static void adsr_attack(adsr_t *e, float att, float n)
{
    e->a_c = seg_coef(att, ATT_LOG2, n);
    e->a_b = (1.0f + ATT_RATIO) * (1.0f - e->a_c);
}

static void adsr_start(adsr_t *e, float att, float dec, float sus, float rel, float n)
{
    e->lvl = 0.0f;
    adsr_attack(e, att, n);
    e->d_c = seg_coef(dec * DR_STRETCH, DR_LOG2, n);
    e->d_b = (sus - DR_RATIO) * (1.0f - e->d_c);
    e->r_c = seg_coef(rel * DR_STRETCH, DR_LOG2, n);
    e->r_b = -DR_RATIO * (1.0f - e->r_c);
    e->sus = sus;
    e->stage = ATTACK;
}

static void adsr_release(adsr_t *e)
{
    if (e->stage != IDLE)
        e->stage = RELEASE;
}

INLINE float adsr_step(adsr_t *e)
{
    switch (e->stage) {
    case ATTACK:
        e->lvl = e->a_b + e->lvl * e->a_c;
        if (e->lvl >= 1.0f) {
            e->lvl = 1.0f;
            e->stage = DECAY;
        }
        break;
    case DECAY:
        e->lvl = e->d_b + e->lvl * e->d_c;
        if (e->lvl <= e->sus) {
            e->lvl = e->sus;
            e->stage = e->sus > 0.0f ? SUSTAIN : IDLE;
        }
        break;
    case RELEASE:
        e->lvl = e->r_b + e->lvl * e->r_c;
        if (e->lvl <= 0.0f) {
            e->lvl = 0.0f;
            e->stage = IDLE;
        }
        break;
    default:
        break;
    }
    return e->lvl;
}

/* ---- slots ----------------------------------------------------------------------------- */

/* the note of the chord before that note i glides from: the same position, else its top */
static int from_note(const chord_t *c, int i)
{
    if (c->from[0] < 0)
        return -1;
    while (i > 0 && c->from[i] < 0)
        i--;
    return c->from[i];
}

/* an oscillator's frequency ratio: its octave and detune */
static float osc_ratio(const preset_t *pr, int k)
{
    return exp2f_((float)pr->oct[k] + pr->detune[k] * (1.0f / 1200.0f));
}

/* a chord note's own small detune (both its oscillators), new each chord, as the notes of
 * an analog polysynth never quite agree: the chord beats gently instead of locking */
static float note_drift(ak_t *a)
{
    a->rng = a->rng * 1664525u + 1013904223u;
    float r = (float)(int32_t)a->rng * (1.0f / 2147483648.0f);     /* -1 .. 1 */
    return exp2f_(r * DRIFT_CENTS * (1.0f / 1200.0f));
}

/* the level for a chord of cnt notes: about the same loudness as 3 */
static float count_norm(int cnt)
{
    return cnt >= 5 ? 0.7746f : (cnt == 4 ? 0.8660f : 1.0f);    /* sqrt(3 / cnt) */
}

static void start_slot(ak_t *a, slot_t *s, const chord_t *c)
{
    const preset_t *pr = &PRESETS[c->preset];
    int glide = pr->glide > 0.0f && c->has_from;
    for (int i = 0; i < NNOTE; i++)
        s->drift[i] = note_drift(a);
    for (int i = 0; i < c->count; i++)
        for (int k = 0; k < 2; k++) {
            float ratio = osc_ratio(pr, k) * s->drift[i];
            float to = clampf(mtof((float)c->note[i]) * ratio, 8.0f, 12000.0f) / SR;
            int f = from_note(c, i);
            float from = glide && f >= 0 ? clampf(mtof((float)f) * ratio, 8.0f, 12000.0f) / SR : to;
            s->osc[i][k].phase = 0.0f;
            s->osc[i][k].inc = from;
            s->osc[i][k].target = to;
        }
    s->gliding = glide;
    s->glide_a = glide ? 1.0f - exp2f_(-3.0f * 1.442695f / (pr->glide * SR)) : 0.0f;
    for (int k = 0; k < 2; k++) {
        s->wave[k] = pr->wave[k];
        s->level[k] = pr->level[k];
        s->pw[k] = pr->pw[k];
    }
    s->fmode = (uint8_t)(a->fsel >= 0 ? a->fsel : pr->fmode);
    s->key_track = exp2f_(((float)c->root - 60.0f) * pr->key_track * (1.0f / 12.0f));
    s->u_cut = cutoff_pos(pr->cutoff);
    s->u_res = pr->res;
    s->u_env = 0.5f * (pr->env_amt + 1.0f);
    adsr_start(&s->aenv, attack_time(a, pr), pr->a_dec, pr->a_sus, pr->a_rel, 1.0f);
    adsr_start(&s->fenv, pr->f_att, pr->f_dec, pr->f_sus, pr->f_rel, (float)COEF_EVERY);
    s->low = s->band = s->low2 = s->band2 = s->low3 = s->band3 = 0.0f;
    s->ff[0] = s->ff[1] = s->ff[2] = 0.0f;
    s->f = 0.0f;
    s->q = 1.0f;
    for (int b = 0; b < 3; b++) {
        s->fa[b][0] = 1.0f;
        s->fa[b][1] = s->fa[b][2] = 0.0f;
    }
    s->in_gain = 1.0f;
    s->coef_age = 0;
    for (int i = 0; i < NNOTE; i++)
        s->note[i] = c->note[i];
    s->count = c->count;
    s->norm = count_norm(c->count);
    s->preset = c->preset;
    s->gate = c->gate;
    s->elapsed = 0;
    s->released = 0;
    s->steal = 0;
    s->amp = c->amp * pr->gain;
    s->age = ++a->age;
    s->stage = ATTACK;
}

static void trigger(cVoice *v)
{
    ak_t *a = (ak_t *)v;
    if (a->magic != MAGIC)
        return;
    read_knobs(a);
    track_filter(a);
    a->prog = prog_off[a->out & 3];     /* this chord's place in the progression */
    a->have_prev = a->have_last && any_sounding(a);         /* after a silence: root position */
    for (int i = 0; i < NNOTE; i++)
        a->prev[i] = a->last[i];
    chord_t c;
    make_chord(a, &c, a->prev, a->have_prev);
    c.has_from = a->have_last;
    for (int i = 0; i < NNOTE; i++) {
        c.from[i] = a->last[i];
        a->last[i] = c.note[i];
    }

    for (int s = 0; s < NSLOT; s++)     /* the chord sounding fades out in STEAL_SAMPLES */
        if (a->slot[s].stage != IDLE && !a->slot[s].steal)
            a->slot[s].steal = STEAL_SAMPLES;
    int free_slot = -1, oldest = 0;
    for (int s = 0; s < NSLOT; s++) {
        if (a->slot[s].stage == IDLE && s != a->pending) {
            free_slot = s;
            break;
        }
        if (a->slot[s].age < a->slot[oldest].age)
            oldest = s;
    }
    if (free_slot >= 0) {
        start_slot(a, &a->slot[free_slot], &c);
        a->newest = free_slot;
        a->tune_since = -1;
    } else {                            /* the new chord takes the slot after the fade */
        if (a->pending < 0) {
            a->pending = oldest;
            a->slot[oldest].steal = STEAL_SAMPLES;
        }
        a->next = c;
        a->newest = -2;
    }
    a->have_last = 1;
}

/* As on voice-zibens, TUNE and DECAY act on what is sounding: the newest chord follows
 * TUNE (the older one, ringing out, keeps its notes), and every chord not yet released
 * follows GATE (so turning DECAY down from drone releases the drones). In its first
 * FOLLOW_SAMPLES a new chord follows TUNE at once (the M4 can send a step's TUNE just
 * after its trigger); later a new TUNE step must hold SETTLE_SAMPLES first, so a step's
 * TUNE arriving just before its trigger doesn't retune the chord before it. */
static void follow(ak_t *a)
{
    for (int i = 0; i < NSLOT; i++) {
        slot_t *t = &a->slot[i];
        if (!t->released)
            t->gate = a->gate_samples;
        if (t->stage != IDLE) {         /* MODE's filter acts on the sounding chords too */
            uint8_t fm = (uint8_t)(a->fsel >= 0 ? a->fsel : PRESETS[t->preset].fmode);
            if (fm != t->fmode) {
                if (fm == F_FORMANT || t->fmode == F_FORMANT)
                    t->low = t->band = t->low2 = t->band2 = t->low3 = t->band3 = 0.0f;
                t->fmode = fm;
            }
        }
        if (t->aenv.stage == ATTACK)    /* the attack follows its knob too (from where it is: no click) */
            adsr_attack(&t->aenv, attack_time(a, &PRESETS[t->preset]), 1.0f);
    }
    slot_t *s = a->newest >= 0 ? &a->slot[a->newest] : 0;
    if (a->newest == -1 || (s && (s->stage == IDLE || s->steal)))
        return;
    chord_t c;
    make_chord(a, &c, a->prev, a->have_prev);
    if (!s) {                           /* still waiting for its slot */
        for (int i = 0; i < NNOTE; i++)
            a->next.note[i] = c.note[i];
        a->next.count = c.count;
        a->next.root = c.root;
        a->next.gate = c.gate;
        for (int i = 0; i < NNOTE; i++)
            a->last[i] = c.note[i];
        return;
    }
    int same = 1;
    for (int i = 0; i < NNOTE; i++)
        same &= s->note[i] == c.note[i];
    if (same) {
        a->tune_since = -1;
        return;
    }
    if (s->elapsed >= FOLLOW_SAMPLES) {
        if (a->tune_since < 0 || a->tune_since > s->elapsed)
            a->tune_since = s->elapsed;
        if (s->elapsed - a->tune_since < SETTLE_SAMPLES)
            return;
    }
    a->tune_since = -1;
    for (int i = 0; i < NNOTE; i++)
        a->last[i] = c.note[i];
    const preset_t *pr = &PRESETS[s->preset];
    for (int i = 0; i < NNOTE; i++) {
        s->note[i] = c.note[i];
        if (i >= c.count)
            continue;
        for (int k = 0; k < 2; k++) {
            float ratio = osc_ratio(pr, k) * s->drift[i];
            float to = clampf(mtof((float)c.note[i]) * ratio, 8.0f, 12000.0f) / SR;
            if (i >= s->count)          /* a note the chord didn't have (a new chord type) */
                s->osc[i][k].phase = 0.0f;
            s->osc[i][k].target = to;
            if (!s->gliding || i >= s->count)
                s->osc[i][k].inc = to;
        }
    }
    s->count = c.count;
    s->norm = count_norm(c.count);
    s->key_track = exp2f_(((float)c.root - 60.0f) * pr->key_track * (1.0f / 12.0f));
}

static void init(cVoice *v)
{
    ak_t *a = (ak_t *)v;
    a->magic = MAGIC;
    a->slot_size = sizeof(slot_t);
    for (int i = 0; i < NNOTE; i++)
        a->last[i] = a->prev[i] = -1;
    for (int s = 0; s < NSLOT; s++)
        a->slot[s].stage = IDLE;
    a->pending = -1;
    a->newest = -1;
    a->role[0] = a->role[1] = -1;
    for (int i = V_CUTOFF; i <= V_ATTACK; i++)
        a->val[i] = 0.5f;               /* 12 o'clock: the preset's own values */
    a->fsel = -1;
    a->preset_ref = 0xff;               /* read_knobs: the preset, MODE now */
    a->tune_pos = -1.0f;
    a->tune_scale = -1;
    a->tune_since = -1;
    a->prog = 0;
    a->rng = 0x2545f491u + a->out;
    uint8_t w = waiting[a->out & 3];    /* for after init: voice-map calls it twice on a rebuild */
    waiting[a->out & 3] = 0;
    read_knobs(a);
    waiting[a->out & 3] = w;
    a->dgain = a->dgain_t;
}

/* ---- audio (per sample) ------------------------------------------------------------------ */

/* the slot's oscillators, summed: each oscillator's waveform chosen once for its 3 notes */
#define NEXT(o, n, dt) do { n += dt; (o)->phase = n >= 1.0f ? n - 1.0f : n; } while (0)

INLINE float oscillators(slot_t *s)
{
    float x = 0.0f;
    const int cnt = s->count;
    for (int k = 0; k < 2; k++) {
        float lv = s->level[k], pw = s->pw[k], y = 0.0f;
        switch (s->wave[k]) {
        case W_SAW:
            for (int i = 0; i < cnt; i++) {
                osc_t *o = &s->osc[i][k];
                float n = o->phase, dt = o->inc;
                y += 2.0f * n - 1.0f - blep(n, dt);
                NEXT(o, n, dt);
            }
            break;
        case W_PULSE:
            for (int i = 0; i < cnt; i++) {
                osc_t *o = &s->osc[i][k];
                float n = o->phase, dt = o->inc, q = n - pw;
                if (q < 0.0f)
                    q += 1.0f;
                y += (n < pw ? 1.0f : -1.0f) + blep(n, dt) - blep(q, dt);
                NEXT(o, n, dt);
            }
            break;
        case W_TRI:
            for (int i = 0; i < cnt; i++) {
                osc_t *o = &s->osc[i][k];
                float n = o->phase, dt = o->inc, q = n - 0.5f;
                if (q < 0.0f)
                    q += 1.0f;
                y += (n < 0.5f ? 4.0f * n - 1.0f : 3.0f - 4.0f * n) - 8.0f * blamp(n, dt) + 8.0f * blamp(q, dt);
                NEXT(o, n, dt);
            }
            break;
        default:
            for (int i = 0; i < cnt; i++) {
                osc_t *o = &s->osc[i][k];
                float n = o->phase, dt = o->inc;
                y += fast_sin(n);
                NEXT(o, n, dt);
            }
            break;
        }
        x += y * lv;
    }
    return x * s->norm;
}

/* formant: the vowels PARAM1 sweeps, dark to bright (U O A E I; Peterson & Barney's
 * averages), three bands each, and the bands' levels */
#define NVOWEL 5
static const float VOWELS[NVOWEL][3] = {
    {300, 870, 2240}, {570, 840, 2410}, {730, 1090, 2440}, {530, 1840, 2480}, {270, 2290, 3010},
};
static const float BAND_LEVEL[3] = {1.0f, 0.63f, 0.35f};

/* the slot's filter coefficients and filter envelope, every COEF_EVERY samples */
static void slot_coefs(const ak_t *a, slot_t *s)
{
    float fe = adsr_step(&s->fenv);
    float ep = fe * (2.0f * warp(a->val[V_ENV], s->u_env) - 1.0f);
    float scale = ep >= 0.0f ? 1.0f + ep * 10.0f : (1.0f + ep > 0.05f ? 1.0f + ep : 0.05f);
    float cut = CUT_MIN * exp2f_(warp(a->val[V_CUTOFF], s->u_cut) * CUT_OCT);
    float fc = clampf(cut * s->key_track * scale, 20.0f, 0.45f * SR);
    /* the iOS synth's coefficient, 2 tan(pi fc / 2 SR) (it puts the filter at about fc / 2: the
     * presets are voiced with it), held below 0.95 to keep it stable */
    float tf = 2.0f * tanf_(0.5f * PI * fc / SR);
    if (tf > 0.95f)
        tf = 0.95f;
    float tq = 1.0f - warp(a->val[V_RES], s->u_res) * 0.9f;
    const float k = 0.0771f;            /* the iOS synth's 0.005 per sample, over COEF_EVERY samples */
    s->f += (tf - s->f) * k;
    s->q += (tq - s->q) * k;
    if (s->fmode == F_FORMANT) {        /* the cutoff knob (and its envelope) picks the vowel */
        float v = clampf(warp(a->val[V_CUTOFF], s->u_cut) + 0.5f * ep, 0.0f, 1.0f) * (NVOWEL - 1);
        /* in resonance's place (ALGO 1): the formant shift, an octave down to an octave up
         * (a bigger to a smaller voice); at 12 o'clock a formant preset's own, else none */
        float own = PRESETS[s->preset].fmode == F_FORMANT ? s->u_res : 0.5f;
        float shift = exp2f_(2.0f * warp(a->val[V_RES], own) - 1.0f);
        int i = (int)v;
        if (i > NVOWEL - 2)
            i = NVOWEL - 2;
        float t = v - (float)i;
        for (int b = 0; b < 3; b++) {
            float hz = (VOWELS[i][b] + (VOWELS[i + 1][b] - VOWELS[i][b]) * t) * shift;
            float fb = tanf_(PI * clampf(hz, 50.0f, 0.3f * SR) / SR);     /* the band at hz */
            s->ff[b] += (fb - s->ff[b]) * k;
            float g = s->ff[b], a1 = 1.0f / (1.0f + g * (g + FORMANT_Q));
            s->fa[b][0] = a1;
            s->fa[b][1] = g * a1;
            s->fa[b][2] = g * g * a1;
        }
    }
    /* resonance compensation, relative to the preset's own resonance (unchanged at 12
     * o'clock): the resonant peak grows about as 1 / q */
    float q0 = 1.0f - s->u_res * 0.9f;
    float tg = s->fmode == F_FORMANT ? 1.0f : (0.4f + 0.6f * tq) / (0.4f + 0.6f * q0);
    s->in_gain += (tg - s->in_gain) * k;
}

/* one TPT (zero-delay-feedback) state-variable filter step (Zavalishin; Simper's form), for
 * the formant bands: the band-pass out; ic1 / ic2 its integrator states */
INLINE float tpt(float x, float *ic1, float *ic2, float a1, float a2, float a3)
{
    float v3 = x - *ic2;
    float v1 = a1 * *ic1 + a2 * v3;
    float v2 = *ic2 + a2 * *ic1 + a3 * v3;
    *ic1 = 2.0f * v1 - *ic1;
    *ic2 = 2.0f * v2 - *ic2;
    return v1;
}

/* the steal fade, after the filter */
INLINE float slot_out(slot_t *s, float y)
{
    if (s->steal > 0) {                 /* fading out for the chord that takes the slot */
        y *= (float)s->steal * (1.0f / STEAL_SAMPLES);
        if (--s->steal == 0)
            s->stage = IDLE;
    }
    return y;
}

INLINE float slot_render(const ak_t *a, slot_t *s)
{
    if (!s->released && s->gate >= 0 && s->elapsed >= s->gate) {
        s->released = 1;
        adsr_release(&s->aenv);
        adsr_release(&s->fenv);
    }
    s->elapsed++;
    if (s->coef_age-- <= 0) {
        s->coef_age = COEF_EVERY - 1;
        slot_coefs(a, s);
    }
    float env = adsr_step(&s->aenv);
    s->stage = s->aenv.stage;

    if (s->gliding) {
        for (int i = 0; i < s->count; i++)
            for (int k = 0; k < 2; k++)
                s->osc[i][k].inc += (s->osc[i][k].target - s->osc[i][k].inc) * s->glide_a;
        if (absf(s->osc[0][0].target - s->osc[0][0].inc) < 1e-7f) {
            for (int i = 0; i < s->count; i++)
                for (int k = 0; k < 2; k++)
                    s->osc[i][k].inc = s->osc[i][k].target;
            s->gliding = 0;
        }
    }
    float x = oscillators(s) * s->in_gain;

    if (s->fmode == F_FORMANT) {        /* three band-passes in parallel, at the vowel's formants */
        float y = 0.0f;
        y += BAND_LEVEL[0] * tpt(x, &s->band, &s->low, s->fa[0][0], s->fa[0][1], s->fa[0][2]);
        y += BAND_LEVEL[1] * tpt(x, &s->band2, &s->low2, s->fa[1][0], s->fa[1][1], s->fa[1][2]);
        y += BAND_LEVEL[2] * tpt(x, &s->band3, &s->low3, s->fa[2][0], s->fa[2][1], s->fa[2][2]);
        return slot_out(s, y * FORMANT_Q * FORMANT_GAIN * env * s->amp);
    }

    /* the iOS synth's state-variable filter (Chamberlin), its states clipped at +-10 (the edge it
     * gets pushed hard): 12 dB high-pass, or two stages for 24 dB low-pass */
    float f = s->f, q = s->q;
    s->low = clampf(s->low + f * s->band, -10.0f, 10.0f);
    float high = x - s->low - q * s->band;
    s->band = clampf(s->band + f * high, -10.0f, 10.0f);
    if (s->fmode == F_HP12)
        return slot_out(s, high * env * s->amp);
    s->low2 = clampf(s->low2 + f * s->band2, -10.0f, 10.0f);      /* LP24: a second stage */
    float high2 = s->low - s->low2 - q * s->band2;
    s->band2 = clampf(s->band2 + f * high2, -10.0f, 10.0f);
    return slot_out(s, s->low2 * env * s->amp);
}

static int16_t render(cVoice *v)
{
    ak_t *a = (ak_t *)v;
    fw_tick_mute_fade(v);
    if (a->magic != MAGIC)
        return 0;
    float y = 0.0f;
    for (int i = 0; i < NSLOT; i++) {
        slot_t *s = &a->slot[i];
        if (s->stage == IDLE) {
            if (a->pending == i) {
                start_slot(a, s, &a->next);
                a->pending = -1;
                if (a->newest == -2)
                    a->newest = i;
            } else {
                continue;
            }
        }
        y += slot_render(a, s);
    }
    /* DC blocker (the pulse oscillators' offset), then the limiter: the last stage */
    y *= MIX;
    float d = y - a->dc_x + DC_R * a->dc_y;
    a->dc_x = y;
    a->dc_y = d;
    float m = absf(d);
    a->lim = m > a->lim ? m : a->lim * LIM_REL;
    if (a->lim > LIM_THR)
        d *= LIM_THR / a->lim;
    a->dgain += (a->dgain_t - a->dgain) * DRIVE_SMOOTH;     /* the level for DRIVE */
    d *= a->dgain;
    float out = clampf(d, -32767.0f, 32767.0f);
    return (int16_t)(((int32_t)out * a->gain) >> 16);
}

/* ---- vtable and construction --------------------------------------------------------- */

/* RTTI-shaped word before the vtable (tools read class names from vtable[-1]) */
static const char ak_name[] = "7cAkords";
static const struct { const void *vptr; const char *name; } ak_typeinfo = {0, ak_name};
static const struct {
    const void *typeinfo;
    cVoice_vtbl vtbl;
} ak_vtable = {&ak_typeinfo, {trigger, init, update, render}};

/* voice-map: build an Akords instance in `obj` (an output's arena) for output `out` */
void pk_ak_build(uint8_t *obj, unsigned out)
{
    for (unsigned i = 0; i < sizeof(ak_t); i++)
        obj[i] = 0;
    ak_t *a = (ak_t *)obj;
    a->vtbl = &ak_vtable.vtbl;
    for (int k = 0; k < 4; k++)
        a->param[k] = &FW_PARAMS[out][k];
    a->out = out;
    a->note = NOTE_REF;
    init((cVoice *)a);
}
