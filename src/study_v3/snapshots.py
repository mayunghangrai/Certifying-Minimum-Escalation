"""A7: in-flight snapshots under binned F0 (rewrite of escalation_study.snapshots).

The incumbent is executed under F0 to the update time t_u. Event times are
exact [lower, upper] intervals from `binned_interval`. A snapshot that finds a
UAV mid-service or mid-preparation moves to the end of that operation (D3).
Airborne positions are rounded to a 1e-6 m grid and batteries down to 1e-6 Wh;
payload, stock and deliveries stay exact. Only D1' is used: no in-flight
commitment, the level masks alone decide what an airborne UAV may change.
The knots are cut at t_u, F1 applies from t_u on, and the caller re-certifies
the previous premise, so rounding can reject a snapshot but never admit an
infeasible one.
"""
from copy import deepcopy
from fractions import Fraction as F
import math

from continuous.binned import binned_interval, position_at
from env.plan import active_count
from env.scenario import Scenario
from .update import apply_magnitude

TIME_GRID = F(1, 10**6)       # s
SPACE_GRID = F(1, 10**6)      # m
ENERGY_GRID = F(1, 10**6)     # Wh
NEAR = F(1, 10**3)            # s: a flight this close to landing ends the snapshot later


def _down(value, grid):
    return F(math.floor(value/grid))*grid


def _round(value, grid):
    return F(math.floor(value/grid + F(1, 2)))*grid


def _up(value, grid):
    return F(math.ceil(value/grid))*grid


def _number(value):
    value = F(value)
    result = float(value)
    if F(str(result)) != value:
        raise ValueError('snapshot value is not representable as a short decimal')
    return int(result) if value.denominator == 1 else result


def _r(value):
    return F(str(value))


def _power(vehicle, mass):
    return _r(vehicle['power_a_w']) + _r(vehicle['power_b_w_per_kg'])*mass


def timeline(scenario):
    """Per UAV: (kind, slot, start interval, end interval) under F0 (= received here)."""
    d = scenario.data
    prep, service = _r(d['operations']['preparation_duration_s']), _r(d['operations']['service_duration_s'])
    epoch = _r(d['mission']['epoch_s'])
    out = {}
    for uid, route in sorted(d['incumbent']['routes'].items()):
        n = active_count(route)
        events, lo, hi = [], epoch, epoch
        if n:
            events.append(('prepare', 0, (lo, hi), (lo+prep, hi+prep)))
            lo, hi = lo+prep, hi+prep
        for h, path in enumerate(route['paths'][:n], 1):
            alo, ahi = binned_interval(scenario, uid, path, lo, hi)
            if alo is None or ahi is None:
                raise ValueError('incumbent reaches the wind horizon')
            events.append(('fly', h, (lo, hi), (alo, ahi)))
            lo, hi = alo, ahi
            if route['stops'][h-1] != 'DEPOT':
                events.append(('service', h, (lo, hi), (lo+service, hi+service)))
                lo, hi = lo+service, hi+service
            elif h < n:
                events.append(('prepare', h, (lo, hi), (lo+prep, hi+prep)))
                lo, hi = lo+prep, hi+prep
        events.append(('idle', n, (lo, hi), None))
        out[uid] = events
    return out


def phase(events, t):
    """The event containing t, or None when t falls inside an event-time interval."""
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


def snapshot_time(events, target):
    """Earliest grid time >= target with every UAV airborne or finished (D3)."""
    t = _up(target, TIME_GRID)
    for _ in range(1000):
        moved = False
        for items in events.values():
            current = phase(items, t)
            if current is None:
                raise ValueError('snapshot time falls inside an event-time interval')
            kind, _, start, end = current
            if kind in ('prepare', 'service') or (kind == 'fly' and end[1] - t < NEAR):
                following = items[items.index(current)+1] if kind == 'fly' else current
                stop_end = following[3] if following[3] is not None else following[2]
                t = _up(stop_end[1] + TIME_GRID, TIME_GRID)
                moved = True
        if not moved:
            return t
    raise ValueError('snapshot time did not settle')


