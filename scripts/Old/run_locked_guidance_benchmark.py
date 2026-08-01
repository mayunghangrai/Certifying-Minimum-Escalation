"""Run the locked final benchmark of fixed guidance versus unguided MAPPO.

The protocol has two deliberately separate phases:

1. ``--prepare`` verifies that the requested seeds are absent from all prior
   repository text artifacts, hashes the two frozen checkpoints, records
   scenario hashes, and writes an immutable predeclaration lock.
2. ``--run`` verifies that lock and the checkpoint hashes before evaluating
   either policy. Evaluation is paired, deterministic, resumable, and never
   loads the rejected adaptive checkpoint.
"""

from __future__ import annotations

import argparse
import copy
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from typing import Mapping, Sequence

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from env.params import EnvParams  # noqa: E402
from env.scenario_generator import generate_scenario  # noqa: E402
from env.uav_env import UAMTVRPIUEnv  # noqa: E402
from methods.gate_learning_development import file_sha256  # noqa: E402
from scripts.run_gate_learning_development import (  # noqa: E402
    _make_agent,
    _run_episode,
)
from scripts.train_mappo import DEFAULT_AGENT_CONFIG, load_agent_config  # noqa: E402


PROTOCOL_VERSION = "locked-fixed-vs-unguided-v1"
POLICIES = ("unguided_graph_mappo", "fixed_guidance")
PRIMARY_METRIC = "J_dep_true"
PROMOTION_RULE = {
    "minimum_mean_deprivation_reduction_fraction": 0.05,
    "paired_confidence_level": 0.95,
    "paired_bootstrap_samples": 10000,
    "paired_bootstrap_seed": 94173,
    "require_paired_ci_lower_bound_above_zero": True,
    "require_fixed_mean_fill_rate_at_least_unguided": True,
    "require_no_additional_feasibility_violations": True,
    "minimum_positive_seed_fraction": 0.60,
    "largest_improvements_removed_for_robustness": 2,
    "require_positive_mean_after_removing_largest_improvements": True,
}
TEXT_EXTENSIONS = {
    ".csv",
    ".json",
    ".log",
    ".md",
    ".py",
    ".tex",
    ".txt",
    ".yaml",
    ".yml",
}
SKIP_DIRECTORIES = {
    ".git",
    ".pytest_cache",
    "__pycache__",
}
EPISODE_FIELDS = (
    "policy",
    "seed",
    "scenario_sha256",
    "checkpoint_sha256",
    "production_gate",
    "guidance_beta",
    "reward",
    "J_dep_true",
    "J_dep_belief",
    "fill_rate",
    "feasibility_violations",
    "mission_completed",
    "termination_reason",
    "environment_steps",
    "episode_duration_h",
    "computational_time_s",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_json_bytes(payload))


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    fields: Sequence[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved = list(fields or dict.fromkeys(
        key for row in rows for key in row
    ))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=resolved,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def _append_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    fields: Sequence[str],
) -> None:
    exists = path.is_file() and path.stat().st_size > 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore",
        )
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _sha256_payload(payload: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _assert_empty_output(output_dir: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"{output_dir} is not empty; the locked benchmark cannot be "
            "prepared over existing artifacts"
        )


def _seed_references(
    repository_root: Path,
    seeds: Sequence[int],
    excluded_root: Path,
) -> dict[int, list[str]]:
    patterns = {
        seed: re.compile(rf"(?<!\d){seed}(?!\d)")
        for seed in seeds
    }
    references = {seed: [] for seed in seeds}
    excluded = excluded_root.resolve()
    for path in repository_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        if any(part in SKIP_DIRECTORIES for part in path.parts):
            continue
        try:
            resolved = path.resolve()
            resolved.relative_to(excluded)
            continue
        except ValueError:
            pass
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for seed, pattern in patterns.items():
            if pattern.search(text):
                references[seed].append(
                    str(path.relative_to(repository_root)).replace("\\", "/")
                )
    return {
        seed: paths for seed, paths in references.items() if paths
    }


def paired_bootstrap_interval(
    values: Sequence[float],
    *,
    confidence: float,
    samples: int,
    seed: int,
) -> dict[str, float]:
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or not len(array):
        raise ValueError("paired bootstrap requires a nonempty vector")
    rng = np.random.default_rng(seed)
    draw_indices = rng.integers(
        0,
        len(array),
        size=(samples, len(array)),
    )
    means = array[draw_indices].mean(axis=1)
    tail = (1.0 - confidence) / 2.0
    return {
        "mean": float(array.mean()),
        "ci_low": float(np.quantile(means, tail)),
        "ci_high": float(np.quantile(means, 1.0 - tail)),
        "confidence_level": float(confidence),
        "method": "paired_percentile_bootstrap",
        "bootstrap_samples": int(samples),
        "bootstrap_seed": int(seed),
    }


def promotion_decision(
    paired_rows: Sequence[Mapping[str, object]],
    *,
    rule: Mapping[str, object] = PROMOTION_RULE,
) -> dict:
    unguided_dep = np.asarray(
        [float(row["unguided_J_dep_true"]) for row in paired_rows]
    )
    fixed_dep = np.asarray(
        [float(row["fixed_J_dep_true"]) for row in paired_rows]
    )
    reductions = unguided_dep - fixed_dep
    baseline_mean = float(unguided_dep.mean())
    reduction_fraction = (
        float(reductions.mean() / baseline_mean)
        if baseline_mean > 0.0
        else -math.inf
    )
    interval = paired_bootstrap_interval(
        reductions,
        confidence=float(rule["paired_confidence_level"]),
        samples=int(rule["paired_bootstrap_samples"]),
        seed=int(rule["paired_bootstrap_seed"]),
    )
    positive_fraction = float((reductions > 0.0).mean())
    remove_count = int(
        rule["largest_improvements_removed_for_robustness"]
    )
    retained = np.sort(reductions)[: max(len(reductions) - remove_count, 0)]
    trimmed_mean = float(retained.mean()) if len(retained) else -math.inf
    unguided_fill = float(np.mean(
        [float(row["unguided_fill_rate"]) for row in paired_rows]
    ))
    fixed_fill = float(np.mean(
        [float(row["fixed_fill_rate"]) for row in paired_rows]
    ))
    unguided_violations = int(sum(
        int(row["unguided_feasibility_violations"])
        for row in paired_rows
    ))
    fixed_violations = int(sum(
        int(row["fixed_feasibility_violations"])
        for row in paired_rows
    ))
    checks = {
        "mean_deprivation_reduction_at_least_5_percent": (
            reduction_fraction
            >= float(rule["minimum_mean_deprivation_reduction_fraction"])
        ),
        "paired_95_percent_ci_supports_improvement": (
            interval["ci_low"] > 0.0
        ),
        "fill_rate_not_worse": fixed_fill >= unguided_fill,
        "no_additional_feasibility_violations": (
            fixed_violations <= unguided_violations
        ),
        "improvement_seen_on_at_least_60_percent_of_seeds": (
            positive_fraction >= float(rule["minimum_positive_seed_fraction"])
        ),
        "improvement_survives_removing_two_best_seeds": trimmed_mean > 0.0,
    }
    passed = all(checks.values())
    return {
        "decision": (
            "PROMOTE_FIXED_GUIDANCE"
            if passed
            else "RETAIN_UNGUIDED_GRAPH_MAPPO"
        ),
        "production_policy": {
            "mode": (
                "graph_mappo_fixed_alns" if passed else "graph_mappo"
            ),
            "production_gate": 0.5 if passed else 0.0,
            "guidance_beta": 5.591 if passed else 0.0,
        },
        "adaptive_guidance": {
            "status": "REJECTED_EXCLUDED_FROM_PROMOTION",
            "evaluated": False,
        },
        "all_promotion_checks_passed": passed,
        "checks": checks,
        "primary_outcome": {
            "unguided_mean_true_deprivation": baseline_mean,
            "fixed_mean_true_deprivation": float(fixed_dep.mean()),
            "mean_paired_reduction": float(reductions.mean()),
            "mean_reduction_fraction": reduction_fraction,
            "mean_reduction_percent": 100.0 * reduction_fraction,
            "paired_interval": interval,
            "positive_seed_fraction": positive_fraction,
            "mean_reduction_after_removing_two_largest": trimmed_mean,
        },
        "secondary_guardrails": {
            "unguided_mean_fill_rate": unguided_fill,
            "fixed_mean_fill_rate": fixed_fill,
            "unguided_feasibility_violations": unguided_violations,
            "fixed_feasibility_violations": fixed_violations,
        },
        "predeclared_rule": dict(rule),
    }


def _load_context(results: Path, device: str):
    metadata = json.loads(
        (results / "metadata.json").read_text(encoding="utf-8")
    )
    experiment = yaml.safe_load(
        (results / "experiment_config.yaml").read_text(encoding="utf-8")
    )
    runtime = experiment["development_runtime"]
    params = EnvParams()
    params.mission.T = float(runtime["mission_horizon_hours"])
    params.hybrid.alns_iterations = int(runtime["alns_iterations"])
    env = UAMTVRPIUEnv(params)
    loaded, _ = load_agent_config(metadata["agent_config"])
    config = {
        **DEFAULT_AGENT_CONFIG,
        **loaded,
        "gamma_hour": params.mission.gamma_hour,
        "device": device,
        "guidance_beta": float(metadata["beta"]),
        "fixed_guidance_gate": float(metadata["fixed_gate"]),
    }
    return metadata, experiment, params, env, config


def _candidate_paths(results: Path) -> dict[str, Path]:
    return {
        "unguided_graph_mappo": (
            results / "graph_mappo" / "checkpoints" / "final.pt"
        ),
        "fixed_guidance": (
            results / "fixed_guidance" / "checkpoints" / "final.pt"
        ),
    }


def prepare_benchmark(
    *,
    repository_root: Path,
    results: Path,
    output_dir: Path,
    seed_start: int,
    seed_count: int,
    device: str,
) -> dict:
    if not 30 <= seed_count <= 50:
        raise ValueError("locked benchmark requires 30 to 50 seeds")
    if seed_start < 0:
        raise ValueError("seed_start must be nonnegative")
    _assert_empty_output(output_dir)
    seeds = list(range(seed_start, seed_start + seed_count))
    references = _seed_references(repository_root, seeds, output_dir)
    if references:
        raise RuntimeError(
            "Requested benchmark seeds are not untouched: "
            + json.dumps(references, sort_keys=True)
        )
    metadata, experiment, params, _, _ = _load_context(results, device)
    candidates = []
    for name, path in _candidate_paths(results).items():
        if not path.is_file():
            raise FileNotFoundError(f"Missing candidate checkpoint: {path}")
        candidates.append(
            {
                "candidate": name,
                "checkpoint_path": str(path.resolve()),
                "checkpoint_sha256": file_sha256(path),
                "mode": (
                    "graph_mappo"
                    if name == "unguided_graph_mappo"
                    else "graph_mappo_fixed_alns"
                ),
                "production_gate": (
                    0.0 if name == "unguided_graph_mappo" else 0.5
                ),
                "guidance_beta": (
                    0.0
                    if name == "unguided_graph_mappo"
                    else float(metadata["beta"])
                ),
            }
        )
    scenario_rows = []
    for seed in seeds:
        scenario = generate_scenario(seed, params)
        scenario_rows.append(
            {
                "seed": seed,
                "scenario_content_sha256": scenario.content_hash(),
                "prior_repository_references": [],
            }
        )
    protocol = {
        "protocol_version": PROTOCOL_VERSION,
        "created_before_policy_evaluation": True,
        "created_utc": _utc_now(),
        "objective": (
            "locked final paired promotion benchmark of fixed guidance "
            "versus unguided graph-MAPPO"
        ),
        "results_source": str(results.resolve()),
        "seed_count": seed_count,
        "deterministic_action_selection": True,
        "identical_scenario_per_seed_for_both_policies": True,
        "policy_execution_order": (
            "alternates by seed index to reduce order bias in computational "
            "time; pairing and actions are unchanged"
        ),
        "no_tuning_on_benchmark_seeds": True,
        "primary_outcome": "true deprivation cost",
        "secondary_outcomes": [
            "fill rate",
            "reward",
            "feasibility violations",
            "mission completion",
            "computational time",
        ],
        "promotion_rule": PROMOTION_RULE,
        "runtime": experiment["development_runtime"],
        "adaptive_guidance": (
            "rejected; checkpoint is not a benchmark candidate and is never "
            "loaded by this runner"
        ),
        "candidate_count": 2,
        "device_requested": device,
        "benchmark_runner_sha256": file_sha256(Path(__file__)),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = output_dir / "candidate_manifest.json"
    seed_path = output_dir / "seed_manifest.json"
    protocol_path = output_dir / "benchmark_protocol.json"
    _write_json(candidate_path, {"candidates": candidates})
    _write_json(seed_path, {"seeds": scenario_rows})
    _write_json(protocol_path, protocol)
    lock = {
        "protocol_version": PROTOCOL_VERSION,
        "locked_utc": _utc_now(),
        "files": {
            "candidate_manifest.json": file_sha256(candidate_path),
            "seed_manifest.json": file_sha256(seed_path),
            "benchmark_protocol.json": file_sha256(protocol_path),
        },
        "candidate_manifest_payload_sha256": _sha256_payload(
            {"candidates": candidates}
        ),
        "seed_manifest_payload_sha256": _sha256_payload(
            {"seeds": scenario_rows}
        ),
        "evaluation_started_at_lock_creation": False,
    }
    _write_json(output_dir / "benchmark_lock.json", lock)
    return {
        "status": "BENCHMARK_PREDECLARED_AND_LOCKED",
        "output_dir": str(output_dir.resolve()),
        "candidate_hashes": {
            row["candidate"]: row["checkpoint_sha256"]
            for row in candidates
        },
        "seed_count": seed_count,
        "lock_sha256": file_sha256(output_dir / "benchmark_lock.json"),
    }


def _load_and_verify_lock(output_dir: Path) -> tuple[dict, dict, dict]:
    lock = json.loads(
        (output_dir / "benchmark_lock.json").read_text(encoding="utf-8")
    )
    for name, expected in lock["files"].items():
        actual = file_sha256(output_dir / name)
        if actual != expected:
            raise RuntimeError(
                f"Locked benchmark file changed: {name}; "
                f"expected {expected}, observed {actual}"
            )
    candidates = json.loads(
        (output_dir / "candidate_manifest.json").read_text(encoding="utf-8")
    )
    seeds = json.loads(
        (output_dir / "seed_manifest.json").read_text(encoding="utf-8")
    )
    for row in candidates["candidates"]:
        actual = file_sha256(row["checkpoint_path"])
        if actual != row["checkpoint_sha256"]:
            raise RuntimeError(
                f"Frozen checkpoint hash mismatch for {row['candidate']}"
            )
    if {row["candidate"] for row in candidates["candidates"]} != set(POLICIES):
        raise RuntimeError("Locked candidate set is not exactly the two policies")
    return lock, candidates, seeds


def _agents(env, config, candidates):
    output = {}
    for row in candidates["candidates"]:
        agent = _make_agent(env, config, row["mode"])
        agent.load(row["checkpoint_path"])
        agent.set_eval()
        output[row["candidate"]] = agent
    return output


def _episode_row(
    *,
    policy: str,
    seed: int,
    scenario_hash: str,
    candidate: Mapping[str, object],
    metrics: Mapping[str, object],
) -> dict:
    termination = str(metrics["termination_reason"])
    completed = (
        int(metrics["steps"]) < 6000
        and termination.lower() not in {"", "in_progress", "step_cap"}
    )
    return {
        "policy": policy,
        "seed": seed,
        "scenario_sha256": scenario_hash,
        "checkpoint_sha256": candidate["checkpoint_sha256"],
        "production_gate": candidate["production_gate"],
        "guidance_beta": candidate["guidance_beta"],
        "reward": metrics["reward"],
        "J_dep_true": metrics["J_dep_true"],
        "J_dep_belief": metrics["J_dep_belief"],
        "fill_rate": metrics["fill_rate"],
        "feasibility_violations": metrics["feasibility_violations"],
        "mission_completed": int(completed),
        "termination_reason": termination,
        "environment_steps": metrics["steps"],
        "episode_duration_h": metrics["episode_duration_h"],
        "computational_time_s": metrics["computational_time_s"],
    }


def _paired_rows(episode_rows: Sequence[Mapping[str, object]]) -> list[dict]:
    by_seed: dict[int, dict[str, Mapping[str, object]]] = {}
    for row in episode_rows:
        by_seed.setdefault(int(row["seed"]), {})[str(row["policy"])] = row
    output = []
    for seed in sorted(by_seed):
        pair = by_seed[seed]
        if set(pair) != set(POLICIES):
            raise RuntimeError(f"Incomplete policy pair for seed {seed}")
        unguided = pair["unguided_graph_mappo"]
        fixed = pair["fixed_guidance"]
        output.append(
            {
                "seed": seed,
                "scenario_sha256": unguided["scenario_sha256"],
                "unguided_J_dep_true": float(unguided["J_dep_true"]),
                "fixed_J_dep_true": float(fixed["J_dep_true"]),
                "deprivation_reduction": (
                    float(unguided["J_dep_true"])
                    - float(fixed["J_dep_true"])
                ),
                "deprivation_reduction_fraction": (
                    (
                        float(unguided["J_dep_true"])
                        - float(fixed["J_dep_true"])
                    )
                    / float(unguided["J_dep_true"])
                ),
                "unguided_fill_rate": float(unguided["fill_rate"]),
                "fixed_fill_rate": float(fixed["fill_rate"]),
                "fill_rate_difference": (
                    float(fixed["fill_rate"])
                    - float(unguided["fill_rate"])
                ),
                "unguided_reward": float(unguided["reward"]),
                "fixed_reward": float(fixed["reward"]),
                "reward_difference": (
                    float(fixed["reward"]) - float(unguided["reward"])
                ),
                "unguided_feasibility_violations": int(
                    unguided["feasibility_violations"]
                ),
                "fixed_feasibility_violations": int(
                    fixed["feasibility_violations"]
                ),
                "unguided_mission_completed": int(
                    unguided["mission_completed"]
                ),
                "fixed_mission_completed": int(fixed["mission_completed"]),
                "unguided_computational_time_s": float(
                    unguided["computational_time_s"]
                ),
                "fixed_computational_time_s": float(
                    fixed["computational_time_s"]
                ),
            }
        )
    return output


def _mean_interval(values: Sequence[float], offset: int = 0) -> dict:
    return paired_bootstrap_interval(
        values,
        confidence=float(PROMOTION_RULE["paired_confidence_level"]),
        samples=int(PROMOTION_RULE["paired_bootstrap_samples"]),
        seed=int(PROMOTION_RULE["paired_bootstrap_seed"]) + offset,
    )


def _summary_rows(paired: Sequence[Mapping[str, object]]) -> list[dict]:
    metrics = (
        ("True deprivation cost", "unguided_J_dep_true", "fixed_J_dep_true"),
        ("Fill rate", "unguided_fill_rate", "fixed_fill_rate"),
        ("Reward", "unguided_reward", "fixed_reward"),
        (
            "Feasibility violations",
            "unguided_feasibility_violations",
            "fixed_feasibility_violations",
        ),
        (
            "Mission completion rate",
            "unguided_mission_completed",
            "fixed_mission_completed",
        ),
        (
            "Computational time (s)",
            "unguided_computational_time_s",
            "fixed_computational_time_s",
        ),
    )
    output = []
    for index, (label, unguided_key, fixed_key) in enumerate(metrics):
        unguided = np.asarray([float(row[unguided_key]) for row in paired])
        fixed = np.asarray([float(row[fixed_key]) for row in paired])
        difference = fixed - unguided
        interval = _mean_interval(difference, 10 + index)
        output.append(
            {
                "outcome": label,
                "unguided_mean": float(unguided.mean()),
                "fixed_mean": float(fixed.mean()),
                "fixed_minus_unguided": float(difference.mean()),
                "paired_ci_low": interval["ci_low"],
                "paired_ci_high": interval["ci_high"],
                "n_pairs": len(paired),
            }
        )
    return output


def _plot_results(output_dir: Path, paired: Sequence[Mapping[str, object]]) -> list[Path]:
    figures = output_dir / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    seeds = np.asarray([int(row["seed"]) for row in paired])
    unguided = np.asarray([float(row["unguided_J_dep_true"]) for row in paired])
    fixed = np.asarray([float(row["fixed_J_dep_true"]) for row in paired])
    reduction_pct = 100.0 * (unguided - fixed) / unguided
    outputs = []

    fig, ax = plt.subplots(figsize=(7.2, 4.8), constrained_layout=True)
    for index in range(len(paired)):
        color = "#2a9d8f" if fixed[index] < unguided[index] else "#e76f51"
        ax.plot([0, 1], [unguided[index], fixed[index]], color=color, alpha=0.35)
    ax.scatter(
        np.zeros(len(paired)),
        unguided,
        color="#264653",
        s=22,
        zorder=3,
        label="Unguided",
    )
    ax.scatter(
        np.ones(len(paired)),
        fixed,
        color="#e9c46a",
        edgecolor="#264653",
        linewidth=0.5,
        s=25,
        zorder=3,
        label="Fixed guidance",
    )
    ax.set_xticks([0, 1], ["Unguided $g=0$", "Fixed $g=0.5$"])
    ax.set_ylabel("True deprivation cost")
    ax.set_title(f"Paired held-out benchmark ({len(paired)} seeds)")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)
    for suffix in ("png", "pdf"):
        path = figures / f"paired_true_deprivation.{suffix}"
        fig.savefig(path, dpi=300)
        outputs.append(path)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.2, 4.8), constrained_layout=True)
    bins = max(8, int(math.sqrt(len(reduction_pct)) * 2))
    ax.hist(
        reduction_pct,
        bins=bins,
        color="#457b9d",
        edgecolor="white",
        alpha=0.9,
    )
    ax.axvline(0.0, color="#9d0208", linewidth=1.4, label="No improvement")
    ax.axvline(
        5.0,
        color="#2a9d8f",
        linewidth=1.4,
        linestyle="--",
        label="5% promotion threshold",
    )
    ax.axvline(
        float(reduction_pct.mean()),
        color="#1d3557",
        linewidth=1.8,
        label=f"Mean = {reduction_pct.mean():.1f}%",
    )
    ax.set_xlabel("Per-seed deprivation reduction (%)")
    ax.set_ylabel("Seed count")
    ax.set_title("Distribution of paired fixed-guidance improvement")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.25)
    for suffix in ("png", "pdf"):
        path = figures / f"paired_reduction_distribution.{suffix}"
        fig.savefig(path, dpi=300)
        outputs.append(path)
    plt.close(fig)

    fill_delta = np.asarray(
        [float(row["fill_rate_difference"]) for row in paired]
    )
    reward_delta = np.asarray(
        [float(row["reward_difference"]) for row in paired]
    )
    time_delta = np.asarray(
        [
            float(row["fixed_computational_time_s"])
            - float(row["unguided_computational_time_s"])
            for row in paired
        ]
    )
    values = [
        100.0 * float(fill_delta.mean()),
        float(reward_delta.mean()),
        float(time_delta.mean()),
    ]
    labels = [
        "Fill rate\n(percentage points)",
        "Reward",
        "Compute time\n(seconds)",
    ]
    colors = ["#2a9d8f", "#457b9d", "#f4a261"]
    fig, axes = plt.subplots(
        1,
        3,
        figsize=(9.2, 3.8),
        constrained_layout=True,
    )
    for ax, value, label, color in zip(axes, values, labels, colors):
        ax.bar([0], [value], color=color, width=0.55)
        ax.axhline(0.0, color="#444444", linewidth=0.8)
        ax.set_xticks([0], [label])
        ax.set_title(f"{value:+.3f}")
        ax.grid(axis="y", alpha=0.2)
    fig.suptitle("Fixed guidance minus unguided: secondary outcomes")
    for suffix in ("png", "pdf"):
        path = figures / f"secondary_outcome_differences.{suffix}"
        fig.savefig(path, dpi=300)
        outputs.append(path)
    plt.close(fig)
    return outputs


