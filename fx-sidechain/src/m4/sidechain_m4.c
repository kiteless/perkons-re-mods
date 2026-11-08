/* fx-sidechain, M4 side: the controls, the page, each kit's settings.
 *
 * KIT + SYNC, from any page: a tap turns the sidechain on or off; holding SYNC for HOLD_MS
 * opens the sidechain page (a page of its own: the M4 host's pages). On the page:
 *   rows 1-4: depth, attack, hold, release; a step chooses its row's value (a dim bar up to
 *             the value, the value bright; all dim while the sidechain is off)
 *   trigger keys: choose the master voice (its trigger LED lit); the voice plays as stock
 *   SYNC: on or off (its LED lit while on)
 * Every other key works as stock (a page button leaves).
 *
 * Each kit keeps its settings (the M4 host's kit sidecar, KITS/PP.KIX, record SCHN, 3 bytes);
 * a kit without one: off, voice 1 the master, the default shape. Loading a kit sends its
 * settings to the M7 (message fx-sidechain, in order with the triggers); so does every
 * change. A change goes into the kit and its sidecar when the page is left, and at once
 * for an on/off from KIT + SYNC.
 *
 * On the framework's M4 host (patches/fx_sidechain.py):
 *   keys.handler_lit (chained)           -> pk_sc_key_event: KIT + SYNC
 *   main loop (chained)                  -> pk_sc_main_loop: the hold opens the page
 *   kit loads (chained)                  -> pk_sc_kit_load
 *   kit sidecar record SCHN              -> pk_sc_kit_save / pk_sc_kit_restore
 *   page sidechain                       -> pk_sc_page_key / _draw / _leave
 *   ui_update: set_led (trigger, SYNC)   -> pk_sc_led: the master and on / off on the page
 */
#include <stdint.h>
#include "pk_host.h"

#define NKITS       64
#define HOLD_MS     500
#define LED_ON      0x80
#define LED_DIM     0x10
#define LED_OFF_VAL 0x30            /* the value step while off */
#define LED_OFF_BAR 0x06

typedef struct {
    uint8_t on, master;
    uint8_t row[4];                 /* depth, attack, hold, release: 0-15 */
} sc_t;

/* the kit table in MAIN (plain .bss), as approved: 64 x 4 B packed */
static uint8_t kit_tab[NKITS][4];   /* [0] bit 7 = has settings, bit 0 on, bits 1-2 master; [1..2] the rows */
static sc_t cur;
static uint8_t sync_down, opened;   /* KIT + SYNC: SYNC held, the page opened by this hold */
static uint32_t sync_at;
static uint8_t dirty;               /* changed on the page since it was entered */

static const sc_t DEFAULTS = {0, PK_SC_DEFAULT_MASTER,
                              {PK_SC_DEFAULT_DEPTH, PK_SC_DEFAULT_ATTACK, PK_SC_DEFAULT_HOLD, PK_SC_DEFAULT_RELEASE}};

static void pack(uint8_t *b, const sc_t *s)
{
    b[0] = (uint8_t)(0x80 | (s->on & 1) | (s->master & 3) << 1);
    b[1] = (uint8_t)((s->row[0] & 15) | (s->row[1] & 15) << 4);
    b[2] = (uint8_t)((s->row[2] & 15) | (s->row[3] & 15) << 4);
    b[3] = 0;
}

static sc_t unpack(const uint8_t *b)
{
    if (!(b[0] & 0x80))
        return DEFAULTS;
    sc_t s = {(uint8_t)(b[0] & 1), (uint8_t)(b[0] >> 1 & 3),
              {(uint8_t)(b[1] & 15), (uint8_t)(b[1] >> 4), (uint8_t)(b[2] & 15), (uint8_t)(b[2] >> 4)}};
    return s;
}

static void send(void)
{
    uint8_t m[6] = {cur.on, cur.master, cur.row[0], cur.row[1], cur.row[2], cur.row[3]};
    pk_send_m7(PK_STREAM_FX_SIDECHAIN, PK_MSG_FX_SIDECHAIN, m, sizeof m);
}

static int current_kit(void)
{
    return *(volatile uint16_t *)(uintptr_t)SYM_current_kit;
}

/* the playing settings into the current kit, and its sidecar written if they changed */
static void keep(void)
{
    int bank = FW_U8(SYM_bank_number), kit = current_kit();
    if (kit < 0 || kit >= NKITS)
        return;
    uint8_t b[4];
    pack(b, &cur);
    for (int i = 0; i < 4; i++)
        if (kit_tab[kit][i] != b[i]) {
            for (int j = 0; j < 4; j++)
                kit_tab[kit][j] = b[j];
            pk_store_save_kit(bank, kit);
            return;
        }
}

void pk_sc_m4_init(void)
{
    cur = DEFAULTS;                 /* kit_tab zeroed: every kit without settings */
}

/* kit loads (chained with the other mods' kit hooks): the kit's settings */
void PK_NEXT(pk_sc_kit_load)(int kit);

