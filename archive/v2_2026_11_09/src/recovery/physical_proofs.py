"""Independent necessary-condition proofs over all continuous flight paths.

These deliberately optimistic relaxations ignore energy, capacity, reserve paths,
optional visits and most commitments. Failure of a relaxation is an exclusion;
success proves nothing. No finite path-library failure enters this module.
"""
from fractions import Fraction
from itertools import permutations, product

from env.local_scope import scope_family, affected_uavs
from env.wind_dependency import diagnose_wind_update
from .linear import rational
from .physics import flight_duration, UnsupportedArithmetic, InadmissiblePath


def _axis_bound(scenario,uid,start,end,axis):
    """Integrate a global upper bound on signed ground velocity in each slab.

    Every path must cross each intervening slab. A cell's bounding box may
    over-cover the slab. Take the maximum over those cells and every time bin
    before the latest deadline of a required delivery. Any feasible prefix
    delivering all required quantities must finish by that time. If a required
    delivery has no deadline, use the mission horizon.
    """
    a,b = rational(start[axis]),rational(end[axis])
    if a == b: return Fraction(0)
    sign = 1 if b>a else -1
    lo,hi = sorted((a,b))
    wind = scenario.data['wind']
    data = scenario.data
    deadlines = [rational(t['deadline_h'] if t['deadline_h'] is not None else data['mission']['horizon_h'])
                 for t in data['mission']['tasks']
                 if rational(t['mandatory'])>rational(data['state']['cumulative_delivered'][t['id']])
                 or any(t['id']==stop and route['deliveries'][h]>0
                        for route in data['incumbent']['routes'].values()
                        for h,stop in enumerate(route['stops'],1))]
    ceiling = max(deadlines,default=rational(data['mission']['horizon_h']))
    speed = rational(next(u['airspeed_kmh'] for u in scenario.data['mission']['vehicles'] if u['id']==uid))
    boxes = [(min(rational(p[axis]) for p in c['polygon_xy']),
              max(rational(p[axis]) for p in c['polygon_xy'])) for c in wind['cells']]
    cuts = sorted({lo,hi,*[x for box in boxes for x in box if lo<x<hi]})
    time = Fraction(0)
    for left,right in zip(cuts,cuts[1:]):
        cells = [r for r,(l,h) in enumerate(boxes) if l<right and h>left]
        if not cells: raise UnsupportedArithmetic('uncovered velocity slab')
        velocity = speed+max(sign*rational(w[axis]) for r in cells
                            for j,w in enumerate(wind['received']['values'][r])
                            if rational(wind['time_knots_h'][j])<ceiling)
        if velocity <= 0: raise UnsupportedArithmetic('nonpositive optimistic velocity')
        time += (right-left)/velocity
    return time


def travel_lower_bound(scenario,uid,start,end):
    return max(_axis_bound(scenario,uid,start,end,j) for j in (0,1))


def _fixed_deadline_failure(scenario,level):
    data = scenario.data
    tasks = {t['id']:t for t in data['mission']['tasks']}
    op = data['operations']
    for uid,route in sorted(data['incumbent']['routes'].items()):
        time = rational(data['mission']['epoch_h'])
        point = data['mission']['depot_xy']
        if route['stops'][0] is not None:
            time += rational(op['preparation_duration_h'])
        for h,site in enumerate(route['stops'],1):
            if site is None: break
            end = data['mission']['depot_xy'] if site=='DEPOT' else tasks[site]['position_xy']
            if level == 0:
                try:
                    dt = flight_duration(scenario,uid,route['paths'][h-1],time,exact=True)
                except InadmissiblePath:
                    return dict(kind='fixed_closed_path',uav=uid,slot=h)
                if dt is None:
                    return dict(kind='fixed_horizon',uav=uid,slot=h)
            else:
                dt = travel_lower_bound(scenario,uid,point,end)
            time += dt
            if site != 'DEPOT':
                time += rational(op['service_duration_h'])
                deadline = tasks[site]['deadline_h']
                if route['deliveries'][h] > 0 and deadline is not None and time > rational(deadline):
                    return dict(kind='fixed_delivery_deadline',uav=uid,slot=h,task=site,
                                earliest=str(time),deadline=str(rational(deadline)))
            elif h < len(route['stops']) and route['stops'][h] is not None:
                time += rational(op['preparation_duration_h'])
            point = end
    return None


