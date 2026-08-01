"""Dependency-aware, belief-consistent repair control for the ALNS scaffold.

The controller reads only the operational belief, reported corridor state,
fleet resources, and depot resources.  Latent demand truth is never queried.
It implements four separate contracts:

* where: reverse tracing through a plan--belief dependency graph;
* when: a valid optimistic-bound screen that can certify continuation;
* how much: mutable route regions plus explicitly frozen decisions;
* what information: the same operational ``PlanContext`` used by ALNS.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

import numpy as np

from env.alns_scaffold import Scaffold, Sortie, sortie_energy_exact
from env.deprivation import expected_deprivation_avoided
from env.events import EventType
from env.graph import DEPOT
from env.params import N_COMMODITIES


OPERATIONAL_REPAIR_EVENTS = frozenset({
    EventType.P1_REPORT,
    EventType.P2_REVEAL,
    EventType.P4_REPORT,
    EventType.AVAIL_CHANGE,
    EventType.REPLENISH,
})


def corridor_resource(i: int, j: int) -> str:
    a, b = sorted((int(i), int(j)))
    return f"corridor:{a}:{b}"


@dataclass(frozen=True, order=True)
class DecisionKey:
    """Stable identity of a future visit in one incumbent scaffold."""

    uav: int
    sortie: int
    visit: int

    def label(self) -> str:
        return f"u{self.uav}/s{self.sortie}/v{self.visit}"


@dataclass
class PlanDecision:
    key: DecisionKey
    node: int
    predecessor_node: int
    resources: FrozenSet[str]


@dataclass
class PlanBeliefDependencyGraph:
    """Small explicit bipartite dependency graph plus route precedence."""

    decisions: Dict[DecisionKey, PlanDecision] = field(default_factory=dict)
    resource_to_decisions: Dict[str, Set[DecisionKey]] = field(
        default_factory=dict)
    route_successors: Dict[DecisionKey, Set[DecisionKey]] = field(
        default_factory=dict)
    same_sortie: Dict[Tuple[int, int], Set[DecisionKey]] = field(
        default_factory=dict)

    @classmethod
    def build(cls, env, scaffold: Optional[Scaffold] = None):
        scaffold = scaffold or env.scaffold
        graph = cls()
        starts = {start.uav: start for start in env._plan_context().uav_starts}
        for u, sorties in scaffold.plans.items():
            start = starts[u]
            previous_flat: Optional[DecisionKey] = None
            for si, sortie in enumerate(sorties):
                predecessor = start.anchor if si == 0 else DEPOT
                sortie_keys: Set[DecisionKey] = set()
                last_key: Optional[DecisionKey] = None
                for vi, visit in enumerate(sortie.visits):
                    key = DecisionKey(u, si, vi)
                    resources = {
                        f"demand:{visit.node}",
                        f"uav:{u}:energy",
                        f"uav:{u}:payload",
                        corridor_resource(predecessor, visit.node),
                        "depot:bays",
                    }
                    for k, amount in enumerate(visit.x_plan):
                        if amount <= 1e-9:
                            continue
                        resources.add(f"cohort:{visit.node}:{k}")
                        resources.add(f"inventory:{k}")
                    decision = PlanDecision(
                        key=key,
                        node=visit.node,
                        predecessor_node=predecessor,
                        resources=frozenset(resources),
                    )
                    graph.decisions[key] = decision
                    sortie_keys.add(key)
                    for resource in resources:
                        graph.resource_to_decisions.setdefault(
                            resource, set()).add(key)
                    if previous_flat is not None:
                        graph.route_successors.setdefault(
                            previous_flat, set()).add(key)
                    previous_flat = key
                    last_key = key
                    predecessor = visit.node
                if last_key is not None:
                    return_resource = corridor_resource(predecessor, DEPOT)
                    previous = graph.decisions[last_key]
                    graph.decisions[last_key] = PlanDecision(
                        key=previous.key,
                        node=previous.node,
                        predecessor_node=previous.predecessor_node,
                        resources=frozenset({
                            *previous.resources, return_resource}),
                    )
                    graph.resource_to_decisions.setdefault(
                        return_resource, set()).add(last_key)
                if sortie_keys:
                    graph.same_sortie[(u, si)] = sortie_keys
        return graph

    def affected_by(self, resources: Iterable[str]) -> Set[DecisionKey]:
        affected: Set[DecisionKey] = set()
        for resource in resources:
            affected.update(self.resource_to_decisions.get(resource, set()))
        return affected

    def downstream_closure(
        self, seeds: Iterable[DecisionKey],
    ) -> Set[DecisionKey]:
        """Expand a direct impact through its sortie and later route decisions."""
        out: Set[DecisionKey] = set()
        stack: List[DecisionKey] = []
        for seed in seeds:
            same = self.same_sortie.get((seed.uav, seed.sortie), {seed})
            out.update(same)
            stack.extend(same)
        while stack:
            current = stack.pop()
            for nxt in self.route_successors.get(current, set()):
                if nxt not in out:
                    out.add(nxt)
                    stack.append(nxt)
        return out


@dataclass
class OperationalSnapshot:
    """Controller-visible operational state; deliberately excludes truth."""

    t: float
    known: FrozenSet[int]
    demand: Dict[int, Tuple[float, ...]]
    inventory: Tuple[float, ...]
    corridors: Dict[Tuple[int, int], bool]
    uav_battery: Tuple[float, ...]
    uav_payload: Tuple[Tuple[float, ...], ...]

    @classmethod
    def capture(cls, env):
        known = frozenset(int(i) for i in env.belief.known)
        locations = [DEPOT, *sorted(known)]
        corridors = {
            (i, j): bool(env.graph.A(i, j))
            for index, i in enumerate(locations)
            for j in locations[index + 1:]
        }
        return cls(
            t=float(env.t),
            known=known,
            demand={
                i: tuple(float(x) for x in env.belief.d_tilde(i))
                for i in known
            },
            inventory=tuple(float(x) for x in env.inventory.S0),
            corridors=corridors,
            uav_battery=tuple(float(uav.b) for uav in env.uavs),
            uav_payload=tuple(
                tuple(float(x) for x in uav.ell) for uav in env.uavs),
        )


@dataclass
class OperationalChanges:
    new_nodes: Set[int] = field(default_factory=set)
    demand_nodes: Set[int] = field(default_factory=set)
    demand_commodities: Set[Tuple[int, int]] = field(default_factory=set)
    inventory_commodities: Set[int] = field(default_factory=set)
    inventory_delta: Dict[int, float] = field(default_factory=dict)
    closed_corridors: Set[Tuple[int, int]] = field(default_factory=set)
    reopened_corridors: Set[Tuple[int, int]] = field(default_factory=set)

    @classmethod
    def between(
        cls, before: OperationalSnapshot, after: OperationalSnapshot,
        atol: float = 1e-8,
    ):
        changes = cls()
        changes.new_nodes = set(after.known - before.known)
        for node in before.known & after.known:
            old = np.asarray(before.demand[node])
            new = np.asarray(after.demand[node])
            changed = np.flatnonzero(np.abs(new - old) > atol)
            if changed.size:
                changes.demand_nodes.add(node)
                changes.demand_commodities.update(
                    (node, int(k)) for k in changed)
        for node in changes.new_nodes:
            changes.demand_nodes.add(node)
            changes.demand_commodities.update(
                (node, k) for k, amount in enumerate(after.demand[node])
                if amount > atol)
        old_inventory = np.asarray(before.inventory)
        new_inventory = np.asarray(after.inventory)
        for k in np.flatnonzero(np.abs(new_inventory - old_inventory) > atol):
            commodity = int(k)
            changes.inventory_commodities.add(commodity)
            changes.inventory_delta[commodity] = float(
                new_inventory[k] - old_inventory[k])
        for edge in before.corridors.keys() & after.corridors.keys():
            old, new = before.corridors[edge], after.corridors[edge]
            if old and not new:
                changes.closed_corridors.add(edge)
            elif not old and new:
                changes.reopened_corridors.add(edge)
        return changes
    @property
    def has_relevant_change(self) -> bool:
        return bool(
            self.new_nodes
            or self.demand_nodes
            or self.inventory_commodities
            or self.closed_corridors
            or self.reopened_corridors
        )

    def resources(self) -> Set[str]:
        resources = {f"demand:{node}" for node in self.demand_nodes}
        resources.update(
            f"cohort:{node}:{k}" for node, k in self.demand_commodities)
        resources.update(
            f"inventory:{k}" for k in self.inventory_commodities)
        resources.update(
            corridor_resource(i, j)
            for i, j in self.closed_corridors | self.reopened_corridors)
        return resources

    @property
    def has_opportunity(self) -> bool:
        return bool(
            self.new_nodes
            or self.reopened_corridors
            or any(delta > 0.0 for delta in self.inventory_delta.values())
        )


@dataclass
class ImpactTrace:
    event_kind: str
    changed_resources: Set[str]
    hard: Set[DecisionKey]
    direct: Set[DecisionKey]
    opportunity_seeds: Set[DecisionKey]
    mutable: Set[DecisionKey]
    frozen: Set[DecisionKey]


def _event_kind(
    event_type: Optional[EventType],
    changes: OperationalChanges,
) -> str:
    if changes.closed_corridors or changes.reopened_corridors:
        return "corridor_state_change"

    if changes.inventory_commodities:
        return "depot_resource_change"

    if changes.new_nodes:
        return "newly_revealed_demand"

    if changes.demand_nodes:
        if event_type == EventType.P4_REPORT:
            return "delivery_delayed_correction"
        return "demand_correction"

    return "feasibility_change"


def _hard_infeasible_decisions(
    env, scaffold: Scaffold, graph: PlanBeliefDependencyGraph,
) -> Set[DecisionKey]:
    hard: Set[DecisionKey] = set()
    starts = {start.uav: start for start in env._plan_context().uav_starts}
    w_k = np.asarray(env.p.commodities.w_k)
    for u, sorties in scaffold.plans.items():
        start = starts[u]
        for si, sortie in enumerate(sorties):
            keys = graph.same_sortie.get((u, si), set())
            predecessor = start.anchor if si == 0 else DEPOT
            for vi, visit in enumerate(sortie.visits):
                key = DecisionKey(u, si, vi)
                if not env.belief.is_known(visit.node):
                    hard.add(key)
                elif not env.graph.A(predecessor, visit.node):
                    hard.add(key)
                predecessor = visit.node
            if sortie.visits and not env.graph.A(predecessor, DEPOT):
                hard.add(DecisionKey(u, si, len(sortie.visits) - 1))
            if float(np.dot(w_k, sortie.y)) > env.p.physics.W_max + 1e-8:
                hard.update(keys)
            known_visits = [
                visit for visit in sortie.visits
                if env.belief.is_known(visit.node)
            ]
            if len(known_visits) != len(sortie.visits):
                continue
            node_pos = [env.graph.pos_of(visit.node) for visit in known_visits]
            xs = [visit.x_plan for visit in known_visits]
            continuing = (
                si == 0 and start.uses_onboard_payload)
            onboard = start.ell.copy() if continuing else sortie.y.copy()
            battery = start.b if continuing else env.p.physics.B_max
            start_pos = start.pos if continuing else env.depot_pos
            energy = sortie_energy_exact(
                start_pos, node_pos, xs, onboard, env.depot_pos, w_k, env.p)
            if energy + env.p.physics.beta_safe > battery + 1e-8:
                hard.update(keys)
    return hard


def _opportunity_competitors(
    env, dependency_graph: PlanBeliefDependencyGraph,
    changes: OperationalChanges,
) -> Set[DecisionKey]:
    if not dependency_graph.decisions:
        return set()
    target_nodes = set(changes.new_nodes)
    for i, j in changes.reopened_corridors:
        target_nodes.update(node for node in (i, j) if node != DEPOT)
    candidates = list(dependency_graph.decisions.values())
    selected: Set[DecisionKey] = set()
    for target in target_nodes:
        if not env.belief.is_known(target):
            continue
        target_pos = env.graph.pos_of(target)
        nearest = min(
            candidates,
            key=lambda decision: float(np.linalg.norm(
                env.graph.pos_of(decision.node) - target_pos)),
        )
        selected.add(nearest.key)
    if changes.has_opportunity and not selected:
        first_by_uav: Dict[int, DecisionKey] = {}
        for key in sorted(dependency_graph.decisions):
            first_by_uav.setdefault(key.uav, key)
        selected.update(first_by_uav.values())
    return selected


def trace_impacts(
    env, dependency_graph: PlanBeliefDependencyGraph,
    changes: OperationalChanges,
    event_type: Optional[EventType],
) -> ImpactTrace:
    resources = changes.resources()
    hard = _hard_infeasible_decisions(
        env, env.scaffold, dependency_graph)
    direct = dependency_graph.affected_by(resources)
    opportunity = _opportunity_competitors(
        env, dependency_graph, changes)
    mutable = dependency_graph.downstream_closure(
        hard | direct | opportunity)
    frozen = set(dependency_graph.decisions) - mutable
    return ImpactTrace(
        event_kind=_event_kind(event_type,changes),
        changed_resources=resources,
        hard=hard,
        direct=direct,
        opportunity_seeds=opportunity,
        mutable=mutable,
        frozen=frozen,
    )


def _partial_warm_start(
    scaffold: Scaffold, mutable: Set[DecisionKey],
) -> Scaffold:
    warm = scaffold.clone()
    for u, sorties in list(warm.plans.items()):
        kept_sorties: List[Sortie] = []
        for si, sortie in enumerate(sorties):
            kept = [
                visit for vi, visit in enumerate(sortie.visits)
                if DecisionKey(u, si, vi) not in mutable
            ]
            if not kept:
                continue
            sortie.visits = kept
            sortie.y = np.sum(
                [visit.x_plan for visit in kept], axis=0)
            kept_sorties.append(sortie)
        warm.plans[u] = kept_sorties
    return warm


def _frozen_nodes(
    dependency_graph: PlanBeliefDependencyGraph,
    mutable: Set[DecisionKey],
) -> Dict[int, Set[int]]:
    mutable_nodes = {
        (key.uav, dependency_graph.decisions[key].node)
        for key in mutable
    }
    frozen: Dict[int, Set[int]] = {}
    for key, decision in dependency_graph.decisions.items():
        if key in mutable or (key.uav, decision.node) in mutable_nodes:
            continue
        frozen.setdefault(key.uav, set()).add(decision.node)
    return frozen


def optimistic_value_upper_bound(env) -> float:
    """Relaxed value upper bound: immediate, free, unconstrained service."""
    ctx = env._plan_context()
    _, lambda_k, alpha_k, kappa_k = env.p.commodities.as_arrays()
    horizon = max(ctx.T - ctx.t, 0.0)
    total = 0.0
    for node, demand in ctx.d_tilde.items():
        total += expected_deprivation_avoided(
            ctx.nu[node], demand, ctx.age_hat[node], 0.0, horizon,
            lambda_k, alpha_k, kappa_k)
    return float(total)


def event_impact_value_proxy(
    env, before: OperationalSnapshot, after: OperationalSnapshot,
    changes: OperationalChanges,
) -> float:
    """Cheap event-local value screen used when the valid bound is inconclusive.

    This is deliberately reported as a proxy, not as a lower-bound
    certificate.  It measures the immediate relaxed value of newly changed
    demand, newly available stock, and reopened-corridor endpoints.
    """
    ctx = env._plan_context()
    _, lambda_k, alpha_k, kappa_k = env.p.commodities.as_arrays()
    horizon = max(ctx.T - ctx.t, 0.0)
    total = 0.0
    for node in changes.demand_nodes:
        if node not in ctx.d_tilde:
            continue
        old = np.asarray(before.demand.get(
            node, (0.0,) * N_COMMODITIES))
        new = np.asarray(after.demand[node])
        delta = np.abs(new - old)
        total += expected_deprivation_avoided(
            ctx.nu[node], delta, ctx.age_hat[node], 0.0, horizon,
            lambda_k, alpha_k, kappa_k)
    for commodity, delta in changes.inventory_delta.items():
        if delta <= 0.0:
            continue
        best_unit = 0.0
        for node, demand in ctx.d_tilde.items():
            if demand[commodity] <= 1e-9:
                continue
            one = np.zeros(N_COMMODITIES)
            one[commodity] = 1.0
            best_unit = max(
                best_unit,
                expected_deprivation_avoided(
                    ctx.nu[node], one, ctx.age_hat[node], 0.0, horizon,
                    lambda_k, alpha_k, kappa_k),
            )
        total += delta * best_unit
    endpoint_nodes = {
        node
        for edge in changes.reopened_corridors
        for node in edge
        if node != DEPOT and node in ctx.d_tilde
    }
    for node in endpoint_nodes - changes.demand_nodes:
        total += expected_deprivation_avoided(
            ctx.nu[node], ctx.d_tilde[node], ctx.age_hat[node],
            0.0, horizon, lambda_k, alpha_k, kappa_k)
    return float(total)


class EventCausalRepairController:
    """Baseline-compatible controller implementing selective belief repair."""

    name = "Event-Causal Belief-Repair ALNS"

    def __init__(
        self,
        selective_repair: bool = True,
        solve_cost: Optional[float] = None,
        proxy_threshold_fraction: float = 0.0,
        screen_soft_events: bool = True,
    ):
        self.selective_repair = bool(selective_repair)
        self.solve_cost = solve_cost
        self.screen_soft_events = bool(screen_soft_events)
        if proxy_threshold_fraction < 0.0:
            raise ValueError("proxy_threshold_fraction must be nonnegative")
        self.proxy_threshold_fraction = float(proxy_threshold_fraction)
        self.previous_snapshot: Optional[OperationalSnapshot] = None
        self.scenario_token: Optional[int] = None
        self.last_t = -np.inf
        self.diagnostics: List[Dict[str, object]] = []
        self.repair_wall_time_s = 0.0
        self.repair_solver_calls = 0

    def reset(self) -> None:
        self.previous_snapshot = None
        self.scenario_token = None
        self.last_t = -np.inf
        self.diagnostics = []
        self.repair_wall_time_s = 0.0
        self.repair_solver_calls = 0

    def act(self, env, obs, masks, deciders):
        del obs, masks
        actions = {u: env.A_FOLLOW for u in deciders}
        token = id(env.scenario)
        if (
            self.previous_snapshot is None
            or token != self.scenario_token
            or env.t < self.last_t - 1e-9
        ):
            self.previous_snapshot = OperationalSnapshot.capture(env)
            self.scenario_token = token
            self.last_t = float(env.t)
            return actions

        current = OperationalSnapshot.capture(env)
        changes = OperationalChanges.between(
            self.previous_snapshot, current)
        dependency_graph = PlanBeliefDependencyGraph.build(env)
        event_type = env.last_decision_event_type
        hard = _hard_infeasible_decisions(
            env, env.scaffold, dependency_graph)
        if not changes.has_relevant_change and not hard:
            self.previous_snapshot = current
            self.last_t = float(env.t)
            return actions

        trace = trace_impacts(
            env, dependency_graph, changes, event_type)
        ctx = env._plan_context()
        current_value = env.planner.evaluate_belief_value(
            env.scaffold, ctx)
        upper_bound = optimistic_value_upper_bound(env)
        j_current = max(upper_bound - current_value, 0.0)
        lower_bound = 0.0
        potential_gain_bound = j_current - lower_bound
        event_impact_proxy = event_impact_value_proxy(
            env, self.previous_snapshot, current, changes)
        solve_cost = float(
            env.p.hybrid.xi_C if self.solve_cost is None else self.solve_cost)
        proxy_activation_threshold = max(
            solve_cost,
            self.proxy_threshold_fraction * upper_bound,
        )
        total_decisions = len(dependency_graph.decisions)
        scope_fraction = (
            len(trace.mutable) / total_decisions
            if total_decisions else (1.0 if changes.has_opportunity else 0.0)
        )
        record: Dict[str, object] = {
            "time_h": float(env.t),
            "event_kind": trace.event_kind,
            "event_type": event_type.name if event_type is not None else "",
            "changed_resources": "|".join(sorted(trace.changed_resources)),
            "hard_impact_count": len(trace.hard),
            "direct_impact_count": len(trace.direct),
            "opportunity_seed_count": len(trace.opportunity_seeds),
            "mutable_decision_count": len(trace.mutable),
            "frozen_decision_count": len(trace.frozen),
            "total_decision_count": total_decisions,
            "repair_scope_fraction": float(scope_fraction),
            "current_plan_value": float(current_value),
            "optimistic_value_upper_bound": float(upper_bound),
            "J_current": float(j_current),
            "LB": float(lower_bound),
            "potential_gain_bound": float(potential_gain_bound),
            "event_impact_value_proxy": float(event_impact_proxy),
            "solve_cost": solve_cost,
            "proxy_threshold_fraction": self.proxy_threshold_fraction,
            "screen_soft_events": int(self.screen_soft_events),
            "proxy_activation_threshold": float(
                proxy_activation_threshold),
            "attempted": 0,
            "installed": 0,
            "fallback_full_replan": 0,
            "localized_solve_wall_time_s": 0.0,
            "fallback_solve_wall_time_s": 0.0,
            "repair_wall_time_s": 0.0,
            "repair_solver_calls": 0,
            "candidate_plan_value": float("nan"),
            "actual_improvement": float("nan"),
            "net_improvement_after_solve": float("nan"),
            "outcome": "",
        }

        if not trace.hard and not trace.changed_resources:
            record["outcome"] = "continue_no_relevant_change"
        elif self.screen_soft_events and not trace.hard and potential_gain_bound <= solve_cost + 1e-9:
            record["outcome"] = "certified_continue"
        elif (
            self.screen_soft_events and
            not trace.hard
            and event_impact_proxy <= proxy_activation_threshold + 1e-9
        ):
            record["outcome"] = "continue_event_impact_below_threshold"
        elif env.K_rem <= 0:
            record["outcome"] = "continue_budget_exhausted"
        else:
            env.begin_external_resolve()
            record["attempted"] = 1
            if self.selective_repair:
                warm = _partial_warm_start(
                    env.scaffold, trace.mutable)
                frozen = _frozen_nodes(
                    dependency_graph, trace.mutable)
            else:
                warm, frozen = None, None
                record["repair_scope_fraction"] = 1.0
                record["mutable_decision_count"] = total_decisions
                record["frozen_decision_count"] = 0
            solve_started = time.perf_counter()
            candidate = env.propose_scaffold_repair(warm, frozen)
            localized_solve_wall_time = time.perf_counter() - solve_started
            record["localized_solve_wall_time_s"] = float(
                localized_solve_wall_time)
            record["repair_solver_calls"] = 1
            candidate_graph = PlanBeliefDependencyGraph.build(env, candidate)
            candidate_hard = _hard_infeasible_decisions(
                env, candidate, candidate_graph)
            candidate_value = env.planner.evaluate_belief_value(
                candidate, ctx)

            if self.selective_repair and (
                candidate_hard or candidate_value <= current_value + 1e-9
            ):
                fallback_started = time.perf_counter()
                full_candidate = env.propose_scaffold_repair(None, None)
                fallback_solve_wall_time = (
                    time.perf_counter() - fallback_started)
                record["fallback_solve_wall_time_s"] = float(
                    fallback_solve_wall_time)
                record["repair_solver_calls"] = 2
                full_graph = PlanBeliefDependencyGraph.build(
                    env, full_candidate)
                full_hard = _hard_infeasible_decisions(
                    env, full_candidate, full_graph)
                full_value = env.planner.evaluate_belief_value(
                    full_candidate, ctx)
                if not full_hard and (
                    candidate_hard or full_value > candidate_value + 1e-9
                ):
                    candidate = full_candidate
                    candidate_hard = full_hard
                    candidate_value = full_value
                    record["fallback_full_replan"] = 1

            actual_improvement = candidate_value - current_value
            record["candidate_plan_value"] = float(candidate_value)
            record["actual_improvement"] = float(actual_improvement)
            record["net_improvement_after_solve"] = float(
                actual_improvement - solve_cost)
            if not candidate_hard and (
                trace.hard or actual_improvement >solve_cost + 1e-9

            ):
                env.install_scaffold_repair(candidate)
                record["installed"] = 1
                if trace.hard:
                    record["outcome"] = (
                        "installed_feasibility_repair"
                    )
                else:
                    record["outcome"] = (
                        "installed_net_beneficial"
                )
            elif candidate_hard:
                record["outcome"] = "rejected_infeasible_candidate"
            else:
                record["outcome"] = "rejected_no_net_benefit"

            repair_wall_time = (
                float(record["localized_solve_wall_time_s"])
                + float(record["fallback_solve_wall_time_s"])
            )
            record["repair_wall_time_s"] = repair_wall_time
            self.repair_wall_time_s += repair_wall_time
            self.repair_solver_calls += int(record["repair_solver_calls"])

        self.diagnostics.append(record)
        self.previous_snapshot = current
        self.last_t = float(env.t)
        return actions


class RegretGatedFullReplanController(EventCausalRepairController):
    """Ablation retaining the valid trigger but removing localization."""

    name = "Regret-Gated Full Replan ALNS"

    def __init__(
        self,
        solve_cost: Optional[float] = None,
        proxy_threshold_fraction: float = 0.0,
    ):
        super().__init__(
            selective_repair=False,
            solve_cost=solve_cost,
            proxy_threshold_fraction=proxy_threshold_fraction,
            screen_soft_events=True,
        )

class EveryEventFullReplanController(
    EventCausalRepairController
):
    """Full-fleet ALNS repair after every observed operational change.

    This baseline uses the same external repair transaction,
    committed-leg contract, onboard-payload contract, candidate
    evaluation and installation pathway as the proposed controller.

    Only the trigger screening and repair localization are removed.
    """

    name = "Full Event Replan ALNS"

    def __init__(
        self,
        solve_cost: Optional[float] = None,
    ):
        super().__init__(
            selective_repair=False,
            solve_cost=solve_cost,
            proxy_threshold_fraction=0.0,
            screen_soft_events=False,
        )