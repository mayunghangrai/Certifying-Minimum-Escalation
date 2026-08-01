"""Operational belief-graph construction with explicit truth exclusion.

The active environment adapter reads only ``BeliefState``, observable fleet
state, depot inventory, the operational availability matrix, and the
incumbent scaffold. The scenario-v2 adapter reads only ``ControllerState``
plus static node/corridor geometry. Neither adapter reads physical demand,
true vulnerability, hidden events, or physical corridor conditions.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from env.deprivation import belief_urgency
from env.energy import flight_energy
from env.entities import Mode
from env.graph import DEPOT
from env.params import COMMODITY_NAMES, N_COMMODITIES


NODE_TYPE_UAV = 0
NODE_TYPE_AFFECTED = 1
NODE_TYPE_DEPOT = 2

NODE_FEATURE_NAMES = (
    "commodity_0",
    "commodity_1",
    "commodity_2",
    "commodity_3",
    "active_commodity_0",
    "active_commodity_1",
    "active_commodity_2",
    "active_commodity_3",
    "operational_urgency",
    "urgency_growth_one_hour",
    "oldest_cohort_age",
    "oldest_cohort_quantity",
    "reported_vulnerability",
    "information_age",
    "report_confidence",
    "position_x",
    "position_y",
    "known_active",
    "battery_or_inventory_mass",
    "remaining_service_or_travel_time",
    "mode_depot",
    "mode_loading",
    "mode_charging",
    "mode_flying",
    "mode_delivering",
    "mode_returning",
    "depot_queue_fraction",
    "resource_available",
    "committed_destination",
    "payload_mass",
    "total_operational_demand",
    "operational_cohort_count",
)

EDGE_FEATURE_NAMES = (
    "condition_normal",
    "condition_degraded",
    "condition_closed",
    "condition_unknown",
    "believed_travel_time",
    "believed_energy",
    "believed_risk",
    "corridor_information_age",
    "static_feasible",
    "uav_relation",
    "operationally_available",
)

PLAN_FEATURE_NAMES = (
    "plan_age",
    "operational_demand_change",
    "operational_inventory_change",
    "newly_known_fraction",
    "invalid_planned_corridor_fraction",
    "completed_planned_service_fraction",
    "execution_deviation",
    "solver_active",
    "solver_request_age",
    "next_action_operationally_feasible",
)

NORMALIZATION_REFERENCES = {
    "demand_units": 10.0,
    "oldest_quantity_units": 10.0,
    "total_demand_units": 20.0,
    "vulnerability_upper_reference": 3.0,
    "urgency_transform": "log1p(value)/8",
    "position_reference": "configured operating-region width",
    "time_reference": "configured mission horizon",
    "energy_reference": "configured battery capacity",
    "payload_reference": "configured payload capacity",
    "risk_reference": "fixed configured geographical-risk range",
    "plan_features": "dimensionless ratios clipped to [0,1]",
}


@dataclass
class BeliefGraph:
    """Padded, fixed-shape graph plus stable entity/action mappings."""

    node_features: np.ndarray
    node_type_ids: np.ndarray
    edge_index: np.ndarray
    edge_features: np.ndarray
    node_mask: np.ndarray
    edge_mask: np.ndarray
    graph_batch_index: np.ndarray
    entity_id_to_slot: Dict[str, int]
    slot_to_entity_id: Dict[int, str]
    uav_to_node: np.ndarray
    action_to_destination: np.ndarray
    action_to_edge: np.ndarray
    alns_prior: np.ndarray
    plan_features: np.ndarray
    recommended_actions: np.ndarray
    plan_feature_raw: np.ndarray = field(
        default_factory=lambda: np.zeros((0, len(PLAN_FEATURE_NAMES)), np.float32)
    )
    plan_feature_clipped: np.ndarray = field(
        default_factory=lambda: np.zeros((0, len(PLAN_FEATURE_NAMES)), bool)
    )
    plan_feature_defaulted: np.ndarray = field(
        default_factory=lambda: np.zeros((0, len(PLAN_FEATURE_NAMES)), bool)
    )
    zero_prior_reasons: List[str] = field(default_factory=list)
    corridor_id_to_edge: Dict[str, int] = field(default_factory=dict)
    operational_corridor_mask: Dict[str, bool] = field(default_factory=dict)
    metadata: Dict[str, object] = field(default_factory=dict)

    def clone(self) -> "BeliefGraph":
        return copy.deepcopy(self)

    @property
    def node_feature_dim(self) -> int:
        return int(self.node_features.shape[-1])

    @property
    def edge_feature_dim(self) -> int:
        return int(self.edge_features.shape[-1])

    @property
    def max_nodes(self) -> int:
        return int(self.node_features.shape[0])

    @property
    def max_edges(self) -> int:
        return int(self.edge_features.shape[0])


def _condition_one_hot(condition: str) -> List[float]:
    names = ("NORMAL", "DEGRADED", "CLOSED", "UNKNOWN")
    normalized = str(condition).upper()
    if normalized not in names:
        normalized = "UNKNOWN"
    return [float(normalized == name) for name in names]


def _cohort_summary(
    cohorts: Sequence[Mapping[str, object]],
    time_s: float,
    commodity: Mapping[str, Sequence[float]],
    vulnerability: float,
) -> Tuple[np.ndarray, float, float, float, float, int]:
    demand = np.zeros(N_COMMODITIES, dtype=np.float64)
    oldest_age_s = 0.0
    oldest_quantity = 0.0
    oldest_onset = float("inf")
    for cohort in cohorts:
        index = int(cohort["commodity_index"])
        quantity = float(cohort["quantity"])
        onset = float(cohort["onset_time_s"])
        demand[index] += quantity
        if quantity > 1e-12 and onset < oldest_onset:
            oldest_onset = onset
            oldest_quantity = quantity
        oldest_age_s = max(oldest_age_s, max(time_s - onset, 0.0))

    def urgency_at(eval_time_s: float) -> float:
        total = 0.0
        for cohort in cohorts:
            index = int(cohort["commodity_index"])
            age_h = max(
                (eval_time_s - float(cohort["onset_time_s"])) / 3600.0, 0.0
            )
            growth = float(commodity["waiting_growth_per_hour"][index])
            total += (
                float(commodity["criticality"][index])
                * float(cohort["quantity"])
                * float(commodity["waiting_scale"][index])
                * growth
                * math.exp(growth * age_h)
            )
        return float(vulnerability) * total

    urgency = urgency_at(time_s)
    urgency_later = urgency_at(time_s + 3600.0)
    return (
        demand,
        urgency,
        max(urgency_later - urgency, 0.0),
        oldest_age_s,
        oldest_quantity,
        len(cohorts),
    )


class OperationalBeliefGraphBuilder:
    """Build fixed-size graphs from operational state only."""

    def __init__(self, max_known_nodes: Optional[int] = None):
        self.max_known_nodes = max_known_nodes

    # ------------------------------------------------------------------
    # Active environment adapter
    # ------------------------------------------------------------------
    def build_from_env(self, env) -> BeliefGraph:
        """Build from the active environment's belief-side state.

        Access to ``env.nodes`` is limited to public coordinates. Demand and
        vulnerability are read only from ``env.belief``.
        """
        max_affected = self.max_known_nodes or env.N
        if env.N > max_affected:
            raise ValueError(
                f"Environment has {env.N} affected nodes, exceeding graph "
                f"capacity {max_affected}"
            )
        max_nodes = env.M + 1 + max_affected
        max_edges = (max_affected + 1) * max_affected + 2 * env.M * (
            max_affected + 1
        )
        node_features = np.zeros((max_nodes, len(NODE_FEATURE_NAMES)), np.float32)
        node_types = np.full(max_nodes, NODE_TYPE_AFFECTED, np.int64)
        node_mask = np.zeros(max_nodes, bool)
        entity_to_slot: Dict[str, int] = {}
        slot_to_entity: Dict[int, str] = {}

        region = max(float(env.p.map.region_km), 1e-6)
        horizon = max(float(env.T), 1e-6)
        w_k, lambda_k, alpha_k, kappa_k = env.p.commodities.as_arrays()
        active_mask = np.ones(N_COMMODITIES, dtype=np.float32)

        for u, uav in enumerate(env.uavs):
            slot = u
            entity = f"UAV{u}"
            entity_to_slot[entity] = slot
            slot_to_entity[slot] = entity
            node_mask[slot] = True
            node_types[slot] = NODE_TYPE_UAV
            position = uav.position_at(env.t)
            remaining = max(uav.arrive_time - env.t, 0.0)
            node_features[slot, 0:4] = uav.ell / 10.0
            node_features[slot, 15:17] = position / region
            node_features[slot, 17] = 1.0
            node_features[slot, 18] = uav.b / max(env.p.physics.B_max, 1e-6)
            node_features[slot, 19] = remaining / horizon
            node_features[slot, 20 + uav.mode.value] = 1.0
            if uav.dest_node is not None:
                node_features[slot, 28] = (
                    (uav.dest_node + 1) / max(env.N + 1, 1)
                )
            node_features[slot, 29] = (
                uav.payload_mass(w_k) / max(env.p.physics.W_max, 1e-6)
            )

        depot_slot = env.M
        entity_to_slot["DEPOT"] = depot_slot
        slot_to_entity[depot_slot] = "DEPOT"
        node_mask[depot_slot] = True
        node_types[depot_slot] = NODE_TYPE_DEPOT
        node_features[depot_slot, 0:4] = (
            env.inventory.S0 / np.maximum(np.asarray(env.scenario.S0_init), 1.0)
        )
        node_features[depot_slot, 4:8] = active_mask
        node_features[depot_slot, 15:17] = env.depot_pos / region
        node_features[depot_slot, 17] = 1.0
        stock_mass = float(np.dot(w_k, env.inventory.S0))
        initial_mass = max(float(np.dot(w_k, env.scenario.S0_init)), 1.0)
        node_features[depot_slot, 18] = stock_mass / initial_mass
        busy = sum(float(t > env.t) for t in env._bay_free)
        node_features[depot_slot, 26] = busy / max(len(env._bay_free), 1)
        node_features[depot_slot, 27] = float(np.any(env.inventory.S0 > 1e-9))

        for i in range(env.N):
            slot = env.M + 1 + i
            entity = f"N{i}"
            node_types[slot] = NODE_TYPE_AFFECTED
            if not env.belief.is_known(i):
                continue
            entity_to_slot[entity] = slot
            slot_to_entity[slot] = entity
            entry = env.belief.entries[i]
            demand = np.maximum(entry.mu, 0.0)
            age = env.belief.age_hat(i, env.t)
            vulnerability = env.belief.vulnerability(i)
            urgency = belief_urgency(
                vulnerability,
                demand,
                age,
                lambda_k,
                alpha_k,
                kappa_k,
            )
            urgency_later = belief_urgency(
                vulnerability,
                demand,
                age + 1.0,
                lambda_k,
                alpha_k,
                kappa_k,
            )
            positive = np.flatnonzero(demand > 1e-12)
            oldest_age = float(age[positive].max()) if len(positive) else 0.0
            oldest_index = (
                int(positive[np.argmax(age[positive])]) if len(positive) else 0
            )
            node_mask[slot] = True
            node_features[slot, 0:4] = demand / 10.0
            node_features[slot, 4:8] = active_mask
            node_features[slot, 8] = math.log1p(max(urgency, 0.0)) / 8.0
            node_features[slot, 9] = (
                math.log1p(max(urgency_later - urgency, 0.0)) / 8.0
            )
            node_features[slot, 10] = oldest_age / horizon
            node_features[slot, 11] = demand[oldest_index] / 10.0
            node_features[slot, 12] = vulnerability / 3.0
            generation_time = getattr(
                entry, "t_last_generation", entry.t_last_report
            )
            node_features[slot, 13] = max(env.t - generation_time, 0.0) / horizon
            node_features[slot, 14] = entry.gamma
            node_features[slot, 15:17] = env.nodes[i].pos / region
            node_features[slot, 17] = 1.0
            node_features[slot, 30] = demand.sum() / 20.0
            node_features[slot, 31] = float(len(positive)) / N_COMMODITIES

        edge_index = np.zeros((2, max_edges), np.int64)
        edge_features = np.zeros((max_edges, len(EDGE_FEATURE_NAMES)), np.float32)
        edge_mask = np.zeros(max_edges, bool)
        edge_lookup: Dict[Tuple[str, str], int] = {}
        edge_cursor = 0
        location_entities = ["DEPOT"] + [
            f"N{i}" for i in range(env.N) if env.belief.is_known(i)
        ]
        for origin in location_entities:
            for destination in location_entities:
                if origin == destination:
                    continue
                oi = DEPOT if origin == "DEPOT" else int(origin[1:])
                di = DEPOT if destination == "DEPOT" else int(destination[1:])
                condition = "NORMAL" if env.graph.A(oi, di) else "CLOSED"
                length = env.graph.euclidean(oi, di)
                travel = length / env.p.physics.v_uav
                energy = flight_energy(
                    length, env.p.physics.W_max, env.p.physics
                )
                risk = float(
                    getattr(env, "_operational_edge_risk", {}).get((oi, di), 0.0)
                )
                report_time = float(
                    getattr(env, "_corridor_report_generation", {}).get(
                        (oi, di), 0.0
                    )
                )
                values = _condition_one_hot(condition) + [
                    travel / horizon,
                    energy / max(env.p.physics.B_max, 1e-6),
                    risk / region,
                    max(env.t - report_time, 0.0) / horizon,
                    1.0,
                    0.0,
                    float(condition != "CLOSED"),
                ]
                edge_index[:, edge_cursor] = [
                    entity_to_slot[origin],
                    entity_to_slot[destination],
                ]
                edge_features[edge_cursor] = values
                edge_mask[edge_cursor] = True
                edge_lookup[(origin, destination)] = edge_cursor
                edge_cursor += 1

        for u in range(env.M):
            uav_entity = f"UAV{u}"
            anchor_index = env._anchor_node(u)
            anchor_entity = "DEPOT" if anchor_index == DEPOT else f"N{anchor_index}"
            for location in location_entities:
                li = DEPOT if location == "DEPOT" else int(location[1:])
                condition = "NORMAL" if env.graph.A(anchor_index, li) else "CLOSED"
                distance = float(
                    np.linalg.norm(
                        env.uavs[u].position_at(env.t) - env.graph.pos_of(li)
                    )
                )
                travel = distance / env.p.physics.v_uav
                energy = flight_energy(
                    distance,
                    env.uavs[u].payload_mass(w_k),
                    env.p.physics,
                )
                values = _condition_one_hot(condition) + [
                    travel / horizon,
                    energy / max(env.p.physics.B_max, 1e-6),
                    0.0,
                    max(
                        env.t
                        - float(
                            getattr(env, "_corridor_report_generation", {}).get(
                                (anchor_index, li), 0.0
                            )
                        ),
                        0.0,
                    )
                    / horizon,
                    1.0,
                    1.0,
                    float(condition != "CLOSED"),
                ]
                for origin, destination in (
                    (uav_entity, location),
                    (location, uav_entity),
                ):
                    edge_index[:, edge_cursor] = [
                        entity_to_slot[origin],
                        entity_to_slot[destination],
                    ]
                    edge_features[edge_cursor] = values
                    edge_mask[edge_cursor] = True
                    edge_lookup[(origin, destination)] = edge_cursor
                    edge_cursor += 1

        action_to_destination, action_to_edge = self._active_action_mappings(
            env, entity_to_slot, edge_lookup
        )
        (
            plan_features,
            priors,
            recommendations,
            plan_raw,
            plan_clipped,
            plan_defaulted,
            zero_prior_reasons,
        ) = self._plan_guidance(env)
        return BeliefGraph(
            node_features=node_features,
            node_type_ids=node_types,
            edge_index=edge_index,
            edge_features=edge_features,
            node_mask=node_mask,
            edge_mask=edge_mask,
            graph_batch_index=np.zeros(max_nodes, np.int64),
            entity_id_to_slot=entity_to_slot,
            slot_to_entity_id=slot_to_entity,
            uav_to_node=np.arange(env.M, dtype=np.int64),
            action_to_destination=action_to_destination,
            action_to_edge=action_to_edge,
            alns_prior=priors,
            plan_features=plan_features,
            recommended_actions=recommendations,
            plan_feature_raw=plan_raw,
            plan_feature_clipped=plan_clipped,
            plan_feature_defaulted=plan_defaulted,
            zero_prior_reasons=zero_prior_reasons,
            metadata={
                "source": "active_operational_belief",
                "time_hours": float(env.t),
                "node_feature_names": NODE_FEATURE_NAMES,
                "edge_feature_names": EDGE_FEATURE_NAMES,
                "plan_feature_names": PLAN_FEATURE_NAMES,
                "active_commodity_mask": [1, 1, 1, 1],
                "uav_anchor_entities": {
                    f"UAV{u}": (
                        "DEPOT"
                        if env._anchor_node(u) == DEPOT
                        else f"N{env._anchor_node(u)}"
                    )
                    for u in range(env.M)
                },
            },
        )

    def _active_action_mappings(
        self,
        env,
        entity_to_slot: Mapping[str, int],
        edge_lookup: Mapping[Tuple[str, str], int],
    ) -> Tuple[np.ndarray, np.ndarray]:
        destinations = np.full((env.M, env.n_actions), -1, np.int64)
        edges = np.full((env.M, env.n_actions), -1, np.int64)
        for u in range(env.M):
            anchor_index = env._anchor_node(u)
            anchor = "DEPOT" if anchor_index == DEPOT else f"N{anchor_index}"
            uav_entity = f"UAV{u}"
            destinations[u, env.A_RETURN] = entity_to_slot["DEPOT"]
            edges[u, env.A_RETURN] = edge_lookup.get((uav_entity, "DEPOT"), -1)
            nxt = env.scaffold.peek_next(u)
            if nxt is not None and env.belief.is_known(nxt.node):
                destination = f"N{nxt.node}"
                destinations[u, env.A_FOLLOW] = entity_to_slot[destination]
                edges[u, env.A_FOLLOW] = edge_lookup.get(
                    (uav_entity, destination), -1
                )
            for i in range(env.N):
                destination = f"N{i}"
                if destination not in entity_to_slot:
                    continue
                for action in (env.encode_insert(i), env.encode_skip(i)):
                    destinations[u, action] = entity_to_slot[destination]
                    edges[u, action] = edge_lookup.get((uav_entity, destination), -1)
                for other in range(env.M):
                    if other == u:
                        continue
                    action = env.encode_swap(i, u, other)
                    destinations[u, action] = entity_to_slot[destination]
                    edges[u, action] = edge_lookup.get(
                        (f"UAV{other}", destination), -1
                    )
        return destinations, edges

    def _plan_guidance(
        self, env
    ) -> Tuple[
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        List[str],
    ]:
        features = np.zeros((env.M, len(PLAN_FEATURE_NAMES)), np.float32)
        raw_features = np.zeros_like(features)
        clipped = np.zeros_like(features, dtype=bool)
        defaulted = np.zeros_like(features, dtype=bool)
        priors = np.zeros((env.M, env.n_actions), np.float32)
        recommendations = np.full(env.M, -1, np.int64)
        zero_reasons = ["OTHER"] * env.M
        scaffold = env.scaffold
        age = max(env.t - scaffold.created_t, 0.0) / max(env.T, 1e-6)

        demand_num = demand_den = 0.0
        for i, old in scaffold.mu_snapshot.items():
            new = (
                env.belief.entries[i].mu
                if env.belief.is_known(i)
                else np.zeros_like(old)
            )
            demand_num += float(np.abs(new - old).sum())
            demand_den += float(np.abs(old).sum())
        demand_change = demand_num / max(demand_den, 1.0)

        inventory_snapshot = np.asarray(
            getattr(scaffold, "inventory_snapshot", env.inventory.S0),
            dtype=float,
        )
        inventory_change = float(
            np.abs(env.inventory.S0 - inventory_snapshot).sum()
            / max(np.abs(inventory_snapshot).sum(), 1.0)
        )
        new_fraction = len(env.belief.known - scaffold.known_snapshot) / max(
            env.N, 1
        )
        initial_count = int(
            getattr(
                scaffold,
                "planned_service_count",
                sum(len(s.visits) for ss in scaffold.plans.values() for s in ss),
            )
        )
        remaining_count = sum(
            len(s.visits) for ss in scaffold.plans.values() for s in ss
        )
        completed_fraction = (
            max(initial_count - remaining_count, 0) / max(initial_count, 1)
        )

        invalid = total_legs = 0
        for u, sorties in scaffold.plans.items():
            anchor = env._anchor_node(u)
            for sortie in sorties:
                previous = anchor
                for visit in sortie.visits:
                    total_legs += 1
                    invalid += int(not env.graph.A(previous, visit.node))
                    previous = visit.node
                if sortie.visits:
                    total_legs += 1
                    invalid += int(not env.graph.A(previous, DEPOT))
                anchor = DEPOT
        invalid_fraction = invalid / max(total_legs, 1)

        for u in range(env.M):
            nxt = scaffold.peek_next(u)
            feasible = bool(nxt is not None and env._leg_feasible(u, nxt.node))
            execution_deviation = 0.0
            if env.uavs[u].mode in (Mode.FLYING, Mode.RETURNING):
                expected = None if nxt is None else nxt.node
                execution_deviation = float(env.uavs[u].dest_node != expected)
            raw = np.asarray([
                age,
                demand_change,
                inventory_change,
                new_fraction,
                invalid_fraction,
                completed_fraction,
                execution_deviation,
                float(getattr(env, "alns_solving", False)),
                (
                    max(env.t - float(env.alns_request_t), 0.0) / max(env.T, 1e-6)
                    if getattr(env, "alns_request_t", None) is not None
                    else 0.0
                ),
                float(feasible),
            ], dtype=np.float32)
            raw_features[u] = raw
            features[u] = np.clip(raw, 0.0, 1.0)
            clipped[u] = np.abs(raw - features[u]) > 1e-12
            defaulted[u, 1] = not bool(scaffold.mu_snapshot)
            defaulted[u, 3] = not bool(scaffold.known_snapshot)
            defaulted[u, 4] = total_legs == 0
            defaulted[u, 5] = initial_count == 0
            defaulted[u, 8] = getattr(env, "alns_request_t", None) is None
            defaulted[u, 9] = nxt is None
            if feasible:
                priors[u, env.A_FOLLOW] = 1.0
                recommendations[u] = env.A_FOLLOW
                zero_reasons[u] = ""
            elif nxt is None:
                if initial_count > 0 and remaining_count == 0:
                    zero_reasons[u] = "RECOMMENDATION_ALREADY_COMPLETED"
                else:
                    zero_reasons[u] = "NO_UAV_RECOMMENDATION"
            elif not env.belief.is_known(nxt.node):
                zero_reasons[u] = "RECOMMENDATION_INVALID"
            else:
                zero_reasons[u] = "RECOMMENDATION_INVALID"
        return (
            features,
            priors,
            recommendations,
            raw_features,
            clipped,
            defaulted,
            zero_reasons,
        )

    # ------------------------------------------------------------------
    # Scenario-v2 ControllerState adapter for seed-18427 auditing
    # ------------------------------------------------------------------
    def build_from_controller(self, scenario, controller) -> BeliefGraph:
        """Build seed-audit graph from controller-visible state plus static data."""
        node_by_id = {node["node_id"]: node for node in scenario.nodes}
        known_ids = sorted(
            controller.known_nodes,
            key=lambda value: int(value[1:]) if value[1:].isdigit() else value,
        )
        max_affected = self.max_known_nodes or len(scenario.nodes)
        fleet_count = int(scenario.fleet["uav_count"])
        max_nodes = fleet_count + 1 + max_affected
        corridors = sorted(
            scenario.corridors, key=lambda corridor: corridor.corridor_id
        )
        max_edges = len(corridors) + 2 * fleet_count * (max_affected + 1)
        node_features = np.zeros((max_nodes, len(NODE_FEATURE_NAMES)), np.float32)
        node_types = np.full(max_nodes, NODE_TYPE_AFFECTED, np.int64)
        node_mask = np.zeros(max_nodes, bool)
        entity_to_slot: Dict[str, int] = {}
        slot_to_entity: Dict[int, str] = {}
        width = max(float(scenario.geography["width_m"]), 1.0)
        horizon_s = max(
            max(
                (
                    float(zone["active_to_s"])
                    for zone in scenario.geography["dynamic_zones"]
                ),
                default=8.0 * 3600.0,
            ),
            8.0 * 3600.0,
        )
        active_mask = np.asarray(
            scenario.metadata["active_commodity_mask"], dtype=np.float32
        )

        for u in range(fleet_count):
            entity_to_slot[f"UAV{u}"] = u
            slot_to_entity[u] = f"UAV{u}"
            node_mask[u] = True
            node_types[u] = NODE_TYPE_UAV
            node_features[u, 15:17] = [
                scenario.depot["x_m"] / width,
                scenario.depot["y_m"] / width,
            ]
            node_features[u, 17] = 1.0
            node_features[u, 18] = 1.0
            node_features[u, 20] = 1.0

        depot_slot = fleet_count
        entity_to_slot["DEPOT"] = depot_slot
        slot_to_entity[depot_slot] = "DEPOT"
        node_mask[depot_slot] = True
        node_types[depot_slot] = NODE_TYPE_DEPOT
        node_features[depot_slot, 0:4] = np.asarray(
            controller.depot_inventory, dtype=float
        ) / np.maximum(np.asarray(scenario.depot["initial_inventory"]), 1.0)
        node_features[depot_slot, 4:8] = active_mask
        node_features[depot_slot, 15:17] = [
            scenario.depot["x_m"] / width,
            scenario.depot["y_m"] / width,
        ]
        node_features[depot_slot, 17] = 1.0
        node_features[depot_slot, 27] = float(
            np.any(np.asarray(controller.depot_inventory) > 1e-9)
        )

        commodity = scenario.config["commodities"]
        for physical_index, node in enumerate(scenario.nodes):
            node_id = node["node_id"]
            slot = fleet_count + 1 + physical_index
            node_types[slot] = NODE_TYPE_AFFECTED
            if node_id not in controller.known_nodes:
                continue
            entity_to_slot[node_id] = slot
            slot_to_entity[slot] = node_id
            cohorts = controller.operational_cohorts.get(node_id, [])
            vulnerability = controller.reported_vulnerability[node_id]
            (
                demand,
                urgency,
                urgency_growth,
                oldest_age_s,
                oldest_quantity,
                cohort_count,
            ) = _cohort_summary(
                cohorts, controller.time_s, commodity, vulnerability
            )
            generation = float(
                getattr(controller, "node_report_generation_time_s", {}).get(
                    node_id, 0.0
                )
            )
            confidence = float(
                getattr(controller, "node_report_confidence", {}).get(
                    node_id, 1.0
                )
            )
            node_mask[slot] = True
            node_features[slot, 0:4] = demand / 10.0
            node_features[slot, 4:8] = active_mask
            node_features[slot, 8] = math.log1p(urgency) / 8.0
            node_features[slot, 9] = math.log1p(urgency_growth) / 8.0
            node_features[slot, 10] = oldest_age_s / horizon_s
            node_features[slot, 11] = oldest_quantity / 10.0
            node_features[slot, 12] = vulnerability / 3.0
            node_features[slot, 13] = max(
                controller.time_s - generation, 0.0
            ) / horizon_s
            node_features[slot, 14] = confidence
            node_features[slot, 15:17] = [
                node_by_id[node_id]["x_m"] / width,
                node_by_id[node_id]["y_m"] / width,
            ]
            node_features[slot, 17] = 1.0
            node_features[slot, 30] = demand.sum() / 20.0
            node_features[slot, 31] = cohort_count / 8.0

        edge_index = np.zeros((2, max_edges), np.int64)
        edge_features = np.zeros((max_edges, len(EDGE_FEATURE_NAMES)), np.float32)
        edge_mask = np.zeros(max_edges, bool)
        corridor_id_to_edge: Dict[str, int] = {}
        operational_corridor_mask: Dict[str, bool] = {}
        cursor = 0
        for corridor in corridors:
            if corridor.origin != "DEPOT" and corridor.origin not in known_ids:
                continue
            if (
                corridor.destination != "DEPOT"
                and corridor.destination not in known_ids
            ):
                continue
            condition = controller.believed_corridor_conditions.get(
                corridor.corridor_id, "UNKNOWN"
            )
            multiplier = scenario.geography["condition_multipliers"]
            time_value = corridor.nominal_travel_time_s
            energy = corridor.nominal_energy_wh
            risk = corridor.integrated_geographical_risk
            if condition == "DEGRADED":
                time_value *= multiplier["time"]
                energy *= multiplier["energy"]
                risk *= multiplier["risk"]
            available = condition not in {"CLOSED", "UNKNOWN"}
            generation = float(
                getattr(
                    controller, "corridor_report_generation_time_s", {}
                ).get(corridor.corridor_id, 0.0)
            )
            edge_index[:, cursor] = [
                entity_to_slot[corridor.origin],
                entity_to_slot[corridor.destination],
            ]
            edge_features[cursor] = _condition_one_hot(condition) + [
                time_value / horizon_s,
                energy / max(scenario.fleet["battery_capacity_wh"], 1.0),
                risk,
                max(controller.time_s - generation, 0.0) / horizon_s,
                float(corridor.static_feasible),
                0.0,
                float(available),
            ]
            edge_mask[cursor] = True
            corridor_id_to_edge[corridor.corridor_id] = cursor
            operational_corridor_mask[corridor.corridor_id] = available
            cursor += 1

        for u in range(fleet_count):
            for entity in ["DEPOT"] + known_ids:
                values = _condition_one_hot("NORMAL") + [
                    0.0,
                    0.0,
                    0.0,
                    controller.time_s / horizon_s,
                    1.0,
                    1.0,
                    1.0,
                ]
                for origin, destination in (
                    (f"UAV{u}", entity),
                    (entity, f"UAV{u}"),
                ):
                    edge_index[:, cursor] = [
                        entity_to_slot[origin],
                        entity_to_slot[destination],
                    ]
                    edge_features[cursor] = values
                    edge_mask[cursor] = True
                    cursor += 1

        return BeliefGraph(
            node_features=node_features,
            node_type_ids=node_types,
            edge_index=edge_index,
            edge_features=edge_features,
            node_mask=node_mask,
            edge_mask=edge_mask,
            graph_batch_index=np.zeros(max_nodes, np.int64),
            entity_id_to_slot=entity_to_slot,
            slot_to_entity_id=slot_to_entity,
            uav_to_node=np.arange(fleet_count, dtype=np.int64),
            action_to_destination=np.full((fleet_count, 0), -1, np.int64),
            action_to_edge=np.full((fleet_count, 0), -1, np.int64),
            alns_prior=np.zeros((fleet_count, 0), np.float32),
            plan_features=np.zeros(
                (fleet_count, len(PLAN_FEATURE_NAMES)), np.float32
            ),
            recommended_actions=np.full(fleet_count, -1, np.int64),
            plan_feature_raw=np.zeros(
                (fleet_count, len(PLAN_FEATURE_NAMES)), np.float32
            ),
            plan_feature_clipped=np.zeros(
                (fleet_count, len(PLAN_FEATURE_NAMES)), bool
            ),
            plan_feature_defaulted=np.ones(
                (fleet_count, len(PLAN_FEATURE_NAMES)), bool
            ),
            zero_prior_reasons=[
                "NO_INCUMBENT_PLAN" for _ in range(fleet_count)
            ],
            corridor_id_to_edge=corridor_id_to_edge,
            operational_corridor_mask=operational_corridor_mask,
            metadata={
                "source": "scenario_v2_controller_state",
                "time_s": float(controller.time_s),
                "node_feature_names": NODE_FEATURE_NAMES,
                "edge_feature_names": EDGE_FEATURE_NAMES,
                "active_commodity_mask": active_mask.astype(int).tolist(),
            },
        )
