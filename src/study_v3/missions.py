"""A5 and the scenario half of A8: build one v3 mission with its incumbent.

Order (design 4.3, 7.2): layout and F0, incumbent by float search, one exact
binned pass over the finished plan, then deadlines and batteries from the
upper ends of the exact intervals. The planner never sees deadlines or
batteries, so float times can only cost efficiency, never validity.
"""
import json
import math
from fractions import Fraction as F
from pathlib import Path

from continuous.binned import binned_interval
from env.scenario import Scenario
from . import geometry, wind_model
from .flight import FloatLegs
from .incumbent import DEPOT, Problem, build_incumbent, simulate
from .seeds import stable_rng

PACKAGE_KG = F(1, 2)
EMPTY_KG = F(13, 2)
PAYLOAD_KG = F(27, 10)
CAPACITY = 5                        # packages per sortie
SERVICE_S, PREPARATION_S = 60, 240
CROSSING_S = 125
MIN_MARGIN_S = 60
SLACK = dict(tight=(0.6, 2), medium=(2, 6), loose=(6, 20))
BETA = dict(tight=F(15, 100), medium=F(1, 2), ample=F(2))
TIME_GRID = F(1, 10**6)
ENERGY_GRID = F(1, 10**6)


PHYSICS = Path(__file__).resolve().parents[2] / 'configs' / 'study_v3' / 'physics.json'


def configured_coefficients(path=PHYSICS):
    """{airspeed: (a_w, b_w_per_kg)} from the physics configuration (Q12)."""
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    c = config['power_coefficients']
    return {speed: (c['a_w'], c['b_w_per_kg']) for speed in config['airspeeds_mps']}


def ceil_grid(value, grid):
    return math.ceil(F(value)/grid)*grid


def floor_grid(value, grid):
    return math.floor(F(value)/grid)*grid


def number(value):
    """A short terminating decimal as a JSON number that reads back exactly."""
    value = F(value)
    result = float(value)
    if F(str(result)) != value:
        raise ValueError(f'{value} is not exactly representable')
    return int(result) if value.denominator == 1 else result


def kappas(seed, n, slack):
    """Margins in cell crossings: log-uniform in the slack range, on a 1e-3 grid."""
    lo, hi = SLACK[slack]
    rng = stable_rng(seed, 'kappa', slack)
    return [F(round(math.exp(rng.uniform(math.log(lo), math.log(hi)))*1000), 1000) for _ in range(n)]


def _power(coefficients, speed, mass):
    a, b = coefficients[speed]
    return F(str(a)) + F(str(b))*mass


