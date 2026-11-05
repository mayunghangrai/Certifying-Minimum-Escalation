"""Descriptive case tables that retain unknown conclusions and sampling failures."""
from collections import Counter, defaultdict
import csv
from fractions import Fraction
import json
from pathlib import Path
from statistics import median

from env.local_scope import scope_family, patch_contains
from env.plan import coordinates
from recovery.linear import rational
from recovery.transfers import build_transfer_problem
from continuous.physics import stationary_duration
from .records import Scenario
from .cli import audit_run


def _stats(values):
    return dict(count=len(values), total=sum(values), median=median(values) if values else None,
                minimum=min(values) if values else None, maximum=max(values) if values else None)


def _margins(record):
    w, out = record['result']['witness'], {}
    if not w: return out
    s = Scenario(record['scenario'])
    u0 = record['result']['affected']['uavs']
    level = w['validation']['level']
    patch = next(p for p in scope_family(s, level, u0) if patch_contains(s, coordinates(s.data, w['plan']), p))
    compiled = build_transfer_problem(s, w['plan'], w['reserve_paths'], patch.releases, exact=True,
        duration_provider=lambda uid, path, time: stationary_duration(s, uid, path, w['validation']['digits'])[1])
    point = [rational(w['plan']['routes'][uid]['deliveries' if a == 'x' else 'loads'][h]) for uid, h, a in compiled.columns]
    slacks = {r.label:r.bound-sum(a*x for a,x in zip(r.coefficients, point)) for r in compiled.problem.rows}
    reserve = [v for k,v in slacks.items() if k.startswith(('reserve:', 'terminal_reserve:', 'depot_arrival_reserve:'))]
    if reserve: out['reserve_margin_wh'] = float(min(reserve))
    out['inventory_margin'] = float(slacks['inventory'])
    tasks = {t['id']:t for t in s.data['mission']['tasks']}
    deadline = []
    for t in compiled.times:
        h, uid = t['slot'], t['uav']
        if not h: continue
        route = w['plan']['routes'][uid]
        site = route['stops'][h-1]
        if site in tasks and route['deliveries'][h] > 0 and tasks[site]['deadline_h'] is not None:
            deadline.append(rational(tasks[site]['deadline_h'])-t['delivery'])
    if deadline: out['deadline_margin_h'] = float(min(deadline))
    return out


def _csv(path, rows, fields):
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def _label(value):
    return 'unknown' if value is None else str(value)


