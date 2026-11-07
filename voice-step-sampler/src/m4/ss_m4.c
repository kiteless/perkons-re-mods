/* STEP SAMPLER, M4 side: the bank's samples, what each hit plays, and the streams.
 *
 *  Bank load (replaces the stock sample load at boot and on a bank switch): for samples
 *  1-64, BANKS/NN/SAMPLES/n.wav, else SAMPLES/n.wav, else an empty slot. Strict format:
 *  PCM, mono, 16-bit, any rate. Each sample's first SS_HEAD_FRAMES go into its head, its
 *  fast-seek table is built, its cue points kept (slices). The stock sample table stays
 *  empty, so stock ALGO 3 plays its factory samples.
 *
 *  A hit (the trigger records on their way to the M7): for each triggered voice running
 *  STEP SAMPLER, what it plays from the step's sample (or the track's), ALGO, MODE and
 *  PARAM2, written into the shared control before the records go out (ss_shared.h). Its
 *  first frames come from the sample's head, or the start prepared for it; neither: it
 *  plays from the sample's beginning (a late start).
 *
 *  Main loop: each playing hit's ring refilled from the card; each output's next hit
 *  predicted (the track's next step, or the knobs) and its start prepared.
 *
 *  Choices: each track's current sample (per kit, KITS/PP.KIX record SSKT) and each step's
 *  (per pattern, PP.PAX record SSPT; 0 = the track's). */
#include <stdint.h>
#include "pk_host.h"
#include "pk_vm.h"
#include "ss_shared.h"
#include "pk_ss_engine.h"                   /* PK_SS_ENGINE: this engine's number at voice-map */

#define NKITS               64
#define NPATTERNS           64
#define TRACKS              4
#define STEPS               16
#define CLMT_ITEMS          16              /* fast-seek table: up to 7 fragments a file */
#define MAX_CUES            16
#define BOUNCE              ((uint8_t *)(uintptr_t)SYM_json_buf)
#define BOUNCE_SIZE         CONST_json_buf_size
#define CHUNK_FRAMES        ((BOUNCE_SIZE - 4u) / 2u)
#define GUARD               2u              /* the M7 reads frames t and t + 1 */
#define FIL_CLTBL           0x2c            /* FIL: the fast-seek table pointer */
#define CREATE_LINKMAP      0xffffffffu
#define CUR_KIT             FW_U16(SYM_current_kit)

/* switch values for panel positions 1, 2, 3 */
enum { POS1 = 1, POS2 = 0, POS3 = 2 };
/* MODE: forward, forward choked at the next cue, reverse */
enum { FORWARD = POS1, CHOKE = POS2, REVERSE = POS3 };

_Static_assert(BOUNCE_SIZE >= 2048, "the JSON buffer bounces reads");

typedef struct {
    uint32_t data_off;                      /* file offset of frame 0 */
    uint8_t in_bank, ncue;                  /* in BANKS/NN/SAMPLES (else SAMPLES) */
    uint16_t pad;
    uint32_t cue[MAX_CUES];                 /* slice starts, frames, ascending */
} file_t;

static file_t files[SS_SAMPLES];
static uint32_t clmt[SS_SAMPLES][CLMT_ITEMS];
static int bank_now;
static int open_sample[SS_FILES];           /* the sample each FIL has open, or -1 */
static uint32_t stream_gen[SS_OUTPUTS];     /* the hit each output's ring was set up for */
static uint8_t fired[TRACKS];               /* the sequencer's fired flags, before stock clears them */

/* choices: 0-63 the sample; step choices 0 = the track's, n = sample n - 1 */
uint8_t pk_ss_kit_sample[NKITS][TRACKS];
uint8_t pk_ss_step_sample[NPATTERNS][TRACKS][STEPS];

static inline void dmb(void)
{
    __asm volatile("dmb" ::: "memory");
}

void pk_ss_init(void)
{
    for (int i = 0; i < SS_FILES; i++)
        open_sample[i] = -1;
    SS->magic = 0;
    SS->loading = 0;
}

/* ---- files -------------------------------------------------------------------------- */

