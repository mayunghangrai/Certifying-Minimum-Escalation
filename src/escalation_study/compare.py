"""Run and summarize comparator policies on the variants of a finished P1 run."""
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import csv
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import platform
from statistics import median

from env.scenario import Scenario
from final_benchmark.records import atomic_json, publish_archive, verify_archive
from recovery.local_search import digest
from .analysis import load
from .comparators import POLICIES, finite_library, global_first, time_sliced, verify_comparator
from .store import read_gzip_json, record_hash, source_files, write_gzip_json


def _final_bounds(phases, case):
    record = phases['pass2'].get(case) or phases['pass1'].get(case)
    return None if record is None else record['result']['bounds']


def _selected(p1_run):
    """Variants whose certified lower bound is at least 1 (the update matters)."""
    ledgers, phases = load(p1_run)
    chosen = {}
    for mission, item in sorted(ledgers.items()):
        if item['ledger']['status'] != 'accepted':
            continue
        for case in sorted(item['ledger']['variants']):
            b = _final_bounds(phases, case)
            if b is not None and (b['lower'] is None or b['lower'] >= 1):
                chosen.setdefault(mission, []).append((case, b))
    return ledgers, chosen


def _bind(out, config, p1_run, workers):
    p1 = Path(p1_run)
    files = source_files()
    binding = dict(config=config, source_hash=digest(files),
                   p1_manifest_hash=hashlib.sha256((p1/'manifest.json').read_bytes()).hexdigest())
    run_hash = digest(binding)
    manifest = out/'manifest.json'
    if manifest.exists():
        stored = json.loads(manifest.read_text(encoding='utf-8'))
        if stored['run_hash'] != run_hash:
            raise ValueError('source, configuration or P1 run changed; use a new directory')
        verify_archive(out/'source.zip', files)
    else:
        out.mkdir(parents=True, exist_ok=True)
        publish_archive(out/'source.zip', files)
        atomic_json(manifest, dict(version='escalation-comparators-v1', run_hash=run_hash, **binding,
                                   p1_run=str(p1), source_files=files, created_utc=datetime.now(timezone.utc).isoformat(),
                                   runtime=dict(python=platform.python_version(), platform=platform.platform(),
                                                logical_cpus=os.cpu_count(), worker_processes=workers)))
    return run_hash


def _mission_job(out, config, p1_run, mission, cases, run_hash):
    path = Path(out)/'records'/f'{mission}.json.gz'
    if path.exists():
        return mission, 0
    ledgers, _ = load(p1_run)
    scenarios = ledgers[mission]['scenarios']
    entries = []
    for case, b in cases:
        scenario = Scenario(scenarios[case])
        results = {
            'C1_finite_library': finite_library(scenario, **config['c1']),
            'C2_global_first': global_first(scenario, **config['c2']),
            'C3_time_sliced': time_sliced(scenario, **config['c3']),
        }
        entries.append(dict(case=case, scenario_hash=scenario.content_hash(), p1_bounds=b, results=results))
    record = dict(version='escalation-comparator-record-v1', run_hash=run_hash, mission=mission, entries=entries)
    record['record_hash'] = record_hash(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.tmp')
    write_gzip_json(temporary, record)
    os.replace(temporary, path)
    return mission, len(entries)


def run_comparators(out, config, p1_run, *, workers=1, log=print):
    out = Path(out)
    run_hash = _bind(out, config, p1_run, workers)
    _, chosen = _selected(p1_run)
    jobs = [(str(out), config, str(p1_run), mission, cases, run_hash) for mission, cases in chosen.items()]
    if workers <= 1:
        for job in jobs:
            log('%s: %d variants' % _mission_job(*job))
        return
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('spawn')) as pool:
        for future in as_completed([pool.submit(_mission_job, *job) for job in jobs]):
            log('%s: %d variants' % future.result())


def audit_comparators(out, p1_run):
    out = Path(out)
    manifest = json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    verify_archive(out/'source.zip', manifest['source_files'])
    ledgers, chosen = _selected(p1_run)
    checked = 0
    for path in sorted((out/'records').glob('*.json.gz')):
        record = read_gzip_json(path)
        if record['record_hash'] != record_hash(record) or record['run_hash'] != manifest['run_hash']:
            raise ValueError('comparator record binding failed: '+path.name)
        expected = {case: b for case, b in chosen[record['mission']]}
        for entry in record['entries']:
            scenario = Scenario(ledgers[record['mission']]['scenarios'][entry['case']])
            if entry['scenario_hash'] != scenario.content_hash() or entry['p1_bounds'] != expected[entry['case']]:
                raise ValueError('comparator entry differs from the P1 run: '+entry['case'])
            for policy in POLICIES:
                if not verify_comparator(scenario, entry['results'][policy]):
                    raise ValueError(f"comparator witness failed: {entry['case']} {policy}")
            checked += 1
    return checked


def summarize(out):
    out = Path(out)
    rows = []
    for path in sorted((out/'records').glob('*.json.gz')):
        record = read_gzip_json(path)
        for entry in record['entries']:
            b = entry['p1_bounds']
            for policy in POLICIES:
                r = entry['results'][policy]
                change = r['change'] or {}
                rows.append(dict(case=entry['case'], policy=policy, certified_minimum=b['minimum'],
                                 found=r['found'], level=r['level'],
                                 over_intervention=(r['found'] and b['minimum'] not in (None, 'infinity')
                                                    and r['level'] > b['minimum']),
                                 changed_uavs=change.get('changed_uav_count'), outside_changed=change.get('outside_changed'),
                                 assignment_changes=change.get('assignment_changes'),
                                 first_plan_wall_s=r['first_plan_wall_s'], minimality_certified=r['minimality_certified']))
    analysis = out/'analysis'
    analysis.mkdir(exist_ok=True)
    if rows:
        with (analysis/'comparators.csv').open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    table = []
    for policy in POLICIES:
        members = [r for r in rows if r['policy'] == policy]
        certified = [r for r in members if r['certified_minimum'] not in (None, 'infinity')]
        found = [r for r in members if r['found']]
        table.append(dict(policy=policy, variants=len(members), plans_found=len(found),
                          finite_minimum_variants=len(certified),
                          over_intervention=sum(r['over_intervention'] for r in certified),
                          plans_on_finite_minimum=sum(r['found'] for r in certified),
                          median_changed_uavs=median([r['changed_uavs'] for r in found if r['changed_uavs'] is not None] or [0]),
                          median_first_plan_s=median([r['first_plan_wall_s'] for r in found
                                                      if r['first_plan_wall_s'] is not None] or [0]),
                          minimality_claimed=sum(bool(r['minimality_certified']) for r in members)))
    (analysis/'comparators_summary.json').write_text(json.dumps(table, indent=2)+'\n', encoding='utf-8')
    return table
