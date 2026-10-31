/* eight-lanes: MIDI in for lanes 5-8, as stock routes it to voices.
 * Multi-channel: a note on a lane's channel plays the lane, records into it in REC (note
 * and velocity into the nearest step), and writes held steps on page B (step entry).
 * Single-channel: a lane's trigger note does the same (in REC: on + velocity only, as
 * stock). midi-velocity off = 127. Voices sharing a channel still get it (stock path). */
#include "el.h"

#define DC_MIDI_VEL     0x1b

#define fw_held_begin   FW_CALL(SYM_held_first, void (*)(void *it))
#define fw_held_next    FW_CALL(SYM_held_next, int (*)(void *it))

uint8_t el_lane_channel(int l);
uint8_t el_lane_trig_note(int l);
void el_lane_live_note(int l, int on, int note, int vel);
extern uint8_t pk_el_page;

static void lane_note_on(int l, int note, int vel, int multi)
{
    if (!FW_U8(SYM_device_config + DC_MIDI_VEL))
        vel = 0x7f;
    uint8_t *vs = el_state(FIRST_LANE + l);
    const uint8_t *s = el_seq();
    if (s[FW_SEQ_PLAY] == 1 && FW_U8(SYM_rec_flags + 1)) {
        /* REC: the nearest step, as stock (later than half a step: the next one) */
        const uint8_t *clk = PTR(U32(vs + FW_VS_CLOCK));
        int step = U16(vs + FW_VS_STEP);
        if (U16(vs + FW_VS_SUBTICK) >= U16(clk + 0x1c) >> 1) {
            int16_t nx = (int16_t)U16(vs + FW_VS_NEXT);
            if (nx >= 0)
                step = nx;
        }
        uint8_t *rec = PTR(U32(vs + FW_VS_BLOCK)) + 8 * step;
        rec[7] = (uint8_t)vel;
        rec[0] = 1;
        if (multi)
            rec[6] = (uint8_t)note;
    } else if (multi && pk_el_page && fw_steps_held()) {
        /* step entry: held steps of the lane's row get the note */
        uint32_t it[2];
        fw_held_begin(it);
        int key;
        while ((key = fw_held_next(it)) != -1) {
            if ((key >> 4) != l)
                continue;
            uint8_t *rec = PTR(U32(vs + FW_VS_BLOCK)) + 8 * (key & 15);
            rec[6] = (uint8_t)note;
            rec[0] = 1;
            rec[7] = (uint8_t)vel;
        }
    }
    el_lane_live_note(l, 1, multi ? note : 36, vel);
}

#define fw_cc_map       FW_CALL(SYM_cc_map, const uint8_t *(*)(int voice))

/* a CC on a lane's channel records into the lane's slot, as stock does for voices (the
 * row's CC numbers; switches on a 0-2 scale) */
static void lane_cc(int l, uint8_t cc, uint8_t val)
{
    const uint8_t *map = fw_cc_map(l);
    uint8_t *vs = el_state(FIRST_LANE + l);
    for (int i = 0; i < NSLOTS; i++) {
        uint32_t slot = el_slot_of[i];
        if (map[slot] != cc)
            continue;
        uint32_t v = slot >= 8 ? (uint32_t)val * 3u / 128u : (uint32_t)val * 0x204u;
        fw_record(vs + FW_VS_LOCKS, slot, v, pk_el_page ? l : 0xff, U16(vs + FW_VS_STEP));
    }
}

/* the MIDI message dispatcher: lanes on their channels (multi-channel mode) */
void PK_NEXT(pk_el_midi_in)(uint8_t *msg);

void pk_el_midi_in(uint8_t *msg)
{
    uint8_t st = msg[0] & 0xf0, ch = msg[0] & 15;
    if (FW_U8(SYM_device_config + FW_DC_MULTI) && (st == 0x80 || st == 0x90 || st == 0xb0)) {
        for (int l = 0; l < NLANES; l++) {
            if (el_lane_channel(l) != ch)
                continue;
            if (st == 0xb0)
                lane_cc(l, msg[1], msg[2]);
            else if (st == 0x90 && msg[2])
                lane_note_on(l, msg[1], msg[2], 1);
            else
                el_lane_live_note(l, 0, msg[1], 0);
        }
    }
    PK_NEXT(pk_el_midi_in)(msg);
}

/* note on/off callbacks: in single-channel mode (voice >= 4), lanes' trigger notes */
void PK_NEXT(pk_el_note_on)(int voice, int note, int vel);

void pk_el_note_on(int voice, int note, int vel)
{
    if (voice >= 4)
        for (int l = 0; l < NLANES; l++)
            if (note == el_lane_trig_note(l)) {
                lane_note_on(l, note, vel, 0);
                return;
            }
    PK_NEXT(pk_el_note_on)(voice, note, vel);
}

void PK_NEXT(pk_el_note_off)(int voice, int note);

void pk_el_note_off(int voice, int note)
{
    if (voice >= 4)
        for (int l = 0; l < NLANES; l++)
            if (note == el_lane_trig_note(l)) {
                el_lane_live_note(l, 0, 36, 0);
                return;
            }
    PK_NEXT(pk_el_note_off)(voice, note);
}