def write_report(path):
    path = Path(path)
    audit = audit_run(path)
    manifest = json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    records = [json.loads(f.read_text(encoding='utf-8')) for f in sorted((path/'records').glob('*.json'))]
    sampling = [json.loads(f.read_text(encoding='utf-8')) for f in sorted((path/'sampling').glob('*.json'))]
    rows, path_rows, groups, transitions = [], [], defaultdict(list), Counter()
    improvements = []
    for r in records:
        result, meta, old = r['result'], r['request']['metadata'], r['baseline']
        full, effort = result['full_domain'], result['effort']
        row = dict(case_id=r['case_id'], n=meta.get('n'), m=meta.get('m'), family=meta.get('family'), seed=meta.get('seed'),
            anchor=meta.get('anchor'), side=meta.get('side'), status=full['status'], minimum=_label(full['minimum']),
            lower=full['lower'], upper=full['upper'], affected_count=result.get('affected', {}).get('count'),
            generated_proposals=effort['generated_proposals'], candidate_checks=effort['candidate_checks'],
            solve_s=r['timing']['solve_s'], audit_s=r['timing']['audit_s'], observation_s=r['timing']['observation_s'],
            setup_s=effort['setup_s'], screen_s=effort['screen_s'], proposal_s=effort['proposal_s'], proof_s=effort['proof_s'],
            budget_exhausted=effort['budget_exhausted'], unsupported=result['unsupported'])
        row.update(_margins(r))
        if result['change']:
            row.update(changed_uavs=result['change']['changed_uav_count'],
                       assignment_changes=result['change']['assignment_changes'],
                       preserved_fraction=result['change']['preserved_fraction'])
        if old:
            row.update(library_minimum=_label(old['represented']['minimum']),
                       archived_full_minimum=_label(old['full_domain']['minimum']),
                       library_lower=old['represented']['lower'], library_upper=old['represented']['upper'],
                       archived_solve_s=old['timing']['solve_s'])
            transitions[row['library_minimum'], row['minimum']] += 1
            if full['upper'] is not None and (old['represented']['minimum'] == 'infinity'
                    or old['represented']['lower'] is not None and full['upper'] < old['represented']['lower']):
                improvements.append(r['case_id'])
        rows.append(row)
        groups[meta.get('anchor', 'continuous'), meta.get('side', 'control')].append(row)
        for i, q in enumerate(result['paths']):
            path_rows.append(dict(case_id=r['case_id'], query=i, uid=q['uid'], start=json.dumps(q['start']), goal=json.dumps(q['goal']),
                lower_h=float(Fraction(q['lower'])), upper_h=float(Fraction(q['upper'])), gap_h=float(Fraction(q['gap'])),
                global_certificate=q['lower_certificate'] is not None, vertices=len(q['path'])))
    summary = dict(version='continuous-benchmark-summary-v1', stage=manifest['config']['stage'],
        phase=manifest['config']['phase'], run_hash=manifest['run_hash'], audit=audit, cases=len(records),
        minima=dict(Counter(row['minimum'] for row in rows)), statuses=dict(Counter(row['status'] for row in rows)),
        certified_minima=sum(row['minimum'] != 'unknown' for row in rows),
        feasible_witnesses=sum(row['upper'] is not None for row in rows),
        unsupported=dict(Counter(row['unsupported'] for row in rows if row['unsupported'])),
        timing={key:_stats([r['timing'][key] for r in records]) for key in ('solve_s', 'audit_s', 'observation_s')},
        effort={key:_stats([r['result']['effort'][key] for r in records])
                for key in ('setup_s', 'screen_s', 'proposal_s', 'proof_s', 'generated_proposals', 'candidate_checks')},
        paths=dict(queries=len(path_rows), certified_lower_fields=sum(p['global_certificate'] for p in path_rows),
                   gaps_h=_stats([p['gap_h'] for p in path_rows if p['global_certificate']])),
        sampling=audit['sampling'], group_counts={f'{a}/{s}':dict(cases=len(g), minima=dict(Counter(r['minimum'] for r in g)))
                                                for (a,s),g in sorted(groups.items())},
        rigorous_library_penalty_cases=improvements,
        interpretation=['Potential meshes certify bounds over all continuous paths; candidate itineraries remain bounded numerical proposals.',
            'Unknown minima and capped sampling failures are retained. Success is never inferred from proposal exhaustion.',
            'Screen and proof components overlap; sum solve, observations, audit and generation to obtain total measured cost.',
            'Archived baseline timings use an earlier runtime and a separate proposal clock, so no speed ranking is inferred.',
            'Shared draws and conditional sampling do not justify independence-based confidence intervals.'])
    if sampling:
        summary['generation_s'] = _stats([i['generation_s'] for i in sampling])
        summary['attempt_outcomes'] = dict(Counter(a['outcome'] for i in sampling for a in i['metadata']['attempts']))
        summary['reference_gaps_h'] = _stats([float(Fraction(i['metadata']['reference_gap'])) for i in sampling if i['metadata']['status'] == 'accepted'])
    if records and records[0]['baseline']:
        summary['archived'] = dict(represented_minima=dict(Counter(_label(r['baseline']['represented']['minimum']) for r in records)),
                                  full_minima=dict(Counter(_label(r['baseline']['full_domain']['minimum']) for r in records)))
    analysis = path/'analysis'; analysis.mkdir(exist_ok=True)
    fields = ['case_id','n','m','family','seed','anchor','side','status','minimum','lower','upper','affected_count',
        'library_minimum','archived_full_minimum','library_lower','library_upper','changed_uavs','assignment_changes','preserved_fraction',
        'deadline_margin_h','reserve_margin_wh','inventory_margin','solve_s','audit_s','observation_s','setup_s','screen_s','proposal_s',
        'proof_s','generated_proposals','candidate_checks','budget_exhausted','unsupported','archived_solve_s']
    _csv(analysis/'cases.csv', rows, fields)
    _csv(analysis/'paths.csv', path_rows, ['case_id','query','uid','start','goal','lower_h','upper_h','gap_h','global_certificate','vertices'])
    _csv(analysis/'transitions.csv', [dict(library=a, continuous=b, count=n) for (a,b),n in sorted(transitions.items())], ['library','continuous','count'])
    (analysis/'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    lines = [f"# Continuous paths: {summary['stage']} ({summary['phase']})", '',
        f"Independent replay passed for {len(records)} records. Certified minima: {summary['certified_minima']}/{len(records)}. "
        f"Feasible witnesses: {summary['feasible_witnesses']}/{len(records)}.", '',
        '| Minimum level | Cases |', '|---|---:|']
    lines.extend(f'| {k} | {summary["minima"].get(k, 0)} |' for k in ['0','1','2','3','4','infinity','unknown'])
    lines += ['', f"Measured search: {summary['timing']['solve_s']['total']:.3f} s; independent replay: "
              f"{summary['timing']['audit_s']['total']:.3f} s; controlled path observations: {summary['timing']['observation_s']['total']:.3f} s."]
    if sampling:
        lines += ['', f"Sampling accepted {audit['sampling']['accepted']}/{audit['sampling']['requested']} base missions; "
                  f"{audit['sampling']['failed']} failed slots retained. Generation took {summary['generation_s']['total']:.3f} s."]
    if 'archived' in summary:
        lines += ['', f"The archived library has {len(records)-summary['archived']['represented_minima'].get('unknown',0)} certified minima; "
                  f"its all-path evidence has {len(records)-summary['archived']['full_minima'].get('unknown',0)}. "
                  f"New continuous witnesses prove a library penalty in {len(improvements)} cases."]
    lines += ['', 'Case observations, margins, path bounds and transitions are in the adjacent CSV files.', '']
    lines.extend('- '+s for s in summary['interpretation'])
    (analysis/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return summary
