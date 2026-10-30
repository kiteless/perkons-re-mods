"""Experimental 8-lane setup on top of SeqHarness."""
from seq_harness import SeqHarness

AXI = 0x24004000
STATES, BLOCKS = AXI, AXI + 8 * 0x10c
NOTES = BLOCKS + 8 * 0x22c          # 8 x 0xc: per-track note/velocity records (stock 4 at 0x1000011c)
NOTES_STOCK = 0x1000011c
NOTES_LITERALS = (0x081019e4, 0x08101cfc, 0x08102154)   # every reference to the stock array


def eight_lanes(h: SeqHarness):
    """Track states and the current pattern's working block in AXI, track count 8."""
    e = h.e
    old_states = e.r32(h.seq + 4)
    hdr = e.r32(h.seq + 8)
    old_blk = e.r32(hdr + 0x18)
    e.uc.mem_write(STATES, bytes(e.uc.mem_read(old_states, 4 * 0x10c)) + bytes(4 * 0x10c))
    e.uc.mem_write(BLOCKS, bytes(e.uc.mem_read(old_blk, 4 * 0x22c)) * 2)
    for t in range(8):
        vs = STATES + t * 0x10c
        if t >= 4:
            e.uc.mem_write(vs, bytes(e.uc.mem_read(STATES + 3 * 0x10c, 0x10c)))
            e.w8(vs, t)
        e.w32(vs + 4, BLOCKS + t * 0x22c)
        e.w32(vs + 0x4c, BLOCKS + t * 0x22c + 0x8c)
    e.w32(h.seq + 4, STATES)
    e.w32(hdr + 0x18, BLOCKS)
    e.w8(hdr + 0x17, 8)
    e.w8(h.seq + 3, 8)
    stock = bytes(e.uc.mem_read(NOTES_STOCK, 4 * 0xc))
    e.uc.mem_write(NOTES, stock + stock)
    for lit in NOTES_LITERALS:
        assert e.r32(lit) == NOTES_STOCK
        e.w32(lit, NOTES)
    return h


def lane_fired(h, lane):
    """The core's 'fired this tick' flag for a lane (send_triggers clears tracks 1-4 only)."""
    vs = STATES + lane * 0x10c
    f = h.e.r8(vs + 0x31)
    h.e.w8(vs + 0x31, 0)
    return f


def lane_note(h, lane):
    """(note, velocity) the core prepared for the lane's step: velocity as send_triggers,
    the step velocity scaled by the groove byte (+3, 0x7f = none)."""
    r = NOTES + lane * 0xc
    groove, vel = h.e.r8(r + 3), h.e.r8(r + 5)
    return h.e.r8(r + 4), (groove * vel + vel) >> 7
