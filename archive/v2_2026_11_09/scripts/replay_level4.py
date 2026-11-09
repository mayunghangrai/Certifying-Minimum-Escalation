"""Replay Level-4 global proof records independently, without running search.

Usage: python scripts/replay_level4.py record.json [another_record.json ...]
       python scripts/replay_level4.py proof.json --scenario scenario.json
JSON arrays and JSONL streams of {scenario,result} records are also accepted.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from env.scenario import Scenario
from level4.replay import replay_tree


def _read(path):
    source = path.read_text(encoding='utf-8')
    if path.suffix.lower() == '.jsonl':
        return [json.loads(line) for line in source.splitlines() if line.strip()]
    value = json.loads(source)
    return value if isinstance(value, list) else [value]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('records', type=Path, nargs='+')
    parser.add_argument('--scenario', type=Path, help='Scenario file when input is a bare proof report')
    args = parser.parse_args()
    valid = True
    for path in args.records:
        try:
            records = _read(path)
            for record in records:
                if args.scenario:
                    scenario, report = Scenario.from_json(args.scenario), record
                else:
                    scenario, report = Scenario(record['scenario']), record['result']
                answer = replay_tree(scenario, report)
                answer.update(case_id=record.get('case_id', scenario.data['benchmark_id']), source=str(path))
                print(json.dumps(answer, sort_keys=True), flush=True)
                valid &= answer['valid']
        except (OSError, ValueError, TypeError, KeyError) as error:
            print(json.dumps(dict(valid=False, status='INVALID', covered=False,
                                  source=str(path), reason=str(error)), sort_keys=True), flush=True)
            valid = False
    return 0 if valid else 1


if __name__ == '__main__':
    raise SystemExit(main())
