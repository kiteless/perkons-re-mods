/* Akords, M4 side: each kit's Akords settings and the settings page.
 *
 * Every voice has five settings: preset, chord type, scale, root and progression. They're
 * kept with the kit (the M4 host's kit sidecar, KITS/PP.KIX, record AKRD: 4 x 5 bytes; an
 * older 4 x 4 one, without progressions and with 14 chord types, is read too); a kit
 * without one has all at 0. Loading a kit, and every change on the page, sends all four
 * voices' settings to the M7 in order with the triggers (message "akords"), so the next
 * chord plays them.
 *
 * Progressions: each voice's chord moves through its progression once per cycle of its
 * track (back on the track's first step), from the first chord when the sequencer starts,
 * at a pattern switch and when stopped. Checked just before the stock trigger sending (both
 * of its tail calls), the scale-degree offset goes to the M7 when it changes (message
 * "akords-prog"), in order before that step's triggers.
 *
 * The settings page: a long press on a voice's Akords step on voice-map's engine page
 * opens it for that voice (pk_vm_settings_voice). Rows 1-4 = preset (14), chord type
 * (steps 1-10) and progression (11 off, 12-16), scale (11), root (12), from step 1
 * (bright: chosen). Pressing a preset, even the one
 * chosen, gives the voice all of the preset's sound again (the M7 drops the knobs' tweaks
 * until they move). The trigger keys
 * play the voices; SHIFT, KIT or MOD goes back to the engine page; another page button
 * leaves as stock. Leaving keeps the settings in the kit and writes the kit's sidecar. */
#include <stdint.h>
#include "pk_host.h"
#include "fw_m4_seq.h"

#define NKITS           64
#define NSET            5           /* preset, chord type, scale, root, progression */
#define NSEND           4           /* the first four go to the M7 */
#define PROG            4           /* the progression's index in a voice's settings */
#define NCHORD          10
#define NPROG           6           /* 0 off, 1-5 */
static const uint8_t NPOS[NSET] = {14, NCHORD, 11, 12, NPROG};
_Static_assert(14 <= 16 && NCHORD <= 16 && 11 <= 16 && 12 <= 16 && NPROG <= 256,
               "each setting fits its bits in the kit table (pack)");

/* the progressions: scale degrees above TUNE's, a chord per track cycle (written for the
 * minor scales: i = 0, III = 2, iv = 3, v = 4, VI = 5, VII = 6) */
static const int8_t PROGRESSION[NPROG][4] = {
    {0, 0, 0, 0},                   /* off */
    {0, 5, 2, 6},                   /* trance: i VI III VII */
    {0, 5, 6, 4},                   /* epic: i VI VII v */
    {0, 4, 5, 3},                   /* progressive house, melodic techno: i v VI iv */
    {0, 5, 0, 5},                   /* techno: i VI */
    {0, 3, 0, 3},                   /* deep house: i iv */
};
#define LED_ON          0x80
#define LED_DIM         0x10

extern uint8_t pk_vm_settings_voice;

#define PACKED          3           /* a voice's settings packed: 4 + 4 + 4 + 4 + 3 bits */
PK_AXI static uint8_t kit_set[NKITS][4][PACKED];        /* each kit's settings, per voice */
PK_AXI static uint8_t cur[4][NSET];             /* the settings playing */
PK_AXI static uint8_t editing;                  /* the voice the page edits */

/* the settings, then the voices (bits) whose preset was just pressed: they take all of
 * the preset's own settings again (the knobs' tweaks too) */
static void send_prog(int force);
static void prog_stopped(void);

static void send(uint8_t pressed)
{
    uint8_t msg[4 * NSEND + 1];
    for (int v = 0; v < 4; v++)
        for (int i = 0; i < NSEND; i++)
            msg[v * NSEND + i] = cur[v][i];
    msg[4 * NSEND] = pressed;
    pk_send_m7(PK_STREAM_AKORDS, PK_MSG_AKORDS, msg, sizeof msg);
    send_prog(0);
}

static int current_kit(void)
{
    return *(volatile uint16_t *)(uintptr_t)SYM_current_kit;
}

/* a kit's table entry: preset | chord << 4, scale | root << 4, progression */
static void pack(uint8_t to[4][PACKED], const uint8_t from[4][NSET])
{
    for (int v = 0; v < 4; v++) {
        to[v][0] = (uint8_t)(from[v][0] | from[v][1] << 4);
        to[v][1] = (uint8_t)(from[v][2] | from[v][3] << 4);
        to[v][2] = from[v][4];
    }
}

static void unpack(uint8_t to[4][NSET], const uint8_t from[4][PACKED])
{
    for (int v = 0; v < 4; v++) {
        to[v][0] = from[v][0] & 15;
        to[v][1] = from[v][0] >> 4;
        to[v][2] = from[v][1] & 15;
        to[v][3] = from[v][1] >> 4;
        to[v][4] = from[v][2];
    }
}

