"""Analytic controls and fresh missions around certified continuous bounds."""
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
import math
import random

from env.fixed_plan import evaluate_plan
from env.local_scope import affected_uavs, scope_family
from env.plan import active_count
from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update
from recovery.linear import rational
from continuous.oracle import ContinuousOracle
from continuous.physics import stationary_duration
from continuous.search import deadline_certificate, verify_deadline_certificate
from continuous.validation import certify_witness, previous_premise
from final_benchmark.controlled import controlled_case, base_payload, make_plan
from final_benchmark.generators import random_pair, axis_plan
from final_benchmark.near_boundary import _resource_reference


@dataclass(frozen=True)
class Case:
    name: str
    scenario: Scenario
    expected: object = None


def controlled_cases():
    result = [Case(c.name, c.scenario, c.expected) for c in
              (controlled_case(name, include_bypass=False) for name in ('C0', 'C1', 'C2', 'C3', 'C4', 'Cinf'))]
    p = base_payload('arbitrary_angle', [('A', [1, 1], 2.1)], [1, 1, 1], alpha=.2)
    p['incumbent'], p['reserve_paths'] = axis_plan(p, {'U1': ['A']})
    result.append(Case(p['benchmark_id'], Scenario(p), 1))
    p = base_payload('analytic_diagonal', [('A', [1, 1], 10)], [1, 1, 1], alpha=0)
    p['wind']['update_support'] = []
    p['incumbent'], p['reserve_paths'] = make_plan(p, {'U1': ['A']})
    result.append(Case(p['benchmark_id'], Scenario(p), 0))
    p = base_payload('constant_headwind', [('A', [1, 0], 3)], [1, 1, 1], alpha=.6)
    p['wind']['received']['values'] = [[[-.6, 0]], [[-.6, 0]]]
    p['wind']['previous']['values'][0][0] = [-.6, 0]
    p['incumbent'], p['reserve_paths'] = make_plan(p, {'U1': ['A']})
    result.append(Case(p['benchmark_id'], Scenario(p), 0))
    p = base_payload('reserve_only', [('A', [1, 0], 3)], [1, 1, 1], alpha=.2)
    p['incumbent'], p['reserve_paths'] = make_plan(p, {'U1': ['A']})
    p['reserve_paths']['U1']['1'] = [[1, 0], [2, 0], [1, 0], [0, 0]]
    for u in p['mission']['vehicles']:
        u['battery_capacity_wh'] = 6
        p['state']['fleet'][u['id']]['battery_wh'] = 6
    result.append(Case(p['benchmark_id'], Scenario(p), 0))
    return tuple(result)


def _deliveries(scenario, plan, leg_intervals):
    tasks = {t['id']: t for t in scenario.data['mission']['tasks']}
    op, times = scenario.data['operations'], {}
    for uid, route in sorted(plan['routes'].items()):
        n = active_count(route)
        lo = hi = rational(scenario.data['mission']['epoch_h'])+(rational(op['preparation_duration_h']) if n else 0)
        for h, site in enumerate(route['stops'][:n], 1):
            left, right = leg_intervals[uid, h]
            lo, hi = lo+left, hi+right
            if site in tasks:
                lo, hi = lo+rational(op['service_duration_h']), hi+rational(op['service_duration_h'])
                if route['deliveries'][h] > 0: times[site] = lo, hi
            elif h < n:
                lo, hi = lo+rational(op['preparation_duration_h']), hi+rational(op['preparation_duration_h'])
    return times


def _decimal(value, upper):
    return (math.ceil if upper else math.floor)(Fraction(value)*10**10)/10**10


