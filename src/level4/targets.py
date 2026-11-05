"""Immutable global escalation on exactly six frozen Level-3 exclusions."""
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
from time import perf_counter

from env.scenario import Scenario
from final_benchmark.records import (ROOT, atomic_json, publish_archive, verify_archive, record_hash)
from level3.targets import (_audit as audit_level3, source_files as level3_sources,
                            PRIOR_ROOTS as EARLIER_ROOTS)
from recovery.local_search import bounds, digest
from .replay import replay_tree
from .search import search_level4


TARGET_IDS = frozenset({
    'CB_12_4_uniform_61004_below', 'CB_3_3_clustered_61001_below',
    'CB_3_3_clustered_61004_below', 'CB_3_3_uniform_61001_below',
    'CB_3_3_uniform_61002_below', 'CB_3_3_uniform_61003_below',
})
PRIOR_ROOTS = (*EARLIER_ROOTS, ROOT/'results/level3_certified_2026_10_05/v1')
INITIAL_LEVEL4_ROOT = ROOT/'results/level4_certified_2026_10_05/v1'
FROZEN_MANIFEST_HASH = 'b90b4eadb576b7b73f256c82574e0d5099027a14bf8c1d2173683359a0df91c6'
FROZEN_INPUT_HASHES = {
    'CB_12_4_uniform_61004_below': '6d9e38d1d31958ae2c6260d901b4e6ef7c34fb6fa135b6318467e2d8f94ff631',
    'CB_3_3_clustered_61001_below': 'a859094ddc240e6635ee99cc0490b3df4a5f09120e82a92fc0882ccbce19c439',
    'CB_3_3_clustered_61004_below': '97cec6c245d218c95ecb65f8b0d0029422ee9526e55d991c1d39d35d4f43b0cc',
    'CB_3_3_uniform_61001_below': '1d8304849da17f1bc7e65aece8b9a37aa570c5d9d90cc5a4ce9c196c063666aa',
    'CB_3_3_uniform_61002_below': '397e221d3180ccb0dd0a8f6adfa91dcce4471830e8b0e1a3fb98cd760076c72c',
    'CB_3_3_uniform_61003_below': 'bbed85377f49cf4d5b813d51bba92596b81de4b9b31412dcb20564f69a6dac60',
}


def select_targets(root):
    root = Path(root)
    if hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest() != FROZEN_MANIFEST_HASH:
        raise ValueError('prior manifest is not the frozen Level-3 run')
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    selected = []
    for path in sorted((root/'records').glob('*.json')):
        r = json.loads(path.read_text(encoding='utf-8'))
        b = r['full_domain']
        if (r['result']['status'] == 'EMPTY' and b['minimum'] is None and b['lower'] == 4
                and b['upper'] is None and b['excluded_levels'] == [0, 1, 2, 3]):
            identity = manifest['inputs'].get(r['case_id'], {})
            if (r['version'] != 'level3_target_record_v1' or r['run_hash'] != manifest['run_hash']
                    or path.stem != r['case_id'] or r['input_hash'] != identity.get('file_hash')
                    or r['baseline']['record_hash'] != identity.get('record_hash')
                    or r['baseline']['run_hash'] != manifest['prior_run_hash']
                    or record_hash(r) != r['record_hash']):
                raise ValueError('target record differs from its original frozen run')
            file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if file_hash != FROZEN_INPUT_HASHES.get(r['case_id']):
                raise ValueError('target bytes differ from the frozen Level-3 output')
            selected.append(dict(path=path, record=r, file_hash=file_hash))
    if len(selected) != 6 or {x['record']['case_id'] for x in selected} != TARGET_IDS:
        raise ValueError('target bank is not the frozen six Level-3 exclusions')
    return selected


def combine_bounds(prior, result):
    if set(prior['excluded_levels']) != set(range(4)) or prior['upper'] is not None:
        raise ValueError('global escalation requires prior exclusions through Level 3')
    status = result['status']
    if status not in ('WITNESS', 'EMPTY', 'UNRESOLVED'):
        raise ValueError('invalid certified Level-4 status')
    return bounds(range(5) if status == 'EMPTY' else range(4), 4 if status == 'WITNESS' else None)