static int same(const uint8_t a[4][PACKED], const uint8_t b[4][NSET])
{
    uint8_t p[4][PACKED];
    pack(p, b);
    for (int v = 0; v < 4; v++)
        for (int i = 0; i < PACKED; i++)
            if (a[v][i] != p[v][i])
                return 0;
    return 1;
}


/* kit loads (chained with the other mods' kit hooks): the kit's settings */
void PK_NEXT(pk_ak_kit_load)(int kit);

void pk_ak_kit_load(int kit)
{
    PK_NEXT(pk_ak_kit_load)(kit);
    if (kit < 0 || kit >= NKITS)
        return;
    unpack(cur, kit_set[kit]);
    send(0);
}

/* the host's kit sidecar, record "AKRD": [voice][preset, chord, scale, root, progression];
 * none = all 0 */
uint32_t pk_ak_kit_save(int bank, int kit, uint8_t *buf, uint32_t max)
{
    (void)bank;
    pack(kit_set[kit], cur);
    uint32_t n = 4 * NSET, any = 0;
    if (max < n)
        return 0;
    for (int v = 0; v < 4; v++)
        for (int i = 0; i < NSET; i++) {
            buf[v * NSET + i] = cur[v][i];
            any |= cur[v][i];
        }
    return any ? n : 0;
}

/* the 14 chord types of a 4 x 4 record: Minor 7 and Sus2 (plain, smooth) are gone; they
 * play Diatonic 7th and Diatonic */
static const uint8_t OLD_CHORD[14] = {0, 1, 2, 3, 4, 5, 2, 3, 0, 1, 6, 7, 8, 9};

void pk_ak_kit_restore(int bank, int kit, const uint8_t *rec, uint32_t len)
{
    (void)bank;
    int n = len == 4 * NSET ? NSET : (len == 4 * 4 ? 4 : 0);
    uint8_t set[4][NSET];
    for (int v = 0; v < 4; v++)
        for (int i = 0; i < NSET; i++) {
            uint8_t x = i < n ? rec[v * n + i] : 0;
            if (n == 4 && i == 1)
                x = x < 14 ? OLD_CHORD[x] : 0;
            set[v][i] = x < NPOS[i] ? x : 0;
        }
    pack(kit_set[kit], set);
}

/* ---- DRIVE ---------------------------------------------------------------------------- */

/* Each voice's DRIVE (the value playing: knob, kit, locks) goes to the M7 when it changes
 * (message "akords-drive", 4 x 0-255, ordered: the stream the settings use): the engine's
 * level follows it. Checked from the main loop (every DRIVE_EVERY_MS), never from an
 * interrupt; sent again every DRIVE_RESEND_MS unchanged too, so a lost one heals. */
#define DRIVE_EVERY_MS  5
#define DRIVE_RESEND_MS 250
PK_AXI static uint8_t drive_sent[4];    /* 0 at boot, as the M7's */
PK_AXI static uint32_t drive_checked, drive_at;     /* ms: the last check, the last send */

void PK_NEXT(pk_ak_main_loop)(void);

void pk_ak_main_loop(void)
{
    PK_NEXT(pk_ak_main_loop)();
    prog_stopped();
    uint32_t now_ms = fw_get_tick();
    if (now_ms - drive_checked < DRIVE_EVERY_MS)
        return;
    drive_checked = now_ms;
    uint8_t now[4];
    int changed = 0;
    for (int v = 0; v < 4; v++) {
        now[v] = (uint8_t)(FW_U16(fw_voice_state(v) + FW_VS_VALUE + 2 * FW_SLOT_DRIVE) >> 8);
        changed |= now[v] != drive_sent[v];
    }
    if (changed || now_ms - drive_at >= DRIVE_RESEND_MS) {
        drive_at = now_ms;
        for (int v = 0; v < 4; v++)
            drive_sent[v] = now[v];
        pk_send_m7(PK_STREAM_AKORDS_DRIVE, PK_MSG_AKORDS_DRIVE, now, sizeof now);
    }
}

/* ---- progressions ------------------------------------------------------------------------ */

PK_AXI static uint16_t prog_step[4];    /* each track's step when last seen */
PK_AXI static uint8_t prog_cycle[4];    /* its cycles since the start (the chord: & 3) */
PK_AXI static int8_t prog_sent[4];      /* the offsets the M7 has (0 at boot, as its own) */
PK_AXI static uint8_t prog_playing;
PK_AXI static const void *prog_pattern; /* the pattern playing */

static uint8_t *seq(void)
{
    return (uint8_t *)(uintptr_t)FW_U32(SYM_seq_ptr);
}

