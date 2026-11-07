/* Akords, M4 side: each kit's Akords settings and the settings page.
 *
 * Every voice has five settings: preset, chord type, scale, root and progression. They're
 * kept with the kit (the M4 host's kit sidecar, KITS/PP.KIX, record AKRD: 4 x 9 bytes,
 * below; older 4 x 5 and 4 x 4 ones, the latter without progressions and with 14 chord
 * types, are read too); a kit without one has all at 0. Loading a kit, and every change on
 * the page, sends all four voices' settings to the M7 in order with the triggers (message
 * "akords"), so the next chord plays them.
 *
 * The sound: a kit keeps the knob and switch positions, but the values the voice plays
 * aren't all on them. PARAM2 sets three values, and keeps the two ALGO isn't on; a preset
 * press gives the preset's values until a knob moves; the filter is the preset's own until
 * MODE moves. The M7 can't send anything back, so this core follows the same rules on the
 * knobs' own positions (no locks) and saves the values with the kit. Loading a kit sends
 * them (message "akords-sound"), held until the kit's positions have reached the M7: while
 * the sequencer plays, the firmware only applies them at the track's next note. A voice saved without Akords, or in a kit from before
 * they were saved, plays its knobs, with the preset's values for the rest.
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
#include "pk_vm.h"                  /* pk_vm_engine */
#include "pk_ak_engine.h"           /* PK_AK_ENGINE: Akords' engine number */

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

/* a voice's values the knobs set, as on the M7 (0-255; 128: 12 o'clock, the preset's own).
 * The cutoff isn't kept: PARAM1 has no other job, so it's on its knob or the preset's. */
enum { V_CUTOFF, V_RES, V_ENV, V_ATTACK, NVAL };
#define NKEPT           3           /* resonance, env amount, attack */
#define VAL_OWN         128
#define MOVED           82          /* knob travel (0-4095, 2%), as the M7's */
#define POS1            1           /* the switch values of panel positions 1, 3 */
#define POS3            2
/* a kit's table entry, and the record's flags byte */
#define KEPT            0x08        /* the values below are kept */
#define KEPT_MODE       0x10        /* the filter is MODE's, not the preset's own */
#define KEPT_CUT_OWN    0x20        /* the cutoff is the preset's, not PARAM1's */
#define KEPT_FLAGS      (KEPT | KEPT_MODE | KEPT_CUT_OWN)
/* the message's flags (the M7's) */
#define SOUND_APPLY     0x40
#define SOUND_HOLD      0x20
#define SOUND_OWN       0x10
#define SOUND_ARM2      0x08
#define SOUND_ARM1      0x04

typedef struct {
    uint32_t ref1 : 12;             /* the knobs when they got their jobs (0-4095) */
    uint32_t ref2 : 12;
    uint32_t role : 2;              /* what PARAM2 sets */
    uint32_t armed : 2;             /* bits: this knob follows (1 PARAM1, 2 PARAM2) */
    uint32_t own : 1;               /* the filter is the preset's own */
    uint32_t kept : 1;              /* the values come from a kit, or it's run Akords */
    uint32_t running : 1;           /* it ran Akords at the last look */
    uint8_t mode_ref;               /* MODE when the preset was chosen */
    uint8_t val[NKEPT];
} sound_t;

#define PACKED          (3 + NKEPT) /* a voice packed: 4 + 4 + 4 + 4 + 3 bits, the flags, the values */
#define RECORD          (NSET + 1 + NKEPT)      /* a voice in the record */
PK_AXI static uint8_t kit_set[NKITS][4][PACKED];        /* each kit's settings and sound, per voice */
PK_AXI static sound_t snd[4];                   /* the sound playing */
/* a kit loaded: the M7 holds its sound until the positions arrive (ms, low 16 bits) */
#define HOLD_SETTLED_MS 20          /* the playing values have matched the kit's this long */
#define HOLD_MAX_MS     2000        /* or this long (locks or an LFO keep them apart) */
PK_AXI static uint16_t hold_from, hold_matched;
PK_AXI static uint8_t holding;
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

