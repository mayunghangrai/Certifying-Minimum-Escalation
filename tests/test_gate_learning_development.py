"""Tests for the adaptive-gate methodology-development experiment."""

from __future__ import annotations

import copy
import csv
import json
from pathlib import Path

import matplotlib.image as mpimg
import numpy as np
import pytest
import torch

from agents.mappo_agent import MAPPOAgent
from env.params import EnvParams
from env.scenario_generator import generate_scenario
from env.uav_env import UAMTVRPIUEnv
from methods.adaptive_gate_diagnostics import (
    FEATURE_SCHEMA,
    assert_truth_exclusion,
    counterfactual_policy,
)
from methods.belief_graph import PLAN_FEATURE_NAMES
from methods.gate_learning_development import (
    QUALITATIVE_AUDIT_SEED,
    REGIME_FIXTURE_VERSION,
    REGIMES,
    TRAINING_SEEDS,
    VALIDATION_SEEDS,
    VERDICTS,
    assert_regime_coverage,
    bootstrap_mean_interval,
    build_regime_intervention,
    classify_operational_regime,
    development_seed_split,
    episode_assignments,
    evaluate_matched_states,
    feature_relationship_rows,
    matched_feature_profiles,
    paired_fresh_stale_effect,
    prior_feasible_regime_counts,
    regime_gate_summary,
    regime_intervention_manifest,
    select_gate_learning_verdict,
    spearman_correlation,
)
from scripts.plot_gate_learning_development import FIGURE_NAMES, plot
from scripts.run_gate_learning_development import (
    _aggregate_evaluation,
    _component_hashes,
    _copy_initialization,
    _run_episode,
)
from scripts.reevaluate_adaptive_checkpoints import select_checkpoint


def _fixture(seed=18440):
    params = EnvParams()
    params.mission.T = 0.35
    params.hybrid.alns_iterations = 2
    env = UAMTVRPIUEnv(params)
    obs, info = env.reset(scenario=generate_scenario(seed, params))
    config = {
        "device": "cpu",
        "hidden_dim": 64,
        "encoder_dim": 32,
        "graph_hidden_dim": 32,
        "graph_num_layers": 2,
        "graph_num_heads": 4,
        "guidance_hidden_dim": 64,
        "guidance_beta": 1.0,
        "fixed_guidance_gate": 0.5,
        "update_epochs": 1,
    }
    return params, env, obs, info, config


def _agent(env, config, mode):
    return MAPPOAgent(
        env.M,
        env.obs_dims,
        env.n_actions,
        {**config, "method_mode": mode},
    )


def test_development_split_and_assignments_are_exact_and_deterministic():
    split = development_seed_split()
    assert split["training_seeds"] == list(range(18440, 18480))
    assert split["validation_seeds"] == list(range(18480, 18490))
    assert split["qualitative_audit_seed"] == 18427
    assert not set(TRAINING_SEEDS) & set(VALIDATION_SEEDS)
    assert QUALITATIVE_AUDIT_SEED not in TRAINING_SEEDS
    first = episode_assignments(200)
    second = episode_assignments(200)
    assert first == second
    assert {row["scenario_seed"] for row in first} == set(TRAINING_SEEDS)
    counts = {
        regime: sum(row["target_regime"] == regime for row in first)
        for regime in REGIMES
    }
    assert all(counts[regime] / 200 >= 0.10 for regime in REGIMES[1:])


