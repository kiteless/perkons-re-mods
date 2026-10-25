"""Swap which engine object outputs 1 and 2 use (pointer swap only).

In wire_voices() (0x080241d8) the slots[] array at voice_engine+0x28 is filled with
  str r5, [r3, #0x28]   @ 0x0802421a   slots[0] = &cFirstSlot
  str r4, [r3, #0x2c]   @ 0x0802429c   slots[1] = &cSecondSlot
Swapping the two store offsets makes output 1 run the voice-2 engine and vice versa.
Param pointers are NOT retargeted, so each engine still follows its *original*
voice's knobs: voice-1's trigger, algo/mode switches and output, but voice-2's knobs.
No new code, no new RAM. It's an audible but harmless smoke test that a modified
M7 image runs.
"""
from perkons.patch import thumb_str_imm

TARGET = 'v1.3.0'
SUMMARY = 'Output 1 <-> output 2 engine swap (2 instruction edits in wire_voices)'
RISK = 'low'


def apply(p):
    p.write('m7', 0x0802421a, thumb_str_imm(5, 3, 0x2c), thumb_str_imm(5, 3, 0x28), 'slots[1] = &cFirstSlot')
    p.write('m7', 0x0802429c, thumb_str_imm(4, 3, 0x28), thumb_str_imm(4, 3, 0x2c), 'slots[0] = &cSecondSlot')