static void path(char *buf, unsigned size, int s, int in_bank)
{
    if (in_bank)
        fw_snprintf(buf, size, "BANKS/%02d/SAMPLES/%d.wav", bank_now, s + 1);
    else
        fw_snprintf(buf, size, "SAMPLES/%d.wav", s + 1);
}

static void close_fil(int i)
{
    if (open_sample[i] >= 0)
        fw_f_close(SS_FIL(i));
    open_sample[i] = -1;
}

/* FIL i on sample s (its fast-seek table attached); 0 on success */
static int use_file(int i, int s)
{
    if (open_sample[i] == s)
        return 0;
    close_fil(i);
    char p[32];
    path(p, sizeof p, s, files[s].in_bank);
    void *fil = SS_FIL(i);
    if (fw_f_open(fil, p, FW_FA_READ) != 0)
        return -1;
    if (clmt[s][0])
        FW_U32((uintptr_t)fil + FIL_CLTBL) = (uint32_t)(uintptr_t)clmt[s];
    open_sample[i] = s;
    return 0;
}

/* read `n` frames of sample s from frame `lo` into dst (any alignment), through the
 * bounce buffer: placed so the part the card's DMA reads straight into it is aligned */
static int read_frames(int i, int s, uint32_t lo, uint32_t n, int16_t *dst)
{
    if (use_file(i, s) != 0)
        return -1;
    void *fil = SS_FIL(i);
    while (n) {
        uint32_t ofs = files[s].data_off + 2u * lo;
        uint32_t k = n < CHUNK_FRAMES ? n : CHUNK_FRAMES;
        uint8_t *b = BOUNCE + (ofs & 3u);
        unsigned got;
        if (fw_f_lseek(fil, ofs) != 0 || fw_f_read(fil, b, 2u * k, &got) != 0 || got != 2u * k) {
            close_fil(i);
            return -1;
        }
        pk_copy(dst, b, 2u * k);
        dst += k;
        lo += k;
        n -= k;
    }
    return 0;
}

static void reverse(int16_t *p, uint32_t n)
{
    for (uint32_t i = 0, j = n - 1; i < j; i++, j--) {
        int16_t x = p[i];
        p[i] = p[j];
        p[j] = x;
    }
}

/* ---- bank load ------------------------------------------------------------------------ */

/* which of a folder's files are "<n>.wav", n 1-64: bit n - 1 of mask[2] */
static void listing(const char *dir, uint32_t mask[2])
{
    uint8_t *d = BOUNCE, *fno = BOUNCE + FW_DIR_MAX;
    mask[0] = mask[1] = 0;
    if (fw_f_opendir(d, dir) != 0)
        return;
    while (fw_f_readdir(d, fno) == 0 && fno[FW_FNO_NAME]) {
        const char *s = (const char *)fno + FW_FNO_NAME;
        int n = 0, i = 0;
        while (i < 2 && s[i] >= '0' && s[i] <= '9')
            n = n * 10 + (s[i++] - '0');
        if (!i || s[0] == '0' || s[i] != '.' || (s[i + 1] & ~0x20) != 'W' || (s[i + 2] & ~0x20) != 'A' ||
            (s[i + 3] & ~0x20) != 'V' || s[i + 4] || n < 1 || n > SS_SAMPLES)
            continue;
        mask[(n - 1) >> 5] |= 1u << ((n - 1) & 31);
    }
    fw_f_closedir(d);
}

static uint32_t rd32(const uint8_t *p)
{
    return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24;
}

static uint16_t rd16(const uint8_t *p)
{
    return (uint16_t)(p[0] | p[1] << 8);
}

static int small_read(void *fil, uint32_t ofs, uint8_t *buf, unsigned n)
{
    unsigned got;
    return fw_f_lseek(fil, ofs) == 0 && fw_f_read(fil, buf, n, &got) == 0 && got == n ? 0 : -1;
}

