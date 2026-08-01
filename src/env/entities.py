"""
Physical state containers (manuscript secs: demand_model, uav_fleet, depot_inventory).

  Cohort / NodeTruth   demand cohorts q_ikc with first-onset-first-served (FOFS)
                       service (eq:cohort_aggregation,
                       eq:cohort_age, eq:true_demand_transition)
  UAVState             [q_u, ell_u, b_u, m_u, s_u] with modes (eq:uav_state)
  DepotInventory       S0_k(t) with loading/replenishment (eq:inventory_transition, C6)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

import numpy as np

from .params import N_COMMODITIES


# ---------------------------------------------------------------------------
@dataclass
class Cohort:
    """A demand cohort: creation time tau_arr and remaining quantity q (sec: demand_model)."""

    tau_arr: float
    q: float

    def age(self, t: float) -> float:
        """a_ikc(t) = t - tau_arr   (eq:cohort_age)."""
        return t - self.tau_arr


@dataclass
class NodeTruth:
    """
    Latent true state of demand node v_i: position p_i, vulnerability nu_i,
    and cohort-resolved residual demand d_ik(t) = sum_c q_ikc (eq:cohort_aggregation).
    """

    idx: int
    pos: np.ndarray                    # p_i in R^2 (eq:node_position)
    nu: float                          # vulnerability coefficient nu_i > 0
    onset_time: float = 0.0            # physical emergence time (N(t) growth)
    reveal_time: float = 0.0           # P2 report-arrival time (>= onset_time)
    cohorts: List[List[Cohort]] = field(
        default_factory=lambda: [[] for _ in range(N_COMMODITIES)])

    # -- demand queries ------------------------------------------------
    def d(self, k: int) -> float:
        """True residual demand d_ik(t) for commodity k."""
        return sum(c.q for c in self.cohorts[k])

    def demand_vector(self) -> np.ndarray:
        """d_i(t) = [d_i1..d_i4]^T   (eq:true_demand_vector)."""
        return np.array([self.d(k) for k in range(N_COMMODITIES)])

    def oldest_age(self, k: int, t: float) -> float:
        """Age of the oldest active cohort for commodity k (0 if none)."""
        if not self.cohorts[k]:
            return 0.0
        return t - min(c.tau_arr for c in self.cohorts[k])

    # -- transitions ----------------------------------------------------
    def add_cohort(self, k: int, q: float, tau_arr: float) -> None:
        """New demand g_ik / P3 mutation creates a new cohort (eq:p3_mutation)."""
        if q > 0.0:
            self.cohorts[k].append(Cohort(tau_arr=tau_arr, q=float(q)))

    def serve_fofs(self, k: int, amount: float) -> float:
        """
        Apply a delivery under first-onset-first-served (FOFS).

        The oldest demand-onset cohort is depleted first, matching the system
        model. Returns the quantity actually absorbed.
        Returns the quantity actually absorbed (<= min(amount, d_ik)).
        """
        remaining = float(amount)
        served = 0.0
        self.cohorts[k].sort(key=lambda c: c.tau_arr)
        kept: List[Cohort] = []
        for c in self.cohorts[k]:
            if remaining <= 0.0:
                kept.append(c)
                continue
            take = min(c.q, remaining)
            c.q -= take
            remaining -= take
            served += take
            if c.q > 1e-12:
                kept.append(c)
        self.cohorts[k] = kept
        return served

    def serve_fifo(self, k: int, amount: float) -> float:
        """Deprecated compatibility alias for :meth:`serve_fofs`."""
        return self.serve_fofs(k, amount)


# ---------------------------------------------------------------------------
class Mode(Enum):
    """Operational modes m_u(t) (eq:uav_state)."""

    DEPOT = 0
    LOADING = 1
    CHARGING = 2
    FLYING = 3
    DELIVERING = 4
    RETURNING = 5


@dataclass
class UAVState:
    """Physical UAV state s_u(t) = [q_u, ell_u, b_u, m_u, s_u] (eq:uav_state)."""

    idx: int
    pos: np.ndarray                                    # q_u(t)
    ell: np.ndarray = field(
        default_factory=lambda: np.zeros(N_COMMODITIES))   # onboard commodity vector
    b: float = 0.0                                     # remaining battery [Wh]
    mode: Mode = Mode.DEPOT
    s: int = 0                                         # completed-sortie index

    # transit bookkeeping (for event-driven flight and mid-leg diversion)
    origin: Optional[np.ndarray] = None
    dest_node: Optional[int] = None                    # node index; -1 = depot
    depart_time: float = 0.0
    arrive_time: float = 0.0
    leg_energy: float = 0.0                            # energy of current leg
    leg_risk: float = 0.0                              # risk of current leg

    def payload_mass(self, w_k: np.ndarray) -> float:
        """w_u^pay = sum_k w_k ell_uk   (eq:payload_mass)."""
        return float(np.dot(w_k, self.ell))

    def position_at(self, t: float) -> np.ndarray:
        """Interpolated position while flying (used for mid-leg re-decisions)."""
        if self.mode not in (Mode.FLYING, Mode.RETURNING) or self.origin is None:
            return self.pos.copy()
        dur = self.arrive_time - self.depart_time
        if dur <= 1e-12:
            return self.pos.copy()
        frac = np.clip((t - self.depart_time) / dur, 0.0, 1.0)
        return self.origin + frac * (self.pos - self.origin)


# ---------------------------------------------------------------------------
@dataclass
class DepotInventory:
    """Finite depot stock S0_k(t) (eq:depot_inventory)."""

    S0: np.ndarray = field(default_factory=lambda: np.zeros(N_COMMODITIES))

    def can_load(self, y: np.ndarray) -> bool:
        """C6: sum_u y_uk <= S0_k(t^-)   (eq:inventory_constraint)."""
        return bool(np.all(y <= self.S0 + 1e-9))

    def load(self, y: np.ndarray) -> np.ndarray:
        """
        Apply a loading event: S0 <- S0 - y (eq:inventory_transition).
        The requested vector is clipped to available stock; returns what
        was actually loaded.
        """
        actual = np.minimum(np.maximum(y, 0.0), self.S0)
        self.S0 = self.S0 - actual
        return actual

    def replenish(self, R: np.ndarray) -> None:
        """External replenishment R0_k(t) (eq:inventory_transition)."""
        self.S0 = self.S0 + np.maximum(R, 0.0)