/* a kit's table entry: preset | chord << 4, scale | root << 4, progression | flags, values */
static void pack_settings(uint8_t to[PACKED], const uint8_t from[NSET], uint8_t flags, const uint8_t val[NKEPT])
{
    to[0] = (uint8_t)(from[0] | from[1] << 4);
    to[1] = (uint8_t)(from[2] | from[3] << 4);
    to[2] = (uint8_t)(from[4] | flags);
    for (int i = 0; i < NKEPT; i++)
        to[3 + i] = val[i];
}

static void unpack_settings(uint8_t to[NSET], const uint8_t from[PACKED])
{
    to[0] = from[0] & 15;
    to[1] = from[0] >> 4;
    to[2] = from[1] & 15;
    to[3] = from[1] >> 4;
    to[4] = from[2] & 7;
}

/* the settings (a knob turned alone doesn't write the card on leaving the page) */
static int same(const uint8_t a[4][PACKED], const uint8_t b[4][NSET])
{
    for (int v = 0; v < 4; v++) {
        uint8_t s[NSET];
        unpack_settings(s, a[v]);
        for (int i = 0; i < NSET; i++)
            if (s[i] != b[v][i])
                return 0;
    }
    return 1;
}

/* ---- the sound ------------------------------------------------------------------------ */

static uint32_t base12(int v, int slot)
{
    return FW_U16(fw_voice_state(v) + FW_VS_BASE + 2 * slot) >> 4;
}

/* what PARAM2 sets, for ALGO's position */
static uint8_t role_now(int v)
{
    int algo = FW_U16(fw_voice_state(v) + FW_VS_BASE + 2 * FW_SLOT_ALGO);
    return algo == POS1 ? V_RES : (algo == POS3 ? V_ATTACK : V_ENV);
}

static uint8_t mode_now(int v)
{
    return (uint8_t)FW_U16(fw_voice_state(v) + FW_VS_BASE + 2 * FW_SLOT_MODE);
}

static uint8_t to_val(uint32_t x)
{
    return (uint8_t)((x * 255u + 2047u) / 4095u);
}

/* the knobs of a voice running Akords, by the M7's rules */
static void sound_follow(int v)
{
    sound_t *s = &snd[v];
    int x1 = (int)base12(v, FW_SLOT_PARAM1), x2 = (int)base12(v, FW_SLOT_PARAM2);
    uint8_t r = role_now(v);
    if (r != s->role) {                 /* a new job: keep the value until the knob moves */
        s->role = r;
        s->armed &= 1;
        s->ref2 = (uint32_t)x2;
    }
    int d1 = x1 - (int)s->ref1, d2 = x2 - (int)s->ref2;
    if (d1 > MOVED || d1 < -MOVED)
        s->armed |= 1;
    if (d2 > MOVED || d2 < -MOVED)
        s->armed |= 2;
    if (s->armed & 2)
        s->val[s->role - V_RES] = to_val((uint32_t)x2);
    if (mode_now(v) != s->mode_ref)
        s->own = 0;
}

/* a kit's or a fresh voice's values take over, the knobs where they are now */
static void sound_set(int v, const uint8_t *e)
{
    sound_t *s = &snd[v];
    s->role = role_now(v);
    s->mode_ref = mode_now(v);
    s->ref1 = base12(v, FW_SLOT_PARAM1);
    s->ref2 = base12(v, FW_SLOT_PARAM2);
    s->kept = e && e[2] & KEPT;
    s->own = !(s->kept && e[2] & KEPT_MODE);
    for (int i = 0; i < NKEPT; i++)
        s->val[i] = s->kept ? e[3 + i] : VAL_OWN;
    if (!s->kept) {                     /* no values: the knobs are the settings */
        s->armed = 3;
        sound_follow(v);
    } else {                            /* a value on its knob just follows it */
        int d = (int)to_val(s->ref2) - (int)s->val[s->role - V_RES];
        s->armed = (e[2] & KEPT_CUT_OWN ? 0 : 1) | (d >= -1 && d <= 1 ? 2 : 0);
    }
}

