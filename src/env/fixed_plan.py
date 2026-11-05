"""Induced execution and one-sided feasibility of externally supplied plans.

The input is an epoch snapshot, not a replay from mission time zero. No
candidate, path, return witness, waiting time, or decision level is selected.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math

from .geometry import polygon, validate_path
from .plan import active_count
from .energy import flight_power
from .route_evaluator import evaluate_path
from .units import time_field

TOL = 1e-9  # Numerical comparison tolerance in the declared physical units.
# Record keys keep their historical `_h` names; values are in the scenario's
# time unit (v2: h, v3: s).


@dataclass(frozen=True)
class PlanEvaluation:
    projection: str
    input_hash: str
    complete: bool
    status: str
    violations: tuple[str, ...]
    unresolved: tuple[str, ...]
    records: dict
    final_states: dict
    delivered: dict
    depot_stock_remaining: float | None
    conservation_error: float | None
    completed_flight_time_h: float | None
    completed_flight_energy_wh: float | None
    reserve_checks: dict

    def to_dict(self):
        return asdict(self)


def _empty_record(h, site):
    return dict(slot=h, site=site, status='unavailable', arrival_h=None,
                delivery_h=None, departure_h=None, onboard_before=None,
                onboard_after=None, battery_before=None, battery_after=None,
                flight_status=None, flight_duration_h=None, flight_energy_wh=None,
                service_energy_wh=None, wind_queries=[], entering_state=None, flight=None)


def _reserve_record():
    return dict(status='unavailable', state=None, flight_status='unavailable',
                arrival_h=None, duration_h=None, energy_wh=None, margin_wh=None,
                wind_queries=[])


def _finite_evaluation(result):
    """Retain known failures, but never serialize overflow as physical values."""
    unavailable = []

    def clean(value, path):
        if isinstance(value,float) and not math.isfinite(value):
            unavailable.append('numerical:'+path)
            return None
        if isinstance(value,dict):
            return {key:clean(item,f'{path}.{key}') for key,item in value.items()}
        if isinstance(value,(list,tuple)):
            items = [clean(item,f'{path}.{i}') for i,item in enumerate(value)]
            return tuple(items) if isinstance(value,tuple) else items
        return value

    values = clean(asdict(result),'evaluation')
    if unavailable:
        values['complete'] = False
        values['status'] = 'infeasible' if result.violations else 'unresolved'
        values['unresolved'] = tuple(sorted(set(result.unresolved).union(unavailable)))
        return PlanEvaluation(**values)
    return result


def evaluate_plan(scenario, plan=None, *, projection='received', reserve_paths=None,
                  enforce_commitments=True):
    data = scenario.data
    plan = data['incumbent'] if plan is None else scenario.validate_candidate(plan, enforce_commitments=enforce_commitments)
    # Reject invalid projection even for an all-idle mission.
    if projection not in ('previous', 'received'):
        raise ValueError('projection must be previous or received')
    mission, observed, protocol = data['mission'], data['state'], data['operations']
    tasks = {i['id']: i for i in mission['tasks']}
    depot = tuple(mission['depot_xy'])
    T = lambda stem: time_field(data, stem)
    epoch, horizon = mission[T('epoch')], mission[T('horizon')]
    mass = mission['commodity_unit_mass_kg']
    witnesses = scenario.validate_reserve_paths(plan, data['reserve_paths'] if reserve_paths is None else reserve_paths)
    region = polygon(mission['operating_region_xy'])
    violations, unresolved = set(), set()
    records, terminal, reserves = {}, {}, {}
    deliveries = {i: 0. for i in tasks}
    planned_deliveries = {i: 0. for i in tasks}
    planned_load = 0.
    actual_load = 0.
    flight_time = flight_energy = 0.
    preparation_intervals = []
    complete = True

    def require(condition, label):
        if not condition:
            violations.add(label)

    def reserve(u, label, position, time, battery, load):
        key = f'reserve:{u["id"]}:{label}'
        record = _reserve_record()
        record.update(status='unresolved', state=dict(position_xy=list(position), time_h=time,
                                                      battery_wh=battery, onboard=load))
        reserves[key] = record
        path = witnesses.get(u['id'], {}).get(str(label))
        if path is None or load < 0:
            unresolved.add(key)
            return
        validate_path(path, region, position, depot)
        result = evaluate_path(scenario, u['id'], path, time, load, projection)
        margin = None if result.energy_wh is None else battery-u['reserve_wh']-result.energy_wh
        passed = result.status == 'complete' and margin >= -TOL
        record.update(status='witness' if passed else 'unresolved',
                      flight_status=result.status, arrival_h=result.arrival_h,
                      duration_h=result.duration_h, energy_wh=result.energy_wh,
                      margin_wh=margin, wind_queries=[asdict(piece) for piece in result.slices])
        if not passed:
            unresolved.add(key)

    for uid, route in plan['routes'].items():
        n = active_count(route)
        planned_load += sum(route['loads'][:n],0.)
        for h, site in enumerate(route['stops'][:n], 1):
            if site != 'DEPOT':
                planned_deliveries[site] += route['deliveries'][h]
    require(planned_load <= observed['depot_stock']+TOL, 'inventory')
    for i, task in tasks.items():
        previous = observed['cumulative_delivered'][i]
        lower, upper = max(0., task['mandatory']-previous), task['demand']-previous
        require(lower-TOL <= planned_deliveries[i] <= upper+TOL, f'service:{i}')

    for u in mission['vehicles']:
        uid = u['id']
        route, initial = plan['routes'][uid], observed['fleet'][uid]
        n = active_count(route)
        recs = [_empty_record(0, 'ORIGIN')]+[_empty_record(h,site) for h,site in enumerate(route['stops'][:n],1)]
        records[uid] = recs
        if n:
            for label in ['initial']+[str(h) for h in range(1,n+1) if route['stops'][h-1] != 'DEPOT']:
                reserves[f'reserve:{uid}:{label}'] = _reserve_record()
        terminal[uid] = None
        time, battery, load = epoch, initial['battery_wh'], initial['onboard']
        position = tuple(initial['position_xy'])
        depot_origin = position == depot and initial['mode'] in ('idle', 'preparing')
        if not depot_origin:
            reserve(u, 'initial', position, time, battery, load)
        failed_at = None
        for h in range(n+1):
            record = recs[h]
            record['entering_state'] = dict(position_xy=list(position), time_h=time,
                                            battery_wh=battery, onboard=load)
            at_depot = depot_origin if h == 0 else route['stops'][h-1] == 'DEPOT'
            if h:
                if load < 0:
                    failed_at = h
                    break
                flight = evaluate_path(scenario, uid, route['paths'][h-1], time, load, projection)
                record['flight'] = flight.to_dict()
                record['flight_status'] = flight.status
                record['wind_queries'] = [asdict(piece) for piece in flight.slices]
                if flight.status == 'unavailable':
                    record['status'] = 'unavailable'
                    unresolved.add(f'coverage:{uid}:{h}:flight')
                    failed_at = h
                    break
                if flight.status == 'closed':
                    violations.add(f'admissibility:{uid}:{h}:flight')
                if flight.status == 'late':
                    record['status'] = 'late'
                    violations.add(f'horizon:{uid}:{h}:flight')
                    failed_at = h
                    break
                time = flight.arrival_h
                battery -= flight.energy_wh
                flight_time += flight.duration_h
                flight_energy += flight.energy_wh
                record.update(flight_duration_h=flight.duration_h, flight_energy_wh=flight.energy_wh)
                site = route['stops'][h-1]
                position = depot if at_depot else tuple(tasks[site]['position_xy'])
                if at_depot:
                    require(battery >= u['reserve_wh']-TOL, f'depot_arrival_reserve:{uid}:{h}')
            else:
                record.update(flight_status='origin', flight_duration_h=0., flight_energy_wh=0.)
            record.update(arrival_h=time, onboard_before=load, battery_before=battery)
            require(-TOL <= battery <= u['battery_capacity_wh']+TOL, f'battery:{uid}:{h}:arrival')
            x, y = route['deliveries'][h], route['loads'][h]
            require(x <= load+TOL, f'delivery_availability:{uid}:{h}')
            require(-TOL <= mass*load <= u['payload_capacity_kg']+TOL and -TOL <= mass*(load-x+y) <= u['payload_capacity_kg']+TOL, f'payload:{uid}:{h}')
            service_duration = service_energy = 0.
            if h and not at_depot:
                residual = initial['residual_operation'] if h == 1 and initial['mode'] == 'servicing' else None
                service_duration = protocol[T('service_duration')] if residual is None else residual[T('duration')]
                service_energy = protocol['service_energy_wh'] if residual is None else residual['energy_wh']
                if residual is None and data['schema_version'] == 'wind-benchmark-v3':
                    # v3: hovering through service at the power of the mass on arrival.
                    service_energy += flight_power(u, mass, load)*service_duration/3600
            delivery_time = time+service_duration
            preparation = 0.
            if at_depot and h < n:
                residual = initial['residual_operation'] if h == 0 and initial['mode'] == 'preparing' else None
                preparation = protocol[T('preparation_duration')] if residual is None else residual[T('duration')]
                if preparation > 0:
                    preparation_intervals.append((time, min(time+preparation,horizon)))
            departure_time = delivery_time+preparation
            if departure_time > horizon:
                violations.add(f'horizon:{uid}:{h}:ground')
                record['status'] = 'late'
                failed_at = h
                break
            battery -= service_energy
            require(battery >= -TOL, f'battery:{uid}:{h}:service')
            load = load-x+y
            if at_depot and h < n:
                battery = u['battery_capacity_wh']
                actual_load += y
            if h and not at_depot:
                deliveries[route['stops'][h-1]] += x
                deadline = tasks[route['stops'][h-1]][T('deadline')]
                if x > 0 and deadline is not None:
                    require(delivery_time <= deadline+TOL, f'deadline:{uid}:{h}:{route["stops"][h-1]}')
                reserve(u, str(h), position, delivery_time, battery, load)
            if h == 0 and at_depot and n:
                reserve(u, 'initial', position, departure_time, battery, load)
            record.update(status='complete', delivery_h=delivery_time,
                          departure_h=departure_time if h<n else None,
                          onboard_after=load, battery_after=battery,
                          service_energy_wh=service_energy)
            time = departure_time
        if failed_at is not None:
            complete = False
            unresolved.update(key for key,value in reserves.items()
                              if key.startswith(f'reserve:{uid}:') and value['status'] == 'unavailable')
            unresolved.add(f'terminal:{uid}')
            for h in range(failed_at, n+1):
                unresolved.add(f'resources:{uid}:{h}')
                if h and route['stops'][h-1] != 'DEPOT':
                    site = route['stops'][h-1]
                    if route['deliveries'][h] > 0 and tasks[site][T('deadline')] is not None:
                        unresolved.add(f'deadline:{uid}:{h}:{site}')
                    unresolved.add(f'reserve:{uid}:{h}')
            continue
        terminal[uid] = dict(position_xy=list(position), time_h=time, battery_wh=battery, onboard=load)
        require(position == depot and time <= horizon and u['reserve_wh']-TOL <= battery <= u['battery_capacity_wh']+TOL and -TOL <= mass*load <= u['payload_capacity_kg']+TOL, f'terminal:{uid}')

    bays = protocol['depot_bays']
    if bays is not None:
        events = [(start,1) for start,end in preparation_intervals if end > start]+[(end,-1) for start,end in preparation_intervals if end > start]
        concurrent = 0
        for _, change in sorted(events):
            concurrent += change
            require(concurrent <= bays, 'depot_bays')
        if not complete and 'depot_bays' not in violations:
            unresolved.add('depot_bays')
    conservation = None
    if complete:
        initial_total = observed['depot_stock']+sum(s['onboard'] for s in observed['fleet'].values())
        final_total = observed['depot_stock']-actual_load+sum(s['onboard'] for s in terminal.values())+sum(deliveries.values())
        conservation = final_total-initial_total
    status = 'infeasible' if violations else ('unresolved' if unresolved or not complete else 'feasible')
    return _finite_evaluation(PlanEvaluation(projection, scenario.content_hash(), complete, status,
                          tuple(sorted(violations)), tuple(sorted(unresolved)), records,
                          terminal, deliveries, observed['depot_stock']-actual_load,
                          conservation, flight_time, flight_energy, reserves))


def evaluate_pair(scenario):
    """Evaluate the same incumbent twice; enforce the previous-wind premise."""
    previous = evaluate_plan(scenario, projection='previous')
    if previous.status != 'feasible':
        raise ValueError('benchmark incumbent lacks a feasible previous-wind witness')
    return previous, evaluate_plan(scenario, projection='received')
