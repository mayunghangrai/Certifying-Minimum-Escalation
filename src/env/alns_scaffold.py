"""
ALNS route-and-loading scaffold Pi^ALNS (manuscript sec: hybrid_interface).

The scaffold specifies, per UAV, a sequence of sorties — node assignments,
visit order, sortie boundaries, per-visit planned deliveries, loading
vectors y_uk, expected service times, and energy-feasibility margins —
computed under the current belief (eq:alns_scaffold). It is an intent prior:
the MAPPO controller may deviate locally (INSERT/SKIP/SWAP/RETURN) or spend
one unit of the re-optimization budget K_rem on a new global solve
(eq:resolve_budget). Plan divergence Delta_plan (eq:plan_divergence) is
computed against snapshots stored at scaffold creation.

Solver: greedy construction by assignment-value density (eq:assignment_value)
+ ALNS improvement (random removal / greedy re-insertion), warm-startable
from the incumbent. Deterministic given its RNG. Sortie energy feasibility is
checked with exact leg masses (every leg carries the payload of all later
visits, eq:sortie_energy).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

import numpy as np

from .deprivation import expected_deprivation_avoided
from .energy import flight_energy, service_energy
from .params import N_COMMODITIES, EnvParams

DEPOT = -1
SERVICE_DWELL = 0.02   # planning estimate of on-site dwell [h]


# ---------------------------------------------------------------------------
@dataclass
class PlannedVisit:
    node: int
    x_plan: np.ndarray                 # planned delivery (units per commodity)
    eta: float = 0.0                   # expected service time

    def clone(self) -> "PlannedVisit":
        return PlannedVisit(self.node, self.x_plan.copy(), self.eta)


@dataclass
class Sortie:
    visits: List[PlannedVisit] = field(default_factory=list)
    y: np.ndarray = field(default_factory=lambda: np.zeros(N_COMMODITIES))
    depart_time: float = 0.0
    energy_est: float = 0.0
    energy_margin: float = 0.0         # battery at start - energy_est - beta_safe

    def clone(self) -> "Sortie":
        s = Sortie(y=self.y.copy(), depart_time=self.depart_time,
                   energy_est=self.energy_est, energy_margin=self.energy_margin)
        s.visits = [v.clone() for v in self.visits]
        return s


@dataclass
class Scaffold:
    plans: Dict[int, List[Sortie]]     # uav -> sorties (Pi^ALNS, eq:alns_scaffold)
    created_t: float = 0.0
    # snapshots for Delta_plan (eq:plan_divergence)
    mu_snapshot: Dict[int, np.ndarray] = field(default_factory=dict)
    urgency_rank_snapshot: List[int] = field(default_factory=list)
    known_snapshot: set = field(default_factory=set)
    inventory_snapshot: np.ndarray = field(
        default_factory=lambda: np.zeros(N_COMMODITIES)
    )
    planned_service_count: int = 0
    uav_position_snapshot: Dict[int, np.ndarray] = field(default_factory=dict)

    def clone(self) -> "Scaffold":
        return Scaffold(
            plans={u: [s.clone() for s in ss] for u, ss in self.plans.items()},
            created_t=self.created_t,
            mu_snapshot={i: m.copy() for i, m in self.mu_snapshot.items()},
            urgency_rank_snapshot=list(self.urgency_rank_snapshot),
            known_snapshot=set(self.known_snapshot),
            inventory_snapshot=self.inventory_snapshot.copy(),
            planned_service_count=self.planned_service_count,
            uav_position_snapshot={
                u: value.copy()
                for u, value in self.uav_position_snapshot.items()
            })

    # -- queries used by the env / action semantics ------------------------
    def planned_nodes(self, u: int) -> List[int]:
        return [v.node for s in self.plans.get(u, []) for v in s.visits]

    def remove_node(self, u: int, node: int) -> Optional[PlannedVisit]:
        """SKIP(i): drop node i from u's plan (first occurrence)."""
        for s in self.plans.get(u, []):
            for idx, v in enumerate(s.visits):
                if v.node == node:
                    return s.visits.pop(idx)
        return None

    def insert_next(self, u: int, node: int, x_plan: np.ndarray) -> None:
        """INSERT(i): make node i the immediate next stop of u's current sortie."""
        sorties = self.plans.setdefault(u, [])
        if not sorties:
            sorties.append(Sortie())
        sorties[0].visits.insert(0, PlannedVisit(node, x_plan.copy()))

    def pop_next(self, u: int) -> Optional[PlannedVisit]:
        """FOLLOW: consume the next planned visit of u's current sortie."""
        ss = self.plans.get(u, [])
        if ss and ss[0].visits:
            return ss[0].visits.pop(0)
        return None

    def peek_next(self, u: int) -> Optional[PlannedVisit]:
        ss = self.plans.get(u, [])
        if ss and ss[0].visits:
            return ss[0].visits[0]
        return None

    def next_planned_nodes(self, u: int, n: int = 3) -> List[int]:
        out = []
        for s in self.plans.get(u, []):
            for v in s.visits:
                out.append(v.node)
                if len(out) >= n:
                    return out
        return out

    def current_sortie_done(self, u: int) -> bool:
        ss = self.plans.get(u, [])
        return not ss or not ss[0].visits

    def advance_sortie(self, u: int) -> Optional[Sortie]:
        """At depot: drop completed leading sorties, return the next (for loading)."""
        ss = self.plans.get(u, [])
        while ss and not ss[0].visits:
            ss.pop(0)
        return ss[0] if ss else None