def source_files():
    extra = [ROOT/'scripts/run_level4_targets.py', ROOT/'scripts/replay_level4.py',
             *ROOT.glob('tests/test_level4*.py')]
    return {**level3_sources(), **{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in extra if p.is_file()}}


def prior_byte_hashes():
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for root in (*PRIOR_ROOTS, INITIAL_LEVEL4_ROOT) for p in sorted(root.rglob('*')) if p.is_file()}


def _prior_manifest(root, frozen_bytes):
    root = Path(root)
    if hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest() != FROZEN_MANIFEST_HASH:
        raise ValueError('prior manifest is not the frozen Level-3 run')
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    binding = {k:manifest[k] for k in ('budget', 'inputs', 'source_hash', 'prior_byte_hashes',
                                     'prior_run_hash', 'prior_manifest_hash')}
    if (manifest['version'] != 'level3_target_run_v1' or digest(binding) != manifest['run_hash']
            or digest(manifest['source_files']) != manifest['source_hash']):
        raise ValueError('prior Level-3 manifest identity mismatch')
    verify_archive(root/'source.zip', manifest['source_files'])
    if any(frozen_bytes.get(k) != v for k,v in manifest['prior_byte_hashes'].items()):
        raise ValueError('earlier experiment bytes differ from the frozen Level-3 inputs')
    return manifest


def _audit(r):
    if r['version'] != 'level4_target_record_v1' or record_hash(r) != r['record_hash']:
        raise ValueError('Level-4 record hash mismatch')
    checked_prior = audit_level3(r['baseline'])
    if checked_prior['status'] != 'EMPTY' or not checked_prior['covered']:
        raise ValueError('prior Level-3 proof does not completely exclude its domain')
    scenario = Scenario(r['scenario'])
    if (r['case_id'] != r['baseline']['case_id'] or r['case_id'] != scenario.data['benchmark_id']
            or scenario.content_hash() != Scenario(r['baseline']['scenario']).content_hash()):
        raise ValueError('original target scenario changed')
    replay = replay_tree(scenario, r['result'])
    if not replay['valid']:
        raise ValueError('global outer/inner replay failed: '+str(replay))
    if r['full_domain'] != combine_bounds(r['baseline']['full_domain'], r['result']):
        raise ValueError('combined Level-4 conclusion mismatch')
    return replay


def _check_request(record, target, budget):
    if record['case_id'] != target['record']['case_id'] or record['baseline'] != target['record']:
        raise ValueError('embedded baseline differs from the exact frozen input')
    actual_budget = {**record['result']['budget'], 'digits':record['result']['digits']}
    if actual_budget != budget:
        raise ValueError('Level-4 proof budget differs from its run request')


def _seeds(prior):
    # Preserve the canonical verified paths/bounds from the unchanged original
    # input; do not transplant a candidate incumbent or mutable cache history.
    level2 = prior['baseline']
    seeds = [*level2['result']['leg_bounds'], *level2['baseline']['result']['paths']]
    for patch in prior['result']['patches']:
        for node in patch['nodes']:
            if node['kind'] == 'sequence':
                seeds.extend(node['proof']['leg_bounds'])
    return seeds


