/* eight-lanes: lanes 5-8 of all 64 patterns, following stock semantics.
 *
 * Stock keeps the bank's 64 patterns in RAM as their saved versions; the playing pattern
 * is edited in place and a snapshot restores it when you switch away (unsaved edits are
 * discarded), saving refreshes the snapshot and writes BANKS/NN/PP.PAT.
 *
 * Lanes: the store holds the saved lanes of all 64 patterns, compact (TUNE, DECAY, P1,
 * P2 and the two switches of each step's automation; the audio-only slots are never used
 * on a lane). A pattern that is queued gets an 8-track working block: its 4 stock tracks
 * plus its lanes expanded, and its header points there, so the stock core plays all 8
 * and every stock edit, copy and save path sees tracks 1-4 where they expect them. When
 * the pattern is left, its header goes back to its own block before the stock revert
 * (the revert then restores the stock tracks there) and the lane edits are dropped, as
 * stock drops track edits. Save packs the lanes into the store, which goes in the host's
 * pattern sidecar (PP.PAX, record "EL8P"); bank load reads it back.
 *
 * In the store a step is one word (lane_pk_t): every value the stock code writes fits
 * (state 0-3, fire flag 10 or 0, the SHUFFLE offset 0-99, ratchet 0-4, condition 0-12,
 * note and velocity 0-127). The sidecar keeps the full 8-byte steps (lane_rec_t), so
 * the files are those of earlier builds. */
#include "el.h"

#define NWORK           3           /* current, queued, and one still draining */



typedef struct {
    uint16_t value[NSLOTS];
    uint8_t locked, glide;          /* bit i = el_slot_of[i] */
} lane_lock_t;

#define NSET            (FW_BLK_LOCKS - FW_STEPS * 8)  /* +0x80: length, speed, play mode, ... */

typedef struct {                    /* a lane in the sidecar file (EL8P) */
    uint8_t steps[FW_STEPS * 8];
    uint8_t settings[NSET];
    lane_lock_t lock[FW_STEPS];
} lane_rec_t;                       /* 364 B */

typedef struct {                    /* a lane in the store */
    uint32_t steps[FW_STEPS];       /* pack_step() */
    uint8_t settings[NSET];
    lane_lock_t lock[FW_STEPS];
} lane_pk_t;                        /* 300 B */

_Static_assert(sizeof(lane_rec_t) == 364, "lane record");
_Static_assert(sizeof(lane_pk_t) == 300, "packed lane");

PK_AXI static lane_pk_t store[NPATTERNS][NLANES];
PK_AXI static lane_pk_t empty_lane;
PK_AXI static uint8_t work[NWORK][TRACKS * 0x22c] __attribute__((aligned(4)));
PK_AXI static int8_t work_owner[NWORK];      /* pattern index, or -1 */

/* ---- pack / unpack ----------------------------------------------------------------- */

static uint32_t clip(uint32_t v, uint32_t max)
{
    return v < max ? v : max;
}

/* a step record (8 B) as one word: state 2 bits, fire flag 1 (+1 nonzero: the sequencer
 * only tests it), SHUFFLE offset 7 (+2, int16), ratchet 3, condition 4, note 7,
 * velocity 7. Values the stock code never writes are clipped. */
static uint32_t pack_step(const uint8_t *s)
{
    return clip(s[0], 3) | (uint32_t)(s[1] != 0) << 2 | clip((uint32_t)(s[2] | s[3] << 8), 127) << 3
           | clip(s[4], 7) << 10 | clip(s[5], 15) << 13 | (uint32_t)(s[6] & 0x7f) << 17
           | (uint32_t)(s[7] & 0x7f) << 24;
}

