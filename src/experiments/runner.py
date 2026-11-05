"""Record controlled paired experiments and independently audit their certificates."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import platform
from statistics import median, quantiles
import subprocess
import sys
from time import perf_counter
import zipfile

from env.scenario import Scenario
from recovery.representation import PathLibrary
from recovery.search import recover, verify_level_evidence, verify_witness
from .instances import build_instances


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path, value):
    path.write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n',encoding='utf-8')


def _append(stream, value):
    stream.write(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n')
    stream.flush()


def _jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def default_protocol():
    return dict(version='controlled-recovery-v1',formulation_date='2026-09-17',
                strategies=['ascending','level4'],repeats=3,
                budgets=dict(low=dict(total_nodes=64,total_branches=4),
                             medium=dict(total_nodes=256,total_branches=16),
                             high=dict(total_nodes=2048,total_branches=128)),
                reference_budget=dict(total_nodes=100000,total_branches=10000),
                linear_limits=dict(max_operations=10000,max_rows=2000,max_iterations=0,numerical=False),
                warmup='One excluded pair on worked B, high budget, before measurements.',
                ordering='Sequential; first strategy alternates by configuration index plus repetition index.',
                timing='perf_counter around the entire recover call; excludes construction, serialization and independent audits.',
                denominator='Configuration labels, not timing repetitions; repeated OFAT controls are not independent samples.',
                evidence='Exact minima and impossibility apply only to the declared finite path representation.',
                design_document='docs/superpowers/plans/2026-09-28-controlled-benchmark.md')


def _source_hashes(root):
    paths = [*root.glob('src/**/*.py'),*root.glob('scripts/*.py'),*root.glob('schemas/*.json'),
             *root.glob('scenarios/worked/*.json'),*root.glob('requirements*.txt'),
             root/'docs/superpowers/plans/2026-09-28-controlled-benchmark.md']
    return {p.relative_to(root).as_posix():_file_hash(p) for p in sorted(paths)}


def _provenance(root):
    return dict(started_utc=datetime.now(timezone.utc).isoformat(),
                python=sys.version,executable=sys.executable,platform=platform.platform(),
                processor=platform.processor(),logical_cpus=os.cpu_count(),
                packages={name:version(name) for name in ('numpy','scipy','shapely','jsonschema','pytest')},
                git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
                git_dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True)),
                source_hashes=_source_hashes(root))


def _solve(s, lib, strategy, budget, protocol):
    return recover(s,lib,strategy=strategy,**budget,
                   max_nodes=budget['total_nodes'],max_branches=budget['total_branches'],
                   **protocol['linear_limits'])


def _audit_report(case, report):
    s = Scenario.from_dict(case['scenario'])
    lib = PathLibrary.from_dict(s,case['representation'])
    if report['scenario_hash'] != s.content_hash() or report['representation_hash'] != lib.content_hash():
        raise ValueError('report is bound to different inputs')
    if report['representation'] != lib.to_dict() or report['previous_premise']['exact_feasible'] is not True:
        raise ValueError('invalid representation or previous-wind premise')
    actual = [r for r in report['levels'] if 'equivalent_to' not in r]
    if (sum(r['nodes'] for r in actual) != report['nodes_used']
            or sum(r['branches'] for r in actual) != report['branches_used']
            or report['nodes_used'] > report['total_node_budget']
            or report['branches_used'] > report['total_branch_budget']):
        raise ValueError('invalid shared-budget accounting')
    empty = set()
    for row in report['levels']:
        if row['status'] == 'EMPTY':
            if not verify_level_evidence(s,lib,row):
                raise ValueError('invalid exact exclusion certificate')
            empty.update(range(row['level']+1))
    if sorted(empty) != report['certified_empty_levels']:
        raise ValueError('unsupported empty-scope claim')
    lower = None if 4 in empty else 1+max(empty,default=-1)
    if report['lower_bound'] != lower:
        raise ValueError('unsupported lower bound')
    upper = None
    if report['witness'] is not None:
        w = report['witness']
        # Exact-transfer keys describe the variables of the searched scope.
        # Replaying a Level-0 proof as Level 4 would incorrectly demand keys
        # for quantities that were fixed, rather than LP variables, in its proof.
        origins = [row['level'] for row in report['levels'] if row['witness'] == w]
        if not origins:
            raise ValueError('witness is missing its searched-scope evidence')
        check = verify_witness(s,lib,w['plan'],w['reserve_paths'],origins[0],exact_transfers=w['exact_transfers'])
        if not check['accepted'] or not check['exact']:
            raise ValueError('invalid exact witness')
        upper = check['level']
    if upper != report['upper_bound'] or report['numerical_upper_bound'] is not None:
        raise ValueError('unsupported exact upper bound')
    expected = ('MINIMUM_CERTIFIED_R' if lower==upper else 'WITNESS_WITH_GAP_R') if upper is not None else (
        'NO_CONTINUATION_R' if 4 in empty else 'UNRESOLVED_R')
    if report['status'] != expected:
        raise ValueError('unsupported result status')


def _audit_records(cases, records, protocol):
    by_id = {c['id']:c for c in cases}
    identities = {c['id']:(Scenario.from_dict(c['scenario']).content_hash(),digest(c['representation'])) for c in cases}
    seen = set()
    for record in records:
        if record['case_id'] not in by_id:
            raise ValueError('unknown case in report')
        r = record['report']
        expected_strategy = record.get('strategy','ascending')
        budget = protocol['budgets'][record['budget']] if 'budget' in record else protocol['reference_budget']
        if (identities[record['case_id']] != (r['scenario_hash'],r['representation_hash'])
                or r['strategy'] != expected_strategy
                or expected_strategy not in protocol['strategies']
                or r['total_node_budget'] != budget['total_nodes']
                or r['total_branch_budget'] != budget['total_branches']):
            raise ValueError('record does not match case, strategy or protocol budget')
        if [row['level'] for row in r['levels']] != ([4] if expected_strategy=='level4' else list(range(len(r['levels'])))):
            raise ValueError('search levels do not match strategy')
        for row in r['levels']:
            if len(row['budgets']) != 1 or any(row['budgets'][0][k] != v for k,v in protocol['linear_limits'].items()):
                raise ValueError('linear solver settings differ from the protocol')
        if digest(record['report']) != record['report_hash']:
            raise ValueError('report hash mismatch')
        if record['report_hash'] not in seen:
            _audit_report(by_id[record['case_id']],record['report'])
            seen.add(record['report_hash'])
    return dict(verified_reports=len(records),unique_reports_audited=len(seen),
                method='Recompile and verify rational primal witnesses and every exact empty-level certificate.')


def _audit_grid(cases, records, measurements, references, protocol):
    if any(set(r) != {'case_id','report','report_hash'} for r in references):
        raise ValueError('reference records must use the reference context and budget')
    if any(set(r) != {'case_id','budget','strategy','report','report_hash'} for r in records):
        raise ValueError('comparison records must declare their strategy and budget')
    expected = {(c['id'],tier,strategy) for c in cases for tier in protocol['budgets'] for strategy in protocol['strategies']}
    key = lambda r:(r['case_id'],r['budget'],r['strategy'])
    if len(records) != len(expected) or {key(r) for r in records} != expected:
        raise ValueError('comparison grid is incomplete or duplicated')
    if len(references) != len(cases) or {r['case_id'] for r in references} != {c['id'] for c in cases}:
        raise ValueError('reference grid is incomplete or duplicated')
    reports = {key(r):r['report_hash'] for r in records}
    expected_measurements = {(k,rep) for k in expected for rep in range(protocol['repeats'])}
    actual = {(key(r),r['repetition']) for r in measurements}
    if len(measurements) != len(expected_measurements) or actual != expected_measurements:
        raise ValueError('timing repetition grid is incomplete or duplicated')
    indexes = {c['id']:i for i,c in enumerate(cases)}
    for row in measurements:
        order = protocol['strategies'][::(-1 if (indexes[row['case_id']]+row['repetition'])%2 else 1)]
        if (row['report_hash'] != reports[key(row)] or row['order'] != order.index(row['strategy'])
                or not math.isfinite(row['elapsed_seconds']) or row['elapsed_seconds']<0):
            raise ValueError('timing record violates pairing or deterministic replay')


def run_benchmark(root, output, *, instances=None, protocol=None, progress=print):
    """Freeze inputs first, preserve partial runs on error, and refuse overwrite."""
    root, output = Path(root), Path(output)
    if output.exists():
        raise FileExistsError(f'run directory already exists: {output}')
    cases = build_instances(root) if instances is None else instances
    protocol = default_protocol() if protocol is None else protocol
    if not cases or len({c['id'] for c in cases}) != len(cases):
        raise ValueError('cases must be nonempty with unique IDs')
    if isinstance(protocol['repeats'],bool) or not isinstance(protocol['repeats'],int) or protocol['repeats'] < 1:
        raise ValueError('repeats must be a positive integer')
    if protocol['strategies'] != ['ascending','level4'] or protocol['linear_limits']['numerical']:
        raise ValueError('this protocol requires both strategies and exact arithmetic')
    objects = [(Scenario.from_dict(c['scenario']),c) for c in cases]
    objects = [(s,PathLibrary.from_dict(s,c['representation'])) for s,c in objects]
    provenance = _provenance(root)
    output.mkdir(parents=True)
    _write(output/'protocol.json',protocol)
    _write(output/'instances.json',cases)
    _write(output/'provenance.json',provenance)
    with zipfile.ZipFile(output/'source_snapshot.zip','x',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,expected in provenance['source_hashes'].items():
            data = (root/name).read_bytes()
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError('source changed while freezing the snapshot')
            archive.writestr(name,data)
    _write(output/'inputs.lock.json',{name:_file_hash(output/name) for name in
                                    ('protocol.json','instances.json','provenance.json')})
    # Same warm-up for every run, independent of any observed result.
    warm = Scenario.from_json(root/'scenarios/worked/four_uav_case_b.json')
    warm_lib = PathLibrary.build(warm)
    for strategy in protocol['strategies']:
        _solve(warm,warm_lib,strategy,default_protocol()['budgets']['high'],protocol)
    records, measurements, references = [], [], []
    with (output/'search_reports.jsonl').open('x',encoding='utf-8') as reports_file, \
         (output/'measurements.jsonl').open('x',encoding='utf-8') as measurements_file, \
         (output/'reference_reports.jsonl').open('x',encoding='utf-8') as reference_file:
        for index,(case,(s,lib)) in enumerate(zip(cases,objects)):
            ref = _solve(s,lib,'ascending',protocol['reference_budget'],protocol)
            if ref['previous_premise']['exact_feasible'] is not True:
                raise ValueError(f'incumbent is not exactly feasible before update: {case["id"]}')
            record = dict(case_id=case['id'],report=ref,report_hash=digest(ref))
            references.append(record)
            _append(reference_file,record)
            for tier,budget in protocol['budgets'].items():
                hashes = {}
                for repetition in range(protocol['repeats']):
                    strategies = protocol['strategies'][::(-1 if (index+repetition)%2 else 1)]
                    for order,strategy in enumerate(strategies):
                        start = perf_counter()
                        report = _solve(s,lib,strategy,budget,protocol)
                        elapsed = perf_counter()-start
                        report_hash = digest(report)
                        key = dict(case_id=case['id'],budget=tier,strategy=strategy)
                        if repetition == 0:
                            record = dict(**key,report=report,report_hash=report_hash)
                            records.append(record)
                            _append(reports_file,record)
                            hashes[strategy] = report_hash
                        elif hashes[strategy] != report_hash:
                            raise ValueError(f'nondeterministic report: {key}')
                        measurement = dict(**key,repetition=repetition,order=order,
                                           elapsed_seconds=elapsed,report_hash=report_hash)
                        measurements.append(measurement)
                        _append(measurements_file,measurement)
            progress(f'{index+1}/{len(cases)} {case["id"]}: reference {ref["status"]} [{ref["lower_bound"]}, {ref["upper_bound"]}]')
    if _source_hashes(root) != provenance['source_hashes']:
        raise ValueError('source files changed during the run; preserve this run as invalid')
    summary = summarize(cases,records,measurements,references)
    _audit_grid(cases,records,measurements,references,protocol)
    audit = _audit_records(cases,records+references,protocol)
    audit['deterministic_repetitions_verified'] = len(measurements)
    audit['source_unchanged_during_run'] = True
    _write(output/'summary.json',summary)
    _write(output/'audit.json',audit)
    _write(output/'files.lock.json',{p.name:_file_hash(p) for p in sorted(output.iterdir()) if p.is_file()})
    return summary


def verify_run(output):
    """Replay certificates from saved data without reusing search decisions."""
    output = Path(output)
    for lock in ('inputs.lock.json','files.lock.json'):
        for name,expected in json.loads((output/lock).read_text(encoding='utf-8')).items():
            if _file_hash(output/name) != expected:
                raise ValueError(f'file integrity mismatch: {name}')
    cases = json.loads((output/'instances.json').read_text(encoding='utf-8'))
    protocol = json.loads((output/'protocol.json').read_text(encoding='utf-8'))
    records = _jsonl(output/'search_reports.jsonl')
    references = _jsonl(output/'reference_reports.jsonl')
    measurements = _jsonl(output/'measurements.jsonl')
    summary = json.loads((output/'summary.json').read_text(encoding='utf-8'))
    if summary != summarize(cases,records,measurements,references):
        raise ValueError('summary differs from raw records')
    _audit_grid(cases,records,measurements,references,protocol)
    return _audit_records(cases,records+references,protocol)


def summarize(cases, records, measurements, references):
    """One condition per solver comparison; repeats only contribute to timing."""
    timings = defaultdict(list)
    for row in measurements:
        timings[(row['case_id'],row['budget'],row['strategy'])].append(row['elapsed_seconds'])
    groups = defaultdict(list)
    for record in records:
        groups[(record['budget'],record['strategy'])].append(record)
    rows = []
    for (budget,strategy),group in groups.items():
        reports = [r['report'] for r in group]
        seconds = [median(timings[(r['case_id'],budget,strategy)]) for r in group]
        quartiles = quantiles(seconds,n=4,method='inclusive') if len(seconds)>1 else [seconds[0]]*3
        rows.append(dict(budget=budget,strategy=strategy,conditions=len(group),
            statuses=dict(sorted(Counter(r['status'] for r in reports).items())),
            exact_recoveries=sum(r['upper_bound'] is not None for r in reports),
            minimum_certificates=sum(r['status']=='MINIMUM_CERTIFIED_R' for r in reports),
            represented_infeasibility_certificates=sum(r['status']=='NO_CONTINUATION_R' for r in reports),
            unresolved=sum(r['status']=='UNRESOLVED_R' for r in reports),
            median_nodes=median(r['nodes_used'] for r in reports),
            median_branches=median(r['branches_used'] for r in reports),
            total_nodes=sum(r['nodes_used'] for r in reports),total_branches=sum(r['branches_used'] for r in reports),
            runtime_median_seconds=median(seconds),runtime_q1_seconds=quartiles[0],runtime_q3_seconds=quartiles[2]))
    refs = [r['report'] for r in references]
    return dict(configuration_count=len(cases),
                unique_scenario_representation_pairs=len({digest([c['scenario'],c['representation']]) for c in cases}),
                comparison_count=len(records),measurement_count=len(measurements),
                reference_statuses=dict(sorted(Counter(r['status'] for r in refs).items())),
                reference_minima=dict(sorted(Counter(str(r['upper_bound']) for r in refs
                                                    if r['status']=='MINIMUM_CERTIFIED_R').items())),
                reference_upper_bounds=dict(sorted(Counter(str(r['upper_bound']) for r in refs
                                                           if r['upper_bound'] is not None).items())),
                by_budget_strategy=rows,
                runtime_aggregation='Median and inclusive quartiles across per-condition median runtimes; repeats are not independent cases.')
