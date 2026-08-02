"""Generate manuscript-ready figures from event-causal repair outputs."""

from __future__ import annotations

import argparse
import csv
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


METHOD_ORDER = (
    "Event-Causal Belief-Repair ALNS",
    "Certificate-Only Belief-Repair ALNS",
    "Proxy-Only Belief-Repair ALNS",
    "Optimistic-Bound-Screened Full Replan ALNS",
    "Periodic Full Replan ALNS",
    "Budget-Matched Periodic Full Replan ALNS",
    "Event-Priority Heuristic ALNS",
    "Full Event Replan ALNS",
    "Initial Plan Only",
)
SHORT_NAMES = {
    "Event-Causal Belief-Repair ALNS": "Event-causal\nrepair",
    "Certificate-Only Belief-Repair ALNS": "Certificate-\nonly",
    "Proxy-Only Belief-Repair ALNS": "Proxy-only\nrepair",
    "Optimistic-Bound-Screened Full Replan ALNS": "Bound-gated\nfull replan",
    "Periodic Full Replan ALNS": "Periodic\nfull replan",
    "Budget-Matched Periodic Full Replan ALNS": "Budget-matched\nperiodic",
    "Event-Priority Heuristic ALNS": "Event-priority\nheuristic",
    "Full Event Replan ALNS": "Every-event\nfull replan",
    "Initial Plan Only": "Initial plan\nonly",
}
COLORS = (
    "#176B87", "#2E86AB", "#6EB5C0", "#64CCC5", "#DAA520",
    "#E3B505", "#B85C38", "#8A8A8A", "#C0C0C0",
)
FIGURE_STEMS = (
    "fig_event_causal_performance",
    "fig_repair_trigger_scope",
    "fig_repair_outcomes",
)


def _read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Required experiment output not found: {path}")
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _finite(rows: Sequence[Dict[str, str]], key: str) -> List[float]:
    values = []
    for row in rows:
        try:
            value = float(row[key])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(value):
            values.append(value)
    return values


def _mean_ci(values: Sequence[float]):
    values = np.asarray(values, dtype=float)
    mean = float(np.mean(values))
    if len(values) < 2:
        return mean, 0.0
    return mean, float(1.96 * np.std(values, ddof=1) / np.sqrt(len(values)))


def _style_axis(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.7, alpha=0.7)
    ax.set_axisbelow(True)


def _save(fig, figures_dir: Path, stem: str) -> List[Path]:
    figures_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for suffix in (".png", ".pdf"):
        path = figures_dir / f"{stem}{suffix}"
        fig.savefig(
            path, dpi=300, bbox_inches="tight",
            facecolor="white")
        paths.append(path)
    plt.close(fig)
    return paths


def _performance_figure(
    episode_rows: Sequence[Dict[str, str]], figures_dir: Path,
) -> List[Path]:
    grouped = {
        method: [row for row in episode_rows if row["method"] == method]
        for method in METHOD_ORDER
    }
    fig, axes = plt.subplots(1, 2, figsize=(10.6, 4.2))
    x = np.arange(len(METHOD_ORDER))
    labels = [SHORT_NAMES[method] for method in METHOD_ORDER]
    for ax, metric, ylabel in (
        (axes[0], "J_composite", "Composite mission cost (lower is better)"),
        (axes[1], "fill_rate", "Relief-demand fill rate"),
    ):
        means, errors = zip(*[
            _mean_ci(_finite(grouped[method], metric))
            for method in METHOD_ORDER
        ])
        ax.bar(
            x, means, yerr=errors, capsize=4, width=0.7,
            color=COLORS, edgecolor="#333333", linewidth=0.6)
        ax.set_xticks(x, labels)
        ax.set_ylabel(ylabel)
        _style_axis(ax)
    axes[0].set_title("(a) Operational objective")
    axes[1].set_title("(b) Service performance")
    axes[1].set_ylim(
        0.0, min(1.05, max(1.0, axes[1].get_ylim()[1])))
    fig.suptitle("Paired-seed comparison of repair architectures", y=1.02)
    fig.tight_layout()
    return _save(fig, figures_dir, FIGURE_STEMS[0])


def _trigger_scope_figure(
    diagnostic_rows: Sequence[Dict[str, str]], figures_dir: Path,
) -> List[Path]:
    proposed_rows = [
        row for row in diagnostic_rows
        if row.get("method") == METHOD_ORDER[0]
    ]
    attempted = [
        row for row in proposed_rows
        if int(float(row.get("attempted", "0") or 0)) == 1
    ]
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.2))
    outcome_colors = {
        "installed_net_beneficial": "#176B87",
        "installed_positive_candidate": "#64CCC5",
        "installed_feasibility_repair": "#DAA520",
        "rejected_nonimproving_candidate": "#C44E52",
        "rejected_infeasible_candidate": "#8C2D04",
    }
    outcomes = sorted({row.get("outcome", "") for row in attempted})
    for outcome in outcomes:
        selected = [row for row in attempted if row.get("outcome") == outcome]
        x = _finite(selected, "potential_gain_bound")
        y = _finite(selected, "actual_improvement")
        axes[0].scatter(
            x, y, s=25, alpha=0.75,
            color=outcome_colors.get(outcome, "#777777"),
            label=outcome.replace("_", " "))
    if attempted:
        solve_costs = _finite(attempted, "solve_cost")
        if solve_costs:
            axes[0].axhline(
                float(np.median(solve_costs)), color="#222222",
                linestyle="--", linewidth=1.0, label="median solve cost")
    axes[0].set_xlabel("Optimistic improvement bound")
    axes[0].set_ylabel("Realized belief-side improvement")
    axes[0].set_title("(a) Trigger conservatism")
    _style_axis(axes[0])
    if outcomes:
        axes[0].legend(frameon=False, fontsize=7, loc="best")

    by_event = defaultdict(list)
    for row in proposed_rows:
        value = _finite([row], "repair_scope_fraction")
        if value:
            by_event[row.get("event_kind", "unknown")].append(value[0])
    events = sorted(by_event)
    if events:
        axes[1].boxplot(
            [by_event[event] for event in events],
            tick_labels=[event.replace("_", "\n") for event in events],
            patch_artist=True,
            boxprops={"facecolor": "#B7E4E1", "edgecolor": "#176B87"},
            medianprops={"color": "#8C2D04", "linewidth": 1.5},
            whiskerprops={"color": "#176B87"},
            capprops={"color": "#176B87"},
            flierprops={
                "marker": "o", "markersize": 3,
                "markerfacecolor": "#DAA520", "markeredgecolor": "none",
            },
        )
    axes[1].set_ylim(-0.03, 1.03)
    axes[1].set_ylabel("Fraction of future decisions made mutable")
    axes[1].set_title("(b) Localized repair scope")
    axes[1].tick_params(axis="x", labelsize=7)
    _style_axis(axes[1])
    fig.tight_layout()
    return _save(fig, figures_dir, FIGURE_STEMS[1])