/* sample s from the file open in the prep FIL: the format, the data, the cues, the head */
static void load_one(int s)
{
    void *fil = SS_FIL(SS_PREP_FIL);
    ss_sample_t *e = &SS->sample[s];
    file_t *f = &files[s];
    clmt[s][0] = CLMT_ITEMS;                            /* the fast-seek table, before any seek */
    FW_U32((uintptr_t)fil + FIL_CLTBL) = (uint32_t)(uintptr_t)clmt[s];
    if (fw_f_lseek(fil, CREATE_LINKMAP) != 0) {
        clmt[s][0] = 0;                                 /* too fragmented: plain seeks */
        FW_U32((uintptr_t)fil + FIL_CLTBL) = 0;
    }
    uint32_t size = FW_U32((uintptr_t)fil + FW_FIL_SIZE);
    uint8_t h[24];
    if (size < 12 || small_read(fil, 0, h, 12) != 0 || rd32(h) != 0x46464952u || rd32(h + 8) != 0x45564157u)
        return;                                         /* not RIFF / WAVE */
    uint32_t pos = 12, data = 0, frames = 0, rate = 0;
    int pcm = 0;
    f->ncue = 0;
    while (pos + 8 <= size && small_read(fil, pos, h, 8) == 0) {
        uint32_t id = rd32(h), len = rd32(h + 4), body = pos + 8;
        if (id == 0x20746d66u && len >= 16 && small_read(fil, body, h, 16) == 0) {        /* "fmt " */
            uint16_t tag = rd16(h), ch = rd16(h + 2), bits = rd16(h + 14);
            rate = rd32(h + 4);
            if (tag == 0xfffeu && len >= 26 && small_read(fil, body + 24, h, 2) == 0)
                tag = rd16(h);                          /* extensible: the subformat's tag */
            pcm = tag == 1 && ch == 1 && bits == 16 && rate >= 1000 && rate <= 192000;
        } else if (id == 0x61746164u) {                                                   /* "data" */
            data = body;
            frames = (len < size - body ? len : size - body) / 2u;
        } else if (id == 0x20657563u && len >= 4 && small_read(fil, body, h, 4) == 0) {    /* "cue " */
            uint32_t n = rd32(h);
            for (uint32_t i = 0; i < n && f->ncue < MAX_CUES && 4 + 24 * (i + 1) <= len; i++) {
                if (small_read(fil, body + 4 + 24 * i + 20, h, 4) != 0)
                    break;
                f->cue[f->ncue++] = rd32(h);            /* the cue's sample offset */
            }
        }
        pos = body + len + (len & 1u);
    }
    if (!pcm || !data || frames < 2)
        return;
    /* cues: ascending, inside the sample, no duplicates */
    for (int i = 1; i < f->ncue; i++)
        for (int j = i; j > 0 && f->cue[j - 1] > f->cue[j]; j--) {
            uint32_t x = f->cue[j];
            f->cue[j] = f->cue[j - 1];
            f->cue[j - 1] = x;
        }
    int k = 0;
    for (int i = 0; i < f->ncue; i++)
        if (f->cue[i] < frames && (!k || f->cue[i] != f->cue[k - 1]))
            f->cue[k++] = f->cue[i];
    f->ncue = (uint8_t)k;
    f->data_off = data;
    uint32_t head = frames < SS_HEAD_FRAMES ? frames : SS_HEAD_FRAMES;
    open_sample[SS_PREP_FIL] = s;                      /* read_frames: this file is open */
    if (read_frames(SS_PREP_FIL, s, 0, head, SS_HEAD(s)) != 0)
        return;
    e->rate = rate;
    e->head_frames = head;
    dmb();
    e->frames = frames;
}

