/* eight-lanes: lanes 5-8 in kits. A stock kit holds every voice's knob and
 * switch values (11 slots each) and is applied on kit load (also with kit-link on pattern
 * switch). Lanes: the 6 slots a lane uses (TUNE, DECAY, P1, P2, range, octave) per kit,
 * saved and loaded with the stock kit, in the host's kit sidecar (KITS/PP.KIX, record
 * "EL8K"); older cards' PP.KI2 (the .KIT format: {1: 1, 3: {1: 11 slots x u16} x 4}) are
 * still read. A kit without either leaves the lanes as they are. */
#include "el.h"

#define NKITS           64
#define KIT_SLOTS       11


PK_AXI static uint16_t kit_value[NKITS][NLANES][NSLOTS];
PK_AXI static uint8_t kit_valid[NKITS];

static void path(char *buf, int bank, int kit)
{
    fw_snprintf(buf, 28, "BANKS/%02d/KITS/%02d.KI2", bank, kit);
}

/* legacy BANKS/NN/KITS/PP.KI2 (before the host's sidecar files): the .KIT format; read
 * when a kit has no record yet, deleted when it is saved */
static void read_kit(int bank, int kit)
{
    char name[28];
    path(name, bank, kit);
    void *fil = PTR(SYM_json_file);
    uint8_t b[8 + NLANES * 26 + 64];
    unsigned got = 0;
    if (fw_f_open(fil, name, FW_FA_READ) != 0)
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

void el_kits_clear(void)
{
    for (int k = 0; k < NKITS; k++)
        kit_valid[k] = 0;
}

/* the host's kit sidecar (KITS/PP.KIX, record "EL8K"): the lanes' 6 slots x 4 */
uint32_t pk_el_kit_rec_save(int bank, int kit, uint8_t *buf, uint32_t max)
{
    (void)bank;
    if (!kit_valid[kit] || sizeof kit_value[kit] > max)
        return 0;
    el_copy(buf, kit_value[kit], sizeof kit_value[kit]);
    return sizeof kit_value[kit];
}

void pk_el_kit_rec_load(int bank, int kit, const uint8_t *rec, uint32_t len)
{
    kit_valid[kit] = 0;
    if (len == sizeof kit_value[kit]) {
        el_copy(kit_value[kit], rec, len);
        kit_valid[kit] = 1;
    } else if (!len) {
        read_kit(bank, kit);                    /* none: a legacy PP.KI2, if any */
    }
}

/* kit save (kit page): the voices' values into the kit and PP.KIT; lanes into PP.KI2 */
void PK_NEXT(pk_el_kit_save)(int bank, int kit);

void pk_el_kit_save(int bank, int kit)
{
    PK_NEXT(pk_el_kit_save)(bank, kit);
    if (kit < 0 || kit >= NKITS)
        return;
    for (int l = 0; l < NLANES; l++)
        for (int i = 0; i < NSLOTS; i++)
            kit_value[kit][l][i] = U16(el_state(FIRST_LANE + l) + FW_VS_BASE + 2 * el_slot_of[i]);
    kit_valid[kit] = 1;
    char name[28];
    path(name, bank, kit);
    fw_f_unlink(name);                          /* legacy file: the host writes PP.KIX now */
}

/* kit load: the voices take the kit's values (and when stopped, play them now); lanes
 * alike, with pot catch re-armed as stock does for the voices */
void PK_NEXT(pk_el_kit_load)(int kit);

void pk_el_kit_load(int kit)
{
    PK_NEXT(pk_el_kit_load)(kit);
    if (kit < 0 || kit >= NKITS || !kit_valid[kit])
        return;
    int playing = el_seq()[FW_SEQ_PLAY] == 1;
    uint8_t catch_on = FW_U8(SYM_device_config + FW_DC_POT_CATCH);
    for (int l = 0; l < NLANES; l++) {
        uint8_t *vs = el_state(FIRST_LANE + l);
        for (int i = 0; i < NSLOTS; i++) {
            U16(vs + FW_VS_BASE + 2 * el_slot_of[i]) = kit_value[kit][l][i];
            if (!playing)
                U16(vs + FW_VS_VALUE + 2 * el_slot_of[i]) = kit_value[kit][l][i];
        }
        for (int i = 0; i < KIT_SLOTS; i++)
            vs[FW_VS_CATCH + i] = catch_on;
    }
}