# ---------------------------------------------------------------------------
@dataclass
class UAVPlanStart:
    """Operational state from which the mutable route suffix begins."""

    uav: int
    pos: np.ndarray
    ell: np.ndarray
    b: float
    ready_time: float
    at_depot: bool

    # True when the planner must use cargo already carried by the UAV.
    payload_committed: bool = False

    # Node used for the first corridor-availability query.
    anchor: int = DEPOT

    @property
    def uses_onboard_payload(self) -> bool:
        return (
            self.payload_committed
            and float(np.sum(self.ell)) > 1e-9
        )          # node context for availability of the first leg


@dataclass
class PlanContext:
    """Belief-side view handed to the planner (never the latent truth)."""

    t: float
    T: float
    params: EnvParams
    d_tilde: Dict[int, np.ndarray]     # per known node
    age_hat: Dict[int, np.ndarray]
    nu: Dict[int, float]
    pos: Dict[int, np.ndarray]
    depot_pos: np.ndarray
    stock: np.ndarray                  # planning copy of S0
    avail: Callable[[int, int], bool]  # avail(i, j) -> A_ij (C2); DEPOT = -1
    risk: Callable[[int, int], float]  # risk(i, j) -> R_ij
    uav_starts: List[UAVPlanStart] = field(default_factory=list)


# ---------------------------------------------------------------------------
def sortie_energy_exact(start_pos: np.ndarray, node_pos: List[np.ndarray],
                        xs: List[np.ndarray], onboard0: np.ndarray,
                        depot_pos: np.ndarray, w_k: np.ndarray,
                        params: EnvParams) -> float:
    """
    Exact sortie energy (eq:sortie_energy): every leg carries the payload of
    all not-yet-delivered visits; return leg flies with the residual mass.
    """
    phys = params.physics
    onboard = onboard0.copy()
    pos = start_pos
    e = 0.0
    for p_i, x in zip(node_pos, xs):
        L = float(np.linalg.norm(p_i - pos))
        e += flight_energy(L, float(np.dot(w_k, onboard)), phys) + service_energy(phys)
        onboard = np.maximum(onboard - x, 0.0)
        pos = p_i
    L_back = float(np.linalg.norm(depot_pos - pos))
    e += flight_energy(L_back, float(np.dot(w_k, onboard)), phys)
    return e


