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


@dataclass(frozen=True)
class RepairNeighborhood:
    """One deterministic level of the expanding repair hierarchy."""

    hierarchy_level: int
    name: str
    mutable: FrozenSet[DecisionKey]


_SHARED_RESOURCE_PREFIXES = (
    "inventory:",
    "corridor:",
)


def _decisions_for_uavs(
    dependency_graph: PlanBeliefDependencyGraph,
    uavs: Iterable[int],
) -> Set[DecisionKey]:
    selected = {int(u) for u in uavs}
    return {
        key
        for key in dependency_graph.decisions
        if key.uav in selected
    }


def _shared_resource_uav_closure(
    dependency_graph: PlanBeliefDependencyGraph,
    seed_uavs: Iterable[int],
) -> Set[int]:
    """Expand UAVs through shared inventory and corridor resources only."""

    selected = {int(u) for u in seed_uavs}

    while True:
        shared_resources: Set[str] = set()

        for key in sorted(dependency_graph.decisions):
            if key.uav not in selected:
                continue

            decision = dependency_graph.decisions[key]
            shared_resources.update(
                resource
                for resource in decision.resources
                if resource.startswith(_SHARED_RESOURCE_PREFIXES)
            )

        expanded = set(selected)

        for resource in sorted(shared_resources):
            expanded.update(
                key.uav
                for key in dependency_graph.resource_to_decisions.get(
                    resource,
                    set(),
                )
            )

        if expanded == selected:
            return selected

        selected = expanded


