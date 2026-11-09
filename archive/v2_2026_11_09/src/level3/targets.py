"""Immutable eight-case Level-3 escalation with original-record byte audits."""
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
from time import perf_counter

from env.scenario import Scenario
from final_benchmark.records import (ROOT, atomic_json, publish_archive, verify_archive,
                                     source_files as existing_sources, record_hash)
from level2.targets import _audit as audit_level2
from recovery.local_search import bounds, digest
from .replay import replay_tree
from .search import search_level3


TARGET_IDS = frozenset({
    'CB_12_4_uniform_61004_below',
    *{f'CB_3_3_uniform_{seed}_below' for seed in range(61001, 61005)},
    *{f'CB_3_3_clustered_{seed}_below' for seed in (61001, 61002, 61004)},
})
PRIOR_ROOTS = (ROOT/'results/continuous_paths_2026_10_05/primary',
               ROOT/'results/level2_exhaustive_2026_10_05/v1')


def select_targets(root):
    root = Path(root)
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    selected = []
    for path in sorted((root/'records').glob('*.json')):
        r = json.loads(path.read_text(encoding='utf-8'))
        b = r['full_domain']
        if r['result']['status'] == 'EMPTY' and b['minimum'] is None and b['lower'] == 3:
            if (r['run_hash'] != manifest['run_hash'] or path.stem != r['case_id']
                    or r['input_hash'] != manifest['inputs'][r['case_id']]['file_hash']
                    or record_hash(r) != r['record_hash']):
                raise ValueError('target record differs from its original frozen run')
            selected.append(dict(path=path, record=r, file_hash=hashlib.sha256(path.read_bytes()).hexdigest()))
    if len(selected) != 8 or {t['record']['case_id'] for t in selected} != TARGET_IDS:
        raise ValueError('target bank is not the frozen eight higher-minimum gaps')
    return selected


def combine_bounds(prior, result):
    excluded = set(prior['excluded_levels'])
    upper = prior['upper']
    if result['status'] == 'WITNESS':
        upper = 3 if upper is None else min(upper, 3)
    elif result['status'] == 'EMPTY':
        excluded.update(range(4))
    return bounds(excluded, upper)


def source_files():
    extra = [ROOT/'scripts/run_level3_targets.py', ROOT/'scripts/replay_level3.py',
             ROOT/'scripts/replay_level2.py', *ROOT.glob('tests/test_level3*.py'),
             *ROOT.glob('tests/test_level2*.py'), *ROOT.glob('requirements*.txt')]
    return {**existing_sources(), **{p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in extra if p.is_file()}}


def prior_byte_hashes():
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for root in PRIOR_ROOTS for p in sorted(root.rglob('*')) if p.is_file()}


def _audit(r):
    if r['version'] != 'level3_target_record_v1' or record_hash(r) != r['record_hash']:
        raise ValueError('Level-3 record hash mismatch')
    audit_level2(r['baseline'])
    s = Scenario(r['scenario'])
    if s.content_hash() != Scenario(r['baseline']['scenario']).content_hash():
        raise ValueError('original target scenario changed')
    replay = replay_tree(s, r['result'])
    if not replay['valid']:
        raise ValueError('outer/inner proof replay failed: '+str(replay))
    if r['full_domain'] != combine_bounds(r['baseline']['full_domain'], r['result']):
        raise ValueError('combined Level-3 conclusion mismatch')
    return replay


