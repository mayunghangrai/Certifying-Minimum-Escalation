"""Acceptance tests for the deterministic seed-18427 audit scenario."""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import numpy as np
import pytest

from env.audit_artifacts import MANDATORY_FIGURES, write_data_artifacts
from env.audit_generator import generate_audit_scenario
from env.audit_geometry import (
    directed_corridor_metrics,
    normalized_risk_layers,
    static_feasible,
)
from env.audit_model import CorridorCondition
from env.audit_replay import ScenarioReplay, load_audit_actions, reduce_fofs
from env.audit_validation import validate_scenario
from env.audit_visualization import generate_audit_figures
from env.params import COMMODITY_NAMES, EnvParams
from env.scenario_generator import generate_scenario
from env.uav_env import UAMTVRPIUEnv


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "prototype_seed.yaml"
ACTIONS = ROOT / "configs" / "audit_policy_seed_18427.yaml"


@pytest.fixture(scope="module")
def audit_fixture():
    scenario = generate_audit_scenario(18427, config_path=CONFIG)
    actions = load_audit_actions(ACTIONS)
    replay = ScenarioReplay(scenario, actions)
    return scenario, actions, replay


def _total(cohorts, node_id, commodity_index):
    return sum(
        row["quantity"]
        for row in cohorts.get(node_id, [])
        if row["commodity_index"] == commodity_index
    )


def test_same_seed_produces_identical_scenario(audit_fixture):
    scenario, _, _ = audit_fixture
    repeated = generate_audit_scenario(18427, config_path=CONFIG)
    assert repeated.canonical_bytes() == scenario.canonical_bytes()
    assert repeated.content_hash() == scenario.content_hash()


def test_different_seed_changes_geography(audit_fixture):
    scenario, _, _ = audit_fixture
    other = generate_audit_scenario(18428, config_path=CONFIG)
    assert other.geography["terrain_spec"]["detail_phase"] != (
        scenario.geography["terrain_spec"]["detail_phase"]
    )
    assert other.content_hash() != scenario.content_hash()


def test_canonical_commodity_mapping_and_mask(audit_fixture):
    scenario, _, _ = audit_fixture
    assert tuple(scenario.metadata["commodity_names"]) == COMMODITY_NAMES
    assert scenario.metadata["active_commodity_mask"] == [1, 0, 1, 0]
    inactive = {1, 3}
    rows = scenario.true_initial_cohorts + scenario.operational_initial_cohorts
    assert all(row["commodity_index"] not in inactive for row in rows)


def test_nominal_corridor_graph_is_strongly_directed_connected(audit_fixture):
    scenario, _, _ = audit_fixture
    graph = nx.DiGraph(
        (corridor.origin, corridor.destination)
        for corridor in scenario.corridors
        if corridor.static_feasible
    )
    assert nx.is_strongly_connected(graph)


def test_all_corridors_are_statically_feasible(audit_fixture):
    scenario, _, _ = audit_fixture
    clearance = scenario.geography["minimum_horizontal_clearance_m"]
    assert all(
        corridor.static_feasible
        and static_feasible(corridor.waypoints_m, scenario.geography, clearance)
        for corridor in scenario.corridors
    )


def test_t4_2_named_corridor_truth_information_mismatch(audit_fixture):
    _, _, replay = audit_fixture
    physical, controller = replay.snapshot(4.2 * 3600.0)
    assert (
        physical.corridor_conditions["corridor_depot_n3_south_outbound"]
        == "CLOSED"
    )
    assert (
        controller.believed_corridor_conditions[
            "corridor_depot_n3_south_outbound"
        ]
        == "NORMAL"
    )
    assert (
        physical.corridor_conditions["corridor_n1_n5_hazard_outbound"]
        == "DEGRADED"
    )
    assert (
        controller.believed_corridor_conditions[
            "corridor_n1_n5_hazard_outbound"
        ]
        == "NORMAL"
    )


def test_t4_2_each_affected_od_has_a_usable_alternative(audit_fixture):
    scenario, actions, _ = audit_fixture
    report = validate_scenario(scenario, actions)
    alternatives = report["checks"]["usable_alternatives_at_t4_2"]
    assert "corridor_depot_n3_north_alternative" in alternatives["DEPOT->N3"]
    assert "corridor_n1_n5_north_alternative" in alternatives["N1->N5"]


def test_t4_2_hidden_information_conditions(audit_fixture):
    _, _, replay = audit_fixture
    physical, controller = replay.snapshot(4.2 * 3600.0)
    assert "N6" not in controller.known_nodes
    assert "TNFZ1" in physical.active_temporary_nfz_ids
    assert "TNFZ1" not in controller.received_zone_notices
    assert "HAZ1" in physical.active_hazard_ids
    assert "HAZ1" not in controller.received_zone_notices
    assert _total(physical.node_cohorts, "N3", 2) == 16.0
    assert _total(controller.operational_cohorts, "N3", 2) == 6.0


