"""Validate a caller-supplied recovery plan and reserve geometries end to end."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

from env.recovery_validation import validate_recovery_plan
from env.scenario import Scenario


def unique_keys(pairs):
    result = {}
    for key,value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True,
                        help='JSON object containing exactly level, plan and reserve_paths.')
    parser.add_argument('--output',type=Path,help='Write the full report; otherwise print JSON.')
    args = parser.parse_args()
    if args.output and args.output.resolve() in {args.scenario.resolve(),args.candidate.resolve()}:
        parser.error('output must not overwrite an input')
    try:
        scenario = Scenario.from_json(args.scenario)
        request = json.loads(args.candidate.read_text(encoding='utf-8'),object_pairs_hook=unique_keys)
        if not isinstance(request,dict) or set(request) != {'level','plan','reserve_paths'}:
            raise ValueError('candidate request must contain exactly level, plan and reserve_paths')
        report = validate_recovery_plan(scenario,request['plan'],request['level'],reserve_paths=request['reserve_paths'])
    except (ValueError,OSError) as error:
        parser.error(str(error))
    encoded = json.dumps(report.to_dict(),indent=2,sort_keys=True,allow_nan=False)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(encoded,encoding='utf-8')
        print(f'{report.status}: feasible_level_upper_bound={report.feasible_level_upper_bound}; minimum_certified=false')
    else:
        print(encoded,end='')
    return 0 if report.status == 'witness' else 1


if __name__ == '__main__':
    sys.exit(main())
