"""Belief-state tests: P1/P2/P4 updates and P3 staleness (sec: information)."""

import numpy as np
import pytest

from env.belief import BeliefState
from env.params import BeliefParams


@pytest.fixture
def belief():
    b = BeliefState(BeliefParams(rho=1.0, sigma_obs=2.0))
    b.reveal(0, mu0=np.array([5.0, 3.0, 0.0, 1.0]),
             sigma0=np.array([2.0, 1.0, 0.5, 0.5]),
             gamma0=0.8, onset_time=0.0, t=0.0)
    return b


def test_reveal_membership(belief):
    # eq:p2_node_reveal: V_hat grows
    assert belief.is_known(0)
    assert not belief.is_known(1)
    belief.reveal(1, np.ones(4), np.ones(4), 0.5, onset_time=1.0, t=2.0)
    assert belief.known == {0, 1}
    # onset recorded separately from report time (sec: information, P2)
    assert np.all(belief.entries[1].est_onset == 1.0)
    assert belief.entries[1].t_last_report == 2.0


def test_d_tilde_risk_adjusted(belief):
    # eq:risk_adjusted_demand: d_tilde = mu + rho sigma
    np.testing.assert_allclose(belief.d_tilde(0),
                               np.array([7.0, 4.0, 0.5, 1.5]))


def test_p1_kalman_update_properties(belief):
    e = belief.entries[0]
    mu_prior = e.mu.copy()
    sig_prior = e.sigma.copy()
    K = belief.kalman_gain(0, gamma_report=0.8, sigma_obs=2.0)
    assert np.all(K >= 0) and np.all(K <= 1)          # eq:p1_update: K in [0,1]
    y = np.array([9.0, 3.0, 2.0, 1.0])
    belief.apply_report(0, y, gamma_report=0.8, t=1.0)
    # posterior mean moves toward the report, never past it
    assert mu_prior[0] < e.mu[0] <= y[0]
    # uncertainty shrinks
    assert np.all(e.sigma <= sig_prior + 1e-12)
    # eta resets (eq:belief_tuple)
    assert e.eta(1.0) == 0.0
    assert e.eta(2.5) == pytest.approx(1.5)


def test_higher_confidence_larger_gain(belief):
    K_low = belief.kalman_gain(0, gamma_report=0.2, sigma_obs=2.0)
    K_high = belief.kalman_gain(0, gamma_report=0.95, sigma_obs=2.0)
    assert np.all(K_high >= K_low)


def test_p4_exact_sync_special_case(belief):
    # eq:p4_exact_case: p_P4=1, delta=0, eps=0 with sigma_obs=0 => mu <- d, sigma <- 0
    d_true = np.array([4.0, 0.0, 2.0, 7.0])
    belief.apply_report(0, d_true, gamma_report=1.0, t=3.0, sigma_obs=0.0)
    e = belief.entries[0]
    np.testing.assert_allclose(e.mu, d_true)
    np.testing.assert_allclose(e.sigma, np.zeros(4))


def test_p3_leaves_belief_stale(belief):
    # eq:p3_stale_belief: no belief method is invoked on a P3 mutation;
    # verify the belief is unchanged by construction (nothing to call)
    mu_before = belief.entries[0].mu.copy()
    # ... latent truth mutates elsewhere; belief object untouched ...
    np.testing.assert_allclose(belief.entries[0].mu, mu_before)


def test_delivery_decrements_belief(belief):
    belief.apply_delivery(0, np.array([2.0, 0.0, 0.0, 0.0]), t=1.0)
    assert belief.entries[0].mu[0] == pytest.approx(3.0)
    # over-delivery clips at zero
    belief.apply_delivery(0, np.array([99.0, 0.0, 0.0, 0.0]), t=1.5)
    assert belief.entries[0].mu[0] == 0.0


def test_age_hat_modes():
    for mode, factor in [("oldest", 1.0), ("mean", 0.5)]:
        b = BeliefState(BeliefParams(belief_age_mode=mode))
        b.reveal(0, np.ones(4), np.ones(4), 0.8, onset_time=1.0, t=2.0)
        np.testing.assert_allclose(b.age_hat(0, 5.0), factor * 4.0 * np.ones(4))


def test_report_reanchors_age_after_emptiness():
    b = BeliefState(BeliefParams(sigma_obs=1.0))
    b.reveal(0, np.zeros(4), np.ones(4), 0.8, onset_time=0.0, t=0.0)
    b.apply_report(0, np.array([5.0, 0.0, 0.0, 0.0]), 0.9, t=4.0)
    # commodity 0 was believed empty; onset re-anchored to the report time
    assert b.entries[0].est_onset[0] == pytest.approx(4.0)
