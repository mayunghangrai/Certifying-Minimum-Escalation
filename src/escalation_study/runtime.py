"""Runtime profile R1: budget reruns, uncontended timing and larger missions.

Budget and timing reruns are ordinary P1 runs on a seed subset (same missions,
different caps or one worker); ``compare_runs`` matches them by case. Larger
missions report Level 0-2 witnesses and their times only.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
from time import perf_counter, process_time

from continuous.search import recover_continuous, verify_continuous_evidence
from env.scenario import Scenario
from final_benchmark.records import atomic_json, publish_archive, verify_archive
from level2.replay import replay_tree
from level2.search import search_level2
from recovery.local_search import digest
from .analysis import rows
from .ladder import _level2_seeds, add_seeds, stage_queries
from .missions import base_mission, mission_id, variant_id
from .store import read_gzip_json, record_hash, source_files, write_gzip_json


def compare_runs(reference, other):
    """Per-case outcome and wall-time comparison between two P1 runs."""
    base = {r['case']: r for r in rows(reference)[0]}
    out = []
    for r in rows(other)[0]:
        b = base.get(r['case'])
        if b is None:
            continue
        out.append(dict(case=r['case'], reference_category=b['category'], other_category=r['category'],
                        reference_certificate_s=b['certificate_wall_s'], other_certificate_s=r['certificate_wall_s'],
                        reference_wall_s=b['wall_s'], other_wall_s=r['wall_s'],
                        reference_cpu_s=b['cpu_s'], other_cpu_s=r['cpu_s']))
    return out


def large_mission(n, m, family, seed, *, strength, slack, max_seconds, max_proposals, refinements=(2, 4),
                  digits=18, max_nodes=100000, max_attempts=24):
    """Generate one variant and look for Level 0-2 witnesses within one total cap."""
    start = perf_counter()
    scenarios, ledger = base_mission(n, m, family, seed, max_attempts=max_attempts, strengths=(strength,),
                                     slacks=(slack,))
    generation_s = perf_counter()-start
    result = dict(mission=ledger['mission'], ledger=ledger, generation_s=generation_s, scenario=None,
                  screen=None, level2=None, timing={})
    if not scenarios:
        return result
    case = variant_id(ledger['mission'], 0, 0)
    scenario = Scenario(scenarios[case])
    result['scenario'] = scenario.to_dict()
    wall, cpu = perf_counter(), process_time()
    screen = recover_continuous(scenario, max_seconds=max_seconds, max_proposals=max_proposals,
                                refinements=refinements, digits=digits)
    result['screen'] = screen
    result['timing']['screen'] = dict(wall_s=perf_counter()-wall, cpu_s=process_time()-cpu)
    upper = screen['full_domain']['upper']
    remaining = max_seconds-(perf_counter()-wall)
    if (upper is None or upper > 2) and 2 not in screen['full_domain']['excluded_levels'] and remaining > 0:
        seeds = {}
        add_seeds(seeds, stage_queries('screen', screen))
        level_wall, level_cpu = perf_counter(), process_time()
        report = search_level2(scenario, max_seconds=remaining, max_nodes=max_nodes, refinements=refinements,
                               digits=digits, initial_bounds=_level2_seeds(scenario, seeds, screen['affected']['uavs']))
        result['level2'] = report
        result['timing']['level2'] = dict(wall_s=perf_counter()-level_wall, cpu_s=process_time()-level_cpu)
    result['timing']['total'] = dict(wall_s=perf_counter()-wall, cpu_s=process_time()-cpu)
    return result


def run_large(out, config, *, log=print):
    out = Path(out)
    files = source_files()
    binding = dict(config=config, source_hash=digest(files))
    run_hash = digest(binding)
    manifest = out/'manifest.json'
    if manifest.exists():
        if json.loads(manifest.read_text(encoding='utf-8'))['run_hash'] != run_hash:
            raise ValueError('source or configuration changed; use a new directory')
        verify_archive(out/'source.zip', files)
    else:
        out.mkdir(parents=True, exist_ok=True)
        publish_archive(out/'source.zip', files)
        atomic_json(manifest, dict(version='escalation-large-missions-v1', run_hash=run_hash, **binding,
                                   source_files=files, created_utc=datetime.now(timezone.utc).isoformat(),
                                   runtime=dict(python=platform.python_version(), platform=platform.platform(),
                                                logical_cpus=os.cpu_count(), worker_processes=1)))
    for n, m in config['sizes']:
        for family in config['families']:
            for seed in config['seeds']:
                path = out/'records'/f'{mission_id(n, m, family, seed)}.json.gz'
                if path.exists():
                    continue
                result = large_mission(n, m, family, seed, **config['search'])
                record = dict(version='escalation-large-record-v1', run_hash=run_hash, **result)
                record['record_hash'] = record_hash(record)
                path.parent.mkdir(parents=True, exist_ok=True)
                write_gzip_json(path, record)
                log(f"{record['mission']}: {_claim(record)}")


def _claim(record):
    if record['scenario'] is None:
        return 'generation failed'
    upper = record['screen']['full_domain']['upper']
    if record['level2'] and record['level2']['status'] == 'WITNESS':
        upper = 2 if upper is None else min(upper, 2)
    return f"witness level {upper}" if upper is not None else 'no witness within the cap'


def audit_large(out):
    out = Path(out)
    manifest = json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    verify_archive(out/'source.zip', manifest['source_files'])
    summary = []
    for path in sorted((out/'records').glob('*.json.gz')):
        record = read_gzip_json(path)
        if record['record_hash'] != record_hash(record) or record['run_hash'] != manifest['run_hash']:
            raise ValueError('large-mission record binding failed: '+path.name)
        if record['scenario'] is not None:
            scenario = Scenario(record['scenario'])
            if not verify_continuous_evidence(scenario, record['screen']):
                raise ValueError('screen evidence failed replay: '+path.name)
            if record['level2'] is not None and not replay_tree(scenario, record['level2'])['valid']:
                raise ValueError('Level-2 evidence failed replay: '+path.name)
        summary.append(dict(mission=record['mission'], claim=_claim(record),
                            wall_s=None if record['scenario'] is None else record['timing']['total']['wall_s']))
    return summary