def test_regime_fixtures_are_deterministic_pre_replay_interventions():
    params = EnvParams()
    params.mission.T = 1.0
    params.hybrid.alns_iterations = 10
    scenario = generate_scenario(TRAINING_SEEDS[0], params)
    original_hash = scenario.content_hash()
    manifest = regime_intervention_manifest(scenario, params)
    assert set(manifest) == set(REGIMES)
    assert all(
        row["fixture_version"] == REGIME_FIXTURE_VERSION
        and row["randomness_sampled_after_reset"] is False
        for row in manifest.values()
    )
    for regime in REGIMES:
        first = build_regime_intervention(scenario, regime, params)
        second = build_regime_intervention(scenario, regime, params)
        assert first.content_hash() == second.content_hash()
        assert first is not scenario
    assert scenario.content_hash() == original_hash
    fresh = build_regime_intervention(
        scenario, "FRESH_AND_STABLE", params
    )
    assert not fresh.p1_reports
    assert not fresh.avail_changes
    assert not fresh.replenishments
    assert all(
        node.reveal_time == 0.0 or node.reveal_time > params.mission.T
        for node in fresh.nodes
    )
    execution = build_regime_intervention(
        scenario, "EXECUTION_DEVIATION", params
    )
    assert len(execution.p1_reports) == 2
    assert execution.p1_reports[0].t < execution.p1_reports[1].t


def test_shared_initialization_copies_all_components_and_checkpoints_reload(
    tmp_path,
):
    _, env, _, _, config = _fixture()
    torch.manual_seed(74)
    shared = _agent(env, config, "graph_mappo")
    # Materialize non-empty Adam state without introducing another objective.
    for optimizer, module in (
        (shared.actor_optimizer, shared.actor),
        (shared.critic_optimizer, shared.critic),
    ):
        optimizer.zero_grad()
        for parameter in module.parameters():
            parameter.grad = torch.zeros_like(parameter)
        optimizer.step()
    fixed = _agent(env, config, "graph_mappo_fixed_alns")
    adaptive = _agent(env, config, "graph_mappo_adaptive_alns")
    _copy_initialization(shared, fixed)
    _copy_initialization(shared, adaptive)
    assert _component_hashes(shared) == _component_hashes(fixed)
    assert _component_hashes(shared) == _component_hashes(adaptive)
    assert fixed.actor_optimizer.state_dict()["state"]
    path = tmp_path / "adaptive.pt"
    adaptive.save(path)
    restored = _agent(env, config, "graph_mappo_adaptive_alns")
    restored.load(path)
    assert _component_hashes(restored) == _component_hashes(adaptive)


def test_regime_labels_are_offline_and_soft_guidance_is_operational():
    _, env, obs, info, config = _fixture(18441)
    graph = env.get_operational_belief_graph()
    assert "regime" not in PLAN_FEATURE_NAMES
    assert "regime" not in json.dumps(FEATURE_SCHEMA).lower()
    assert len(PLAN_FEATURE_NAMES) == 10
    agent = _agent(env, config, "graph_mappo_adaptive_alns")
    agent.select_actions(
        obs,
        info["masks"],
        env.get_global_state(),
        deterministic=True,
        graph=graph,
        diagnostics_enabled=True,
    )
    found = False
    for uav_id, detail in agent.last_diagnostics.items():
        recommendation = int(detail["recommended_action"])
        if recommendation >= 0:
            found = True
            prior = np.asarray(detail["alns_prior"])
            expected = np.zeros_like(prior)
            expected[recommendation] = 1.0
            np.testing.assert_array_equal(prior, expected)
            assert info["masks"][uav_id][recommendation]
    assert found


@pytest.mark.parametrize(
    ("features", "expected"),
    [
        ([0, 0, 0, 0, 0, 0, 0, 0, 0, 1], "FRESH_AND_STABLE"),
        ([0, 1, 0, 0, 0, 0, 0, 0, 0, 1], "DEMAND_UPDATED_BUT_FEASIBLE"),
        ([0, 0, 0, 1, 0, 0, 0, 0, 0, 1], "NEW_NODE_REVEALED"),
        ([0, 0, 1, 0, 0, 0, 0, 0, 0, 1], "INVENTORY_CHANGED"),
        ([0, 0, 0, 0, 0, 0, 1, 0, 0, 1], "EXECUTION_DEVIATION"),
        ([0, 0, 0, 0, 1, 0, 0, 0, 0, 1], "PARTIALLY_INVALID_PLAN"),
        ([0, 1, 1, 0, 0, 0, 0, 0, 0, 1], "MIXED_OPERATIONAL_CHANGE"),
    ],
)
def test_operational_regime_classification(features, expected):
    row = dict(zip(PLAN_FEATURE_NAMES, features))
    assert classify_operational_regime(row) == expected


