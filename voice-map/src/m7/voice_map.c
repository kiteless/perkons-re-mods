/* Voice map: any output can run any of the four stock voice engines.
 *
 * The four original engine objects are kept untouched as templates. Every output runs
 * its own copy in a private 16 KB arena, so remapping an output means copying a template
 * over its arena; nothing else is ever shared or moved, and slots[] never changes after
 * boot. The initial map is compiled in (PK_MAP, one nibble per output); the M4 changes it
 * with the voice-map message (PK_MSG_VOICE_MAP: 4 bytes, one engine per output), sent when
 * a kit loads or the engine page changes it. Engines 0-3 are the stock ones (copied from
 * their templates); 4 and up are engines other mods add (such as zibens), built in place by
 * the function the generated pk_extra_build[] table names. Unknown engines mean stock.
 *
 * On the framework's M7 host (patches/_voice_map_common.py):
 *   boot, after wire_voices                    -> pk_vm_boot (init)
 *   message "voice-map" (ordered)              -> pk_vm_on_map: pending engines
 *   trigger dispatch: bl cVoice_set_velocity   -> pk_vm_velocity: switch at the note
 *   main: bl cSamplePlayer_load_a / _load_b    -> pk_sample_load_a / _b
 *   main: strb r3, [slots[3], #0x2c6d]         -> pk_p2cfg
 *   cFourthSlot render: sampler / noise-crush  -> pk_sampler_render / pk_crush_render
 */
#include <stdint.h>
#include "pk7_host.h"
#include "pk_ram.h"
#include "slot_layout.h"
#include "pk_extra_engines.h"   /* PK_N_EXTRA, pk_extra_build[]: other mods' engines */

#define PK_N_STOCK 4

static cVoice *instance[4];     /* engine instance per output (== PK_ARENA(out)) */
static uint8_t running[4];      /* the engine each output runs */
static uint8_t samples_ready;   /* last sample message was "ready" */
static uint8_t p2cfg;           /* last sampler P2-config value */
static uint32_t sampler_static[4];  /* per-output copies of function-static engine state */
static uint32_t crush_static[4];
static uint32_t static_init[2]; /* their values at boot, for freshly built engines */

/* Point every param pointer of an instance of `src`'s engine at output `out`'s params. */
static void retarget(uint8_t *obj, unsigned src, unsigned out)
{
    const pk_slot_t *s = &pk_slots[src];
    for (unsigned i = 0; i < s->n_pp; i++)
        *(int32_t **)(obj + s->pp[i].off) = &FW_PARAMS[out][s->pp[i].k];
}

/* The engine output `out` runs for map value `v`: v itself if it's built in, else stock. */
static unsigned engine_for(unsigned out, unsigned v)
{
    if (v < PK_N_STOCK)
        return v;
#if PK_N_EXTRA
    if (v - PK_N_STOCK < PK_N_EXTRA && pk_extra_build[v - PK_N_STOCK])
        return v;
#endif
    return out;
}

/* Overwrite output `out`'s arena with a fresh instance of engine `src` (engine_for()). */
static uint8_t *build_output(unsigned out, unsigned src)
{
    uint8_t *obj = PK_ARENA(out);
    if (src < PK_N_STOCK) {
        const pk_slot_t *s = &pk_slots[src];
        pk_copy(obj, (const void *)(uintptr_t)s->base, s->size);
        retarget(obj, src, out);
    }
#if PK_N_EXTRA
    else {
        pk_extra_build[src - PK_N_STOCK](obj, out);
    }
#endif
    instance[out] = (cVoice *)obj;
    running[out] = (uint8_t)src;
    sampler_static[out] = static_init[0];
    crush_static[out] = static_init[1];
    return obj;
}

/* M7 host init: runs after wire_voices; main calls slots[i]->init() right after. */
void pk_vm_boot(void)
{
    p2cfg = *((const uint8_t *)pk_slots[FW_SAMPLE_VOICE].base + FW_P2CFG_OFF);
    static_init[0] = *FW_SAMPLER_STATIC;
    static_init[1] = *FW_CRUSH_STATIC;
    for (unsigned out = 0; out < 4; out++)
        FW_SLOTS[out] = (cVoice *)build_output(out, engine_for(out, (PK_MAP >> (4 * out)) & 0xf));
}

/* Switch one output to another engine, in the audio callback just before its note (so the
 * callback never renders a half-built engine; nothing that interrupts the callback uses
 * the engines). The output's switch/mute state carries over. */
