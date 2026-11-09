"""The formulation, rather than the previous simulator, defines the contract."""
import copy
import json
from pathlib import Path

import pytest

from env.scenario import Scenario

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'scenarios' / 'benchmark'


def raw(name='local_delay'):
    return json.loads((FIXTURES / f'{name}.json').read_text(encoding='utf-8'))


def test_scalar_fixture_round_trip_and_defensive_copy(tmp_path):
    payload = raw()
    scenario = Scenario.from_dict(payload)
    assert scenario.to_dict() == payload
    payload['state']['depot_stock'] = 123
    assert scenario.to_dict()['state']['depot_stock'] == 6
    path = tmp_path / 'case.json'
    scenario.to_json(path)
    assert Scenario.from_json(path).content_hash() == scenario.content_hash()


@pytest.mark.parametrize('name', ['local_delay', 'benign_update', 'horizon_late'])
def test_pair_has_full_coverage_and_only_local_wind_changes(name):
    s = Scenario.from_dict(raw(name)).to_dict()
    w = s['wind']
    assert w['time_knots_h'][0] == s['mission']['epoch_h']
    assert w['time_knots_h'][-1] == s['mission']['horizon_h']
    support = {tuple(x) for x in w['update_support']}
    assert len(support) < len(w['cells']) * (len(w['time_knots_h']) - 1)
    changed = set()
    for r, cell in enumerate(w['cells']):
        for j, (before, after) in enumerate(zip(w['previous']['values'][r], w['received']['values'][r])):
            if before != after:
                changed.add((cell['id'], j))
    assert changed and changed <= support


@pytest.mark.parametrize('section,key,value', [
    ('mission', 'commodity_unit_mass_kg', [2.]),
    ('state', 'depot_stock', [6.]),
    ('mission', 'commodities', ['food', 'medicine']),
    ('wind', 'no_fly_zones', []),
    ('wind', 'weather', []),
    ('wind', 'airspace', []),
    ('mission', 'forecast_horizon_h', 1.5),
    ('operations', 'waiting_time_h', 1.),
])
def test_rejects_legacy_or_unknown_fields(section, key, value):
    p = raw(); p[section][key] = value
    with pytest.raises(ValueError):
        Scenario.from_dict(p)


@pytest.mark.parametrize('mutation', [
    lambda p: p.update(schema_version='information-aware-routing-v3'),
    lambda p: p['mission']['tasks'][0].update(demand=[1., 2., 3., 4.]),
    lambda p: p['state']['fleet']['U1'].update(onboard=[0.]),
    lambda p: p['incumbent']['routes']['U1']['loads'].__setitem__(0, [2.]),
    lambda p: p['wind']['received']['values'][0].pop(),
    lambda p: p['wind']['previous']['values'].pop(),
    lambda p: p['wind']['time_knots_h'].__setitem__(-1, 7.),
    lambda p: p['wind']['time_knots_h'].__setitem__(1, 1.),
    lambda p: p['wind']['received']['values'][0].__setitem__(2, [1., 0.]),
    lambda p: p['wind'].update(update_support=[[c,j] for c in ['L','R'] for j in range(3)]),
    lambda p: p['wind'].update(update_support=[['missing', 0]]),
    lambda p: p['wind'].update(speed_bound_kmh=10.),
    lambda p: p['wind']['previous']['values'][0].__setitem__(0, [10., 0.]),
    lambda p: p['wind']['received'].update(issued_at_h=2.),
    lambda p: p['state']['cumulative_delivered'].update(A=5.),
    lambda p: p['mission']['tasks'][0].update(mandatory=5.),
    lambda p: p['state']['fleet']['U1'].update(battery_wh=101.),
    lambda p: p['mission'].update(commodity_unit_mass_kg=float('nan')),
    lambda p: p['mission']['vehicles'][0].update(slot_bound=True),
    lambda p: p['wind']['cells'][1].update(polygon_xy=[[7,0],[12,0],[12,8],[7,8]]),
    lambda p: p['wind']['cells'][1].update(polygon_xy=[[5,0],[12,0],[12,8],[5,8]]),
])
def test_invalid_input_fails_closed(mutation):
    p = raw(); mutation(p)
    with pytest.raises(ValueError):
        Scenario.from_dict(p)


def test_declared_support_can_conservatively_include_unchanged_entries():
    p = raw(); p['wind']['update_support'].append(['L', 0])
    assert Scenario.from_dict(p).to_dict() == p
