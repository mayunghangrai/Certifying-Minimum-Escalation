"""Run the frozen controlled protocol, or independently audit a saved run."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

from experiments.runner import run_benchmark, verify_run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--verify',action='store_true',help='audit existing outputs instead of running searches')
    args = parser.parse_args()
    try:
        result = verify_run(args.output) if args.verify else run_benchmark(ROOT,args.output)
    except (OSError,ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result,indent=2,sort_keys=True))


if __name__ == '__main__':
    main()
