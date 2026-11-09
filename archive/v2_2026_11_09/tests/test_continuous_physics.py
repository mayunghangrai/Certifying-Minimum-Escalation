"""Analytic checks of the independently certified continuous path physics."""
from fractions import Fraction
import importlib

import pytest

from env.scenario import Scenario
from final_benchmark.controlled import base_payload, make_plan


def scene(alpha=0):
    p = base_payload('continuous_physics', [('A', [1, 1], 10)], [1, 1, 1], alpha=float(alpha))
    p['incumbent'], p['reserve_paths'] = make_plan(p, {'U1': ['A']})
    return Scenario(p)


def test_irrational_diagonal_has_outward_rational_bounds():
    physics = importlib.import_module('continuous.physics')
    lo, hi = physics.stationary_duration(scene(), 'U1', [[0, 0], [1, 1]])
    assert lo * lo < 2 < hi * hi
    assert hi - lo <= Fraction(1, 10**18)


def test_perfect_square_bounds_preserve_exact_equality():
    physics = importlib.import_module('continuous.physics')
    assert physics.sqrt_bounds(Fraction(25, 16), 18) == (Fraction(5, 4), Fraction(5, 4))


def test_small_tailwind_displacement_keeps_duration_lower_nonnegative():
    physics = importlib.import_module('continuous.physics')
    p = scene().to_dict()
    p['wind']['received']['values'] = [[[.6, 0]], [[.6, 0]]]
    p['wind']['previous']['values'] = [[[.6, 0]], [[.6, 0]]]
    p['wind']['update_support'] = []
    for distance, digits in ((1e-20, 18), (.01, 1)):
        lo, hi = physics.stationary_duration(Scenario(p), 'U1', [[0, 0], [distance, distance]], digits)
        assert 0 <= lo <= hi


def test_headwind_flight_and_reverse_have_different_exact_durations():
    physics = importlib.import_module('continuous.physics')
    s = scene(Fraction(3, 5))
    assert physics.stationary_duration(s, 'U1', [[0, 0], [1, 0]]) == (Fraction(5, 2),) * 2
    assert physics.stationary_duration(s, 'U1', [[1, 0], [0, 0]]) == (Fraction(5, 8),) * 2


def test_exact_cell_splitting_integrates_both_wind_regions():
    physics = importlib.import_module('continuous.physics')
    assert physics.stationary_duration(scene(Fraction(3, 5)), 'U1', [[-1, 0], [1, 0]]) == (Fraction(7, 2),) * 2


def test_boundary_aligned_flight_uses_declared_lowest_cell_owner():
    physics = importlib.import_module('continuous.physics')
    assert physics.stationary_duration(scene(Fraction(3, 5)), 'U1', [[0, 0], [0, 1]]) == (Fraction(1),) * 2


def test_path_outside_region_is_rejected():
    physics = importlib.import_module('continuous.physics')
    with pytest.raises(ValueError):
        physics.stationary_duration(scene(), 'U1', [[0, 0], [4, 1]])


def test_time_varying_wind_is_explicitly_unsupported():
    physics = importlib.import_module('continuous.physics')
    p = scene().to_dict()
    p['wind']['time_knots_h'] = [0, 10, 20]
    for projection in ('previous', 'received'):
        p['wind'][projection].update(values=[[[0, 0], [0, 0]], [[0, 0], [0, 0]]],
            admissible=[[True, True], [True, True]], coverage=['forecast', 'forecast'])
    p['wind']['received']['values'][1][1] = [-.6, 0]
    p['wind']['update_support'] = [['east', 1]]
    assert 'time' in physics.stationary_guard(Scenario(p))
