"""Keep Windows from idle-sleeping until a file exists (for long local runs).

Uses SetThreadExecutionState, a per-process request that ends when this
process exits; no power setting is changed. A closed lid or Sleep still sleeps.

    python scripts/keep_awake_until.py results/v3_phase_a_r08/gate_summary.json
"""
import ctypes
from pathlib import Path
import sys
import time

ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001

if __name__ == '__main__':
    target = Path(sys.argv[1])
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    print(f'keeping awake until {target} exists', flush=True)
    try:
        while not target.exists():
            time.sleep(60)
    finally:
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
    print('done; sleep allowed again', flush=True)