void pk_ss_load_samples(int bank)
{
    uint8_t m = 0;
    pk_send_m7(3, 3, &m, 1);                            /* as stock: samples changing */
    SS->loading = 1;
    SS->bank_gen++;
    dmb();
    for (int i = 0; i < SS_FILES; i++)
        close_fil(i);
    /* the stock sample table stays empty: stock ALGO 3 plays its factory samples */
    for (uint32_t a = SYM_sample_table; a < SYM_sample_data; a += 4)
        FW_U32(a) = 0;
    bank_now = bank;
    uint32_t in_bank[2], in_root[2];
    char dir[24];
    fw_snprintf(dir, sizeof dir, "BANKS/%02d/SAMPLES", bank);
    listing(dir, in_bank);
    listing("SAMPLES", in_root);
    for (int s = 0; s < SS_SAMPLES; s++) {
        SS->sample[s].frames = 0;
        int b = in_bank[s >> 5] >> (s & 31) & 1, r = in_root[s >> 5] >> (s & 31) & 1;
        if (!b && !r)
            continue;
        files[s].in_bank = (uint8_t)b;
        char p[32];
        path(p, sizeof p, s, b);
        if (fw_f_open(SS_FIL(SS_PREP_FIL), p, FW_FA_READ) != 0)
            continue;
        open_sample[SS_PREP_FIL] = -1;
        load_one(s);
        fw_f_close(SS_FIL(SS_PREP_FIL));
        open_sample[SS_PREP_FIL] = -1;
    }
    for (int o = 0; o < SS_OUTPUTS; o++) {
        SS->out[o].next_len = 0;
        stream_gen[o] = SS->out[o].gen;
    }
    SS->magic = SS_MAGIC;
    dmb();
    SS->loading = 0;
    m = 1;
    pk_send_m7(3, 3, &m, 1);                            /* as stock: samples ready */
}

/* ---- what a hit plays --------------------------------------------------------------- */

typedef struct {
    uint32_t sample, dir, rstart, rend, loop;
} plan_t;

/* slice i's start and end in sample s: its cue to the next (the last to the end), or 16
 * equal slices */
static void slice(int s, uint32_t i, uint32_t *start, uint32_t *end)
{
    uint32_t n = SS->sample[s].frames, ns = files[s].ncue;
    if (ns) {
        *start = files[s].cue[i];
        *end = i + 1 < ns ? files[s].cue[i + 1] : n;
    } else {
        *start = (uint32_t)((uint64_t)n * i / 16u);
        *end = (uint32_t)((uint64_t)n * (i + 1) / 16u);
    }
}

/* the first cut (a cue, else a 16th of the sample) after frame f of sample s, or its end */
static uint32_t next_cut(int s, uint32_t f)
{
    uint32_t n = SS->sample[s].frames, ns = files[s].ncue ? files[s].ncue : 16u;
    for (uint32_t i = 0; i < ns; i++) {
        uint32_t a, b;
        slice(s, i, &a, &b);
        if (a > f)
            return a;
    }
    return n;
}

/* the hit's stretch for sample s, ALGO / MODE (switch values), PARAM2 (0..4095). Forward
 * plays on to the sample's end, choke stops at the next cut, reverse plays the stretch
 * backwards; forward and reverse go round again while the envelope is open */
static void plan(plan_t *p, int s, int algo, int mode, uint32_t p2)
{
    uint32_t n = SS->sample[s].frames;
    p->sample = (uint32_t)s;
    p->dir = mode == REVERSE ? SS_REV : SS_FWD;
    p->loop = mode != CHOKE;
    p->rstart = 0;
    p->rend = n;
    if (algo == POS3) {                                 /* slice: the cues, else 16 equal */
        uint32_t ns = files[s].ncue ? files[s].ncue : 16u, end;
        slice(s, p2 * ns / 4096u, &p->rstart, &end);
        if (mode != FORWARD)
            p->rend = end;
        return;
    }
    if (algo == POS2)                                   /* start: PARAM2 */
        p->rstart = (uint32_t)((uint64_t)n * p2 / 4096u);
    if (p->rstart >= p->rend)
        p->rstart = p->rend ? p->rend - 1 : 0;
    if (mode == CHOKE)
        p->rend = next_cut(s, p->rstart);
}

static inline uint32_t first_frame(const plan_t *p)
{
    return p->dir == SS_REV ? p->rend - 1u : p->rstart;
}

/* tape frames of a plan the sample's head holds from the start: the hit needs nothing
 * else for those */
static uint32_t head_cover(const plan_t *p)
{
    uint32_t head = SS->sample[p->sample].head_frames, len = p->rend - p->rstart;
    if (p->dir == SS_FWD)
        return p->rstart < head ? (head - p->rstart < len ? head - p->rstart : len) : 0;
    return p->rend <= head ? len : 0;                    /* reverse: from its end, down */
}

/* the track's sample (the current kit's), and the pattern shown / playing (ss_page.c too) */
int pk_ss_track_sample(int v)
{
    int k = CUR_KIT;
    return k >= 0 && k < NKITS ? pk_ss_kit_sample[k][v] : 0;
}