@pytest.mark.parametrize(
    "regime",
    (
        "FRESH_AND_STABLE",
        "PARTIALLY_INVALID_PLAN",
        "MIXED_OPERATIONAL_CHANGE",
    ),
)
def test_hard_regime_fixtures_create_actual_usable_decisions(regime):
    params, env, _, _, config = _fixture(18480)
    torch.manual_seed(0)
    agent = _agent(env, config, "graph_mappo_adaptive_alns")
    _, rows, _ = _run_episode(
        env=env,
        scenario=generate_scenario(18480, params),
        agent=agent,
        branch="graph_mappo_adaptive_alns",
        phase="fixture_test",
        episode=1,
        checkpoint_episode=0,
        target_regime=regime,
        train=False,
        deterministic=True,
    )
    counts = prior_feasible_regime_counts(rows)
    assert counts[regime] >= 1
    assert all(
        row["regime_fixture_version"] == REGIME_FIXTURE_VERSION
        for row in rows
    )


def test_regime_coverage_fails_loudly():
    row = {
        "regime": "FRESH_AND_STABLE",
        "prior_nonzero": 1,
        "recommended_action_feasible": 1,
    }
    assert_regime_coverage(
        [row], {"FRESH_AND_STABLE": 1}, phase="test"
    )
    with pytest.raises(AssertionError, match="FRESH_AND_STABLE=1<2"):
        assert_regime_coverage(
            [row], {"FRESH_AND_STABLE": 2}, phase="test"
        )


def test_directional_gate_regularizer_pushes_fresh_above_stale():
    _, env, _, _, config = _fixture(18441)
    config = {
        **config,
        "gate_directional_regularization_coef": 1.0,
        "gate_directional_margin": 0.10,
    }
    agent = _agent(env, config, "graph_mappo_adaptive_alns")
    optimizer = torch.optim.Adam(
        agent.actor.guidance_gate.parameters(), lr=1e-2
    )
    with torch.no_grad():
        _, fresh_before, stale_before, _ = agent._gate_directional_loss()
        difference_before = float(fresh_before - stale_before)
    for _ in range(100):
        optimizer.zero_grad()
        loss, _, _, _ = agent._gate_directional_loss()
        loss.backward()
        optimizer.step()
    with torch.no_grad():
        loss, fresh_after, stale_after, satisfied = (
            agent._gate_directional_loss()
        )
    assert float(fresh_after - stale_after) > difference_before
    assert float(loss) < 1e-3
    assert float(satisfied) == pytest.approx(1.0)


def test_truth_exclusion_and_hidden_truth_cannot_change_regime_label():
    row = {
        **dict(zip(PLAN_FEATURE_NAMES, np.zeros(10))),
        "gate_adaptive": 0.5,
        "regime": "FRESH_AND_STABLE",
        "prior_nonzero": 1,
        "recommended_action_feasible": 1,
    }
    before = classify_operational_regime(row)
    hidden_physical_mutation = {"node": 3, "delta": [10, 0, 0, 0]}
    assert hidden_physical_mutation  # deliberately never passed to classifier
    after = classify_operational_regime(row)
    assert before == after
    assert_truth_exclusion(row)
    for forbidden in (
        "true_demand",
        "unreported_corridor",
        "future_event",
        "hidden_p3",
    ):
        assert forbidden not in json.dumps(row).lower()


