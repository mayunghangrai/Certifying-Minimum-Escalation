"""Search a finite path representation; emit a reproducible JSON evidence report."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

from env.scenario import Scenario
from recovery.representation import PathLibrary
from recovery.search import recover


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario',type=Path,required=True)
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--exhaustive',action='store_true')
    parser.add_argument('--max-nodes',type=int,default=100000)
    parser.add_argument('--total-nodes',type=int,default=500000)
    parser.add_argument('--total-branches',type=int)
    parser.add_argument('--strategy',choices=('ascending','level4'),default='ascending')
    parser.add_argument('--max-branches',type=int,default=2000)
    parser.add_argument('--max-operations',type=int,default=10000)
    parser.add_argument('--max-rows',type=int,default=2000)
    parser.add_argument('--max-iterations',type=int,default=10000)
    parser.add_argument('--exact-only',action='store_true')
    args = parser.parse_args()
    try:
        if args.output and args.output.resolve() in {p.resolve() for p in (args.scenario,args.manifest) if p}:
            raise ValueError('output must not overwrite an input')
        scenario = Scenario.from_json(args.scenario)
        library = (PathLibrary.from_dict(scenario,json.loads(args.manifest.read_text(encoding='utf-8')))
                   if args.manifest else PathLibrary.build(scenario))
        result = recover(scenario,library,exhaustive=args.exhaustive,max_nodes=args.max_nodes,
                         total_nodes=args.total_nodes,max_branches=args.max_branches,
                         total_branches=args.total_branches,strategy=args.strategy,
                         max_operations=args.max_operations,max_rows=args.max_rows,
                         max_iterations=args.max_iterations,numerical=not args.exact_only)
        output = json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n'
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(output,encoding='utf-8')
        else:
            print(output,end='')
    except (ValueError,OSError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
