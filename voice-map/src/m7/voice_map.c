/* Voice map: any output can run any of the four stock voice engines.
 *
 * The four original engine objects are kept untouched as templates. Every output runs
 * its own copy in a private 16 KB arena, so remapping an output means copying a template
 * over its arena; nothing else is ever shared or moved, and slots[] never changes after
 * boot. The initial map is compiled in (PK_MAP, one nibble per output); the M4 can
 * replace it at any time with config message type PK_MSG_VOICE_MAP (4 bytes, one engine
 * per output). Engines 0-3 are the stock ones (copied from their templates); 4 and up
 * are engines other mods add (voices.json names such as "slinks"), built in place by the function the
 * generated pk_extra_build[] table names. Unknown engines mean stock for that output.
 *
 * On the framework's M7 host (patches/_voice_map_common.py):
 *   boot, after wire_voices                    -> pk_vm_boot (init)
 *   config message "voice-map"                 -> pk_vm_on_map
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

typedef struct {
    uint32_t magic;
    cVoice *inst[4];            /* engine instance per output (== PK_ARENA(out)) */
    uint8_t src[4];             /* original voice whose engine each output runs */
    uint8_t samples_ready;      /* last sample message was "ready" */
    uint8_t p2cfg;              /* last sampler P2-config value */
    uint8_t pad[2];
    uint32_t sampler_static[4]; /* per-output copies of function-static engine state */
    uint32_t crush_static[4];
    uint32_t static_init[2];    /* their values at boot, for freshly built engines */
    uint32_t remaps;            /* number of runtime remaps applied (diagnostics) */
} pk_state_t;

#define PK_MAGIC 0x564d4150u    /* 'VMAP' */
#define PK ((pk_state_t *)PK_RAM_BASE)

_Static_assert(sizeof(pk_state_t) <= PK_STATE_SIZE, "state overflows its slot");

static inline uint32_t irq_save(void)
{
    uint32_t primask;
    __asm volatile("mrs %0, primask\n cpsid i" : "=r"(primask) :: "memory");
    return primask;
}

static inline void irq_restore(uint32_t primask)
{
    __asm volatile("msr primask, %0" :: "r"(primask) : "memory");
}

static void copy_words(uint32_t *dst, const uint32_t *src, uint32_t bytes)
{
    for (uint32_t i = 0; i < bytes / 4; i++)
        dst[i] = src[i];
}

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
        copy_words((uint32_t *)obj, (const uint32_t *)s->base, s->size);
        retarget(obj, src, out);
    }
#if PK_N_EXTRA
    else {
        pk_extra_build[src - PK_N_STOCK](obj, out);
    }
#endif
    PK->inst[out] = (cVoice *)obj;
    PK->src[out] = (uint8_t)src;
    PK->sampler_static[out] = PK->static_init[0];
    PK->crush_static[out] = PK->static_init[1];
    return obj;
}

/* M7 host init: runs after wire_voices; main calls slots[i]->init() right after. */
void pk_vm_boot(void)
{
    PK->magic = PK_MAGIC;
    PK->samples_ready = 0;
    PK->p2cfg = *((const uint8_t *)pk_slots[FW_SAMPLE_VOICE].base + FW_P2CFG_OFF);
    PK->static_init[0] = *FW_SAMPLER_STATIC;
    PK->static_init[1] = *FW_CRUSH_STATIC;
    PK->remaps = 0;
    for (unsigned out = 0; out < 4; out++)
        FW_SLOTS[out] = (cVoice *)build_output(out, engine_for(out, (PK_MAP >> (4 * out)) & 0xf));
}

/* Switch one output to another engine while audio runs: an instant cut. The new engine
 * is silent until its next trigger. The output's switch/mute state carries over. Runs
 * with interrupts off so the audio callback never sees a half-built engine. */
static void remap_output(unsigned out, unsigned src)
{
    uint32_t primask = irq_save();
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
        obj[FW_P2CFG_OFF] = PK->p2cfg;
        if (PK->samples_ready)
            fw_sample_load_a(obj + FW_SAMPLER_OFF, 0);
    }
    irq_restore(primask);
}

static void apply_map_msg(const uint8_t *map)
{
    for (unsigned out = 0; out < 4; out++) {
        unsigned src = engine_for(out, map[out]);
        if (src != PK->src[out])
            remap_output(out, src);
    }
    PK->remaps++;
}

/* The voice-map config message (M7 host): one engine per output. */
void pk_vm_on_map(const uint8_t *buf, uint32_t len)
{
    if (len == 4)
        apply_map_msg(buf);
}

/* Sample messages: apply to every output running the sampler engine. The firmware
 * computed r0 from slots[3], which may not be a cFourthSlot, so it's ignored. */
void pk_sample_load_a(void *unused, int arg)
{
    (void)unused;
    PK->samples_ready = 1;
    for (unsigned out = 0; out < 4; out++)
        if (PK->src[out] == FW_SAMPLE_VOICE)
            fw_sample_load_a((uint8_t *)PK->inst[out] + FW_SAMPLER_OFF, arg);
}

void pk_sample_load_b(void *unused)
{
    (void)unused;
    PK->samples_ready = 0;
    for (unsigned out = 0; out < 4; out++)
        if (PK->src[out] == FW_SAMPLE_VOICE)
            fw_sample_load_b((uint8_t *)PK->inst[out] + FW_SAMPLER_OFF);
}

/* Replaces a 4-byte "strb.w r3, [r2, #0xc6d]"; the value arrives in r3. */
void pk_p2cfg(int r0, int r1, int r2, int value)
{
    (void)r0; (void)r1; (void)r2;
    PK->p2cfg = (uint8_t)value;
    for (unsigned out = 0; out < 4; out++)
        if (PK->src[out] == FW_SAMPLE_VOICE)
            *((uint8_t *)PK->inst[out] + FW_P2CFG_OFF) = (uint8_t)value;
}

static int output_of(const uint8_t *slot)
{
    for (int out = 0; out < 4; out++)
        if ((const uint8_t *)PK->inst[out] == slot)
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
                              FW_SAMPLER_STATIC, PK->sampler_static);
}

int16_t pk_crush_render(void *crush)
{
    return render_with_static(PK_NEXT(pk_crush_render), crush, (uint8_t *)crush - FW_CRUSH_OFF,
                              FW_CRUSH_STATIC, PK->crush_static);
}
