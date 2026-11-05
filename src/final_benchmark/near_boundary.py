"""Conditional random missions bracketing loss of incumbent deadline feasibility."""
from copy import deepcopy
from fractions import Fraction
import math
import random

from env.fixed_plan import evaluate_plan
from env.local_scope import affected_uavs, scope_family
from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update
from recovery.local_search import previous_premise, verify_local_witness
from recovery.physical_proofs import physical_certificate
from recovery.transfers import build_transfer_problem
from .controlled import Case
from .generators import random_pair, axis_library


def _ceil_decimal(value):
    return math.ceil(Fraction(value) * 10**10) / 10**10


def _floor_decimal(value):
    return math.floor(Fraction(value) * 10**10) / 10**10


def _times(scenario, projection, *, plan=None, reserves=None):
    p = scenario.to_dict()
    if projection == 'previous':
        p['wind']['received'] = deepcopy(p['wind']['previous'])
        p['wind']['update_support'] = []
    s = Scenario(p)
    releases = dict(A=(), S=(), L=(), P=tuple(f'{uid}:{h}' for uid,r in p['incumbent']['routes'].items() for h in range(1,len(r['stops'])+1)))
    c = build_transfer_problem(s, plan or p['incumbent'], reserves or p['reserve_paths'], releases, exact=True)
    return {p['incumbent']['routes'][r['uav']]['stops'][r['slot']-1]: r['delivery']
            for r in c.times if r['slot'] and p['incumbent']['routes'][r['uav']]['stops'][r['slot']-1] != 'DEPOT'}


def _resource_reference(p, before, after, slack):
    requirements = {}
    for u in p['mission']['vehicles']:
        uid, cap, reserve = u['id'], u['battery_capacity_wh'], u['reserve_wh']
        required = reserve
        for evaluation in (before, after):
            required = max(required, cap-evaluation.final_states[uid]['battery_wh']+reserve)
            for key, check in evaluation.reserve_checks.items():
                if key.startswith('reserve:'+uid+':'):
                    required = max(required, cap-check['state']['battery_wh']+check['energy_wh']+reserve)
        requirements[uid] = required
    scale = max(1, max(requirements.values()))
    for u in p['mission']['vehicles']:
        cap = _ceil_decimal(Fraction(str(requirements[u['id']]))+Fraction(str(slack))*Fraction(str(scale)))
        u['battery_capacity_wh'] = cap
        p['state']['fleet'][u['id']]['battery_wh'] = cap