def task_counts(n, m):
    """Exactly n // m tasks per UAV; the first n % m UAVs take one more (SC sizes)."""
    return {f'U{j+1}': n//m + (j < n % m) for j in range(m)}


def build_mission(seed, *, m, n, family, slack, beta, coefficients, iterations=2000, geometry_seed=None):
    """`coefficients[airspeed] = (a_w, b_w_per_kg)` (Q12, supplied by the caller).

    `geometry_seed` (default `seed`) fixes the layout, so A8 can keep one
    geometry for 12 draws while F0, margins and the update change.
    """
    layout = geometry.layout(n, family, seed if geometry_seed is None else geometry_seed)
    tasks = [f'T{i+1}' for i in range(n)]
    uids = [f'U{j+1}' for j in range(m)]
    speeds = dict(zip(uids, geometry.airspeeds(m)))
    cells, region, depot = geometry.cells(), geometry.region(), (0, 0)
    legs = FloatLegs(region, cells, lambda r, j: wind_model.f0_value(seed, r, j), wind_model.BIN_S)
    problem = Problem(depot, dict(zip(tasks, map(tuple, layout['positions']))), dict(zip(tasks, layout['demands'])),
                      speeds, task_counts(n, m), CAPACITY, float(SERVICE_S), float(PREPARATION_S), legs)
    routes = build_incumbent(problem, uids, iterations)

    float_makespan = max(simulate(problem, u, s)[0] for u, s in routes.items())
    kappa = dict(zip(tasks, kappas(seed, n, slack)))
    margins = {i: max(F(MIN_MARGIN_S), kappa[i]*CROSSING_S) for i in tasks}
    horizon = math.ceil((float_makespan + float(max(margins.values())) + 3600)/wind_model.BIN_S)*wind_model.BIN_S

    payload = _payload(seed, layout, tasks, uids, speeds, routes, horizon, coefficients)
    scenario = Scenario(payload)
    deliveries, requirement = exact_pass(scenario, coefficients)
    for t in payload['mission']['tasks']:
        t['deadline_s'] = number(ceil_grid(deliveries[t['id']], TIME_GRID) + margins[t['id']])
    for u in payload['mission']['vehicles']:
        cap = ceil_grid(requirement[u['id']]*(1 + BETA[beta])/F(9, 10), ENERGY_GRID)
        u['battery_capacity_wh'], u['reserve_wh'] = number(cap), number(cap/10)
        payload['state']['fleet'][u['id']]['battery_wh'] = number(cap)
    info = dict(seed=seed, geometry_seed=geometry_seed, m=m, n=n, family=family, slack=slack, beta=beta, routes=routes,
                float_makespan=float_makespan, kappa={i: str(v) for i, v in kappa.items()},
                deliveries_upper={i: str(v) for i, v in deliveries.items()},
                requirement_wh={u: str(v) for u, v in requirement.items()})
    return Scenario(payload), info


def _payload(seed, layout, tasks, uids, speeds, routes, horizon, coefficients):
    positions = dict(zip(tasks, layout['positions']))
    demands = dict(zip(tasks, layout['demands']))
    n = len(tasks)
    bound = 2*n + 1                   # D-6: never binds (Rules 1 and 2)
    cells = geometry.cells()
    knots = wind_model.knots(horizon)
    table = wind_model.f0_table(seed, len(cells), len(knots) - 1)
    values = [[[wind_model.wire(x) for x in w] for w in row] for row in table]
    plan, reserves = {'assignment': {}, 'routes': {}}, {}
    for u in uids:
        stops = routes[u] + [DEPOT]
        points = [[0, 0]] + [[0, 0] if s == DEPOT else positions[s] for s in stops]
        loads, deliveries = [0]*(bound + 1), [0]*(bound + 1)
        for h, s in enumerate([DEPOT] + stops):      # h = 0 is the depot origin
            if s == DEPOT:
                if h < len(stops):
                    load = 0
                    for t in stops[h:]:
                        if t == DEPOT:
                            break
                        load += demands[t]
                    loads[h] = load
            else:
                deliveries[h] = demands[s]
                plan['assignment'][s] = u
        paths = [[points[h], points[h+1]] for h in range(len(stops))]
        plan['routes'][u] = dict(stops=stops + [None]*(bound - len(stops)),
                                 paths=paths + [[[0, 0]]]*(bound - len(stops)),
                                 deliveries=deliveries, loads=loads)
        reserves[u] = {'initial': [[0, 0]]}
        for h, s in enumerate(stops, 1):
            if s != DEPOT:
                reserves[u][str(h)] = [positions[s], [0, 0]]
    big = 10**6
    return dict(
        schema_version='wind-benchmark-v3', formulation_date='2026-11-04',
        benchmark_id=f'MS_{seed}_{len(uids)}x{n // len(uids)}',
        units=dict(distance='m', time='s', mass='kg', energy='Wh', quantity='commodity_unit'),
        hierarchy=dict(helper_budget=1, affected_set_rule='directed_incumbent_union'),
        mission=dict(epoch_s=0, horizon_s=horizon, commodity_unit_mass_kg=float(PACKAGE_KG),
                     operating_region_xy=geometry.region(), depot_xy=[0, 0],
                     tasks=[dict(id=t, position_xy=positions[t], demand=demands[t], mandatory=demands[t],
                                 deadline_s=horizon) for t in tasks],
                     vehicles=[dict(id=u, airspeed_mps=speeds[u], empty_mass_kg=float(EMPTY_KG),
                                    power_a_w=coefficients[speeds[u]][0], power_b_w_per_kg=coefficients[speeds[u]][1],
                                    battery_capacity_wh=big, reserve_wh=0, payload_capacity_kg=float(PAYLOAD_KG),
                                    slot_bound=bound) for u in uids]),
        state=dict(depot_stock=layout['stock'], cumulative_delivered={t: 0 for t in tasks},
                   fleet={u: dict(position_xy=[0, 0], battery_wh=big, onboard=0, mode='idle',
                                  residual_operation=None) for u in uids}),
        operations=dict(service_duration_s=SERVICE_S, service_energy_wh=0,
                        preparation_duration_s=PREPARATION_S, depot_bays=None),
        wind=dict(cells=cells, boundary_owner='lowest_cell_id', time_knots_s=knots,
                  speed_bound_mps=8,
                  previous=dict(issued_at_s=0, values=values, admissible=[[True]*(len(knots)-1)]*len(cells),
                                coverage=['forecast']*(len(knots)-1)),
                  received=dict(issued_at_s=0, values=values, admissible=[[True]*(len(knots)-1)]*len(cells),
                                coverage=['forecast']*(len(knots)-1)),
                  update_support=[]),
        incumbent=plan, commitments={a: [] for a in 'ASPL'}, reserve_paths=reserves)


def exact_pass(scenario, coefficients):
    """Upper delivery times and battery requirements R from exact binned intervals.

    Mirrors the transfer compiler's interval mode: times follow the upper chain,
    and each flight's energy is charged over arrival_hi minus departure_lo.
    """
    data = scenario.data
    unit = F(str(data['mission']['commodity_unit_mass_kg']))
    service_energy = F(str(data['operations']['service_energy_wh']))
    deliveries, requirement = {}, {}
    tasks = {t['id']: t for t in data['mission']['tasks']}
    for u in data['mission']['vehicles']:
        uid, speed = u['id'], u['airspeed_mps']
        route = data['incumbent']['routes'][uid]
        stops = [s for s in route['stops'] if s is not None]
        lo = hi = F(PREPARATION_S) if stops else F(0)
        load = F(route['loads'][0])
        used, need = F(0), F(0)
        for h, stop in enumerate(stops, 1):
            alo, ahi = binned_interval(scenario, uid, route['paths'][h-1], lo, hi)
            if alo is None or ahi is None:
                raise ValueError('incumbent reaches the wind horizon')
            used += _power(coefficients, speed, EMPTY_KG + unit*load)*(ahi - lo)/3600
            lo, hi = alo, ahi
            if stop == DEPOT:
                need = max(need, used)
                if h < len(stops):
                    lo, hi = lo + PREPARATION_S, hi + PREPARATION_S
                    used, load = F(0), F(route['loads'][h])
                continue
            lo, hi = lo + SERVICE_S, hi + SERVICE_S
            deliveries[stop] = hi
            used += service_energy + _power(coefficients, speed, EMPTY_KG + unit*load)*SERVICE_S/3600
            load -= F(route['deliveries'][h])
            rlo, rhi = binned_interval(scenario, uid, [tasks[stop]['position_xy'], [0, 0]], lo, hi)
            back = _power(coefficients, speed, EMPTY_KG + unit*load)*(rhi - lo)/3600
            need = max(need, used + back)
        requirement[uid] = need
    return deliveries, requirement