int pk_ss_pattern(void)
{
    const uint8_t *seq = (const uint8_t *)(uintptr_t)FW_U32(SYM_seq_ptr);
    return fw_pattern_of((const void *)(uintptr_t)FW_U32((uintptr_t)seq + FW_SEQ_CURRENT));
}

#define track_sample pk_ss_track_sample

static int step_sample(int v, int step)
{
    int pat = pk_ss_pattern();
    int c = pat >= 0 && step >= 0 && step < STEPS ? pk_ss_step_sample[pat][v][step] : 0;
    return c ? c - 1 : track_sample(v);
}

/* the hit going out now on voice v (sequenced: its current step, else the track's sample) */
static void hit(int v, int sequenced)
{
    uint8_t *vs = fw_voice_state(v);
    int s = sequenced ? step_sample(v, (int16_t)FW_U16(vs + FW_VS_STEP)) : track_sample(v);
    int algo = FW_U16(vs + FW_VS_VALUE + 2 * FW_SLOT_ALGO), mode = FW_U16(vs + FW_VS_VALUE + 2 * FW_SLOT_MODE);
    uint32_t p2 = FW_U16(vs + FW_VS_VALUE + 2 * FW_SLOT_PARAM2) >> 4;
    ss_out_t *o = &SS->out[v];
    plan_t p;
    p.sample = p.dir = p.rstart = p.rend = p.loop = 0;  /* (= {0} would call memset) */
    uint32_t a_len = 0, src = SS_SRC_HEAD, cover;
    if (SS->sample[s].frames) {
        plan(&p, s, algo, mode, p2);
        cover = head_cover(&p);
        uint32_t len = p.rend - p.rstart;
        if (o->next_len && o->next_sample == p.sample && o->next_dir == p.dir && o->next_first == first_frame(&p) &&
            o->next_len >= (len < SS_NEXT_FRAMES ? len : SS_NEXT_FRAMES)) {
            src = SS_SRC_NEXT;                          /* prepared: this hit uses it up */
            a_len = o->next_len;
            cover = a_len;
            o->next_len = 0;
        } else if (!cover) {                            /* not loaded: a late start, from the beginning */
            p.dir = SS_FWD;
            p.rstart = 0;
            p.rend = mode == CHOKE ? next_cut(s, 0) : SS->sample[s].frames;
            cover = head_cover(&p);
        }
    } else {
        p.sample = (uint32_t)s;                         /* an empty slot: silent */
        cover = 0;
    }
    o->sample = (uint8_t)p.sample;
    o->dir = (uint8_t)p.dir;
    o->loop = (uint8_t)p.loop;
    o->src = (uint8_t)src;
    o->rstart = p.rstart;
    o->rend = p.rend;
    o->a_len = a_len;
    o->cover = cover;
    dmb();
    o->gen++;
}

/* send_triggers, from its two tail calls: the sequencer's fired flags, before it clears them */
void PK_NEXT(pk_ss_send)(void);

void pk_ss_send(void)
{
    for (int v = 0; v < TRACKS; v++)
        fired[v] = fw_voice_state(v)[FW_VS_FIRED];
    PK_NEXT(pk_ss_send)();
}

/* the trigger records going to the M7 (send_triggers' ipc_send): the hits, first */
int PK_NEXT(pk_ss_triggers)(int stream, const void *buf, int len, int type);

int pk_ss_triggers(int stream, const void *buf, int len, int type)
{
    const uint8_t *rec = buf;
    if (stream == 2 && type == 0 && len >= 4 * TRACKS && SS->magic == SS_MAGIC && !SS->loading) {
        for (int v = 0; v < TRACKS; v++)
            if (rec[4 * v] && pk_vm_engine(v) == PK_SS_ENGINE)
                hit(v, fired[v]);
    }
    for (int v = 0; v < TRACKS; v++)
        fired[v] = 0;
    return PK_NEXT(pk_ss_triggers)(stream, buf, len, type);
}

/* ---- main loop: streams and prepared starts ------------------------------------------- */

