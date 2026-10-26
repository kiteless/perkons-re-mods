/* Voice map, M4 side: after a bank's samples load, read the voice map and send it to
 * the M7 (config stream, type PK_MSG_VOICE_MAP, 4 bytes = engine 0-3 per output).
 *
 * voices.json: {"voice1": N, "voice2": N, "voice3": N, "voice4": N}, N = 1-4 for the
 * stock engines, 5 and up for engines other mods add (e.g. zibens). Missing keys, 0, values
 * above 15 or an unreadable file mean "stock" for that output; the M7 also treats
 * engines that aren't built in as stock.
 * Lookup: BANKS/NN/voices.json if PK_PER_BANK and it exists, else voices.json in the root.
 *
 * Hook: the three `bl load_samples` calls (boot_init, switch_bank, boot_load_last_bank)
 * -> pk4_load_samples.
 */
#include <stdint.h>
#include "fw_m4.h"

#define PK_MSG_VOICE_MAP 4

#ifndef PK_PER_BANK
#define PK_PER_BANK 0
#endif

static const fw_json_entry_t voice_keys[4] = {
    {"voice1", 0, FW_JSON_U8, 0, 0},
    {"voice2", 1, FW_JSON_U8, 0, 0},
    {"voice3", 2, FW_JSON_U8, 0, 0},
    {"voice4", 3, FW_JSON_U8, 0, 0},
};
static const fw_json_schema_t voice_schema = {voice_keys, 4};

static void load_voice_map(int bank, uint8_t cfg[4])
{
#if PK_PER_BANK
    char path[32];
    fw_snprintf(path, sizeof path, "BANKS/%02d/voices.json", bank);
    if (fw_file_exists(path)) {
        fw_json_load(path, &voice_schema, cfg);
        return;
    }
#else
    (void)bank;
#endif
    fw_json_load("voices.json", &voice_schema, cfg);
}

void pk4_load_samples(int bank)
{
    fw_load_samples(bank);

    uint8_t cfg[4] = {0, 0, 0, 0};
    load_voice_map(bank, cfg);
    uint8_t map[4];
    for (unsigned out = 0; out < 4; out++)
        map[out] = (cfg[out] >= 1 && cfg[out] <= 15) ? (uint8_t)(cfg[out] - 1) : (uint8_t)out;
    fw_ipc_send(FW_IPC_CONFIG, map, 4, PK_MSG_VOICE_MAP);
}
