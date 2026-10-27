/* Voice map, M4 side: after a bank's samples load, read the voice map and send it to
 * the M7 (config stream, type PK_MSG_VOICE_MAP, 4 bytes = engine index per output).
 *
 * voices.json: {"voice1": "voice4", "voice2": "zibens", ...}: each output names the
 * engine it runs, "voice1"-"voice4" for the stock voices' engines, and the names other
 * mods register (e.g. "zibens"; generated into pk_engine_names.h). Missing keys,
 * unknown names or an unreadable file mean "stock" for that output. Lookup:
 * BANKS/NN/voices.json if PK_PER_BANK and it exists, else voices.json in the root.
 *
 * Hook: the three `bl load_samples` calls (boot_init, switch_bank, boot_load_last_bank)
 * -> pk4_load_samples.
 */
#include <stdint.h>
#include "fw_m4.h"
#include "pk_engine_names.h"    /* PK_ENGINE_NAMES: "", "voice1" .. "voice4", extras */

#define PK_MSG_VOICE_MAP 4

#ifndef PK_PER_BANK
#define PK_PER_BANK 0
#endif

/* index = engine number: 0 = unknown/stock (what the loader stores for no match),
 * 1-4 = the stock engines, 5 and up = engines from other mods */
static const char *const engine_names[] = {PK_ENGINE_NAMES};
static const fw_json_enum_t engine_enum = {engine_names, sizeof engine_names / sizeof engine_names[0]};

static const fw_json_entry_t by_name_keys[4] = {
    {"voice1", 0, FW_JSON_ENUM, &engine_enum, 0},
    {"voice2", 1, FW_JSON_ENUM, &engine_enum, 0},
    {"voice3", 2, FW_JSON_ENUM, &engine_enum, 0},
    {"voice4", 3, FW_JSON_ENUM, &engine_enum, 0},
};
static const fw_json_schema_t by_name = {by_name_keys, 4};

static const char *voice_map_path(int bank, char *buf, unsigned size)
{
#if PK_PER_BANK
    fw_snprintf(buf, size, "BANKS/%02d/voices.json", bank);
    if (fw_file_exists(buf))
        return buf;
#else
    (void)bank;
    (void)buf;
    (void)size;
#endif
    return "voices.json";
}

void pk4_load_samples(int bank)
{
    fw_load_samples(bank);

    char buf[32];
    const char *path = voice_map_path(bank, buf, sizeof buf);
    uint8_t engine[4] = {0, 0, 0, 0};
    fw_json_load(path, &by_name, engine);

    uint8_t map[4];
    for (unsigned out = 0; out < 4; out++)
        map[out] = engine[out] ? (uint8_t)(engine[out] - 1) : (uint8_t)out;
    fw_ipc_send(FW_IPC_CONFIG, map, 4, PK_MSG_VOICE_MAP);
}
