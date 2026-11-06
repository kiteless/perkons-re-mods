"""Test helpers: the engine map as the M4 sends it, on the emulated M7."""
MSG_VOICE_MAP = 4           # the M7 host's type for "voice-map" when it's the only message
                            # (types go in name order: pass msg= from m7host.message_types)
REC = 0x2001d000            # scratch trigger record in M7 RAM the firmware doesn't use


def send_map(e, m, msg=MSG_VOICE_MAP):
    """The map message on the trigger stream, taken by the next audio callback: each output
    whose engine changes then switches at its next note."""
    e.send(2, msg, bytes(m))
    e.audio(32)


def remap(e, m, cave, msg=MSG_VOICE_MAP):
    """send_map, then each output switches as at a note (without playing one)."""
    send_map(e, m, msg)
    e.uc.mem_write(REC, bytes([0, 1, 0, 0, 0]))         # +1: trigger flag
    for o in range(4):
        e.call(cave['pk_vm_before_note'], e.slot(o), REC)
