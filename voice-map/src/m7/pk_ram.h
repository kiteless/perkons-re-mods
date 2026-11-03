/* Voice-map mod: M7 RAM it owns, one engine arena per output from the base of the VOICE
 * area (its other state is ordinary globals, in the M7 host's RAM). Keep in sync with
 * lib/vm_model.py (tests check this). The newlib heap is capped below PK_RAM_BASE. */
#pragma once
#include <stdint.h>

#define PK_RAM_BASE         0x2000c000u
#define PK_ARENA_BASE       PK_RAM_BASE
#define PK_ARENA_SIZE       0x4000u
#define PK_ARENA(out)       ((uint8_t *)(PK_ARENA_BASE + (out) * PK_ARENA_SIZE))
#define PK_RAM_END          (PK_ARENA_BASE + 4 * PK_ARENA_SIZE)  /* stack lives above this */
