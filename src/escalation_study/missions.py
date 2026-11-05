"""P1 base missions: one local wind update shared by every slack/strength variant.

Selection uses previous-forecast quantities, exposure and locality only; no
recovery label is queried. A failed generation slot keeps its complete ledger.
"""
from copy import deepcopy
from fractions import Fraction
import math
import random

from continuous.physics import split_static_path, stationary_duration
from continuous.validation import previous_premise
from continuous_benchmark.cases import _deliveries, _decimal
from env.fixed_plan import evaluate_plan
from env.local_scope import affected_uavs
from env.plan import active_count
from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update
from final_benchmark.controlled import make_plan
from final_benchmark.generators import random_pair
from recovery.local_search import digest

STRENGTHS = ('1/5', '2/5', '3/5')
SLACKS = ('2/5', '1/5', '1/10', '1/20', '1/50')
SPEEDS = (1, 1.275, 1.56)
DIRECTIONS = ((1, 0), (-1, 0), (0, 1), (0, -1),
              *(('3/5' if sx > 0 else '-3/5', '4/5' if sy > 0 else '-4/5') for sx in (1, -1) for sy in (1, -1)),
              *(('4/5' if sx > 0 else '-4/5', '3/5' if sy > 0 else '-3/5') for sx in (1, -1) for sy in (1, -1)))


def mission_id(n, m, family, seed):
    return f'P1_{n}_{m}_{family}_{seed}'


def variant_id(mission, strength_index, slack_index):
    return f'{mission}_r{strength_index}_s{slack_index}'


def _decimal_vector(vector):
    values = []
    for v in vector:
        number = float(v)
        if Fraction(str(number)) != v:
            raise ValueError('wind component is not a terminating decimal')
        values.append(number)
    return values


def _geometry(n, m, family, geometry_seed, rng):
    """Zero-wind straight-leg incumbent on the random_pair task geometry."""
    p = random_pair(n, m, family, geometry_seed)[0].scenario.to_dict()
    p['mission']['horizon_h'] = 1000
    for t in p['mission']['tasks']:
        t['deadline_h'] = None
    speeds = list(SPEEDS)
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
    return p


def battery_reference(p, slack):
    """Capacity from the previous forecast only: requirement plus slack x scale.

    With slack 3/2 the capacity is at least reserve + 5/2 x (requirement - reserve).
    An update with |w| <= 3/5 v_min lengthens every flight by at most
    v/(v-|w|) <= 5/2, so the incumbent sequence stays energy-feasible.
    """
    before = evaluate_plan(Scenario(p), projection='previous')
    if before.status != 'feasible':
        raise ValueError('reference mission not feasible: '+str(before.violations))
    requirements = {}
    for u in p['mission']['vehicles']:
        uid, cap, reserve = u['id'], Fraction(str(u['battery_capacity_wh'])), Fraction(str(u['reserve_wh']))
        required = cap-Fraction(str(before.final_states[uid]['battery_wh']))+reserve
        for key, check in before.reserve_checks.items():
            if key.startswith('reserve:'+uid+':'):
                required = max(required, cap-Fraction(str(check['state']['battery_wh']))
                               + Fraction(str(check['energy_wh']))+reserve)
        requirements[uid] = required
    scale = max(Fraction(1), max(requirements.values())
                - min(Fraction(str(u['reserve_wh'])) for u in p['mission']['vehicles']))
    capacities = {}
    for u in p['mission']['vehicles']:
        value = _decimal(requirements[u['id']]+Fraction(slack)*scale, True)
        u['battery_capacity_wh'] = value
        p['state']['fleet'][u['id']]['battery_wh'] = value
        capacities[u['id']] = str(Fraction(str(value)))
    return dict(requirements={k: str(v) for k, v in requirements.items()}, scale=str(scale),
                slack=str(Fraction(slack)), capacities=capacities)


def previous_delivery_times(p):
    """Certified [lower, upper] previous-forecast delivery times per task."""
    return delivery_times(Scenario(p))


def delivery_times(scenario):
    """Certified [lower, upper] incumbent delivery times under the received wind."""
    p = scenario.data
    intervals = {(uid, h): stationary_duration(scenario, uid, path)
                 for uid, r in p['incumbent']['routes'].items()
                 for h, path in enumerate(r['paths'][:active_count(r)], 1)}
    return _deliveries(scenario, p['incumbent'], intervals)


def exposure(scenario, cell_index, wind):
    """Along-track wind on every incumbent leg piece inside the changed cell."""
    rows = []
    for uid, route in sorted(scenario.data['incumbent']['routes'].items()):
        for h, path in enumerate(route['paths'][:active_count(route)], 1):
            for a, b, cell in split_static_path(scenario, path):
                if cell != cell_index:
                    continue
                d = [b[0]-a[0], b[1]-a[1]]
                length = math.hypot(*map(float, d))
                if length:
                    along = float(wind[0]*d[0]+wind[1]*d[1])/length
                    rows.append(dict(uid=uid, slot=h, along_track_kmh=along, length_km=length))
    return rows


def speed_ranks(p):
    speeds = sorted({Fraction(str(u['airspeed_kmh'])) for u in p['mission']['vehicles']}, reverse=True)
    return {u['id']: dict(airspeed_kmh=u['airspeed_kmh'], rank=1+speeds.index(Fraction(str(u['airspeed_kmh']))))
            for u in p['mission']['vehicles']}


