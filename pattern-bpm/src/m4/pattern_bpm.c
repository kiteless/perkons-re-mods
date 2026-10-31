/* pattern-bpm: each pattern keeps the tempo it was saved at, and plays at it.
 *
 * On (config row 3 step 14): saving a pattern stores the tempo in its sidecar record
 * (the M4 host's PP.PAX); when the playing pattern changes (queued, chained, chosen on
 * the PATTERN page, a bank load), a pattern with a stored tempo sets it through the
 * stock tempo setter, so the TEMPO knob catches it as after the tempo page or tap tempo.
 * Nothing happens with an external clock, for patterns saved without a tempo, or while
 * the setting is off (then nothing is saved either). */
#include <stdint.h>
#include "pk_host.h"

#define NPATTERNS       64

PK_AXI uint8_t pk_cfg_pattern_bpm;          /* system/mods.json "pattern-bpm" */
PK_AXI static uint16_t bpm10[NPATTERNS];    /* each pattern's tempo x 10; 0 = none */

static int pattern_of(uint32_t hdr)
{
    uint32_t off = hdr - (uint32_t)SYM_pat_headers;
    return off < NPATTERNS * FW_HDR_SIZE && off % FW_HDR_SIZE == 0 ? (int)(off / FW_HDR_SIZE) : -1;
}

/* the host's pattern sidecar, record "BPM1": u16 tempo x 10 */
uint32_t pk_pb_save(int bank, int idx, uint8_t *buf, uint32_t max)
{
    (void)bank;
    if (!pk_cfg_pattern_bpm || max < 2)
        return 0;
    uint32_t v = (uint32_t)(FW_F32(SYM_tempo_state + FW_TEMPO_BPM) * 10.0f + 0.5f);
    bpm10[idx] = (uint16_t)v;
    buf[0] = (uint8_t)v;
    buf[1] = (uint8_t)(v >> 8);
    return 2;
}

void pk_pb_load(int bank, int idx, const uint8_t *rec, uint32_t len)
{
    (void)bank;
    bpm10[idx] = len == 2 ? (uint16_t)(rec[0] | rec[1] << 8) : 0;
}

/* host event pattern_switched */
void pk_pb_switched(void)
{
    if (!pk_cfg_pattern_bpm || FW_U8(SYM_device_config + FW_DC_CLOCK_SRC) != 0)
        return;
    int p = pattern_of(FW_U32(SYM_switch_record + FW_SWITCH_NEW));
    if (p >= 0 && bpm10[p])
        fw_tempo_set(bpm10[p] / 10.0f);
}
