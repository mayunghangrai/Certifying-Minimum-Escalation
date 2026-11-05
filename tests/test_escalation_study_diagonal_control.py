"""Analytic control for the diagonal winds used by P1 (plan Section 2.3).

Under a uniform wind w, a UAV with airspeed v covers a displacement d in
t = (sqrt((w.d)^2 + A |d|^2) - w.d) / A with A = v^2 - |w|^2, and the straight
chord is time-optimal. The certified chord duration must enclose t and the
verified all-path lower bound must not exceed it.
"""
import math
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))

import pytest

from continuous.physics import stationary_duration
from continuous.potential import propose_potential, verify_potential
from env.scenario import Scenario
from escalation_study.missions import DIRECTIONS, SPEEDS, STRENGTHS
from final_benchmark.controlled import base_payload, make_plan

# Chords cross the WEST/east cell boundary with, against and across the wind.
CHORDS = (((-1.5, -.5), (2.5, 2.5)), ((2.5, 2.5), (-1.5, -.5)), ((-1.5, 2.5), (2.5, -.5)),
          ((-1, 1), (2, 1)), ((1, -.5), (1, 2.5)))


def uniform(wind):
    p = base_payload('diagonal_control', [('A', [1, 1], 10)], list(SPEEDS), alpha=0)
    p['incumbent'], p['reserve_paths'] = make_plan(p, {'U1': ['A']})
    for projection in ('previous', 'received'):
        p['wind'][projection]['values'] = [[list(wind)], [list(wind)]]
    p['wind']['update_support'] = []
    return Scenario(p)


def closed_form(v, w, d):
    a = v*v-(w[0]**2+w[1]**2)
    along = w[0]*d[0]+w[1]*d[1]
    return (math.sqrt(along*along+a*(d[0]**2+d[1]**2))-along)/a


def reach(v, w, d, t):
    """|d - w t|^2 - (v t)^2: nonnegative before arrival, nonpositive after."""
    v, t = Fraction(str(v)), Fraction(t)
    w, d = [Fraction(str(x)) for x in w], [Fraction(str(x)) for x in d]
    return (d[0]-w[0]*t)**2+(d[1]-w[1]*t)**2-(v*t)**2


def wind(direction, strength):
    unit = [Fraction(c) for c in direction]
    assert unit[0]**2+unit[1]**2 == 1
    return [float(Fraction(strength)*c) for c in unit]


@pytest.mark.parametrize('direction', DIRECTIONS)
def test_chord_duration_encloses_the_closed_form(direction):
    for strength in STRENGTHS:
        w = wind(direction, strength)
        scenario = uniform(w)
        for j, v in enumerate(SPEEDS, 1):
            for a, b in CHORDS:
                d = (b[0]-a[0], b[1]-a[1])
                lo, hi = stationary_duration(scenario, f'U{j}', [list(a), list(b)])
                assert reach(v, w, d, lo) >= 0 >= reach(v, w, d, hi)
                assert hi-lo <= Fraction(1, 10**15)
                assert abs(float(lo)-closed_form(v, w, d)) <= 1e-12*max(1., float(hi))


@pytest.mark.parametrize('direction', DIRECTIONS[4:])
def test_all_path_lower_bound_is_valid_and_tight(direction):
    w = wind(direction, '3/5')
    scenario = uniform(w)
    for a, b in CHORDS[:3]:
        d = (b[0]-a[0], b[1]-a[1])
        certificate = propose_potential(scenario, 'U1', list(a), list(b), 2)
        lower = Fraction(certificate['lower'])
        assert verify_potential(scenario, 'U1', certificate)
        assert reach(1, w, d, lower) >= 0
        assert closed_form(1, w, d)-float(lower) <= 1e-6
