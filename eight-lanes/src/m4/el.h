/* eight-lanes: shared definitions. See ../../docs/design.md. */
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
#define STEPS           16
#define LOCKS_OFF       0x8c                              /* lock records in a block */
#define LOCK_REC        0x1a

/* track state (voice_state) fields */
#define VS_INDEX        0x00
#define VS_BLOCK        0x04
#define VS_PENDING      0x08        /* block to move to at the track's loop end */
#define VS_STEP         0x1c
#define VS_FIRED        0x31
#define VS_LOCKS        0x4c
#define VS_VALUE        0x50
#define VS_MUTE         0x108

/* sequencer object, pattern headers */
#define SEQ_PLAY        0x00
#define SEQ_COUNT       0x03
#define SEQ_STATES      0x04
#define SEQ_CURRENT     0x08
#define SEQ_QUEUED      0x0c
#define HDR_SIZE        0x20
#define HDR_REPEATS     0x14
#define HDR_BLOCK       0x18

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
uint32_t el_put_varint(uint8_t *b, uint32_t n, uint32_t v);
uint32_t el_get_varint(const uint8_t *b, uint32_t len, uint32_t *i);

/* el_kits.c */
void el_kits_load_bank(int bank);

/* a voice's 11 control slots (automation, values, kits, pots: the stock order, which is
 * not the panel's or the M7's): the engine controls are 0, 1, 4, 5 and the ALGO / MODE
 * switches 8, 9; 2, 3, 6, 7 are the analog knobs and 10 the filter switch */
#define SLOT_TUNE       0
#define SLOT_PARAM1     1
#define SLOT_DECAY      4
#define SLOT_PARAM2     5
#define SLOT_RANGE      8           /* top switch (ALGO): TUNE range */
#define SLOT_OCTAVE     9           /* bottom switch (MODE): octave */

/* lane automation slots kept (TUNE DECAY P1 P2 range octave) */
#define NSLOTS          6
static const uint8_t el_slot_of[NSLOTS] = {SLOT_TUNE, SLOT_DECAY, SLOT_PARAM1, SLOT_PARAM2,
                                           SLOT_RANGE, SLOT_OCTAVE};