def run_targets(input_root, output, *, budget=None):
    input_root, output = Path(input_root).resolve(), Path(output).resolve()
    budget = budget or dict(max_seconds=60, max_nodes=100000, refinements=[2, 4],
                            digits=18, max_operations=100000, max_rows=10000)
    targets = select_targets(input_root)
    frozen_bytes = prior_byte_hashes()
    prior_manifest = _prior_manifest(input_root, frozen_bytes)
    files = source_files()
    inputs = {t['record']['case_id']:dict(file_hash=t['file_hash'], record_hash=t['record']['record_hash'])
              for t in targets}
    binding = dict(budget=budget, inputs=inputs, source_hash=digest(files), prior_byte_hashes=frozen_bytes,
                   prior_run_hash=prior_manifest['run_hash'],
                   prior_manifest_hash=hashlib.sha256((input_root/'manifest.json').read_bytes()).hexdigest())
    run_hash = digest(binding)
    output.mkdir(parents=True, exist_ok=True)
    if (output/'manifest.json').exists():
        manifest = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
        if manifest['run_hash'] != run_hash:
            raise ValueError('source, frozen inputs or budget changed; use a new run directory')
        verify_archive(output/'source.zip', files)
    else:
        publish_archive(output/'source.zip', files)
        atomic_json(output/'manifest.json', dict(version='level4_target_run_v1', run_hash=run_hash,
            **binding, source_files=files, created_utc=datetime.now(timezone.utc).isoformat(),
            runtime=dict(python=platform.python_version(), platform=platform.platform(), worker_processes=1),
            timing='One total soft time/node budget per case for one global assignment tree and all inner searches; replay separate.'))
    records = []
    for target in targets:
        prior, name = target['record'], target['record']['case_id']
        path = output/'records'/f'{name}.json'
        if path.exists():
            r = json.loads(path.read_text(encoding='utf-8'))
            if r['run_hash'] != run_hash or r['input_hash'] != target['file_hash']:
                raise ValueError('stored Level-4 record belongs to another request')
            _check_request(r, target, budget)
            _audit(r)
        else:
            audit_level3(prior)
            scenario = Scenario(prior['scenario'])
            start = perf_counter()
            result = search_level4(scenario, initial_bounds=_seeds(prior), **budget)
            solve_s = perf_counter()-start
            start = perf_counter()
            replay = replay_tree(scenario, result)
            if not replay['valid']:
                raise ValueError('new Level-4 proof failed replay: '+name+' '+str(replay))
            r = dict(version='level4_target_record_v1', run_hash=run_hash, case_id=name,
                input_hash=target['file_hash'], scenario=scenario.to_dict(), baseline=prior, result=result,
                full_domain=combine_bounds(prior['full_domain'], result), replay=replay,
                timing=dict(solve_s=solve_s, replay_s=perf_counter()-start))
            r['record_hash'] = record_hash(r)
            _check_request(r, target, budget)
            _audit(r)
            atomic_json(path, r)
        records.append(r)
        print(f"{name}: {r['result']['status']}, minimum={r['full_domain']['minimum']}, "
              f"bounds=[{r['full_domain']['lower']},{r['full_domain']['upper']}], "
              f"sequences={r['result']['effort']['sequences']}, search={r['timing']['solve_s']:.3f}s", flush=True)
    if prior_byte_hashes() != frozen_bytes:
        raise ValueError('a prior experiment file changed during the Level-4 run')
    write_report(output, records)
    return records


