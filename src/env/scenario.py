"""
Scenario container: the seeded dynamic "map".

A Scenario holds everything exogenous — node geography and vulnerability,
initial demand cohorts, the full pre-sampled information-event timeline
(P1 corrections, P2 reveals, P3 mutations), route-availability changes,
hazard/wind field specifications, and depot inventory/replenishment — so a
seed fully determines the world independent of the policy. Only P4 reports
are policy-dependent and are sampled online from a dedicated RNG stream
whose seed is stored here.

The same file drives both training (UAMTVRPIUEnv.reset) and the map
visualizations (scripts/create_map.py). ``passive_truth_at``/``passive_belief_at``
evaluate the no-fleet evolution of the map for visualization without
instantiating the environment.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from .params import N_COMMODITIES, EnvParams
from .belief import BeliefState
from .entities import NodeTruth
from .graph import DynamicFields


# ---------------------------------------------------------------------------
@dataclass
class ScenarioNode:
    """One physical demand node with its P2 reveal report content."""

    idx: int
    x: float
    y: float
    nu: float                            # vulnerability nu_i
    onset_time: float                    # physical demand-onset time
    reveal_time: float                   # P2 report-arrival time (0 => initially known)
    d0: List[float]                      # true initial demand (units per commodity)
    mu0: List[float]                     # reported/assessed initial estimate
    sigma0: List[float]                  # initial uncertainty
    gamma0: float                        # initial report confidence
    nu_reported: Optional[float] = None  # controller-visible vulnerability


@dataclass
class P1Report:
    """Pre-sampled P1 demand correction: y = d(t) + eps (eq:p1_observation).

    Only the noise is pre-sampled; y is formed online because d(t) depends on
    deliveries made before the report fires."""

    t: float
    node: int
    eps: List[float]
    gamma: float


@dataclass
class P3Mutation:
    """Pre-sampled latent mutation Delta d >= 0 (eq:p3_mutation)."""

    t: float
    node: int
    delta_d: List[float]


@dataclass
class AvailabilityChange:
    """Pre-sampled availability flip of edge (i, j); i/j = -1 denotes the depot."""

    t: float
    i: int
    j: int
    available: bool


@dataclass
class Replenishment:
    """Depot replenishment R0_k(t) (eq:inventory_transition)."""

    t: float
    R: List[float]


# ---------------------------------------------------------------------------
@dataclass
class Scenario:
    seed: int
    params: Dict                              # EnvParams.to_dict()
    depot: List[float]                        # v0 position
    nodes: List[ScenarioNode]
    p1_reports: List[P1Report]
    p3_mutations: List[P3Mutation]
    avail_changes: List[AvailabilityChange]
    replenishments: List[Replenishment]
    hazard_bumps: List[dict]
    wind_spec: dict
    S0_init: List[float]                      # depot stock S0_k(0)
    p4_seed: int                              # RNG stream for online P4 sampling
    r_feasible: float                         # conservative service radius used

    # ------------------------------------------------------------------
    def env_params(self) -> EnvParams:
        return EnvParams.from_dict(self.params)

    def fields(self) -> DynamicFields:
        return DynamicFields(self.hazard_bumps, self.wind_spec)

    def node_positions(self) -> np.ndarray:
        return np.array([[n.x, n.y] for n in self.nodes], dtype=float)

    # -- serialization ---------------------------------------------------
    def to_dict(self) -> Dict:
        return dataclasses.asdict(self)

    def to_json(self, path: str) -> str:
        payload = self.to_dict()
        payload["content_hash"] = self.content_hash()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1)
        return path

    @classmethod
    def from_dict(cls, d: Dict) -> "Scenario":
        d = dict(d)
        d.pop("content_hash", None)
        d["nodes"] = [ScenarioNode(**n) for n in d["nodes"]]
        d["p1_reports"] = [P1Report(**r) for r in d["p1_reports"]]
        d["p3_mutations"] = [P3Mutation(**m) for m in d["p3_mutations"]]
        d["avail_changes"] = [AvailabilityChange(**a) for a in d["avail_changes"]]
        d["replenishments"] = [Replenishment(**r) for r in d["replenishments"]]
        return cls(**d)

    @classmethod
    def from_json(cls, path: str) -> "Scenario":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def content_hash(self) -> str:
        """Reproducibility check: sha256 over the canonical JSON encoding."""
        canonical = json.dumps(self.to_dict(), sort_keys=True,
                               separators=(",", ":"), default=float)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Passive (no-fleet) evolution — used by create_map visualizations.
    # ------------------------------------------------------------------
    def build_truth_nodes(self) -> List[NodeTruth]:
        """Instantiate NodeTruth objects with their initial cohorts (at onset)."""
        out = []
        for n in self.nodes:
            nt = NodeTruth(idx=n.idx, pos=np.array([n.x, n.y]), nu=n.nu,
                           onset_time=n.onset_time, reveal_time=n.reveal_time)
            for k in range(N_COMMODITIES):
                nt.add_cohort(k, n.d0[k], n.onset_time)
            out.append(nt)
        return out

    def passive_truth_at(self, t: float) -> List[NodeTruth]:
        """True demand state at time t with no deliveries: initial cohorts
        (for nodes with onset <= t) plus all P3 mutations up to t."""
        nodes = []
        for n in self.nodes:
            nt = NodeTruth(idx=n.idx, pos=np.array([n.x, n.y]), nu=n.nu,
                           onset_time=n.onset_time, reveal_time=n.reveal_time)
            if n.onset_time <= t:
                for k in range(N_COMMODITIES):
                    nt.add_cohort(k, n.d0[k], n.onset_time)
            nodes.append(nt)
        for m in self.p3_mutations:
            if m.t <= t and self.nodes[m.node].onset_time <= t:
                for k in range(N_COMMODITIES):
                    nodes[m.node].add_cohort(k, m.delta_d[k], m.t)
        return nodes

    def passive_belief_at(self, t: float) -> BeliefState:
        """Belief state at time t with no deliveries: initial assessments,
        P2 reveals up to t, and P1 corrections applied in time order."""
        p = self.env_params()
        belief = BeliefState(p.belief)
        truth = {n.idx: n for n in self.passive_truth_at(t)}  # for forming y = d + eps
        events: List[Tuple[float, int, object]] = []
        for n in self.nodes:
            if n.reveal_time <= t:
                events.append((n.reveal_time, 0, n))
        for r in self.p1_reports:
            if r.t <= t:
                events.append((r.t, 1, r))
        events.sort(key=lambda e: (e[0], e[1]))
        # replay in order, recomputing the passive truth at each report time
        for et, _, obj in events:
            if isinstance(obj, ScenarioNode):
                belief.reveal(obj.idx, np.array(obj.mu0), np.array(obj.sigma0),
                              obj.gamma0, obj.onset_time, et,
                              obj.nu if obj.nu_reported is None else obj.nu_reported)
            else:
                truth_nodes = self.passive_truth_at(et)
                d = truth_nodes[obj.node].demand_vector()
                y = np.maximum(d + np.array(obj.eps), 0.0)
                belief.apply_report(obj.node, y, obj.gamma, et)
        return belief

    def availability_at(self, t: float) -> Dict[Tuple[int, int], bool]:
        """Edge availability map at time t from the pre-sampled flip list."""
        state: Dict[Tuple[int, int], bool] = {}
        for a in sorted(self.avail_changes, key=lambda a: a.t):
            if a.t <= t:
                state[(a.i, a.j)] = a.available
        return state
