"""Generate the ten required adaptive-gate diagnostic figures."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


FIGURE_NAMES = (
    "gate_distribution.png",
    "gate_over_time.png",
    "gate_vs_fixed.png",
    "feature_variation.png",
    "prior_coverage_and_masking.png",
    "guidance_probability_shift.png",
    "gate_gradient_norms.png",
    "gate_parameter_updates.png",
    "action_follow_deviation_rates.png",
    "controlled_probe_sensitivity.png",
)


def _read(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _finish(figure, path):
    figure.savefig(path, dpi=180)
    plt.close(figure)


def plot(diagnostics: Path, output_dir: Path) -> list[Path]:
    decisions = _read(diagnostics / "adaptive_gate_decisions.csv")
    updates = _read(diagnostics / "adaptive_gate_update_diagnostics.csv")
    features = _read(diagnostics / "adaptive_gate_feature_summary.csv")
    probes = _read(diagnostics / "adaptive_gate_controlled_probes.csv")
    if not decisions:
        raise ValueError("No adaptive-gate decision diagnostics")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    gate = np.asarray([float(row["gate_adaptive"]) for row in decisions])
    fixed = float(decisions[0]["gate_fixed"])

    fig, ax = plt.subplots(figsize=(8, 4.8), constrained_layout=True)
    ax.hist(gate, bins=24, color="#2a9d8f", alpha=0.85)
    ax.axvspan(0, 0.05, color="#d62728", alpha=0.12, label="low saturation")
    ax.axvspan(0.95, 1, color="#9467bd", alpha=0.12, label="high saturation")
    ax.axvline(fixed, color="#111111", linestyle="--", label=f"fixed g={fixed:g}")
    ax.set(xlabel="Adaptive gate", ylabel="Decision count", xlim=(0, 1))
    ax.grid(alpha=0.2)
    ax.legend()
    path = output_dir / FIGURE_NAMES[0]
    _finish(fig, path); outputs.append(path)

    fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
    time = np.asarray([float(row["decision_time"]) for row in decisions])
    uavs = np.asarray([int(row["uav_id"]) for row in decisions])
    phase = np.asarray([row["phase"] for row in decisions])
    for uav in sorted(set(uavs)):
        keep = (uavs == uav) & (phase == "training")
        ax.scatter(time[keep], gate[keep], s=10, alpha=0.55, label=f"UAV {uav}")
    ax.axhline(fixed, color="#111111", linestyle="--", label="fixed gate")
    ax.set(xlabel="Operational decision time (h)", ylabel="Adaptive gate", ylim=(0, 1))
    ax.grid(alpha=0.2); ax.legend(ncol=2)
    path = output_dir / FIGURE_NAMES[1]
    _finish(fig, path); outputs.append(path)

    fig, (left, right) = plt.subplots(1, 2, figsize=(10, 4.5), constrained_layout=True)
    left.scatter(np.full_like(gate, fixed), gate, s=10, alpha=0.45)
    left.plot([0, 1], [0, 1], "--", color="#555555")
    left.set(xlabel="Fixed gate", ylabel="Adaptive gate", xlim=(0, 1), ylim=(0, 1))
    right.hist(np.abs(gate - fixed), bins=24, color="#e76f51")
    right.set(xlabel="|adaptive - fixed|", ylabel="Decision count")
    left.grid(alpha=0.2); right.grid(alpha=0.2)
    path = output_dir / FIGURE_NAMES[2]
    _finish(fig, path); outputs.append(path)

    all_features = [
        row for row in features
        if row["scope"] == "all" and row["scope_value"] == "all"
    ]
    names = [row["feature"] for row in all_features]
    variability = [float(row["standard_deviation"]) for row in all_features]
    colors = [
        "#2a9d8f" if row["status"] == "VARIABLE" else "#e76f51"
        for row in all_features
    ]
    fig, ax = plt.subplots(figsize=(10, 5.5), constrained_layout=True)
    ax.barh(np.arange(len(names)), variability, color=colors)
    ax.set_yticks(np.arange(len(names)), labels=names)
    ax.invert_yaxis()
    ax.set(xlabel="Standard deviation of normalized feature")
    ax.grid(axis="x", alpha=0.2)
    path = output_dir / FIGURE_NAMES[3]
    _finish(fig, path); outputs.append(path)

    prior = np.asarray([not int(row["prior_is_zero"]) for row in decisions])
    mapped = np.asarray([
        bool(int(row["recommendation_maps_successfully"])) for row in decisions
    ])
    feasible = np.asarray([
        bool(int(row["recommended_action_feasible"])) for row in decisions
    ])
    masked = np.asarray([
        bool(int(row["recommended_action_masked"])) for row in decisions
    ])
    values = [prior.mean(), mapped.mean(), feasible.mean(), masked.mean()]
    fig, ax = plt.subplots(figsize=(8, 4.8), constrained_layout=True)
    ax.bar(
        ["prior nonzero", "mapped", "feasible", "masked"],
        100 * np.asarray(values),
        color=["#2a9d8f", "#457b9d", "#1d3557", "#e63946"],
    )
    ax.set(ylabel="Percentage of decisions", ylim=(0, 100))
    ax.grid(axis="y", alpha=0.2)
    path = output_dir / FIGURE_NAMES[4]
    _finish(fig, path); outputs.append(path)

    bearing = [row for row in decisions if not int(row["prior_is_zero"])]
    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4.8), constrained_layout=True)
    if bearing:
        x = np.arange(len(bearing))
        left.scatter(x, [float(row["alns_action_base_probability"]) for row in bearing],
                     s=10, label="no guidance")
        left.scatter(x, [float(row["alns_action_fixed_probability"]) for row in bearing],
                     s=10, label="fixed")
        left.scatter(x, [float(row["alns_action_adaptive_probability"]) for row in bearing],
                     s=10, label="adaptive")
    left.set(xlabel="Prior-bearing decision", ylabel="ALNS-action probability")
    left.legend(); left.grid(alpha=0.2)
    right.hist(
        [float(row["tv_adaptive_fixed"]) for row in decisions],
        bins=24,
        alpha=0.65,
        label="TV adaptive/fixed",
    )
    right.hist(
        [float(row["kl_adaptive_fixed"]) for row in decisions],
        bins=24,
        alpha=0.65,
        label="KL adaptive/fixed",
    )
    right.set(xlabel="Distribution shift", ylabel="Count")
    right.legend(); right.grid(alpha=0.2)
    path = output_dir / FIGURE_NAMES[5]
    _finish(fig, path); outputs.append(path)

    update_index = np.arange(len(updates))
    fig, ax = plt.subplots(figsize=(8, 4.8), constrained_layout=True)
    ax.plot(
        update_index,
        [float(row["gate_gradient_l2_norm"]) for row in updates],
        "o-",
        ms=3,
    )
    ax.set(xlabel="PPO epoch update", ylabel="Gate gradient L2 norm")
    ax.grid(alpha=0.2)
    path = output_dir / FIGURE_NAMES[6]
    _finish(fig, path); outputs.append(path)

    fig, ax = plt.subplots(figsize=(8, 4.8), constrained_layout=True)
    ax.plot(
        update_index,
        [float(row["gate_relative_parameter_update"]) for row in updates],
        "o-",
        ms=3,
        color="#e76f51",
    )
    ax.set(xlabel="PPO epoch update", ylabel="Relative gate-parameter update")
    ax.grid(alpha=0.2)
    path = output_dir / FIGURE_NAMES[7]
    _finish(fig, path); outputs.append(path)

    recommended = np.asarray([int(row["recommended_action"]) for row in decisions])
    has = recommended >= 0
    policies = {
        "no guidance": np.asarray([int(row["unguided_argmax_action"]) for row in decisions]),
        "fixed": np.asarray([int(row["fixed_argmax_action"]) for row in decisions]),
        "adaptive": np.asarray([int(row["adaptive_argmax_action"]) for row in decisions]),
    }
    rates = [
        float((actions[has] == recommended[has]).mean()) if has.any() else 0.0
        for actions in policies.values()
    ]
    fig, ax = plt.subplots(figsize=(8, 4.8), constrained_layout=True)
    ax.bar(list(policies), 100 * np.asarray(rates), color=["#8d99ae", "#f4a261", "#2a9d8f"])
    ax.set(ylabel="ALNS-following argmax rate (%)", ylim=(0, 100))
    ax.grid(axis="y", alpha=0.2)
    path = output_dir / FIGURE_NAMES[8]
    _finish(fig, path); outputs.append(path)

    checkpoints = list(dict.fromkeys(row["checkpoint"] for row in probes))
    profiles = list(dict.fromkeys(row["profile"] for row in probes))
    fig, ax = plt.subplots(figsize=(11, 5.5), constrained_layout=True)
    width = 0.8 / max(len(checkpoints), 1)
    positions = np.arange(len(profiles))
    for index, checkpoint in enumerate(checkpoints):
        values = [
            float(next(
                row["gate_value"] for row in probes
                if row["checkpoint"] == checkpoint and row["profile"] == profile
            ))
            for profile in profiles
        ]
        ax.bar(
            positions + (index - (len(checkpoints) - 1) / 2) * width,
            values,
            width=width,
            label=checkpoint,
        )
    ax.set_xticks(positions, labels=profiles, rotation=35, ha="right")
    ax.set(ylabel="Gate output", ylim=(0, 1))
    ax.grid(axis="y", alpha=0.2); ax.legend()
    path = output_dir / FIGURE_NAMES[9]
    _finish(fig, path); outputs.append(path)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    for path in plot(args.diagnostics, args.output_dir):
        print(path)


if __name__ == "__main__":
    main()
