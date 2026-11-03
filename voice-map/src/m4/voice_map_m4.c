/* Voice map, M4 side: each kit chooses the engine of each voice.
 *
 * The four engines are kept with the kit (the M4 host's kit sidecar, KITS/PP.KIX, record
 * VMAP: one nibble per voice); a kit without one plays the stock engines 1, 2, 3, 4. Loading
 * a kit (the KIT page, a bank load, kit-link on a pattern switch) sends its engines to the
 * M7 in order with the triggers, so the next note of each voice plays the kit's engine.
 *
 * Engine page, a UI page of its own (the M4 host's pages): hold KIT and press MOD, from any
 * page (as PATTERN + KIT opens the bank menu). Rows 1-4 = voices 1-4, columns = engines
 * (stock 1-4, then other mods' engines); the LED shows each voice's engine, dim the ones it
 * could have. A step chooses; every other key works as stock: the trigger keys play the
 * voices (the next note sounds the new engine), a page button leaves. Leaving keeps the
 * choice in the kit and writes the kit's sidecar. */
#include <stdint.h>
#include "pk_host.h"
#include "pk_engines.h"             /* PK_N_ENGINES, PK_ENGINE_MASK: the engine page's columns */

#define NKITS           64
#define DEFAULT_MAP     0x3210u     /* voice v runs engine v */
#define LED_ON          0x80
#define LED_DIM         0x10

PK_AXI static uint16_t kit_map[NKITS];  /* each kit's engines, a nibble per voice */
PK_AXI static uint16_t cur;             /* the engines playing */

static unsigned engine_of(uint16_t map, int v)
{
    return map >> (4 * v) & 0xfu;
}

static void send(uint16_t map)
{
    uint8_t m[4];
    for (int v = 0; v < 4; v++)
        m[v] = (uint8_t)engine_of(map, v);
    pk_send_m7(PK_STREAM_VOICE_MAP, PK_MSG_VOICE_MAP, m, 4);
}

void pk_vm_init(void)
{
    for (int k = 0; k < NKITS; k++)
        kit_map[k] = DEFAULT_MAP;
    cur = DEFAULT_MAP;
}

/* kit loads (chained with the other mods' kit hooks): the kit's engines */
void PK_NEXT(pk_vm_kit_load)(int kit);

void pk_vm_kit_load(int kit)
{
    PK_NEXT(pk_vm_kit_load)(kit);
    if (kit < 0 || kit >= NKITS)
        return;
    cur = kit_map[kit];
    send(cur);
}

/* the host's kit sidecar, record "VMAP": u16, a nibble per voice; none = stock engines */
uint32_t pk_vm_kit_save(int bank, int kit, uint8_t *buf, uint32_t max)
{
    (void)bank;
    kit_map[kit] = cur;
    if (cur == DEFAULT_MAP || max < 2)
        return 0;
    buf[0] = (uint8_t)cur;
    buf[1] = (uint8_t)(cur >> 8);
    return 2;
}

void pk_vm_kit_restore(int bank, int kit, const uint8_t *rec, uint32_t len)
{
    (void)bank;
    kit_map[kit] = len == 2 ? (uint16_t)(rec[0] | rec[1] << 8) : DEFAULT_MAP;
}

/* KIT + MOD (chained before the stock key handling): the engine page */
int PK_NEXT(pk_vm_key_event)(const uint8_t *evt);

int pk_vm_key_event(const uint8_t *evt)
{
    if (evt[0] == FW_KEY_MOD && evt[1] == FW_EV_DOWN && fw_key_held(FW_KEY_KIT)) {
        fw_set_mode(PK_PAGE_ENGINES);
        return 1;
    }
    return PK_NEXT(pk_vm_key_event)(evt);
}

/* the engine page: a step chooses that row's voice's engine; the KIT and MOD releases are
 * kept from the stock handling (a long hold's release would go to the MAIN page) */
int pk_vm_page_key(const uint8_t *evt)
{
    if (evt[0] < 0x40) {
        int v = evt[0] / 16, e = evt[0] % 16;
        if (evt[1] == FW_EV_DOWN && v < 4 && (PK_ENGINE_MASK >> e & 1) && (unsigned)e != engine_of(cur, v)) {
            cur = (uint16_t)((cur & ~(0xfu << (4 * v))) | (unsigned)e << (4 * v));
            send(cur);
        }
        return 1;
    }
    return evt[1] == FW_EV_UP && (evt[0] == FW_KEY_KIT || evt[0] == FW_KEY_MOD);
}

void pk_vm_page_draw(void)
{
    for (int k = 0; k < 0x40; k++) {
        int v = k / 16, e = k % 16;
        int lvl = v < 4 && (PK_ENGINE_MASK >> e & 1) ? ((unsigned)e == engine_of(cur, v) ? LED_ON : LED_DIM) : 0;
        fw_set_led(k, lvl);
    }
}

/* leaving the page: a changed choice goes into the kit and its sidecar */
void pk_vm_page_leave(void)
{
    int bank = FW_U8(SYM_bank_number), kit = *(volatile uint16_t *)(uintptr_t)SYM_current_kit;
    if (kit >= 0 && kit < NKITS && kit_map[kit] != cur) {
        kit_map[kit] = cur;
        pk_store_save_kit(bank, kit);
    }
}