static void remap_output(unsigned out, unsigned src)
{
    uint8_t *obj = PK_ARENA(out);
    /* algo, mode, velocity, accent are consecutive bytes starting at FW_ALGO_OFF */
    uint8_t ctrl[4] = {obj[FW_ALGO_OFF], obj[FW_MODE_OFF], obj[FW_VELOCITY_OFF], obj[FW_ACCENT_OFF]};
    uint8_t mute = obj[FW_MUTE_OFF];
    int32_t gain = *(int32_t *)(obj + FW_GAIN_OFF);
    build_output(out, src);
    ((cVoice *)obj)->vtbl->init((cVoice *)obj);
    for (unsigned i = 0; i < 4; i++)
        obj[FW_ALGO_OFF + i] = ctrl[i];
    obj[FW_MUTE_OFF] = mute;
    *(int32_t *)(obj + FW_GAIN_OFF) = gain;
    if (src == FW_SAMPLE_VOICE) {
        obj[FW_P2CFG_OFF] = p2cfg;
        if (samples_ready)
            fw_sample_load_a(obj + FW_SAMPLER_OFF, 0);
    }
}

/* The voice-map message (M7 host, ordered: handled in the audio callback in order with the
 * trigger messages): one engine per output. An output whose engine changes switches at its
 * next note (pk_vm_before_note), so a ringing sound is replaced by a note, as a retrigger
 * replaces it, never cut, and a note sent after the map always plays the new engine. */
static uint8_t pending[4];              /* engine + 1 to switch to at the next note; 0 none */

void pk_vm_on_map(const uint8_t *buf, uint32_t len)
{
    if (len != 4)
        return;
    for (unsigned out = 0; out < 4; out++) {
        unsigned src = engine_for(out, buf[out]);
        pending[out] = src != running[out] ? (uint8_t)(src + 1) : 0;
    }
}

/* The trigger dispatch calls cVoice_set_velocity first in each output's turn, with that
 * output's trigger record in r7 (+1 trigger flag): a triggered output with a pending engine
 * switches before its note. */
static int output_of(const uint8_t *slot);

void pk_vm_before_note(const uint8_t *slot, const uint8_t *rec)
{
    int out = output_of(slot);
    if (out < 0 || !rec[1] || !pending[out])
        return;
    remap_output((unsigned)out, pending[out] - 1u);
    pending[out] = 0;
}

__attribute__((naked)) void pk_vm_velocity(void)
{
    __asm volatile(
        "push {r0, r1, r2, lr}\n"
        "mov r1, r7\n"
        "bl pk_vm_before_note\n"
        "pop {r0, r1, r2, lr}\n"
        "b.w pk_next_pk_vm_velocity\n");
}

/* Sample messages: apply to every output running the sampler engine. The firmware
 * computed r0 from slots[3], which may not be a cFourthSlot, so it's ignored. */
void pk_sample_load_a(void *unused, int arg)
{
    (void)unused;
    samples_ready = 1;
    for (unsigned out = 0; out < 4; out++)
        if (running[out] == FW_SAMPLE_VOICE)
            fw_sample_load_a((uint8_t *)instance[out] + FW_SAMPLER_OFF, arg);
}

void pk_sample_load_b(void *unused)
{
    (void)unused;
    samples_ready = 0;
    for (unsigned out = 0; out < 4; out++)
        if (running[out] == FW_SAMPLE_VOICE)
            fw_sample_load_b((uint8_t *)instance[out] + FW_SAMPLER_OFF);
}

/* Replaces a 4-byte "strb.w r3, [r2, #0xc6d]"; the value arrives in r3. */
void pk_p2cfg(int r0, int r1, int r2, int value)
{
    (void)r0; (void)r1; (void)r2;
    p2cfg = (uint8_t)value;
    for (unsigned out = 0; out < 4; out++)
        if (running[out] == FW_SAMPLE_VOICE)
            *((uint8_t *)instance[out] + FW_P2CFG_OFF) = (uint8_t)value;
}

static int output_of(const uint8_t *slot)
{
    for (int out = 0; out < 4; out++)
        if ((const uint8_t *)instance[out] == slot)
            return out;
    return -1;
}

/* Run a render with `*shared` holding this output's private copy of the static. */
static int16_t render_with_static(int16_t (*render)(void *), void *engine, const uint8_t *slot,
                                  volatile uint32_t *shared, uint32_t *saved)
{
    int out = output_of(slot);
    if (out < 0)
        return render(engine);
    *shared = saved[out];
    int16_t v = render(engine);
    saved[out] = *shared;
    return v;
}

int16_t PK_NEXT(pk_sampler_render)(void *sampler);
int16_t PK_NEXT(pk_crush_render)(void *crush);

int16_t pk_sampler_render(void *sampler)
{
    return render_with_static(PK_NEXT(pk_sampler_render), sampler, (uint8_t *)sampler - FW_SAMPLER_OFF,
                              FW_SAMPLER_STATIC, sampler_static);
}

int16_t pk_crush_render(void *crush)
{
    return render_with_static(PK_NEXT(pk_crush_render), crush, (uint8_t *)crush - FW_CRUSH_OFF,
                              FW_CRUSH_STATIC, crush_static);
}
