"""Phase A checks for method v3: the fill count over every design cell, then Gate A.

    python -P scripts/run_v3_phase_a.py --workers 14 --stages fill gate

Finished slots and missions are kept; a repeated run continues where it stopped.
See `study_v3.phase_a` for what each stage checks.
"""
import argparse
import json
import os
from pathlib import Path
import sys

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
os.chdir(ROOT)

from study_v3.phase_a import run_fill, run_gate

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=14)
    parser.add_argument('--stages', nargs='+', default=['fill', 'gate'], choices=['fill', 'gate'])
    parser.add_argument('--out', default='results/v3_phase_a')
    args = parser.parse_args()

    def log(message):
        print(message, flush=True)
    for stage in args.stages:
        summary = (run_fill if stage == 'fill' else run_gate)(Path(args.out), args.workers, log)
        log(json.dumps({k: v for k, v in summary.items() if k != 'rows'}, indent=1))
