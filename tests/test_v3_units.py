from copy import deepcopy
from fractions import Fraction

import pytest

from env import units
from env.scenario import Scenario
from v2_fixtures import revised


def _scale_points(points, k):
    return [[x*k for x in p] for p in points]


def v3_case():
    """The worked four-UAV case in SI with the affine power model."""
    p = revised()
    p.update(schema_version='wind-benchmark-v3', formulation_date='2026-11-04')
    p['units'] = dict(p['units'], distance='m', time='s')
    m = p['mission']
    m['epoch_s'], m['horizon_s'] = 0, 14400
    del m['epoch_h'], m['horizon_h']
    m['commodity_unit_mass_kg'] = .5
    m['operating_region_xy'] = _scale_points(m['operating_region_xy'], 1000)
    m['depot_xy'] = [0, 0]
    for t in m['tasks']:
        t['position_xy'] = [x*1000 for x in t['position_xy']]
        t['deadline_s'] = t.pop('deadline_h')*3600
    for v in m['vehicles']:
        speed = v.pop('airspeed_kmh')
        del v['energy_coefficient_wh_per_kg_km']
        v.update(airspeed_mps=10*speed, empty_mass_kg=6.5, power_a_w=300, power_b_w_per_kg=20,
                 battery_capacity_wh=500, reserve_wh=50, payload_capacity_kg=2.7)
    for s in p['state']['fleet'].values():
        s['battery_wh'] = 500
    o = p['operations']
    o['service_duration_s'] = o.pop('service_duration_h')*3600
    o['preparation_duration_s'] = o.pop('preparation_duration_h')*3600
    w = p['wind']
    for c in w['cells']:
        c['polygon_xy'] = _scale_points(c['polygon_xy'], 1000)
    w['time_knots_s'] = [k*3600 for k in w.pop('time_knots_h')]
    del w['speed_bound_kmh']
    w['speed_bound_mps'] = 8
    for projection in ('previous', 'received'):
        w[projection]['issued_at_s'] = w[projection].pop('issued_at_h')*3600
    w['received']['values'] = [[[0, 0]], [['-15/2', 0]]]
    for route in p['incumbent']['routes'].values():
        route['paths'] = [_scale_points(path, 1000) for path in route['paths']]
    for labels in p['reserve_paths'].values():
        for label, path in labels.items():
            labels[label] = _scale_points(path, 1000)
    return p


def test_v3_fixture_validates_and_round_trips():
    p = v3_case()
    assert Scenario(p).to_dict() == p


@pytest.mark.parametrize('field', ['airspeed_kmh', 'energy_coefficient_wh_per_kg_km'])
def test_v3_schema_rejects_v2_vehicle_fields(field):
    p = v3_case()
    p['mission']['vehicles'][0][field] = 1.
    with pytest.raises(ValueError, match='invalid schema'):
        Scenario(p)


@pytest.mark.parametrize('change', ['optional_part', 'fractional', 'too_heavy'])
def test_v3_rule_one_demands(change):
    p = v3_case()
    task = p['mission']['tasks'][0]
    if change == 'optional_part':
        task['demand'] = 2.
    elif change == 'fractional':
        task['demand'] = task['mandatory'] = 1.5
    else:
        task['demand'] = task['mandatory'] = 6.   # 3 kg > 2.7 kg
    with pytest.raises(ValueError, match='v3 demand'):
        Scenario(p)


def test_v3_wind_bound_is_checked_exactly():
    p = v3_case()
    p['wind']['received']['values'][1][0] = [-8, '1/1000000']
    with pytest.raises(ValueError, match='exceeds the declared bound'):
        Scenario(p)


def test_accessors_read_both_versions_exactly():
    v2, v3 = Scenario(revised()).data, Scenario(v3_case()).data
    assert units.horizon(v2) == 4 and units.horizon(v3) == 14400
    assert units.time_knots(v3) == (0, 14400)
    assert units.deadline(v3, v3['mission']['tasks'][0]) == 5400
    assert units.airspeed(v2, v2['mission']['vehicles'][1]) == 2
    assert units.airspeed(v3, v3['mission']['vehicles'][1]) == 20
    assert units.speed_bound(v3) == 8
    assert units.wind_values(v3, 'received')[1][0] == (Fraction(-15, 2), 0)
    assert units.issued_at(v3, 'received') == 0
    with pytest.raises(ValueError):
        units.version({'schema_version': 'wind-benchmark-v0'})


def test_v2_energy_equals_the_inline_formula():
    data = Scenario(revised()).data
    vehicle = data['mission']['vehicles'][1]
    gamma, v, m0 = (Fraction(str(vehicle[k])) for k in
                    ('energy_coefficient_wh_per_kg_km', 'airspeed_kmh', 'empty_mass_kg'))
    unit = Fraction(str(data['mission']['commodity_unit_mass_kg']))
    load, dt = Fraction(3, 7), Fraction(5, 11)
    expected = (m0 + unit*load)*gamma*v*dt          # recovery/transfers.py energy()
    mass = units.mass(data, vehicle, load)
    assert units.energy_wh(data, vehicle, mass, dt) == expected
    assert units.power_w(data, vehicle, mass) == gamma*mass*v


