"""Command line of the final study."""
import argparse
import json
from pathlib import Path
import time

from .stages import STAGES, run


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run the final study and write its report.')
    parser.add_argument('--config', default='configs/final_study/final.json')
    parser.add_argument('--out', default='results/final_study')
    parser.add_argument('--workers', type=int, default=6,
                        help='worker processes (the comparison protocol fixes six)')
    parser.add_argument('--stages', default=','.join(STAGES),
                        help='comma-separated subset of: '+', '.join(STAGES))
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    stages = [s.strip() for s in args.stages.split(',') if s.strip()]
    unknown = [s for s in stages if s not in STAGES]
    if unknown:
        parser.error('unknown stages: '+', '.join(unknown))
    log_path = Path(args.out)/'run.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(line):
        stamped = time.strftime('%Y-%m-%d %H:%M:%S')+'  '+line
        print(stamped, flush=True)
        with log_path.open('a', encoding='utf-8') as stream:
            stream.write(stamped+'\n')
    log(f'final study: {len(stages)} stages, {args.workers} workers, output {args.out}')
    run(args.out, config, stages=stages, workers=args.workers, log=log)
    report = Path(args.out)/'analysis'/'REPORT.md'
    if report.exists():
        log(f'done. Open {report}')
