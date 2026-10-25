/* fx-freeze, M4 side: the 2-way switch as freeze, switchable in config.
 *
 * Built by the M4 host (tools/perkons/m4host.py in the framework). In freeze mode the
 * switch no longer selects SHORT/LONG (fx_update always sees SHORT); at LONG it freezes:
 *   delay:  a looper; the last delay-time of the delay's output repeats, input closed
 *           (pk_fx_delay, recording into the shared FX buffer)
 *   reverb: (fx-reverb) the tail is held, as Elements; the reverb reads
 *           pk_fx_freeze_engaged()
 */
#include <stdint.h>
#include "pk_host.h"

#define NF              PK_FX_NF
#define XFADE           64          /* samples */
#define RING            pk_fx_buf
#define RING_LEN        PK_FX_BUF_LEN
#define LEVEL_SHORT     ((int)CONST_fx_switch_short_level)
#define LEVEL_FREEZE    (!LEVEL_SHORT)  /* LONG */

uint8_t pk_cfg_freeze;              /* device.json "fx-switch-freeze", config row 3 step 16 */
uint8_t pk_frozen;                  /* delay looper engaged */
int32_t pk_loop_len;

static uint8_t switch_level;        /* physical switch, last read */
static int32_t rec_w, loop_start, loop_pos;
static int32_t release;             /* crossfade counter after unfreezing */

static inline int16_t sat16(float x)
{
    return (int16_t)(x > 32767.0f ? 32767 : (x < -32768.0f ? -32768 : (int32_t)x));
}

/* replaces fx_update's SHORT/LONG read: in freeze mode the delay always sees SHORT */
int pk_fx_read_switch(void *port, uint16_t pin)
{
    int level = fw_gpio_read(port, pin);
    switch_level = (uint8_t)level;
    if (pk_host_booted() && pk_cfg_freeze)
        return LEVEL_SHORT;
    return level;
}

int pk_fx_switch_is_freeze(void)
{
    return pk_cfg_freeze;
}

int pk_fx_freeze_engaged(void)
{
    return pk_cfg_freeze && switch_level == LEVEL_FREEZE;
}

void pk_fx_reset(void)
{
    pk_frozen = 0;
    release = 0;
    rec_w = 0;
}

static int16_t ring_at(int32_t i)
{
    return RING[i & (RING_LEN - 1)];
}

/* the delay: stock BBD, plus the looper */
void pk_fx_delay(const int16_t *in, int16_t *out)
{
    static const int16_t silence[2 * NF];
    int frz = pk_fx_freeze_engaged();

    if (frz && !pk_frozen) {
        /* capture: loop the last delay-time of the delay's output */
        float ticks = FW_BBD_TICKS;
        int32_t len = ticks > 0.0f ? (int32_t)((float)FW_BBD_STAGES / ticks) : 4800;
        if (len < 2 * XFADE)
            len = 2 * XFADE;
        if (len > RING_LEN - 2 * XFADE)
            len = RING_LEN - 2 * XFADE;
        pk_loop_len = len;
        loop_start = rec_w - len;
        loop_pos = 0;
        pk_frozen = 1;
    } else if (!frz && pk_frozen) {
        pk_frozen = 0;
        release = XFADE;
    }

    /* the BBD keeps running (input muted while frozen) so release continues naturally */
    fw_fx_bbd_process(frz ? silence : in, out);

    for (int f = 0; f < NF; f++) {
        int16_t bbd = out[2 * f];
        if (!pk_frozen) {
            RING[rec_w & (RING_LEN - 1)] = bbd;
            rec_w++;
        }
        if (pk_frozen || release > 0) {
            int32_t p = loop_pos, len = pk_loop_len;
            float loop = ring_at(loop_start + p);
            if (p >= len - XFADE) {            /* seam: fade into the audio before the start */
                float a = (float)(len - p) / XFADE;
                loop = loop * a + (float)ring_at(loop_start + p - len) * (1.0f - a);
            }
            if (++loop_pos >= len)
                loop_pos = 0;
            if (pk_frozen) {
                out[2 * f] = sat16(loop);
            } else {                            /* release: crossfade loop -> live delay */
                float a = (float)release / XFADE;
                out[2 * f] = sat16(loop * a + (float)bbd * (1.0f - a));
                release--;
            }
        }
    }
}