def test_v3_energy_is_affine_power_times_seconds():
    data = Scenario(v3_case()).data
    vehicle = data['mission']['vehicles'][0]
    mass = units.mass(data, vehicle, 4)                # 6.5 kg + 4 x 0.5 kg
    assert mass == Fraction(17, 2)
    assert units.power_w(data, vehicle, mass) == 300 + 20*mass
    assert units.energy_wh(data, vehicle, mass, 900) == (300 + 20*mass)*900/3600
    constant, per_kg = units.energy_coefficients(data, vehicle, 900)
    assert (constant, per_kg) == (75, 5)


# A0.4: float evaluator and U0 on v3 (hand computation).
# U1 flies depot (0,0) -> T1 (1000,0) in the east cell at 10 m/s with 1 package
# (7 kg, P = 300 + 20*7 = 440 W). Previous wind is calm, received is -7.5 m/s.

def test_v3_float_evaluator_matches_hand_computation():
    from env.route_evaluator import evaluate_path
    s = Scenario(v3_case())
    calm = evaluate_path(s, 'U1', [[0, 0], [1000, 0]], 0., 1., 'previous')
    head = evaluate_path(s, 'U1', [[0, 0], [1000, 0]], 0., 1., 'received')
    assert calm.status == head.status == 'complete'
    assert calm.duration_h == pytest.approx(100) and head.duration_h == pytest.approx(400)
    assert head.energy_wh == pytest.approx(440*400/3600)
    back = evaluate_path(s, 'U1', [[1000, 0], [0, 0]], 400., 0., 'received')
    assert back.duration_h == pytest.approx(1000/17.5)
    assert back.energy_wh == pytest.approx(430*(1000/17.5)/3600)


def test_v3_fixed_plan_and_u0():
    from env.fixed_plan import evaluate_pair
    from env.local_scope import affected_uavs
    from env.wind_dependency import diagnose_wind_update
    s = Scenario(v3_case())
    previous, received = evaluate_pair(s)
    assert previous.status == 'feasible'
    assert received.records['U1'][1]['delivery_h'] == pytest.approx(400)
    assert received.records['U1'][2]['arrival_h'] == pytest.approx(400 + 1000/17.5)
    diagnostic = diagnose_wind_update(s)
    assert diagnostic.tolerances['time_h'] == 1e-6
    # U1 and U2 fly through the east cell; U3 and U4 stay west.
    assert affected_uavs(s, diagnostic)['uavs'] == ['U1', 'U2']


# A0.5: transfer rows use the affine power model and SI times.

def _v3_axis_durations(scenario):
    """Exact durations for the fixture's paths, which all run along the x axis."""
    data = scenario.data
    wind = units.wind_values(data, 'received')
    fleet = {u['id']: u for u in data['mission']['vehicles']}

    def provider(uid, path, time):
        total = Fraction(0)
        for a, b in zip(path, path[1:]):
            dx = Fraction(str(b[0])) - Fraction(str(a[0]))
            if dx == 0:
                continue
            cell = 1 if a[0] + b[0] > 0 else 0          # east cell is row 1
            speed = units.airspeed(data, fleet[uid]) + wind[cell][0][0]*(1 if dx > 0 else -1)
            total += abs(dx)/speed
        return total
    return provider


def test_v3_transfer_rows_use_affine_energy():
    from env.intervention_scope import release_sets
    from recovery.transfers import build_transfer_problem
    s = Scenario(v3_case())
    p = s.to_dict()
    c = build_transfer_problem(s, p['incumbent'], p['reserve_paths'], release_sets(s, 0),
                               exact=True, duration_provider=_v3_axis_durations(s))
    times = {(t['uav'], t['slot']): t for t in c.times}
    assert times['U1', 1]['delivery'] == 400
    out = (300 + 20*Fraction(7))*400/3600                # 1 package: 7 kg
    back = (300 + 20*Fraction(13, 2))*Fraction(400, 7)/3600
    row, = [r for r in c.problem.rows if r.label == 'depot_arrival_reserve:U1:2']
    assert row.bound == 500 - out - back - 50


def test_v3_power_must_be_positive_and_a_may_be_negative():
    p = v3_case()
    for v in p['mission']['vehicles']:
        v.update(power_a_w=-368, power_b_w_per_kg=145.5)       # Q12: 577.75 W at 6.5 kg
    Scenario(p)
    p['mission']['vehicles'][0]['power_b_w_per_kg'] = 50       # 325 - 368 < 0
    with pytest.raises(ValueError, match='power must be positive'):
        Scenario(p)


def test_v3_service_hovers_at_arrival_mass():
    """60 s of service at P(7 kg) = 440 W adds 440*60/3600 Wh before the return."""
    from env.fixed_plan import evaluate_plan
    from env.intervention_scope import release_sets
    from recovery.transfers import build_transfer_problem
    p = v3_case()
    p['operations']['service_duration_s'] = 60
    s = Scenario(p)
    record = evaluate_plan(s, projection='received').records['U1'][1]
    assert record['service_energy_wh'] == pytest.approx(440*60/3600)
    c = build_transfer_problem(s, p['incumbent'], p['reserve_paths'], release_sets(s, 0),
                               exact=True, duration_provider=_v3_axis_durations(s))
    out = (300 + 20*Fraction(7))*400/3600
    back = (300 + 20*Fraction(13, 2))*Fraction(400, 7)/3600
    row, = [r for r in c.problem.rows if r.label == 'depot_arrival_reserve:U1:2']
    assert row.bound == 500 - out - Fraction(440*60, 3600) - back - 50
