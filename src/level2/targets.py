"""Frozen thirteen-case follow-up, provenance and independently replayed reports."""
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
from time import perf_counter

from continuous.search import verify_continuous_evidence
from continuous_benchmark.records import audit_record as audit_prior
from env.scenario import Scenario
from final_benchmark.records import (ROOT, atomic_json, publish_archive, verify_archive,
                                     source_files as existing_sources, record_hash)
from recovery.local_search import bounds, digest
from .replay import replay_tree
from .search import search_level2


TARGET_IDS = frozenset({
    'CB_12_4_uniform_61004_below', 'CB_24_6_clustered_61002_below',
    'CB_24_6_uniform_61002_below', 'CB_6_3_uniform_61002_below',
    *{f'CB_3_3_{family}_{seed}_below' for family in ('uniform', 'clustered')
      for seed in range(61001, 61005)},
    'NB_3_3_uniform_41002_fixed_sequence_below',
})


def select_targets(root):
    root = Path(root)
    selected = []
    for stage in ('cohort', 'paired'):
        manifest = json.loads((root/stage/'manifest.json').read_text(encoding='utf-8'))
        for f in sorted((root/stage/'records').glob('*.json')):
            # Selection reads frozen results only. It never generates missions.
            r = json.loads(f.read_text(encoding='utf-8'))
            b = r['result']['full_domain']
            if b['minimum'] is None and b['lower'] == 2:
                if r['run_hash'] != manifest['run_hash'] or f.stem != r['case_id']:
                    raise ValueError('target record identity differs from its frozen run')
                selected.append(dict(stage=stage, path=f, record=r,
                                     file_hash=hashlib.sha256(f.read_bytes()).hexdigest()))
    if (len(selected) != 13 or {t['record']['case_id'] for t in selected} != TARGET_IDS
            or sum(t['stage'] == 'cohort' for t in selected) != 12):
        raise ValueError('target bank is not the frozen twelve plus one')
    return selected


def combine_bounds(baseline, result):
    excluded = set(baseline['excluded_levels'])
    upper = baseline['upper']
    if result['status'] == 'EMPTY':
        excluded.update((0, 1, 2))
    elif result['status'] == 'WITNESS':
        upper = 2 if upper is None else min(upper, 2)
    return bounds(excluded, upper)


def source_files():
    extra = [ROOT/'scripts/run_level2_targets.py', ROOT/'scripts/replay_level2.py',
             *ROOT.glob('tests/test_level2*.py'), *ROOT.glob('requirements*.txt')]
    return {**existing_sources(), **{p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in extra if p.is_file()}}


def _audit(r):
    if r['version'] != 'level2_target_record_v1' or record_hash(r) != r['record_hash']:
        raise ValueError('target record hash mismatch')
    if not audit_prior(r['baseline']):
        raise ValueError('frozen continuous evidence failed replay')
    s = Scenario(r['scenario'])
    if s.content_hash() != Scenario(r['baseline']['scenario']).content_hash():
        raise ValueError('target scenario changed from frozen baseline')
    replay = replay_tree(s, r['result'])
    if not replay['valid']:
        raise ValueError('Level-2 tree failed replay: '+str(replay))
    if r['full_domain'] != combine_bounds(r['baseline']['result']['full_domain'], r['result']):
        raise ValueError('combined conclusion mismatch')
    return replay


def run_targets(input_root, output, *, budget=None):
    input_root, output = Path(input_root).resolve(), Path(output).resolve()
    budget = budget or dict(max_seconds=60, max_nodes=100000, refinements=[2, 4],
                            digits=18, max_operations=100000, max_rows=10000)
    targets = select_targets(input_root)
    output.mkdir(parents=True, exist_ok=True)
    files = source_files()
    inputs = {t['record']['case_id']: dict(stage=t['stage'], file_hash=t['file_hash'],
               record_hash=t['record']['record_hash']) for t in targets}
    stage_manifests = {}
    for stage in ('cohort', 'paired'):
        m = json.loads((input_root/stage/'manifest.json').read_text(encoding='utf-8'))
        verify_archive(input_root/stage/'source.zip', m['source_files'])
        stage_manifests[stage] = dict(file_hash=hashlib.sha256((input_root/stage/'manifest.json').read_bytes()).hexdigest(),
                                      run_hash=m['run_hash'])
    binding = dict(budget=budget, inputs=inputs, prior_manifests=stage_manifests, source_hash=digest(files))
    run_hash = digest(binding)
    if (output/'manifest.json').exists():
        manifest = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
        if manifest['run_hash'] != run_hash:
            raise ValueError('source, target bank or budget changed; use a new output directory')
        verify_archive(output/'source.zip', files)
    else:
        publish_archive(output/'source.zip', files)
        atomic_json(output/'manifest.json', dict(version='level2_target_run_v1', run_hash=run_hash,
            **binding, source_files=files, created_utc=datetime.now(timezone.utc).isoformat(),
            runtime=dict(python=platform.python_version(), platform=platform.platform(), worker_processes=1),
            timing='Total soft per-case search cap checked between oracle/LP/tree operations; replay separate.'))
    records = []
    for target in targets:
        prior = target['record']
        name = prior['case_id']
        path = output/'records'/f'{name}.json'
        if path.exists():
            r = json.loads(path.read_text(encoding='utf-8'))
            if r['run_hash'] != run_hash or r['input_hash'] != target['file_hash']:
                raise ValueError('stored target record has another request')
            _audit(r)
        else:
            if not audit_prior(prior):
                raise ValueError('frozen record failed replay: '+name)
            scenario = Scenario(prior['scenario'])
            start = perf_counter()
            result = search_level2(scenario, initial_bounds=prior['result']['paths'], **budget)
            solve_s = perf_counter()-start
            start = perf_counter()
            replay = replay_tree(scenario, result)
            if not replay['valid']:
                raise ValueError('new proof failed independent replay: '+name+' '+str(replay))
            r = dict(version='level2_target_record_v1', run_hash=run_hash, case_id=name,
                     input_hash=target['file_hash'], stage=target['stage'], baseline=prior,
                     scenario=scenario.to_dict(), result=result, replay=replay,
                     full_domain=combine_bounds(prior['result']['full_domain'], result),
                     timing=dict(solve_s=solve_s, replay_s=perf_counter()-start))
            r['record_hash'] = record_hash(r)
            _audit(r)
            atomic_json(path, r)
        records.append(r)
        print(f"{name}: {r['result']['status']}, minimum={r['full_domain']['minimum']}, "
              f"bounds=[{r['full_domain']['lower']},{r['full_domain']['upper']}], "
              f"nodes={len(r['result']['nodes'])}, search={r['timing']['solve_s']:.3f}s", flush=True)
    write_report(output, records)
    return records