/* the voices (bits) to the M7 */
static void sound_send(uint8_t voices, uint8_t hold)
{
    uint8_t msg[4 * (1 + NVAL)];
    for (int v = 0; v < 4; v++) {
        const sound_t *s = &snd[v];
        msg[v * 5] = voices >> v & 1 ? (uint8_t)(SOUND_APPLY | hold | s->role | (s->own ? SOUND_OWN : 0)
                                                 | (s->armed & 1 ? SOUND_ARM1 : 0)
                                                 | (s->armed & 2 ? SOUND_ARM2 : 0)) : 0;
        msg[v * 5 + 1] = s->armed & 1 ? to_val(base12(v, FW_SLOT_PARAM1)) : VAL_OWN;
        for (int i = 0; i < NKEPT; i++)
            msg[v * 5 + 2 + i] = s->val[i];
    }
    pk_send_m7(PK_STREAM_AKORDS_SOUND, PK_MSG_AKORDS_SOUND, msg, sizeof msg);
}

/* the voice's playing values are the kit's */
static int arrived(int v)
{
    static const uint8_t SLOTS[4] = {FW_SLOT_PARAM1, FW_SLOT_PARAM2, FW_SLOT_ALGO, FW_SLOT_MODE};
    const uint8_t *vs = fw_voice_state(v);
    for (int i = 0; i < 4; i++)
        if (FW_U16(vs + FW_VS_VALUE + 2 * SLOTS[i]) != FW_U16(vs + FW_VS_BASE + 2 * SLOTS[i]))
            return 0;
    return 1;
}

/* the M7 holding a kit's sound: let it go once the positions have arrived */
static void hold_poll(void)
{
    uint16_t now = (uint16_t)fw_get_tick();
    for (int v = 0; v < 4; v++)
        if (snd[v].running && !arrived(v))
            hold_matched = now;
    if ((uint16_t)(now - hold_matched) >= HOLD_SETTLED_MS || (uint16_t)(now - hold_from) >= HOLD_MAX_MS) {
        holding = 0;
        sound_send(15, 0);
    }
}

/* each voice running Akords follows its knobs; one that has just started running it gets
 * its values again (voice-map builds a new engine at the next note) */
static void sound_poll(void)
{
    uint8_t started = 0;
    for (int v = 0; v < 4; v++) {
        sound_t *s = &snd[v];
        int on = pk_vm_engine(v) == PK_AK_ENGINE;
        if (on && !s->running) {
            if (!s->kept) {
                sound_set(v, 0);
                s->kept = 1;
            }
            started |= (uint8_t)(1u << v);
        } else if (on) {
            sound_follow(v);
        }
        s->running = (uint8_t)on;
    }
    if (started)
        sound_send(started, 0);
    if (holding)
        hold_poll();
}

/* a preset pressed: all its own values, its own filter; each knob takes over when it moves */
static void sound_preset(int v)
{
    uint8_t e[PACKED] = {0, 0, KEPT, VAL_OWN, VAL_OWN, VAL_OWN};
    sound_set(v, e);
    snd[v].armed = 0;
}


/* kit loads (chained with the other mods' kit hooks): the kit's settings */
void PK_NEXT(pk_ak_kit_load)(int kit);

void pk_ak_kit_load(int kit)
{
    PK_NEXT(pk_ak_kit_load)(kit);
    if (kit < 0 || kit >= NKITS)
        return;
    for (int v = 0; v < 4; v++) {
        unpack_settings(cur[v], kit_set[kit][v]);
        sound_set(v, kit_set[kit][v]);
    }
    send(0);
    holding = 1;
    hold_from = hold_matched = (uint16_t)fw_get_tick();
    sound_send(15, SOUND_HOLD);
}

/* the host's kit sidecar, record "AKRD": [voice][preset, chord, scale, root, progression,
 * flags, resonance, env amount, attack]; none = all 0. A voice not running Akords
 * keeps its settings but no sound. */
