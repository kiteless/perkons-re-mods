/* eight-lanes: lanes 5-8 in kits. A stock kit holds every voice's knob and
 * switch values (11 slots each) and is applied on kit load (also with kit-link on pattern
 * switch). Lanes: the 6 slots a lane uses (TUNE, DECAY, P1, P2, range, octave) per kit,
 * saved and loaded with the stock kit, stored in BANKS/NN/KITS/PP.KI2 (the .KIT format:
 * {1: 1, 3: {1: 11 slots x u16} x 4}). A kit without a .KI2 leaves the lanes as they are. */
#include "el.h"

#define NKITS           64
#define KIT_SLOTS       11
#define VS_BASE         0x6a        /* u16 x 11: knob/kit value of each slot */
#define VS_CATCH        0xf8        /* u8 x 11: pot catch armed */
#define DC_POT_CATCH    0x04
#define FA_READ         0x01u

#define fw_kit_load     FW_CALL(SYM_kit_load, void (*)(int kit))
#define fw_kit_save     FW_CALL(SYM_kit_save, void (*)(int bank, int kit))
#define fw_f_read       FW_CALL(SYM_f_read, int (*)(void *fil, void *buf, unsigned n, unsigned *got))

PK_AXI static uint16_t kit_value[NKITS][NLANES][NSLOTS];
PK_AXI static uint8_t kit_valid[NKITS];

static void path(char *buf, int bank, int kit)
{
    fw_snprintf(buf, 28, "BANKS/%02d/KITS/%02d.KI2", bank, kit);
}

static void write_kit(int bank, int kit)
{
    uint32_t voice = 1 + 1 + 2 * KIT_SLOTS;                    /* {1: bytes[22]} */
    uint32_t body = 2 + NLANES * (1 + 1 + voice);
    uint8_t b[8 + NLANES * 26];
    uint32_t n = el_put_varint(b, 0, body);
    b[n++] = 0x08; b[n++] = 1;
    for (int l = 0; l < NLANES; l++) {
        b[n++] = 0x1a; b[n++] = (uint8_t)voice;
        b[n++] = 0x0a; b[n++] = 2 * KIT_SLOTS;
        uint8_t *v = b + n;
        for (int i = 0; i < 2 * KIT_SLOTS; i++)
            v[i] = 0;
        for (int i = 0; i < NSLOTS; i++) {
            v[2 * el_slot_of[i]] = (uint8_t)kit_value[kit][l][i];
            v[2 * el_slot_of[i] + 1] = (uint8_t)(kit_value[kit][l][i] >> 8);
        }
        n += 2 * KIT_SLOTS;
    }
    char name[28];
    path(name, bank, kit);
    void *fil = PTR(SYM_json_file);
    unsigned put;
    if (fw_f_open(fil, name, FW_FA_WRITE_NEW) == 0) {
        fw_f_write(fil, b, n, &put);
        fw_f_close(fil);
    }
}

static void read_kit(int bank, int kit)
{
    char name[28];
    path(name, bank, kit);
    void *fil = PTR(SYM_json_file);
    uint8_t b[8 + NLANES * 26 + 64];
    unsigned got = 0;
    if (fw_f_open(fil, name, FA_READ) != 0)
        return;
    fw_f_read(fil, b, sizeof b, &got);
    fw_f_close(fil);
    uint32_t i = 0, len = el_get_varint(b, got, &i);
    if (len > got - i)
        return;
    uint32_t end = i + len;
    int l = 0;
    while (i < end && l < NLANES) {
        uint32_t key = el_get_varint(b, end, &i);
        if ((key & 7) == 0) {
            el_get_varint(b, end, &i);
        } else if ((key & 7) == 2) {
            uint32_t n = el_get_varint(b, end, &i), sub = i;
            i += n;
            if (key >> 3 == 3 && i <= end) {
                uint32_t k = el_get_varint(b, i, &sub), vn = el_get_varint(b, i, &sub);
                if (k == 0x0a && vn == 2 * KIT_SLOTS && sub + vn <= i) {
                    for (int s = 0; s < NSLOTS; s++)
                        kit_value[kit][l][s] = (uint16_t)(b[sub + 2 * el_slot_of[s]] | b[sub + 2 * el_slot_of[s] + 1] << 8);
                    l++;
                }
            }
        } else {
            return;
        }
    }
    kit_valid[kit] = l == NLANES;
}

void el_kits_load_bank(int bank)
{
    for (int k = 0; k < NKITS; k++) {
        kit_valid[k] = 0;
        read_kit(bank, k);
    }
}

/* kit save (kit page): the voices' values into the kit and PP.KIT; lanes into PP.KI2 */
void pk_el_kit_save(int bank, int kit)
{
    fw_kit_save(bank, kit);
    if (kit < 0 || kit >= NKITS)
        return;
    for (int l = 0; l < NLANES; l++)
        for (int i = 0; i < NSLOTS; i++)
            kit_value[kit][l][i] = U16(el_state(FIRST_LANE + l) + VS_BASE + 2 * el_slot_of[i]);
    kit_valid[kit] = 1;
    write_kit(bank, kit);
}

/* kit load: the voices take the kit's values (and when stopped, play them now); lanes
 * alike, with pot catch re-armed as stock does for the voices */
void pk_el_kit_load(int kit)
{
    fw_kit_load(kit);
    if (kit < 0 || kit >= NKITS || !kit_valid[kit])
        return;
    int playing = el_seq()[SEQ_PLAY] == 1;
    uint8_t catch_on = FW_U8(SYM_device_config + DC_POT_CATCH);
    for (int l = 0; l < NLANES; l++) {
        uint8_t *vs = el_state(FIRST_LANE + l);
        for (int i = 0; i < NSLOTS; i++) {
            U16(vs + VS_BASE + 2 * el_slot_of[i]) = kit_value[kit][l][i];
            if (!playing)
                U16(vs + VS_VALUE + 2 * el_slot_of[i]) = kit_value[kit][l][i];
        }
        for (int i = 0; i < KIT_SLOTS; i++)
            vs[VS_CATCH + i] = catch_on;
    }
}
