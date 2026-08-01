"""ALNS guidance algebra, masking, rollout gradients, and compatibility."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
import torch

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from agents.mappo_agent import MAPPOAgent
from env.params import EnvParams
from env.scenario_generator import generate_scenario
from env.uav_env import UAMTVRPIUEnv
from methods.belief_graph import (
    EDGE_FEATURE_NAMES,
    NODE_FEATURE_NAMES,
    NODE_TYPE_AFFECTED,
)
from methods.graph_networks import GraphMAPPOActor, TorchBeliefGraphBatch
from scripts.train_mappo import load_agent_config


def _fixture(seed=810):
    params = EnvParams()
    params.mission.T = 0.6
    params.hybrid.alns_iterations = 2
    env = UAMTVRPIUEnv(params)
    obs, info = env.reset(scenario=generate_scenario(seed, params))
    graph = env.get_operational_belief_graph()
    return env, obs, info, graph


def _actor(env, mode, fixed_gate=0.5, beta=2.0):
    dims = env.obs_dims
    return GraphMAPPOActor(
        own_dim=dims["own"],
        flat_node_dim=dims["node"],
        flat_node_count=dims["n_nodes"],
        rest_dim=dims["n_others"] * dims["fleet"] + dims["event"],
        node_dim=len(NODE_FEATURE_NAMES),
        edge_dim=len(EDGE_FEATURE_NAMES),
        action_dim=env.n_actions,
        hidden_dim=32,
        num_layers=2,
        num_heads=4,
        guidance_mode=mode,
        fixed_gate=fixed_gate,
        beta=beta,
    ).eval()


def _forward_inputs(env, obs, info, graph):
    u = sorted(obs)[0]
    return (
        torch.as_tensor(obs[u][None], dtype=torch.float32),
        TorchBeliefGraphBatch.collate([graph], torch.device("cpu")),
        torch.tensor([u]),
        torch.as_tensor(info["masks"][u][None], dtype=torch.float32),
        torch.as_tensor(graph.plan_features[u][None], dtype=torch.float32),
        torch.as_tensor(graph.alns_prior[u][None], dtype=torch.float32),
    )


def test_no_guidance_and_zero_prior_preserve_mappo_logits():
    env, obs, info, graph = _fixture()
    inputs = _forward_inputs(env, obs, info, graph)
    torch.manual_seed(4)
    actor_none = _actor(env, "none")
    with torch.no_grad():
        _, logits_none, gate_none, base_none, _ = actor_none(*inputs)
    valid = inputs[3].bool()
    torch.testing.assert_close(logits_none[valid], base_none[valid])
    assert torch.count_nonzero(gate_none) == 0

    torch.manual_seed(4)
    actor_fixed = _actor(env, "fixed")
    zero_prior_inputs = (*inputs[:-1], torch.zeros_like(inputs[-1]))
    with torch.no_grad():
        _, logits_zero, _, base_zero, _ = actor_fixed(*zero_prior_inputs)
    torch.testing.assert_close(logits_zero[valid], base_zero[valid])


@pytest.mark.parametrize("gate", [0.0, 0.5, 1.0])
def test_fixed_gate_exact_prior_contribution(gate):
    env, obs, info, graph = _fixture(811)
    inputs = list(_forward_inputs(env, obs, info, graph))
    inputs[-1] = torch.zeros_like(inputs[-1])
    inputs[-1][:, env.A_FOLLOW] = 1.0
    inputs[3][:, env.A_FOLLOW] = 1.0
    beta = 1.7
    torch.manual_seed(12)
    actor = _actor(env, "fixed", fixed_gate=gate, beta=beta)
    with torch.no_grad():
        _, logits, gates, base, _ = actor(*inputs)
    assert float(gates[0, 0]) == pytest.approx(gate)
    assert float(logits[0, env.A_FOLLOW] - base[0, env.A_FOLLOW]) == pytest.approx(
        beta * gate
    )


def test_action_mask_overrides_positive_guidance():
    env, obs, info, graph = _fixture(812)
    inputs = list(_forward_inputs(env, obs, info, graph))
    blocked = env.A_FOLLOW
    inputs[3][:, blocked] = 0.0
    inputs[-1] = torch.zeros_like(inputs[-1])
    inputs[-1][:, blocked] = 1e6
    actor = _actor(env, "fixed", fixed_gate=1.0, beta=100.0)
    with torch.no_grad():
        probabilities, logits, _, _, _ = actor(*inputs)
    assert logits[0, blocked] == -1e8
    assert probabilities[0, blocked] == 0.0


def test_adaptive_gate_range_and_gradient():
    env, obs, info, graph = _fixture(813)
    inputs = list(_forward_inputs(env, obs, info, graph))
    inputs[3][:, env.A_FOLLOW] = 1.0
    inputs[3][:, env.A_RETURN] = 1.0
    inputs[-1] = torch.zeros_like(inputs[-1])
    inputs[-1][:, env.A_FOLLOW] = 1.0
    actor = _actor(env, "adaptive").train()
    probabilities, _, gate, _, _ = actor(*inputs)
    assert torch.all((gate >= 0.0) & (gate <= 1.0))
    loss = -torch.log(probabilities[0, env.A_FOLLOW].clamp(min=1e-8))
    loss.backward()
    gradient = sum(
        float(parameter.grad.abs().sum())
        for parameter in actor.guidance_gate.parameters()
        if parameter.grad is not None
    )
    graph_gradient = sum(
        float(parameter.grad.abs().sum())
        for parameter in actor.graph_encoder.parameters()
        if parameter.grad is not None
    )
    assert gradient > 0.0
    assert graph_gradient > 0.0


def test_actor_logits_are_invariant_to_affected_node_permutation():
    env, obs, info, graph = _fixture(817)
    permuted = graph.clone()
    affected = np.flatnonzero(
        (permuted.node_type_ids == NODE_TYPE_AFFECTED) & permuted.node_mask
    )
    order = np.arange(permuted.max_nodes)
    order[affected] = affected[::-1]
    inverse = np.argsort(order)
    permuted.node_features = permuted.node_features[order]
    permuted.node_type_ids = permuted.node_type_ids[order]
    permuted.node_mask = permuted.node_mask[order]
    permuted.edge_index = inverse[permuted.edge_index]
    permuted.uav_to_node = inverse[permuted.uav_to_node]
    permuted.entity_id_to_slot = {
        entity: int(inverse[slot])
        for entity, slot in permuted.entity_id_to_slot.items()
    }
    torch.manual_seed(91)
    actor = _actor(env, "adaptive").eval()
    first = _forward_inputs(env, obs, info, graph)
    second = _forward_inputs(env, obs, info, permuted)
    with torch.no_grad():
        output_a = actor(*first)
        output_b = actor(*second)
    torch.testing.assert_close(output_a[1], output_b[1], rtol=1e-5, atol=1e-6)


def test_graph_rollout_update_and_checkpoint_roundtrip(tmp_path):
    env, obs, info, graph = _fixture(814)
    config = {
        "device": "cpu",
        "method_mode": "graph_mappo_adaptive_alns",
        "hidden_dim": 64,
        "encoder_dim": 32,
        "graph_hidden_dim": 32,
        "graph_num_heads": 4,
        "update_epochs": 1,
    }
    torch.manual_seed(22)
    agent = MAPPOAgent(env.M, env.obs_dims, env.n_actions, config)
    gstate = env.get_global_state()
    actions, log_probs, value = agent.select_actions(
        obs, info["masks"], gstate, deterministic=False, graph=graph
    )
    agent.begin_episode()
    agent.record_decisions(
        env.t, obs, info["masks"], gstate,
        actions, log_probs, value, graph=graph,
    )
    assert all(pending.gobs.size == 0 for pending in agent._pending.values())
    forbidden = {
        "true_demand", "true_vulnerability", "physical_corridor_conditions",
        "unreceived_events", "active_hazard_ids",
    }
    assert not forbidden.intersection(graph.metadata)
    start = env.t
    _, reward, _, _ = env.step(actions)
    agent.record_reward(reward, start)
    agent.end_episode(env.t)
    actor_loss, critic_loss = agent.update()
    assert np.isfinite(actor_loss)
    assert np.isfinite(critic_loss)
    assert agent.last_gradient_norms["graph_encoder"] > 0.0
    assert agent.last_gradient_norms["actor_graph_projection"] > 0.0
    assert agent.last_gradient_norms["critic_graph_projection"] > 0.0
    assert agent.last_gradient_norms["guidance_gate"] > 0.0

    checkpoint = tmp_path / "graph_agent.pt"
    agent.set_eval()
    agent.save(checkpoint)
    try:
        saved = torch.load(checkpoint, map_location="cpu", weights_only=False)
    except TypeError:
        saved = torch.load(checkpoint, map_location="cpu")
    assert saved["normalization"]["demand_units"] == 10.0
    assert saved["normalization"]["plan_features"].endswith("[0,1]")
    expected = agent.select_actions(
        obs, info["masks"], gstate, deterministic=True, graph=graph
    )
    restored = MAPPOAgent(env.M, env.obs_dims, env.n_actions, config)
    restored.load(checkpoint)
    restored.set_eval()
    actual = restored.select_actions(
        obs, info["masks"], gstate, deterministic=True, graph=graph
    )
    assert actual[0] == expected[0]
    assert actual[2] == pytest.approx(expected[2], rel=1e-7, abs=1e-7)
    for u in expected[1]:
        assert actual[1][u] == pytest.approx(expected[1][u], abs=1e-7)


def test_vanilla_default_and_explicit_mode_are_identical():
    env, obs, info, _ = _fixture(815)
    common = {
        "device": "cpu",
        "hidden_dim": 64,
        "encoder_dim": 32,
        "num_heads": 4,
        "num_layers": 2,
    }
    torch.manual_seed(31)
    implicit = MAPPOAgent(env.M, env.obs_dims, env.n_actions, common)
    torch.manual_seed(31)
    explicit = MAPPOAgent(
        env.M,
        env.obs_dims,
        env.n_actions,
        {**common, "method_mode": "vanilla_mappo"},
    )
    implicit.set_eval()
    explicit.set_eval()
    first = implicit.select_actions(
        obs, info["masks"], env.get_global_state(), deterministic=True
    )
    second = explicit.select_actions(
        obs, info["masks"], env.get_global_state(), deterministic=True
    )
    assert first[0] == second[0]
    assert first[2] == pytest.approx(second[2], abs=1e-8)
    assert first[1] == pytest.approx(second[1], abs=1e-8)


def test_checkpoint_mode_mismatch_fails_loudly(tmp_path):
    env, _, _, _ = _fixture(816)
    vanilla = MAPPOAgent(
        env.M, env.obs_dims, env.n_actions,
        {"device": "cpu", "method_mode": "vanilla_mappo"},
    )
    path = tmp_path / "vanilla.pt"
    vanilla.save(path)
    graph = MAPPOAgent(
        env.M, env.obs_dims, env.n_actions,
        {"device": "cpu", "method_mode": "graph_mappo"},
    )
    with pytest.raises(ValueError, match="does not match"):
        graph.load(path)


def test_guided_checkpoint_beta_mismatch_fails_loudly(tmp_path):
    env, _, _, _ = _fixture(817)
    first = MAPPOAgent(
        env.M,
        env.obs_dims,
        env.n_actions,
        {
            "device": "cpu",
            "method_mode": "graph_mappo_adaptive_alns",
            "guidance_beta": 1.0,
        },
    )
    path = tmp_path / "guided.pt"
    first.save(path)
    different_beta = MAPPOAgent(
        env.M,
        env.obs_dims,
        env.n_actions,
        {
            "device": "cpu",
            "method_mode": "graph_mappo_adaptive_alns",
            "guidance_beta": 5.591,
        },
    )
    with pytest.raises(ValueError, match="guidance beta"):
        different_beta.load(path)


def test_documented_method_config_is_executable():
    config_path = (
        Path(__file__).resolve().parents[1]
        / "configs"
        / "agent"
        / "belief_graph_guided.yaml"
    )
    config, mode = load_agent_config(config_path)
    assert mode == "graph_mappo_adaptive_alns"
    assert config["graph_hidden_dim"] == 128
    assert config["graph_num_layers"] == 2
    assert config["guidance_beta"] == 1.0
