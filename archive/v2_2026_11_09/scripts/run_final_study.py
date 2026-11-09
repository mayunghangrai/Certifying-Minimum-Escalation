"""Run the final study (FS, LS, equal-resource comparison, XR, scaling) and write its report.

One command runs every stage in order and can be repeated: finished work is kept and
an interrupted run continues where it stopped. See docs/FINAL_STUDY_GUIDE.md.

    python scripts/run_final_study.py --workers 6
    python scripts/run_final_study.py --workers 6 --stages report
"""
import os
from pathlib import Path
import sys

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
os.chdir(ROOT)

from final_study.cli import main

if __name__ == '__main__':
    main()