def boundary_pair(n, m, family, seed, *, max_attempts=24, offset='1/10', refinements=(2,)):
    if (n < 1 or m < 3 or family not in ('uniform', 'clustered') or isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int) or max_attempts < 0):
        raise ValueError('invalid continuous cohort generator setting')
    eps = Fraction(offset)
    if not 0 < eps < 1: raise ValueError('invalid boundary offset')
    rng, base = random.Random(seed), f'CB_{n}_{m}_{family}_{seed}'
    meta = dict(status='generation_failed', base_mission=base, n=n, m=m, family=family, seed=seed,
                boundary_type='certified_continuous_fixed_sequence', offset=str(eps), refinements=list(refinements),
                locality_limit=m//2, selection_uses_recovery_labels=False, attempts=[])
    for attempt in range(max_attempts):
        if attempt % 12 == 0:
            geometry_seed = seed*100+attempt//12
            p = random_pair(n, m, family, geometry_seed)[0].scenario.to_dict()
            p['mission']['horizon_h'] = 1000
            for t in p['mission']['tasks']: t['deadline_h'] = None
            speeds = [1, 1.275, 1.56]
            rng.shuffle(speeds)
            for j, u in enumerate(p['mission']['vehicles']):
                u.update(airspeed_kmh=speeds[j % 3], battery_capacity_wh=10000)
                p['state']['fleet'][u['id']]['battery_wh'] = 10000
            sequences = {uid: [i for i in r['stops'] if i not in (None, 'DEPOT')]
                         for uid, r in p['incumbent']['routes'].items()}
            p['incumbent'], p['reserve_paths'] = make_plan(p, sequences)
            p['wind'].update(time_knots_h=[0, 1000], speed_bound_kmh=.6, update_support=[])
            for projection in ('previous', 'received'):
                p['wind'][projection].update(values=[[[0, 0]] for _ in p['wind']['cells']],
                    admissible=[[True] for _ in p['wind']['cells']], coverage=['forecast'])
            previous = Scenario(p)
            baseline = evaluate_plan(previous)
            support = sorted({q['cell_id'] for rows in baseline.records.values() for r in rows for q in r['wind_queries']})
            old_intervals = {(uid, h): stationary_duration(previous, uid, path)
                             for uid, r in p['incumbent']['routes'].items()
                             for h, path in enumerate(r['paths'][:active_count(r)], 1)}
            old_times = _deliveries(previous, p['incumbent'], old_intervals)
        q = deepcopy(p)
        cell, axis, sign = rng.choice(support), rng.randrange(2), rng.choice((-1, 1))
        vector = [0, 0]; vector[axis] = sign*.6
        idx = next(i for i, c in enumerate(q['wind']['cells']) if c['id'] == cell)
        q['wind']['received']['values'][idx][0] = vector
        q['wind']['update_support'] = [[cell, 0]]
        scenario = Scenario(q)
        diagnostic = diagnose_wind_update(scenario)
        affected = affected_uavs(scenario, diagnostic)
        log = dict(attempt=attempt, geometry_seed=geometry_seed, cell=cell, wind=vector,
                   affected_count=affected['count'])
        meta['attempts'].append(log)
        if not 0 < affected['count'] <= m//2:
            log['outcome'] = 'not_local'; continue
        oracle = ContinuousOracle(scenario, refinements)
        released = scope_family(scenario, 1, affected['uavs'])[0].releases['P']
        reference_plan, intervals = deepcopy(q['incumbent']), {}
        for uid, route in sorted(reference_plan['routes'].items()):
            for h, path in enumerate(route['paths'][:active_count(route)], 1):
                if f'{uid}:{h}' in released:
                    query = oracle.query(uid, path[0], path[-1], [path])
                    intervals[uid, h] = Fraction(query['lower']), Fraction(query['upper'])
                    route['paths'][h-1] = query['path']
                else: intervals[uid, h] = stationary_duration(scenario, uid, path)
        reference_times = _deliveries(scenario, reference_plan, intervals)
        tau = max(hi for lo, hi in old_times.values())
        delayed = sorted(i for i in old_times if reference_times[i][0]-old_times[i][1] >= Fraction(1, 1000)*max(Fraction(1, 10), tau))
        log['max_certified_delay'] = str(max(reference_times[i][0]-old_times[i][1] for i in old_times))
        if not delayed:
            log['outcome'] = 'no_material_certified_delay'; continue
        critical = rng.choice(delayed)
        lower, upper = reference_times[critical]
        delta = lower-old_times[critical][1]
        reference_reserves = deepcopy(q['reserve_paths'])
        before = evaluate_plan(scenario, projection='previous')
        after = evaluate_plan(scenario, reference_plan, reserve_paths=reference_reserves)
        slack = [.05, .2, .5][seed % 3]
        _resource_reference(q, before, after, slack)
        cases = []
        for side, deadline in (('below', _decimal(lower-eps*delta, False)), ('above', _decimal(upper+eps*delta, True))):
            r = deepcopy(q); r['benchmark_id'] = base+'_'+side
            next(t for t in r['mission']['tasks'] if t['id'] == critical)['deadline_h'] = deadline
            cases.append(Case(r['benchmark_id'], Scenario(r)))
        below, above = cases
        certificate = deadline_certificate(below.scenario, 1, oracle)
        check = certify_witness(above.scenario, reference_plan, reference_reserves, 1)
        if (not all(previous_premise(c.scenario)['accepted'] for c in cases) or not check['accepted']
                or certificate is None or not verify_deadline_certificate(below.scenario, certificate)):
            log['outcome'] = 'boundary_validation_failed'; continue
        log['outcome'] = 'accepted'
        meta.update(status='accepted', critical_task=critical, previous_upper=str(old_times[critical][1]),
                    updated_lower=str(lower), updated_upper=str(upper), delay=str(delta),
                    reference_gap=str(upper-lower), resource_slack=slack, affected_count=affected['count'],
                    boundary_certificate=certificate, reference_plan=reference_plan,
                    reference_reserves=reference_reserves, upper_validation=check, geometry_seed=geometry_seed)
        return tuple(cases), meta
    return (), meta