/* each voice's offset now to the M7, if it changed (or `force`) */
static void send_prog(int force)
{
    int8_t off[4];
    int changed = force;
    for (int v = 0; v < 4; v++) {
        off[v] = PROGRESSION[cur[v][PROG]][prog_cycle[v] & 3];
        changed |= off[v] != prog_sent[v];
    }
    if (!changed)
        return;
    for (int v = 0; v < 4; v++)
        prog_sent[v] = off[v];
    pk_send_m7(PK_STREAM_AKORDS_PROG, PK_MSG_AKORDS_PROG, off, sizeof off);
}

static void prog_restart(void)
{
    for (int v = 0; v < 4; v++) {
        prog_cycle[v] = 0;
        prog_step[v] = FW_U16(fw_voice_state(v) + FW_VS_STEP);
    }
}

/* the stock trigger sending (tail-called by the sequencer's ticks): each track's cycle
 * first, so the chord's offset reaches the M7 before the step's triggers */
int PK_NEXT(pk_ak_send_triggers)(void);

int pk_ak_send_triggers(void)
{
    const uint8_t *s = seq();
    if (s[FW_SEQ_PLAY] == 1) {
        const void *pat = (const void *)(uintptr_t)FW_U32(s + FW_SEQ_CURRENT);
        if (!prog_playing || pat != prog_pattern) {     /* started, or a new pattern */
            prog_playing = 1;
            prog_pattern = pat;
            prog_restart();
        }
        for (int v = 0; v < 4; v++) {
            const uint8_t *vs = fw_voice_state(v);
            uint16_t step = FW_U16(vs + FW_VS_STEP);
            if (step != prog_step[v]) {
                const uint8_t *blk = (const uint8_t *)(uintptr_t)FW_U32(vs + FW_VS_BLOCK);
                if (step == blk[FW_BLK_FIRST])          /* back on its first step: a cycle */
                    prog_cycle[v]++;
                prog_step[v] = step;
            }
        }
        send_prog(0);
    }
    return PK_NEXT(pk_ak_send_triggers)();
}

/* stopped: the first chord again (from the main loop) */
static void prog_stopped(void)
{
    if (seq()[FW_SEQ_PLAY] == 1 || !prog_playing)
        return;
    prog_playing = 0;
    for (int v = 0; v < 4; v++)
        prog_cycle[v] = 0;
    send_prog(0);
}

/* ---- the settings page ------------------------------------------------------------------ */

int pk_ak_page_key(const uint8_t *evt)
{
    if (evt[1] != FW_EV_DOWN && evt[1] != FW_EV_UP)
        return 0;                       /* not a key (the panel switches): stock */
    int k = evt[0], down = evt[1] == FW_EV_DOWN;
    if (k < 0x40) {                     /* steps (their releases too: the long press's) */
        int row = k / 16, col = k % 16;
        if (!down)
            return 1;
        if (col >= (row == 1 ? NCHORD + NPROG : NPOS[row]))
            return 1;
        if (row == 0) {                 /* a preset, even the one chosen: all its sound */
            cur[editing][0] = (uint8_t)col;
            send((uint8_t)(1u << editing));
        } else if (row == 1 && col >= NCHORD) {         /* off, or a progression */
            if (cur[editing][PROG] != col - NCHORD) {
                cur[editing][PROG] = (uint8_t)(col - NCHORD);
                send(0);
            }
        } else if (cur[editing][row] != col) {
            cur[editing][row] = (uint8_t)col;
            send(0);
        }
        return 1;
    }
    if (k == FW_KEY_SHIFT || k == FW_KEY_KIT || k == FW_KEY_MOD) {
        if (down)
            fw_set_mode(PK_PAGE_ENGINES);
        return 1;                       /* (a release here would go to MAIN) */
    }
    return 0;                           /* the trigger keys play; other page buttons leave */
}

/* entering the page (from the engine page's long press): that voice */
void pk_ak_page_enter(void)
{
    if (pk_vm_settings_voice < 4)
        editing = pk_vm_settings_voice;
}

void pk_ak_page_draw(void)
{
    for (int k = 0; k < 0x40; k++) {
        int row = k / 16, col = k % 16, lvl = 0;
        if (row == 1 && col >= NCHORD && col < NCHORD + NPROG)
            lvl = cur[editing][PROG] == col - NCHORD ? LED_ON : LED_DIM;
        else if (col < NPOS[row])
            lvl = cur[editing][row] == col ? LED_ON : LED_DIM;
        fw_set_led(k, lvl);
    }
}

/* leaving the page: changed settings go into the kit and its sidecar */
void pk_ak_page_leave(void)
{
    int bank = FW_U8(SYM_bank_number), kit = current_kit();
    if (kit >= 0 && kit < NKITS && !same(kit_set[kit], cur)) {
        pack(kit_set[kit], cur);
        pk_store_save_kit(bank, kit);
    }
}