def near_boundary_pair(n, m, family, seed, *, max_attempts=48, offset='1/10', anchor='incumbent'):
    """Select by exposure/boundary checks only; never query a recovery label.

    Every 16 support trials draw a new geometry. Failed slots are returned with
    their complete ledger; callers must not replace them with extra primary seeds.
    """
    if (n < 1 or m < 3 or family not in ('uniform', 'clustered') or max_attempts < 0
            or anchor not in ('incumbent','fixed_sequence')):
        raise ValueError('invalid conditional generator setting')
    eps = Fraction(offset)
    if not 0 < eps < 1: raise ValueError('offset must be between zero and one')
    rng = random.Random(seed)
    base = f'NB_{n}_{m}_{family}_{seed}_{anchor}'
    meta = dict(status='generation_failed', boundary_type='incumbent_deadline' if anchor=='incumbent' else 'represented_fixed_sequence_deadline',
                anchor=anchor, base_mission=base,
                n=n, m=m, family=family, seed=seed, offset=str(eps), attempts=[],
                selection_uses_recovery_labels=False, locality_limit=m//2)
    for attempt in range(max_attempts):
        if attempt % 16 == 0:
            geometry_seed = seed*100+attempt//16
            p = random_pair(n, m, family, geometry_seed)[0].scenario.to_dict()
            p['mission']['horizon_h'] = 1000
            for t in p['mission']['tasks']: t['deadline_h'] = None
            speeds = [1, 1.275, 1.56]
            rng.shuffle(speeds)
            for j, u in enumerate(p['mission']['vehicles']):
                u.update(airspeed_kmh=speeds[j % 3], battery_capacity_wh=10000)
                p['state']['fleet'][u['id']]['battery_wh'] = 10000
            p['wind'].update(time_knots_h=[0, 1000], speed_bound_kmh=.6, update_support=[])
            for projection in ('previous', 'received'):
                p['wind'][projection].update(values=[[[0, 0]] for _ in p['wind']['cells']],
                    admissible=[[True] for _ in p['wind']['cells']], coverage=['forecast'])
            baseline = evaluate_plan(Scenario(p), projection='previous')
            support = sorted({q['cell_id'] for records in baseline.records.values()
                              for r in records for q in r['wind_queries']})
        q = deepcopy(p)
        cell = rng.choice(support)
        axis, sign = rng.randrange(2), rng.choice([-1, 1])
        vector = [0, 0]; vector[axis] = '3/5' if sign > 0 else '-3/5'
        cell_index = next(i for i, c in enumerate(q['wind']['cells']) if c['id'] == cell)
        q['wind']['received']['values'][cell_index][0] = vector
        q['wind']['update_support'] = [[cell, 0]]
        s = Scenario(q)
        diagnostic = diagnose_wind_update(s)
        affected = affected_uavs(s, diagnostic)
        log = dict(attempt=attempt, geometry_seed=geometry_seed, cell=cell, wind=vector,
                   affected_count=affected['count'])
        meta['attempts'].append(log)
        if not 0 < affected['count'] <= m//2:
            log['outcome'] = 'not_local'; continue
        old, new = _times(s, 'previous'), _times(s, 'received')
        reference = new
        reference_plan, reference_reserves = q['incumbent'], q['reserve_paths']
        if anchor == 'fixed_sequence':
            from recovery.static_paths import fastest_static_plan
            reference_plan, reference_reserves = fastest_static_plan(s, axis_library(s), q['incumbent'],
                scope_family(s, 1, affected['uavs'])[0].releases['P'])
            reference = _times(s, 'received', plan=reference_plan, reserves=reference_reserves)
        tau = max(old.values())
        log['max_reference_delay'] = str(max(reference[i]-old[i] for i in old))
        # A delay of 0.1% of the reference mission time remains many orders
        # above decimal serialization error, including for fast UAVs.
        delayed = sorted(i for i in old if reference[i]-old[i] >= Fraction(1, 1000)*max(Fraction(1, 10), tau))
        if not delayed:
            log['outcome'] = 'no_material_delivery_delay'; continue
        critical = rng.choice(delayed)
        delta = reference[critical]-old[critical]
        before, after = diagnostic.previous, diagnostic.received
        slack = [.05, .2, .5][seed % 3]
        _resource_reference(q, before, after, slack)
        for t in q['mission']['tasks']:
            t['deadline_h'] = _ceil_decimal(max(old[t['id']], new[t['id']])+Fraction(str(slack))*tau)
        cases = []
        for side, deadline in [('below', _floor_decimal(reference[critical]-eps*delta)),
                               ('above', _ceil_decimal(reference[critical]+eps*delta))]:
            r = deepcopy(q); r['benchmark_id'] = base+'_'+side
            next(t for t in r['mission']['tasks'] if t['id'] == critical)['deadline_h'] = deadline
            scenario = Scenario(r)
            cases.append(Case(r['benchmark_id'], scenario, axis_library(scenario)))
        lower, upper = cases
        check = verify_local_witness(upper.scenario, upper.library, reference_plan, reference_reserves,
                                     0 if anchor=='incumbent' else 1)
        if (not all(previous_premise(c.scenario)['exact_feasible'] for c in cases)
                or not check['accepted'] or not check['exact'] or physical_certificate(lower.scenario, 0) is None):
            log['outcome'] = 'boundary_validation_failed'; continue
        log['outcome'] = 'accepted'
        meta.update(status='accepted', critical_task=critical, previous_delivery=str(old[critical]),
                    updated_delivery=str(new[critical]), boundary_delivery=str(reference[critical]), delay=str(delta), resource_slack=slack,
                    affected_count=affected['count'], geometry_seed=geometry_seed)
        return tuple(cases), meta
    return (), meta


def summarize_near(path):
    """Keep the constructed retention controls out of escalation prevalence."""
    from collections import Counter
    import json
    from pathlib import Path
    from .analysis import load_records, summarize, _stats
    from .records import verify_archive
    from recovery.local_search import digest
    path = Path(path)
    manifest = json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    verify_archive(path/'source.zip', manifest['source_files'])
    records = load_records(path)
    ledgers = [json.loads(p.read_text(encoding='utf-8')) for p in sorted((path/'sampling').glob('*.json'))]
    for item in ledgers:
        if (item['run_hash'] != manifest['run_hash'] or item['binding_hash'] != digest(
                {k:v for k,v in item.items() if k not in ('binding_hash', 'generation_s')})):
            raise ValueError('invalid sampling ledger')
        observed = [r for r in records if r['request']['metadata']['base_mission'] == item['metadata']['base_mission']]
        if sorted(r['request']['scenario_hash'] for r in observed) != sorted(item['scenario_hashes']):
            raise ValueError('incomplete or extra paired records')
    if sum(len(i['scenario_hashes']) for i in ledgers) != len(records):
        raise ValueError('records missing a sampling ledger')
    config = manifest['config']
    expected = len(config['sizes'])*len(config['families'])*len(config['seeds'])*len(config.get('anchors',['incumbent']))
    if len(ledgers) != expected: raise ValueError('sampling ledger is incomplete')
    result = dict(population='conditional local adverse-wind deadline boundaries',
                  sampling=dict(requested_bases=expected, accepted_bases=sum(i['metadata']['status']=='accepted' for i in ledgers),
                                failed_bases=sum(i['metadata']['status']!='accepted' for i in ledgers),
                                attempt_outcomes=dict(Counter(a['outcome'] for i in ledgers for a in i['metadata']['attempts'])),
                                attempts_per_slot=_stats([len(i['metadata']['attempts']) for i in ledgers]),
                                generation_s=sum(i['generation_s'] for i in ledgers)),
                  interpretation='Above/below pairing conditions on a declared incumbent or represented fixed-sequence reference. Report each anchor and side separately; these are conditional stress-population frequencies.')
    def panel_summary(subset):
        value = summarize(subset)
        value.pop('represented_certified_frequency_cluster_bootstrap_95', None)
        value['inference_note'] = ('Descriptive counts and identification intervals for this balanced stress panel. '
            'Random draws are shared across some strata; no independence-based sampling confidence interval is reported. '
            'Generation failures are separate and unknown minima remain in each accepted-case denominator.')
        return value
    for side in ('below', 'above'):
        subset = [r for r in records if r['request']['metadata']['side'] == side]
        result[side] = panel_summary(subset)
        result[side]['returned_witness_levels'] = dict(Counter(str(r['result']['witness']['validation']['level'])
            if r['result']['witness'] else 'none' for r in subset))
        result[side]['effort_total_s'] = {key:sum(r['timing'][key] for r in subset) for key in ('solve_s','audit_s')}
        result[side]['effort_components_s'] = {key:_stats([r['result']['effort'][key] for r in subset])
            for key in ('setup_s','static_screen_s','proposal_s','represented_proof_s','physical_proof_s')}
    result['strata'] = {}
    for anchor in config.get('anchors',['incumbent']):
        for side in ('below','above'):
            subset = [r for r in records if r['request']['metadata'].get('anchor','incumbent')==anchor
                      and r['request']['metadata']['side']==side]
            result['strata'][anchor+'_'+side] = panel_summary(subset)
    return result
