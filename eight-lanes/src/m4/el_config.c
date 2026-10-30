/* eight-lanes: lane MIDI settings, in system/mods.json beside the stock
 * device.json values. Channels 5-8 (0-based 4-7) by default; single-channel trigger
 * notes 40-43, after the stock 36-39, edited on the card like the stock ones (stock has
 * no on-unit editor for trigger notes).
 *
 * The stock MIDI channel page (UI page 12, rows = voices) shows and sets lanes 5-8 in
 * the same rows while SHIFT is held, in multi-channel view; leaving the page saves both
 * files as before. */
#include "el.h"

#define KEY_SHIFT       0x47
#define EV_DOWN         0x11
#define LED_ON          0x80

#define fw_key_held     FW_CALL(SYM_key_held, int (*)(int key))
#define fw_page_event   FW_CALL(SYM_midi_page_event, int (*)(const uint8_t *evt))
#define fw_page_render  FW_CALL(SYM_midi_page_render, void (*)(void))

PK_AXI uint8_t pk_el_ch5, pk_el_ch6, pk_el_ch7, pk_el_ch8;
PK_AXI uint8_t pk_el_tn5, pk_el_tn6, pk_el_tn7, pk_el_tn8;

static uint8_t *const channel[NLANES] = {&pk_el_ch5, &pk_el_ch6, &pk_el_ch7, &pk_el_ch8};
static uint8_t *const trig_note[NLANES] = {&pk_el_tn5, &pk_el_tn6, &pk_el_tn7, &pk_el_tn8};

void el_config_defaults(void)
{
    for (int l = 0; l < NLANES; l++) {
        *channel[l] = (uint8_t)(4 + l);
        *trig_note[l] = (uint8_t)(40 + l);
    }
}

uint8_t el_lane_channel(int l)
{
    return *channel[l] & 15;
}

uint8_t el_lane_trig_note(int l)
{
    return *trig_note[l] & 127;
}

static int lanes_shown(void)
{
    return FW_U8(SYM_midi_page_multi) && fw_key_held(KEY_SHIFT);
}

int pk_el_midi_page_event(const uint8_t *evt)
{
    if (evt[1] == EV_DOWN && evt[0] < 0x40 && lanes_shown()) {
        *channel[evt[0] >> 4] = evt[0] & 15;
        FW_U8(SYM_midi_page_dirty) = 1;
        return 1;
    }
    return fw_page_event(evt);
}

void pk_el_midi_page_render(void)
{
    if (!lanes_shown()) {
        fw_page_render();
        return;
    }
    for (int row = 0; row < NLANES; row++)
        for (int col = 0; col < 16; col++)
            fw_set_led(row * 16 + col, col == el_lane_channel(row) ? LED_ON : 0);
}
