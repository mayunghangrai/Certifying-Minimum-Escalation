"""Run, audit or report the P1 escalation study (see docs/ESCALATION_STUDY.md)."""
import os
from pathlib import Path
import sys

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from escalation_study.cli import main

if __name__ == '__main__':
    main()
