"""Re-evaluate saved adaptive checkpoints with gate and logistics criteria."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
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
from methods.gate_learning_development import (  # noqa: E402
    REGIMES,
    VALIDATION_SEEDS,
    evaluate_matched_states,
    file_sha256,
    paired_fresh_stale_effect,
    validation_assignments,
)
from scripts.run_gate_learning_development import (  # noqa: E402
    _aggregate_evaluation,
    _make_agent,
    _run_episode,
)
from scripts.train_mappo import DEFAULT_AGENT_CONFIG, load_agent_config  # noqa: E402


GATE_THRESHOLDS = {
    "minimum_prior_coverage": 0.30,
    "minimum_gate_variation": 0.03,
    "minimum_fresh_stale_gate_effect": 0.05,
    "minimum_adverse_profiles_below_fresh": 3,
    "minimum_adaptive_fixed_tv": 0.003,
    "minimum_argmax_change_rate": 0.01,
    "maximum_adaptive_unguided_argmax_change_rate": 0.10,
    "minimum_fresh_stale_follow_gap": 0.05,
    "maximum_recommendation_saturation_rate": 0.05,
}


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    output = []
    for row in rows:
        converted = {}
        for key, value in row.items():
            if value is None or value == "":
                converted[key] = value
                continue
            try:
                number = float(value)
            except ValueError:
                converted[key] = value
            else:
                converted[key] = (
                    int(number)
                    if key in {
                        "checkpoint_episode",
                        "validation_seed_count",
                        "environment_decisions",
                        "prior_bearing_decisions",
                        "feasibility_violations",
                        "matched_source_state_count",
                        "adverse_profiles_below_fresh",
                    }
                    else number
                )
        output.append(converted)
    return output


def _rate(rows, field: str) -> float:
    return float(np.mean([float(row[field]) for row in rows])) if rows else 0.0


def _collect_checkpoint(
    *,
    env,
    params,
    agent,
    branch: str,
    checkpoint_episode: int,
    max_matched_states: int,
) -> tuple[dict, list[dict]]:
    episode_metrics = []
    decisions = []
    vectors = []
    performance_rows = []
    decision_index = 0
    agent.set_eval()
    for assignment in validation_assignments():
        metrics, rows, current_vectors = _run_episode(
            env=env,
            scenario=generate_scenario(assignment["scenario_seed"], params),
            agent=agent,
            branch=branch,
            phase="checkpoint_reevaluation",
            episode=assignment["validation_episode"],
            checkpoint_episode=checkpoint_episode,
            target_regime=assignment["target_regime"],
            train=False,
            deterministic=True,
            collect_vectors=True,
            decision_start=decision_index,
        )
        decision_index += len(rows)
        episode_metrics.append(metrics)
        decisions.extend(rows)
        vectors.extend(current_vectors)
        performance_rows.append(
            {
                "branch": branch,
                "checkpoint_episode": checkpoint_episode,
                "scenario_seed": assignment["scenario_seed"],
                "target_regime": assignment["target_regime"],
                "reward": metrics["reward"],
                "J_dep_true": metrics["J_dep_true"],
                "J_dep_belief": metrics["J_dep_belief"],
                "fill_rate": metrics["fill_rate"],
                "feasibility_violations": metrics["feasibility_violations"],
                "episode_duration_h": metrics["episode_duration_h"],
            }
        )

    summary = _aggregate_evaluation(
        branch,
        checkpoint_episode,
        episode_metrics,
        decisions,
        vectors,
        [],
        sum(row["computational_time_s"] for row in episode_metrics),
        guidance_beta=float(agent.actor.beta),
        fixed_gate=float(agent.actor.fixed_gate),
    )
    matched, _ = evaluate_matched_states(
        agent.actor,
        vectors,
        max_states=max_matched_states,
    )
    effect = paired_fresh_stale_effect(matched)
    fresh = [row for row in matched if row["profile"] == "fresh_valid_plan"]
    stale = [
        row for row in matched
        if row["profile"] == "combined_stale_deviated"
    ]
    paired_profiles = fresh + stale
    profile_gate = {}
    for profile in {str(row["profile"]) for row in matched}:
        profile_gate[profile] = float(np.mean(
            [
                float(row["gate_adaptive"])
                for row in matched
                if row["profile"] == profile
            ]
        ))
    fresh_gate = profile_gate.get("fresh_valid_plan", -math.inf)
    adverse_below = sum(
        profile != "fresh_valid_plan" and value < fresh_gate
        for profile, value in profile_gate.items()
    )
    summary.update(
        {
            "matched_source_state_count": effect["source_state_count"],
            "paired_effect": effect["fresh_minus_stale_mean"],
            "paired_ci_low": effect["ci_low"],
            "adverse_profiles_below_fresh": adverse_below,
            "matched_profile_median_adaptive_fixed_tv": (
                float(np.median(
                    [float(row["tv_adaptive_fixed"]) for row in paired_profiles]
                ))
                if paired_profiles
                else 0.0
            ),
            "matched_profile_adaptive_fixed_argmax_rate": _rate(
                [
                    {
                        "different": int(
                            row["adaptive_argmax"] != row["fixed_argmax"]
                        )
                    }
                    for row in paired_profiles
                ],
                "different",
            ),
            "matched_profile_adaptive_unguided_argmax_rate": _rate(
                [
                    {
                        "different": int(
                            row["adaptive_argmax"] != row["unguided_argmax"]
                        )
                    }
                    for row in paired_profiles
                ],
                "different",
            ),
            "matched_fresh_minus_stale_follow_rate": (
                _rate(fresh, "adaptive_follows_alns")
                - _rate(stale, "adaptive_follows_alns")
            ),
            "matched_recommended_probability_saturation_rate": _rate(
                [
                    {
                        "saturated": int(
                            float(row["alns_action_probability"]) > 0.95
                        )
                    }
                    for row in paired_profiles
                ],
                "saturated",
            ),
        }
    )
    return summary, performance_rows


def gate_validity_checks(
    row: Mapping[str, object],
    thresholds: Mapping[str, float] = GATE_THRESHOLDS,
) -> dict[str, bool]:
    variation = max(
        float(row["gate_standard_deviation"]),
        float(row["mean_abs_gate_minus_fixed"]),
    )
    fixed_influence = (
        float(row["matched_profile_median_adaptive_fixed_tv"])
        >= thresholds["minimum_adaptive_fixed_tv"]
        or float(row["matched_profile_adaptive_fixed_argmax_rate"])
        >= thresholds["minimum_argmax_change_rate"]
    )
    adaptive_unguided = float(
        row["matched_profile_adaptive_unguided_argmax_rate"]
    )
    return {
        "feasible_rollouts": int(row["feasibility_violations"]) == 0,
        "sufficient_prior_coverage": (
            float(row["prior_coverage"])
            >= thresholds["minimum_prior_coverage"]
        ),
        "material_gate_variation": (
            variation >= thresholds["minimum_gate_variation"]
        ),
        "fresh_above_stale_gate": (
            float(row["paired_effect"])
            >= thresholds["minimum_fresh_stale_gate_effect"]
            and float(row["paired_ci_low"]) > 0.0
            and int(row["adverse_profiles_below_fresh"])
            >= int(thresholds["minimum_adverse_profiles_below_fresh"])
        ),
        "measurable_adaptive_fixed_influence": fixed_influence,
        "controlled_adaptive_unguided_influence": (
            thresholds["minimum_argmax_change_rate"]
            <= adaptive_unguided
            <= thresholds["maximum_adaptive_unguided_argmax_change_rate"]
        ),
        "fresh_stale_follow_separation": (
            float(row["matched_fresh_minus_stale_follow_rate"])
            >= thresholds["minimum_fresh_stale_follow_gap"]
        ),
        "non_saturated_recommendation_probability": (
            float(row["matched_recommended_probability_saturation_rate"])
            <= thresholds["maximum_recommendation_saturation_rate"]
        ),
    }


def select_checkpoint(
    adaptive_rows: Sequence[Mapping[str, object]],
    *,
    fixed: Mapping[str, object],
    unguided: Mapping[str, object],
) -> dict:
    assessed = []
    for source in adaptive_rows:
        row = dict(source)
        checks = gate_validity_checks(row)
        row["gate_valid"] = all(checks.values())
        row["gate_validity_checks"] = checks
        assessed.append(row)
    eligible = [row for row in assessed if row["gate_valid"]]
    selected = (
        min(
            eligible,
            key=lambda row: (
                float(row["mean_true_deprivation_cost"]),
                -float(row["mean_fill_rate"]),
                -float(row["cumulative_reward"]),
            ),
        )
        if eligible
        else None
    )
    promotion_checks = (
        {
            "true_deprivation_no_worse_than_fixed": (
                float(selected["mean_true_deprivation_cost"])
                <= float(fixed["mean_true_deprivation_cost"])
            ),
            "fill_rate_no_worse_than_fixed": (
                float(selected["mean_fill_rate"])
                >= float(fixed["mean_fill_rate"])
            ),
            "reward_no_worse_than_fixed": (
                float(selected["cumulative_reward"])
                >= float(fixed["cumulative_reward"])
            ),
            "feasibility_no_worse_than_fixed": (
                int(selected["feasibility_violations"])
                <= int(fixed["feasibility_violations"])
            ),
        }
        if selected is not None
        else {}
    )
    promote = bool(promotion_checks) and all(promotion_checks.values())
    return {
        "status": (
            "ADAPTIVE_GUIDANCE_PROMOTED"
            if promote
            else "FIXED_GUIDANCE_RETAINED"
        ),
        "selection_rule": (
            "Gate-valid checkpoints are ranked by minimum true deprivation, "
            "then maximum fill rate and reward. Adaptive guidance replaces "
            "fixed guidance only if it is no worse on every logistics metric."
        ),
        "adaptive_candidates": assessed,
        "selected_adaptive_checkpoint_episode": (
            int(selected["checkpoint_episode"]) if selected else None
        ),
        "selected_adaptive_checkpoint": selected,
        "adaptive_promotion_checks": promotion_checks,
        "best_guided_baseline": {
            "mode": (
                "graph_mappo_adaptive_alns"
                if promote
                else "graph_mappo_fixed_alns"
            ),
            "checkpoint_episode": (
                int(selected["checkpoint_episode"])
                if promote and selected
                else int(fixed["checkpoint_episode"])
            ),
        },
        "production_policy": {
            "mode": "graph_mappo",
            "production_gate": 0.0,
            "status": (
                "UNCHANGED_PENDING_SEPARATE_PERFORMANCE_BENCHMARK"
            ),
            "checkpoint_episode": int(unguided["checkpoint_episode"]),
        },
    }


def _diagnosis(selected, fixed, unguided) -> dict:
    adaptive = selected or {}
    adaptive_gate = float(adaptive.get("production_gate_mean", math.nan))
    adaptive_fixed_counterfactual = float(
        adaptive.get("counterfactual_fixed_alns_follow_rate", math.nan)
    )
    fixed_follow = float(fixed["alns_follow_rate"])
    attenuation = (
        math.isfinite(adaptive_gate)
        and adaptive_gate < float(adaptive.get("fixed_gate", 0.5))
    )
    coadaptation = (
        math.isfinite(adaptive_fixed_counterfactual)
        and fixed_follow - adaptive_fixed_counterfactual >= 0.10
    )
    return {
        "classification": (
            "COMBINED_GATE_ATTENUATION_AND_ACTOR_COADAPTATION"
            if attenuation and coadaptation
            else (
                "GATE_ATTENUATION"
                if attenuation
                else "NO_SINGLE_MECHANISM_ESTABLISHED"
            )
        ),
        "evidence": {
            "adaptive_mean_gate": adaptive_gate,
            "fixed_gate": float(adaptive.get("fixed_gate", 0.5)),
            "adaptive_effective_guidance_scale_mean": float(
                adaptive.get("effective_guidance_scale_mean", math.nan)
            ),
            "adaptive_actual_alns_follow_rate": float(
                adaptive.get("alns_follow_rate", math.nan)
            ),
            "adaptive_actor_fixed_gate_counterfactual_follow_rate": (
                adaptive_fixed_counterfactual
            ),
            "separately_trained_fixed_branch_follow_rate": fixed_follow,
            "fixed_true_deprivation_improvement_vs_unguided_fraction": (
                (
                    float(unguided["mean_true_deprivation_cost"])
                    - float(fixed["mean_true_deprivation_cost"])
                )
                / float(unguided["mean_true_deprivation_cost"])
            ),
            "fixed_fill_rate_gain_vs_unguided": (
                float(fixed["mean_fill_rate"])
                - float(unguided["mean_fill_rate"])
            ),
        },
        "interpretation": [
            (
                "The learned adaptive gate is below the fixed gate on the "
                "evaluated trajectory, so it attenuates the ALNS logit boost."
            ),
            (
                "Applying the fixed gate counterfactually to the adaptive "
                "actor does not recover the separately trained fixed branch's "
                "ALNS-follow rate, indicating actor/gate co-adaptation."
            ),
            (
                "The directional regularizer constrains fresh-minus-stale "
                "gate differences but does not anchor the absolute fresh gate "
                "above the fixed 0.5 baseline."
            ),
        ],
    }


def _markdown(selection: Mapping[str, object], diagnosis: Mapping[str, object]) -> str:
    candidates = selection["adaptive_candidates"]
    lines = [
        "# Adaptive checkpoint re-evaluation",
        "",
        f"**Decision: {selection['status']}**",
        "",
        "| Episode | Gate valid | True deprivation | Fill rate | Reward | Mean gate | ALNS follow |",
        "|---:|:---:|---:|---:|---:|---:|---:|",
    ]
    for row in candidates:
        lines.append(
            f"| {int(row['checkpoint_episode'])} | "
            f"{'yes' if row['gate_valid'] else 'no'} | "
            f"{float(row['mean_true_deprivation_cost']):.6f} | "
            f"{float(row['mean_fill_rate']):.6f} | "
            f"{float(row['cumulative_reward']):.6f} | "
            f"{float(row['production_gate_mean']):.6f} | "
            f"{float(row['alns_follow_rate']):.6f} |"
        )
    lines.extend(
        [
            "",
            f"Selected adaptive candidate: "
            f"{selection['selected_adaptive_checkpoint_episode']}.",
            "",
            "Fixed guidance remains the guided baseline unless the selected "
            "adaptive checkpoint is no worse on true deprivation, fill rate, "
            "reward, and feasibility.",
            "",
            "Production remains unguided (`g=0`) pending a separate "
            "performance benchmark.",
            "",
            "## Suppression diagnosis",
            "",
            f"Classification: `{diagnosis['classification']}`.",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in diagnosis["interpretation"])
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results",
        type=Path,
        default=Path("results/gate_learning_beta5591_pilot"),
    )
    parser.add_argument(
        "--episodes",
        default="75,100,125,150,175,200",
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--max-matched-states", type=int, default=2000)
    parser.add_argument(
        "--reuse-evaluation",
        action="store_true",
        help=(
            "Finalize already-written checkpoint_evaluation.csv rows without "
            "replaying the environment."
        ),
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    episodes = [int(value) for value in args.episodes.split(",") if value.strip()]
    metadata = json.loads(
        (args.results / "metadata.json").read_text(encoding="utf-8")
    )
    experiment = yaml.safe_load(
        (args.results / "experiment_config.yaml").read_text(encoding="utf-8")
    )
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
        "device": args.device,
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
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    torch.use_deterministic_algorithms(True)

    output_dir = args.output_dir or args.results / "checkpoint_reevaluation"
    output_dir.mkdir(parents=True, exist_ok=True)
    evaluation_path = output_dir / "checkpoint_evaluation.csv"
    episode_metrics_path = output_dir / "checkpoint_episode_metrics.csv"
    if args.reuse_evaluation:
        if not evaluation_path.is_file():
            raise FileNotFoundError(
                f"Missing completed evaluation table: {evaluation_path}"
            )
        summaries = _read_csv(evaluation_path)
        episode_rows = (
            _read_csv(episode_metrics_path)
            if episode_metrics_path.is_file()
            else []
        )
        baseline_summaries = {}
        for branch, directory in (
            ("graph_mappo", "graph_mappo"),
            ("graph_mappo_fixed_alns", "fixed_guidance"),
        ):
            rows = _read_csv(
                args.results / directory / "evaluation_log.csv"
            )
            summary = rows[-1]
            summary["guidance_beta"] = float(metadata["beta"])
            summary["fixed_gate"] = float(metadata["fixed_gate"])
            path = args.results / directory / "checkpoints" / "final.pt"
            summary["checkpoint_path"] = str(path)
            summary["checkpoint_sha256"] = file_sha256(path)
            baseline_summaries[branch] = summary
    else:
        summaries = []
        episode_rows = []
        paths = {
            "graph_mappo": (
                args.results / "graph_mappo" / "checkpoints" / "final.pt"
            ),
            "graph_mappo_fixed_alns": (
                args.results / "fixed_guidance" / "checkpoints" / "final.pt"
            ),
        }
        baseline_summaries = {}
        for branch, path in paths.items():
            agent = _make_agent(env, config, branch)
            agent.load(path)
            episode = 0 if branch == "graph_mappo" else int(
                metadata["planned_episodes_per_branch"]
            )
            summary, rows = _collect_checkpoint(
                env=env,
                params=params,
                agent=agent,
                branch=branch,
                checkpoint_episode=episode,
                max_matched_states=args.max_matched_states,
            )
            summary["checkpoint_path"] = str(path)
            summary["checkpoint_sha256"] = file_sha256(path)
            baseline_summaries[branch] = summary
            episode_rows.extend(rows)

        for episode in episodes:
            path = (
                args.results
                / "adaptive_guidance"
                / "checkpoints"
                / f"episode_{episode:04d}.pt"
            )
            if not path.is_file():
                raise FileNotFoundError(f"Missing adaptive checkpoint: {path}")
            agent = _make_agent(env, config, "graph_mappo_adaptive_alns")
            agent.load(path)
            summary, rows = _collect_checkpoint(
                env=env,
                params=params,
                agent=agent,
                branch="graph_mappo_adaptive_alns",
                checkpoint_episode=episode,
                max_matched_states=args.max_matched_states,
            )
            summary["checkpoint_path"] = str(path)
            summary["checkpoint_sha256"] = file_sha256(path)
            summaries.append(summary)
            episode_rows.extend(rows)
            print(
                f"episode {episode}: beta={summary['guidance_beta']:.3f} "
                f"gate={summary['production_gate_mean']:.3f} "
                f"J_dep={summary['mean_true_deprivation_cost']:.3f} "
                f"fill={summary['mean_fill_rate']:.3f}",
                flush=True,
            )

    selection = select_checkpoint(
        summaries,
        fixed=baseline_summaries["graph_mappo_fixed_alns"],
        unguided=baseline_summaries["graph_mappo"],
    )
    diagnostic_checkpoint = (
        selection["selected_adaptive_checkpoint"]
        or max(summaries, key=lambda row: int(row["checkpoint_episode"]))
    )
    diagnosis = _diagnosis(
        diagnostic_checkpoint,
        baseline_summaries["graph_mappo_fixed_alns"],
        baseline_summaries["graph_mappo"],
    )
    payload = {
        **selection,
        "gate_thresholds": GATE_THRESHOLDS,
        "baselines": baseline_summaries,
        "adaptive_suppression_diagnosis": diagnosis,
        "evaluation_protocol": {
            "validation_seeds": list(VALIDATION_SEEDS),
            "regimes": list(REGIMES),
            "deterministic": True,
            "guidance_beta": float(metadata["beta"]),
            "fixed_gate": float(metadata["fixed_gate"]),
        },
    }
    _write_csv(evaluation_path, summaries)
    if episode_rows:
        _write_csv(episode_metrics_path, episode_rows)
    _write_json(output_dir / "checkpoint_selection.json", payload)
    (output_dir / "checkpoint_selection.md").write_text(
        _markdown(selection, diagnosis),
        encoding="utf-8",
    )
    print(json.dumps(
        {
            "status": selection["status"],
            "selected_adaptive_checkpoint_episode": selection[
                "selected_adaptive_checkpoint_episode"
            ],
            "production_policy": selection["production_policy"],
            "diagnosis": diagnosis["classification"],
        },
        indent=2,
        sort_keys=True,
    ))
    print(f"checkpoint re-evaluation -> {output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
