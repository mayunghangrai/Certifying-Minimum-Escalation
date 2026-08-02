"""
Model parameters for the UA-MTVRP-IU system model.

Every field is named after the corresponding manuscript symbol
(manuscript/sections/system_model.tex). Units: km, hours, Wh, kg.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

N_COMMODITIES = 4  # |K| = 4: medical, food, water, shelter
COMMODITY_NAMES = ("medical", "food", "water", "shelter")


# ---------------------------------------------------------------------------
@dataclass
class PhysicsParams:
    """UAV fleet physics (sec: uav_fleet)."""

    W_max: float = 2.5        # payload capacity [kg]        (eq:payload_capacity)
    m0: float = 4.0           # empty airframe mass [kg]
    B_max: float = 230.0      # battery capacity [Wh]
    e_c: float = 3.125        # propulsion energy coeff [Wh/km/kg] (eq:flight_energy)
    e_v: float = 2.5          # descent-delivery-ascent energy [Wh] (eq:service_energy)
    beta_safe: float = 23.0   # safety energy reserve [Wh]   (eq:safe_return_constraint)
    v_uav: float = 60.0       # cruise speed [km/h] -> tau_ij = L_ij / v_uav


# ---------------------------------------------------------------------------
@dataclass
class CommodityParams:
    """Commodity set K (eq:true_demand_vector) and deprivation shape (eq:waiting_cost_function)."""

    # unit masses w_k [kg/unit]                       (eq:payload_mass)
    w_k: List[float] = field(default_factory=lambda: [0.25, 0.5, 1.0, 2.5])
    # criticality coefficients lambda_k               (eq:true_deprivation)
    lambda_k: List[float] = field(default_factory=lambda: [4.0, 2.0, 3.0, 1.0])
    # waiting-cost scale alpha_k                      (eq:waiting_cost_function)
    alpha_k: List[float] = field(default_factory=lambda: [1.0, 1.0, 1.0, 1.0])
    # waiting-cost growth rate kappa_k [1/h]          (eq:waiting_cost_function)
    kappa_k: List[float] = field(default_factory=lambda: [0.35, 0.20, 0.30, 0.10])

    def as_arrays(self):
        return (np.asarray(self.w_k), np.asarray(self.lambda_k),
                np.asarray(self.alpha_k), np.asarray(self.kappa_k))


# ---------------------------------------------------------------------------
@dataclass
class BeliefParams:
    """Shared belief state (sec: information)."""

    rho: float = 1.0            # uncertainty aversion in d_tilde = mu + rho*sigma (eq:risk_adjusted_demand)
    sigma_obs: float = 2.0      # report observation noise std [units] (eq:p1_observation)
    # Kalman gain form (config-controlled choice documented in the plan):
    #   K = sigma^2 / (sigma^2 + sigma_obs^2 / gamma)   (eq:p1_update, K in [0,1])
    K_gain_mode: str = "kalman"
    # f_hat age approximation when cohort-level belief is unavailable
    # (manuscript sec: urgency, "oldest or mean outstanding demand"):
    belief_age_mode: str = "oldest"     # "oldest" | "mean"
    sigma0_frac: float = 0.4    # initial sigma as fraction of initial mu
    gamma0_range: List[float] = field(default_factory=lambda: [0.5, 0.9])
    init_report_noise_frac: float = 0.3  # imperfect initial assessment for known nodes


# ---------------------------------------------------------------------------
@dataclass
class EventParams:
    """Typed information events P1-P4 (sec: information) and availability process."""

    # P1 demand-correction reports: Poisson rate per known node [1/h]
    p1_rate: float = 0.15
    # P2 popup revelations: handled via per-node (onset_time, reveal_time) in the scenario
    p2_reveal_window: List[float] = field(default_factory=lambda: [0.05, 0.6])  # fraction of T
    # P3 latent mutations: compound Poisson rate per node [1/h], Gamma marks
    p3_rate: float = 0.08
    p3_gamma_shape: float = 2.0
    p3_gamma_scale: float = 2.0
    # P4 delivery-triggered reports (eq:p4_report)
    p_P4: float = 0.8            # report probability
    delta_P4_mean: float = 0.1   # mean communication delay [h] (exponential)
    sigma_P4: float = 1.0        # P4 report noise std [units]
    # route availability process A_ij(t): closure intervals correlated with hazard
    # Default is information-only. Disruption families opt into a calibrated
    # sparse per-edge rate (0.002 in the manuscript experiments).
    avail_closure_rate: float = 0.0
    avail_closure_dur: List[float] = field(default_factory=lambda: [0.5, 2.0])  # [h] uniform
    avail_hazard_threshold: float = 0.15  # edges with exposure below this never close


# ---------------------------------------------------------------------------
@dataclass
class HybridParams:
    """Hybrid ALNS/MAPPO interface (sec: hybrid_interface) and reward weights (eq:event_reward)."""

    K_max: int = 3               # global re-optimization budget (eq:resolve_budget)
    # plan-divergence weights omega_1..omega_5       (eq:plan_divergence)
    omega: List[float] = field(default_factory=lambda: [1.0, 1.0, 2.0, 2.0, 0.25])
    # reward weights                                  (eq:event_reward)
    xi_E: float = 0.01           # energy [1/Wh]
    xi_R: float = 0.1            # route risk
    xi_C: float = 5.0            # RESOLVE invocation cost
    P_viol: float = 50.0         # infeasible/unsafe action penalty
    # assignment-value weights                        (eq:assignment_value)
    mu_E: float = 0.01
    mu_R: float = 0.1
    # ALNS solver
    alns_iterations: int = 60
    alns_removal_frac: float = 0.3
    route_depth: int = 3         # planned nodes per sortie upper bound


# ---------------------------------------------------------------------------
@dataclass
class MapParams:
    """Seeded scenario/map generation (feasibility-aware, ~12x12 km)."""

    region_km: float = 12.0
    n_nodes: int = 20            # total physical demand nodes (incl. hidden)
    n_hidden: int = 4            # nodes revealed via P2 (subset of n_nodes)
    n_clusters: int = 3
    cluster_std_km: float = 0.9
    feasible_frac: float = 0.95  # nodes placed within feasible_frac * r_max of depot
    min_node_sep_km: float = 0.35
    nu_range: List[float] = field(default_factory=lambda: [0.5, 3.0])
    # initial true demand: Poisson means per commodity [units]
    demand_mean_k: List[float] = field(default_factory=lambda: [2.0, 3.0, 2.5, 0.8])
    # hazard field: Gaussian bumps with decaying amplitude keyframes
    n_hazard_bumps: List[int] = field(default_factory=lambda: [2, 3])   # [min, max]
    hazard_amp_range: List[float] = field(default_factory=lambda: [0.5, 1.5])
    hazard_radius_range: List[float] = field(default_factory=lambda: [1.5, 3.5])
    # path functional weights (eq:feasible_path)
    alpha_h: float = 1.0
    alpha_w: float = 0.3
    path_mode: str = "euclidean"   # "euclidean" | "field_astar"
    astar_grid: int = 48


# ---------------------------------------------------------------------------
@dataclass
class MissionParams:
    """Mission horizon, fleet, depot service and inventory (secs: uav_fleet, depot_inventory)."""

    T: float = 12.0              # planning horizon [h]
    M: int = 3                   # fleet size
    T_load: float = 0.15         # loading time [h]           (eq:turnaround_time)
    T_charge: float = 0.5        # recharge time [h]
    n_depot_bays: int = 2        # finite service capacity -> T_queue
    # depot inventory: S0_k(0) = stock_mult * total initial known demand per k (eq:depot_inventory)
    stock_mult: float = 1.2
    # replenishment events R0_k(t): count over horizon and size as fraction of S0(0)
    n_replenish: int = 2
    replenish_frac: float = 0.35
    gamma_hour: float = 0.98     # SMDP discount per hour: gamma_eff = gamma_hour ** dt
    terminate_on_belief_zero: bool = True


# ---------------------------------------------------------------------------
@dataclass
class EnvParams:
    """Top-level parameter bundle."""

    physics: PhysicsParams = field(default_factory=PhysicsParams)
    commodities: CommodityParams = field(default_factory=CommodityParams)
    belief: BeliefParams = field(default_factory=BeliefParams)
    events: EventParams = field(default_factory=EventParams)
    hybrid: HybridParams = field(default_factory=HybridParams)
    map: MapParams = field(default_factory=MapParams)
    mission: MissionParams = field(default_factory=MissionParams)

    # ------------------------------------------------------------------
    def to_dict(self) -> Dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "EnvParams":
        def _load(klass, sub):
            valid = {f.name for f in dataclasses.fields(klass)}
            return klass(**{k: v for k, v in (sub or {}).items() if k in valid})

        return cls(
            physics=_load(PhysicsParams, d.get("physics")),
            commodities=_load(CommodityParams, d.get("commodities")),
            belief=_load(BeliefParams, d.get("belief")),
            events=_load(EventParams, d.get("events")),
            hybrid=_load(HybridParams, d.get("hybrid")),
            map=_load(MapParams, d.get("map")),
            mission=_load(MissionParams, d.get("mission")),
        )

    @classmethod
    def from_yaml(cls, path: str) -> "EnvParams":
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(yaml.safe_load(f) or {})