/* one refill of output o's ring, if it needs one */
static void stream(int o)
{
    ss_out_t *h = &SS->out[o];
    uint32_t gen = h->gen;
    if (gen != stream_gen[o]) {                         /* a new hit: its ring from its cover on */
        stream_gen[o] = gen;
        h->ring_gen = 0;
        dmb();
        h->ring_from = h->ring_to = h->cover;
        dmb();
        h->ring_gen = gen;
    }
    if (h->ring_gen != gen || h->rend <= h->rstart || !SS->sample[h->sample].frames)
        return;
    if (h->seen_gen == gen && !h->m7_active)
        return;                                         /* the note has ended */
    uint32_t t_read = h->seen_gen == gen ? h->t_read : 0;
    uint32_t to = h->ring_to, ahead = to > t_read ? to - t_read : 0;
    if (!h->loop && to >= h->rend - h->rstart)
        return;                                         /* choked: it doesn't go round */
    if (ahead + GUARD >= SS_RING_FRAMES)
        return;                                         /* full */
    uint32_t n = SS_RING_FRAMES - GUARD - ahead, slot = to % SS_RING_FRAMES;
    if (n > SS_RING_FRAMES - slot)
        n = SS_RING_FRAMES - slot;                      /* up to the ring's end */
    if (n > CHUNK_FRAMES)
        n = CHUNK_FRAMES;
    if (n < 256 && ahead > 1024)
        return;                                         /* small reads cost the most: wait */
    uint32_t f0 = ss_frame(h->rstart, h->rend, h->dir, to), lo;
    if (h->dir == SS_FWD) {
        if (n > h->rend - f0)
            n = h->rend - f0;                           /* up to the end of the stretch (then round) */
        lo = f0;
    } else {
        if (n > f0 - h->rstart + 1)
            n = f0 - h->rstart + 1;
        lo = f0 + 1 - n;
    }
    int16_t *dst = SS_RINGBUF(o) + slot;
    if (read_frames(o, h->sample, lo, n, dst) != 0)
        return;
    if (h->dir == SS_REV)
        reverse(dst, n);
    if (h->gen != gen || h->ring_gen != gen)
        return;                                         /* a new hit meanwhile */
    dmb();
    h->ring_to = to + n;
}

/* the next hit's plan on voice v: the track's next step if the sequencer plays, else the
 * knobs; 0 if there's nothing to prepare */
static int predict(int v, plan_t *p)
{
    uint8_t *vs = fw_voice_state(v);
    const uint8_t *seq = (const uint8_t *)(uintptr_t)FW_U32(SYM_seq_ptr);
    int algo = FW_U16(vs + FW_VS_BASE + 2 * FW_SLOT_ALGO), mode = FW_U16(vs + FW_VS_BASE + 2 * FW_SLOT_MODE);
    uint32_t p2v = FW_U16(vs + FW_VS_BASE + 2 * FW_SLOT_PARAM2);
    int s = track_sample(v);
    if (seq[FW_SEQ_PLAY] == 1) {
        const uint8_t *blk = (const uint8_t *)(uintptr_t)FW_U32((uintptr_t)vs + FW_VS_BLOCK);
        int first = blk[FW_BLK_FIRST], last = blk[FW_BLK_LAST], step = (int16_t)FW_U16(vs + FW_VS_STEP);
        int next = -1;
        for (int i = 1; i <= STEPS && next < 0; i++) {
            int k = step + i;
            while (k > last)
                k -= last - first + 1;
            if (k >= first && k <= last && blk[FW_STEP_SIZE * k] == 1)
                next = k;
        }
        if (next < 0)
            return 0;
        const uint8_t *lock = blk + FW_BLK_LOCKS + FW_LOCK_SIZE * next;
        uint16_t locked = FW_U16((uintptr_t)lock + 2 * FW_NSLOTS);
        if (locked >> FW_SLOT_PARAM2 & 1)
            p2v = FW_U16((uintptr_t)lock + 2 * FW_SLOT_PARAM2);
        if (locked >> FW_SLOT_ALGO & 1)
            algo = FW_U16((uintptr_t)lock + 2 * FW_SLOT_ALGO);
        if (locked >> FW_SLOT_MODE & 1)
            mode = FW_U16((uintptr_t)lock + 2 * FW_SLOT_MODE);
        s = step_sample(v, next);
    }
    if (!SS->sample[s].frames)
        return 0;
    plan(p, s, algo, mode, p2v >> 4);
    return !head_cover(p);                              /* the head has it already */
}

