"""
Shared belief state B(t) and typed information-event updates
(manuscript sec: information).

  b_ik(t) = [mu_ik, sigma_ik, gamma_i, eta_i]      (eq:belief_tuple)
  B(t)    = { b_ik : v_i in V_hat(t) }             (eq:shared_belief)
  d_tilde = mu + rho sigma                         (eq:risk_adjusted_demand)

P1 / P4 use a confidence-aware Kalman-style update (eq:p1_update):
  K = sigma^2 / (sigma^2 + sigma_obs^2 / gamma_report)  in [0, 1]
  mu    <- mu + K (y - mu),   truncated at 0
  sigma <- sqrt(1 - K) * sigma
  gamma <- gamma_report,  last-report time <- t  (so eta_i(t) = t - t_report)

P2 inserts a node into V_hat with its report content (eq:p2_node_reveal);
the demand-onset time is recorded separately from the report time so the
waiting age of newly revealed demand is not conflated with discovery time.

P3 never touches the belief (eq:p3_stale_belief) — mutations are latent.

f_hat age approximation (manuscript sec: urgency — "the age of the oldest or
mean outstanding demand may be used as a controlled approximation"): the
belief tracks a per-node-commodity estimated onset time; the planning age is
  oldest:  a_hat = t - est_onset
  mean:    a_hat = 0.5 (t - est_onset)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

import numpy as np

from .params import N_COMMODITIES, BeliefParams


# ---------------------------------------------------------------------------
@dataclass
class BeliefEntry:
    """Belief tuple for one known node (all commodities): eq:belief_tuple."""

    mu: np.ndarray                     # estimated residual demand
    sigma: np.ndarray                  # estimation uncertainty
    gamma: float                       # report confidence in [0, 1]
    t_last_report: float               # eta_i(t) = t - t_last_report
    est_onset: np.ndarray              # estimated demand-onset time per commodity
    reported_vulnerability: float = 1.0
    t_last_generation: float = 0.0

    def eta(self, t: float) -> float:
        return t - self.t_last_report


# ---------------------------------------------------------------------------
class BeliefState:
    """Command-center shared belief over the known node set V_hat(t)."""

    def __init__(self, params: BeliefParams):
        self.p = params
        self.entries: Dict[int, BeliefEntry] = {}

    # -- membership -----------------------------------------------------
    @property
    def known(self) -> Set[int]:
        """V_hat(t): node indices currently known to the command center (C1)."""
        return set(self.entries.keys())

    def is_known(self, i: int) -> bool:
        return i in self.entries

    # -- planning quantities ---------------------------------------------
    def d_tilde(self, i: int) -> np.ndarray:
        """Risk-adjusted demand surrogate d_tilde = mu + rho sigma (eq:risk_adjusted_demand)."""
        e = self.entries[i]
        return np.maximum(e.mu + self.p.rho * e.sigma, 0.0)

    def age_hat(self, i: int, t: float) -> np.ndarray:
        """f_hat age per commodity under the configured approximation mode."""
        e = self.entries[i]
        raw = np.maximum(t - e.est_onset, 0.0)
        if self.p.belief_age_mode == "mean":
            return 0.5 * raw
        return raw                      # "oldest"

    def vulnerability(self, i: int) -> float:
        """Latest controller-visible vulnerability assessment for node ``i``."""
        return self.entries[i].reported_vulnerability

    # -- event updates ----------------------------------------------------
    def reveal(self, i: int, mu0: np.ndarray, sigma0: np.ndarray,
               gamma0: float, onset_time: float, t: float,
               reported_vulnerability: Optional[float] = None,
               generation_time: Optional[float] = None) -> None:
        """P2: V_hat <- V_hat U {v_j} with report content (eq:p2_node_reveal)."""
        self.entries[i] = BeliefEntry(
            mu=np.maximum(np.asarray(mu0, dtype=float), 0.0),
            sigma=np.maximum(np.asarray(sigma0, dtype=float), 0.0),
            gamma=float(np.clip(gamma0, 0.0, 1.0)),
            t_last_report=t,
            est_onset=np.full(N_COMMODITIES, float(onset_time)),
            reported_vulnerability=(
                1.0
                if reported_vulnerability is None
                else float(reported_vulnerability)
            ),
            t_last_generation=(
                float(t) if generation_time is None else float(generation_time)
            ),
        )

    def kalman_gain(self, i: int, gamma_report: float, sigma_obs: float) -> np.ndarray:
        """K_ik in [0,1] from prior uncertainty and report confidence (eq:p1_update)."""
        e = self.entries[i]
        g = max(float(gamma_report), 1e-6)
        prior_var = e.sigma ** 2
        obs_var = (sigma_obs ** 2) / g
        denom = prior_var + obs_var
        K = np.where(denom > 1e-12, prior_var / denom, 0.0)
        return np.clip(K, 0.0, 1.0)

    def apply_report(self, i: int, y: np.ndarray, gamma_report: float,
                     t: float, sigma_obs: Optional[float] = None,
                     generation_time: Optional[float] = None) -> None:
        """
        P1 / P4 confidence-aware update (eq:p1_update, eq:p4_report):
        mu <- mu + K (y - mu). sigma_obs = 0 with gamma = 1 reproduces the
        exact-synchronization special case mu <- d, sigma <- 0 (eq:p4_exact_case).
        """
        if i not in self.entries:
            return
        e = self.entries[i]
        s_obs = self.p.sigma_obs if sigma_obs is None else float(sigma_obs)
        if s_obs <= 1e-12:
            K = np.ones(N_COMMODITIES)
        else:
            K = self.kalman_gain(i, gamma_report, s_obs)
        y = np.maximum(np.asarray(y, dtype=float), 0.0)
        prev_mu = e.mu.copy()
        e.mu = np.maximum(e.mu + K * (y - e.mu), 0.0)
        e.sigma = np.sqrt(np.maximum(1.0 - K, 0.0)) * e.sigma
        e.gamma = float(np.clip(gamma_report, 0.0, 1.0))
        e.t_last_report = t
        e.t_last_generation = (
            float(t) if generation_time is None else float(generation_time)
        )
        # Age re-anchoring: where the belief was empty and the report reveals
        # positive demand, the onset is unknown to the command center — the
        # report time is the conservative (youngest) estimate.
        e.est_onset = np.where((prev_mu <= 1e-9) & (e.mu > 1e-9), t, e.est_onset)

    def apply_delivery(
        self, i: int, x: np.ndarray, t: float,
        attempted: Optional[np.ndarray] = None,
    ) -> None:
        """
        Own-fleet fulfillment is observed by the command center. Normally
        ``mu <- [mu - x]^+`` with unchanged uncertainty. If a site accepts
        less than the attempted handoff, that shortfall is an exact service
        observation of zero residual demand for the affected commodities;
        no latent state is queried.
        """
        if i not in self.entries:
            return
        e = self.entries[i]
        delivered = np.maximum(np.asarray(x, dtype=float), 0.0)
        e.mu = np.maximum(e.mu - delivered, 0.0)
        if attempted is not None:
            requested = np.maximum(
                np.asarray(attempted, dtype=float), 0.0,
            )
            observed_empty = delivered < requested - 1e-9
            e.mu = np.where(observed_empty, 0.0, e.mu)
            e.sigma = np.where(observed_empty, 0.0, e.sigma)
        # If believed demand is fully cleared, future demand estimates start fresh.
        e.est_onset = np.where(e.mu <= 1e-9, t, e.est_onset)

    # -- summaries ---------------------------------------------------------
    def total_d_tilde(self) -> float:
        return float(sum(self.d_tilde(i).sum() for i in self.entries))

    def snapshot_mu(self) -> Dict[int, np.ndarray]:
        return {i: e.mu.copy() for i, e in self.entries.items()}