def base_mission(n, m, family, seed, *, max_attempts=24, battery_slack='3/2',
                 strengths=STRENGTHS, slacks=SLACKS):
    """Return (variants, ledger). Variants map variant id -> scenario payload."""
    if (n < 1 or m < 3 or family not in ('uniform', 'clustered') or isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int) or max_attempts < 0):
        raise ValueError('invalid P1 generator setting')
    strengths = tuple(Fraction(r) for r in strengths)
    slacks = tuple(Fraction(s) for s in slacks)
    if any(not 0 < r <= Fraction(3, 5) for r in strengths) or any(s <= 0 for s in slacks):
        raise ValueError('invalid strength or slack value')
    if list(slacks) != sorted(slacks, reverse=True):
        raise ValueError('slacks must be ordered from loosest to tightest')
    rng, name = random.Random(seed), mission_id(n, m, family, seed)
    ledger = dict(version='escalation-p1-sampling-v1', status='generation_failed', mission=name, n=n, m=m,
                  family=family, seed=seed, strengths=list(map(str, strengths)), slacks=list(map(str, slacks)),
                  battery_slack=str(Fraction(battery_slack)), locality_limit=m//2,
                  selection_uses_recovery_labels=False, attempts=[])
    for attempt in range(max_attempts):
        if attempt % 12 == 0:
            geometry_seed = seed*100+attempt//12
            p = _geometry(n, m, family, geometry_seed, rng)
            battery = battery_reference(p, Fraction(battery_slack))
            times = previous_delivery_times(p)
            tau = max(hi for _, hi in times.values())
            previous = evaluate_plan(Scenario(p), projection='previous')
            support = sorted({q['cell_id'] for rows in previous.records.values() for r in rows
                              for q in r['wind_queries']})
        cell = rng.choice(support)
        direction = tuple(Fraction(v) for v in rng.choice(DIRECTIONS))
        log = dict(attempt=attempt, geometry_seed=geometry_seed, cell=cell, direction=list(map(str, direction)))
        ledger['attempts'].append(log)
        index = next(i for i, c in enumerate(p['wind']['cells']) if c['id'] == cell)
        v_min = min(Fraction(str(u['airspeed_kmh'])) for u in p['mission']['vehicles'])
        deadlines = {task: [_decimal(hi+s*tau, True) for s in slacks] for task, (_, hi) in sorted(times.items())}
        variants = {}
        for ri, r in enumerate(strengths):
            wind = _decimal_vector(tuple(r*v_min*c for c in direction))
            for si, s in enumerate(slacks):
                q = deepcopy(p)
                q['benchmark_id'] = variant_id(name, ri, si)
                q['wind']['received']['values'][index][0] = wind
                q['wind']['update_support'] = [[cell, 0]]
                for t in q['mission']['tasks']:
                    if t['id'] in deadlines:
                        t['deadline_h'] = deadlines[t['id']][si]
                variants[q['benchmark_id']] = dict(strength_index=ri, slack_index=si, payload=q)
        scenarios = {k: Scenario(v['payload']) for k, v in variants.items()}
        u0 = None
        failure = None
        for k, s in scenarios.items():
            affected = affected_uavs(s, diagnose_wind_update(s))['uavs']
            if u0 is None:
                u0 = affected
                log['affected_count'] = len(u0)
                if not 0 < len(u0) <= m//2:
                    failure = 'not_local'
                    break
            elif affected != u0:
                failure = 'affected_set_varies'
                break
            if not previous_premise(s)['accepted']:
                failure = 'previous_premise_failed'
                break
        if failure:
            log['outcome'] = failure
            continue
        log['outcome'] = 'accepted'
        first = scenarios[variant_id(name, 0, 0)]
        # Certified incumbent delay per strength: a covariate for the analysis, not a selection rule.
        delays = {}
        for ri, r in enumerate(strengths):
            received = delivery_times(scenarios[variant_id(name, ri, 0)])
            delays[str(r)] = [str(max(received[i][0]-times[i][1] for i in times)),
                              str(max(received[i][1]-times[i][0] for i in times))]
        ledger.update(status='accepted', geometry_seed=geometry_seed, cell=cell, cell_index=index,
                      direction=list(map(str, direction)), v_min=str(v_min), affected=u0,
                      battery=battery, tau=str(tau),
                      previous_delivery={t: [str(lo), str(hi)] for t, (lo, hi) in sorted(times.items())},
                      deadlines={t: list(v) for t, v in deadlines.items()},
                      speed_ranks=speed_ranks(p), incumbent_delay=delays,
                      exposure={str(r): exposure(first, index, tuple(r*v_min*c for c in direction))
                                for r in strengths},
                      variants={k: dict(strength=str(strengths[v['strength_index']]),
                                        slack=str(slacks[v['slack_index']]),
                                        strength_index=v['strength_index'], slack_index=v['slack_index'],
                                        scenario_hash=scenarios[k].content_hash())
                                for k, v in variants.items()})
        return {k: s.to_dict() for k, s in scenarios.items()}, ledger
    return {}, ledger


def ledger_hash(ledger, scenarios):
    return digest(dict(ledger=ledger, scenarios=scenarios))