/* output o's prepared start: the predicted next hit's first frames, if they aren't */
static void prepare(int o)
{
    ss_out_t *h = &SS->out[o];
    if (h->src == SS_SRC_NEXT && h->seen_gen == h->gen && h->m7_active && h->t_read < h->a_len + GUARD)
        return;                                         /* the buffer is playing */
    if (h->src == SS_SRC_NEXT && h->seen_gen != h->gen)
        return;                                         /* a hit on its way to the M7 uses it */
    plan_t p;
    if (!predict(o, &p))
        return;
    uint32_t first = first_frame(&p);
    uint32_t len = p.rend - p.rstart, n = len < SS_NEXT_FRAMES ? len : SS_NEXT_FRAMES;
    if (h->next_len >= n && h->next_sample == p.sample && h->next_dir == p.dir && h->next_first == first)
        return;                                         /* prepared already */
    uint32_t gen = h->gen;
    h->next_len = 0;                                    /* not valid while it's written */
    dmb();
    if (h->gen != gen)
        return;                                         /* a hit took it meanwhile: it's playing */
    uint32_t lo = p.dir == SS_FWD ? first : first + 1 - n;
    int16_t *dst = SS_NEXTBUF(o);
    if (read_frames(SS_PREP_FIL, (int)p.sample, lo, n, dst) != 0)
        return;
    if (p.dir == SS_REV)
        reverse(dst, n);
    h->next_sample = p.sample;
    h->next_dir = p.dir;
    h->next_first = first;
    dmb();
    h->next_len = n;
    h->next_gen++;
}

/* the main loop, each pass (after the key poll) */
void PK_NEXT(pk_ss_poll)(void);

void pk_ss_poll(void)
{
    PK_NEXT(pk_ss_poll)();
    if (SS->magic != SS_MAGIC || SS->loading)
        return;
    for (int o = 0; o < SS_OUTPUTS; o++) {
        if (pk_vm_engine(o) != PK_SS_ENGINE)
            continue;
        stream(o);
        prepare(o);
    }
}

/* ---- choices, kept with kits and patterns (the M4 host's sidecars) ---------------------- */

uint32_t pk_ss_kit_save(int bank, int kit, uint8_t *buf, uint32_t max)
{
    (void)bank;
    if (kit < 0 || kit >= NKITS || max < TRACKS)
        return 0;
    int any = 0;
    for (int v = 0; v < TRACKS; v++)
        any |= pk_ss_kit_sample[kit][v];
    if (!any)
        return 0;                                       /* all sample 1: nothing to keep */
    pk_copy(buf, pk_ss_kit_sample[kit], TRACKS);
    return TRACKS;
}

void pk_ss_kit_restore(int bank, int kit, const uint8_t *rec, uint32_t len)
{
    (void)bank;
    if (kit < 0 || kit >= NKITS)
        return;
    for (int v = 0; v < TRACKS; v++)
        pk_ss_kit_sample[kit][v] = len == TRACKS && rec[v] < SS_SAMPLES ? rec[v] : 0;
}

uint32_t pk_ss_pat_save(int bank, int idx, uint8_t *buf, uint32_t max)
{
    (void)bank;
    if (idx < 0 || idx >= NPATTERNS || max < TRACKS * STEPS)
        return 0;
    const uint8_t *c = &pk_ss_step_sample[idx][0][0];
    int any = 0;
    for (int i = 0; i < TRACKS * STEPS; i++)
        any |= c[i];
    if (!any)
        return 0;
    pk_copy(buf, c, TRACKS * STEPS);
    return TRACKS * STEPS;
}

void pk_ss_pat_restore(int bank, int idx, const uint8_t *rec, uint32_t len)
{
    (void)bank;
    if (idx < 0 || idx >= NPATTERNS)
        return;
    uint8_t *c = &pk_ss_step_sample[idx][0][0];
    for (int i = 0; i < TRACKS * STEPS; i++)
        c[i] = len == TRACKS * STEPS && rec[i] <= SS_SAMPLES ? rec[i] : 0;
}