def audit_run(output):
    output = Path(output)
    manifest = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    binding = {k: manifest[k] for k in ('budget', 'inputs', 'prior_manifests', 'source_hash')}
    if digest(binding) != manifest['run_hash'] or digest(manifest['source_files']) != manifest['source_hash']:
        raise ValueError('manifest binding mismatch')
    verify_archive(output/'source.zip', manifest['source_files'])
    if source_files() != manifest['source_files']:
        raise ValueError('active replay source differs from frozen source snapshot')
    records = []
    for path in sorted((output/'records').glob('*.json')):
        r = json.loads(path.read_text(encoding='utf-8'))
        if (path.stem != r['case_id'] or r['run_hash'] != manifest['run_hash']
                or r['input_hash'] != manifest['inputs'][r['case_id']]['file_hash']
                or r['baseline']['record_hash'] != manifest['inputs'][r['case_id']]['record_hash']
                or r['baseline']['run_hash'] != manifest['prior_manifests'][r['stage']]['run_hash']
                or r['stage'] != manifest['inputs'][r['case_id']]['stage']):
            raise ValueError('record/input/run binding mismatch')
        _audit(r)
        records.append(r)
    if len(records) != 13 or {r['case_id'] for r in records} != TARGET_IDS:
        raise ValueError('run does not contain exactly the thirteen targets')
    return dict(valid=True, records=13, source_hash=manifest['source_hash'],
                statuses={status: sum(r['result']['status'] == status for r in records)
                          for status in ('WITNESS', 'EMPTY', 'UNRESOLVED')})


def write_report(output, records):
    output = Path(output)/'analysis'
    output.mkdir(parents=True, exist_ok=True)
    columns = ['case_id', 'stage', 'level2_status', 'minimum', 'lower', 'upper', 'nodes',
               'complete_skeletons', 'structural', 'resource', 'quantity', 'open', 'solve_s', 'replay_s']
    with (output/'cases.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for r in records:
            e = r['result']['effort']
            writer.writerow(dict(case_id=r['case_id'], stage=r['stage'], level2_status=r['result']['status'],
                minimum=r['full_domain']['minimum'], lower=r['full_domain']['lower'], upper=r['full_domain']['upper'],
                nodes=len(r['result']['nodes']), complete_skeletons=e['complete_skeletons'],
                structural=e['structural'], resource=e['resource'], quantity=e['quantity'],
                open=sum(n['kind'] == 'open' for n in r['result']['nodes']), **r['timing']))
    counts = {s: sum(r['result']['status'] == s for r in records) for s in ('WITNESS', 'EMPTY', 'UNRESOLVED')}
    text = ['# Level-2 Exhaustive Search v1: thirteen frozen targets', '',
            f"Independent tree and prior-evidence replay passed for {len(records)} cases.", '',
            f"Level 2 sufficient: {counts['WITNESS']}; Level 2 excluded: {counts['EMPTY']}; "
            f"Level 2 unresolved: {counts['UNRESOLVED']}.", '',
            '| Case | Level-2 conclusion | Combined minimum/bounds |', '|---|---|---|']
    for r in records:
        b = r['full_domain']
        conclusion = str(b['minimum']) if b['minimum'] is not None else f"[{b['lower']}, {b['upper'] or '?'}]"
        text.append(f"| {r['case_id']} | {r['result']['status']} | {conclusion} |")
    text.extend(['', 'The tree covers the full assignment-preserving route-slot alphabet, including repeated tasks, '
                 'depot revisits and inactive suffixes. Numerical paths and LP proposals never establish exclusion.', '',
                 'EMPTY proves sequence repair insufficient. A minimum of 3 additionally requires the independently '
                 'replayed stored Level-3 witness. Open geometry or budget leaves retain uncertainty.', '',
                 f"Measured search: {sum(r['timing']['solve_s'] for r in records):.3f} s; "
                 f"new tree replay: {sum(r['timing']['replay_s'] for r in records):.3f} s. "
                 'These omit initial/secondary baseline audits and full-run verification.', '',
                 'Original continuous benchmark records are unchanged. No new missions or scaling runs were generated.'])
    (output/'REPORT.md').write_text('\n'.join(text)+'\n', encoding='utf-8')
