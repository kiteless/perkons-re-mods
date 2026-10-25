"""fx-reverb constants shared by the patch module and tests (keep in sync with src/m4/pk4_ram.h)."""
PK4_STATE_ADDR = 0x1002ff00
PK4_REVERB_BUF = 0x10030000
OFF_CFG_REVERB = 4          # pk4_state_t.cfg_reverb
OFF_CFG_FREEZE = 5          # pk4_state_t.cfg_freeze
OFF_SWITCH_LEVEL = 6
OFF_ACTIVE_REVERB = 7
OFF_FROZEN = 12
OFF_LOOP_LEN = 24
JSON_KEY_REVERB = 'fx-reverb'
JSON_KEY_FREEZE = 'fx-switch-freeze'
KEY_FX_TYPE, KEY_SWITCH_MODE = 46, 47
