/* fx-sidechain: the master voice's triggers duck the other three voices.
 *
 * Every output's render goes through a wrapper: the output's voice object gets a copy of
 * its method table in RAM with the render entry pointing at this output's wrapper, which
 * calls the engine's own render and scales the sample by the duck gain. voice-map rebuilds
 * an output's object (and so its method table) when the output switches engine; that
 * happens in the trigger dispatch, in voice-map's hook before this one, so this hook wraps
 * the output again before it renders. An output that isn't ducking returns the engine's
 * sample unchanged.
 *
 * Each output runs its own envelope (attack, hold, release), so it follows its own
 * samples' timing: the M7 renders outputs 3-4 and 1-2 in separate callbacks. The master's
 * trigger (any trigger: sequencer step, trigger key, MIDI) starts the envelope of the
 * other three. Turning the duck off or choosing another master never cuts a running duck:
 * it finishes its release.
 *
 * On the framework's M7 host (patches/fx_sidechain.py):
 *   trigger dispatch: bl cVoice_set_velocity   -> pk_sc_velocity (after voice-map's)
 *   message "fx-sidechain" (ordered)           -> pk_sc_on_msg: the settings
 */
#include <stdint.h>
#include "pk7_host.h"
#include "sc_tables.h"          /* generated: PK_SC_DEPTH[16], _ATTACK[16], _HOLD[16], _RELEASE[16] */

#define FLOOR   0.01f           /* a release ends at 1% of the duck (the gain step is inaudible) */

enum { IDLE, ATTACK, HOLD, RELEASE };

typedef struct {
    float x;                    /* how far ducked, 0..1 (the gain is 1 - depth * x) */
    uint32_t n;                 /* hold samples left */
    uint8_t stage;
    uint8_t pad[3];
} env_t;

static cVoice_vtbl vt[4];       /* each output's method table copy, render wrapped */
static int16_t (*orig[4])(cVoice *);    /* each output's engine render */
static env_t env[4];
static float depth, att_inc, rel_k;     /* from the settings (tables) */
static uint32_t hold_n;
static uint8_t on, master;

static void set(unsigned d, unsigned a, unsigned h, unsigned r)
{
    depth = PK_SC_DEPTH[d & 15];
    att_inc = PK_SC_ATTACK[a & 15];
    hold_n = PK_SC_HOLD[h & 15];
    rel_k = PK_SC_RELEASE[r & 15];
}

void pk_sc_init(void)
{
    on = PK_SC_DEFAULT_ON;
    master = PK_SC_DEFAULT_MASTER;
    set(PK_SC_DEFAULT_DEPTH, PK_SC_DEFAULT_ATTACK, PK_SC_DEFAULT_HOLD, PK_SC_DEFAULT_RELEASE);
}

/* The settings (M7 host, ordered: in the audio callback, in order with the triggers):
 * {on, master 0-3, depth, attack, hold, release 0-15}. */
void pk_sc_on_msg(const uint8_t *buf, uint32_t len)
{
    if (len != 6)
        return;
    on = buf[0] ? 1 : 0;
    master = buf[1] & 3;
    set(buf[2], buf[3], buf[4], buf[5]);
}

static int16_t duck(unsigned o, int16_t v)
{
    env_t *e = &env[o];
    switch (e->stage) {
    case ATTACK:
        e->x += att_inc;
        if (e->x >= 1.0f) {
            e->x = 1.0f;
            e->stage = HOLD;
            e->n = hold_n;
        }
        break;
    case HOLD:
        if (e->n)
            e->n--;
        else
            e->stage = RELEASE;
        break;
    default:
        e->x *= rel_k;
        if (e->x < FLOOR) {
            e->x = 0.0f;
            e->stage = IDLE;
            return v;
        }
        break;
    }
    return (int16_t)((float)v * (1.0f - depth * e->x));
}

/* idle: straight on to the engine's render (a tail call) */
#define WRAP(o) static int16_t render##o(cVoice *v) \
    { return env[o].stage == IDLE ? orig[o](v) : duck(o, orig[o](v)); }
WRAP(0)
WRAP(1)
WRAP(2)
WRAP(3)
static int16_t (*const wrapper[4])(cVoice *) = {render0, render1, render2, render3};

/* Give output `o`'s object the wrapped method table, unless it has it already. */
static void wrap(unsigned o, cVoice *obj)
{
    if (obj->vtbl == &vt[o])
        return;
    vt[o] = *obj->vtbl;
    orig[o] = vt[o].render;
    vt[o].render = wrapper[o];
    obj->vtbl = &vt[o];
}

/* The trigger dispatch calls cVoice_set_velocity first in each output's turn, for every
 * output, with the output's object in r0 and its trigger record in r7 (+1 trigger flag). */
void pk_sc_before_note(cVoice *obj, const uint8_t *rec)
{
    unsigned o;
    for (o = 0; o < 4; o++)
        if (FW_SLOTS[o] == obj)
            break;
    if (o == 4)
        return;
    wrap(o, obj);
    if (!on || o != master || !rec[1])
        return;
    for (unsigned k = 0; k < 4; k++)
        if (k != master)
            env[k].stage = ATTACK;      /* from where it is: a retrigger never jumps */
}

__attribute__((naked)) void pk_sc_velocity(void)
{
    __asm volatile(
        "push {r0, r1, r2, lr}\n"
        "mov r1, r7\n"
        "bl pk_sc_before_note\n"
        "pop {r0, r1, r2, lr}\n"
        "b.w pk_next_pk_sc_velocity\n");
}