def run_targets(input_root, output, *, budget=None):
    input_root, output = Path(input_root).resolve(), Path(output).resolve()
    budget = budget or dict(max_seconds=60, max_nodes=100000, refinements=[2, 4],
                            digits=18, max_operations=100000, max_rows=10000)
    targets = select_targets(input_root)
    prior_manifest = json.loads((input_root/'manifest.json').read_text(encoding='utf-8'))
    verify_archive(input_root/'source.zip', prior_manifest['source_files'])
    prior_binding = {k: prior_manifest[k] for k in ('budget', 'inputs', 'prior_manifests', 'source_hash')}
    if (digest(prior_binding) != prior_manifest['run_hash']
            or digest(prior_manifest['source_files']) != prior_manifest['source_hash']):
        raise ValueError('prior Level-2 manifest identity mismatch')
    # This intentionally checks the archived prior source rather than requiring
    # live code to equal it: the explicit kernel is the new implementation.
    frozen_bytes = prior_byte_hashes()
    files = source_files()
    inputs = {t['record']['case_id']: dict(file_hash=t['file_hash'], record_hash=t['record']['record_hash'])
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
        atomic_json(output/'manifest.json', dict(version='level3_target_run_v1', run_hash=run_hash,
            **binding, source_files=files, created_utc=datetime.now(timezone.utc).isoformat(),
            runtime=dict(python=platform.python_version(), platform=platform.platform(), worker_processes=1),
            timing='One total soft time/node budget per case shared by all patches and inner searches; replay separate.'))
    records = []
    for target in targets:
        prior, name = target['record'], target['record']['case_id']
        path = output/'records'/f'{name}.json'
        if path.exists():
            r = json.loads(path.read_text(encoding='utf-8'))
            if r['run_hash'] != run_hash or r['input_hash'] != target['file_hash']:
                raise ValueError('stored Level-3 record belongs to another request')
            _audit(r)
        else:
            audit_level2(prior)
            scenario = Scenario(prior['scenario'])
            seeds = [*prior['result']['leg_bounds'], *prior['baseline']['result']['paths']]
            start = perf_counter()
            result = search_level3(scenario, initial_bounds=seeds, **budget)
            solve_s = perf_counter()-start
            start = perf_counter()
            replay = replay_tree(scenario, result)
            if not replay['valid']:
                raise ValueError('new Level-3 proof failed replay: '+name+' '+str(replay))
            r = dict(version='level3_target_record_v1', run_hash=run_hash, case_id=name,
                input_hash=target['file_hash'], scenario=scenario.to_dict(), baseline=prior, result=result,
                full_domain=combine_bounds(prior['full_domain'], result), replay=replay,
                timing=dict(solve_s=solve_s, replay_s=perf_counter()-start))
            r['record_hash'] = record_hash(r)
            _audit(r)
            atomic_json(path, r)
        records.append(r)
        print(f"{name}: {r['result']['status']}, minimum={r['full_domain']['minimum']}, "
              f"bounds=[{r['full_domain']['lower']},{r['full_domain']['upper']}], "
              f"patches={len(r['result']['patches'])}, sequences={r['result']['effort']['sequences']}, "
              f"search={r['timing']['solve_s']:.3f}s", flush=True)
    if prior_byte_hashes() != frozen_bytes:
        raise ValueError('a prior experiment file changed during the Level-3 run')
    write_report(output, records)
    return records


def audit_run(output):
    output = Path(output)
    manifest = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    binding = {k: manifest[k] for k in ('budget', 'inputs', 'source_hash', 'prior_byte_hashes',
                                      'prior_run_hash', 'prior_manifest_hash')}
    if digest(binding) != manifest['run_hash'] or digest(manifest['source_files']) != manifest['source_hash']:
        raise ValueError('Level-3 manifest binding mismatch')
    verify_archive(output/'source.zip', manifest['source_files'])
    if source_files() != manifest['source_files']:
        raise ValueError('active Level-3 replay source differs from frozen snapshot')
    if prior_byte_hashes() != manifest['prior_byte_hashes']:
        raise ValueError('prior experiment bytes differ from pre-run snapshot')
    records = []
    for path in sorted((output/'records').glob('*.json')):
        r = json.loads(path.read_text(encoding='utf-8'))
        if (path.stem != r['case_id'] or r['run_hash'] != manifest['run_hash']
                or r['input_hash'] != manifest['inputs'][r['case_id']]['file_hash']
                or r['baseline']['record_hash'] != manifest['inputs'][r['case_id']]['record_hash']
                or r['baseline']['run_hash'] != manifest['prior_run_hash']):
            raise ValueError('Level-3 record/input/run identity mismatch')
        _audit(r)
        records.append(r)
    if len(records) != 8 or {r['case_id'] for r in records} != TARGET_IDS:
        raise ValueError('Level-3 run does not contain exactly eight frozen targets')
    return dict(valid=True, records=8, prior_files_unchanged=len(manifest['prior_byte_hashes']),
                source_hash=manifest['source_hash'],
                statuses={s: sum(r['result']['status'] == s for r in records)
                          for s in ('WITNESS', 'EMPTY', 'UNRESOLVED')})


def write_report(output, records):
    directory = Path(output)/'analysis'
    directory.mkdir(parents=True, exist_ok=True)
    columns = ['case_id', 'level3_status', 'minimum', 'lower', 'upper', 'patches', 'assignment_nodes',
               'assignment_prunes', 'sequences', 'sequence_nodes', 'solve_s', 'replay_s']
    with (directory/'cases.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for r in records:
            e, b = r['result']['effort'], r['full_domain']
            writer.writerow(dict(case_id=r['case_id'], level3_status=r['result']['status'], minimum=b['minimum'],
                lower=b['lower'], upper=b['upper'], patches=len(r['result']['patches']),
                **{k:e[k] for k in ('assignment_nodes', 'assignment_prunes', 'sequences', 'sequence_nodes')},
                **r['timing']))
    counts = {s: sum(r['result']['status'] == s for r in records) for s in ('WITNESS', 'EMPTY', 'UNRESOLVED')}
    lines = ['# Level-3 Certified Reassignment v1: eight frozen targets', '',
        f"Independent outer/inner proof replay passed for {len(records)} cases.", '',
        f"Level 3 feasible: {counts['WITNESS']}; excluded: {counts['EMPTY']}; unresolved: {counts['UNRESOLVED']}.", '',
        '| Case | Level-3 conclusion | Combined minimum/bounds |', '|---|---|---|']
    for r in records:
        b = r['full_domain']
        value = str(b['minimum']) if b['minimum'] is not None else f"[{b['lower']}, {b['upper'] or '?'}]"
        lines.append(f"| {r['case_id']} | {r['result']['status']} | {value} |")
    lines.extend(['', 'Every permitted helper patch is represented. Raw assignment branches include the whole fleet '
        'and unassigned ownership when released; fixed-route incompatibility is explicitly certified. '
        'Every attached full-slot sequence proof is checked against its candidate assignment and original release mask.', '',
        'UNRESOLVED inner proofs remain open in the outer conclusion. Shared caches are scenario-scoped, '
        'and each proof includes immutable copies of its own consumed evidence.', '',
        f"Measured search: {sum(r['timing']['solve_s'] for r in records):.3f} s; new outer/inner replay: "
        f"{sum(r['timing']['replay_s'] for r in records):.3f} s. Prior audits and final full-run checks are additional.", '',
        'Prior primary continuous and Level-2 experiment files were byte-hashed before and after the run and remain unchanged. '
        'No new missions, Level-4 search or scaling study was run.'])
    (directory/'REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