def _orders_failure(scenario,uid,ids,tasks):
    op = scenario.data['operations']
    failures = []
    for order in permutations(ids):
        time = rational(scenario.data['mission']['epoch_h'])
        point = scenario.data['mission']['depot_xy']
        if order: time += rational(op['preparation_duration_h'])
        failed = None
        for i in order:
            time += travel_lower_bound(scenario,uid,point,tasks[i]['position_xy'])
            time += rational(op['service_duration_h'])
            deadline = tasks[i]['deadline_h']
            if deadline is not None and time > rational(deadline):
                failed = dict(order=list(order),task=i,earliest=str(time),deadline=str(rational(deadline)))
                break
            point = tasks[i]['position_xy']
        if failed is None:
            return None
        failures.append(failed)
    return failures


def physical_certificate(scenario,excluded_through,*,max_tasks=6,max_assignments=20000):
    """Return a proof only if every optimistic assignment/order is excluded."""
    if isinstance(excluded_through,bool) or excluded_through not in range(5):
        raise ValueError('invalid excluded scope')
    data = scenario.data
    # This proof's theorem has explicit, intentionally narrow applicability.
    if (data['schema_version'] != 'wind-benchmark-v2'
            or 'missing' in data['wind']['received']['coverage']
            or any(s['mode']!='idle' or tuple(s['position_xy'])!=tuple(data['mission']['depot_xy'])
                   for s in data['state']['fleet'].values())):
        return None
    try:
        body = None
        if excluded_through <= 1:
            failure = _fixed_deadline_failure(scenario,excluded_through)
            if failure is None: return None
            body = dict(fixed_failure=failure)
        else:
            tasks = {t['id']:t for t in data['mission']['tasks']
                     if rational(t['mandatory'])>rational(data['state']['cumulative_delivered'][t['id']])}
            if len(tasks)>max_tasks: return None
            diagnostic = diagnose_wind_update(scenario)
            u0 = affected_uavs(scenario,diagnostic)['uavs']
            patch_proofs = []
            cache, examined = {},0
            for patch in scope_family(scenario,excluded_through,u0):
                ids = sorted(tasks)
                allowed = [list(patch.participants) if i in patch.releases['A'] else
                           [data['incumbent']['assignment'][i]] if data['incumbent']['assignment'][i] is not None else []
                           for i in ids]
                rejected = []
                for owners in product(*allowed):
                    examined += 1
                    if examined > max_assignments: return None
                    failure = None
                    for uid in sorted(data['state']['fleet']):
                        assigned = tuple(i for i,u in zip(ids,owners) if u==uid)
                        key = uid,assigned
                        if key not in cache:
                            cache[key] = _orders_failure(scenario,uid,assigned,tasks)
                        if cache[key] is not None:
                            failure = dict(assignment=dict(zip(ids,owners)),blocked_uav=uid,
                                           order_failures=cache[key])
                            break
                    if failure is None: return None
                    rejected.append(failure)
                patch_proofs.append(dict(patch=patch.to_dict(),allowed_owners=dict(zip(ids,allowed)),
                                         assignment_failures=rejected))
            body = dict(patches=patch_proofs)
        return dict(kind='all_path_deadline_relaxation_v1',scenario_hash=scenario.content_hash(),
                    excluded_through=excluded_through,**body)
    except (UnsupportedArithmetic,ArithmeticError):
        return None


def verify_physical_certificate(scenario,certificate):
    """Rebuild the necessary-condition proof using rational physical bounds.

    This checker does not call the recovery search, finite path enumeration,
    numerical simulator feasibility flags, or an LP solver.
    """
    try:
        if (certificate['kind']!='all_path_deadline_relaxation_v1'
                or certificate['scenario_hash']!=scenario.content_hash()): return False
        expected = physical_certificate(scenario,certificate['excluded_through'])
        return expected is not None and certificate == expected
    except (KeyError,ValueError,TypeError,ArithmeticError):
        return False
