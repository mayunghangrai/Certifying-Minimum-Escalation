"""Create the ten required gate-learning development figures."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import sys

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from methods.gate_learning_development import (
    PRIMARY_FEATURES,
    REGIMES,
    paired_fresh_stale_effect,
)


FIGURE_NAMES = (
    "training_gate_mean_std.png",
    "training_gate_vs_fixed.png",
    "gate_by_plan_regime.png",
    "fresh_vs_stale_paired_effect.png",
    "gate_feature_relationships.png",
    "adaptive_fixed_policy_distance.png",
    "alns_follow_rate_by_regime.png",
    "validation_objective_curves.png",
    "prior_coverage_by_regime.png",
    "gate_learning_decision_summary.png",
)


def _read(path: Path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _float(row, key, default=math.nan):
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return default


def _finish(figure, path):
    figure.savefig(path, dpi=180)
    plt.close(figure)


def _rolling(values, window=10):
    values = np.asarray(values, dtype=float)
    if not len(values):
        return values
    output = np.empty_like(values)
    for index in range(len(values)):
        output[index] = values[max(0, index - window + 1): index + 1].mean()
    return output


def plot(results: Path, output_dir: Path) -> list[Path]:
    adaptive_train = _read(results / "adaptive_guidance" / "training_log.csv")
    decisions = _read(results / "validation" / "regime_decisions.csv")
    matched = _read(results / "validation" / "matched_state_pairs.csv")
    relationships = _read(results / "validation" / "feature_relationships.csv")
    counterfactual = _read(
        results / "validation" / "counterfactual_policy_comparison.csv"
    )
    summary = _read(results / "validation" / "regime_gate_summary.csv")
    verdict = json.loads(
        (results / "gate_learning_verdict.json").read_text(encoding="utf-8")
    )
    if not adaptive_train or not decisions:
        raise ValueError("Completed training and validation tables are required")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []

    episodes = np.asarray([int(row["episode"]) for row in adaptive_train])
    gate_mean = np.asarray([_float(row, "gate_mean") for row in adaptive_train])
    gate_std = np.asarray(
        [_float(row, "gate_standard_deviation") for row in adaptive_train]
    )
    fig, ax = plt.subplots(figsize=(8.5, 4.8), constrained_layout=True)
    ax.plot(episodes, gate_mean, color="#2a9d8f", label="gate mean")
    ax.fill_between(
        episodes,
        np.clip(gate_mean - gate_std, 0, 1),
        np.clip(gate_mean + gate_std, 0, 1),
        color="#2a9d8f",
        alpha=0.2,
        label="±1 std",
    )
    ax.axhline(0.5, color="#222222", linestyle="--", label="fixed gate")
    ax.set(xlabel="Training episode", ylabel="Gate output", ylim=(0, 1))
    ax.grid(alpha=0.2); ax.legend()
    path = output_dir / FIGURE_NAMES[0]
    _finish(fig, path); outputs.append(path)

    fig, ax = plt.subplots(figsize=(8.5, 4.8), constrained_layout=True)
    distance = np.asarray(
        [_float(row, "mean_abs_gate_minus_fixed") for row in adaptive_train]
    )
    ax.plot(episodes, distance, alpha=0.35, color="#e76f51", label="episode")
    ax.plot(
        episodes,
        _rolling(distance, 10),
        color="#c43d21",
        linewidth=2,
        label="10-episode mean",
    )
    ax.axhline(0.03, linestyle="--", color="#555555", label="development target")
    ax.set(xlabel="Training episode", ylabel="Mean |adaptive - 0.5|")
    ax.grid(alpha=0.2); ax.legend()
    path = output_dir / FIGURE_NAMES[1]
    _finish(fig, path); outputs.append(path)

    prior = [
        row
        for row in decisions
        if int(row["prior_nonzero"])
        and int(row["recommended_action_feasible"])
    ]
    values = [
        [_float(row, "gate_adaptive") for row in prior if row["regime"] == regime]
        for regime in REGIMES
    ]
    fig, ax = plt.subplots(figsize=(11, 5.2), constrained_layout=True)
    nonempty = [
        (index, regime, value)
        for index, (regime, value) in enumerate(zip(REGIMES, values), 1)
        if value
    ]
    ax.boxplot(
        [value for _, _, value in nonempty],
        positions=[index for index, _, _ in nonempty],
        showfliers=False,
    )
    ax.set_xticks(range(1, len(REGIMES) + 1), REGIMES)
    ax.set_xlim(0.5, len(REGIMES) + 0.5)
    for index, value in enumerate(values, 1):
        if not value:
            ax.text(
                index,
                0.5,
                "no observed\nstates",
                ha="center",
                va="bottom",
                color="#555555",
            )
    ax.axhline(0.5, color="#333333", linestyle="--")
    ax.tick_params(axis="x", rotation=30)
    ax.set(ylabel="Adaptive gate", ylim=(0, 1))
    ax.grid(axis="y", alpha=0.2)
    path = output_dir / FIGURE_NAMES[2]
    _finish(fig, path); outputs.append(path)

    fig, ax = plt.subplots(figsize=(8.5, 4.8), constrained_layout=True)
    matched_effect = paired_fresh_stale_effect(matched)
    exact_effect = matched_effect["fresh_minus_stale_mean"]
    ax.barh(
        ["Canonical feature probe"],
        [exact_effect],
        color="#457b9d",
        alpha=0.85,
    )
    ax.axvline(0.0, color="#222222", linestyle="--", label="no effect")
    ax.axvline(0.05, color="#e76f51", linestyle=":", label="development target")
    ax.text(
        0.02,
        0.96,
        (
            f"exact contrast={exact_effect:.3f}\n"
            f"source states={matched_effect['source_state_count']}"
        ),
        transform=ax.transAxes,
        ha="left",
        va="top",
    )
    ax.set(
        xlabel="Fresh gate − combined stale/deviated gate",
        ylabel="Controlled comparison",
    )
    ax.grid(alpha=0.2); ax.legend()
    path = output_dir / FIGURE_NAMES[3]
    _finish(fig, path); outputs.append(path)

    fig, axes = plt.subplots(2, 4, figsize=(13, 7), constrained_layout=True)
    for axis, feature in zip(axes.flat, PRIMARY_FEATURES):
        subset = [row for row in relationships if row["feature"] == feature]
        x = [
            0.5 * (_float(row, "bin_low") + _float(row, "bin_high"))
            for row in subset
            if int(row["count"]) > 0
        ]
        y = [
            _float(row, "mean_gate")
            for row in subset
            if int(row["count"]) > 0
        ]
        axis.plot(x, y, "o-", color="#2a9d8f")
        rho = _float(subset[0], "spearman") if subset else math.nan
        axis.set_title(f"{feature}\nSpearman={rho:.3f}")
        axis.set(xlabel="Feature", ylabel="Mean gate", ylim=(0, 1))
        axis.grid(alpha=0.2)
    axes.flat[-1].axis("off")
    path = output_dir / FIGURE_NAMES[4]
    _finish(fig, path); outputs.append(path)

    prior_cf = [row for row in counterfactual if int(row["prior_nonzero"])]
    fig, (left, right) = plt.subplots(1, 2, figsize=(10.5, 4.5), constrained_layout=True)
    left.hist(
        [_float(row, "tv_adaptive_fixed") for row in prior_cf],
        bins=30,
        color="#2a9d8f",
    )
    left.axvline(0.003, color="#e76f51", linestyle="--")
    left.set(xlabel="TV(adaptive, fixed)", ylabel="Prior-bearing decisions")
    right.hist(
        [_float(row, "kl_adaptive_fixed") for row in prior_cf],
        bins=30,
        color="#457b9d",
    )
    right.set(xlabel="KL(adaptive || fixed)", ylabel="Prior-bearing decisions")
    left.grid(alpha=0.2); right.grid(alpha=0.2)
    path = output_dir / FIGURE_NAMES[5]
    _finish(fig, path); outputs.append(path)

    rates = []
    regime_counts = []
    for regime in REGIMES:
        subset = [row for row in prior_cf if row["regime"] == regime]
        regime_counts.append(len(subset))
        rates.append(
            [
                np.mean([int(row["unguided_follows_alns"]) for row in subset])
                if subset else 0.0,
                np.mean([int(row["fixed_follows_alns"]) for row in subset])
                if subset else 0.0,
                np.mean([int(row["adaptive_follows_alns"]) for row in subset])
                if subset else 0.0,
            ]
        )
    rates = np.asarray(rates)
    x = np.arange(len(REGIMES))
    fig, ax = plt.subplots(figsize=(11, 5), constrained_layout=True)
    for offset, label, color in (
        (-0.25, "no guidance", "#8d99ae"),
        (0.0, "fixed", "#f4a261"),
        (0.25, "adaptive", "#2a9d8f"),
    ):
        column = {"no guidance": 0, "fixed": 1, "adaptive": 2}[label]
        ax.bar(x + offset, 100 * rates[:, column], width=0.24, label=label, color=color)
    ax.set_xticks(x, REGIMES, rotation=30, ha="right")
    for index, count in enumerate(regime_counts):
        if count == 0:
            ax.text(
                index,
                1.0,
                "no observed\nstates",
                ha="center",
                va="bottom",
                color="#555555",
            )
    ax.set(ylabel="ALNS-following argmax rate (%)", ylim=(0, 100))
    ax.grid(axis="y", alpha=0.2); ax.legend()
    path = output_dir / FIGURE_NAMES[6]
    _finish(fig, path); outputs.append(path)

    fig, ax = plt.subplots(figsize=(8.5, 4.8), constrained_layout=True)
    for directory, label, color in (
        ("graph_mappo", "graph MAPPO", "#8d99ae"),
        ("fixed_guidance", "fixed guidance", "#f4a261"),
        ("adaptive_guidance", "adaptive guidance", "#2a9d8f"),
    ):
        rows = _read(results / directory / "evaluation_log.csv")
        if not rows:
            raise ValueError(
                f"Missing checkpoint validation log for {directory}"
            )
        ax.plot(
            [int(row["checkpoint_episode"]) for row in rows],
            [_float(row, "mean_true_deprivation_cost") for row in rows],
            marker="o",
            label=label,
            color=color,
        )
    ax.set(
        xlabel="Training checkpoint episode",
        ylabel="Validation mean true deprivation cost",
    )
    ax.grid(alpha=0.2); ax.legend()
    path = output_dir / FIGURE_NAMES[7]
    _finish(fig, path); outputs.append(path)

    counts = {regime: {"all": 0, "prior": 0} for regime in REGIMES}
    for row in decisions:
        counts[row["regime"]]["all"] += 1
        counts[row["regime"]]["prior"] += int(row["prior_nonzero"])
    coverage = np.asarray(
        [
            (
                counts[regime]["prior"] / counts[regime]["all"]
                if counts[regime]["all"]
                else math.nan
            )
            for regime in REGIMES
        ],
        dtype=float,
    )
    fig, ax = plt.subplots(figsize=(10.5, 4.8), constrained_layout=True)
    ax.bar(REGIMES, 100 * coverage, color="#457b9d")
    ax.set_xlim(-0.5, len(REGIMES) - 0.5)
    for index, value in enumerate(coverage):
        if not np.isfinite(value):
            ax.text(
                index,
                1.0,
                "no observed\nstates",
                ha="center",
                va="bottom",
                color="#555555",
            )
    ax.axhline(30, color="#e76f51", linestyle="--", label="30% target")
    ax.tick_params(axis="x", rotation=30)
    ax.set(ylabel="Prior coverage (%)", ylim=(0, 100))
    ax.grid(axis="y", alpha=0.2); ax.legend()
    path = output_dir / FIGURE_NAMES[8]
    _finish(fig, path); outputs.append(path)

    targets = verdict["development_targets"]
    labels = [
        "Prior coverage",
        "Prior count",
        "Gate variation",
        "Paired effect",
        "Regime medians",
        "Policy distance",
        "Gradients",
        "Contracts",
        "Stability",
    ]
    values = [
        int(targets[key])
        for key in (
            "prior_coverage_at_least_0_30",
            "prior_decisions_at_least_1000",
            "material_gate_variation",
            "paired_effect_at_least_0_05_ci_positive",
            "three_stale_regimes_below_fresh",
            "measurable_policy_difference",
            "finite_nonzero_gate_gradients",
            "truth_mask_observation_checks",
            "no_catastrophic_collapse",
        )
    ]
    fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
    colors = ["#2a9d8f" if value else "#e76f51" for value in values]
    ax.barh(labels, values, color=colors)
    ax.set(xlim=(0, 1.05), xlabel="Development target supported")
    ax.set_xticks([0, 1], ["No", "Yes"])
    ax.invert_yaxis()
    ax.set_title(verdict["verdict"])
    ax.grid(axis="x", alpha=0.2)
    path = output_dir / FIGURE_NAMES[9]
    _finish(fig, path); outputs.append(path)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results",
        type=Path,
        default=Path("results/gate_learning_development"),
    )
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    output = args.output_dir or args.results / "figures"
    for path in plot(args.results, output):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