uint32_t pk_ak_kit_save(int bank, int kit, uint8_t *buf, uint32_t max)
{
    (void)bank;
    static const uint8_t none[NKEPT];
    uint32_t n = 4 * RECORD, any = 0;
    sound_poll();
    for (int v = 0; v < 4; v++) {
        const sound_t *s = &snd[v];
        uint8_t flags = s->running ? (uint8_t)(KEPT | (s->own ? 0 : KEPT_MODE)
                                               | (s->armed & 1 ? 0 : KEPT_CUT_OWN)) : 0;
        const uint8_t *val = s->running ? s->val : none;
        pack_settings(kit_set[kit][v], cur[v], flags, val);
        if (max >= n) {
            uint8_t *r = buf + v * RECORD;
            for (int i = 0; i < NSET; i++)
                any |= r[i] = cur[v][i];
            any |= r[NSET] = flags;
            for (int i = 0; i < NKEPT; i++)
                r[NSET + 1 + i] = val[i];
        }
    }
    return max >= n && any ? n : 0;
}

/* the 14 chord types of a 4 x 4 record: Minor 7 and Sus2 (plain, smooth) are gone; they
 * play Diatonic 7th and Diatonic */
static const uint8_t OLD_CHORD[14] = {0, 1, 2, 3, 4, 5, 2, 3, 0, 1, 6, 7, 8, 9};

void pk_ak_kit_restore(int bank, int kit, const uint8_t *rec, uint32_t len)
{
    (void)bank;
    int n = len == 4 * RECORD ? RECORD : (len == 4 * NSET ? NSET : (len == 4 * 4 ? 4 : 0));
    static const uint8_t none[NKEPT];
    for (int v = 0; v < 4; v++) {
        uint8_t set[NSET];
        for (int i = 0; i < NSET; i++) {
            uint8_t x = i < n ? rec[v * n + i] : 0;
            if (n == 4 && i == 1)
                x = x < 14 ? OLD_CHORD[x] : 0;
            set[i] = x < NPOS[i] ? x : 0;
        }
        const uint8_t *r = rec + v * RECORD;
        uint8_t flags = n == RECORD && r[NSET] & KEPT ? r[NSET] & KEPT_FLAGS : 0;
        pack_settings(kit_set[kit][v], set, flags, flags ? r + NSET + 1 : none);
    }
}

/* ---- DRIVE ---------------------------------------------------------------------------- */

/* Each voice's DRIVE (the value playing: knob, kit, locks) goes to the M7 when it changes
 * (message "akords-drive", 4 x 0-255, ordered: the stream the settings use): the engine's
 * level follows it. Checked from the main loop (every DRIVE_EVERY_MS), never from an
 * interrupt; sent again every DRIVE_RESEND_MS unchanged too, so a lost one heals. */
#define DRIVE_EVERY_MS  5
#define DRIVE_RESEND_MS 250
PK_AXI static uint8_t drive_sent[4];    /* 0 at boot, as the M7's */
PK_AXI static uint16_t drive_checked, drive_at;     /* ms, low 16 bits: the last check, the last send */

void PK_NEXT(pk_ak_main_loop)(void);

void pk_ak_main_loop(void)
{
    PK_NEXT(pk_ak_main_loop)();
    prog_stopped();
    uint16_t now_ms = (uint16_t)fw_get_tick();
    if ((uint16_t)(now_ms - drive_checked) < DRIVE_EVERY_MS)
        return;
    drive_checked = now_ms;
    sound_poll();
    uint8_t now[4];
    int changed = 0;
    for (int v = 0; v < 4; v++) {
        now[v] = (uint8_t)(FW_U16(fw_voice_state(v) + FW_VS_VALUE + 2 * FW_SLOT_DRIVE) >> 8);
        changed |= now[v] != drive_sent[v];
    }
    if (changed || (uint16_t)(now_ms - drive_at) >= DRIVE_RESEND_MS) {
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
            sound_preset(editing);
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
    if (kit >= 0 && kit < NKITS && !same(kit_set[kit], cur))
        pk_store_save_kit(bank, kit);
}
