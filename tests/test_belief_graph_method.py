"""Operational belief-graph truth boundaries, dynamics, and equivariance."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch

from env.audit_model import AuditScenario
from env.audit_replay import ScenarioReplay, load_audit_actions, urgency_score
from env.events import Event, EventType
from env.params import COMMODITY_NAMES, EnvParams
from env.scenario_generator import generate_scenario
from env.uav_env import UAMTVRPIUEnv
from methods.belief_graph import (
    EDGE_FEATURE_NAMES,
    NODE_FEATURE_NAMES,
    NODE_TYPE_AFFECTED,
    OperationalBeliefGraphBuilder,
)
from methods.graph_networks import BeliefGraphEncoder, TorchBeliefGraphBatch


ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "outputs" / "seed_18427" / "seed_18427.json"
ACTIONS = ROOT / "outputs" / "seed_18427" / "audit_actions.json"


@pytest.fixture(scope="module")
def audit_graph_fixture():
    scenario = AuditScenario.from_json(SCENARIO)
    replay = ScenarioReplay(scenario, load_audit_actions(ACTIONS))
    builder = OperationalBeliefGraphBuilder(max_known_nodes=len(scenario.nodes))
    return scenario, replay, builder


def _small_env(seed=731):
    params = EnvParams()
    params.mission.T = 0.75
    params.hybrid.alns_iterations = 2
    env = UAMTVRPIUEnv(params)
    env.reset(scenario=generate_scenario(seed, params))
    return env


def test_active_graph_excludes_true_demand_vulnerability_and_hidden_p3():
    env = _small_env()
    node = min(env.belief.known)
    before = env.get_operational_belief_graph()
    masks_before = {
        u: env._action_mask(u).copy() for u in range(env.M)
    }
    env.nodes[node].nu = 999.0
    delta = np.array([0.0, 0.0, 1234.0, 0.0])
    env._apply_event(
        Event(env.t, EventType.P3_MUTATION, {"node": node, "delta": delta})
    )
    after = env.get_operational_belief_graph()
    np.testing.assert_array_equal(before.node_features, after.node_features)
    np.testing.assert_array_equal(before.edge_features, after.edge_features)
    np.testing.assert_array_equal(before.plan_features, after.plan_features)
    for u in range(env.M):
        np.testing.assert_array_equal(masks_before[u], env._action_mask(u))


def test_unknown_membership_stable_slots_and_padding():
    env = _small_env(732)
    unknown = next(i for i in range(env.N) if not env.belief.is_known(i))
    before = env.get_operational_belief_graph()
    expected_slot = env.M + 1 + unknown
    assert f"N{unknown}" not in before.entity_id_to_slot
    assert not before.node_mask[expected_slot]
    node = env.scenario.nodes[unknown]
    env.belief.reveal(
        unknown,
        np.asarray(node.mu0),
        np.asarray(node.sigma0),
        node.gamma0,
        node.onset_time,
        env.t,
        node.nu if node.nu_reported is None else node.nu_reported,
    )
    after = env.get_operational_belief_graph()
    assert after.entity_id_to_slot[f"N{unknown}"] == expected_slot
    assert after.node_mask[expected_slot]
    insert = env.encode_insert(unknown)
    assert after.action_to_destination[0, insert] == expected_slot
    assert after.action_to_edge[0, insert] >= 0
    for entity, slot in before.entity_id_to_slot.items():
        assert after.entity_id_to_slot[entity] == slot
    assert after.edge_mask.sum() <= after.max_edges


def test_information_age_uses_report_generation_time():
    env = _small_env(733)
    node = min(env.belief.known)
    env.t = 0.6
    env.belief.entries[node].t_last_report = 0.55
    env.belief.entries[node].t_last_generation = 0.2
    graph = env.get_operational_belief_graph()
    slot = graph.entity_id_to_slot[f"N{node}"]
    value = graph.node_features[
        slot, NODE_FEATURE_NAMES.index("information_age")
    ]
    assert value == pytest.approx((0.6 - 0.2) / env.T)
    assert value != pytest.approx((0.6 - 0.55) / env.T)


def test_seed_hidden_state_and_dynamic_membership(audit_graph_fixture):
    scenario, replay, builder = audit_graph_fixture
    physical_37, controller_37 = replay.snapshot(3.7 * 3600)
    graph_37 = builder.build_from_controller(scenario, controller_37)
    water = COMMODITY_NAMES.index("water")
    slot = graph_37.entity_id_to_slot["N3"]
    assert sum(
        row["quantity"]
        for row in physical_37.node_cohorts["N3"]
        if row["commodity_index"] == water
    ) == 16.0
    assert graph_37.node_features[
        slot, NODE_FEATURE_NAMES.index("commodity_2")
    ] == pytest.approx(0.6)

    _, controller_42 = replay.snapshot(4.2 * 3600)
    graph_42 = builder.build_from_controller(scenario, controller_42)
    assert "N6" not in graph_42.entity_id_to_slot
    _, controller_50 = replay.snapshot(5.0 * 3600)
    graph_50 = builder.build_from_controller(scenario, controller_50)
    assert "N6" in graph_50.entity_id_to_slot
    expected_slot = scenario.fleet["uav_count"] + 1 + 5
    assert graph_50.entity_id_to_slot["N6"] == expected_slot


def test_lost_report_does_not_update_features(audit_graph_fixture):
    scenario, replay, builder = audit_graph_fixture
    _, before_state = replay.snapshot(7919.0)
    _, after_state = replay.snapshot(12000.0)
    before = builder.build_from_controller(scenario, before_state)
    after = builder.build_from_controller(scenario, after_state)
    slot_before = before.entity_id_to_slot["N4"]
    slot_after = after.entity_id_to_slot["N4"]
    fixed = [
        NODE_FEATURE_NAMES.index(name)
        for name in (
            "commodity_0", "commodity_1", "commodity_2", "commodity_3",
            "reported_vulnerability", "report_confidence",
        )
    ]
    np.testing.assert_array_equal(
        before.node_features[slot_before, fixed],
        after.node_features[slot_after, fixed],
    )
    assert "E_N4_LOST_P1" not in after_state.received_event_ids


def test_cohort_urgency_and_oldest_age_match_existing_model(audit_graph_fixture):
    scenario, replay, builder = audit_graph_fixture
    time_s = 3.7 * 3600
    _, controller = replay.snapshot(time_s)
    graph = builder.build_from_controller(scenario, controller)
    slot = graph.entity_id_to_slot["N3"]
    expected_urgency = urgency_score(
        controller.operational_cohorts["N3"],
        controller.reported_vulnerability["N3"],
        time_s,
        scenario.config["commodities"],
    )
    encoded = graph.node_features[
        slot, NODE_FEATURE_NAMES.index("operational_urgency")
    ]
    assert np.expm1(encoded * 8.0) == pytest.approx(
        expected_urgency, rel=2e-6
    )
    oldest = max(
        time_s - row["onset_time_s"]
        for row in controller.operational_cohorts["N3"]
    )
    horizon = max(
        8.0 * 3600.0,
        max(zone["active_to_s"] for zone in scenario.geography["dynamic_zones"]),
    )
    assert graph.node_features[
        slot, NODE_FEATURE_NAMES.index("oldest_cohort_age")
    ] == pytest.approx(oldest / horizon)


def test_directed_corridors_notice_mask_and_alternative(audit_graph_fixture):
    scenario, replay, builder = audit_graph_fixture
    _, controller_42 = replay.snapshot(4.2 * 3600)
    graph_42 = builder.build_from_controller(scenario, controller_42)
    named = "corridor_depot_n3_south_outbound"
    reverse = "corridor_depot_n3_south_reverse"
    alternative = "corridor_depot_n3_north_alternative"
    assert graph_42.operational_corridor_mask[named]
    forward_edge = graph_42.corridor_id_to_edge[named]
    reverse_edge = graph_42.corridor_id_to_edge[reverse]
    time_index = EDGE_FEATURE_NAMES.index("believed_travel_time")
    energy_index = EDGE_FEATURE_NAMES.index("believed_energy")
    assert graph_42.edge_features[forward_edge, time_index] != pytest.approx(
        graph_42.edge_features[reverse_edge, time_index]
    )
    assert graph_42.edge_features[forward_edge, energy_index] != pytest.approx(
        graph_42.edge_features[reverse_edge, energy_index]
    )

    _, controller_48 = replay.snapshot(4.8 * 3600)
    graph_48 = builder.build_from_controller(scenario, controller_48)
    assert not graph_48.operational_corridor_mask[named]
    assert graph_48.operational_corridor_mask[alternative]
    closed_index = EDGE_FEATURE_NAMES.index("condition_closed")
    assert graph_48.edge_features[
        graph_48.corridor_id_to_edge[named], closed_index
    ] == 1.0


def _permuted_affected_graph(graph):
    changed = graph.clone()
    affected = np.flatnonzero(
        (changed.node_type_ids == NODE_TYPE_AFFECTED) & changed.node_mask
    )
    permutation = np.arange(changed.max_nodes)
    permutation[affected] = affected[::-1]
    inverse = np.argsort(permutation)
    changed.node_features = changed.node_features[permutation]
    changed.node_type_ids = changed.node_type_ids[permutation]
    changed.node_mask = changed.node_mask[permutation]
    changed.edge_index = inverse[changed.edge_index]
    changed.entity_id_to_slot = {
        entity: int(inverse[slot])
        for entity, slot in changed.entity_id_to_slot.items()
    }
    changed.slot_to_entity_id = {
        slot: entity for entity, slot in changed.entity_id_to_slot.items()
    }
    changed.uav_to_node = inverse[changed.uav_to_node]
    return changed


def test_encoder_permutation_equivariance(audit_graph_fixture):
    scenario, replay, builder = audit_graph_fixture
    _, controller = replay.snapshot(5.1 * 3600)
    graph = builder.build_from_controller(scenario, controller)
    permuted = _permuted_affected_graph(graph)
    torch.manual_seed(17)
    encoder = BeliefGraphEncoder(
        len(NODE_FEATURE_NAMES),
        len(EDGE_FEATURE_NAMES),
        hidden_dim=32,
        num_layers=2,
        num_heads=4,
        dropout=0.0,
    ).eval()
    with torch.no_grad():
        nodes_a, pooled_a = encoder(
            TorchBeliefGraphBatch.collate([graph], torch.device("cpu"))
        )
        nodes_b, pooled_b = encoder(
            TorchBeliefGraphBatch.collate([permuted], torch.device("cpu"))
        )
    torch.testing.assert_close(pooled_a, pooled_b, rtol=1e-5, atol=1e-6)
    for entity, slot_a in graph.entity_id_to_slot.items():
        slot_b = permuted.entity_id_to_slot[entity]
        torch.testing.assert_close(
            nodes_a[0, slot_a], nodes_b[0, slot_b], rtol=1e-5, atol=1e-6
        )
