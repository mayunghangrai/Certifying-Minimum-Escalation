"""Physically grounded case study 2: off-centre depot, 6 UAVs x 4 tasks, multiple sorties.

docs/PHYSICAL_CASE_STUDY_2_DESIGN_2026_10_21.md (decisions: both profiles, both anchors, update
at dispatch only, 6 x 4). Task positions, demands, urgency classes and depot stock come from FS
mission FS_6x4_medium_ample_uniform_76101; the aircraft constants are case 1's. The incumbent,
deadlines and wind updates follow fixed rules that read no recovery result.
"""
from copy import deepcopy
from fractions import Fraction
import math

from continuous_benchmark.cases import _decimal
from env.scenario import Scenario
from escalation_study.missions import delivery_times
from . import physical_case as pc

SOURCE = 'FS_6x4_medium_ample_uniform_76101'
SOURCE_VARIANT = SOURCE+'_r1_t0'

DEPOT_XY = [-0.95, -0.95]           # stadium on the dry south-west edge, off the 100 m task grid
UNIT_KG = 10                        # demands 5, 10, 15 kg: inside the 5-30 kg winch range
SORTIE_UNITS = Fraction(pc.PAYLOAD_KG, UNIT_KG)
CLASS_ORDER = (1, 10, 50)           # urgent, essential, routine
MINUTE = Fraction(1, 60)
PROFILES = {'P15': {1: 15, 10: 30, 50: 60}, 'P10': {1: 10, 10: 20, 50: 40}}    # targets, minutes
ANCHORS = {'A1': (3, 3), 'A2': (1, 1)}                                          # C33, C11
COVERAGES = ('K1', 'K2', 'K3')


def _cell(x, y):
    return 4*x+y                    # cells are listed x-major (C00, C01, ..., C33)


def coverage_cells(anchor, coverage):
    """The anchor cell, or the 2 x 2 / 3 x 3 block grown toward the grid centre."""
    x, y = ANCHORS[anchor]
    if coverage == 'K1':
        return (_cell(x, y),)
    if coverage == 'K2':
        xs, ys = ((v, v+1) if v <= 1 else (v-1, v) for v in (x, y))
    else:
        xs, ys = (range(min(max(v-1, 0), 1), min(max(v-1, 0), 1)+3) for v in (x, y))
    return tuple(sorted(_cell(a, b) for a in xs for b in ys))


def sectors(tasks, m):
    """Contiguous blocks of equal size in order of bearing from the depot."""
    dx, dy = DEPOT_XY

    def key(t):
        x, y = t['position_xy']
        return round(math.atan2(y-dy, x-dx), 12), math.hypot(x-dx, y-dy), t['id']
    ordered = sorted(tasks, key=key)
    k = len(ordered)//m
    return [ordered[j*k:(j+1)*k] for j in range(m)]


def visiting_order(block, classes):
    """Urgent, then essential, then routine; nearest neighbour within each class."""
    point, order = DEPOT_XY, []
    for c in CLASS_ORDER:
        left = [t for t in block if classes[t['id']] == c]
        while left:
            t = min(left, key=lambda t: (math.dist(point, t['position_xy']), t['id']))
            order.append(t)
            left.remove(t)
            point = t['position_xy']
    return order


def dispatcher_plan(p, classes):
    """(incumbent, reserve paths): sectors, priority order, a depot stop before an overload."""
    tasks, vehicles = p['mission']['tasks'], p['mission']['vehicles']
    plan, reserves = dict(assignment={t['id']: None for t in tasks}, routes={}), {}
    for u, block in zip(vehicles, sectors(tasks, len(vehicles))):
        uid, bound = u['id'], u['slot_bound']
        sites, sortie_loads, onboard = [], [Fraction(0)], Fraction(0)
        for t in visiting_order(block, classes):
            demand = Fraction(str(t['demand']))
            if onboard+demand > SORTIE_UNITS:
                sites.append('DEPOT')
                sortie_loads.append(Fraction(0))
                onboard = Fraction(0)
            sites.append(t)
            sortie_loads[-1] += demand
            onboard += demand
            plan['assignment'][t['id']] = uid
        sites.append('DEPOT')
        if len(sites) > bound:
            raise ValueError('route exceeds the slot bound')
        positions = [DEPOT_XY]+[DEPOT_XY if s == 'DEPOT' else s['position_xy'] for s in sites]
        loads, deliveries, sortie = [float(sortie_loads[0])], [0], 0
        for h, s in enumerate(sites, 1):
            if s == 'DEPOT':
                sortie += 1
                loads.append(float(sortie_loads[sortie]) if h < len(sites) else 0)
                deliveries.append(0)
            else:
                loads.append(0)
                deliveries.append(s['demand'])
        plan['routes'][uid] = dict(stops=[s if s == 'DEPOT' else s['id'] for s in sites]+[None]*(bound-len(sites)),
                                   paths=[[a, b] for a, b in zip(positions, positions[1:])]
                                   + [[DEPOT_XY]]*(bound-len(sites)),
                                   loads=loads+[0]*(bound-len(sites)), deliveries=deliveries+[0]*(bound-len(sites)))
        reserves[uid] = {'initial': [DEPOT_XY]}
        for h, s in enumerate(sites, 1):
            if s != 'DEPOT':
                reserves[uid][str(h)] = [s['position_xy'], DEPOT_XY]
    return plan, reserves


