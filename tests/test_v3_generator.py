"""Phase A: F0, geometry, incumbent (design 4.3) and mission assembly."""
from fractions import Fraction as F

import pytest

from continuous.validation import previous_premise
from study_v3 import geometry, wind_model
from study_v3.incumbent import DEPOT, valid
from study_v3.missions import build_mission

from study_v3.missions import configured_coefficients

# Q12 (decided 5 November): P(m) = 145.5 m - 368 W for every airspeed.
COEFFICIENTS = configured_coefficients()


def test_f0_is_bounded_rational_and_prefix_stable():
    short, long = wind_model.f0_table(7, 64, 4), wind_model.f0_table(7, 64, 9)
    assert [row[:4] for row in long] == short
    assert all(x*x + y*y <= 25 for row in long for x, y in row)
    assert all(d[0]**2 + d[1]**2 == 1 for d in wind_model.DIRECTIONS)


def test_geometry_layout():
    cells = geometry.cells()
    assert len(cells) == 64 and cells[0]['polygon_xy'][0] == [-5000, -5000]
    lay = geometry.layout(12, 'clustered', 3)
    assert all(abs(c) <= 5000 and c % 500 == 0 for p in lay['positions'] for c in p)
    assert set(lay['demands']) <= {1, 2, 3, 4, 5} and lay['stock'] >= sum(lay['demands'])
    assert geometry.airspeeds(4) == [10, 12.5, 15, 10]


@pytest.fixture(scope='module')
def mission():
    return build_mission(11, m=3, n=6, family='uniform', slack='medium', beta='medium',
                         coefficients=COEFFICIENTS, iterations=50)


def test_incumbent_obeys_rules_and_k(mission):
    scenario, info = mission
    from study_v3.incumbent import Problem
    demands = {t['id']: t['demand'] for t in scenario.data['mission']['tasks']}
    problem = Problem((0, 0), {}, demands, {}, {}, 5, 60., 240., None)
    for uid, stops in info['routes'].items():
        assert sum(s != DEPOT for s in stops) == 2
        assert valid(problem, stops)
    assert sorted(s for r in info['routes'].values() for s in r if s != DEPOT) == sorted(demands)


def test_incumbent_is_deterministic(mission):
    _, again = build_mission(11, m=3, n=6, family='uniform', slack='medium', beta='medium',
                             coefficients=COEFFICIENTS, iterations=50)
    assert again['routes'] == mission[1]['routes']


def test_deadlines_battery_and_premise(mission):
    scenario, info = mission
    data = scenario.data
    for t in data['mission']['tasks']:
        margin = F(str(t['deadline_s'])) - F(info['deliveries_upper'][t['id']])
        assert margin >= 2*125 - F(1, 10**6)            # medium slack: kappa >= 2
    for u in data['mission']['vehicles']:
        cap, reserve = F(str(u['battery_capacity_wh'])), F(str(u['reserve_wh']))
        assert reserve == cap/10
        assert cap - reserve >= F(info['requirement_wh'][u['id']])*F(3, 2)
    assert data['mission']['horizon_s'] % 900 == 0
    premise = previous_premise(scenario)
    assert premise['accepted'], premise


# A6 and A7: magnitude update, placement and in-flight snapshots.

def test_block_placement_and_t0_update(mission):
    from env.local_scope import affected_uavs
    from env.wind_dependency import diagnose_wind_update
    from study_v3.update import apply_magnitude, legs_changing_bin, place_block
    from env.scenario import Scenario
    scenario, _ = mission
    block = place_block(scenario, 11, 4)
    assert len(block['cells']) == 4 and 1 <= len(block['bins']) <= 3
    assert block == place_block(scenario, 11, 4)               # shared by the nine variants
    updated = Scenario(apply_magnitude(scenario.to_dict(), block, 0.8))
    assert len(updated.data['wind']['update_support']) == 4*len(block['bins'])
    assert legs_changing_bin(updated) >= 0
    u0 = affected_uavs(updated, diagnose_wind_update(updated))['uavs']
    assert block['leg'][0] in u0


@pytest.mark.parametrize('fraction', [F(1, 4), F(1, 2)])
def test_in_flight_snapshot(mission, fraction):
    from continuous.validation import certify_witness
    from env.scenario import Scenario
    from study_v3.snapshots import build_snapshot, conservation
    from study_v3.update import place_block
    scenario, _ = mission
    block = place_block(scenario, 11, 1)
    payload, provenance = build_snapshot(scenario.to_dict(), block, 0.6, block['tau']*float(fraction))
    snap = Scenario(payload)
    assert conservation(scenario.to_dict(), payload)
    assert F(provenance['snapshot']) >= F(str(block['tau']))*fraction - F(1, 10**6)
    assert snap.data['wind']['time_knots_s'][0] == snap.data['mission']['epoch_s']
    premise = previous_premise(snap)
    assert premise['accepted'], premise
    assert premise['kind'] == 'binned_interval_witness_v3'
