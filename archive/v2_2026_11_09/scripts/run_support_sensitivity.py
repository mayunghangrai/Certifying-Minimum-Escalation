"""Support sensitivity: relabel the 53 missions of the 60 s arena third with updates of 1 to 15 cells.

docs/SUPPORT_SENSITIVITY_DESIGN_2026_10_21.md. Reads results/final_study_2026_10_17 read-only,
writes a new run directory through the final study's Store, and resumes: finished units are kept.

    python scripts/run_support_sensitivity.py --out results/support_sensitivity_2026_10_22 --workers 6
    python scripts/run_support_sensitivity.py --out results/support_sensitivity_smoke --limit 3
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
os.chdir(ROOT)

from final_study import support_sensitivity as ss     # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--config', default='configs/final_study/final.json')
    parser.add_argument('--source', default='results/final_study_2026_10_17')
    parser.add_argument('--out', required=True)
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--limit', type=int, default=None, help='first N missions only (smoke run)')
    parser.add_argument('--stages', default=','.join(ss.STAGES))
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    config['support_sensitivity'] = dict(
        design='docs/SUPPORT_SENSITIVITY_DESIGN_2026_10_21.md (decisions 1a, 2, 3)', source=args.source,
        variant=ss.VARIANT, conditions=list(ss.CONDITIONS), arena_budget_s=config['arena']['budget_short'],
        arena_arms=list(ss.ARMS), limit=args.limit)
    stages = [s.strip() for s in args.stages.split(',') if s.strip()]
    unknown = [s for s in stages if s not in ss.STAGES]
    if unknown:
        parser.error('unknown stages: '+', '.join(unknown))
    log_path = Path(args.out)/'run.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(line):
        stamped = time.strftime('%Y-%m-%d %H:%M:%S')+'  '+line
        print(stamped, flush=True)
        with log_path.open('a', encoding='utf-8') as stream:
            stream.write(stamped+'\n')
    log(f'support sensitivity: stages {stages}, {args.workers} workers, output {args.out}')
    ss.run(args.out, config, stages=stages, workers=args.workers, log=log)


if __name__ == '__main__':
    main()