static void unpack_step(uint8_t *s, uint32_t w)
{
    s[0] = (uint8_t)(w & 3);
    s[1] = w >> 2 & 1 ? 10 : 0;
    s[2] = (uint8_t)(w >> 3 & 0x7f);
    s[3] = 0;
    s[4] = (uint8_t)(w >> 10 & 7);
    s[5] = (uint8_t)(w >> 13 & 15);
    s[6] = (uint8_t)(w >> 17 & 0x7f);
    s[7] = (uint8_t)(w >> 24 & 0x7f);
}

static void pack_steps(uint32_t *w, const uint8_t *steps)
{
    for (int k = 0; k < FW_STEPS; k++)
        w[k] = pack_step(steps + 8 * k);
}

static void unpack_steps(uint8_t *steps, const uint32_t *w)
{
    for (int k = 0; k < FW_STEPS; k++)
        unpack_step(steps + 8 * k, w[k]);
}

static void pack(lane_pk_t *r, const uint8_t *block)
{
    pack_steps(r->steps, block);
    pk_copy(r->settings, block + FW_STEPS * 8, NSET);
    for (int k = 0; k < FW_STEPS; k++) {
        const uint8_t *src = block + FW_BLK_LOCKS + k * FW_LOCK_SIZE;
        uint16_t locked = FW_U16(src + 0x16), glide = FW_U16(src + 0x18);
        lane_lock_t *d = &r->lock[k];
        d->locked = d->glide = 0;
        for (int i = 0; i < NSLOTS; i++) {
            d->value[i] = FW_U16(src + 2 * el_slot_of[i]);
            if (locked >> el_slot_of[i] & 1)
                d->locked |= (uint8_t)(1 << i);
            if (glide >> el_slot_of[i] & 1)
                d->glide |= (uint8_t)(1 << i);
        }
    }
}

static void unpack(uint8_t *block, const lane_pk_t *r)
{
    pk_copy(block, PTR(SYM_track_template), BLOCK);
    unpack_steps(block, r->steps);
    pk_copy(block + FW_STEPS * 8, r->settings, NSET);
    for (int k = 0; k < FW_STEPS; k++) {
        uint8_t *d = block + FW_BLK_LOCKS + k * FW_LOCK_SIZE;
        const lane_lock_t *s = &r->lock[k];
        uint16_t locked = 0, glide = 0;
        for (int i = 0; i < NSLOTS; i++) {
            FW_U16(d + 2 * el_slot_of[i]) = s->value[i];
            if (s->locked >> i & 1)
                locked |= (uint16_t)(1 << el_slot_of[i]);
            if (s->glide >> i & 1)
                glide |= (uint16_t)(1 << el_slot_of[i]);
        }
        FW_U16(d + 0x16) = locked;
        FW_U16(d + 0x18) = glide;
    }
}

/* the sidecar's form of a lane, and back */
static void to_rec(lane_rec_t *d, const lane_pk_t *r)
{
    unpack_steps(d->steps, r->steps);
    pk_copy(d->settings, r->settings, NSET + sizeof d->lock);
}

static void from_rec(lane_pk_t *d, const lane_rec_t *r)
{
    pack_steps(d->steps, r->steps);
    pk_copy(d->settings, r->settings, NSET + sizeof d->lock);
}

/* ---- patterns and working blocks --------------------------------------------------- */

static uint8_t *header(int p)
{
    return PTR(SYM_pat_headers + p * FW_HDR_SIZE);
}

static uint8_t *stock_block(int p)
{
    return PTR(SYM_pat_blocks + p * 4 * BLOCK);
}

static int work_of(const uint8_t *block)
{
    for (int w = 0; w < NWORK; w++)
        if (block == work[w])
            return w;
    return -1;
}

static int work_in_use(int w)
{
    const uint8_t *s = el_seq();
    uint32_t lo = ADDR(work[w]), hi = lo + TRACKS * BLOCK;
    for (int t = 0; t < TRACKS; t++) {
        uint32_t b = FW_U32(el_state(t) + FW_VS_BLOCK), n = FW_U32(el_state(t) + FW_VS_PENDING);
        if ((b >= lo && b < hi) || (n >= lo && n < hi))
            return 1;
    }
    for (int i = FW_SEQ_CURRENT; i <= FW_SEQ_QUEUED; i += 4) {
        const uint8_t *h = PTR(FW_U32(s + i));
        if (h && PTR(FW_U32(h + FW_HDR_BLOCK)) == work[w])
            return 1;
    }
    return 0;
}