def expanding_repair_neighborhoods(
    dependency_graph: PlanBeliefDependencyGraph,
    trace: ImpactTrace,
    selective_repair: bool = True,
) -> List[RepairNeighborhood]:
    """Build the parameter-free deterministic repair hierarchy.

    Level 1 repairs only the causal decision closure.
    Level 2 releases complete routes of causally affected UAVs.
    Level 3 releases UAVs connected through shared inventory or corridors.
    Level 4 releases the complete fleet.

    Duplicate decision sets are removed, so an expansion level is not solved
    twice when it adds no new mutable decisions.
    """

    all_decisions = set(dependency_graph.decisions)

    if not selective_repair:
        return [
            RepairNeighborhood(
                hierarchy_level=4,
                name="full_fleet",
                mutable=frozenset(all_decisions),
            )
        ]

    causal = set(trace.mutable)
    causal_uavs = {key.uav for key in causal}

    affected_routes = _decisions_for_uavs(
        dependency_graph,
        causal_uavs,
    )

    shared_uavs = _shared_resource_uav_closure(
        dependency_graph,
        causal_uavs,
    )
    shared_resource_routes = _decisions_for_uavs(
        dependency_graph,
        shared_uavs,
    )

    raw_levels = [
        (1, "causal_decisions", causal),
        (2, "affected_uav_routes", affected_routes),
        (3, "shared_resource_uavs", shared_resource_routes),
        (4, "full_fleet", all_decisions),
    ]

    neighborhoods: List[RepairNeighborhood] = []
    seen: Set[FrozenSet[DecisionKey]] = set()

    for hierarchy_level, name, mutable in raw_levels:
        signature = frozenset(mutable)

        if signature in seen:
            continue

        seen.add(signature)
        neighborhoods.append(
            RepairNeighborhood(
                hierarchy_level=hierarchy_level,
                name=name,
                mutable=signature,
            )
        )

    return neighborhoods


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
    """Optimistic-bound-screened expanding event-causal ALNS repair."""

    name = "Event-Causal Belief-Repair ALNS"

    def __init__(
        self,
        selective_repair: bool = True,
        solve_cost: Optional[float] = None,
        proxy_threshold_fraction: float = 0.0,
        screen_soft_events: bool = True,
        shadow_audit_screened_events: bool = False,
    ):
        self.selective_repair = bool(selective_repair)
        self.solve_cost = solve_cost
        self.screen_soft_events = bool(screen_soft_events)

        self.shadow_audit_screened_events = bool(
            shadow_audit_screened_events
        )

        if proxy_threshold_fraction < 0.0:
            raise ValueError(
                "proxy_threshold_fraction must be nonnegative"
            )

        self.proxy_threshold_fraction = float(
            proxy_threshold_fraction
        )
        self.previous_snapshot: Optional[
            OperationalSnapshot
        ] = None
        self.scenario_token: Optional[int] = None
        self.last_t = -np.inf
        self.diagnostics: List[Dict[str, object]] = []
        self.shadow_audit_records: List[
        Dict[str, object] ] = []
        self._shadow_audit_event_index = 0

        self.repair_wall_time_s = 0.0
        self.repair_solver_calls = 0

    def reset(self) -> None:
        self.previous_snapshot = None
        self.scenario_token = None
        self.last_t = -np.inf
        self.diagnostics = []
        self.shadow_audit_records = []
        self._shadow_audit_event_index = 0
        self.repair_wall_time_s = 0.0
        self.repair_solver_calls = 0

    @staticmethod
    def _prefer_candidate(
        candidate_hard: Set[DecisionKey],
        candidate_value: float,
        selected_hard: Optional[Set[DecisionKey]],
        selected_value: float,
    ) -> bool:
        """Choose the best diagnostic candidate when no level is accepted."""

        if selected_hard is None:
            return True

        candidate_feasible = not candidate_hard
        selected_feasible = not selected_hard

        if candidate_feasible and not selected_feasible:
            return True

        if candidate_feasible != selected_feasible:
            return False

        if candidate_feasible:
            return candidate_value > selected_value + 1e-9

        if len(candidate_hard) != len(selected_hard):
            return len(candidate_hard) < len(selected_hard)

        return candidate_value > selected_value + 1e-9
    def _run_screen_shadow_audit(
    self,
    env,
    dependency_graph: PlanBeliefDependencyGraph,
    trace: ImpactTrace,
    ctx,
    current_value: float,
    solve_cost: float,
    operational_record: Dict[str, object],) -> Dict[str, object]:
        """Counterfactually solve a screened soft event.

            Two candidates are evaluated without changing the real episode:

            1. the Level-1 causal neighborhood;
            2. an unrestricted full-fleet replan.

            The candidates are never installed and do not consume repair
            budget or operational solver accounting.
            """

        self._shadow_audit_event_index += 1
        audit_index = self._shadow_audit_event_index

        audit_calls_before = int(
            env.shadow_audit_solver_calls
        )
        audit_wall_before = float(
            env.shadow_audit_wall_time_s
        )

        total_decisions = len(
            dependency_graph.decisions
        )

        # --------------------------------------------------------------
        # Level 1: causal decision neighborhood
        # --------------------------------------------------------------
        level1_mutable = set(trace.mutable)

        level1_warm = _partial_warm_start(
            env.scaffold,
            level1_mutable,
        )

        level1_frozen = _frozen_nodes(
            dependency_graph,
            level1_mutable,
        )

        level1_candidate = (
            env.propose_shadow_scaffold_repair(
                ctx=ctx,
                warm=level1_warm,
                frozen_nodes_by_uav=level1_frozen,
            )
        )

        level1_graph = (
            PlanBeliefDependencyGraph.build(
                env,
                level1_candidate,
            )
        )

        level1_hard = (
            _hard_infeasible_decisions(
                env,
                level1_candidate,
                level1_graph,
            )
        )

        level1_value = (
            env._shadow_audit_planner
            .evaluate_belief_value(
                level1_candidate,
                ctx,
            )
        )

        level1_improvement = (
            level1_value - current_value
        )

        level1_feasible = not level1_hard

        level1_net_beneficial = (
            level1_feasible
            and level1_improvement
            > solve_cost + 1e-9
        )

        # --------------------------------------------------------------
        # Full fleet: unrestricted counterfactual replan
        # --------------------------------------------------------------
        full_candidate = (
            env.propose_shadow_scaffold_repair(
                ctx=ctx,
                warm=None,
                frozen_nodes_by_uav=None,
            )
        )

        full_graph = (
            PlanBeliefDependencyGraph.build(
                env,
                full_candidate,
            )
        )

        full_hard = (
            _hard_infeasible_decisions(
                env,
                full_candidate,
                full_graph,
            )
        )

        full_value = (
            env._shadow_audit_planner
            .evaluate_belief_value(
                full_candidate,
                ctx,
            )
        )

        full_improvement = (
            full_value - current_value
        )

        full_feasible = not full_hard

        full_net_beneficial = (
            full_feasible
            and full_improvement
            > solve_cost + 1e-9
        )

        # A false negative means the proxy rejected the event even
        # though a full repair would have produced positive net value.
        screen_false_negative = bool(
            full_net_beneficial
        )

        # Feasibility-based need for expansion.
        expansion_was_needed = bool(
            not level1_feasible
            and full_feasible
        )

        # Value-based need for expansion: Level 1 would not qualify,
        # while the full-fleet candidate would qualify.
        expansion_net_benefit_needed = bool(
            not level1_net_beneficial
            and full_net_beneficial
        )

        expansion_extra_improvement = float(
            full_improvement - level1_improvement
        )

        audit_solver_calls = (
            int(env.shadow_audit_solver_calls)
            - audit_calls_before
        )

        audit_wall_time_s = max(
            float(env.shadow_audit_wall_time_s)
            - audit_wall_before,
            0.0,
        )

        level1_scope_fraction = (
            len(level1_mutable) / total_decisions
            if total_decisions
            else 0.0
        )

        return {
            "audit_event_index": audit_index,
            "scenario_seed": int(
                env.scenario.seed
            ),
            "time_h": float(
                operational_record["time_h"]
            ),
            "event_kind": str(
                operational_record["event_kind"]
            ),
            "event_type": str(
                operational_record["event_type"]
            ),
            "changed_resources": str(
                operational_record[
                    "changed_resources"
                ]
            ),
            "hard_impact_count": int(
                operational_record[
                    "hard_impact_count"
                ]
            ),
            "current_plan_value": float(
                current_value
            ),
            "optimistic_value_upper_bound": float(
                operational_record[
                    "optimistic_value_upper_bound"
                ]
            ),
            "potential_gain_bound": float(
                operational_record[
                    "potential_gain_bound"
                ]
            ),
            "event_impact_value_proxy": float(
                operational_record[
                    "event_impact_value_proxy"
                ]
            ),
            "proxy_activation_threshold": float(
                operational_record[
                    "proxy_activation_threshold"
                ]
            ),
            "proxy_threshold_fraction": float(
                operational_record[
                    "proxy_threshold_fraction"
                ]
            ),
            "solve_cost": float(solve_cost),
            "repair_budget_remaining": int(
                env.K_rem
            ),
            "total_decision_count": int(
                total_decisions
            ),
            "shadow_level1_mutable_count": int(
                len(level1_mutable)
            ),
            "shadow_level1_scope_fraction": float(
                level1_scope_fraction
            ),
            "shadow_level1_feasible": int(
                level1_feasible
            ),
            "shadow_level1_hard_count": int(
                len(level1_hard)
            ),
            "shadow_level1_value": float(
                level1_value
            ),
            "shadow_level1_improvement": float(
                level1_improvement
            ),
            "shadow_level1_net_beneficial": int(
                level1_net_beneficial
            ),
            "shadow_full_feasible": int(
                full_feasible
            ),
            "shadow_full_hard_count": int(
                len(full_hard)
            ),
            "shadow_full_value": float(
                full_value
            ),
            "shadow_full_improvement": float(
                full_improvement
            ),
            "shadow_full_net_beneficial": int(
                full_net_beneficial
            ),
            "screen_false_negative": int(
                screen_false_negative
            ),
            "expansion_was_needed": int(
                expansion_was_needed
            ),
            "expansion_net_benefit_needed": int(
                expansion_net_benefit_needed
            ),
            "expansion_extra_improvement": float(
                expansion_extra_improvement
            ),
            "shadow_audit_solver_calls": int(
                audit_solver_calls
            ),
            "shadow_audit_wall_time_s": float(
                audit_wall_time_s
            ),}
    def act(self, env, obs, masks, deciders):
        del obs, masks

        actions = {
            u: env.A_FOLLOW
            for u in deciders
        }
        token = id(env.scenario)

        if (
            self.previous_snapshot is None
            or token != self.scenario_token
            or env.t < self.last_t - 1e-9
        ):
            self.previous_snapshot = (
                OperationalSnapshot.capture(env)
            )
            self.scenario_token = token
            self.last_t = float(env.t)
            return actions

        current = OperationalSnapshot.capture(env)
        changes = OperationalChanges.between(
            self.previous_snapshot,
            current,
        )
        dependency_graph = PlanBeliefDependencyGraph.build(
            env
        )
        event_type = env.last_decision_event_type
        hard = _hard_infeasible_decisions(
            env,
            env.scaffold,
            dependency_graph,
        )

        if not changes.has_relevant_change and not hard:
            self.previous_snapshot = current
            self.last_t = float(env.t)
            return actions

        trace = trace_impacts(
            env,
            dependency_graph,
            changes,
            event_type,
        )
        ctx = env._plan_context()
        current_value = (
            env.planner.evaluate_belief_value(
                env.scaffold,
                ctx,
            )
        )
        upper_bound = optimistic_value_upper_bound(env)
        j_current = max(
            upper_bound - current_value,
            0.0,
        )
        lower_bound = 0.0
        potential_gain_bound = j_current - lower_bound
        event_impact_proxy = event_impact_value_proxy(
            env,
            self.previous_snapshot,
            current,
            changes,
        )
        solve_cost = float(
            env.p.hybrid.xi_C
            if self.solve_cost is None
            else self.solve_cost
        )
        proxy_activation_threshold = max(
            solve_cost,
            self.proxy_threshold_fraction * upper_bound,
        )
        total_decisions = len(
            dependency_graph.decisions
        )
        initial_scope_fraction = (
            len(trace.mutable) / total_decisions
            if total_decisions
            else (
                1.0
                if changes.has_opportunity
                else 0.0
            )
        )

        record: Dict[str, object] = {
            "time_h": float(env.t),
            "event_kind": trace.event_kind,
            "event_type": (
                event_type.name
                if event_type is not None
                else ""
            ),
            "changed_resources": "|".join(
                sorted(trace.changed_resources)
            ),
            "hard_impact_count": len(trace.hard),
            "direct_impact_count": len(trace.direct),
            "opportunity_seed_count": len(
                trace.opportunity_seeds
            ),
            "mutable_decision_count": len(
                trace.mutable
            ),
            "frozen_decision_count": len(
                trace.frozen
            ),
            "total_decision_count": total_decisions,
            "repair_scope_fraction": float(
                initial_scope_fraction
            ),
            "current_plan_value": float(
                current_value
            ),
            "optimistic_value_upper_bound": float(
                upper_bound
            ),
            "J_current": float(j_current),
            "LB": float(lower_bound),
            "potential_gain_bound": float(
                potential_gain_bound
            ),
            "event_impact_value_proxy": float(
                event_impact_proxy
            ),
            "solve_cost": solve_cost,
            "proxy_threshold_fraction": (
                self.proxy_threshold_fraction
            ),
            "screen_soft_events": int(
                self.screen_soft_events
            ),
            "proxy_activation_threshold": float(
                proxy_activation_threshold
            ),
            "attempted": 0,
            "installed": 0,
            "shadow_audited": 0,
            "shadow_screen_false_negative": 0,
            "shadow_expansion_was_needed": 0,
            "shadow_expansion_net_benefit_needed": 0,
            "shadow_audit_solver_calls": 0,
            "shadow_audit_wall_time_s": 0.0,
            "fallback_full_replan": 0,
            "full_fleet_attempted": 0,
            "neighborhood_attempt_count": 0,
            "neighborhood_levels_attempted": "",
            "accepted_neighborhood_level": 0,
            "accepted_neighborhood_name": "",
            "localized_solve_wall_time_s": 0.0,
            "fallback_solve_wall_time_s": 0.0,
            "repair_wall_time_s": 0.0,
            "repair_solver_calls": 0,
            "candidate_plan_value": float("nan"),
            "actual_improvement": float("nan"),
            "net_improvement_after_solve": float(
                "nan"
            ),
            "outcome": "",
        }

        if not trace.hard and not trace.changed_resources:
            record["outcome"] = (
                "continue_no_relevant_change"
            )

        elif (
            self.screen_soft_events
            and not trace.hard
            and potential_gain_bound
            <= solve_cost + 1e-9
        ):
            record["outcome"] = "certified_continue"

        elif (
            self.screen_soft_events
            and not trace.hard
            and event_impact_proxy
            <= proxy_activation_threshold + 1e-9
        ):
            record["outcome"] = (
                "continue_event_impact_below_threshold"
            )

            if self.shadow_audit_screened_events:
                audit_record = (
                    self._run_screen_shadow_audit(
                        env=env,
                        dependency_graph=(
                            dependency_graph
                        ),
                        trace=trace,
                        ctx=ctx,
                        current_value=current_value,
                        solve_cost=solve_cost,
                        operational_record=record,
                    )
                )

                self.shadow_audit_records.append(
                    audit_record
                )

                record["shadow_audited"] = 1

                record[
                    "shadow_screen_false_negative"
                ] = int(
                    audit_record[
                        "screen_false_negative"
                    ]
                )

                record[
                    "shadow_expansion_was_needed"
                ] = int(
                    audit_record[
                        "expansion_was_needed"
                    ]
                )

                record[
                    "shadow_expansion_net_benefit_needed"
                ] = int(
                    audit_record[
                        "expansion_net_benefit_needed"
                    ]
                )

                record[
                    "shadow_audit_solver_calls"
                ] = int(
                    audit_record[
                        "shadow_audit_solver_calls"
                    ]
                )

                record[
                    "shadow_audit_wall_time_s"
                ] = float(
                    audit_record[
                        "shadow_audit_wall_time_s"
                    ]
                )

        elif env.K_rem <= 0:
            record["outcome"] = (
                "continue_budget_exhausted"
            )

        elif not env.begin_external_resolve():
            record["outcome"] = (
                "continue_budget_exhausted"
            )

        else:
            record["attempted"] = 1

            transaction_calls_before = int(
                env.repair_solver_calls
            )
            transaction_wall_before = float(
                env.repair_solver_wall_time_s
            )

            neighborhoods = expanding_repair_neighborhoods(
                dependency_graph,
                trace,
                selective_repair=self.selective_repair,
            )

            attempted_names: List[str] = []

            selected_candidate: Optional[Scaffold] = None
            selected_hard: Optional[Set[DecisionKey]] = None
            selected_value = -np.inf
            selected_level = 0
            selected_name = ""
            selected_mutable: FrozenSet[DecisionKey] = (
                frozenset()
            )

            accepted = False

            for attempt_index, neighborhood in enumerate(
                neighborhoods,
                start=1,
            ):
                mutable = set(neighborhood.mutable)

                if neighborhood.name == "full_fleet":
                    warm = None
                    frozen = None
                    record["full_fleet_attempted"] = 1
                    record["fallback_full_replan"] = 1
                else:
                    warm = _partial_warm_start(
                        env.scaffold,
                        mutable,
                    )
                    frozen = _frozen_nodes(
                        dependency_graph,
                        mutable,
                    )

                solve_wall_before = float(
                    env.repair_solver_wall_time_s
                )
                candidate = env.propose_scaffold_repair(
                    warm,
                    frozen,
                )
                solve_wall_time = max(
                    float(env.repair_solver_wall_time_s)
                    - solve_wall_before,
                    0.0,
                )

                candidate_graph = (
                    PlanBeliefDependencyGraph.build(
                        env,
                        candidate,
                    )
                )
                candidate_hard = (
                    _hard_infeasible_decisions(
                        env,
                        candidate,
                        candidate_graph,
                    )
                )
                candidate_value = (
                    env.planner.evaluate_belief_value(
                        candidate,
                        ctx,
                    )
                )
                actual_improvement = (
                    candidate_value - current_value
                )
                candidate_feasible = not candidate_hard
                accepted_here = (
                    candidate_feasible
                    and (
                        bool(trace.hard)
                        or actual_improvement
                        > solve_cost + 1e-9
                    )
                )

                mutable_count = len(mutable)
                frozen_count = max(
                    total_decisions - mutable_count,
                    0,
                )
                scope_fraction = (
                    mutable_count / total_decisions
                    if total_decisions
                    else (
                        1.0
                        if changes.has_opportunity
                        else 0.0
                    )
                )

                prefix = f"level_{attempt_index}"
                record[f"{prefix}_hierarchy_level"] = (
                    neighborhood.hierarchy_level
                )
                record[f"{prefix}_name"] = (
                    neighborhood.name
                )
                record[f"{prefix}_mutable_count"] = (
                    mutable_count
                )
                record[f"{prefix}_scope_fraction"] = float(
                    scope_fraction
                )
                record[f"{prefix}_candidate_value"] = float(
                    candidate_value
                )
                record[f"{prefix}_improvement"] = float(
                    actual_improvement
                )
                record[f"{prefix}_hard_count"] = len(
                    candidate_hard
                )
                record[f"{prefix}_feasible"] = int(
                    candidate_feasible
                )
                record[f"{prefix}_accepted"] = int(
                    accepted_here
                )
                record[f"{prefix}_solve_wall_time_s"] = (
                    float(solve_wall_time)
                )

                attempted_names.append(neighborhood.name)

                if neighborhood.name == "causal_decisions":
                    record[
                        "localized_solve_wall_time_s"
                    ] = float(solve_wall_time)
                else:
                    record[
                        "fallback_solve_wall_time_s"
                    ] = float(
                        record[
                            "fallback_solve_wall_time_s"
                        ]
                    ) + float(solve_wall_time)

                if self._prefer_candidate(
                    candidate_hard,
                    candidate_value,
                    selected_hard,
                    selected_value,
                ):
                    selected_candidate = candidate
                    selected_hard = set(candidate_hard)
                    selected_value = float(candidate_value)
                    selected_level = (
                        neighborhood.hierarchy_level
                    )
                    selected_name = neighborhood.name
                    selected_mutable = neighborhood.mutable

                if accepted_here:
                    selected_candidate = candidate
                    selected_hard = set(candidate_hard)
                    selected_value = float(candidate_value)
                    selected_level = (
                        neighborhood.hierarchy_level
                    )
                    selected_name = neighborhood.name
                    selected_mutable = neighborhood.mutable
                    accepted = True
                    break

            if selected_candidate is None or selected_hard is None:
                raise RuntimeError(
                    "Expanding repair produced no candidate"
                )

            transaction_calls = (
                int(env.repair_solver_calls)
                - transaction_calls_before
            )
            transaction_wall_time = max(
                float(env.repair_solver_wall_time_s)
                - transaction_wall_before,
                0.0,
            )

            selected_improvement = (
                selected_value - current_value
            )
            selected_mutable_count = len(
                selected_mutable
            )
            selected_scope_fraction = (
                selected_mutable_count / total_decisions
                if total_decisions
                else (
                    1.0
                    if changes.has_opportunity
                    else 0.0
                )
            )

            record["neighborhood_attempt_count"] = (
                transaction_calls
            )
            record["neighborhood_levels_attempted"] = (
                "|".join(attempted_names)
            )
            record["repair_solver_calls"] = (
                transaction_calls
            )
            record["repair_wall_time_s"] = float(
                transaction_wall_time
            )
            record["candidate_plan_value"] = float(
                selected_value
            )
            record["actual_improvement"] = float(
                selected_improvement
            )
            record["net_improvement_after_solve"] = float(
                selected_improvement - solve_cost
            )
            record["mutable_decision_count"] = (
                selected_mutable_count
            )
            record["frozen_decision_count"] = max(
                total_decisions - selected_mutable_count,
                0,
            )
            record["repair_scope_fraction"] = float(
                selected_scope_fraction
            )

            if accepted:
                env.install_scaffold_repair(
                    selected_candidate
                )
                record["installed"] = 1
                record["accepted_neighborhood_level"] = (
                    selected_level
                )
                record["accepted_neighborhood_name"] = (
                    selected_name
                )

                if trace.hard:
                    record["outcome"] = (
                        "installed_feasibility_repair"
                    )
                else:
                    record["outcome"] = (
                        "installed_net_beneficial"
                    )

            elif selected_hard:
                record["outcome"] = (
                    "rejected_infeasible_candidate"
                )

            else:
                record["outcome"] = (
                    "rejected_no_net_benefit"
                )

            self.repair_wall_time_s += float(
                transaction_wall_time
            )
            self.repair_solver_calls += int(
                transaction_calls
            )

        self.diagnostics.append(record)
        self.previous_snapshot = current
        self.last_t = float(env.t)
        return actions


class OptimisticBoundScreenedFullReplanController(
    EventCausalRepairController
):
    """Ablation retaining the valid screen but removing localization."""

    name = (
        "Optimistic-Bound-Screened Full Replan ALNS"
    )

    def __init__(
        self,
        solve_cost: Optional[float] = None,
        proxy_threshold_fraction: float = 0.0,
    ):
        super().__init__(
            selective_repair=False,
            solve_cost=solve_cost,
            proxy_threshold_fraction=(
                proxy_threshold_fraction
            ),
            screen_soft_events=True,
        )


class EveryEventFullReplanController(
    EventCausalRepairController
):
    """Full-fleet ALNS repair after every observed operational change."""

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

