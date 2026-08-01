"""
Deprivation cost, urgency, and assignment value (manuscript sec: urgency).

Implements:
  eq:waiting_cost_function   f_k(a) = alpha_k (e^{kappa_k a} - 1)
  eq:true_deprivation        C_i^dep,true(t)  (cohort-resolved, latent truth)
  eq:belief_deprivation      C_hat_i^dep(t)   (belief-side, d_tilde and f_hat)
  eq:dynamic_urgency         U_i = dC/dt, U_hat_i = dC_hat/dt
  eq:assignment_value        V_ui = E[Delta C_dep] - mu_E E_ui - mu_R R_ui

plus the *closed-form* interval integral used by the event-interval reward
(eq:event_reward) and the true objective (eq:true_objective):

  int_0^D f(a0 + s) ds = alpha [ e^{kappa a0} (e^{kappa D} - 1) / kappa - D ]

so no numerical quadrature is required anywhere.
"""

from __future__ import annotations

import numpy as np


# ---------------------------------------------------------------------------
# Waiting-cost function and its exact interval integral
# ---------------------------------------------------------------------------

def f_waiting(a, alpha, kappa):
    """f_k(a) = alpha_k (e^{kappa_k a} - 1), f(0) = 0   (eq:waiting_cost_function)."""
    return alpha * (np.exp(kappa * np.maximum(a, 0.0)) - 1.0)


def f_waiting_rate(a, alpha, kappa):
    """f_k'(a) = alpha_k kappa_k e^{kappa_k a} — used for urgency U_i (eq:dynamic_urgency)."""
    return alpha * kappa * np.exp(kappa * np.maximum(a, 0.0))


def f_waiting_integral(a0, dt, alpha, kappa):
    """
    Exact integral of the waiting cost over an event interval:
        int_0^dt f(a0 + s) ds
      = alpha [ e^{kappa a0} (e^{kappa dt} - 1) / kappa - dt ].
    Vectorized over any broadcastable combination of arguments.
    """
    a0 = np.maximum(a0, 0.0)
    dt = np.maximum(dt, 0.0)
    return alpha * (np.exp(kappa * a0) * np.expm1(kappa * dt) / kappa - dt)


# ---------------------------------------------------------------------------
# True (latent, cohort-resolved) deprivation
# ---------------------------------------------------------------------------

def true_deprivation_rate(nu: float, cohorts_by_k, t: float,
                          lambda_k, alpha_k, kappa_k) -> float:
    """
    C_i^dep,true(t) = nu_i sum_k sum_c lambda_k q_ikc f_k(a_ikc)   (eq:true_deprivation).

    ``cohorts_by_k`` is a length-4 sequence of cohort lists; each cohort
    exposes .q and .tau_arr (age a = t - tau_arr, eq:cohort_age).
    """
    total = 0.0
    for k, cohorts in enumerate(cohorts_by_k):
        for c in cohorts:
            total += lambda_k[k] * c.q * f_waiting(t - c.tau_arr, alpha_k[k], kappa_k[k])
    return nu * total


def true_deprivation_integral(nu: float, cohorts_by_k, t0: float, dt: float,
                              lambda_k, alpha_k, kappa_k) -> float:
    """
    Exact int_{t0}^{t0+dt} C_i^dep,true(t) dt for cohorts constant over the
    interval (true between consecutive events by construction).
    """
    if dt <= 0.0:
        return 0.0
    total = 0.0
    for k, cohorts in enumerate(cohorts_by_k):
        for c in cohorts:
            total += lambda_k[k] * c.q * f_waiting_integral(
                t0 - c.tau_arr, dt, alpha_k[k], kappa_k[k])
    return nu * total


def true_urgency(nu: float, cohorts_by_k, t: float,
                 lambda_k, alpha_k, kappa_k) -> float:
    """U_i(t) = dC_i^dep,true/dt = nu sum_k sum_c lambda_k q f_k'(a)   (eq:dynamic_urgency)."""
    total = 0.0
    for k, cohorts in enumerate(cohorts_by_k):
        for c in cohorts:
            total += lambda_k[k] * c.q * f_waiting_rate(t - c.tau_arr, alpha_k[k], kappa_k[k])
    return nu * total


# ---------------------------------------------------------------------------
# Belief-side deprivation (d_tilde with estimated ages, eq:belief_deprivation)
# ---------------------------------------------------------------------------

def belief_deprivation_rate(nu: float, d_tilde: np.ndarray, age_hat: np.ndarray,
                            lambda_k, alpha_k, kappa_k) -> float:
    """C_hat_i(t) = nu_i sum_k lambda_k d_tilde_ik f_hat_ik   (eq:belief_deprivation)."""
    return float(nu * np.sum(lambda_k * d_tilde * f_waiting(age_hat, alpha_k, kappa_k)))


def belief_deprivation_integral(nu: float, d_tilde: np.ndarray, age_hat0: np.ndarray,
                                dt: float, lambda_k, alpha_k, kappa_k) -> float:
    """Exact int over [t, t+dt) of C_hat_i with d_tilde constant and ages advancing."""
    if dt <= 0.0:
        return 0.0
    return float(nu * np.sum(
        lambda_k * d_tilde * f_waiting_integral(age_hat0, dt, alpha_k, kappa_k)))


def belief_urgency(nu: float, d_tilde: np.ndarray, age_hat: np.ndarray,
                   lambda_k, alpha_k, kappa_k) -> float:
    """U_hat_i(t) = dC_hat_i/dt   (eq:dynamic_urgency)."""
    return float(nu * np.sum(lambda_k * d_tilde * f_waiting_rate(age_hat, alpha_k, kappa_k)))


# ---------------------------------------------------------------------------
# Accessibility-aware assignment value (eq:assignment_value)
# ---------------------------------------------------------------------------

def expected_deprivation_avoided(nu: float, x_hat: np.ndarray, age_hat_now: np.ndarray,
                                 tau_ui: float, horizon_remaining: float,
                                 lambda_k, alpha_k, kappa_k) -> float:
    """
    E_B[ Delta C_i^dep(t + tau_ui) ]: the deprivation the prospective delivery
    x_hat (units per commodity) would otherwise accrue from the arrival time
    t + tau_ui to the end of the horizon, evaluated under the belief.

        Delta C = nu sum_k lambda_k x_hat_k int_0^{H - tau} f_k(a_hat + tau + s) ds
    """
    span = max(horizon_remaining - tau_ui, 0.0)
    if span <= 0.0:
        return 0.0
    return float(nu * np.sum(
        lambda_k * x_hat * f_waiting_integral(age_hat_now + tau_ui, span, alpha_k, kappa_k)))


def assignment_value(delta_C_dep: float, E_ui: float, R_ui: float,
                     mu_E: float, mu_R: float) -> float:
    """V_ui = E[Delta C_dep] - mu_E E_ui - mu_R R_ui   (eq:assignment_value)."""
    return delta_C_dep - mu_E * E_ui - mu_R * R_ui
