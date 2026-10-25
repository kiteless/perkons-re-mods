/* fx-reverb: M4 RAM owned by the mod (D2 SRAM gap between the heap and the M7's audio
 * DMA buffer at 0x10040000). The newlib heap is capped below PK4_STATE by patching
 * _sbrk's limit. Keep in sync with lib/fxr.py (tests check this). */
#pragma once
#include <stdint.h>

#define PK4_STATE_ADDR      0x1002ff00u
#define PK4_STATE_SIZE      0x100u
#define PK4_REVERB_BUF      0x10030000u          /* 64 KB, reverb lines / looper ring */
#define PK4_REVERB_END      0x10040000u
#define PK4_PREDELAY_LEN    8192                 /* int16 samples in the BBD line (16 KB) */
