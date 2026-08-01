"""Deprivation-cost tests: closed form vs numerical quadrature (sec: urgency)."""

import numpy as np
import pytest

from env.deprivation import (assignment_value, belief_deprivation_integral,
                             belief_deprivation_rate, belief_urgency,
                             expected_deprivation_avoided, f_waiting,
                             f_waiting_integral, f_waiting_rate,
                             true_deprivation_integral, true_deprivation_rate,
                             true_urgency)
from env.entities import Cohort


def test_f_zero_at_zero():
    # eq:waiting_cost_function: f_k(0) = 0
    assert f_waiting(0.0, 1.3, 0.4) == 0.0
    assert np.all(f_waiting(np.zeros(4), np.ones(4), np.ones(4)) == 0.0)


def test_f_nondecreasing():
    a = np.linspace(0, 10, 100)
    v = f_waiting(a, 0.7, 0.25)
    assert np.all(np.diff(v) > 0)


def test_closed_form_integral_vs_quadrature():
    trapezoid = getattr(np, "trapezoid", None) or np.trapz  # numpy 2.x rename
    # int_0^dt alpha (e^{kappa (a0+s)} - 1) ds via dense trapezoid
    for alpha, kappa, a0, dt in [(1.0, 0.35, 0.0, 2.0), (0.5, 0.1, 3.0, 5.0),
                                 (2.0, 0.6, 1.5, 0.7), (1.0, 0.2, 0.0, 12.0)]:
        s = np.linspace(0.0, dt, 200001)
        quad = trapezoid(f_waiting(a0 + s, alpha, kappa), s)
        closed = f_waiting_integral(a0, dt, alpha, kappa)
        assert closed == pytest.approx(quad, rel=1e-8)


def test_integral_zero_interval():
    assert f_waiting_integral(2.0, 0.0, 1.0, 0.3) == 0.0


def test_true_deprivation_rate_and_integral():
    lam = np.array([4.0, 2.0, 3.0, 1.0])
    alp = np.ones(4)
    kap = np.array([0.35, 0.2, 0.3, 0.1])
    cohorts = [[Cohort(0.0, 2.0)], [], [Cohort(1.0, 3.0), Cohort(2.0, 1.0)], []]
    t = 4.0
    # eq:true_deprivation: nu * sum lambda_k q f_k(age)
    expected = 1.5 * (4.0 * 2.0 * f_waiting(4.0, 1.0, 0.35)
                      + 3.0 * 3.0 * f_waiting(3.0, 1.0, 0.3)
                      + 3.0 * 1.0 * f_waiting(2.0, 1.0, 0.3))
    assert true_deprivation_rate(1.5, cohorts, t, lam, alp, kap) \
        == pytest.approx(expected)
    # integral consistency: d/dt of integral == rate
    dt = 1e-6
    integ = true_deprivation_integral(1.5, cohorts, t, dt, lam, alp, kap)
    assert integ / dt == pytest.approx(expected, rel=1e-4)


def test_belief_deprivation_and_urgency():
    lam = np.array([4.0, 2.0, 3.0, 1.0])
    alp = np.ones(4)
    kap = np.array([0.35, 0.2, 0.3, 0.1])
    d_tilde = np.array([2.0, 0.0, 1.0, 0.0])
    age = np.array([3.0, 0.0, 1.0, 0.0])
    rate = belief_deprivation_rate(2.0, d_tilde, age, lam, alp, kap)
    expected = 2.0 * (4.0 * 2.0 * f_waiting(3.0, 1.0, 0.35)
                      + 3.0 * 1.0 * f_waiting(1.0, 1.0, 0.3))
    assert rate == pytest.approx(expected)
    # eq:dynamic_urgency: urgency equals the time derivative of the rate's integral
    dt = 1e-6
    integ = belief_deprivation_integral(2.0, d_tilde, age, dt, lam, alp, kap)
    assert integ / dt == pytest.approx(rate, rel=1e-4)
    U = belief_urgency(2.0, d_tilde, age, lam, alp, kap)
    num = (belief_deprivation_rate(2.0, d_tilde, age + dt, lam, alp, kap) - rate) / dt
    assert U == pytest.approx(num, rel=1e-4)


def test_assignment_value():
    # eq:assignment_value: V = E[dC] - mu_E E - mu_R R
    assert assignment_value(10.0, 100.0, 5.0, 0.01, 0.1) \
        == pytest.approx(10.0 - 1.0 - 0.5)


def test_expected_deprivation_avoided_monotone_in_urgency():
    lam = np.array([4.0, 2.0, 3.0, 1.0])
    alp = np.ones(4)
    kap = np.array([0.35, 0.2, 0.3, 0.1])
    x = np.array([1.0, 0.0, 0.0, 0.0])
    young = expected_deprivation_avoided(1.0, x, np.zeros(4), 0.1, 10.0, lam, alp, kap)
    old = expected_deprivation_avoided(1.0, x, np.full(4, 5.0), 0.1, 10.0, lam, alp, kap)
    assert old > young > 0
    # arriving after the horizon avoids nothing
    assert expected_deprivation_avoided(1.0, x, np.zeros(4), 11.0, 10.0,
                                        lam, alp, kap) == 0.0
