/* STEP SAMPLER: what the M4 and the M7 share, at fixed places in the AXI SRAM that held
 * the stock custom samples (both cores address AXI SRAM alike; the card's DMA reaches it).
 *
 *   control   the sample table and, per output, the hit and its stream
 *   heads     the first SS_HEAD_FRAMES of each of the 64 samples (bank load)
 *   files     the M4's FatFs file objects: one per output (its stream), one to prepare
 *             starts and load banks (their sector buffers take the card's DMA)
 *   next      per output: a prepared start (the next hit's first frames, in playing order)
 *   ring      per output: the rest of the hit, streamed as it plays
 *
 * A hit plays a "tape": its frames in playing order (forward or reverse), round its region
 * again and again while it loops. Tape frame t is sample frame ss_frame(hit, t). The M7
 * finds frame t in the head (if the sample frame is there), else in the prepared start
 * (t < a_len, src SS_SRC_NEXT), else in the ring (ring_gen == the hit, ring_from <= t <
 * ring_to). The M4 writes the hit just before the trigger goes out (the trigger message
 * follows it), and streams the ring from its main loop.
 *
 * The card's DMA needs word-aligned buffers, so the M4 reads through the firmware's 4 KB
 * JSON buffer (AXI SRAM, free whenever the main loop runs our code), placed so the direct
 * part of each read is aligned, then copies (and for reverse, turns) the frames over. */
#pragma once
#include <stdint.h>

#define SS_SAMPLES          64
#define SS_OUTPUTS          4
#define SS_HEAD_FRAMES      2560                    /* 5 KB: ~53 ms at 48 kHz */
#define SS_NEXT_FRAMES      2560
#define SS_RING_FRAMES      5000                    /* ~10 KB: ~104 ms at 48 kHz */
#define SS_FIL_SIZE         0x240                   /* a FatFs FIL is 0x230 */
#define SS_FILES            (SS_OUTPUTS + 1)        /* + 1: preparing starts, loading banks */
#define SS_PREP_FIL         SS_OUTPUTS
#define SS_MAGIC            0x53535331u             /* 'SSS1' */

#define SS_BASE             0x24020100u             /* the stock sample data starts at 0x240200e4 */
#define SS_CTRL             SS_BASE
#define SS_CTRL_SIZE        0x520u
#define SS_HEADS            (SS_CTRL + SS_CTRL_SIZE)
#define SS_FILS             (SS_HEADS + SS_SAMPLES * SS_HEAD_FRAMES * 2u)
#define SS_NEXT             (SS_FILS + SS_FILES * SS_FIL_SIZE)
#define SS_RING             (SS_NEXT + SS_OUTPUTS * SS_NEXT_FRAMES * 2u)
#define SS_END              (SS_RING + SS_OUTPUTS * SS_RING_FRAMES * 2u)
#define SS_POOL_END         0x24080000u             /* the stock sample data ends here */

_Static_assert(SS_END <= SS_POOL_END, "STEP SAMPLER fits the stock custom-sample RAM");

enum { SS_FWD = 0, SS_REV = 1 };
enum { SS_SRC_HEAD = 0, SS_SRC_NEXT = 1 };

typedef struct {
    uint32_t frames;                /* 0: an empty slot */
    uint32_t rate;                  /* Hz: played at its own rate */
    uint32_t head_frames;           /* in its head: min(frames, SS_HEAD_FRAMES) */
    uint32_t pad;
} ss_sample_t;

/* one output: the hit (M4, at the trigger), its stream (M4 main loop), its progress (M7) */
typedef struct {
    volatile uint32_t gen;          /* M4: +1 per hit, after the fields below are written */
    uint8_t sample, dir, src, loop; /* loop: 1 goes round while the envelope is open, 0 stops (choke) */
    uint32_t rstart, rend;          /* the region: sample frames [rstart, rend) */
    uint32_t a_len;                 /* tape frames [0, a_len) in the prepared start (SS_SRC_NEXT) */
    volatile uint32_t ring_gen;     /* M4: the hit the ring holds */
    volatile uint32_t ring_from;    /* M4: tape frames [ring_from, ring_to) are in the ring, */
    volatile uint32_t ring_to;      /*     tape frame t at slot t % SS_RING_FRAMES */
    volatile uint32_t seen_gen;     /* M7: the hit it plays (0 none) */
    volatile uint32_t t_read;       /* M7: the tape frame it has reached */
    volatile uint32_t m7_active;    /* M7: 1 while the hit sounds (the M4 streams only then) */
    volatile uint32_t next_gen;     /* M4: +1 each time the prepared start changes */
    uint32_t next_sample, next_dir, next_first, next_len;   /* M4: what is prepared (len 0: nothing) */
    uint32_t cover;                 /* M4: tape frames the hit has before the ring is needed */
} ss_out_t;

typedef struct {
    volatile uint32_t magic;        /* SS_MAGIC once a bank is loaded */
    volatile uint32_t bank_gen;     /* M4: +1 per bank load (the M7 drops every hit) */
    volatile uint32_t loading;      /* M4: 1 while a bank loads */
    uint32_t pad;
    ss_sample_t sample[SS_SAMPLES];
    ss_out_t out[SS_OUTPUTS];
} ss_ctrl_t;

_Static_assert(sizeof(ss_ctrl_t) <= SS_CTRL_SIZE, "control fits");
/* the layout tests and tools mirror (lib/ss_layout.py) */
_Static_assert(sizeof(ss_sample_t) == 16 && sizeof(ss_out_t) == 68, "ss_layout.py: SAMPLE_SIZE, OUT_SIZE");
_Static_assert(__builtin_offsetof(ss_ctrl_t, out) == 16 + 16 * SS_SAMPLES, "ss_layout.py: CTRL_OUT");
_Static_assert(__builtin_offsetof(ss_out_t, cover) == 64 && __builtin_offsetof(ss_out_t, ring_to) == 28,
               "ss_layout.py: OUT_FIELDS");

#define SS            ((ss_ctrl_t *)(uintptr_t)SS_CTRL)
#define SS_HEAD(s)    ((int16_t *)(uintptr_t)(SS_HEADS + (uint32_t)(s) * SS_HEAD_FRAMES * 2u))
#define SS_NEXTBUF(o) ((int16_t *)(uintptr_t)(SS_NEXT + (uint32_t)(o) * SS_NEXT_FRAMES * 2u))
#define SS_RINGBUF(o) ((int16_t *)(uintptr_t)(SS_RING + (uint32_t)(o) * SS_RING_FRAMES * 2u))
#define SS_FIL(i)     ((void *)(uintptr_t)(SS_FILS + (uint32_t)(i) * SS_FIL_SIZE))

/* the sample frame tape frame t of a hit plays (looping round its region) */
static inline uint32_t ss_frame(uint32_t rstart, uint32_t rend, uint32_t dir, uint32_t t)
{
    uint32_t len = rend - rstart, i = len ? t % len : 0;
    return dir == SS_REV ? rend - 1u - i : rstart + i;
}
