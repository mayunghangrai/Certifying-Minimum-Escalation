"""Entry point for the versioned final benchmark, restricted to one process."""
import os
from pathlib import Path
import sys

for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from final_benchmark.cli import main

if __name__=='__main__': main()