void pk_sc_kit_load(int kit)
{
    PK_NEXT(pk_sc_kit_load)(kit);
    if (kit < 0 || kit >= NKITS)
        return;
    cur = unpack(kit_tab[kit]);
    send();
}

/* the host's kit sidecar, record "SCHN": 3 bytes (on | master << 1, depth | attack << 4,
 * hold | release << 4); none: the defaults, off */
uint32_t pk_sc_kit_save(int bank, int kit, uint8_t *buf, uint32_t max)
{
    (void)bank;
    pack(kit_tab[kit], &cur);       /* the kit saved takes the playing settings (as voice-map) */
    if (max < 3)
        return 0;
    for (int i = 0; i < 3; i++)
        buf[i] = kit_tab[kit][i];
    return 3;
}

void pk_sc_kit_restore(int bank, int kit, const uint8_t *rec, uint32_t len)
{
    (void)bank;
    for (int i = 0; i < 4; i++)
        kit_tab[kit][i] = len == 3 && i < 3 ? rec[i] | (i ? 0 : 0x80) : 0;
}

static void toggle(void)
{
    cur.on ^= 1;
    send();
}

/* KIT + SYNC (chained before the stock key handling) */
int PK_NEXT(pk_sc_key_event)(const uint8_t *evt);

int pk_sc_key_event(const uint8_t *evt)
{
    if (evt[0] == FW_KEY_SYNC) {
        if (evt[1] == FW_EV_DOWN && fw_key_held(FW_KEY_KIT)) {
            sync_down = 1;
            opened = 0;
            sync_at = fw_get_tick();
            return 1;
        }
        if (evt[1] == FW_EV_UP && sync_down) {
            sync_down = 0;
            if (!opened) {          /* a tap: on / off, kept in the kit */
                toggle();
                if (fw_get_mode() == PK_PAGE_SIDECHAIN)
                    dirty = 1;
                else
                    keep();
            }
            return 1;
        }
    }
    return PK_NEXT(pk_sc_key_event)(evt);
}

/* main loop (chained): a held KIT + SYNC opens the page */
void PK_NEXT(pk_sc_main_loop)(void);

void pk_sc_main_loop(void)
{
    PK_NEXT(pk_sc_main_loop)();
    if (sync_down && !opened && fw_get_tick() - sync_at >= HOLD_MS) {
        opened = 1;
        if (fw_get_mode() != PK_PAGE_SIDECHAIN)
            fw_set_mode(PK_PAGE_SIDECHAIN);
    }
}

void pk_sc_page_enter(void)
{
    dirty = 0;
}

int pk_sc_page_key(const uint8_t *evt)
{
    if (evt[1] != FW_EV_DOWN && evt[1] != FW_EV_UP)
        return 0;                   /* not a key (the panel switches): stock */
    int down = evt[1] == FW_EV_DOWN;
    if (evt[0] < 0x40) {            /* a step: its row's value */
        int row = evt[0] / 16, v = evt[0] % 16;
        if (down && cur.row[row] != v) {
            cur.row[row] = (uint8_t)v;
            dirty = 1;
            send();
        }
        return 1;
    }
    if (evt[0] >= FW_KEY_TRIG(0) && evt[0] <= FW_KEY_TRIG(3)) {    /* the master; it plays */
        if (down && cur.master != evt[0] - FW_KEY_TRIG(0)) {
            cur.master = (uint8_t)(evt[0] - FW_KEY_TRIG(0));
            dirty = 1;
            send();
        }
        return 0;
    }
    if (evt[0] == FW_KEY_SYNC) {    /* on / off */
        if (down) {
            toggle();
            dirty = 1;
        }
        return 1;
    }
    /* KIT released after opening the page with a hold: stay (stock would go to MAIN) */
    return !down && evt[0] == FW_KEY_KIT;
}

void pk_sc_page_draw(void)
{
    for (int k = 0; k < 0x40; k++) {
        int row = k / 16, v = k % 16, val = cur.row[row];
        int lvl = v > val ? 0 : v == val ? (cur.on ? LED_ON : LED_OFF_VAL) : (cur.on ? LED_DIM : LED_OFF_BAR);
        fw_set_led(k, lvl);
    }
}

/* ui_update sets the trigger and SYNC LEDs after the page draw (chained at those two calls):
 * on the page, the master's trigger LED stays lit (its notes still flash it) and SYNC
 * shows on / off */
void PK_NEXT(pk_sc_led)(int key, int level);

void pk_sc_led(int key, int level)
{
    if (fw_get_mode() == PK_PAGE_SIDECHAIN) {
        if (key == FW_LED_SYNC)
            level = cur.on ? LED_ON : 0;
        else if (key == FW_LED_TRIG(cur.master) && !level)
            level = cur.on ? LED_ON : LED_OFF_VAL;
    }
    PK_NEXT(pk_sc_led)(key, level);
}

/* leaving the page: the settings go into the kit and its sidecar */
void pk_sc_page_leave(void)
{
    if (dirty)
        keep();
    dirty = 0;
    sync_down = 0;
}
