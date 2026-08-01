"""Correctness and behavior-preservation tests for adaptive-gate diagnostics."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import matplotlib.image as mpimg
import numpy as np
import pytest
import torch

from agents.mappo_agent import MAPPOAgent
from env.events import Event, EventType
from env.params import EnvParams
from env.scenario_generator import generate_scenario
from env.uav_env import UAMTVRPIUEnv
from methods.adaptive_gate_diagnostics import (
    AdaptiveGateDiagnostics,
    DEFAULT_DIAGNOSTIC_CONFIG,
    FEATURE_SCHEMA,
    assert_truth_exclusion,
    build_decision_diagnostic,
    classify_root_causes,
    counterfactual_policy,
    evaluate_controlled_probes,
)
from methods.belief_graph import PLAN_FEATURE_NAMES
from scripts.plot_adaptive_gate_diagnostics import FIGURE_NAMES, plot


def _fixture(seed=920):
    params = EnvParams()
    params.mission.T = 0.6
    params.hybrid.alns_iterations = 2
    env = UAMTVRPIUEnv(params)
    obs, info = env.reset(scenario=generate_scenario(seed, params))
    graph = env.get_operational_belief_graph()
    config = {
        "device": "cpu",
        "method_mode": "graph_mappo_adaptive_alns",
        "hidden_dim": 64,
        "encoder_dim": 32,
        "graph_hidden_dim": 32,
        "graph_num_heads": 4,
        "update_epochs": 1,
    }
    torch.manual_seed(71)
    agent = MAPPOAgent(env.M, env.obs_dims, env.n_actions, config)
    return env, obs, info, graph, agent, config


def _decision(env, obs, info, graph, agent, decision_index=0):
    actions, log_probs, value = agent.select_actions(
        obs,
        info["masks"],
        env.get_global_state(),
        deterministic=True,
        graph=graph,
        diagnostics_enabled=True,
    )
    uav = sorted(obs)[0]
    row, counter, vectors = build_decision_diagnostic(
        detail=agent.last_diagnostics[uav],
        graph=graph,
        env=env,
        uav_id=uav,
        context={
            "run_id": "test",
            "mode": agent.method_mode,
            "master_seed": 920,
            "training_seed": 921,
            "evaluation_seed": "",
            "episode": 1,
            "environment_step": 0,
            "decision_index": decision_index,
            "decision_time": env.t,
            "checkpoint_identifier": "initial",
            "phase": "training",
            "selection_mode": "deterministic",
        },
    )
    return actions, log_probs, value, row, counter, vectors


def test_feature_schema_exact_order_and_truth_exclusion():
    assert tuple(item["name"] for item in FEATURE_SCHEMA) == PLAN_FEATURE_NAMES
    assert [item["index"] for item in FEATURE_SCHEMA] == list(range(10))
    for item in FEATURE_SCHEMA:
        assert item["source_state"]
        assert item["normalization_rule"]
        assert item["missing_value_rule"]
        assert "operational" in item["operational_information_guarantee"].lower()
    encoded = json.dumps(FEATURE_SCHEMA).lower()
    for forbidden in ("true_demand", "true_vulnerability", "physical_corridor"):
        assert forbidden not in encoded


def test_counterfactual_exact_algebra_and_mask_precedence():
    base = np.array([0.2, -0.4, 1.1, 0.5])
    prior = np.array([1.0, 0.0, 0.0, 0.0])
    mask = np.array([False, True, True, True])
    result = counterfactual_policy(base, prior, mask, 0.3, 0.5, 2.0)
    np.testing.assert_allclose(result["unguided_logits"], base)
    np.testing.assert_allclose(
        result["adaptive_guided_logits"], base + 2.0 * 0.3 * prior
    )
    np.testing.assert_allclose(
        result["fixed_guided_logits"], base + 2.0 * 0.5 * prior
    )
    assert result["adaptive_probabilities"][0] == 0.0
    assert result["fixed_probabilities"][0] == 0.0
    assert result["masked_adaptive_logits"][0] == -1e8


def test_diagnostics_on_off_add_no_rng_draws_or_action_change():
    env, obs, info, graph, agent, _ = _fixture()
    rng = torch.random.get_rng_state().clone()
    first = agent.select_actions(
        obs, info["masks"], env.get_global_state(),
        deterministic=False, graph=graph, diagnostics_enabled=False,
    )
    end_first = torch.random.get_rng_state().clone()
    torch.random.set_rng_state(rng)
    second = agent.select_actions(
        obs, info["masks"], env.get_global_state(),
        deterministic=False, graph=graph, diagnostics_enabled=True,
    )
    end_second = torch.random.get_rng_state().clone()
    assert first == second
    torch.testing.assert_close(end_first, end_second, rtol=0, atol=0)


def test_diagnostics_preserve_loss_gradients_and_parameter_updates():
    env, obs, info, graph, plain, config = _fixture(921)
    observed = MAPPOAgent(env.M, env.obs_dims, env.n_actions, config)
    observed.actor.load_state_dict(copy.deepcopy(plain.actor.state_dict()))
    observed.critic.load_state_dict(copy.deepcopy(plain.critic.state_dict()))
    actions, log_probs, value = plain.select_actions(
        obs, info["masks"], env.get_global_state(),
        deterministic=True, graph=graph,
    )
    plain.begin_episode()
    plain.record_decisions(
        env.t, obs, info["masks"], env.get_global_state(),
        actions, log_probs, value, graph=graph,
    )
    start = env.t
    _, reward, _, _ = env.step(actions)
    plain.record_reward(reward, start)
    plain.end_episode(env.t)
    observed._traj = copy.deepcopy(plain._traj)
    observed._pending = {}

    expected = plain.update()
    collector = AdaptiveGateDiagnostics()
    actual = observed.update(
        collector, {"run_id": "test", "mode": observed.method_mode, "episode": 1}
    )
    np.testing.assert_allclose(actual, expected, rtol=0, atol=0)
    for left, right in zip(plain.actor.parameters(), observed.actor.parameters()):
        torch.testing.assert_close(left, right, rtol=0, atol=0)
        if left.grad is not None:
            torch.testing.assert_close(left.grad, right.grad, rtol=0, atol=0)
    direct_gradient_norm = float(
        observed.last_gate_gradient_vector_preclip.pow(2).sum().sqrt()
    )
    direct_update_norm = float(
        (
            observed.last_gate_parameters_after_update
            - observed.last_gate_parameters_before_update
        ).pow(2).sum().sqrt()
    )
    assert collector.update_rows[0]["gate_gradient_l2_norm"] == pytest.approx(
        direct_gradient_norm
    )
    assert collector.update_rows[0][
        "gate_parameter_update_l2_distance"
    ] == pytest.approx(direct_update_norm)


def test_diagnostic_fields_do_not_break_checkpoint_compatibility(tmp_path):
    env, _, _, _, agent, config = _fixture(925)
    path = tmp_path / "diagnostic-compatible.pt"
    agent.save(path)
    restored = MAPPOAgent(env.M, env.obs_dims, env.n_actions, config)
    restored.load(path)
    for expected, actual in zip(
        agent.actor.state_dict().values(), restored.actor.state_dict().values()
    ):
        torch.testing.assert_close(expected, actual, rtol=0, atol=0)
    for expected, actual in zip(
        agent.critic.state_dict().values(), restored.critic.state_dict().values()
    ):
        torch.testing.assert_close(expected, actual, rtol=0, atol=0)


def test_prior_mapping_zero_reason_mask_and_full_vectors_are_consistent():
    env, obs, info, graph, agent, _ = _fixture(922)
    _, _, _, row, _, vectors = _decision(env, obs, info, graph, agent)
    prior = np.asarray(vectors["alns_prior"])
    assert row["prior_nonzero_count"] == np.count_nonzero(prior)
    assert row["prior_l1_norm"] == pytest.approx(np.abs(prior).sum())
    assert row["positive_prior_actions_surviving_mask"] <= row[
        "positive_prior_action_count"
    ]
    adaptive = np.asarray(vectors["adaptive_probabilities"])
    assert row["adaptive_argmax_action"] == int(np.argmax(adaptive))
    assert row["kl_adaptive_unguided"] >= 0.0
    if row["recommended_action"] >= 0:
        expected = np.zeros_like(prior)
        expected[row["recommended_action"]] = 1.0
        np.testing.assert_array_equal(prior, expected)

    env.scaffold.plans = {u: [] for u in range(env.M)}
    empty = env.get_operational_belief_graph()
    assert np.count_nonzero(empty.alns_prior) == 0
    assert all(
        reason in {
            "NO_UAV_RECOMMENDATION", "RECOMMENDATION_ALREADY_COMPLETED"
        }
        for reason in empty.zero_prior_reasons
    )


def test_mapping_failure_masked_recommendation_and_zero_prior_are_explicit():
    env, obs, info, graph, agent, _ = _fixture(926)
    agent.select_actions(
        obs, info["masks"], env.get_global_state(),
        deterministic=True, graph=graph, diagnostics_enabled=True,
    )
    uav = sorted(obs)[0]
    detail = copy.deepcopy(agent.last_diagnostics[uav])
    context = {
        "run_id": "test", "mode": agent.method_mode, "master_seed": 926,
        "training_seed": 927, "evaluation_seed": "", "episode": 1,
        "environment_step": 0, "decision_index": 0,
        "decision_time": env.t, "checkpoint_identifier": "initial",
        "phase": "training", "selection_mode": "deterministic",
    }

    detail["alns_prior"] = np.zeros_like(detail["alns_prior"])
    detail["recommended_action"] = len(detail["alns_prior"]) + 1
    outside, _, outside_vectors = build_decision_diagnostic(
        detail=detail, graph=graph, env=env, uav_id=uav, context=context,
    )
    assert outside["recommendation_maps_successfully"] == 0
    assert outside["zero_prior_reason"] == (
        "RECOMMENDED_ACTION_NOT_IN_CURRENT_ACTION_SET"
    )
    np.testing.assert_array_equal(
        outside_vectors["base_logits"],
        outside_vectors["adaptive_guided_logits"],
    )

    mapped_detail = copy.deepcopy(agent.last_diagnostics[uav])
    recommended = int(mapped_detail["recommended_action"])
    assert recommended >= 0
    failed_graph = copy.deepcopy(graph)
    failed_graph.action_to_destination[uav, recommended] = -1
    mapped_detail["alns_prior"] = np.zeros_like(mapped_detail["alns_prior"])
    failed, _, _ = build_decision_diagnostic(
        detail=mapped_detail, graph=failed_graph, env=env,
        uav_id=uav, context=context,
    )
    assert failed["zero_prior_reason"] == "ACTION_MAPPING_FAILED"

    masked_detail = copy.deepcopy(agent.last_diagnostics[uav])
    masked_detail["action_mask"][recommended] = False
    masked, _, _ = build_decision_diagnostic(
        detail=masked_detail, graph=graph, env=env,
        uav_id=uav, context=context,
    )
    assert masked["recommended_action_masked"] == 1
    assert masked["any_positive_prior_action_masked"] == 1
    assert masked["positive_prior_actions_surviving_mask"] == 0


def test_counterfactual_logging_does_not_mutate_environment_or_leak_hidden_p3():
    env, obs, info, graph, agent, _ = _fixture(923)
    known = min(env.belief.known)
    _, _, _, before, _, _ = _decision(env, obs, info, graph, agent)
    time_before = env.t
    belief_before = env.belief.entries[known].mu.copy()
    env._apply_event(
        Event(
            env.t,
            EventType.P3_MUTATION,
            {"node": known, "delta": np.array([0.0, 0.0, 50.0, 0.0])},
        )
    )
    graph_after = env.get_operational_belief_graph()
    _, _, _, after, _, _ = _decision(env, obs, info, graph_after, agent, 1)
    assert env.t == time_before
    np.testing.assert_array_equal(env.belief.entries[known].mu, belief_before)
    for feature in PLAN_FEATURE_NAMES:
        assert before[f"{feature}__normalized"] == after[
            f"{feature}__normalized"
        ]
    assert_truth_exclusion(after)


@pytest.mark.parametrize(
    ("metrics", "expected"),
    [
        ({"prior_coverage_rate": 0.0}, "NO_PRIOR_COVERAGE"),
        ({"prior_coverage_rate": 1.0, "prior_masked_rate": 0.9}, "PRIOR_MOSTLY_MASKED"),
        ({"prior_coverage_rate": 1.0, "mean_abs_gate_minus_fixed": 0.001}, "GATE_CLOSE_TO_FIXED"),
        ({"prior_coverage_rate": 1.0, "gate_below_005_fraction": 0.9}, "GATE_SATURATED_LOW"),
        ({"prior_coverage_rate": 1.0, "gate_above_095_fraction": 0.9}, "GATE_SATURATED_HIGH"),
        ({"prior_coverage_rate": 1.0, "mean_max_logit_shift": 0.001}, "GUIDANCE_LOGIT_EFFECT_NEGLIGIBLE"),
        ({
            "prior_coverage_rate": 1.0,
            "mean_max_logit_shift": 1.0,
            "mean_kl_adaptive_unguided": 0.1,
            "adaptive_unguided_argmax_change_rate": 0.0,
        }, "PROBABILITIES_CHANGE_BUT_ACTIONS_DO_NOT"),
        ({
            "prior_coverage_rate": 1.0,
            "feature_statuses": ["CONSTANT", "CONSTANT"],
        }, "PLAN_FEATURES_CONSTANT"),
        ({
            "prior_coverage_rate": 1.0,
            "feature_statuses": ["VARIABLE", "CONSTANT"],
        }, "PLAN_FEATURES_PARTIALLY_DEGENERATE"),
        ({
            "prior_coverage_rate": 1.0,
            "median_gate_gradient_norm": 0.0,
        }, "GATE_GRADIENT_ABSENT"),
        ({
            "prior_coverage_rate": 1.0,
            "median_gate_gradient_norm": 1e-3,
            "median_relative_gate_update": 1e-10,
        }, "GATE_UPDATE_NEGLIGIBLE"),
        ({
            "prior_coverage_rate": 1.0,
            "fixed_adaptive_paths_identical": True,
        }, "FIXED_AND_ADAPTIVE_PATHS_IDENTICAL"),
        ({
            "prior_coverage_rate": 1.0,
            "prior_bearing_decisions": 1,
            "ppo_updates": 1,
        }, "SMOKE_RUN_TOO_SHORT"),
        ({
            "prior_coverage_rate": 1.0,
            "stochastic_action_coincidence": True,
        }, "STOCHASTIC_ACTION_COINCIDENCE"),
        ({
            "prior_coverage_rate": 1.0,
            "synchronous_solver_features_constant": True,
        }, "SYNCHRONOUS_ALNS_FEATURE_LIMITATION"),
        ({}, "NO_DIAGNOSTIC_PROBLEM_DETECTED"),
        ({
            "prior_coverage_rate": 0.0,
            "mean_abs_gate_minus_fixed": 0.0,
        }, "NO_SINGLE_DOMINANT_CAUSE"),
    ],
)
def test_automatic_diagnosis_categories(metrics, expected):
    defaults = {
        "prior_coverage_rate": 1.0,
        "prior_masked_rate": 0.0,
        "mean_abs_gate_minus_fixed": 1.0,
        "gate_below_005_fraction": 0.0,
        "gate_above_095_fraction": 0.0,
        "mean_max_logit_shift": 1.0,
        "mean_kl_adaptive_unguided": 0.0,
        "adaptive_unguided_argmax_change_rate": 1.0,
        "feature_statuses": ["VARIABLE"],
        "median_gate_gradient_norm": 1.0,
        "median_relative_gate_update": 1.0,
        "fixed_adaptive_paths_identical": False,
        "prior_bearing_decisions": 100,
        "ppo_updates": 20,
        "stochastic_action_coincidence": False,
        "synchronous_solver_features_constant": False,
    }
    classifications = classify_root_causes({**defaults, **metrics})
    assert expected in {item["classification"] for item in classifications}


def test_canonical_outputs_reproducible_and_all_plots_open(tmp_path):
    env, obs, info, graph, agent, _ = _fixture(924)
    _, _, _, row, counter, vectors = _decision(
        env, obs, info, graph, agent
    )
    update = {
        "run_id": "test", "mode": agent.method_mode, "episode": 1,
        "phase": "training", "update_index": 0, "minibatch_index": 0,
        "actor_loss": 0.1, "critic_loss": 0.2, "entropy": 1.0,
        "ppo_kl_estimate": 0.0, "ppo_clipping_fraction": 0.0,
        "gate_gradient_l2_norm": 0.01,
        "gate_gradient_max_absolute": 0.005,
        "gate_gradient_mean_absolute": 0.001,
        "gate_nonzero_gradient_parameter_count": 10,
        "gate_zero_gradient_fraction": 0.0,
        "gate_gradients_all_finite": 1,
        "gate_parameter_l2_norm_before": 2.0,
        "gate_parameter_l2_norm_after": 2.0,
        "gate_parameter_update_l2_distance": 0.001,
        "gate_relative_parameter_update": 0.0005,
        "gate_optimizer_learning_rate": 3e-4,
        "gate_parameters_in_optimizer": 1,
        "gate_parameters_require_grad": 1,
        "gate_module_in_train_mode": 1,
        "average_gate": row["gate_adaptive"],
        "gate_standard_deviation": 0.0,
        "gate_below_005_fraction": 0.0,
        "gate_above_095_fraction": 0.0,
        "average_abs_gate_minus_fixed": row["abs_gate_minus_fixed"],
        "prior_coverage_rate": 1.0 - row["prior_is_zero"],
        "average_policy_kl_from_guidance": row["kl_adaptive_unguided"],
        "adaptive_guidance_argmax_change_fraction": 0.0,
    }
    outputs = []
    for name in ("a", "b"):
        collector = AdaptiveGateDiagnostics(DEFAULT_DIAGNOSTIC_CONFIG)
        collector.record_decision(row, counter, vectors)
        collector.record_update(update)
        collector.record_probes(
            evaluate_controlled_probes(agent.actor, "initial_untrained")
        )
        directory = tmp_path / name
        collector.write(
            directory,
            {"run_id": "test", "decision_count": 1, "performance_claim": "none"},
        )
        outputs.append(directory)
    for filename in (
        "adaptive_gate_feature_schema.json",
        "adaptive_gate_decisions.csv",
        "adaptive_gate_vectors.jsonl.gz",
        "adaptive_gate_update_diagnostics.csv",
        "adaptive_gate_feature_summary.json",
        "adaptive_gate_diagnosis.json",
    ):
        assert (outputs[0] / filename).read_bytes() == (
            outputs[1] / filename
        ).read_bytes()

    figures = plot(outputs[0], outputs[0] / "figures")
    assert {path.name for path in figures} == set(FIGURE_NAMES)
    for figure in figures:
        image = mpimg.imread(figure)
        assert image.size > 0
        assert np.isfinite(image).all()
