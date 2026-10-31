/* eight-lanes: shared definitions. */
#pragma once
#include <stdint.h>
#include "pk_host.h"

#define TRACKS          8
#define FIRST_LANE      4
#define NLANES          4
#define NPATTERNS       64
#define STATE           ((uint32_t)CONST_track_state)     /* 0x10c */
#define BLOCK           ((uint32_t)CONST_track_block)     /* 0x22c */
#define NOTE_REC        ((uint32_t)CONST_note_rec)        /* 0xc */

/* track state (voice_state) fields */

/* sequencer object, pattern headers */

#define U8(p)           (*(volatile uint8_t *)(p))
#define U16(p)          (*(volatile uint16_t *)(p))
#define U32(p)          (*(volatile uint32_t *)(p))
#define PTR(v)          ((uint8_t *)(uintptr_t)(v))
#define ADDR(p)         ((uint32_t)(uintptr_t)(p))

extern uint8_t pk_el_states[];

static inline uint8_t *el_seq(void)
{
    return PTR(FW_U32(SYM_seq_ptr));
}

static inline uint8_t *el_state(int t)
{
    return pk_el_states + t * STATE;
}

void el_copy(void *dst, const void *src, uint32_t n);
uint32_t el_irq_off(void);
void el_irq_restore(uint32_t primask);

/* el_patterns.c */
void el_patterns_init(void);
uint32_t el_get_varint(const uint8_t *b, uint32_t len, uint32_t *i);

/* el_kits.c */
void el_kits_clear(void);

/* a voice's 11 control slots (automation, values, kits, pots: the stock order, which is
 * not the panel's or the M7's): the engine controls are 0, 1, 4, 5 and the ALGO / MODE
 * switches 8, 9; 2, 3, 6, 7 are the analog knobs and 10 the filter switch */
#define SLOT_RANGE      8           /* top switch (ALGO): TUNE range */
#define SLOT_OCTAVE     9           /* bottom switch (MODE): octave */

/* lane automation slots kept (TUNE DECAY P1 P2 range octave) */
#define NSLOTS          6
static const uint8_t el_slot_of[NSLOTS] = {FW_SLOT_TUNE, FW_SLOT_DECAY, FW_SLOT_PARAM1, FW_SLOT_PARAM2,
                                           SLOT_RANGE, SLOT_OCTAVE};
