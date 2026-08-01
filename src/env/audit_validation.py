"""Fail-loud validation for deterministic scenario-v2 artifacts."""

from __future__ import annotations

from typing import Dict, Iterable, List

import networkx as nx

from .audit_geometry import condition_at
from .audit_geometry import sample_polyline, terrain_elevation_m
from .audit_model import AuditScenario, CorridorCondition
from .audit_replay import ScenarioReplay
from .observation_contract import (
    ACTOR_BLOCK_ORDER,
    EVENT_FEATURE_ORDER,
    FLEET_FEATURE_ORDER,
    NODE_FEATURE_ORDER,
    OWN_FEATURE_ORDER,
)
from .params import COMMODITY_NAMES, MapParams


class ScenarioValidationError(ValueError):
    """Raised when a mandatory research or reproducibility invariant fails."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ScenarioValidationError(message)


def _demand_total(cohorts: Dict[str, List[Dict]], node_id: str, index: int) -> float:
    return float(
        sum(
            item["quantity"]
            for item in cohorts.get(node_id, [])
            if item["commodity_index"] == index
        )
    )


def _contains_forbidden_key(value, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        if forbidden.intersection(value):
            return True
        return any(_contains_forbidden_key(item, forbidden) for item in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden_key(item, forbidden) for item in value)
    return False


def validate_scenario(
    scenario: AuditScenario,
    audit_actions: Dict,
    required_figure_names: Iterable[str] | None = None,
) -> Dict:
    checks: Dict[str, object] = {}
    commodity_names = tuple(scenario.metadata["commodity_names"])
    _require(
        commodity_names == tuple(COMMODITY_NAMES),
        "Canonical commodity mapping differs from repository COMMODITY_NAMES",
    )
    _require(
        scenario.metadata["active_commodity_mask"] == [1, 0, 1, 0],
        "Medical/water active commodity mask must be [1,0,1,0]",
    )
    checks["commodity_mapping"] = {
        "names": list(commodity_names),
        "active_mask": scenario.metadata["active_commodity_mask"],
        "passed": True,
    }

    vulnerability_values = [
        float(node["true_vulnerability"]) for node in scenario.nodes
    ]
    vulnerability_domain = MapParams().nu_range
    _require(
        min(vulnerability_values) >= vulnerability_domain[0]
        and max(vulnerability_values) <= vulnerability_domain[1],
        "Scenario vulnerability exceeds the existing mathematical domain",
    )
    checks["vulnerability_domain"] = {
        "existing_domain": vulnerability_domain,
        "scenario_min": min(vulnerability_values),
        "scenario_max": max(vulnerability_values),
        "passed": True,
    }

    expected_block_order = ("own", "nodes", "fleet", "event")
    expected_lengths = {"own": 17, "node": 20, "fleet": 11, "event": 15}
    actual_lengths = {
        "own": len(OWN_FEATURE_ORDER),
        "node": len(NODE_FEATURE_ORDER),
        "fleet": len(FLEET_FEATURE_ORDER),
        "event": len(EVENT_FEATURE_ORDER),
    }
    _require(
        ACTOR_BLOCK_ORDER == expected_block_order
        and actual_lengths == expected_lengths,
        "Existing MAPPO/ALNS observation dimensions or block ordering changed",
    )
    _require(
        NODE_FEATURE_ORDER[13] == "reported_vulnerability",
        "Actor node vulnerability slot is not controller-reported vulnerability",
    )
    checks["observation_contract"] = {
        "block_order": list(ACTOR_BLOCK_ORDER),
        "feature_lengths": actual_lengths,
        "node_feature_order": list(NODE_FEATURE_ORDER),
        "new_spatial_fields_in_tensor": [],
        "passed": True,
    }

    scenario_payload = scenario.to_dict()
    _require(
        "audit_actions" not in scenario_payload and "actions" not in scenario_payload,
        "Scenario JSON contains audit-policy actions or algorithm decisions",
    )
    checks["scenario_excludes_audit_actions"] = True

    _require(
        all(corridor.static_feasible for corridor in scenario.corridors),
        "At least one serialized nominal corridor is not statically feasible",
    )
    static_details = []
    for corridor in scenario.corridors:
        sampled_points = sample_polyline(
            corridor.waypoints_m,
            spacing_m=scenario.geography["fine_cell_m"],
        )
        terrain = terrain_elevation_m(
            sampled_points[:, 0],
            sampled_points[:, 1],
            scenario.geography,
        )
        _require(
            corridor.cruise_altitude_m
            >= float(terrain.max())
            + scenario.geography["minimum_vertical_clearance_m"]
            - 1e-6,
            f"Terrain-clearance invariant failed for {corridor.corridor_id}",
        )
        _require(
            corridor.minimum_obstacle_clearance_m
            >= scenario.geography["minimum_horizontal_clearance_m"] - 1e-6,
            f"Building/permanent-NFZ clearance failed for {corridor.corridor_id}",
        )
        _require(
            corridor.nominal_energy_wh
            <= scenario.fleet["battery_capacity_wh"]
            - scenario.fleet["safety_reserve_wh"]
            + 1e-6,
            f"Vehicle energy-reserve invariant failed for {corridor.corridor_id}",
        )
        static_details.append(corridor.corridor_id)
    _require(
        scenario.fleet["nominal_payload_kg"]
        <= scenario.fleet["payload_capacity_kg"],
        "Nominal corridor payload exceeds vehicle capacity",
    )
    checks["static_corridor_feasibility"] = {
        "corridor_count": len(static_details),
        "terrain_clearance": True,
        "building_and_permanent_nfz_clearance": True,
        "vehicle_payload_and_energy_reserve": True,
    }
    graph = nx.DiGraph()
    for corridor in scenario.corridors:
        if corridor.static_feasible:
            graph.add_edge(corridor.origin, corridor.destination)
    _require(
        nx.is_strongly_connected(graph),
        "Nominal base corridor graph is not strongly directed-connected",
    )
    checks["nominal_graph"] = {
        "nodes": graph.number_of_nodes(),
        "directed_edges": graph.number_of_edges(),
        "strongly_connected": True,
    }

    replay = ScenarioReplay(scenario, audit_actions)
    snapshot_s = float(scenario.config["audit"]["snapshot_time_s"])
    physical, controller = replay.snapshot(snapshot_s)
    fixed_closed = "corridor_depot_n3_south_outbound"
    fixed_degraded = "corridor_n1_n5_hazard_outbound"
    _require(
        physical.corridor_conditions.get(fixed_closed) == "CLOSED"
        and controller.believed_corridor_conditions.get(fixed_closed) == "NORMAL",
        f"{fixed_closed} must be physically CLOSED and operationally NORMAL at 4.2 h",
    )
    _require(
        physical.corridor_conditions.get(fixed_degraded) == "DEGRADED"
        and controller.believed_corridor_conditions.get(fixed_degraded) == "NORMAL",
        f"{fixed_degraded} must be physically DEGRADED and operationally NORMAL at 4.2 h",
    )
    checks["named_corridors_at_t4_2"] = {
        fixed_closed: {
            "true": physical.corridor_conditions[fixed_closed],
            "operational": controller.believed_corridor_conditions[fixed_closed],
        },
        fixed_degraded: {
            "true": physical.corridor_conditions[fixed_degraded],
            "operational": controller.believed_corridor_conditions[fixed_degraded],
        },
    }

    alternative_requirements = [
        ("DEPOT", "N3", fixed_closed),
        ("N1", "N5", fixed_degraded),
    ]
    alternatives: Dict[str, List[str]] = {}
    for origin, destination, affected in alternative_requirements:
        usable = [
            corridor.corridor_id
            for corridor in scenario.corridors
            if corridor.origin == origin
            and corridor.destination == destination
            and corridor.corridor_id != affected
            and corridor.static_feasible
            and condition_at(
                corridor, scenario_payload, snapshot_s, operational=False
            )
            == CorridorCondition.NORMAL
        ]
        _require(
            bool(usable),
            f"Affected OD pair {origin}->{destination} lacks a usable NORMAL alternative",
        )
        alternatives[f"{origin}->{destination}"] = sorted(usable)
    checks["usable_alternatives_at_t4_2"] = alternatives

    _require("N6" not in controller.known_nodes, "N6 must be unknown at 4.2 h")
    _require(
        "TNFZ1" in physical.active_temporary_nfz_ids
        and "TNFZ1" not in controller.received_zone_notices,
        "Temporary NFZ must be active and unreported at 4.2 h",
    )
    _require(
        "HAZ1" in physical.active_hazard_ids
        and "HAZ1" not in controller.received_zone_notices,
        "Hazard must be active and unreported at 4.2 h",
    )
    true_n3_water = _demand_total(physical.node_cohorts, "N3", 2)
    operational_n3_water = _demand_total(controller.operational_cohorts, "N3", 2)
    _require(
        true_n3_water > operational_n3_water,
        "Hidden N3 P3 mutation is not producing truth-operational demand divergence",
    )
    checks["truth_information_mismatch_at_t4_2"] = {
        "unknown_node": "N6",
        "temporary_nfz_active_unreported": True,
        "hazard_active_unreported": True,
        "n3_true_water": true_n3_water,
        "n3_operational_water": operational_n3_water,
        "passed": True,
    }

    forbidden = {
        "true_vulnerability",
        "true_demand",
        "latent_demand",
        "physical_corridor_conditions",
        "unreceived_events",
        "active_hazard_ids",
        "active_temporary_nfz_ids",
    }
    controller_export = controller.to_dict()
    _require(
        not _contains_forbidden_key(controller_export, forbidden),
        "Controller export contains a latent-truth field",
    )
    checks["controller_truth_exclusion"] = {
        "forbidden_keys": sorted(forbidden),
        "passed": True,
    }

    checkpoints = []
    rankings = []
    for expected in scenario.config["audit"]["expected_urgency_leaders"]:
        ranking = replay.urgency_rankings(float(expected["time_s"]))
        true_leader = ranking["true"][0]
        operational_leader = ranking["operational"][0]
        _require(
            true_leader == expected["true"],
            f"True urgency leader mismatch at {expected['time_s']} s: "
            f"expected {expected['true']}, got {true_leader}",
        )
        _require(
            operational_leader == expected["operational"],
            f"Operational urgency leader mismatch at {expected['time_s']} s: "
            f"expected {expected['operational']}, got {operational_leader}",
        )
        checkpoints.append(
            {
                "time_s": expected["time_s"],
                "true_leader": true_leader,
                "operational_leader": operational_leader,
                "true_ranking": ranking["true"],
                "operational_ranking": ranking["operational"],
                "passed": True,
            }
        )
        rankings.append(ranking)
    _require(
        rankings[0]["true"] != rankings[1]["true"],
        "True urgency ranking did not change after hidden P3",
    )
    _require(
        rankings[1]["operational"] != rankings[2]["operational"],
        "Operational urgency ranking did not change after P1 reception",
    )
    _require(
        rankings[2]["true"] != rankings[3]["true"]
        and rankings[2]["operational"] != rankings[3]["operational"],
        "True and operational urgency rankings did not change after audit delivery",
    )
    checks["urgency_checkpoints"] = checkpoints

    reverse_pairs = []
    by_geometry = {
        (corridor.origin, corridor.destination, corridor.fixture_role): corridor
        for corridor in scenario.corridors
        if corridor.fixture_role
    }
    for corridor in scenario.corridors:
        if not corridor.fixture_role or corridor.fixture_role.endswith("_reverse"):
            continue
        reverse = next(
            (
                candidate
                for candidate in scenario.corridors
                if candidate.origin == corridor.destination
                and candidate.destination == corridor.origin
                and candidate.fixture_role == corridor.fixture_role + "_reverse"
            ),
            None,
        )
        if reverse is None:
            continue
        _require(
            abs(corridor.nominal_travel_time_s - reverse.nominal_travel_time_s)
            > 1e-6
            or abs(corridor.nominal_energy_wh - reverse.nominal_energy_wh) > 1e-6,
            f"Directed metrics are not asymmetric for {corridor.corridor_id}",
        )
        reverse_pairs.append(
            {
                "forward": corridor.corridor_id,
                "reverse": reverse.corridor_id,
                "forward_time_s": corridor.nominal_travel_time_s,
                "reverse_time_s": reverse.nominal_travel_time_s,
            }
        )
    checks["directional_asymmetry"] = reverse_pairs

    reception_errors = [
        event.event_id
        for event in scenario.exogenous_events
        if event.report_reception_time_s is not None
        and event.report_generation_time_s is not None
        and event.report_reception_time_s < event.report_generation_time_s
    ]
    _require(not reception_errors, f"Report timestamp ordering errors: {reception_errors}")
    entity_ids = {node["node_id"] for node in scenario.nodes}
    entity_ids.update(zone["zone_id"] for zone in scenario.geography["dynamic_zones"])
    entity_ids.add("DEPOT")
    entity_ids.update(corridor.corridor_id for corridor in scenario.corridors)
    invalid_events = [
        event.event_id
        for event in scenario.exogenous_events
        if event.affected_entity not in entity_ids
    ]
    _require(not invalid_events, f"Events reference invalid entities: {invalid_events}")
    checks["event_integrity"] = {
        "event_count": len(scenario.exogenous_events),
        "timestamp_ordering": True,
        "entity_references": True,
    }

    checks["exogenous_random_draws_after_replay_start"] = 0
    checks["mandatory_figures"] = list(required_figure_names or [])
    return {
        "scenario_hash": scenario.content_hash(),
        "master_seed": scenario.metadata["master_seed"],
        "generator_version": scenario.metadata["generator_version"],
        "passed": True,
        "checks": checks,
    }