/* give a working block back: its owner's header to its own block (tracks 1-4 copied
 * back if the header still pointed here, e.g. queued and then replaced unplayed) */
static void release(int w)
{
    int p = work_owner[w];
    if (p >= 0 && PTR(FW_U32(header(p) + FW_HDR_BLOCK)) == work[w]) {
        pk_copy(stock_block(p), work[w], 4 * BLOCK);
        FW_U32(header(p) + FW_HDR_BLOCK) = ADDR(stock_block(p));
    }
    work_owner[w] = -1;
}

static void expand(int p, int w)
{
    pk_copy(work[w], PTR(FW_U32(header(p) + FW_HDR_BLOCK)), 4 * BLOCK);
    for (int l = 0; l < NLANES; l++)
        unpack(work[w] + (FIRST_LANE + l) * BLOCK, &store[p][l]);
    FW_U32(header(p) + FW_HDR_BLOCK) = ADDR(work[w]);
    work_owner[w] = (int8_t)p;
}

/* make sure pattern p plays from an 8-track working block */
static void attach(int p)
{
    if (p < 0 || work_of(PTR(FW_U32(header(p) + FW_HDR_BLOCK))) >= 0)
        return;
    for (int w = 0; w < NWORK; w++) {
        if (work_owner[w] < 0 || !work_in_use(w)) {
            release(w);
            expand(p, w);
            return;
        }
    }
    /* none free (cannot happen with three): the pattern plays its tracks 1-4 only */
}

/* detach every working block (bank reload): headers back to their own blocks */
static void detach_all(void)
{
    for (int w = 0; w < NWORK; w++)
        release(w);
}

void el_patterns_init(void)
{
    pack(&empty_lane, PTR(SYM_track_template));
    for (int p = 0; p < NPATTERNS; p++)
        for (int l = 0; l < NLANES; l++)
            pk_copy(&store[p][l], &empty_lane, sizeof(lane_pk_t));
    for (int w = 0; w < NWORK; w++)
        work_owner[w] = -1;
    uint8_t *s = el_seq();
    int p = fw_pattern_of(PTR(FW_U32(s + FW_SEQ_CURRENT)));
    attach(p);
    for (int t = 0; t < TRACKS; t++) {
        uint8_t *b = PTR(FW_U32(header(p) + FW_HDR_BLOCK)) + t * BLOCK;
        FW_U32(el_state(t) + FW_VS_BLOCK) = ADDR(b);
        FW_U32(el_state(t) + FW_VS_LOCKS) = ADDR(b + FW_BLK_LOCKS);
    }
}

/* replaces the stock queue (seq+0xc = header) */
void pk_el_queue(uint8_t *hdr)
{
    uint32_t pm = pk_irq_off();
    attach(fw_pattern_of(hdr));
    FW_U32(el_seq() + FW_SEQ_QUEUED) = ADDR(hdr);
    pk_irq_restore(pm);
}

/* main loop: the stock revert/snapshot after a pattern switch */
void PK_NEXT(pk_el_switch_done)(void);

void pk_el_switch_done(void)
{
    uint8_t *rec = PTR(SYM_switch_record);      /* {old, new, ?, ?, flag} */
    if (rec[0x10]) {
        uint8_t *old = PTR(FW_U32(rec)), *new = PTR(FW_U32(rec + 4));
        int p = fw_pattern_of(old);
        int w = p >= 0 ? work_of(PTR(FW_U32(old + FW_HDR_BLOCK))) : -1;
        if (w >= 0 && old != new) {
            /* the stock revert restores tracks 1-4 into the pattern's own block; the lane
             * edits are dropped (the store keeps the saved lanes) */
            FW_U32(old + FW_HDR_BLOCK) = ADDR(stock_block(p));
            work_owner[w] = -1;     /* free once no track plays from it any more */
        }
    }
    PK_NEXT(pk_el_switch_done)();
}

