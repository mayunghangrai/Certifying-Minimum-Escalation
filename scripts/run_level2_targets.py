"""Run or independently audit only the thirteen frozen Level-2 targets."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

from level2.targets import audit_run, run_targets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT/'results/continuous_paths_2026_10_05/primary')
    parser.add_argument('--output', type=Path, default=ROOT/'results/level2_exhaustive_2026_10_05/v1')
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--nodes', type=int, default=100000)
    args = parser.parse_args()
    if args.verify:
        print(audit_run(args.output))
    else:
        run_targets(args.input, args.output, budget=dict(max_seconds=args.seconds, max_nodes=args.nodes,
                    refinements=[2, 4], digits=18, max_operations=100000, max_rows=10000))


if __name__ == '__main__':
    main()
