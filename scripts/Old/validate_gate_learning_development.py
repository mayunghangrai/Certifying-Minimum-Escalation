"""Validate a completed gate-learning development experiment."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sys
from typing import Mapping, Sequence

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import numpy as np
import torch
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from env.params import EnvParams  # noqa: E402
from env.scenario_generator import generate_scenario  # noqa: E402
from env.uav_env import UAMTVRPIUEnv  # noqa: E402
from methods.adaptive_gate_diagnostics import (  # noqa: E402
    assert_truth_exclusion,
    counterfactual_policy,
)
from methods.belief_graph import PLAN_FEATURE_NAMES  # noqa: E402
from methods.gate_learning_development import (  # noqa: E402
    PRIMARY_FEATURES,
    QUALITATIVE_AUDIT_SEED,
    REGIME_FIXTURE_VERSION,
    REGIMES,
    VALIDATION_SEEDS,
    assert_regime_coverage,
    evaluate_matched_states,
    feature_relationship_rows,
    file_sha256,
    paired_fresh_stale_effect,
    regime_gate_summary,
    select_gate_learning_verdict,
)
from scripts.run_gate_learning_development import (  # noqa: E402
    _component_hashes,
    _make_agent,
    _run_episode,
)
from scripts.train_mappo import DEFAULT_AGENT_CONFIG, load_agent_config  # noqa: E402


REGIME_DECISION_FIELDS = (
    "branch",
    "phase",
    "checkpoint_episode",
    "episode",
    "scenario_seed",
    "target_regime",
    "regime_fixture_version",
    "environment_step",
    "decision_index",
    "decision_time_h",
    "uav_id",
    "selected_action",
    "recommended_action",
    "recommended_action_feasible",
    "recommended_action_masked",
    "prior_nonzero",
    "prior_nonzero_count",
    "gate_production",
    "gate_adaptive",
    "gate_fixed",
    "gate_logit",
    "abs_gate_minus_fixed",
    "followed_alns",
    "regime",
    "regime_label_in_policy_input",
    "state_collection_mode",
    *PLAN_FEATURE_NAMES,
)


def _write_json(path: Path, payload: object) -> None:
    def safe(value):
        if isinstance(value, Mapping):
            return {str(key): safe(child) for key, child in value.items()}
        if isinstance(value, (list, tuple)):
            return [safe(child) for child in value]
        if isinstance(value, (float, np.floating)) and not math.isfinite(
            float(value)
        ):
            return None
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.bool_):
            return bool(value)
        return value

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(safe(payload), indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        if not fields:
            return
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_gzip_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
            for row in rows:
                compressed.write(
                    (
                        json.dumps(
                            row,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        )
                        + "\n"
                    ).encode("utf-8")
                )


def _counterfactual_rows(
    decisions,
    vectors,
    *,
    guidance_beta: float,
    fixed_gate: float,
):
    output = []
    for row, vector in zip(decisions, vectors):
        result = counterfactual_policy(
            np.asarray(vector["base_logits"], dtype=float),
            np.asarray(vector["alns_prior"], dtype=float),
            np.asarray(vector["action_mask"], dtype=bool),
            float(row["gate_adaptive"]),
            fixed_gate,
            guidance_beta,
        )
        recommendation = int(row["recommended_action"])
        valid_recommendation = 0 <= recommendation < len(
            result["adaptive_probabilities"]
        )
        output.append(
            {
                "decision_index": int(row["decision_index"]),
                "scenario_seed": int(row["scenario_seed"]),
                "regime": row["regime"],
                "prior_nonzero": int(row["prior_nonzero"]),
                "recommended_action_feasible": int(
                    row["recommended_action_feasible"]
                ),
                "gate_adaptive": float(row["gate_adaptive"]),
                "gate_fixed": fixed_gate,
                "kl_adaptive_unguided": result["kl_adaptive_unguided"],
                "kl_adaptive_fixed": result["kl_adaptive_fixed"],
                "tv_adaptive_unguided": result["tv_adaptive_unguided"],
                "tv_adaptive_fixed": result["tv_adaptive_fixed"],
                "entropy_unguided": result["entropy_unguided"],
                "entropy_fixed": result["entropy_fixed"],
                "entropy_adaptive": result["entropy_adaptive"],
                "alns_probability_unguided": (
                    float(result["unguided_probabilities"][recommendation])
                    if valid_recommendation
                    else 0.0
                ),
                "alns_probability_fixed": (
                    float(result["fixed_probabilities"][recommendation])
                    if valid_recommendation
                    else 0.0
                ),
                "alns_probability_adaptive": (
                    float(result["adaptive_probabilities"][recommendation])
                    if valid_recommendation
                    else 0.0
                ),
                "argmax_unguided": result["unguided_argmax"],
                "argmax_fixed": result["fixed_argmax"],
                "argmax_adaptive": result["adaptive_argmax"],
                "adaptive_fixed_argmax_different": int(
                    result["adaptive_argmax"] != result["fixed_argmax"]
                ),
                "adaptive_unguided_argmax_different": int(
                    result["adaptive_argmax"] != result["unguided_argmax"]
                ),
                "unguided_follows_alns": int(
                    valid_recommendation
                    and result["unguided_argmax"] == recommendation
                ),
                "fixed_follows_alns": int(
                    valid_recommendation
                    and result["fixed_argmax"] == recommendation
                ),
                "adaptive_follows_alns": int(
                    valid_recommendation
                    and result["adaptive_argmax"] == recommendation
                ),
                "probability_changed_without_argmax_change": int(
                    result["tv_adaptive_fixed"] > 1e-12
                    and result["adaptive_argmax"] == result["fixed_argmax"]
                ),
            }
        )
    return output


def _unique_state_signature(vector: Mapping[str, object]) -> str:
    selected = {
        key: vector[key]
        for key in (
            "scenario_seed",
            "uav_id",
            "recommended_action",
            "plan_features",
            "base_logits",
            "alns_prior",
            "action_mask",
        )
    }
    encoded = json.dumps(
        selected, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _collect_validation(
    *,
    env,
    agent,
    branch,
    params,
    deterministic,
    extension_repeats,
    master_seed,
    collect_decisions,
):
    episode_metrics = []
    decisions = []
    vectors = []
    index = 0
    schedule = [
        (0, seed_index, seed, REGIMES[seed_index % len(REGIMES)])
        for seed_index, seed in enumerate(VALIDATION_SEEDS)
    ]
    for repeat in range(1, extension_repeats + 1):
        for regime_index, regime in enumerate(REGIMES):
            for seed_index, seed in enumerate(VALIDATION_SEEDS):
                schedule.append((repeat, seed_index, seed, regime))
    for episode_index, (repeat, seed_index, seed, target_regime) in enumerate(
        schedule, 1
    ):
        if repeat:
            rollout_seed = (
                master_seed
                + 100000 * repeat
                + 1000 * REGIMES.index(target_regime)
                + seed
            )
            random.seed(rollout_seed)
            np.random.seed(rollout_seed)
            torch.manual_seed(rollout_seed)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(rollout_seed)
        scenario = generate_scenario(seed, params)
        metrics, rows, current_vectors = _run_episode(
            env=env,
            scenario=scenario,
            agent=agent,
            branch=branch,
            phase="final_validation",
            episode=episode_index,
            checkpoint_episode=0,
            target_regime=target_regime,
            train=False,
            deterministic=(deterministic if repeat == 0 else False),
            collect_vectors=collect_decisions,
            decision_start=index,
        )
        mode = (
            "deterministic_argmax"
            if repeat == 0 and deterministic
            else "reproducible_stochastic_extension"
        )
        for row in rows:
            row["state_collection_mode"] = mode
        index += len(rows)
        episode_metrics.append(
            {
                "branch": branch,
                "scenario_seed": seed,
                "repeat": repeat,
                "target_regime": target_regime,
                "state_collection_mode": mode,
                "reward": metrics["reward"],
                "J_dep_true": metrics["J_dep_true"],
                "J_dep_belief": metrics["J_dep_belief"],
                "fill_rate": metrics["fill_rate"],
                "feasibility_violations": metrics[
                    "feasibility_violations"
                ],
                "episode_duration_h": metrics["episode_duration_h"],
                "computational_time_s": metrics["computational_time_s"],
            }
        )
        if collect_decisions:
            decisions.extend(rows)
            vectors.extend(current_vectors)
    return episode_metrics, decisions, vectors


def _performance_summary(rows):
    output = {}
    for branch in ("graph_mappo", "graph_mappo_fixed_alns", "graph_mappo_adaptive_alns"):
        subset = [
            row
            for row in rows
            if row["branch"] == branch
            and int(row["repeat"]) == 0
        ]
        output[branch] = {
            "episode_count": len(subset),
            "mean_reward": float(np.mean([row["reward"] for row in subset])),
            "mean_true_deprivation_cost": float(
                np.mean([row["J_dep_true"] for row in subset])
            ),
            "mean_belief_deprivation_cost": float(
                np.mean([row["J_dep_belief"] for row in subset])
            ),
            "mean_fill_rate": float(
                np.mean([row["fill_rate"] for row in subset])
            ),
            "feasibility_violations": int(
                sum(row["feasibility_violations"] for row in subset)
            ),
        }
    return output


def _load_agents(results, metadata, experiment):
    runtime = experiment["development_runtime"]
    params = EnvParams()
    params.mission.T = float(runtime["mission_horizon_hours"])
    params.hybrid.alns_iterations = int(runtime["alns_iterations"])
    env = UAMTVRPIUEnv(params)
    env.reset(scenario=generate_scenario(VALIDATION_SEEDS[0], params))
    loaded, _ = load_agent_config(metadata["agent_config"])
    config = {
        **DEFAULT_AGENT_CONFIG,
        **loaded,
        "gamma_hour": params.mission.gamma_hour,
        "device": metadata["device"],
        "guidance_beta": float(metadata["beta"]),
        "fixed_guidance_gate": float(metadata["fixed_gate"]),
        "gate_directional_regularization_coef": float(
            experiment["gate_training"][
                "directional_regularization_coefficient"
            ]
        ),
        "gate_directional_margin": float(
            experiment["gate_training"]["directional_margin"]
        ),
    }
    paths = {
        "graph_mappo": results / "graph_mappo" / "checkpoints" / "final.pt",
        "graph_mappo_fixed_alns": (
            results / "fixed_guidance" / "checkpoints" / "final.pt"
        ),
        "graph_mappo_adaptive_alns": (
            results / "adaptive_guidance" / "checkpoints" / "final.pt"
        ),
    }
    agents = {}
    reloads = {}
    for mode, path in paths.items():
        if not path.exists():
            raise FileNotFoundError(f"Missing final checkpoint: {path}")
        agent = _make_agent(env, config, mode)
        agent.load(path)
        expected = _component_hashes(agent)
        reloaded = _make_agent(env, config, mode)
        reloaded.load(path)
        actual = _component_hashes(reloaded)
        reloads[mode] = {
            "passed": expected == actual,
            "checkpoint_sha256": file_sha256(path),
            "component_hashes": expected,
        }
        if expected != actual:
            raise AssertionError(f"Checkpoint reload mismatch: {mode}")
        agents[mode] = agent
    return params, env, agents, reloads


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _validation_metrics(
    *,
    decisions,
    counterfactuals,
    matched_effect,
    matched_rows,
    regime_summary,
    performance,
    update_rows,
    evaluation_rows,
    checkpoint_reloads,
    minimum_prior,
    practical_per_regime,
):
    gates = np.asarray([row["gate_adaptive"] for row in decisions], dtype=float)
    prior_rows = [
        row
        for row in counterfactuals
        if int(row["prior_nonzero"])
        and int(row["recommended_action_feasible"])
    ]
    prior_tv = np.asarray(
        [row["tv_adaptive_fixed"] for row in prior_rows], dtype=float
    )
    prior_argmax = np.asarray(
        [row["adaptive_fixed_argmax_different"] for row in prior_rows],
        dtype=float,
    )
    prior_tv_unguided = np.asarray(
        [row["tv_adaptive_unguided"] for row in prior_rows], dtype=float
    )
    prior_argmax_unguided = np.asarray(
        [row["adaptive_unguided_argmax_different"] for row in prior_rows],
        dtype=float,
    )
    matched_prior = [
        row for row in matched_rows
        if row["profile"] in {
            "fresh_valid_plan",
            "combined_stale_deviated",
        }
    ]
    matched_fresh = [
        row for row in matched_prior
        if row["profile"] == "fresh_valid_plan"
    ]
    matched_stale = [
        row for row in matched_prior
        if row["profile"] == "combined_stale_deviated"
    ]
    matched_tv = np.asarray(
        [row["tv_adaptive_fixed"] for row in matched_prior], dtype=float
    )
    matched_argmax = np.asarray(
        [
            int(row["adaptive_argmax"] != row["fixed_argmax"])
            for row in matched_prior
        ],
        dtype=float,
    )
    matched_argmax_unguided = np.asarray(
        [
            int(row["adaptive_argmax"] != row["unguided_argmax"])
            for row in matched_prior
        ],
        dtype=float,
    )
    fresh = next(
        (row for row in regime_summary if row["regime"] == "FRESH_AND_STABLE"),
        {"median": math.nan},
    )
    stale_below = sum(
        row["regime"] != "FRESH_AND_STABLE"
        and int(row["decision_count"]) > 0
        and float(row["median"]) < float(fresh["median"])
        for row in regime_summary
    )
    gradients = [
        _safe_float(row.get("gate_gradient_l2_norm"))
        for row in update_rows
    ]
    gradient_finite_nonzero = bool(gradients) and all(
        math.isfinite(value) for value in gradients
    ) and any(value > 0 for value in gradients)
    separation = [
        _safe_float(row.get("mean_abs_gate_minus_fixed"))
        for row in evaluation_rows
    ]
    trend = (
        float(np.polyfit(np.arange(len(separation)), separation, 1)[0])
        if len(separation) >= 2
        else 0.0
    )
    invalid = []
    if any(int(row["recommended_action_masked"]) and int(row["prior_nonzero"]) for row in decisions):
        invalid.append("positive_prior_mask_violation")
    if any(int(row.get("regime_label_in_policy_input", 1)) for row in decisions):
        invalid.append("regime_label_entered_policy_input")
    if any(row["feasibility_violations"] for branch in performance.values() for row in [branch]):
        invalid.append("invalid_action_selected")
    if not all(item["passed"] for item in checkpoint_reloads.values()):
        invalid.append("checkpoint_reload_failure")
    adaptive_cost = performance["graph_mappo_adaptive_alns"][
        "mean_true_deprivation_cost"
    ]
    fixed_cost = performance["graph_mappo_fixed_alns"][
        "mean_true_deprivation_cost"
    ]
    adaptive_fill = performance["graph_mappo_adaptive_alns"][
        "mean_fill_rate"
    ]
    fixed_fill = performance["graph_mappo_fixed_alns"]["mean_fill_rate"]
    adaptive_reward = performance["graph_mappo_adaptive_alns"]["mean_reward"]
    fixed_reward = performance["graph_mappo_fixed_alns"]["mean_reward"]
    stability = adaptive_cost <= 1.15 * fixed_cost
    logistics_competitive = all(
        (
            adaptive_cost <= fixed_cost,
            adaptive_fill >= fixed_fill,
            adaptive_reward >= fixed_reward,
        )
    )
    unguided_follow = float(
        np.mean([row["unguided_follows_alns"] for row in prior_rows])
    ) if prior_rows else 0.0
    fixed_follow = float(
        np.mean([row["fixed_follows_alns"] for row in prior_rows])
    ) if prior_rows else 0.0
    adaptive_follow = float(
        np.mean([row["adaptive_follows_alns"] for row in prior_rows])
    ) if prior_rows else 0.0
    matched_fresh_follow = float(
        np.mean([row["adaptive_follows_alns"] for row in matched_fresh])
    ) if matched_fresh else 0.0
    matched_stale_follow = float(
        np.mean([row["adaptive_follows_alns"] for row in matched_stale])
    ) if matched_stale else 0.0
    counts = {
        row["regime"]: int(row["decision_count"]) for row in regime_summary
    }
    limitations = []
    if len(prior_rows) < minimum_prior:
        limitations.append(
            f"prior-bearing validation decisions {len(prior_rows)} "
            f"< required {minimum_prior}"
        )
    for regime, count in counts.items():
        if count < practical_per_regime:
            limitations.append(
                f"{regime} prior-bearing feasible decisions {count} "
                f"< practical target {practical_per_regime}"
            )
    return {
        "decision_count": len(decisions),
        "unique_state_count": len(
            {
                (
                    int(row["scenario_seed"]),
                    int(row["uav_id"]),
                    float(row["decision_time_h"]),
                    int(row["selected_action"]),
                    tuple(float(row[name]) for name in PLAN_FEATURE_NAMES),
                )
                for row in decisions
            }
        ),
        "prior_bearing_decisions": len(prior_rows),
        "prior_coverage": len(prior_rows) / max(len(decisions), 1),
        "gate_mean": float(gates.mean()),
        "gate_standard_deviation": float(gates.std()),
        "gate_minimum": float(gates.min()),
        "gate_maximum": float(gates.max()),
        "mean_abs_gate_minus_fixed": float(np.abs(gates - 0.5).mean()),
        "gate_below_005_fraction": float((gates < 0.05).mean()),
        "gate_above_095_fraction": float((gates > 0.95).mean()),
        "paired_effect": matched_effect["fresh_minus_stale_mean"],
        "paired_ci_low": matched_effect["ci_low"],
        "paired_ci_high": matched_effect["ci_high"],
        "paired_effect_method": matched_effect["uncertainty_method"],
        "paired_effect_source_state_count": matched_effect[
            "source_state_count"
        ],
        "stale_regimes_below_fresh": stale_below,
        "prior_median_adaptive_fixed_tv": (
            float(np.median(prior_tv)) if len(prior_tv) else 0.0
        ),
        "prior_mean_adaptive_fixed_tv": (
            float(prior_tv.mean()) if len(prior_tv) else 0.0
        ),
        "prior_adaptive_fixed_argmax_rate": (
            float(prior_argmax.mean()) if len(prior_argmax) else 0.0
        ),
        "prior_median_adaptive_unguided_tv": (
            float(np.median(prior_tv_unguided))
            if len(prior_tv_unguided)
            else 0.0
        ),
        "prior_mean_adaptive_unguided_tv": (
            float(prior_tv_unguided.mean())
            if len(prior_tv_unguided)
            else 0.0
        ),
        "prior_adaptive_unguided_argmax_rate": (
            float(prior_argmax_unguided.mean())
            if len(prior_argmax_unguided)
            else 0.0
        ),
        "matched_profile_median_adaptive_fixed_tv": (
            float(np.median(matched_tv)) if len(matched_tv) else 0.0
        ),
        "matched_profile_adaptive_fixed_argmax_rate": (
            float(matched_argmax.mean()) if len(matched_argmax) else 0.0
        ),
        "matched_profile_adaptive_unguided_argmax_rate": (
            float(matched_argmax_unguided.mean())
            if len(matched_argmax_unguided)
            else 0.0
        ),
        "matched_fresh_adaptive_follow_rate": matched_fresh_follow,
        "matched_combined_stale_adaptive_follow_rate": matched_stale_follow,
        "matched_fresh_minus_stale_follow_rate": (
            matched_fresh_follow - matched_stale_follow
        ),
        "matched_recommended_probability_saturation_rate": (
            float(
                np.mean(
                    [
                        float(row["alns_action_probability"]) > 0.95
                        for row in matched_prior
                    ]
                )
            )
            if matched_prior
            else 0.0
        ),
        "gate_gradients_finite_nonzero": gradient_finite_nonzero,
        "gate_gradient_median": (
            float(np.median(gradients)) if gradients else 0.0
        ),
        "development_stability_ok": stability,
        "logistics_competitive_with_fixed": logistics_competitive,
        "adaptive_true_deprivation": adaptive_cost,
        "fixed_true_deprivation": fixed_cost,
        "adaptive_fill_rate": adaptive_fill,
        "fixed_fill_rate": fixed_fill,
        "adaptive_reward": adaptive_reward,
        "fixed_reward": fixed_reward,
        "adaptive_fixed_cost_ratio": (
            adaptive_cost / fixed_cost if fixed_cost > 0 else math.inf
        ),
        "actor_absorbs_follow": unguided_follow >= fixed_follow - 0.02,
        "unguided_follow_rate": unguided_follow,
        "fixed_follow_rate": fixed_follow,
        "adaptive_follow_rate": adaptive_follow,
        "gate_separation_trend": trend,
        "episodes_completed": int(
            max(
                [_safe_float(row.get("checkpoint_episode")) for row in evaluation_rows]
                or [0]
            )
        ),
        "regime_prior_counts": counts,
        "sampling_limitations": limitations,
        "invalid_conditions": invalid,
        "solver_feature_exclusion": (
            "solver_active and solver_request_age excluded from primary "
            "direction criteria because synchronous ALNS keeps them constant"
        ),
    }


def _verdict_markdown(verdict, metrics):
    return (
        "# Gate-learning development verdict\n\n"
        f"## {verdict['verdict']}\n\n"
        f"{verdict['rationale']}\n\n"
        "This is methodology-development evidence only and is not a "
        "publication-level superiority claim.\n\n"
        f"- Prior-bearing decisions: {metrics['prior_bearing_decisions']}\n"
        f"- Prior coverage: {metrics['prior_coverage']:.6f}\n"
        f"- Gate standard deviation: {metrics['gate_standard_deviation']:.6f}\n"
        f"- Mean |gate - 0.5|: "
        f"{metrics['mean_abs_gate_minus_fixed']:.6f}\n"
        f"- Exact fresh-minus-stale contrast: "
        f"{metrics['paired_effect']:.6f} "
        f"[{metrics['paired_ci_low']:.6f}, "
        f"{metrics['paired_ci_high']:.6f}]\n"
        f"- Prior-bearing median adaptive/fixed TV: "
        f"{metrics['prior_median_adaptive_fixed_tv']:.6f}\n"
        f"- Prior-bearing adaptive/fixed argmax difference: "
        f"{metrics['prior_adaptive_fixed_argmax_rate']:.6f}\n"
        f"- Matched adaptive/unguided argmax difference: "
        f"{metrics['matched_profile_adaptive_unguided_argmax_rate']:.6f}\n"
        f"- Matched fresh-minus-stale ALNS-follow rate: "
        f"{metrics['matched_fresh_minus_stale_follow_rate']:.6f}\n"
        f"- Guidance beta: {metrics['guidance_beta']:.6f}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results",
        type=Path,
        default=Path("results/gate_learning_development"),
    )
    parser.add_argument("--extension-repeats", type=int, default=1)
    parser.add_argument(
        "--reuse-validation-artifacts",
        action="store_true",
        help=(
            "Reapply current logistics-aware selection to an existing "
            "validation table without replaying the environment."
        ),
    )
    args = parser.parse_args()
    metadata = json.loads(
        (args.results / "metadata.json").read_text(encoding="utf-8")
    )
    if metadata.get("regime_fixture_version") != REGIME_FIXTURE_VERSION:
        raise RuntimeError(
            "Validation results do not use the corrected operational-regime "
            "fixture protocol"
        )
    experiment = yaml.safe_load(
        (args.results / "experiment_config.yaml").read_text(encoding="utf-8")
    )
    if args.reuse_validation_artifacts:
        validation_dir = args.results / "validation"
        metrics_path = validation_dir / "validation_metrics.json"
        metrics_payload = json.loads(
            metrics_path.read_text(encoding="utf-8")
        )
        performance = metrics_payload["performance_by_branch"]
        adaptive = performance["graph_mappo_adaptive_alns"]
        fixed = performance["graph_mappo_fixed_alns"]
        metrics_payload.update(
            {
                "adaptive_true_deprivation": float(
                    adaptive["mean_true_deprivation_cost"]
                ),
                "fixed_true_deprivation": float(
                    fixed["mean_true_deprivation_cost"]
                ),
                "adaptive_fill_rate": float(adaptive["mean_fill_rate"]),
                "fixed_fill_rate": float(fixed["mean_fill_rate"]),
                "adaptive_reward": float(adaptive["mean_reward"]),
                "fixed_reward": float(fixed["mean_reward"]),
                "logistics_competitive_with_fixed": all(
                    (
                        float(adaptive["mean_true_deprivation_cost"])
                        <= float(fixed["mean_true_deprivation_cost"]),
                        float(adaptive["mean_fill_rate"])
                        >= float(fixed["mean_fill_rate"]),
                        float(adaptive["mean_reward"])
                        >= float(fixed["mean_reward"]),
                    )
                ),
            }
        )
        verdict = select_gate_learning_verdict(metrics_payload)
        previous_verdict = json.loads(
            (args.results / "gate_learning_verdict.json").read_text(
                encoding="utf-8"
            )
        )
        targets = dict(previous_verdict.get("development_targets", {}))
        targets["no_catastrophic_collapse"] = bool(
            metrics_payload["development_stability_ok"]
        )
        targets["logistics_competitive_with_fixed_guidance"] = bool(
            metrics_payload["logistics_competitive_with_fixed"]
        )
        verdict_payload = {
            **verdict,
            "development_targets": targets,
            "validation_metrics": {
                key: value
                for key, value in metrics_payload.items()
                if key not in {
                    "performance_by_branch",
                    "checkpoint_reload_verification",
                    "matched_effect",
                }
            },
        }
        _write_json(metrics_path, metrics_payload)
        _write_json(
            args.results / "gate_learning_verdict.json",
            verdict_payload,
        )
        (args.results / "gate_learning_verdict.md").write_text(
            _verdict_markdown(verdict, metrics_payload),
            encoding="utf-8",
        )
        report_path = args.results / "reproducibility_report.json"
        if report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            for path in (
                metrics_path,
                args.results / "gate_learning_verdict.json",
                args.results / "gate_learning_verdict.md",
            ):
                relative = str(path.relative_to(args.results)).replace(
                    "\\", "/"
                )
                report["canonical_files"][relative] = file_sha256(path)
            _write_json(report_path, report)
        print(json.dumps(verdict_payload, indent=2, sort_keys=True))
        print("reused existing validation trajectories; no replay performed")
        return 0
    analysis = experiment["analysis"]
    params, env, agents, checkpoint_reloads = _load_agents(
        args.results, metadata, experiment
    )
    master_seed = int(metadata["master_seed"])
    torch.use_deterministic_algorithms(True)

    performance_rows = []
    adaptive_decisions = []
    adaptive_vectors = []
    for branch, agent in agents.items():
        agent.set_eval()
        metrics, decisions, vectors = _collect_validation(
            env=env,
            agent=agent,
            branch=branch,
            params=params,
            deterministic=True,
            extension_repeats=(
                args.extension_repeats
                if branch == "graph_mappo_adaptive_alns"
                else 0
            ),
            master_seed=master_seed,
            collect_decisions=(branch == "graph_mappo_adaptive_alns"),
        )
        performance_rows.extend(metrics)
        if branch == "graph_mappo_adaptive_alns":
            adaptive_decisions = decisions
            adaptive_vectors = vectors

    # Qualitative seed is replayed separately and excluded from development
    # validation statistics.
    qualitative_metrics, qualitative_rows, _ = _run_episode(
        env=env,
        scenario=generate_scenario(QUALITATIVE_AUDIT_SEED, params),
        agent=agents["graph_mappo_adaptive_alns"],
        branch="graph_mappo_adaptive_alns",
        phase="qualitative_audit",
        episode=1,
        checkpoint_episode=0,
        target_regime="QUALITATIVE_AUDIT_ONLY",
        train=False,
        deterministic=True,
        collect_vectors=False,
        decision_start=0,
    )
    _write_json(
        args.results / "validation" / "qualitative_seed_18427.json",
        {
            "seed": QUALITATIVE_AUDIT_SEED,
            "excluded_from_development_metrics": True,
            "episode_metrics": qualitative_metrics,
            "decision_count": len(qualitative_rows),
        },
    )

    signatures = set()
    dedup_decisions = []
    dedup_vectors = []
    for row, vector in zip(adaptive_decisions, adaptive_vectors):
        signature = _unique_state_signature(vector)
        if signature in signatures:
            continue
        signatures.add(signature)
        dedup_decisions.append(row)
        dedup_vectors.append(vector)
    adaptive_decisions = dedup_decisions
    adaptive_vectors = dedup_vectors
    minimum_training_fresh = int(
        experiment["gate_training"][
            "minimum_fresh_prior_bearing_training_decisions"
        ]
    )
    minimum_validation_fresh = int(
        experiment["gate_training"][
            "minimum_fresh_prior_bearing_validation_decisions"
        ]
    )
    adaptive_training_rows = [
        row
        for row in _read_csv(
            args.results / "adaptive_guidance" / "decision_log.csv"
        )
        if row.get("phase") == "training"
    ]
    assert_regime_coverage(
        adaptive_training_rows,
        {"FRESH_AND_STABLE": minimum_training_fresh},
        phase="adaptive training recheck",
    )
    assert_regime_coverage(
        adaptive_decisions,
        {
            "FRESH_AND_STABLE": minimum_validation_fresh,
            **{regime: 1 for regime in REGIMES[1:]},
        },
        phase="final validation",
    )
    for row in adaptive_decisions:
        assert_truth_exclusion(row)
    for vector in adaptive_vectors:
        assert_truth_exclusion(vector)

    regime_summary = regime_gate_summary(adaptive_decisions)
    relationships = feature_relationship_rows(adaptive_decisions)
    counterfactuals = _counterfactual_rows(
        adaptive_decisions,
        adaptive_vectors,
        guidance_beta=float(metadata["beta"]),
        fixed_gate=float(metadata["fixed_gate"]),
    )
    max_states = int(analysis["maximum_matched_states"])
    matched_rows, matched_vectors = evaluate_matched_states(
        agents["graph_mappo_adaptive_alns"].actor,
        adaptive_vectors,
        max_states=max_states,
    )
    matched_effect = paired_fresh_stale_effect(matched_rows)
    performance = _performance_summary(performance_rows)
    update_rows = _read_csv(
        args.results / "adaptive_guidance" / "gate_update_log.csv"
    )
    evaluation_rows = _read_csv(
        args.results / "adaptive_guidance" / "evaluation_log.csv"
    )
    validation_metrics = _validation_metrics(
        decisions=adaptive_decisions,
        counterfactuals=counterfactuals,
        matched_effect=matched_effect,
        matched_rows=matched_rows,
        regime_summary=regime_summary,
        performance=performance,
        update_rows=update_rows,
        evaluation_rows=evaluation_rows,
        checkpoint_reloads=checkpoint_reloads,
        minimum_prior=int(
            analysis["minimum_prior_bearing_validation_decisions"]
        ),
        practical_per_regime=int(analysis["practical_minimum_per_regime"]),
    )
    validation_metrics["planned_episodes"] = int(
        metadata["planned_episodes_per_branch"]
    )
    validation_metrics["guidance_beta"] = float(metadata["beta"])
    verdict = select_gate_learning_verdict(validation_metrics)
    verdict_payload = {
        **verdict,
        "development_targets": {
            "prior_coverage_at_least_0_30": (
                validation_metrics["prior_coverage"] >= 0.30
            ),
            "prior_decisions_at_least_1000": (
                validation_metrics["prior_bearing_decisions"] >= 1000
            ),
            "material_gate_variation": (
                validation_metrics["gate_standard_deviation"] >= 0.03
                or validation_metrics["mean_abs_gate_minus_fixed"] >= 0.03
            ),
            "paired_effect_at_least_0_05_ci_positive": (
                validation_metrics["paired_effect"] >= 0.05
                and validation_metrics["paired_ci_low"] > 0.0
            ),
            "three_stale_regimes_below_fresh": (
                validation_metrics["stale_regimes_below_fresh"] >= 3
            ),
            "measurable_policy_difference": (
                validation_metrics["prior_median_adaptive_fixed_tv"] >= 0.003
                or validation_metrics[
                    "prior_adaptive_fixed_argmax_rate"
                ]
                >= 0.01
            ),
            "finite_nonzero_gate_gradients": validation_metrics[
                "gate_gradients_finite_nonzero"
            ],
            "truth_mask_observation_checks": not validation_metrics[
                "invalid_conditions"
            ],
            "no_catastrophic_collapse": validation_metrics[
                "development_stability_ok"
            ],
            "logistics_competitive_with_fixed_guidance": validation_metrics[
                "logistics_competitive_with_fixed"
            ],
        },
        "validation_metrics": validation_metrics,
    }

    validation_dir = args.results / "validation"
    _write_csv(
        validation_dir / "regime_decisions.csv",
        adaptive_decisions,
    )
    _write_csv(
        validation_dir / "regime_gate_summary.csv",
        regime_summary,
    )
    _write_json(
        validation_dir / "regime_gate_summary.json",
        regime_summary,
    )
    _write_csv(validation_dir / "matched_state_pairs.csv", matched_rows)
    _write_gzip_jsonl(
        validation_dir / "matched_state_vectors.jsonl.gz",
        matched_vectors,
    )
    _write_csv(
        validation_dir / "counterfactual_policy_comparison.csv",
        counterfactuals,
    )
    _write_csv(
        validation_dir / "feature_relationships.csv",
        relationships,
    )
    _write_csv(
        validation_dir / "development_objective_metrics.csv",
        performance_rows,
    )
    _write_json(
        validation_dir / "validation_metrics.json",
        {
            **validation_metrics,
            "matched_effect": matched_effect,
            "performance_by_branch": performance,
            "checkpoint_reload_verification": checkpoint_reloads,
            "truth_exclusion": "passed",
            "observation_feature_order": list(PLAN_FEATURE_NAMES),
            "primary_expected_direction_features": list(PRIMARY_FEATURES),
        },
    )
    _write_json(args.results / "gate_learning_verdict.json", verdict_payload)
    (args.results / "gate_learning_verdict.md").write_text(
        _verdict_markdown(verdict, validation_metrics),
        encoding="utf-8",
    )

    canonical = [
        args.results / "seed_split.json",
        args.results / "episode_scenario_assignments.csv",
        validation_dir / "regime_decisions.csv",
        validation_dir / "regime_gate_summary.csv",
        validation_dir / "regime_gate_summary.json",
        validation_dir / "matched_state_pairs.csv",
        validation_dir / "matched_state_vectors.jsonl.gz",
        validation_dir / "counterfactual_policy_comparison.csv",
        validation_dir / "feature_relationships.csv",
        validation_dir / "validation_metrics.json",
        args.results / "gate_learning_verdict.json",
        args.results / "gate_learning_verdict.md",
    ]
    _write_json(
        args.results / "reproducibility_report.json",
        {
            "canonical_files": {
                str(path.relative_to(args.results)).replace("\\", "/"): (
                    file_sha256(path)
                )
                for path in canonical
            },
            "noncanonical_timing_fields": [
                "computational_time_s",
            ],
            "checkpoint_hashes": {
                mode: payload["checkpoint_sha256"]
                for mode, payload in checkpoint_reloads.items()
            },
        },
    )
    print(json.dumps(verdict_payload, indent=2, sort_keys=True))
    print(f"validation outputs -> {validation_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