def test_counterfactual_and_matched_state_isolation_do_not_mutate_env():
    _, env, obs, info, config = _fixture(18442)
    graph = env.get_operational_belief_graph()
    agent = _agent(env, config, "graph_mappo_adaptive_alns")
    agent.select_actions(
        obs,
        info["masks"],
        env.get_global_state(),
        deterministic=True,
        graph=graph,
        diagnostics_enabled=True,
    )
    uav = next(
        u
        for u, detail in agent.last_diagnostics.items()
        if int(detail["recommended_action"]) >= 0
    )
    detail = agent.last_diagnostics[uav]
    vector = {
        "decision_index": 0,
        "scenario_seed": 18442,
        "uav_id": uav,
        "recommended_action": int(detail["recommended_action"]),
        "plan_features": np.asarray(detail["plan_features"]).tolist(),
        "base_logits": np.asarray(detail["base_logits"]).tolist(),
        "alns_prior": np.asarray(detail["alns_prior"]).tolist(),
        "action_mask": np.asarray(detail["action_mask"], dtype=int).tolist(),
    }
    time_before = env.t
    belief_before = copy.deepcopy(env.belief.entries)
    rows, vectors = evaluate_matched_states(agent.actor, [vector])
    assert env.t == time_before
    assert env.belief.entries.keys() == belief_before.keys()
    assert len(rows) == 8
    assert len(vectors) == 8
    for child in vectors:
        assert child["base_logits"] == vector["base_logits"]
        assert child["alns_prior"] == vector["alns_prior"]
        assert child["action_mask"] == vector["action_mask"]
    profiles = matched_feature_profiles(vector["plan_features"])
    assert set(profiles) == {
        "fresh_valid_plan",
        "old_valid_plan",
        "demand_changed_plan",
        "inventory_changed_plan",
        "newly_revealed_node",
        "high_execution_deviation",
        "later_corridor_invalid_current_feasible",
        "combined_stale_deviated",
    }


def test_metric_utilities_are_exact_and_deterministic():
    interval_1 = bootstrap_mean_interval([1, 2, 3, 4], seed=7, samples=500)
    interval_2 = bootstrap_mean_interval([1, 2, 3, 4], seed=7, samples=500)
    assert interval_1 == interval_2
    assert interval_1["mean"] == 2.5
    assert spearman_correlation([1, 2, 3], [3, 2, 1]) == pytest.approx(-1)
    policy = counterfactual_policy(
        np.array([0.1, 0.2]),
        np.array([1.0, 0.0]),
        np.array([True, True]),
        0.8,
        0.5,
        1.0,
    )
    assert policy["kl_adaptive_fixed"] >= 0
    assert policy["tv_adaptive_fixed"] >= 0
    matched = []
    for decision_index in range(3):
        matched.extend(
            [
                {
                    "decision_index": decision_index,
                    "profile": "fresh_valid_plan",
                    "gate_adaptive": 0.7,
                },
                {
                    "decision_index": decision_index,
                    "profile": "combined_stale_deviated",
                    "gate_adaptive": 0.5,
                },
            ]
        )
    effect = paired_fresh_stale_effect(matched)
    assert effect["pair_count"] == 1
    assert effect["source_state_count"] == 3
    assert effect["fresh_minus_stale_mean"] == pytest.approx(0.2)
    assert effect["uncertainty_method"] == (
        "deterministic_exact_no_sampling_interval"
    )
    decisions = []
    for index, regime in enumerate(REGIMES):
        for gate in (0.3, 0.5, 0.7):
            decisions.append(
                {
                    "regime": regime,
                    "prior_nonzero": 1,
                    "recommended_action_feasible": 1,
                    "gate_adaptive": gate,
                    **dict(zip(PLAN_FEATURE_NAMES, np.linspace(0, 1, 10))),
                }
            )
    assert len(regime_gate_summary(decisions)) == 7
    relationships = feature_relationship_rows(decisions)
    assert {row["feature"] for row in relationships}


