/* voice-map's M4 interface for engine mods (add voice-map's src/m4 to the include path) */
#pragma once

/* the engine voice v (0-3) runs now: 0-3 the stock engines, 4- the extra engines (their
 * slot - 1, as the engine page's column - 1), or -1 */
int pk_vm_engine(int v);