/* ---- stock pattern operations, extended to the lanes ------------------------------- */

/* pattern save: src's 4 tracks to pattern idx (file + RAM); lanes alike */
int PK_NEXT(pk_el_save)(uint8_t *hdr, int bank, int idx);

int pk_el_save(uint8_t *src, int bank, int idx)
{
    int r = PK_NEXT(pk_el_save)(src, bank, idx);
    if (idx < 0 || idx >= NPATTERNS)
        return r;
    const uint8_t *blk = PTR(FW_U32(src + FW_HDR_BLOCK));
    int sp = fw_pattern_of(src);
    for (int l = 0; l < NLANES; l++) {
        if (work_of(blk) >= 0)                  /* the pattern being played/edited */
            pack(&store[idx][l], blk + (FIRST_LANE + l) * BLOCK);
        else if (sp >= 0 && sp != idx)          /* not expanded: its saved lanes */
            pk_copy(&store[idx][l], &store[sp][l], sizeof(lane_pk_t));
    }
    (void)bank;
    /* save to another slot queues idx (stock): attached then with the lanes just stored */
    return r;
}

/* pattern clear: deletes PP.PAT and clears the pattern; lanes alike */
void PK_NEXT(pk_el_clear)(int bank, int idx);

void pk_el_clear(int bank, int idx)
{
    PK_NEXT(pk_el_clear)(bank, idx);
    (void)bank;
    if (idx < 0 || idx >= NPATTERNS)
        return;
    for (int l = 0; l < NLANES; l++)
        pk_copy(&store[idx][l], &empty_lane, sizeof(lane_pk_t));
    uint8_t *blk = PTR(FW_U32(header(idx) + FW_HDR_BLOCK));
    if (work_of(blk) >= 0)
        for (int l = 0; l < NLANES; l++)
            unpack(blk + (FIRST_LANE + l) * BLOCK, &empty_lane);
}

/* bank load (bank_prepare): every PP.PAT into RAM; the lanes come after, from the host's
 * sidecar records (pk_el_pat_load) */
void PK_NEXT(pk_el_bank_prepare)(int bank);

void pk_el_bank_prepare(int bank)
{
    uint32_t pm = pk_irq_off();
    detach_all();
    pk_irq_restore(pm);
    PK_NEXT(pk_el_bank_prepare)(bank);
    el_kits_clear();
}

/* the host's pattern sidecar (PP.PAX, record "EL8P"): the 4 lane records of a pattern */
uint32_t pk_el_pat_save(int bank, int idx, uint8_t *buf, uint32_t max)
{
    (void)bank;
    const uint8_t *e = (const uint8_t *)&empty_lane, *r = (const uint8_t *)store[idx];
    uint32_t n = NLANES * sizeof(lane_rec_t);
    int used = 0;
    for (uint32_t i = 0; i < sizeof store[idx] && !used; i++)
        used = r[i] != e[i % sizeof(lane_pk_t)];
    if (!used || n > max)
        return 0;                               /* empty lanes: no record */
    for (int l = 0; l < NLANES; l++)
        to_rec((lane_rec_t *)buf + l, &store[idx][l]);
    return n;
}

void pk_el_pat_load(int bank, int idx, const uint8_t *rec, uint32_t len)
{
    (void)bank;
    for (int l = 0; l < NLANES; l++) {
        if (len == NLANES * sizeof(lane_rec_t))
            from_rec(&store[idx][l], (const lane_rec_t *)rec + l);
        else
            pk_copy(&store[idx][l], &empty_lane, sizeof(lane_pk_t));
    }
}
