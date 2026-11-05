"""E1 in-flight snapshots: execute the incumbent under the previous wind to t.

Event times use certified rational intervals for the zero-wind straight legs.
A snapshot that finds a UAV mid-service or mid-preparation moves to the end of
that operation (D3). Positions are rounded to a 1e-9 km grid and batteries down
to 1e-9 Wh; payload, stock and deliveries stay exact. The previous premise is
re-certified at the snapshot, so rounding can reject a snapshot but never admit
an infeasible one. D1: an airborne UAV keeps its destination (S and, for a task,
A committed); the rest of its current leg stays a released path. D1' (``rule='D1p'``)
adds no commitment: the level masks alone decide what an airborne UAV may change.
"""
from copy import deepcopy
from fractions import Fraction
import math

from continuous.physics import stationary_duration
from env.plan import active_count
from env.scenario import Scenario
from recovery.linear import rational

GRID = Fraction(1, 10**9)
NEAR = Fraction(1, 10**6)


def _down(value, grid=GRID):
    return Fraction(math.floor(value/grid))*grid


def _round(value, grid=GRID):
    return Fraction(math.floor(value/grid+Fraction(1, 2)))*grid


def _up(value, grid=GRID):
    return Fraction(math.ceil(value/grid))*grid


def _number(value):
    """A rational on the decimal grid as a JSON float that round-trips exactly."""
    number = float(value)
    if Fraction(str(number)) != value:
        raise ValueError('snapshot value is not representable as a short decimal')
    return number


def timeline(scenario):
    """Per UAV: ordered events with [lower, upper] times under the previous wind.

    Each entry is (kind, slot, start interval, end interval), kind in
    {'prepare', 'fly', 'service', 'idle'}. The scenario must start at idle depot origins.
    """
    d = scenario.data
    op = d['operations']
    prep, service = rational(op['preparation_duration_h']), rational(op['service_duration_h'])
    epoch = rational(d['mission']['epoch_h'])
    out = {}
    for uid, route in sorted(d['incumbent']['routes'].items()):
        n = active_count(route)
        events = []
        lo = hi = epoch
        if n:
            events.append(('prepare', 0, (lo, hi), (lo+prep, hi+prep)))
            lo, hi = lo+prep, hi+prep
        for h, path in enumerate(route['paths'][:n], 1):
            a, b = stationary_duration(scenario, uid, path)
            events.append(('fly', h, (lo, hi), (lo+a, hi+b)))
            lo, hi = lo+a, hi+b
            site = route['stops'][h-1]
            if site != 'DEPOT':
                events.append(('service', h, (lo, hi), (lo+service, hi+service)))
                lo, hi = lo+service, hi+service
            elif h < n:
                events.append(('prepare', h, (lo, hi), (lo+prep, hi+prep)))
                lo, hi = lo+prep, hi+prep
        events.append(('idle', n, (lo, hi), None))
        out[uid] = events
    return out


def phase(events, t):
    """The event containing t, or None when t is within an interval boundary."""
    for event in events:
        kind, _, start, end = event
        if t < start[0]:
            return None
        if end is None:
            return event if t >= start[1] else None
        if start[1] <= t < end[0]:
            return event
        if end[0] <= t < end[1] or start[0] <= t < start[1]:
            return None
    return None


def snapshot_time(scenario, target):
    """Earliest time >= target with every UAV airborne or finished (D3)."""
    events = timeline(scenario)
    t = _up(target)
    for _ in range(1000):
        moved = False
        for uid, items in events.items():
            current = phase(items, t)
            if current is None:
                raise ValueError('snapshot time falls inside an event-time interval')
            kind, _, start, end = current
            # Ground operations, and flights about to land, end the snapshot later.
            if kind in ('prepare', 'service') or (kind == 'fly' and end[1]-t < NEAR):
                following = items[items.index(current)+1] if kind == 'fly' else current
                stop_end = following[3] if following[3] is not None else following[2]
                t = _up(stop_end[1]+GRID)
                moved = True
        if not moved:
            return t, events
    raise ValueError('snapshot time did not settle')


