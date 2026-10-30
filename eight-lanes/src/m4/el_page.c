/* eight-lanes: page B. SHIFT (held) + PATTERN flips the step grid between
 * page A (tracks 1-4, stock) and page B (lanes 5-8). On page B every UI path that finds
 * its track from a key row (step grid, LEDs, trigger keys, SHIFT settings, LAST, the MOD
 * page, mutes) gets lane row + 4 instead; the sound-engine controls follow the page
 * (TUNE, DECAY, PARAM1, PARAM2 and the ALGO/MODE switches), the analog section (CUTOFF,
 * DRIVE, FX SEND, LEVEL, FILTER) stays with voices 1-4. The PATTERN LED is dim on page B.
 * The sequencer core keeps the real track numbers throughout. */
#include "el.h"

#define KEY_PATTERN     0x40
#define KEY_SHIFT       0x47
#define LED_PATTERN     0x49
#define EV_DOWN         0x11
#define EV_UP           0x10
#define MODE_MAIN       0
#define MODE_SHIFT      1
#define MODE_PATTERN    4
#define MODE_BANK       0xf
#define LED_DIM         0x10

#define fw_key_event    FW_CALL(SYM_key_event, int (*)(const uint8_t *evt))
#define fw_key_held     FW_CALL(SYM_key_held, int (*)(int key))
#define fw_set_mode     FW_CALL(SYM_set_mode, void (*)(int mode))
#define fw_get_mode     FW_CALL(SYM_get_mode, int (*)(void))
#define fw_steps_held   FW_CALL(SYM_steps_held, int (*)(void))
#define fw_record       FW_CALL(SYM_seq_record, void (*)(uint8_t *locks, uint32_t slot, uint32_t value, int track, uint32_t step))
#define fw_clear_slot   FW_CALL(SYM_seq_clear_slot, void (*)(uint8_t *locks, uint32_t slot))
#define fw_voice_play   FW_CALL(SYM_voice_play, void (*)(int voice, int on, int note, int vel))
#define fw_trig_active  FW_CALL(SYM_trig_active, int (*)(int track))
#define fw_ui_update    FW_CALL(SYM_ui_update, void (*)(void))
#define fw_page0_render FW_CALL(SYM_page0_render, void (*)(void))

PK_AXI uint8_t pk_el_page;              /* 0 = page A, 1 = page B; page A at power-on */
PK_AXI static uint8_t shift_clean;      /* SHIFT down and no other key since */
PK_AXI static uint8_t gesture;          /* SHIFT + PATTERN was ours: swallow their key-ups */
PK_AXI static uint8_t cc_lane;          /* last knob/switch move went to lane cc_lane - 1 */

uint8_t el_lane_channel(int l);
#define fw_midi_out     FW_CALL(SYM_midi_out_bytes, void (*)(int port, uint32_t packed))

void el_lane_live(int lane, int on, int vel);   /* el_core.c */

static int lane_slot(uint32_t slot)
{
    for (int i = 0; i < NSLOTS; i++)
        if (el_slot_of[i] == slot)
            return 1;
    return 0;
}

static int track_of_locks(const uint8_t *locks)
{
    uint32_t off = ADDR(locks) - VS_LOCKS - ADDR(pk_el_states);
    return off < TRACKS * STATE && off % STATE == 0 ? (int)(off / STATE) : -1;
}

/* the UI's voice_state: key rows mean lanes on page B */
uint8_t *pk_el_ui_vs(int track)
{
    return el_state(pk_el_page && track < 4 ? track + FIRST_LANE : track);
}

/* knob and switch recording (record, lock held steps, pot catch): the engine controls of
 * a column belong to the lane on page B; the held-step rows stay physical rows */
void pk_el_record(uint8_t *locks, uint32_t slot, uint32_t value, int track, uint32_t step)
{
    int t = track_of_locks(locks);
    if (pk_el_page && t >= 0 && t < 4 && lane_slot(slot)) {
        uint8_t *vs = el_state(t + FIRST_LANE);
        locks = vs + VS_LOCKS;
        step = U16(vs + VS_STEP);
        cc_lane = (uint8_t)(t + 1);
    } else {
        cc_lane = 0;
    }
    fw_record(locks, slot, value, track, step);
}

/* CLEAR + knob touch / switch: erase that control's automation, on the lane on page B */
void pk_el_clear_slot(uint8_t *locks, uint32_t slot)
{
    int t = track_of_locks(locks);
    if (pk_el_page && t >= 0 && t < 4 && lane_slot(slot))
        locks = el_state(t + FIRST_LANE) + VS_LOCKS;
    fw_clear_slot(locks, slot);
}