def nominal_mission(source_payload, classes):
    """Case 1's FlyCart 30 physics, the off-centre depot, the 10 kg unit and the dispatcher plan."""
    p = pc.nominal_mission(source_payload)
    p['benchmark_id'] = 'PHY2_FC30'
    p['mission']['depot_xy'] = list(DEPOT_XY)
    p['mission']['commodity_unit_mass_kg'] = UNIT_KG
    for t in p['mission']['tasks']:
        t['deadline_h'] = None
    for s in p['state']['fleet'].values():
        s['position_xy'] = list(DEPOT_XY)
    p['incumbent'], p['reserve_paths'] = dispatcher_plan(p, classes)
    return Scenario(p).to_dict()


def with_profile(p, classes, profile):
    """Targets by class; a task whose nominal arrival + 1 min passes its target gets the promised
    time: the arrival rounded up to a whole minute, plus 1 min. Returns (payload, fallbacks)."""
    arrival = delivery_times(Scenario(p))
    q, fallbacks = deepcopy(p), {}
    q['benchmark_id'] = f'PHY2_FC30_{profile}'
    for t in q['mission']['tasks']:
        target = PROFILES[profile][classes[t['id']]]*MINUTE
        hi = arrival[t['id']][1]
        due = target
        if hi+MINUTE > target:
            due = math.ceil(hi/MINUTE)*MINUTE+MINUTE
            fallbacks[t['id']] = dict(target_min=float(target/MINUTE), nominal_arrival_min=float(hi/MINUTE),
                                      promised_min=float(due/MINUTE))
        t['deadline_h'] = _decimal(due, True)
    return Scenario(q).to_dict(), fallbacks


def conditions():
    return [(pr, a, c, d, s) for pr in PROFILES for a in ANCHORS for c in COVERAGES
            for d in pc.DIRECTIONS for s in pc.STRENGTHS_MS]


def condition_id(profile, anchor, coverage, direction, strength):
    return f'PHY2_{profile}_{anchor}_{coverage}_{direction}_{strength}ms'


def apply_update(p, anchor, coverage, direction, strength, *, profile):
    q = deepcopy(p)
    q['benchmark_id'] = condition_id(profile, anchor, coverage, direction, strength)
    vector = [float(Fraction(strength)*pc.KMH*c) for c in pc.DIRECTIONS[direction]]
    cells = coverage_cells(anchor, coverage)
    for c in cells:
        q['wind']['received']['values'][c][0] = vector
    q['wind']['update_support'] = [[q['wind']['cells'][c]['id'], 0] for c in cells]
    return Scenario(q).to_dict()


def smoke_control(p):
    """A declared update on C33 with zero change: must certify Level 0 and replay."""
    q = deepcopy(p)
    q['benchmark_id'] = 'PHY2_SMOKE_zero_change'
    q['wind']['update_support'] = [[q['wind']['cells'][_cell(3, 3)]['id'], 0]]
    return Scenario(q).to_dict()


def nominal_report(p):
    """Sorties, loads, arrivals, margins and battery at depot arrivals under the previous forecast."""
    from env.fixed_plan import evaluate_plan
    s = Scenario(p)
    result = evaluate_plan(s, projection='previous')
    due = {t['id']: t['deadline_h'] for t in p['mission']['tasks']}
    uavs = {}
    for uid, route in p['incumbent']['routes'].items():
        stops = [x for x in route['stops'] if x is not None]
        records = result.records[uid][1:]
        uavs[uid] = dict(
            stops=stops, sorties=stops.count('DEPOT'),
            sortie_loads=[route['loads'][0]]+[route['loads'][h] for h, x in enumerate(stops[:-1], 1) if x == 'DEPOT'],
            arrivals_min={r['site']: round(r['delivery_h']*60, 3) for r in records if r['site'] != 'DEPOT'},
            margins_min={r['site']: round((due[r['site']]-r['delivery_h'])*60, 3) for r in records if r['site'] != 'DEPOT'},
            battery_at_depot_wh=[round(r['battery_before'], 1) for r in records if r['site'] == 'DEPOT'],
            back_min=round(result.final_states[uid]['time_h']*60, 3))
    return dict(status=result.status, violations=list(result.violations), uavs=uavs,
                min_reserve_margin_wh=min(v['margin_wh'] for v in result.reserve_checks.values()
                                          if v.get('margin_wh') is not None))


def plan_battery_margin(payload, witness):
    """Smallest reserve margin (Wh) of a returned plan under the received wind."""
    from env.fixed_plan import evaluate_plan
    result = evaluate_plan(Scenario(payload), witness['plan'], projection='received',
                           reserve_paths=witness['reserve_paths'])
    margins = [v['margin_wh'] for v in result.reserve_checks.values() if v.get('margin_wh') is not None]
    return min(margins) if margins else None
