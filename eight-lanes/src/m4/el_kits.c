/* eight-lanes: lanes 5-8 in kits. A stock kit holds every voice's knob and
 * switch values (11 slots each) and is applied on kit load (also with kit-link on pattern
 * switch). Lanes: the 6 slots a lane uses (TUNE, DECAY, P1, P2, range, octave) per kit,
 * saved and loaded with the stock kit, in the host's kit sidecar (KITS/PP.KIX, record
 * "EL8K"). A kit without one leaves the lanes as they are. */
#include "el.h"

#define NKITS           64
#define KIT_SLOTS       11


PK_AXI static uint16_t kit_value[NKITS][NLANES][NSLOTS];
PK_AXI static uint8_t kit_valid[NKITS];

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
    pk_copy(buf, kit_value[kit], sizeof kit_value[kit]);
    return sizeof kit_value[kit];
}

void pk_el_kit_rec_load(int bank, int kit, const uint8_t *rec, uint32_t len)
{
    (void)bank;
    kit_valid[kit] = len == sizeof kit_value[kit];
    if (kit_valid[kit])
        pk_copy(kit_value[kit], rec, len);
}

/* kit save (kit page): the voices' values into the kit and PP.KIT; the lanes' into the
 * kit's record (the host writes the sidecar after) */
int PK_NEXT(pk_el_kit_save)(int bank, int kit);

int pk_el_kit_save(int bank, int kit)
{
    int r = PK_NEXT(pk_el_kit_save)(bank, kit);    /* the kit page flashes the step on it */
    if (kit < 0 || kit >= NKITS)
        return r;
    for (int l = 0; l < NLANES; l++)
        for (int i = 0; i < NSLOTS; i++)
            kit_value[kit][l][i] = FW_U16(el_state(FIRST_LANE + l) + FW_VS_BASE + 2 * el_slot_of[i]);
    kit_valid[kit] = 1;
    return r;
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
            FW_U16(vs + FW_VS_BASE + 2 * el_slot_of[i]) = kit_value[kit][l][i];
            if (!playing)
                FW_U16(vs + FW_VS_VALUE + 2 * el_slot_of[i]) = kit_value[kit][l][i];
        }
        for (int i = 0; i < KIT_SLOTS; i++)
            vs[FW_VS_CATCH + i] = catch_on;
    }
}
