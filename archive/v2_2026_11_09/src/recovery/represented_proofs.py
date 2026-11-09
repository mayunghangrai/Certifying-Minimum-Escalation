"""Optimistic deadline/order proofs confined to a stationary path library.

All represented paths become graph edges. Shortest walks allow unlimited stops,
ignore intermediate service and recharge time, and may use any task location.
Thus they lower-bound every permitted represented route, including repeated
visits. Capacity, energy, and most commitments are relaxed. A failed relaxation
is useful; a successful one is not a feasible recovery witness.
"""
from fractions import Fraction
from itertools import permutations, product

from env.local_scope import scope_family, affected_uavs
from env.wind_dependency import diagnose_wind_update
from .linear import rational
from .physics import flight_duration, UnsupportedArithmetic, InadmissiblePath
from .static_paths import _guard


def _distances(scenario, library):
    d = scenario.data
    points = sorted({p for path in library.nominal for p in (path[0], path[-1])})
    result = {}
    for uid in sorted(d['state']['fleet']):
        dist = {(a,a):Fraction(0) for a in points}
        for path in library.nominal:
            dt = flight_duration(scenario, uid, path, d['mission']['epoch_h'], exact=True)
            if dt is None: continue
            edge = path[0], path[-1]
            if edge not in dist or dt < dist[edge]: dist[edge] = dt
        for middle in points:
            for a in points:
                if (a,middle) not in dist: continue
                for b in points:
                    if (middle,b) not in dist: continue
                    value = dist[a,middle]+dist[middle,b]
                    if (a,b) not in dist or value < dist[a,b]: dist[a,b] = value
        result[uid] = dist
    return result


def represented_deadline_certificate(scenario, library, excluded_through):
    if isinstance(excluded_through,bool) or excluded_through not in (2,3,4): raise ValueError('invalid represented proof scope')
    library.validate(scenario)
    if _guard(scenario) is not None: return None
    d = scenario.data
    tasks = {t['id']:t for t in d['mission']['tasks'] if rational(t['mandatory']) > rational(d['state']['cumulative_delivered'][t['id']])}
    ids = sorted(tasks)
    try:
        dist = _distances(scenario, library)
    except (UnsupportedArithmetic, InadmissiblePath):
        return None
    cache = {}

    def order_failures(uid, assigned):
        key = uid, assigned
        if key in cache: return cache[key]
        if len(assigned)>5: return None  # bounded proof effort, never an exclusion
        failures = []
        for order in permutations(assigned):
            time = rational(d['mission']['epoch_h'])
            if order: time += rational(d['operations']['preparation_duration_h'])
            point = tuple(d['mission']['depot_xy'])
            failure = None
            for i in order:
                end = tuple(tasks[i]['position_xy'])
                dt = dist[uid].get((point,end))
                if dt is None:
                    failure = dict(order=list(order),task=i,reason='unreachable_in_relaxed_graph'); break
                time += dt+rational(d['operations']['service_duration_h'])
                deadline = rational(tasks[i]['deadline_h'] if tasks[i]['deadline_h'] is not None else d['mission']['horizon_h'])
                if time>deadline:
                    failure = dict(order=list(order),task=i,earliest=str(time),deadline=str(deadline)); break
                point = end
            if failure is None:
                cache[key] = None; return None
            failures.append(failure)
        cache[key] = failures
        return failures

    u0 = affected_uavs(scenario, diagnose_wind_update(scenario))['uavs']
    patches, examined = [], 0
    for patch in scope_family(scenario, excluded_through, u0):
        allowed = [list(patch.participants) if i in patch.releases['A'] else
                   [d['incumbent']['assignment'][i]] if d['incumbent']['assignment'][i] is not None else [] for i in ids]
        failures = []
        for owners in product(*allowed):
            examined += 1
            if examined>512: return None
            failure = None
            for uid in sorted(d['state']['fleet']):
                assigned = tuple(i for i,owner in zip(ids,owners) if owner==uid)
                rejected = order_failures(uid, assigned)
                if rejected is not None:
                    failure = dict(assignment=dict(zip(ids,owners)),blocked_uav=uid,order_failures=rejected); break
            if failure is None: return None
            failures.append(failure)
        patches.append(dict(patch=patch.to_dict(),allowed_owners=dict(zip(ids,allowed)),assignment_failures=failures))
    return dict(kind='represented_graph_deadline_relaxation_v1',domain='represented',
                scenario_hash=scenario.content_hash(),library_hash=library.content_hash(),
                excluded_through=excluded_through,patches=patches)


def verify_represented_certificate(scenario, library, certificate):
    try:
        if certificate['kind']!='represented_graph_deadline_relaxation_v1' or certificate['domain']!='represented': return False
        expected = represented_deadline_certificate(scenario, library, certificate['excluded_through'])
        return expected is not None and expected == certificate
    except (KeyError,ValueError,TypeError,ArithmeticError):
        return False