def build_snapshot(payload, target_fraction, *, received_wind, rule='D1'):
    """Return (snapshot payload, provenance) for a P1 variant payload.

    ``received_wind`` = (cell index, wind vector) of the update applied at t*.
    ``rule`` is 'D1' (an airborne UAV's destination is committed) or 'D1p' (no commitment).
    """
    if rule not in ('D1', 'D1p'):
        raise ValueError('unknown in-flight commitment rule')
    d = Scenario(payload).to_dict()
    # Execution happens under the previous forecast, before the update is received.
    executed = deepcopy(d)
    executed['wind']['received'] = deepcopy(executed['wind']['previous'])
    executed['wind']['update_support'] = []
    parent = Scenario(executed)
    times = timeline(parent)
    tau = max(e[3][1] for items in times.values() for e in items if e[0] == 'service')
    target = rational(d['mission']['epoch_h'])+Fraction(target_fraction)*tau
    t, events = snapshot_time(parent, target)
    mission, state = d['mission'], d['state']
    depot = list(mission['depot_xy'])
    tasks = {x['id']: x for x in mission['tasks']}
    vehicles = {u['id']: u for u in mission['vehicles']}
    mass = rational(mission['commodity_unit_mass_kg'])
    snap = deepcopy(d)
    snap['benchmark_id'] = d['benchmark_id']+f'_t{target_fraction.replace("/", "_")}'
    snap['mission']['epoch_h'] = _number(t)
    delivered = {i: rational(v) for i, v in state['cumulative_delivered'].items()}
    stock = rational(state['depot_stock'])
    commitments = {a: [] for a in 'ASPL'}
    reserves, provenance = {}, dict(target=str(target), snapshot=str(t), shift=str(t-target), tau=str(tau), uavs={})
    for uid, route in sorted(d['incumbent']['routes'].items()):
        u, n = vehicles[uid], active_count(route)
        kind, h, start, end = phase(events[uid], t)
        completed = h-1 if kind == 'fly' else n
        # Exact payload, stock and deliveries through the completed stops.
        load = rational(state['fleet'][uid]['onboard'])
        battery_lo = battery_hi = rational(state['fleet'][uid]['battery_wh'])
        if n:
            # The depot origin prepares first: initial loading and a full recharge.
            stock -= rational(route['loads'][0])
            load += rational(route['loads'][0])
            battery_lo = battery_hi = rational(u['battery_capacity_wh'])
        coefficient = rational(u['energy_coefficient_wh_per_kg_km'])*rational(u['airspeed_kmh'])
        legs = range(1, completed+1) if kind == 'idle' else range(1, h)
        for k in legs:
            a, b = stationary_duration(parent, uid, route['paths'][k-1])
            energy = (rational(u['empty_mass_kg'])+mass*load)*coefficient
            battery_lo, battery_hi = battery_lo-energy*b, battery_hi-energy*a
            site = route['stops'][k-1]
            x, y = rational(route['deliveries'][k]), rational(route['loads'][k])
            if site != 'DEPOT':
                battery_lo -= rational(d['operations']['service_energy_wh'])
                battery_hi -= rational(d['operations']['service_energy_wh'])
                delivered[site] += x
                load -= x
            elif k < n:
                stock -= y
                load += y
                battery_lo = battery_hi = rational(u['battery_capacity_wh'])
        record = dict(phase=kind, slot=h, completed=completed, onboard=str(load))
        if kind == 'fly':
            path = route['paths'][h-1]
            a, b = (tuple(map(rational, p)) for p in (path[0], path[-1]))
            duration = stationary_duration(parent, uid, path)
            fraction = ((t-start[1])/duration[1], (t-start[0])/duration[0])
            energy = (rational(u['empty_mass_kg'])+mass*load)*coefficient
            battery_lo -= energy*(t-start[0])
            position = [_round(a[j]+fraction[0]*(b[j]-a[j])) for j in (0, 1)]
            battery = _down(battery_lo)
            record.update(fraction=[str(f) for f in fraction], battery_lower=str(battery_lo),
                          position_rounding=[str(position[j]-(a[j]+fraction[0]*(b[j]-a[j]))) for j in (0, 1)])
            snap['state']['fleet'][uid] = dict(position_xy=[_number(v) for v in position], battery_wh=_number(battery),
                                               onboard=_number(load), mode='airborne', residual_operation=None)
            keep = route['stops'][h-1:n]
            new_paths = [[snap['state']['fleet'][uid]['position_xy'], list(path[-1])], *route['paths'][h:n]]
            deliveries = [0, *route['deliveries'][h:n+1]]
            loads = [0, *route['loads'][h:n+1]]
            if rule == 'D1':
                commitments['S'].append(f'{uid}:1')
                if keep[0] != 'DEPOT':
                    commitments['A'].append(keep[0])
        else:
            battery = _down(battery_lo)
            record.update(battery_lower=str(battery_lo))
            snap['state']['fleet'][uid] = dict(position_xy=list(depot), battery_wh=_number(battery),
                                               onboard=_number(load), mode='idle', residual_operation=None)
            keep, new_paths, deliveries, loads = [], [], [0], [0]
        bound = u['slot_bound']-completed
        snap_vehicle = next(v for v in snap['mission']['vehicles'] if v['id'] == uid)
        snap_vehicle['slot_bound'] = bound
        active = len(keep)
        snap['incumbent']['routes'][uid] = dict(
            stops=[*keep, *[None]*(bound-active)], paths=[*new_paths, *[[list(depot)]]*(bound-active)],
            deliveries=[*deliveries, *[0]*(bound+1-len(deliveries))], loads=[*loads, *[0]*(bound+1-len(loads))])
        reserves[uid] = {}
        if active:
            reserves[uid]['initial'] = [snap['state']['fleet'][uid]['position_xy'], list(depot)]
            for j, site in enumerate(keep, 1):
                if site != 'DEPOT':
                    reserves[uid][str(j)] = [list(tasks[site]['position_xy']), list(depot)]
        provenance['uavs'][uid] = record
    snap['state']['cumulative_delivered'] = {i: _number(v) for i, v in delivered.items()}
    snap['state']['depot_stock'] = _number(stock)
    remaining = {i for i, x in tasks.items() if rational(x['demand']) > delivered[i]}
    snap['incumbent']['assignment'] = {i: owner for i, owner in d['incumbent']['assignment'].items() if i in remaining}
    snap['reserve_paths'] = reserves
    snap['commitments'] = commitments
    cell, wind = received_wind
    snap['wind']['time_knots_h'] = [_number(t), mission['horizon_h']]
    snap['wind']['previous'].update(values=[[[0, 0]] for _ in snap['wind']['cells']],
                                    admissible=[[True] for _ in snap['wind']['cells']], coverage=['forecast'])
    snap['wind']['received'] = deepcopy(snap['wind']['previous'])
    snap['wind']['received']['issued_at_h'] = _number(t)
    snap['wind']['received']['values'][cell][0] = list(wind)
    snap['wind']['update_support'] = [[snap['wind']['cells'][cell]['id'], 0]]
    provenance['completed_deliveries'] = str(sum(delivered.values()))
    return Scenario(snap).to_dict(), provenance


def conservation(parent_payload, snapshot_payload):
    """Stock + onboard + delivered is unchanged by execution."""
    def total(p):
        s = p['state']
        return (rational(s['depot_stock'])+sum(rational(f['onboard']) for f in s['fleet'].values())
                + sum(rational(v) for v in s['cumulative_delivered'].values()))
    return total(parent_payload) == total(snapshot_payload)