/* the CC the stock code sends for that move: on the lane's channel (multi-channel; the
 * lane uses its row's CC numbers, as every voice does there); single-channel: none, the
 * lanes have no CC numbers of their own there */
void pk_el_cc_out(int port, uint32_t packed)
{
    if (cc_lane) {
        int l = cc_lane - 1;
        cc_lane = 0;
        if (!FW_U8(SYM_device_config + 0x1d))
            return;
        packed = (packed & ~0x0fu) | el_lane_channel(l);
    }
    fw_midi_out(port, packed);
}

/* trigger keys play the voice live; on page B the lane (MIDI) */
void pk_el_play(int voice, int on, int note, int vel)
{
    if (pk_el_page && voice >= 0 && voice < 4)
        el_lane_live(voice, on, vel);
    else
        fw_voice_play(voice, on, note, vel);
}

/* the MOD page shows each row's 11 values: the lanes' playing values on page B */
#define fw_mod_values   FW_CALL(SYM_mod_values, const uint16_t *(*)(int voice))

const uint16_t *pk_el_mod_values(int voice)
{
    if (pk_el_page && voice >= 0 && voice < 4)
        return (const uint16_t *)(el_state(voice + FIRST_LANE) + VS_VALUE);
    return fw_mod_values(voice);
}

/* note repeat page (9): lanes on page B */
void el_roll_hold(int l, int on);
void el_roll_rate_set(int l, int rate);
int el_roll_rate_get(int l);
#define fw_roll_hold    FW_CALL(SYM_roll_hold, void (*)(int track, int on))
#define fw_roll_rate_set FW_CALL(SYM_roll_rate_set, void (*)(int track, int rate))
#define fw_roll_rate_get FW_CALL(SYM_roll_rate_get, int (*)(int track))

void pk_el_roll_hold(int track, int on)
{
    if (!on) {                      /* releases (also the page's exit) reach both */
        el_roll_hold(track, 0);
        fw_roll_hold(track, 0);
    } else if (pk_el_page && track >= 0 && track < 4) {
        el_roll_hold(track, on);
    } else {
        fw_roll_hold(track, on);
    }
}

void pk_el_roll_rate_set(int track, int rate)
{
    if (pk_el_page && track >= 0 && track < 4)
        el_roll_rate_set(track, rate);
    else
        fw_roll_rate_set(track, rate);
}

int pk_el_roll_rate_get(int track)
{
    return pk_el_page && track >= 0 && track < 4 ? el_roll_rate_get(track) : fw_roll_rate_get(track);
}

/* trigger LEDs show the lanes' activity on page B */
int pk_el_trig_active(int track)
{
    return fw_trig_active(pk_el_page && track < 4 ? track + FIRST_LANE : track);
}

static void page_led(void)
{
    int mode = fw_get_mode();
    if (pk_el_page && mode != MODE_PATTERN && mode != MODE_BANK && !fw_steps_held())
        fw_set_led(LED_PATTERN, LED_DIM);
}

void pk_el_ui_update(void)
{
    fw_ui_update();
    page_led();
}

void pk_el_page0_render(void)
{
    fw_page0_render();
    page_led();
}

/* the key handler copies every voice's knob values (FUN_0810ca1c, 4 voices) before
 * this call: the lanes' too */
#define fw_store_values FW_CALL(SYM_store_values, void (*)(uint8_t *locks))
#define fw_after_store  FW_CALL(SYM_after_store_values, void (*)(void))

void pk_el_after_store_values(void)
{
    for (int t = FIRST_LANE; t < TRACKS; t++)
        fw_store_values(el_state(t) + VS_LOCKS);
    fw_after_store();
}

/* key events (before the stock handler): SHIFT + PATTERN on a clean press flips the page */
int pk_el_key_event(const uint8_t *evt)
{
    uint8_t key = evt[0], type = evt[1];
    if (type == EV_DOWN) {
        if (key == KEY_SHIFT) {
            shift_clean = 1;
        } else if (key == KEY_PATTERN && shift_clean && fw_key_held(KEY_SHIFT)) {
            pk_el_page ^= 1;           /* again while SHIFT stays held: flips back */
            gesture = 1;
            return 1;
        } else {
            shift_clean = 0;
        }
    } else if (type == EV_UP && gesture) {
        if (key == KEY_PATTERN)
            return 1;                   /* no pattern-menu latch from our press */
        if (key == KEY_SHIFT) {
            gesture = 0;
            if (fw_get_mode() == MODE_SHIFT)
                fw_set_mode(MODE_MAIN); /* no SHIFT-menu latch either */
            return 1;
        }
    }
    return fw_key_event(evt);
}
