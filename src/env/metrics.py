"""
Episode objectives (manuscript sec: objective).

  J_dep_true    eq:true_objective     — evaluated against the latent truth
  J_dep_belief  eq:belief_objective   — the controller's operational objective
  J_energy, J_risk, J_compute         — composite terms (eq:composite_objective)
  J_fair                              — max / percentile / Gini of node-level
                                        cumulative true deprivation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np


@dataclass
class EpisodeMetrics:
    J_dep_true: float = 0.0
    J_dep_belief: float = 0.0
    J_energy: float = 0.0            # total energy consumed [Wh]
    J_risk: float = 0.0              # total route-risk exposure
    n_resolves: int = 0              # J_compute proxy (number of ALNS re-solves)
    delivered_units: np.ndarray = field(default_factory=lambda: np.zeros(4))
    generated_units: np.ndarray = field(default_factory=lambda: np.zeros(4))
    per_node_dep_true: Dict[int, float] = field(default_factory=dict)
    termination_reason: str = ""
    n_events: int = 0
    n_decisions: int = 0

    # ------------------------------------------------------------------
    def add_true_deprivation(self, node: int, value: float) -> None:
        self.J_dep_true += value
        self.per_node_dep_true[node] = self.per_node_dep_true.get(node, 0.0) + value

    def fairness(self, mode: str = "gini", percentile: float = 90.0) -> float:
        """J_fair over per-node cumulative true deprivation (sec: objective)."""
        vals = np.array(sorted(self.per_node_dep_true.values()))
        if len(vals) == 0:
            return 0.0
        if mode == "max":
            return float(vals.max())
        if mode == "percentile":
            return float(np.percentile(vals, percentile))
        # Gini coefficient
        if vals.sum() <= 1e-12:
            return 0.0
        n = len(vals)
        cum = np.cumsum(vals)
        return float((n + 1 - 2.0 * (cum / cum[-1]).sum()) / n)

    def composite(self, zeta_E: float = 0.0, zeta_R: float = 0.0,
                  zeta_F: float = 0.0, zeta_C: float = 0.0,
                  fair_mode: str = "gini") -> float:
        """J = J_dep_true + z_E J_energy + z_R J_risk + z_F J_fair + z_C J_compute."""
        return (self.J_dep_true + zeta_E * self.J_energy + zeta_R * self.J_risk
                + zeta_F * self.fairness(fair_mode) + zeta_C * self.n_resolves)

    def fill_rate(self) -> float:
        g = self.generated_units.sum()
        return float(self.delivered_units.sum() / g) if g > 0 else 1.0

    def summary(self) -> Dict:
        return {
            "J_dep_true": self.J_dep_true,
            "J_dep_belief": self.J_dep_belief,
            "J_energy": self.J_energy,
            "J_risk": self.J_risk,
            "n_resolves": self.n_resolves,
            "J_fair_gini": self.fairness("gini"),
            "J_fair_max": self.fairness("max"),
            "fill_rate": self.fill_rate(),
            "delivered_units": self.delivered_units.tolist(),
            "termination_reason": self.termination_reason,
            "n_events": self.n_events,
            "n_decisions": self.n_decisions,
        }