def _write_publication_table(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{Locked paired benchmark on untouched seeds.}",
        r"\label{tab:fixed-guidance-final-benchmark}",
        r"\begin{tabular}{lrrrr}",
        r"\hline",
        r"Outcome & Unguided & Fixed & Difference & 95\% CI \\",
        r"\hline",
    ]
    for row in rows:
        label = str(row["outcome"]).replace("%", r"\%").replace("_", r"\_")
        lines.append(
            f"{label} & {float(row['unguided_mean']):.4f} & "
            f"{float(row['fixed_mean']):.4f} & "
            f"{float(row['fixed_minus_unguided']):+.4f} & "
            f"[{float(row['paired_ci_low']):+.4f}, "
            f"{float(row['paired_ci_high']):+.4f}] \\\\"
        )
    lines.extend([r"\hline", r"\end{tabular}", r"\end{table}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _decision_markdown(decision: Mapping[str, object]) -> str:
    outcome = decision["primary_outcome"]
    guardrails = decision["secondary_guardrails"]
    lines = [
        "# Locked fixed-guidance promotion decision",
        "",
        f"## {decision['decision']}",
        "",
        f"- Mean deprivation reduction: "
        f"{float(outcome['mean_reduction_percent']):.3f}%",
        f"- Paired 95% CI for absolute reduction: "
        f"[{float(outcome['paired_interval']['ci_low']):.6f}, "
        f"{float(outcome['paired_interval']['ci_high']):.6f}]",
        f"- Seeds improved: "
        f"{100.0 * float(outcome['positive_seed_fraction']):.1f}%",
        f"- Mean reduction after removing the two best seeds: "
        f"{float(outcome['mean_reduction_after_removing_two_largest']):.6f}",
        f"- Mean fill rate, unguided/fixed: "
        f"{float(guardrails['unguided_mean_fill_rate']):.6f} / "
        f"{float(guardrails['fixed_mean_fill_rate']):.6f}",
        f"- Feasibility violations, unguided/fixed: "
        f"{int(guardrails['unguided_feasibility_violations'])} / "
        f"{int(guardrails['fixed_feasibility_violations'])}",
        "",
        "Adaptive guidance was rejected before this benchmark and was not "
        "loaded, evaluated, or considered for promotion.",
        "",
        "### Predeclared checks",
        "",
    ]
    lines.extend(
        f"- [{'x' if passed else ' '}] {name}"
        for name, passed in decision["checks"].items()
    )
    return "\n".join(lines) + "\n"


def finalize_benchmark(
    *,
    output_dir: Path,
    candidates: Mapping[str, object],
    seeds: Mapping[str, object],
) -> dict:
    episode_rows = _read_csv(output_dir / "paired_episode_metrics.csv")
    expected = 2 * len(seeds["seeds"])
    if len(episode_rows) != expected:
        raise RuntimeError(
            f"Cannot finalize incomplete benchmark: {len(episode_rows)}/"
            f"{expected} policy episodes"
        )
    paired = _paired_rows(episode_rows)
    decision = promotion_decision(paired)
    summary = _summary_rows(paired)
    _write_csv(output_dir / "paired_seed_results.csv", paired)
    _write_csv(output_dir / "benchmark_summary.csv", summary)
    _write_json(output_dir / "promotion_decision.json", decision)
    (output_dir / "promotion_decision.md").write_text(
        _decision_markdown(decision),
        encoding="utf-8",
    )
    _write_publication_table(output_dir / "benchmark_table.tex", summary)
    figures = _plot_results(output_dir, paired)
    post_hashes = {}
    for row in candidates["candidates"]:
        actual = file_sha256(row["checkpoint_path"])
        post_hashes[row["candidate"]] = {
            "expected": row["checkpoint_sha256"],
            "observed": actual,
            "passed": actual == row["checkpoint_sha256"],
        }
    if not all(row["passed"] for row in post_hashes.values()):
        raise RuntimeError("Candidate checkpoint changed during benchmark")
    artifacts = [
        output_dir / "benchmark_protocol.json",
        output_dir / "benchmark_lock.json",
        output_dir / "candidate_manifest.json",
        output_dir / "seed_manifest.json",
        output_dir / "checkpoint_hash_verification.json",
        output_dir / "paired_episode_metrics.csv",
        output_dir / "paired_seed_results.csv",
        output_dir / "benchmark_summary.csv",
        output_dir / "benchmark_table.tex",
        output_dir / "promotion_decision.json",
        output_dir / "promotion_decision.md",
        *figures,
    ]
    _write_json(
        output_dir / "reproducibility_report.json",
        {
            "protocol_version": PROTOCOL_VERSION,
            "completed_utc": _utc_now(),
            "candidate_hash_verification_after_evaluation": post_hashes,
            "artifact_sha256": {
                str(path.relative_to(output_dir)).replace("\\", "/"): (
                    file_sha256(path)
                )
                for path in artifacts
            },
        },
    )
    return decision


def run_benchmark(
    *,
    results: Path,
    output_dir: Path,
    device: str,
) -> dict:
    lock, candidates, seeds = _load_and_verify_lock(output_dir)
    protocol = json.loads(
        (output_dir / "benchmark_protocol.json").read_text(encoding="utf-8")
    )
    if protocol["benchmark_runner_sha256"] != file_sha256(Path(__file__)):
        raise RuntimeError(
            "Benchmark runner changed after predeclaration; prepare a new "
            "locked output directory"
        )
    metadata, _, params, env, config = _load_context(results, device)
    if not math.isclose(float(metadata["beta"]), 5.591, abs_tol=1e-12):
        raise RuntimeError("Fixed challenger beta is not the locked 5.591")
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    torch.use_deterministic_algorithms(True)
    first_seed = int(seeds["seeds"][0]["seed"])
    env.reset(scenario=generate_scenario(first_seed, params))
    candidate_lookup = {
        row["candidate"]: row for row in candidates["candidates"]
    }
    _write_json(
        output_dir / "checkpoint_hash_verification.json",
        {
            "verified_before_evaluation": True,
            "verified_utc": _utc_now(),
            "candidates": {
                name: {
                    "expected": row["checkpoint_sha256"],
                    "observed": file_sha256(row["checkpoint_path"]),
                    "passed": (
                        file_sha256(row["checkpoint_path"])
                        == row["checkpoint_sha256"]
                    ),
                }
                for name, row in candidate_lookup.items()
            },
            "adaptive_checkpoint_loaded": False,
        },
    )
    agents = _agents(env, config, candidates)
    metrics_path = output_dir / "paired_episode_metrics.csv"
    existing_rows = _read_csv(metrics_path)
    existing_keys = [
        (int(row["seed"]), row["policy"]) for row in existing_rows
    ]
    if len(existing_keys) != len(set(existing_keys)):
        raise RuntimeError("Duplicate policy/seed rows in resumable benchmark")
    seed_lookup = {
        int(row["seed"]): row for row in seeds["seeds"]
    }
    for row in existing_rows:
        seed = int(row["seed"])
        policy = row["policy"]
        if seed not in seed_lookup or policy not in candidate_lookup:
            raise RuntimeError("Existing result is outside the locked manifest")
        if row["scenario_sha256"] != seed_lookup[seed][
            "scenario_content_sha256"
        ]:
            raise RuntimeError(f"Existing scenario hash mismatch for seed {seed}")
        if row["checkpoint_sha256"] != candidate_lookup[policy][
            "checkpoint_sha256"
        ]:
            raise RuntimeError(
                f"Existing checkpoint hash mismatch for {policy}, seed {seed}"
            )
    completed = set(existing_keys)
    for seed_index, seed_row in enumerate(seeds["seeds"]):
        seed = int(seed_row["seed"])
        scenario = generate_scenario(seed, params)
        actual_scenario_hash = scenario.content_hash()
        if actual_scenario_hash != seed_row["scenario_content_sha256"]:
            raise RuntimeError(f"Scenario hash mismatch for seed {seed}")
        order = (
            POLICIES
            if seed_index % 2 == 0
            else tuple(reversed(POLICIES))
        )
        for policy in order:
            if (seed, policy) in completed:
                continue
            started = time.perf_counter()
            metrics, _, _ = _run_episode(
                env=env,
                scenario=copy.deepcopy(scenario),
                agent=agents[policy],
                branch=candidate_lookup[policy]["mode"],
                phase="locked_final_benchmark",
                episode=seed_index + 1,
                checkpoint_episode=(
                    0 if policy == "unguided_graph_mappo" else 200
                ),
                target_regime="UNTOUCHED_FINAL_BENCHMARK",
                train=False,
                deterministic=True,
                collect_vectors=False,
                decision_start=0,
            )
            metrics["computational_time_s"] = time.perf_counter() - started
            row = _episode_row(
                policy=policy,
                seed=seed,
                scenario_hash=actual_scenario_hash,
                candidate=candidate_lookup[policy],
                metrics=metrics,
            )
            _append_csv(metrics_path, [row], EPISODE_FIELDS)
            completed.add((seed, policy))
        print(
            f"paired seed {seed_index + 1}/{len(seeds['seeds'])}: {seed}",
            flush=True,
        )
    decision = finalize_benchmark(
        output_dir=output_dir,
        candidates=candidates,
        seeds=seeds,
    )
    return {
        "status": "LOCKED_BENCHMARK_COMPLETE",
        "decision": decision["decision"],
        "production_policy": decision["production_policy"],
        "output_dir": str(output_dir.resolve()),
        "lock_sha256": file_sha256(output_dir / "benchmark_lock.json"),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare", action="store_true")
    action.add_argument("--run", action="store_true")
    action.add_argument("--verify-only", action="store_true")
    parser.add_argument(
        "--results",
        type=Path,
        default=Path("results/gate_learning_beta5591_pilot"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/fixed_vs_unguided_final_benchmark"),
    )
    parser.add_argument("--seed-start", type=int)
    parser.add_argument("--seed-count", type=int, default=40)
    parser.add_argument("--device", default="cuda")
    return parser


def main() -> int:
    args = _parser().parse_args()
    repository_root = Path(__file__).resolve().parents[1]
    if args.prepare:
        if args.seed_start is None:
            raise ValueError("--prepare requires an explicit --seed-start")
        result = prepare_benchmark(
            repository_root=repository_root,
            results=args.results,
            output_dir=args.output_dir,
            seed_start=args.seed_start,
            seed_count=args.seed_count,
            device=args.device,
        )
    elif args.verify_only:
        lock, candidates, seeds = _load_and_verify_lock(args.output_dir)
        result = {
            "status": "LOCK_VERIFIED",
            "lock_sha256": file_sha256(
                args.output_dir / "benchmark_lock.json"
            ),
            "candidate_count": len(candidates["candidates"]),
            "seed_count": len(seeds["seeds"]),
            "evaluation_started_at_lock_creation": lock[
                "evaluation_started_at_lock_creation"
            ],
        }
    else:
        result = run_benchmark(
            results=args.results,
            output_dir=args.output_dir,
            device=args.device,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