# ---------------------------------------------------------------------------
class ALNSPlanner:
    def __init__(self, params: EnvParams):
        self.p = params

    # -- public -------------------------------------------------------------
    def solve(self, ctx: PlanContext, rng: np.random.Generator,
              warm: Optional[Scaffold] = None,
              frozen_nodes_by_uav: Optional[Dict[int, Set[int]]] = None,
              removal_weights_by_uav_node: Optional[
                  Dict[Tuple[int, int], float]
              ] = None,
              respect_onboard: bool = False) -> Scaffold:
        """Greedy construction (optionally warm-started) + ALNS improvement.

        ``frozen_nodes_by_uav`` is an additive selective-repair contract: when
        supplied, destroy operators may not remove those future node decisions.
        ``removal_weights_by_uav_node`` provides a soft alternative: every
        positive-weight visit remains removable, while larger weights bias the
        destroy operator toward causally related route regions.
        Legacy callers omit it and retain the original ALNS behavior.
        """
        best = self._construct(ctx, warm, respect_onboard=respect_onboard)
        best_val = self._evaluate(best, ctx)
        cur = best
        for _ in range(self.p.hybrid.alns_iterations):
            cand = self._destroy_repair(
                cur,
                ctx,
                rng,
                frozen_nodes_by_uav=frozen_nodes_by_uav,
                removal_weights_by_uav_node=removal_weights_by_uav_node,
            )
            val = self._evaluate(cand, ctx)
            if val > best_val + 1e-9:
                best, best_val = cand, val
                cur = cand
            elif rng.random() < 0.1:   # mild diversification
                cur = cand
        self._finalize(best, ctx)
        return best

    def evaluate_belief_value(self, scaffold: Scaffold, ctx: PlanContext) -> float:
        """Evaluate a scaffold without crediting demand more than once.

        This side-effect-free value is used by the regret screen.  The legacy
        ALNS search objective remains unchanged for backward compatibility.
        """
        return self._evaluate_capped(scaffold, ctx)

    # -- construction ---------------------------------------------------------
    def _construct(self, ctx: PlanContext, warm: Optional[Scaffold],
                   respect_onboard: bool = False) -> Scaffold:
        remaining = {i: d.copy() for i, d in ctx.d_tilde.items() if d.sum() > 1e-9}
        stock = ctx.stock.copy()
        scaffold = Scaffold(plans={s.uav: [] for s in ctx.uav_starts},
                            created_t=ctx.t)
        if warm is not None:
            self._absorb_warm(
                scaffold, warm, remaining, stock, ctx,
                respect_onboard=respect_onboard)
        for start in ctx.uav_starts:
            self._extend_plan(scaffold, start, remaining, stock, ctx)
        return scaffold

    def _absorb_warm(self, scaffold: Scaffold, warm: Scaffold,
                     remaining: Dict[int, np.ndarray], stock: np.ndarray,
                     ctx: PlanContext, respect_onboard: bool = False) -> None:
        """Keep warm-start visits that still address believed demand."""
        starts = {start.uav: start for start in ctx.uav_starts}
        for u, sorties in warm.plans.items():
            if u not in scaffold.plans:
                continue
            start = starts[u]
            onboard = start.ell.copy()
            continuing = (
                respect_onboard
                and start.uses_onboard_payload
            )
            kept: List[Sortie] = []
            for sortie_index, s in enumerate(sorties):
                ns = Sortie()
                for v in s.visits:
                    if v.node not in remaining:
                        continue
                    supply = onboard if continuing and sortie_index == 0 else stock
                    x = np.minimum(
                        np.minimum(v.x_plan, remaining[v.node]), supply)
                    # C4: the absorbed sortie's loading must fit W_max
                    w_k = np.asarray(self.p.commodities.w_k)
                    mass_room = self.p.physics.W_max - float(np.dot(w_k, ns.y))
                    x = self._fit_mass(x, w_k, mass_room,
                                       np.asarray(self.p.commodities.lambda_k))
                    if x.sum() <= 1e-9:
                        continue
                    remaining[v.node] = remaining[v.node] - x
                    if remaining[v.node].sum() <= 1e-9:
                        remaining.pop(v.node)
                    if continuing and sortie_index == 0:
                        onboard = np.maximum(onboard - x, 0.0)
                    else:
                        stock -= x
                    ns.visits.append(PlannedVisit(v.node, x))
                    ns.y = ns.y + x
                if ns.visits:
                    kept.append(ns)
                continuing = False
            scaffold.plans[u] = kept

    def _extend_plan(self, scaffold: Scaffold, start: UAVPlanStart,
                     remaining: Dict[int, np.ndarray], stock: np.ndarray,
                     ctx: PlanContext) -> None:
        """Append sorties for one UAV until nothing valuable/feasible remains."""
        phys = self.p.physics
        w_k, lambda_k, alpha_k, kappa_k = self.p.commodities.as_arrays()
        hyb = self.p.hybrid
        mission = self.p.mission

        # position the cursor after any visits already in the plan (warm start)
        start = self._tail_start(scaffold, start, ctx)
        t_cursor = start.ready_time
        continuing = start.uses_onboard_payload

        for _ in range(12):            # sortie loop (bounded)
            if t_cursor >= ctx.T or not remaining:
                break
            if continuing:
                start_pos, battery, onboard_cap = start.pos, start.b, start.ell.copy()
                anchor = start.anchor
            else:
                start_pos, battery = ctx.depot_pos, phys.B_max
                onboard_cap = None     # limited by stock + W_max instead
                anchor = DEPOT
            visits: List[PlannedVisit] = []
            xs: List[np.ndarray] = []
            node_pos: List[np.ndarray] = []

            for _depth in range(hyb.route_depth):
                best = None            # (score, node, x, tau, eta)
                committed_mass = float(np.dot(w_k, np.sum(xs, axis=0))) if xs else 0.0
                cur_pos = node_pos[-1] if node_pos else start_pos
                cur_anchor = visits[-1].node if visits else anchor
                t_leg0 = t_cursor + sum(
                    float(np.linalg.norm(p - q)) / phys.v_uav + SERVICE_DWELL
                    for p, q in zip(node_pos, [start_pos] + node_pos[:-1]))
                for i, dem in remaining.items():
                    if not ctx.avail(cur_anchor, i):          # C2
                        continue
                    if not ctx.avail(i, DEPOT):               # safe return path
                        continue
                    if continuing:
                        room = np.maximum(onboard_cap - (np.sum(xs, axis=0) if xs else 0.0), 0.0)
                        x = np.floor(np.minimum(dem, room))
                    else:
                        x = np.floor(np.minimum(dem, np.maximum(stock, 0.0)))
                        mass_room = phys.W_max - committed_mass
                        x = self._fit_mass(x, w_k, mass_room, lambda_k)
                    if x.sum() <= 1e-9:
                        continue
                    # C5 / eq:sortie_energy with exact leg masses
                    trial_xs = xs + [x]
                    trial_pos = node_pos + [ctx.pos[i]]
                    onboard0 = onboard_cap if continuing else np.sum(trial_xs, axis=0)
                    e_total = sortie_energy_exact(start_pos, trial_pos, trial_xs,
                                                  onboard0, ctx.depot_pos, w_k, self.p)
                    if battery < e_total + phys.beta_safe:
                        continue
                    L_to = float(np.linalg.norm(ctx.pos[i] - cur_pos))
                    tau = L_to / phys.v_uav
                    eta = t_leg0 + tau
                    if eta >= ctx.T:
                        continue
                    dep_avoid = expected_deprivation_avoided(
                        ctx.nu[i], x, ctx.age_hat[i], eta - ctx.t, ctx.T - ctx.t,
                        lambda_k, alpha_k, kappa_k)
                    e_prev = sortie_energy_exact(
                        start_pos, node_pos, xs,
                        onboard_cap if continuing else (np.sum(xs, axis=0) if xs else np.zeros(N_COMMODITIES)),
                        ctx.depot_pos, w_k, self.p) if xs else 0.0
                    marginal_e = e_total - e_prev
                    r_leg = ctx.risk(cur_anchor, i)
                    score = (dep_avoid - hyb.mu_E * marginal_e - hyb.mu_R * r_leg) \
                        / max(tau, 1e-3)
                    if score > 1e-9 and (best is None or score > best[0]):
                        best = (score, i, x, tau, eta)
                if best is None:
                    break
                _, node, x, tau, eta = best
                visits.append(PlannedVisit(node, x, eta=eta))
                xs.append(x)
                node_pos.append(ctx.pos[node])
                remaining[node] = remaining[node] - x
                if remaining[node].sum() <= 1e-9:
                    remaining.pop(node)
                if not continuing:
                    stock -= x
                    np.maximum(stock, 0.0, out=stock)

            if not visits:
                break
            sortie = Sortie(visits=visits, depart_time=t_cursor)
            sortie.y = np.zeros(N_COMMODITIES) if continuing else np.sum(xs, axis=0)
            scaffold.plans[start.uav].append(sortie)
            # advance cursor over the sortie + turnaround
            pos = start_pos
            for p_i in node_pos:
                t_cursor += float(np.linalg.norm(p_i - pos)) / phys.v_uav + SERVICE_DWELL
                pos = p_i
            t_cursor += float(np.linalg.norm(ctx.depot_pos - pos)) / phys.v_uav
            t_cursor += mission.T_load + mission.T_charge
            continuing = False
            start = UAVPlanStart(uav=start.uav, pos=ctx.depot_pos.copy(),
                                 ell=np.zeros(N_COMMODITIES), b=phys.B_max,
                                 ready_time=t_cursor, at_depot=True,payload_committed=False)

    @staticmethod
    def _fit_mass(x: np.ndarray, w_k: np.ndarray, mass_room: float,
                  priority: np.ndarray) -> np.ndarray:
        """Trim candidate delivery x to fit mass_room, dropping least-critical units first."""
        x = np.floor(np.maximum(x, 0.0))
        if mass_room <= 0:
            return np.zeros_like(x)
        order = np.argsort(priority)   # ascending criticality -> trimmed first
        while float(np.dot(w_k, x)) > mass_room + 1e-9:
            for k in order:
                if x[k] > 0:
                    x[k] -= 1
                    break
            else:
                break
        return x

    # -- ALNS improvement -----------------------------------------------------
    def _destroy_repair(
        self, scaffold: Scaffold, ctx: PlanContext,
        rng: np.random.Generator,
        frozen_nodes_by_uav: Optional[Dict[int, Set[int]]] = None,
        removal_weights_by_uav_node: Optional[
            Dict[Tuple[int, int], float]
        ] = None,
    ) -> Scaffold:
        cand = scaffold.clone()
        all_visits: List[Tuple[int, int, int]] = []
        removal_weights: List[float] = []
        for u, ss in cand.plans.items():
            for si, s in enumerate(ss):
                for vi, visit in enumerate(s.visits):
                    if visit.node in (frozen_nodes_by_uav or {}).get(u, set()):
                        continue
                    weight = 1.0
                    if removal_weights_by_uav_node is not None:
                        weight = max(
                            float(removal_weights_by_uav_node.get(
                                (u, visit.node), 0.0)),
                            0.0,
                        )
                    if weight <= 0.0:
                        continue
                    all_visits.append((u, si, vi))
                    removal_weights.append(weight)
        if not all_visits:
            return cand
        n_remove = max(1, int(self.p.hybrid.alns_removal_frac * len(all_visits)))
        probabilities = None
        if removal_weights_by_uav_node is not None:
            probabilities = np.asarray(removal_weights, dtype=float)
            probabilities /= float(probabilities.sum())
        idxs = rng.choice(len(all_visits), size=min(n_remove, len(all_visits)),
                          replace=False, p=probabilities)
        removed: List[PlannedVisit] = []
        for u, si, vi in sorted((all_visits[i] for i in idxs), key=lambda m: -m[2]):
            removed.append(cand.plans[u][si].visits.pop(vi))
        for u in cand.plans:           # drop emptied sorties, refresh y
            cand.plans[u] = [s for s in cand.plans[u] if s.visits]
            for s in cand.plans[u]:
                s.y = np.sum([v.x_plan for v in s.visits], axis=0)
        # pool the removed demand and greedily re-insert
        remaining: Dict[int, np.ndarray] = {}
        for v in removed:
            remaining[v.node] = remaining.get(v.node, np.zeros(N_COMMODITIES)) + v.x_plan
        stock_used = np.zeros(N_COMMODITIES)
        for u, ss in cand.plans.items():
            for s in ss:
                stock_used += s.y
        stock = np.maximum(ctx.stock - stock_used, 0.0)
        order = list(ctx.uav_starts)
        rng.shuffle(order)
        for start in order:
            self._extend_plan(cand, start, remaining, stock, ctx)
        return cand

    def _tail_start(self, scaffold: Scaffold, start: UAVPlanStart,
                    ctx: PlanContext) -> UAVPlanStart:
        """Plan-start positioned after the UAV's already-planned sorties."""
        sorties = scaffold.plans.get(start.uav, [])
        if not sorties:
            return start
        phys = self.p.physics
        mission = self.p.mission
        t_cursor = start.ready_time
        pos = start.pos.copy()
        for s in sorties:
            for v in s.visits:
                t_cursor += float(np.linalg.norm(ctx.pos[v.node] - pos)) / phys.v_uav \
                    + SERVICE_DWELL
                pos = ctx.pos[v.node].copy()
            t_cursor += float(np.linalg.norm(pos - ctx.depot_pos)) / phys.v_uav
            t_cursor += mission.T_load + mission.T_charge
            pos = ctx.depot_pos.copy()
        return UAVPlanStart(
                uav=start.uav,
                pos=pos,
                ell=np.zeros(N_COMMODITIES),
                b=phys.B_max,
                ready_time=t_cursor,
                at_depot=True,
                payload_committed=False,
                anchor=DEPOT,
            )

    # -- evaluation ------------------------------------------------------------
    def _evaluate(self, scaffold: Scaffold, ctx: PlanContext) -> float:
        """Belief-side scaffold value: sum of V_ui terms (eq:assignment_value)."""
        phys = self.p.physics
        w_k, lambda_k, alpha_k, kappa_k = self.p.commodities.as_arrays()
        hyb = self.p.hybrid
        mission = self.p.mission
        total = 0.0
        for start in ctx.uav_starts:
            t_cursor = start.ready_time
            pos = start.pos.copy()
            anchor = start.anchor
            continuing = start.uses_onboard_payload
            for s in scaffold.plans.get(start.uav, []):
                onboard = start.ell.copy() if continuing else s.y.copy()
                for v in s.visits:
                    L = float(np.linalg.norm(ctx.pos[v.node] - pos))
                    tau = L / phys.v_uav
                    e = flight_energy(L, float(np.dot(w_k, onboard)), phys) \
                        + service_energy(phys)
                    t_cursor += tau
                    if t_cursor < ctx.T and v.node in ctx.d_tilde:
                        dep = expected_deprivation_avoided(
                            ctx.nu[v.node],
                            np.minimum(v.x_plan, ctx.d_tilde[v.node]),
                            ctx.age_hat[v.node], t_cursor - ctx.t, ctx.T - ctx.t,
                            lambda_k, alpha_k, kappa_k)
                        total += dep - hyb.mu_E * e - hyb.mu_R * ctx.risk(anchor, v.node)
                    onboard = np.maximum(onboard - v.x_plan, 0.0)
                    pos = ctx.pos[v.node].copy()
                    anchor = v.node
                    t_cursor += SERVICE_DWELL
                L_back = float(np.linalg.norm(pos - ctx.depot_pos))
                total -= hyb.mu_E * flight_energy(L_back, float(np.dot(w_k, onboard)), phys)
                t_cursor += L_back / phys.v_uav + mission.T_load + mission.T_charge
                pos = ctx.depot_pos.copy()
                anchor = DEPOT
                continuing = False
        return total

    def _evaluate_capped(self, scaffold: Scaffold, ctx: PlanContext) -> float:
        """Belief-side value with a global remaining-demand ledger."""
        phys = self.p.physics
        w_k, lambda_k, alpha_k, kappa_k = self.p.commodities.as_arrays()
        hyb = self.p.hybrid
        mission = self.p.mission
        remaining = {i: d.copy() for i, d in ctx.d_tilde.items()}
        total = 0.0
        for start in ctx.uav_starts:
            t_cursor = start.ready_time
            pos = start.pos.copy()
            anchor = start.anchor
            continuing = start.uses_onboard_payload
            for s in scaffold.plans.get(start.uav, []):
                onboard = start.ell.copy() if continuing else s.y.copy()
                for v in s.visits:
                    if v.node not in ctx.pos:
                        continue
                    L = float(np.linalg.norm(ctx.pos[v.node] - pos))
                    tau = L / phys.v_uav
                    e = flight_energy(L, float(np.dot(w_k, onboard)), phys) \
                        + service_energy(phys)
                    t_cursor += tau
                    available = remaining.get(v.node)
                    if t_cursor < ctx.T and available is not None:
                        x = np.minimum(v.x_plan, available)
                        if x.sum() > 1e-9:
                            dep = expected_deprivation_avoided(
                                ctx.nu[v.node], x, ctx.age_hat[v.node],
                                t_cursor - ctx.t, ctx.T - ctx.t,
                                lambda_k, alpha_k, kappa_k)
                            total += dep - hyb.mu_E * e \
                                - hyb.mu_R * ctx.risk(anchor, v.node)
                            remaining[v.node] = np.maximum(available - x, 0.0)
                    onboard = np.maximum(onboard - v.x_plan, 0.0)
                    pos = ctx.pos[v.node].copy()
                    anchor = v.node
                    t_cursor += SERVICE_DWELL
                L_back = float(np.linalg.norm(pos - ctx.depot_pos))
                total -= hyb.mu_E * flight_energy(
                    L_back, float(np.dot(w_k, onboard)), phys)
                t_cursor += L_back / phys.v_uav \
                    + mission.T_load + mission.T_charge
                pos = ctx.depot_pos.copy()
                anchor = DEPOT
                continuing = False
        return total

    # -- finalize: ETAs, energy estimates and margins ---------------------------
    def _finalize(self, scaffold: Scaffold, ctx: PlanContext) -> None:
        phys = self.p.physics
        w_k = np.asarray(self.p.commodities.w_k)
        mission = self.p.mission
        for start in ctx.uav_starts:
            t_cursor = start.ready_time
            pos = start.pos.copy()
            continuing = start.uses_onboard_payload
            for s in scaffold.plans.get(start.uav, []):
                s.depart_time = t_cursor
                onboard0 = start.ell.copy() if continuing else s.y.copy()
                battery0 = start.b if continuing else phys.B_max
                node_pos = [ctx.pos[v.node] for v in s.visits]
                xs = [v.x_plan for v in s.visits]
                s.energy_est = sortie_energy_exact(pos, node_pos, xs, onboard0,
                                                   ctx.depot_pos, w_k, self.p)
                s.energy_margin = battery0 - s.energy_est - phys.beta_safe
                onboard = onboard0.copy()
                for v in s.visits:
                    t_cursor += float(np.linalg.norm(ctx.pos[v.node] - pos)) / phys.v_uav
                    v.eta = t_cursor
                    t_cursor += SERVICE_DWELL
                    onboard = np.maximum(onboard - v.x_plan, 0.0)
                    pos = ctx.pos[v.node].copy()
                t_cursor += float(np.linalg.norm(pos - ctx.depot_pos)) / phys.v_uav
                t_cursor += mission.T_load + mission.T_charge
                pos = ctx.depot_pos.copy()
                continuing = False


