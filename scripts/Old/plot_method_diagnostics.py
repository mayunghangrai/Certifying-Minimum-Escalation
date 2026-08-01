"""Plot belief-graph guidance diagnostics from a training decision log."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


def _read(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"Diagnostic log contains no decision rows: {path}")
    return rows


def plot(path: Path, output_dir: Path) -> list[Path]:
    rows = _read(path)
    output_dir.mkdir(parents=True, exist_ok=True)
    time = np.asarray([float(row["decision_time_h"]) for row in rows])
    uav = np.asarray([int(row["uav_id"]) for row in rows])
    gate = np.asarray([float(row["gate"]) for row in rows])
    selected = np.asarray([int(row["selected_action"]) for row in rows])
    recommended = np.asarray(
        [int(row["alns_recommended_action"]) for row in rows]
    )
    plan_age = np.asarray([float(row["plan_age"]) for row in rows])
    invalid = np.asarray(
        [float(row["invalid_planned_corridor_fraction"]) for row in rows]
    )
    outputs = []

    figure, axis = plt.subplots(figsize=(8, 4.5), constrained_layout=True)
    for agent in sorted(set(uav)):
        keep = uav == agent
        axis.plot(time[keep], gate[keep], "o-", ms=3, label=f"UAV {agent}")
    axis.set(xlabel="Decision time (h)", ylabel="Adaptive gate", ylim=(-0.02, 1.02))
    axis.grid(alpha=0.25)
    axis.legend()
    target = output_dir / "gate_value_over_time.png"
    figure.savefig(target, dpi=180)
    plt.close(figure)
    outputs.append(target)

    figure, axis = plt.subplots(figsize=(8, 4.5), constrained_layout=True)
    order = np.arange(len(rows))
    axis.scatter(order, selected, s=16, label="Executed MAPPO action")
    valid = recommended >= 0
    axis.scatter(
        order[valid],
        recommended[valid],
        s=35,
        facecolors="none",
        edgecolors="#d62728",
        label="ALNS recommendation",
    )
    axis.set(xlabel="Decision record", ylabel="Flat action index")
    axis.grid(alpha=0.25)
    axis.legend()
    target = output_dir / "alns_recommendation_vs_action.png"
    figure.savefig(target, dpi=180)
    plt.close(figure)
    outputs.append(target)

    figure, axis_left = plt.subplots(
        figsize=(8, 4.5), constrained_layout=True
    )
    axis_right = axis_left.twinx()
    axis_left.plot(time, plan_age, color="#1f77b4", label="Plan age")
    axis_right.plot(
        time,
        invalid,
        color="#d62728",
        linestyle="--",
        label="Invalid corridor fraction",
    )
    axis_left.set(xlabel="Decision time (h)", ylabel="Normalized plan age")
    axis_right.set(ylabel="Invalid planned-corridor fraction", ylim=(-0.02, 1.02))
    axis_left.grid(alpha=0.25)
    lines = axis_left.lines + axis_right.lines
    axis_left.legend(lines, [line.get_label() for line in lines])
    target = output_dir / "plan_age_and_invalid_fraction.png"
    figure.savefig(target, dpi=180)
    plt.close(figure)
    outputs.append(target)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("diagnostics", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    for output in plot(args.diagnostics, args.output_dir):
        print(output)


if __name__ == "__main__":
    main()
