"""Run or audit the six frozen Level-4 global escalation targets."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from level4.targets import audit_run, run_targets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT/'results/level3_certified_2026_10_05/v1')
    parser.add_argument('--output', type=Path, default=ROOT/'results/level4_certified_2026_10_05/v1_completion_bounds')
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--nodes', type=int, default=100000)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if args.verify:
        print(audit_run(args.output))
    else:
        run_targets(args.input, args.output, budget=dict(max_seconds=args.seconds, max_nodes=args.nodes,
            refinements=[2, 4], digits=18, max_operations=100000, max_rows=10000))


if __name__ == '__main__':
    main()