# ---------------------------------------------------------------------------
def plan_divergence(scaffold: Scaffold, t: float,
                    mu_now: Dict[int, np.ndarray],
                    urgency_rank_now: List[int],
                    n_new_reveals: int,
                    n_invalid_legs: int,
                    omega: List[float]) -> Tuple[float, np.ndarray]:
    """
    Delta_plan = w1 Delta_D + w2 Delta_U + w3 N_new + w4 N_invalid + w5 A_plan
    (eq:plan_divergence). Returns (value, components).
    """
    # Delta_D: normalized change in estimated demand over snapshot nodes
    num, den = 0.0, 0.0
    for i, mu0 in scaffold.mu_snapshot.items():
        mu1 = mu_now.get(i, np.zeros_like(mu0))
        num += float(np.abs(mu1 - mu0).sum())
        den += float(np.abs(mu0).sum())
    delta_D = num / max(den, 1.0)
    # Delta_U: normalized Kendall-tau distance between urgency orderings
    common = [i for i in scaffold.urgency_rank_snapshot if i in urgency_rank_now]
    delta_U = 0.0
    if len(common) >= 2:
        pos_now = {i: r for r, i in enumerate(urgency_rank_now)}
        disc = 0
        n = len(common)
        for a in range(n):
            for b in range(a + 1, n):
                if pos_now[common[a]] > pos_now[common[b]]:
                    disc += 1
        delta_U = disc / (n * (n - 1) / 2)
    A_plan = t - scaffold.created_t
    comps = np.array([delta_D, delta_U, float(n_new_reveals),
                      float(n_invalid_legs), A_plan])
    return float(np.dot(np.asarray(omega), comps)), comps