def test_checkpoint_evaluation_uses_configured_guidance_beta():
    decisions = [
        {
            "gate_adaptive": 0.8,
            "gate_production": 0.8,
            "prior_nonzero": 1,
            "recommended_action_feasible": 1,
            "recommended_action_masked": 0,
            "recommended_action": 0,
            "followed_alns": 1,
        }
    ]
    vectors = [
        {
            "base_logits": [0.0, 1.0],
            "alns_prior": [1.0, 0.0],
            "action_mask": [1, 1],
        }
    ]
    metrics = [
        {
            "reward": -1.0,
            "J_dep_true": 1.0,
            "fill_rate": 0.5,
            "feasibility_violations": 0,
            "episode_duration_h": 1.0,
        }
    ]
    result = _aggregate_evaluation(
        "graph_mappo_adaptive_alns",
        75,
        metrics,
        decisions,
        vectors,
        [],
        0.0,
        guidance_beta=5.591,
        fixed_gate=0.5,
    )
    expected = counterfactual_policy(
        np.asarray(vectors[0]["base_logits"]),
        np.asarray(vectors[0]["alns_prior"]),
        np.asarray(vectors[0]["action_mask"], dtype=bool),
        0.8,
        0.5,
        5.591,
    )
    wrong_beta = counterfactual_policy(
        np.asarray(vectors[0]["base_logits"]),
        np.asarray(vectors[0]["alns_prior"]),
        np.asarray(vectors[0]["action_mask"], dtype=bool),
        0.8,
        0.5,
        1.0,
    )
    assert result["guidance_beta"] == pytest.approx(5.591)
    assert result["adaptive_fixed_tv"] == pytest.approx(
        expected["tv_adaptive_fixed"]
    )
    assert result["adaptive_fixed_tv"] != pytest.approx(
        wrong_beta["tv_adaptive_fixed"]
    )


