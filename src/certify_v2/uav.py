"""Exact rows of one UAV's transfer problem, for proofs and plans one UAV at a time.

``uav_problem`` builds, for one UAV and one stop sequence, exactly the rows that
``recovery.transfers.build_transfer_problem`` creates for that UAV (same labels,
coefficients and bounds), the service rows of the tasks it owns, and the stock row
restricted to its own loads. Every row is implied by the full problem when the UAV
alone visits its tasks and other loads are nonnegative, so a Farkas combination of
these rows excludes the stop sequence whatever the other UAVs do. With lower flight
times it is a relaxation; with the times of actual paths it proposes quantities
that the full exact checker then confirms. ``tests/test_certify_v2_uav.py`` compares
the rows with the full compiler.
"""
from dataclasses import dataclass
from fractions import Fraction

from level2.quantities import _solve
from recovery.linear import LinearProblem, Row, rational, verify_exclusion
from recovery.transfers import BranchRejected


@dataclass(frozen=True)
class UavProblem:
    problem: LinearProblem
    columns: tuple        # ((h, 'x'|'y'), ...)
    times: tuple


def depot_origin(data, uid):
    s = data['state']['fleet'][uid]
    return tuple(s['position_xy']) == tuple(data['mission']['depot_xy']) and s['mode'] in ('idle', 'preparing')