def test_hidden_p3_does_not_immediately_change_controller(audit_fixture):
    _, _, replay = audit_fixture
    physical_before, controller_before = replay.snapshot(12959.0)
    physical_after, controller_after = replay.snapshot(12961.0)
    assert _total(physical_before.node_cohorts, "N3", 2) == 6.0
    assert _total(physical_after.node_cohorts, "N3", 2) == 16.0
    assert _total(controller_before.operational_cohorts, "N3", 2) == 6.0
    assert _total(controller_after.operational_cohorts, "N3", 2) == 6.0


def test_lost_report_never_changes_controller(audit_fixture):
    _, _, replay = audit_fixture
    _, before = replay.snapshot(7919.0)
    _, after = replay.snapshot(12000.0)
    assert _total(before.operational_cohorts, "N4", 2) == 9.0
    assert _total(after.operational_cohorts, "N4", 2) == 9.0
    assert "E_N4_LOST_P1" not in after.received_event_ids


def test_p2_reveals_unknown_node_at_exact_reception(audit_fixture):
    _, _, replay = audit_fixture
    _, before = replay.snapshot(17999.0)
    _, at_reception = replay.snapshot(18000.0)
    assert "N6" not in before.known_nodes
    assert "N6" in at_reception.known_nodes
    assert "E_N6_P2" in at_reception.received_event_ids


def test_p4_potential_is_activated_only_by_audit_service(audit_fixture):
    scenario, _, _ = audit_fixture
    no_action_replay = ScenarioReplay(scenario, {"scenario_seed": 18427, "actions": []})
    _, without_service = no_action_replay.snapshot(24000.0)
    _, before_reception = audit_fixture[2].snapshot(22751.0)
    _, at_reception = audit_fixture[2].snapshot(22752.0)
    assert "P4_N3_1" not in without_service.received_event_ids
    assert "P4_N3_1" not in before_reception.received_event_ids
    assert "P4_N3_1" in at_reception.received_event_ids


def test_fofs_delivery_reduces_oldest_onset_first():
    grouped = {
        "N": [
            {
                "commodity_index": 0,
                "cohort_id": "old",
                "onset_time_s": 10.0,
                "quantity": 3.0,
            },
            {
                "commodity_index": 0,
                "cohort_id": "new",
                "onset_time_s": 20.0,
                "quantity": 4.0,
            },
        ]
    }
    accepted = reduce_fofs(grouped, "N", [5.0, 0.0, 0.0, 0.0])
    assert accepted == [5.0, 0.0, 0.0, 0.0]
    assert [(row["cohort_id"], row["quantity"]) for row in grouped["N"]] == [
        ("new", 2.0)
    ]


def test_degraded_metrics_exceed_nominal_and_closed_is_infeasible(audit_fixture):
    scenario, _, _ = audit_fixture
    corridor = next(
        item
        for item in scenario.corridors
        if item.corridor_id == "corridor_n1_n5_hazard_outbound"
    )
    normal = directed_corridor_metrics(
        corridor.waypoints_m,
        scenario.geography,
        scenario.fleet,
        payload_kg=1.0,
        condition=CorridorCondition.NORMAL,
    )
    degraded = directed_corridor_metrics(
        corridor.waypoints_m,
        scenario.geography,
        scenario.fleet,
        payload_kg=1.0,
        condition=CorridorCondition.DEGRADED,
    )
    closed = directed_corridor_metrics(
        corridor.waypoints_m,
        scenario.geography,
        scenario.fleet,
        payload_kg=1.0,
        condition=CorridorCondition.CLOSED,
    )
    assert degraded["travel_time_s"] > normal["travel_time_s"]
    assert degraded["energy_wh"] > normal["energy_wh"]
    assert np.isinf(closed["travel_time_s"])
    assert np.isinf(closed["energy_wh"])


def test_direction_dependent_time_and_energy(audit_fixture):
    scenario, _, _ = audit_fixture
    forward = next(
        item
        for item in scenario.corridors
        if item.corridor_id == "corridor_depot_n3_south_outbound"
    )
    reverse = next(
        item
        for item in scenario.corridors
        if item.fixture_role == "temporary_nfz_affected_reverse"
    )
    assert forward.nominal_travel_time_s != reverse.nominal_travel_time_s
    assert forward.nominal_energy_wh != reverse.nominal_energy_wh


def test_fixed_normalization_references_are_not_seed_extrema(audit_fixture):
    scenario, _, _ = audit_fixture
    expected = scenario.config["risk"]["reference_ranges"]
    assert scenario.geography["risk_reference_ranges"] == expected
    layers = normalized_risk_layers(
        np.array([0.0, 2500.0, 5000.0]),
        np.array([0.0, 2500.0, 5000.0]),
        scenario.geography,
        hazard_intensity=1.0,
    )
    assert all(np.all((values >= 0.0) & (values <= 1.0)) for values in layers.values())


