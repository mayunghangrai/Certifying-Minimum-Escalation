from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import pytest

from env.intervention_scope import release_sets
from env.scenario import Scenario
from recovery.physics import flight_duration
from recovery.representation import PathLibrary
from recovery.search import recover
from recovery.transfers import build_transfer_problem


@pytest.fixture(scope='module')
def cases():
    from experiments.instances import build_instances
    return build_instances(Path(__file__).resolve().parents[1])


def test_all_generated_cases_have_exact_feasible_incumbents_and_proper_full_tables(cases):
    assert len(cases) == len({c['id'] for c in cases}) == 88
    for case in cases:
        p = deepcopy(case['scenario'])
        s = Scenario.from_dict(p)
        PathLibrary.from_dict(s, case['representation']).validate(s)
        wind = p['wind']
        actual = {(cell['id'], j) for cell, before, after in
                  zip(wind['cells'], wind['previous']['values'], wind['received']['values'])
                  for j, (a, b) in enumerate(zip(before, after)) if a != b}
        assert actual == {tuple(e) for e in wind['update_support']}
        assert len(actual) < len(wind['cells']) * (len(wind['time_knots_h']) - 1)
        wind['received']['values'] = deepcopy(wind['previous']['values'])
        wind['update_support'] = []
        previous = Scenario.from_dict(p)
        lp = build_transfer_problem(previous, p['incumbent'], p['reserve_paths'],
                                    release_sets(previous, 0), exact=True)
        assert lp.problem.accepts(()), case['id']


def test_each_factor_changes_only_its_declared_inputs(cases):
    groups = {}
    for case in cases:
        p = deepcopy(case['scenario'])
        factor = case['factor']
        if factor == 'wind_magnitude':
            p['wind']['received']['values'][1] = None
            p['wind']['update_support'] = None
        elif factor == 'wind_duration':
            p['wind']['received']['values'][1] = None
            p['wind']['update_support'] = None
        elif factor == 'deadline':
            p['mission']['tasks'][0]['deadline_h'] = None
        elif factor == 'battery':
            for vehicle in p['mission']['vehicles']:
                assert vehicle['battery_capacity_wh'] == p['state']['fleet'][vehicle['id']]['battery_wh']
                vehicle['battery_capacity_wh'] = None
                p['state']['fleet'][vehicle['id']]['battery_wh'] = None
        group = groups.setdefault((case['family'], factor), p)
        assert p == group, case['id']
    for family in ('A', 'B', 'divisible'):
        durations = [c for c in cases if c['family'] == family and c['factor'] == 'wind_duration']
        assert [c['scenario']['wind']['time_knots_h'] for c in durations] == [[0, 1, 2, 4]] * 4


def test_libraries_are_nested_with_fixed_returns_and_original_fixture_paths(cases):
    for family in ('A', 'B', 'divisible', 'bypass'):
        variants = [c for c in cases if c['family'] == family and c['factor'] == 'paths']
        libraries = [PathLibrary.from_dict(Scenario.from_dict(c['scenario']), c['representation']) for c in variants]
        for a, b in zip(libraries, libraries[1:]):
            assert set(a.nominal) < set(b.nominal)
            assert a.returns == b.returns
            assert a.scenario_hash == b.scenario_hash


def test_useful_bypass_has_hand_derived_time_and_changes_represented_recoverability(cases):
    variants = [c for c in cases if c['family'] == 'bypass']
    s = Scenario.from_dict(variants[0]['scenario'])
    assert flight_duration(s, 'U1', [[0, 0], [2, 0]], 0, exact=True) == 1
    assert flight_duration(s, 'U1', [[0, 0], [0, .5], [2, .5], [2, 0]], 0, exact=True) == Fraction(5, 8)
    for case, minimum in zip(variants, [None, 1, 1, 1]):
        lib = PathLibrary.from_dict(s, case['representation'])
        r = recover(s, lib, numerical=False)
        assert r['status'] == ('NO_CONTINUATION_R' if minimum is None else 'MINIMUM_CERTIFIED_R')
        assert r['upper_bound'] == minimum


def test_divisible_case_requires_sequence_repair_with_fractional_transfers(cases):
    case = next(c for c in cases if c['family'] == 'divisible' and c['factor'] == 'deadline' and c['value'] == 2.3)
    s = Scenario.from_dict(case['scenario'])
    r = recover(s, PathLibrary.from_dict(s, case['representation']), numerical=False)
    assert r['lower_bound'] == r['upper_bound'] == 2
    assert {'3/4', '1/2'} <= set(r['witness']['exact_transfers'].values())