def test_checkpoint_selection_requires_gate_validity_and_logistics():
    base = {
        "guidance_beta": 5.591,
        "fixed_gate": 0.5,
        "prior_coverage": 0.5,
        "gate_standard_deviation": 0.04,
        "mean_abs_gate_minus_fixed": 0.10,
        "paired_effect": 0.20,
        "paired_ci_low": 0.20,
        "adverse_profiles_below_fresh": 6,
        "matched_profile_median_adaptive_fixed_tv": 0.01,
        "matched_profile_adaptive_fixed_argmax_rate": 0.02,
        "matched_profile_adaptive_unguided_argmax_rate": 0.04,
        "matched_fresh_minus_stale_follow_rate": 0.10,
        "matched_recommended_probability_saturation_rate": 0.0,
        "feasibility_violations": 0,
        "production_gate_mean": 0.4,
        "effective_guidance_scale_mean": 2.2364,
        "alns_follow_rate": 0.1,
        "counterfactual_fixed_alns_follow_rate": 0.1,
    }
    candidates = [
        {
            **base,
            "checkpoint_episode": 75,
            "mean_true_deprivation_cost": 100.0,
            "mean_fill_rate": 0.20,
            "cumulative_reward": -1000.0,
        },
        {
            **base,
            "checkpoint_episode": 100,
            "mean_true_deprivation_cost": 90.0,
            "mean_fill_rate": 0.25,
            "cumulative_reward": -900.0,
        },
    ]
    fixed = {
        "checkpoint_episode": 200,
        "mean_true_deprivation_cost": 80.0,
        "mean_fill_rate": 0.30,
        "cumulative_reward": -800.0,
        "feasibility_violations": 0,
    }
    unguided = {"checkpoint_episode": 0}
    selection = select_checkpoint(
        candidates,
        fixed=fixed,
        unguided=unguided,
    )
    assert selection["selected_adaptive_checkpoint_episode"] == 100
    assert selection["status"] == "FIXED_GUIDANCE_RETAINED"
    assert selection["best_guided_baseline"]["mode"] == (
        "graph_mappo_fixed_alns"
    )
    assert selection["production_policy"]["production_gate"] == 0.0


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        (
            {},
            "TRAINING_OR_IMPLEMENTATION_FAILURE",
        ),
        (
            {"invalid_conditions": ["nan"]},
            "TRAINING_OR_IMPLEMENTATION_FAILURE",
        ),
        (
            {
                "prior_coverage": 0.5,
                "prior_bearing_decisions": 1200,
                "gate_standard_deviation": 0.05,
                "paired_effect": 0.08,
                "paired_ci_low": 0.03,
                "stale_regimes_below_fresh": 4,
                "prior_median_adaptive_fixed_tv": 0.004,
                "gate_gradients_finite_nonzero": True,
                "development_stability_ok": True,
                "logistics_competitive_with_fixed": True,
            },
            "KEEP_EXISTING_ADAPTIVE_GATE",
        ),
        (
            {
                "prior_coverage": 0.5,
                "prior_bearing_decisions": 1200,
                "gate_standard_deviation": 0.05,
                "paired_effect": 0.08,
                "paired_ci_low": 0.03,
                "stale_regimes_below_fresh": 4,
                "prior_median_adaptive_fixed_tv": 0.0001,
                "prior_adaptive_fixed_argmax_rate": 0.0,
                "gate_gradients_finite_nonzero": True,
                "development_stability_ok": True,
                "logistics_competitive_with_fixed": True,
                "episodes_completed": 1000,
                "planned_episodes": 1000,
            },
            "GATE_LEARNED_POLICY_INERT",
        ),
        (
            {
                "gate_gradients_finite_nonzero": True,
                "gate_separation_trend": 0.001,
                "episodes_completed": 200,
            },
            "MORE_TRAINING_REQUIRED",
        ),
        (
            {
                "gate_gradients_finite_nonzero": True,
                "gate_separation_trend": 0.001,
                "episodes_completed": 200,
                "paired_effect": -0.10,
                "paired_ci_low": -0.10,
                "paired_ci_high": -0.10,
            },
            "WRONG_DIRECTION_GATE",
        ),
        (
            {
                "gate_gradients_finite_nonzero": True,
                "episodes_completed": 200,
                "gate_standard_deviation": 0.01,
                "mean_abs_gate_minus_fixed": 0.01,
                "paired_effect": 0.01,
                "paired_ci_low": -0.01,
                "actor_absorbs_follow": True,
            },
            "ACTOR_GATE_IDENTIFIABILITY_PROBLEM",
        ),
        (
            {
                "gate_standard_deviation": 0.01,
                "mean_abs_gate_minus_fixed": 0.01,
                "prior_median_adaptive_fixed_tv": 0.0001,
                "prior_adaptive_fixed_argmax_rate": 0.0,
                "gate_gradients_finite_nonzero": True,
            },
            "FIXED_GUIDANCE_SUFFICIENT",
        ),
    ],
)
def test_every_verdict_category(overrides, expected):
    defaults = {
        "invalid_conditions": [],
        "prior_coverage": 0.0,
        "prior_bearing_decisions": 0,
        "gate_standard_deviation": 0.0,
        "mean_abs_gate_minus_fixed": 0.0,
        "paired_effect": 0.0,
        "paired_ci_low": -1.0,
        "paired_ci_high": 1.0,
        "stale_regimes_below_fresh": 0,
        "prior_median_adaptive_fixed_tv": 0.0,
        "prior_adaptive_fixed_argmax_rate": 0.0,
        "gate_gradients_finite_nonzero": False,
        "development_stability_ok": False,
        "logistics_competitive_with_fixed": False,
        "gate_separation_trend": 0.0,
        "episodes_completed": 200,
        "planned_episodes": 1000,
        "actor_absorbs_follow": False,
    }
    verdict = select_gate_learning_verdict({**defaults, **overrides})
    assert verdict["verdict"] == expected
    assert verdict["verdict"] in VERDICTS