def test_individual_risk_layers_are_exported(audit_fixture, tmp_path):
    scenario, actions, _ = audit_fixture
    write_data_artifacts(scenario, tmp_path, actions)
    expected = {
        "population_risk.npy",
        "infrastructure_risk.npy",
        "terrain_difficulty.npy",
        "base_composite_risk.npy",
    }
    arrays = {
        name: np.load(tmp_path / name, allow_pickle=False) for name in expected
    }
    assert all(array.shape == (41, 41) for array in arrays.values())
    assert all(array.dtype == np.dtype("<f4") for array in arrays.values())
    assert all(np.isfinite(array).all() for array in arrays.values())
    assert all(np.all((array >= 0.0) & (array <= 1.0)) for array in arrays.values())
    metadata = json.loads(
        (tmp_path / "risk_layers_metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["grid"]["shape_yx"] == [41, 41]
    assert metadata["dynamic_hazard_included"] is False
    assert set(metadata["arrays"]) == expected


def test_vulnerability_values_preserve_repository_domain(audit_fixture):
    scenario, _, _ = audit_fixture
    lo, hi = EnvParams().map.nu_range
    values = [node["true_vulnerability"] for node in scenario.nodes]
    assert min(values) >= lo
    assert max(values) <= hi
    assert max(values) > 1.0


def test_scenario_json_excludes_policy_actions_and_decisions(audit_fixture):
    scenario, _, _ = audit_fixture
    payload = scenario.to_dict()
    encoded = json.dumps(payload, sort_keys=True)
    assert "audit_actions" not in payload
    assert '"actions"' not in encoded
    assert "audit_delivery_n3_t6" not in encoded


def test_events_reference_valid_entities_and_have_ordered_reports(audit_fixture):
    scenario, actions, _ = audit_fixture
    report = validate_scenario(scenario, actions)
    assert report["checks"]["event_integrity"] == {
        "event_count": len(scenario.exogenous_events),
        "timestamp_ordering": True,
        "entity_references": True,
    }


def test_true_and_operational_cohort_totals_match_source_demands(audit_fixture):
    scenario, _, _ = audit_fixture
    node_config = {row["node_id"]: row for row in scenario.config["nodes"]}
    for node_id, config in node_config.items():
        true = [
            _total(
                {
                    node_id: [
                        row
                        for row in scenario.true_initial_cohorts
                        if row["node_id"] == node_id
                    ]
                },
                node_id,
                index,
            )
            for index in range(4)
        ]
        assert true == config["true_demand"]
        if config["initially_known"]:
            operational = [
                _total(
                    {
                        node_id: [
                            row
                            for row in scenario.operational_initial_cohorts
                            if row["node_id"] == node_id
                        ]
                    },
                    node_id,
                    index,
                )
                for index in range(4)
            ]
            assert operational == config["reported_demand"]


def test_urgency_leaders_and_ranking_changes(audit_fixture):
    scenario, actions, _ = audit_fixture
    report = validate_scenario(scenario, actions)
    checkpoints = report["checks"]["urgency_checkpoints"]
    assert [
        (row["true_leader"], row["operational_leader"]) for row in checkpoints
    ] == [("N4", "N4"), ("N3", "N4"), ("N3", "N3"), ("N4", "N4")]


def test_controller_export_contains_no_latent_truth(audit_fixture):
    _, _, replay = audit_fixture
    physical, controller = replay.snapshot(4.2 * 3600.0)
    export = controller.to_dict()
    assert "true_vulnerability" not in export
    assert "active_hazard_ids" not in export
    assert "active_temporary_nfz_ids" not in export
    assert physical.true_vulnerability != controller.reported_vulnerability


def test_replay_samples_no_exogenous_randomness(audit_fixture, monkeypatch):
    scenario, actions, _ = audit_fixture

    def forbidden(*args, **kwargs):
        raise AssertionError("Randomness was sampled after replay start")

    monkeypatch.setattr(np.random, "default_rng", forbidden)
    replay = ScenarioReplay(scenario, actions)
    replay.snapshot(4.2 * 3600.0)
    replay.snapshot(6.5 * 3600.0)


def test_actor_observation_dimensions_order_and_truth_exclusion_unchanged():
    params = EnvParams()
    env = UAMTVRPIUEnv(params)
    env.reset(scenario=generate_scenario(42, params))
    assert env.obs_dims == {
        "own": 17,
        "node": 20,
        "fleet": 11,
        "event": 15,
        "n_nodes": 20,
        "n_others": 2,
        "actor": 454,
        "critic_node": 26,
        "critic": 586,
    }
    node_id = min(env.belief.known)
    before = env._node_feats(0, node_id)
    assert before.shape == (20,)
    assert before[13] == pytest.approx(env.belief.vulnerability(node_id) / 3.0)
    env.nodes[node_id].nu += 100.0
    after = env._node_feats(0, node_id)
    np.testing.assert_array_equal(after, before)


def test_all_mandatory_visualizations_are_generated(audit_fixture, tmp_path):
    scenario, actions, replay = audit_fixture
    paths = generate_audit_figures(scenario, replay, tmp_path, 4.2 * 3600.0)
    assert [path.name for path in paths] == MANDATORY_FIGURES
    assert all(path.is_file() and path.stat().st_size > 10_000 for path in paths)
