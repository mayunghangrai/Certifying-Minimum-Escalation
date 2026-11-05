"""Reproduce paired simulations, wind dependency graphs and automatic scopes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

from env.intervention_scope import release_sets
from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update


def run_cases(paths):
    cases = []
    for path in paths:
        scenario = Scenario.from_json(path)
        diagnostic = diagnose_wind_update(scenario)
        previous, received = diagnostic.previous, diagnostic.received
        seeds = diagnostic.affected_tasks
        releases = [release_sets(scenario, k, seeds) for k in range(5)]
        assert all(all(lo[a] <= hi[a] for a in lo) for lo,hi in zip(releases,releases[1:]))
        cases.append({
            'benchmark_id': scenario.data['benchmark_id'],
            'fixture_file_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'scenario_content_sha256': scenario.content_hash(),
            'previous': previous.to_dict(),
            'received': received.to_dict(),
            'diagnostic': diagnostic.to_dict(),
            'intervention_spaces': {
                'purpose': 'Permissions derived from wind diagnosis and constraint closure; no minimum-level claim.',
                'affected_tasks': sorted(seeds),
                'neighborhood': sorted(diagnostic.neighborhood),
                'release_counts': [{a:len(keys) for a,keys in release.items()} for release in releases],
            },
        })
    return {
        'formulation_date': '2026-09-17',
        'sources': json.loads((ROOT/'docs/formulation/2026-09-17/sources.json').read_text(encoding='utf-8')),
        'cases': cases,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', type=Path, action='append', help='Additional path supplied instead of the three canonical cases; repeat for multiple cases.')
    parser.add_argument('--output', type=Path, help='Write full deterministic JSON traces.')
    args = parser.parse_args()
    paths = args.scenario or sorted((ROOT/'scenarios/benchmark').glob('*.json'))
    result = run_cases(paths)
    if args.output:
        if args.output.resolve() in {p.resolve() for p in paths}:
            parser.error('output must not overwrite an input fixture')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+'\n', encoding='utf-8')
    for case in result['cases']:
        before, after = case['previous'], case['received']
        print(f"{case['benchmark_id']}: previous={before['status']}, received={after['status']}, complete={str(after['complete']).lower()}")


if __name__ == '__main__':
    main()