def _csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_all_required_figures_open_from_canonical_tables(tmp_path):
    for directory, scale in (
        ("graph_mappo", 1.0),
        ("fixed_guidance", 0.95),
        ("adaptive_guidance", 0.9),
    ):
        _csv(
            tmp_path / directory / "training_log.csv",
            [
                {
                    "episode": episode,
                    "gate_mean": 0.5 + 0.001 * episode,
                    "gate_standard_deviation": 0.02,
                    "mean_abs_gate_minus_fixed": 0.001 * episode,
                    "J_dep_true": scale * (100 - episode),
                }
                for episode in range(1, 11)
            ],
        )
        _csv(
            tmp_path / directory / "evaluation_log.csv",
            [
                {
                    "checkpoint_episode": episode,
                    "mean_true_deprivation_cost": scale * (100 - episode),
                }
                for episode in (5, 10)
            ],
        )
    decisions = []
    counter = []
    matched = []
    relationships = []
    summary = []
    index = 0
    for regime_index, regime in enumerate(REGIMES):
        for sample in range(5):
            gate = 0.65 - 0.02 * regime_index + 0.001 * sample
            decisions.append(
                {
                    "regime": regime,
                    "prior_nonzero": 1,
                    "recommended_action_feasible": 1,
                    "gate_adaptive": gate,
                }
            )
            counter.append(
                {
                    "regime": regime,
                    "prior_nonzero": 1,
                    "tv_adaptive_fixed": 0.001 * (regime_index + 1),
                    "kl_adaptive_fixed": 0.0001 * (regime_index + 1),
                    "unguided_follows_alns": 0,
                    "fixed_follows_alns": 1,
                    "adaptive_follows_alns": int(regime_index < 3),
                }
            )
            matched.extend(
                [
                    {
                        "decision_index": index,
                        "profile": "fresh_valid_plan",
                        "gate_adaptive": 0.65,
                    },
                    {
                        "decision_index": index,
                        "profile": "combined_stale_deviated",
                        "gate_adaptive": 0.50,
                    },
                ]
            )
            index += 1
        summary.append({"regime": regime, "decision_count": 5, "median": gate})
    for feature_index, feature in enumerate(
        (
            "plan_age",
            "operational_demand_change",
            "operational_inventory_change",
            "newly_known_fraction",
            "invalid_planned_corridor_fraction",
            "execution_deviation",
            "next_action_operationally_feasible",
        )
    ):
        for bin_index in range(4):
            relationships.append(
                {
                    "feature": feature,
                    "spearman": -0.5,
                    "bin": bin_index,
                    "bin_low": 0.25 * bin_index,
                    "bin_high": 0.25 * (bin_index + 1),
                    "count": 10,
                    "mean_gate": 0.7 - 0.05 * bin_index,
                }
            )
    _csv(tmp_path / "validation" / "regime_decisions.csv", decisions)
    _csv(
        tmp_path / "validation" / "counterfactual_policy_comparison.csv",
        counter,
    )
    _csv(tmp_path / "validation" / "matched_state_pairs.csv", matched)
    _csv(tmp_path / "validation" / "feature_relationships.csv", relationships)
    _csv(tmp_path / "validation" / "regime_gate_summary.csv", summary)
    targets = {
        "prior_coverage_at_least_0_30": True,
        "prior_decisions_at_least_1000": False,
        "material_gate_variation": True,
        "paired_effect_at_least_0_05_ci_positive": True,
        "three_stale_regimes_below_fresh": True,
        "measurable_policy_difference": True,
        "finite_nonzero_gate_gradients": True,
        "truth_mask_observation_checks": True,
        "no_catastrophic_collapse": True,
    }
    (tmp_path / "gate_learning_verdict.json").write_text(
        json.dumps(
            {
                "verdict": "MORE_TRAINING_REQUIRED",
                "development_targets": targets,
            }
        ),
        encoding="utf-8",
    )
    outputs = plot(tmp_path, tmp_path / "figures")
    assert [path.name for path in outputs] == list(FIGURE_NAMES)
    for path in outputs:
        image = mpimg.imread(path)
        assert image.size > 0
        assert np.isfinite(image).all()