def _outcomes_figure(
    episode_rows: Sequence[Dict[str, str]],
    diagnostic_rows: Sequence[Dict[str, str]],
    figures_dir: Path,
) -> List[Path]:
    fig, axes = plt.subplots(1, 3, figsize=(13.8, 4.2))
    event_outcomes = defaultdict(Counter)
    for row in diagnostic_rows:
        if row.get("method") != METHOD_ORDER[0]:
            continue
        event_outcomes[row.get("event_kind", "unknown")][
            row.get("outcome", "unknown")
        ] += 1
    events = sorted(event_outcomes)
    outcome_order = (
        "certified_continue",
        "continue_no_relevant_change",
        "continue_event_impact_below_threshold",
        "continue_event_impact_below_cost",
        "continue_budget_exhausted",
        "installed_net_beneficial",
        "installed_positive_candidate",
        "installed_feasibility_repair",
        "rejected_nonimproving_candidate",
        "rejected_infeasible_candidate",
    )
    bottoms = np.zeros(len(events))
    palette = (
        "#BDBDBD", "#E0E0E0", "#FDBF6F", "#F4A261", "#969696",
        "#176B87", "#64CCC5", "#DAA520", "#E8A09A", "#8C2D04",
    )
    for outcome, color in zip(outcome_order, palette):
        values = np.array([
            event_outcomes[event][outcome] for event in events])
        if values.sum() == 0:
            continue
        axes[0].bar(
            np.arange(len(events)), values, bottom=bottoms,
            color=color, label=outcome.replace("_", " "))
        bottoms += values
    axes[0].set_xticks(
        np.arange(len(events)),
        [event.replace("_", "\n") for event in events])
    axes[0].set_ylabel("Decision-event count")
    axes[0].set_title("(a) Screen and repair outcomes")
    axes[0].tick_params(axis="x", labelsize=7)
    _style_axis(axes[0])
    if events:
        axes[0].legend(
            frameon=False, fontsize=6.5, ncol=2, loc="upper right")

    grouped = {
        method: [row for row in episode_rows if row["method"] == method]
        for method in METHOD_ORDER
    }
    means, errors = zip(*[
        _mean_ci(_finite(grouped[method], "n_resolves"))
        for method in METHOD_ORDER
    ])
    x = np.arange(len(METHOD_ORDER))
    axes[1].bar(
        x, means, yerr=errors, capsize=4, width=0.7,
        color=COLORS, edgecolor="#333333", linewidth=0.6)
    axes[1].set_xticks(
        x, [SHORT_NAMES[method] for method in METHOD_ORDER])
    axes[1].set_ylabel("ALNS invocations per episode")
    axes[1].set_title("(b) Repair invocations")
    _style_axis(axes[1])

    time_means, time_errors = zip(*[
        _mean_ci(_finite(grouped[method], "repair_wall_time_s"))
        for method in METHOD_ORDER
    ])
    axes[2].bar(
        x, time_means, yerr=time_errors, capsize=4, width=0.7,
        color=COLORS, edgecolor="#333333", linewidth=0.6)
    axes[2].set_xticks(
        x, [SHORT_NAMES[method] for method in METHOD_ORDER])
    axes[2].set_ylabel("Online repair wall time per episode [s]")
    axes[2].set_title("(c) Measured repair time")
    _style_axis(axes[2])
    fig.tight_layout()
    return _save(fig, figures_dir, FIGURE_STEMS[2])


def plot(output_dir: Path) -> List[Path]:
    output_dir = Path(output_dir)
    episode_rows = _read_csv(output_dir / "episode_metrics.csv")
    diagnostic_rows = _read_csv(output_dir / "repair_diagnostics.csv")
    figures_dir = output_dir / "figures"
    paths = []
    paths.extend(_performance_figure(episode_rows, figures_dir))
    paths.extend(_trigger_scope_figure(diagnostic_rows, figures_dir))
    paths.extend(_outcomes_figure(
        episode_rows, diagnostic_rows, figures_dir))
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir", type=Path,
        default=Path("results/event_causal_repair"))
    args = parser.parse_args()
    for path in plot(args.input_dir):
        print(path.resolve())


if __name__ == "__main__":
    main()