def audit_run(output):
    output = Path(output)
    manifest = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    binding = {k:manifest[k] for k in ('budget', 'inputs', 'source_hash', 'prior_byte_hashes',
                                     'prior_run_hash', 'prior_manifest_hash')}
    if (manifest['version'] != 'level4_target_run_v1' or digest(binding) != manifest['run_hash']
            or digest(manifest['source_files']) != manifest['source_hash']):
        raise ValueError('Level-4 manifest binding mismatch')
    targets = {t['record']['case_id']:t for t in select_targets(PRIOR_ROOTS[-1])}
    expected_inputs = {name:dict(file_hash=t['file_hash'], record_hash=t['record']['record_hash'])
                       for name,t in targets.items()}
    if manifest['inputs'] != expected_inputs:
        raise ValueError('Level-4 manifest differs from the exact frozen inputs')
    verify_archive(output/'source.zip', manifest['source_files'])
    if source_files() != manifest['source_files']:
        raise ValueError('active Level-4 replay source differs from frozen snapshot')
    frozen_bytes = prior_byte_hashes()
    if frozen_bytes != manifest['prior_byte_hashes']:
        raise ValueError('prior experiment bytes differ from pre-run snapshot')
    prior_manifest = _prior_manifest(PRIOR_ROOTS[-1], frozen_bytes)
    if (prior_manifest['run_hash'] != manifest['prior_run_hash']
            or hashlib.sha256((PRIOR_ROOTS[-1]/'manifest.json').read_bytes()).hexdigest() != manifest['prior_manifest_hash']):
        raise ValueError('prior Level-3 run binding mismatch')
    records = []
    for path in sorted((output/'records').glob('*.json')):
        r = json.loads(path.read_text(encoding='utf-8'))
        identity = manifest['inputs'].get(r['case_id'], {})
        if (path.stem != r['case_id'] or r['run_hash'] != manifest['run_hash']
                or r['input_hash'] != identity.get('file_hash')
                or r['baseline']['record_hash'] != identity.get('record_hash')
                or r['baseline']['run_hash'] != manifest['prior_run_hash']):
            raise ValueError('Level-4 record/input/run identity mismatch')
        _check_request(r, targets[r['case_id']], manifest['budget'])
        _audit(r)
        records.append(r)
    if len(records) != 6 or {r['case_id'] for r in records} != TARGET_IDS:
        raise ValueError('Level-4 run does not contain exactly six frozen targets')
    return dict(valid=True, records=6, prior_files_unchanged=len(frozen_bytes), source_hash=manifest['source_hash'],
                statuses={s:sum(r['result']['status'] == s for r in records)
                          for s in ('WITNESS', 'EMPTY', 'UNRESOLVED')})


def write_report(output, records):
    directory = Path(output)/'analysis'
    directory.mkdir(parents=True, exist_ok=True)
    columns = ['case_id', 'level4_status', 'minimum', 'lower', 'upper', 'assignment_nodes',
               'assignment_prunes', 'sequences', 'sequence_nodes', 'solve_s', 'replay_s']
    with (directory/'cases.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for r in records:
            b, e = r['full_domain'], r['result']['effort']
            writer.writerow(dict(case_id=r['case_id'], level4_status=r['result']['status'],
                **{k:b[k] for k in ('minimum', 'lower', 'upper')},
                **{k:e[k] for k in ('assignment_nodes', 'assignment_prunes', 'sequences', 'sequence_nodes')},
                **r['timing']))
    counts = {s:sum(r['result']['status'] == s for r in records) for s in ('WITNESS', 'EMPTY', 'UNRESOLVED')}
    lines = ['# Level-4 Certified Global Reoptimization v1: six frozen targets', '',
        f"Independent global outer/inner replay passed for {len(records)} cases.", '',
        f"Minimum 4: {counts['WITNESS']}; modeled infeasibility: {counts['EMPTY']}; unresolved: {counts['UNRESOLVED']}.", '',
        '| Case | Level-4 conclusion | Combined minimum/bounds |', '|---|---|---|']
    for r in records:
        b = r['full_domain']
        value = str(b['minimum']) if b['minimum'] is not None else '[4, ?]'
        lines.append(f"| {r['case_id']} | {r['result']['status']} | {value} |")
    lines.extend(['', 'Each case has exactly one original global release mask and assignment tree. '
        'Every raw owner child and every attached full-slot sequence proof is independently checked. '
        'Original commitments remain fixed; depot revisits, repeated task visits and inactive slots remain permitted.', '',
        'WITNESS certifies minimum 4 using prior exclusions 0–3. EMPTY certifies infinity for the modeled '
        'remaining-mission domain. UNRESOLVED retains lower bound 4 and no feasible upper bound.', '',
        f"Measured search: {sum(r['timing']['solve_s'] for r in records):.3f} s; new proof replay: "
        f"{sum(r['timing']['replay_s'] for r in records):.3f} s. Prior/full-run audits add overhead. "
        'These are targeted diagnostic timings, not scaling results.', '',
        'All prior primary continuous, Level-2, Level-3 and initial Level-4 experiment files were byte-hashed before/after '
        'and remain unchanged. No other case or scaling study was run.'])
    (directory/'REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