def uav_problem(scenario, uid, stops, durations, reserves, *, released=None, fixed=None):
    """Rows for one UAV flying ``stops`` (active prefix, last stop the depot).

    ``durations[h-1]`` is the flight time of leg h; ``reserves`` maps 'initial' and
    the task-stop labels str(h) to reserve-return flight times. ``released`` is the
    set of (h, a) quantity coordinates that are variables (default: all eligible);
    other eligible coordinates take ``fixed[(h, a)]`` (default 0).
    """
    d = scenario.data
    mission, state, protocol = d['mission'], d['state'], d['operations']
    u = next(v for v in mission['vehicles'] if v['id'] == uid)
    initial = state['fleet'][uid]
    if initial['mode'] not in ('idle', 'airborne'):
        raise ValueError('unfinished ground operations are not supported')
    tasks = {t['id']: t for t in mission['tasks']}
    n = len(stops)
    if n and stops[-1] != 'DEPOT':
        raise ValueError('active route must end at the depot')
    if len(durations) != n:
        raise ValueError('one flight time per leg is required')
    origin = depot_origin(d, uid)
    eligible = []
    for h in range(n+1):
        if 0 < h <= n and stops[h-1] != 'DEPOT':
            eligible.append((h, 'x'))
        if h < n and (origin if h == 0 else stops[h-1] == 'DEPOT'):
            eligible.append((h, 'y'))
    columns = tuple(sorted(c for c in eligible if released is None or c in released))
    index = {c: i for i, c in enumerate(columns)}
    width = len(columns)
    fixed = fixed or {}
    rows = []

    def const(value):
        return [Fraction(0)]*width, Fraction(value)

    def var(c):
        coeff = [Fraction(0)]*width
        coeff[index[c]] = Fraction(1)
        return coeff, Fraction(0)

    def add(a, b):
        return [x+y for x, y in zip(a[0], b[0])], a[1]+b[1]

    def sub(a, b):
        return [x-y for x, y in zip(a[0], b[0])], a[1]-b[1]

    def scale(a, k):
        return [x*k for x in a[0]], a[1]*k

    def le(left, right, label):
        expr = sub(left, right)
        rows.append(Row(tuple(expr[0]), -expr[1], label))

    def transfer(h, a):
        if (h, a) in index:
            expr = var((h, a))
            le(scale(expr, -1), const(0), f'nonnegative:{uid}:{h}:{a}')
            return expr
        if (h, a) in eligible:
            return const(fixed.get((h, a), 0))
        return const(0)

    transfers = {(h, a): transfer(h, a) for h in range(len(stops)+1) for a in ('x', 'y')}
    epoch, horizon = rational(mission['epoch_h']), rational(mission['horizon_h'])
    mass = rational(mission['commodity_unit_mass_kg'])
    cap, res, payload = rational(u['battery_capacity_wh']), rational(u['reserve_wh']), rational(u['payload_capacity_kg'])
    factor = rational(u['energy_coefficient_wh_per_kg_km'])*rational(u['airspeed_kmh'])
    empty = rational(u['empty_mass_kg'])

    def energy(load, dt):
        return scale(add(const(empty), scale(load, mass)), factor*dt)

    def reserve(label, time, battery, load):
        if label not in reserves or reserves[label] is None:
            raise ValueError(f'missing reserve flight time: {uid}:{label}')
        dt = reserves[label]
        if time+dt > horizon:
            raise BranchRejected(f'reserve_horizon:{uid}:{label}', exact=True)
        le(add(energy(load, dt), const(res)), battery, f'reserve:{uid}:{label}')

    time, load, battery = epoch, const(rational(initial['onboard'])), const(rational(initial['battery_wh']))
    delivered, stock, times = {}, const(0), []
    if not origin:
        reserve('initial', time, battery, load)
    for h in range(n+1):
        at_depot = origin if h == 0 else stops[h-1] == 'DEPOT'
        if h:
            dt = durations[h-1]
            if dt < 0:
                raise ValueError('flight duration must be nonnegative')
            if time+dt > horizon:
                raise BranchRejected(f'horizon:{uid}:{h}:flight', exact=True)
            time += dt
            battery = sub(battery, energy(load, dt))
            if at_depot:
                le(const(res), battery, f'depot_arrival_reserve:{uid}:{h}')
        le(const(0), battery, f'battery:{uid}:{h}:lower')
        le(battery, const(cap), f'battery:{uid}:{h}:upper')
        x, y = transfers[h, 'x'], transfers[h, 'y']
        le(x, load, f'availability:{uid}:{h}')
        le(const(0), load, f'payload_before:{uid}:{h}:lower')
        le(scale(load, mass), const(payload), f'payload_before:{uid}:{h}:upper')
        service_time = service_energy = Fraction(0)
        if h and not at_depot:
            service_time = rational(protocol['service_duration_h'])
            service_energy = rational(protocol['service_energy_wh'])
        delivery_time = time+service_time
        preparation = rational(protocol['preparation_duration_h']) if at_depot and h < n else Fraction(0)
        departure = delivery_time+preparation
        if departure > horizon:
            raise BranchRejected(f'horizon:{uid}:{h}:ground', exact=True)
        battery = sub(battery, const(service_energy))
        le(const(0), battery, f'battery_service:{uid}:{h}')
        load = add(sub(load, x), y)
        le(const(0), load, f'payload_after:{uid}:{h}:lower')
        le(scale(load, mass), const(payload), f'payload_after:{uid}:{h}:upper')
        if at_depot and h < n:
            battery = const(cap)
            stock = add(stock, y)
        if h and not at_depot:
            site = stops[h-1]
            delivered[site] = add(delivered.get(site, const(0)), x)
            deadline = tasks[site]['deadline_h']
            if deadline is not None and delivery_time > rational(deadline):
                le(x, const(0), f'deadline:{uid}:{h}:{site}')
            reserve(str(h), delivery_time, battery, load)
        if h == 0 and origin and n:
            reserve('initial', departure, battery, load)
        times.append(dict(slot=h, arrival=time, delivery=delivery_time, departure=departure))
        time = departure
    le(const(res), battery, f'terminal_reserve:{uid}')
    le(stock, const(rational(state['depot_stock'])), f'inventory:{uid}')
    for site in sorted(delivered):
        previous = rational(state['cumulative_delivered'][site])
        task = tasks[site]
        le(const(max(Fraction(0), rational(task['mandatory'])-previous)), delivered[site], f'service:{site}:mandatory')
        le(delivered[site], const(rational(task['demand'])-previous), f'service:{site}:demand')
    names = tuple(f'{uid}:{h}:{a}' for h, a in columns)
    return UavProblem(LinearProblem(names, tuple(rows), True), columns, tuple(times))


def solve_uav(built, *, exclusion, max_operations=100000, max_rows=10000):
    """('WITNESS', values) | ('EMPTY', {label: multiplier}) | ('UNRESOLVED', reason)."""
    result = _solve(built.problem, max_operations, max_rows, exclusion=exclusion)
    if result.status == 'WITNESS' and result.exact and built.problem.accepts(result.values):
        return 'WITNESS', tuple(result.values)
    if result.status == 'EMPTY' and result.exact and verify_exclusion(built.problem, result.certificate):
        rows = built.problem.rows
        return 'EMPTY', {rows[int(i)].label: v for i, v in result.certificate['multipliers'].items()}
    return 'UNRESOLVED', result.reason or result.status


def verify_uav_exclusion(built, multipliers):
    """Check a Farkas combination keyed by row label against rebuilt rows."""
    labels = {row.label: i for i, row in enumerate(built.problem.rows)}
    if len(labels) != len(built.problem.rows) or not isinstance(multipliers, dict):
        return False
    try:
        certificate = dict(kind='farkas', multipliers={str(labels[k]): v for k, v in multipliers.items()})
    except KeyError:
        return False
    return verify_exclusion(built.problem, certificate)