def build_snapshot(payload, block, r, target):
    """(snapshot payload, provenance) at the first settled time >= target.

    `payload` is the t_u = 0 mission (received = previous = F0).
    """
    d = Scenario(payload).to_dict()
    parent = Scenario(d)
    events = timeline(parent)
    t = snapshot_time(events, _r(target))
    mission, state = d['mission'], d['state']
    depot = list(mission['depot_xy'])
    tasks = {x['id']: x for x in mission['tasks']}
    vehicles = {u['id']: u for u in mission['vehicles']}
    unit = _r(mission['commodity_unit_mass_kg'])
    service_energy = _r(d['operations']['service_energy_wh'])
    snap = deepcopy(d)
    snap['benchmark_id'] = f"{d['benchmark_id']}_t{str(t).replace('/', '_')}"
    snap['mission']['epoch_s'] = _number(t)
    delivered = {i: _r(v) for i, v in state['cumulative_delivered'].items()}
    stock = _r(state['depot_stock'])
    reserves, provenance = {}, dict(target=str(target), snapshot=str(t), shift=str(t - _r(target)), uavs={})
    for uid, route in sorted(d['incumbent']['routes'].items()):
        u, n = vehicles[uid], active_count(route)
        kind, h, start, end = phase(events[uid], t)
        completed = h - 1 if kind == 'fly' else n
        load = _r(state['fleet'][uid]['onboard'])
        battery = _r(state['fleet'][uid]['battery_wh'])
        if n:
            stock -= _r(route['loads'][0])
            load += _r(route['loads'][0])
            battery = _r(u['battery_capacity_wh'])
        flights = [e for e in events[uid] if e[0] == 'fly']
        for kk in (range(1, completed+1) if kind == 'idle' else range(1, h)):
            _, _, (dlo, _), (_, ahi) = flights[kk-1]
            battery -= _power(u, _r(u['empty_mass_kg']) + unit*load)*(ahi - dlo)/3600
            site = route['stops'][kk-1]
            x, y = _r(route['deliveries'][kk]), _r(route['loads'][kk])
            if site != 'DEPOT':
                battery -= service_energy + _power(u, _r(u['empty_mass_kg']) + unit*load)*_r(d['operations']['service_duration_s'])/3600
                delivered[site] += x
                load -= x
            elif kk < n:
                stock -= y
                load += y
                battery = _r(u['battery_capacity_wh'])
        record = dict(phase=kind, slot=h, completed=completed, onboard=str(load))
        if kind == 'fly':
            path = route['paths'][h-1]
            behind, ahead = position_at(parent, uid, path, start[0], start[1], t)
            battery -= _power(u, _r(u['empty_mass_kg']) + unit*load)*(t - start[0])/3600
            position = [_round(behind[j], SPACE_GRID) for j in (0, 1)]
            record.update(behind=[str(v) for v in behind], ahead=[str(v) for v in ahead])
            fleet_state = dict(position_xy=[_number(v) for v in position], battery_wh=_number(_down(battery, ENERGY_GRID)),
                               onboard=_number(load), mode='airborne', residual_operation=None)
            keep = route['stops'][h-1:n]
            new_paths = [[fleet_state['position_xy'], list(path[-1])], *route['paths'][h:n]]
            deliveries, loads = [0, *route['deliveries'][h:n+1]], [0, *route['loads'][h:n+1]]
        else:
            fleet_state = dict(position_xy=list(depot), battery_wh=_number(_down(battery, ENERGY_GRID)),
                               onboard=_number(load), mode='idle', residual_operation=None)
            keep, new_paths, deliveries, loads = [], [], [0], [0]
        record['battery_lower'] = str(battery)
        snap['state']['fleet'][uid] = fleet_state
        bound = u['slot_bound'] - completed
        next(v for v in snap['mission']['vehicles'] if v['id'] == uid)['slot_bound'] = bound
        active = len(keep)
        snap['incumbent']['routes'][uid] = dict(
            stops=[*keep, *[None]*(bound - active)], paths=[*new_paths, *[[list(depot)]]*(bound - active)],
            deliveries=[*deliveries, *[0]*(bound + 1 - len(deliveries))], loads=[*loads, *[0]*(bound + 1 - len(loads))])
        reserves[uid] = {}
        if active:
            reserves[uid]['initial'] = [fleet_state['position_xy'], list(depot)]
            for j, site in enumerate(keep, 1):
                if site != 'DEPOT':
                    reserves[uid][str(j)] = [list(tasks[site]['position_xy']), list(depot)]
        provenance['uavs'][uid] = record
    snap['state']['cumulative_delivered'] = {i: _number(v) for i, v in delivered.items()}
    snap['state']['depot_stock'] = _number(stock)
    remaining = {i for i, x in tasks.items() if _r(x['demand']) > delivered[i]}
    snap['incumbent']['assignment'] = {i: o for i, o in d['incumbent']['assignment'].items() if i in remaining}
    snap['reserve_paths'] = reserves
    snap['commitments'] = {a: [] for a in 'ASPL'}
    # Cut the knots at t: drop whole bins before t; the bin holding t starts at t.
    knots = [_r(k) for k in d['wind']['time_knots_s']]
    first = max(j for j in range(len(knots) - 1) if knots[j] <= t)
    snap['wind']['time_knots_s'] = [_number(t), *d['wind']['time_knots_s'][first+1:]]
    for projection in ('previous', 'received'):
        packet = snap['wind'][projection]
        packet['values'] = [row[first:] for row in d['wind']['previous']['values']]
        packet['admissible'] = [row[first:] for row in d['wind']['previous']['admissible']]
        packet['coverage'] = d['wind']['previous']['coverage'][first:]
        packet.pop('retained_from', None)
    snap['wind']['previous']['issued_at_s'] = d['wind']['previous']['issued_at_s']
    snap['wind']['received']['issued_at_s'] = _number(t)
    snap = apply_magnitude(snap, block, r, first_bin=first, bin_offset=first)
    provenance['completed_deliveries'] = str(sum(delivered.values()))
    return Scenario(snap).to_dict(), provenance


def conservation(parent_payload, snapshot_payload):
    """Stock + onboard + delivered is unchanged by execution."""
    def total(p):
        s = p['state']
        return (_r(s['depot_stock']) + sum(_r(f['onboard']) for f in s['fleet'].values())
                + sum(_r(v) for v in s['cumulative_delivered'].values()))
    return total(parent_payload) == total(snapshot_payload)
