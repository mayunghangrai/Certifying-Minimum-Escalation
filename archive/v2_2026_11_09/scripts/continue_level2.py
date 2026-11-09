"""Continue the two frozen capped Level-2 cases with bounded route proposals."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from env.scenario import Scenario
from final_benchmark.records import atomic_json, publish_archive, verify_archive, record_hash
from recovery.local_search import digest
from level2.proposals import propose_routes
from level2.search import search_level2
from level2.targets import _audit, combine_bounds, source_files
from level2.replay import replay_tree

CASES = ('CB_24_6_uniform_61002_below', 'CB_24_6_clustered_61002_below')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(output, prior_root):
    manifest = json.loads((output/'manifest.json').read_text())
    verify_archive(output/'source.zip', manifest['source_files'])
    for name in CASES:
        path = prior_root/'records'/f'{name}.json'
        assert sha(path) == manifest['inputs'][name], 'prior input changed'
        prior = json.loads(path.read_text())
        _audit(prior)
        record = json.loads((output/'records'/f'{name}.json').read_text())
        assert record['run_hash'] == manifest['run_hash']
        assert record['input_hash'] == sha(path)
        assert record['baseline'] == prior['baseline']
        assert record['scenario'] == prior['scenario']
        result = _audit(record)
        print(name, record['full_domain'], result, flush=True)
    for path, expected in manifest['preserved_files'].items():
        assert sha(ROOT/path) == expected, 'frozen evidence changed: '+path
    print('Source archive, both complete records, prior evidence and frozen file hashes verified.', flush=True)


def run(output, prior_root, seconds):
    if (output/'manifest.json').exists():
        raise ValueError('output already exists; audit it or choose a fresh directory')
    output.mkdir(parents=True, exist_ok=True)
    inputs = {name: sha(prior_root/'records'/f'{name}.json') for name in CASES}
    preserved = {}
    for directory in ('continuous_paths_2026_10_05', 'level2_exhaustive_2026_10_05',
                      'level3_certified_2026_10_05', 'level4_certified_2026_10_05'):
        for path in (ROOT/'results'/directory).rglob('*'):
            if path.is_file():
                preserved[path.relative_to(ROOT).as_posix()] = sha(path)
    files = source_files()
    files['scripts/continue_level2.py'] = sha(Path(__file__))
    budget = dict(max_seconds=seconds, max_nodes=100000, refinements=[2, 4], digits=18,
                  max_operations=100000, max_rows=10000)
    binding = dict(inputs=inputs, source_hash=digest(files), budget=budget,
                   proposal_budget=dict(max_seconds=seconds, max_candidates=1000))
    run_hash = digest(binding)
    publish_archive(output/'source.zip', files)
    atomic_json(output/'manifest.json', dict(version='level2_continuation_run_v1', run_hash=run_hash,
                **binding, source_files=files, preserved_files=preserved,
                timing='Proposal, search, and replay separately measured; soft caps checked between operations.'))
    summary = []
    for name in CASES:
        prior = json.loads((prior_root/'records'/f'{name}.json').read_text())
        _audit(prior)
        scenario = Scenario(prior['scenario'])
        seeds = prior['result']['leg_bounds']
        proposal = propose_routes(scenario, initial_bounds=seeds, **binding['proposal_budget'])
        start = perf_counter()
        result = search_level2(scenario, initial_bounds=seeds, preferred_prefix=proposal['prefix'], **budget)
        solve_s = perf_counter()-start
        start = perf_counter()
        replay = replay_tree(scenario, result)
        replay_s = perf_counter()-start
        if not replay['valid']:
            raise ValueError('new proof failed replay: '+str(replay))
        record = dict(version='level2_target_record_v1', run_hash=run_hash, case_id=name,
            input_hash=inputs[name], stage=prior['stage'], baseline=prior['baseline'],
            scenario=prior['scenario'], result=result, replay=replay, proposal=proposal,
            full_domain=combine_bounds(prior['baseline']['result']['full_domain'], result),
            timing=dict(proposal_s=proposal['elapsed_s'], solve_s=solve_s, replay_s=replay_s))
        record['record_hash'] = record_hash(record)
        _audit(record)
        atomic_json(output/'records'/f'{name}.json', record)
        summary.append(dict(case_id=name, conclusion=record['full_domain'], timing=record['timing'],
                            nodes=len(result['nodes']), effort=result['effort'], proposal_attempts=proposal['attempts']))
        print(name, record['full_domain'], record['timing'], flush=True)
    atomic_json(output/'summary.json', summary)
    audit(output, prior_root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior', type=Path, default=ROOT/'results/level2_exhaustive_2026_10_05/v1')
    parser.add_argument('--output', type=Path, default=ROOT/'results/level2_continuation_2026_10_06/v1')
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if args.verify:
        audit(args.output, args.prior)
    else:
        run(args.output, args.prior, args.seconds)


if __name__ == '__main__':
    main()
