"""Calibrate ALNS guidance strength offline from saved matched policy states.

No environment replay, sampling, optimizer update, or checkpoint mutation is
performed.  The script evaluates the exact one-hot FOLLOW logit intervention

    hybrid_logits = base_logits + beta * gate * alns_prior

for controlled matched profiles and recommends the smallest tested beta that
creates measurable but non-saturated policy influence in the intended
fresh-above-stale direction.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from pathlib import Path
from typing import Dict, Iterable, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


DEFAULT_BETAS = (0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0)
FRESH_PROFILE = "fresh_valid_plan"
STALE_PROFILE = "combined_stale_deviated"
SWEEP_FIELDS = (
    "beta",
    "state_profile_count",
    "median_tv_adaptive_fixed",
    "median_tv_adaptive_unguided",
    "adaptive_fixed_argmax_change_rate",
    "adaptive_unguided_argmax_change_rate",
    "adaptive_follow_rate",
    "fixed_follow_rate",
    "unguided_follow_rate",
    "fresh_adaptive_follow_rate",
    "combined_stale_adaptive_follow_rate",
    "fresh_minus_stale_follow_rate",
    "recommended_probability_saturation_rate",
    "measurable_adaptive_fixed",
    "controlled_adaptive_unguided",
    "fresh_stale_separation",
    "non_saturated",
    "eligible",
)


def _read_csv(path: Path) -> list[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    fields: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _parse_betas(value: str | None) -> list[float] | None:
    if value is None:
        return None
    values = sorted({float(item.strip()) for item in value.split(",")})
    if not values or values[0] < 0.0 or not all(math.isfinite(v) for v in values):
        raise ValueError("All beta candidates must be finite and nonnegative")
    return values


def _masked_softmax(logits: np.ndarray, mask: np.ndarray) -> np.ndarray:
    feasible = np.asarray(mask, dtype=bool)
    if not feasible.any():
        raise ValueError("Matched state has no feasible action")
    values = np.asarray(logits, dtype=float).copy()
    values[~feasible] = -np.inf
    maximum = float(np.max(values[feasible]))
    probabilities = np.zeros_like(values)
    probabilities[feasible] = np.exp(values[feasible] - maximum)
    probabilities /= probabilities.sum()
    return probabilities


def load_calibration_states(validation_dir: Path) -> Dict[str, np.ndarray]:
    """Load and validate the canonical matched-state calibration table."""
    vector_path = validation_dir / "matched_state_vectors.jsonl.gz"
    pair_path = validation_dir / "matched_state_pairs.csv"
    if not vector_path.is_file() or not pair_path.is_file():
        raise FileNotFoundError(
            "Calibration requires matched_state_vectors.jsonl.gz and "
            "matched_state_pairs.csv from final validation"
        )
    pair_rows = _read_csv(pair_path)
    gate_lookup = {
        (int(row["decision_index"]), row["profile"]): float(
            row["gate_adaptive"]
        )
        for row in pair_rows
    }
    records = []
    with gzip.open(vector_path, "rt", encoding="utf-8") as handle:
        for line in handle:
            payload = json.loads(line)
            decision_index = int(payload["decision_index"])
            profile = str(payload["profile"])
            key = (decision_index, profile)
            if key not in gate_lookup:
                raise AssertionError(f"Missing gate for matched state {key}")
            logits = np.asarray(payload["base_logits"], dtype=float)
            prior = np.asarray(payload["alns_prior"], dtype=float)
            mask = np.asarray(payload["action_mask"], dtype=bool)
            if not (len(logits) == len(prior) == len(mask)):
                raise AssertionError(f"Action dimension mismatch for {key}")
            nonzero = np.flatnonzero(prior > 0.0)
            if len(nonzero) != 1 or not np.isclose(prior[nonzero[0]], 1.0):
                raise AssertionError(
                    f"Expected one-hot ALNS prior for matched state {key}"
                )
            recommended = int(nonzero[0])
            if not mask[recommended]:
                raise AssertionError(
                    f"ALNS recommendation is infeasible for matched state {key}"
                )
            base_probability = _masked_softmax(logits, mask)
            other_logits = logits.copy()
            other_logits[~mask] = -np.inf
            other_logits[recommended] = -np.inf
            gap = max(
                float(np.max(other_logits) - logits[recommended]),
                0.0,
            )
            records.append(
                {
                    "decision_index": decision_index,
                    "profile": profile,
                    "gate": gate_lookup[key],
                    "base_recommended_probability": float(
                        base_probability[recommended]
                    ),
                    "base_follows": int(
                        recommended == int(np.argmax(base_probability))
                    ),
                    "logit_gap": gap,
                }
            )
    if not records:
        raise ValueError("No matched calibration states were loaded")
    profiles = {row["profile"] for row in records}
    for required in (FRESH_PROFILE, STALE_PROFILE):
        if required not in profiles:
            raise AssertionError(f"Missing required matched profile: {required}")
    return {
        "decision_index": np.asarray(
            [row["decision_index"] for row in records], dtype=int
        ),
        "profile": np.asarray([row["profile"] for row in records], dtype=object),
        "gate": np.asarray([row["gate"] for row in records], dtype=float),
        "base_probability": np.asarray(
            [row["base_recommended_probability"] for row in records],
            dtype=float,
        ),
        "base_follows": np.asarray(
            [row["base_follows"] for row in records], dtype=bool
        ),
        "logit_gap": np.asarray(
            [row["logit_gap"] for row in records], dtype=float
        ),
    }


def _boosted_probability(
    base_probability: np.ndarray, boost: np.ndarray
) -> np.ndarray:
    """Return recommended-action probability after a one-hot logit boost."""
    exponent = np.exp(np.clip(boost, -50.0, 50.0))
    numerator = base_probability * exponent
    return numerator / (1.0 + base_probability * (exponent - 1.0))


def derive_beta_candidates(
    states: Mapping[str, np.ndarray],
) -> list[float]:
    """Add data-derived fresh break-even quantiles to the coarse beta grid."""
    fresh = states["profile"] == FRESH_PROFILE
    gate = states["gate"][fresh]
    gaps = states["logit_gap"][fresh]
    positive = gate > 1e-12
    break_even = gaps[positive] / gate[positive]
    if not len(break_even):
        return list(DEFAULT_BETAS)
    quantiles = np.quantile(
        break_even,
        [0.0, 0.01, 0.025, 0.05, 0.075, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95],
    )
    candidates = set(DEFAULT_BETAS)
    for value in quantiles:
        candidates.add(round(float(value), 4))
        candidates.add(round(float(value) + 0.0001, 4))
    return sorted(value for value in candidates if value >= 0.0)


def evaluate_beta(
    states: Mapping[str, np.ndarray],
    beta: float,
    *,
    minimum_tv: float,
    minimum_argmax_change: float,
    maximum_argmax_change: float,
    minimum_fresh_stale_gap: float,
    maximum_saturation: float,
) -> Dict[str, object]:
    gate = states["gate"]
    base_probability = states["base_probability"]
    gap = states["logit_gap"]
    base_follows = states["base_follows"]
    adaptive_probability = _boosted_probability(
        base_probability, beta * gate
    )
    fixed_probability = _boosted_probability(
        base_probability, np.full_like(gate, beta * 0.5)
    )
    adaptive_follows = base_follows | (beta * gate >= gap - 1e-12)
    fixed_follows = base_follows | (beta * 0.5 >= gap - 1e-12)
    adaptive_fixed_change = adaptive_follows != fixed_follows
    adaptive_unguided_change = adaptive_follows != base_follows
    fresh = states["profile"] == FRESH_PROFILE
    stale = states["profile"] == STALE_PROFILE
    fresh_follow = float(np.mean(adaptive_follows[fresh]))
    stale_follow = float(np.mean(adaptive_follows[stale]))
    median_tv_fixed = float(
        np.median(np.abs(adaptive_probability - fixed_probability))
    )
    median_tv_unguided = float(
        np.median(np.abs(adaptive_probability - base_probability))
    )
    fixed_change_rate = float(np.mean(adaptive_fixed_change))
    unguided_change_rate = float(np.mean(adaptive_unguided_change))
    saturation = float(np.mean(adaptive_probability > 0.95))
    measurable = (
        median_tv_fixed >= minimum_tv
        or fixed_change_rate >= minimum_argmax_change
    )
    controlled = (
        minimum_argmax_change
        <= unguided_change_rate
        <= maximum_argmax_change
    )
    separated = fresh_follow - stale_follow >= minimum_fresh_stale_gap
    non_saturated = saturation <= maximum_saturation
    return {
        "beta": float(beta),
        "state_profile_count": int(len(gate)),
        "median_tv_adaptive_fixed": median_tv_fixed,
        "median_tv_adaptive_unguided": median_tv_unguided,
        "adaptive_fixed_argmax_change_rate": fixed_change_rate,
        "adaptive_unguided_argmax_change_rate": unguided_change_rate,
        "adaptive_follow_rate": float(np.mean(adaptive_follows)),
        "fixed_follow_rate": float(np.mean(fixed_follows)),
        "unguided_follow_rate": float(np.mean(base_follows)),
        "fresh_adaptive_follow_rate": fresh_follow,
        "combined_stale_adaptive_follow_rate": stale_follow,
        "fresh_minus_stale_follow_rate": fresh_follow - stale_follow,
        "recommended_probability_saturation_rate": saturation,
        "measurable_adaptive_fixed": int(measurable),
        "controlled_adaptive_unguided": int(controlled),
        "fresh_stale_separation": int(separated),
        "non_saturated": int(non_saturated),
        "eligible": int(
            measurable and controlled and separated and non_saturated
        ),
    }


def break_even_rows(
    states: Mapping[str, np.ndarray],
) -> list[Dict[str, object]]:
    rows = []
    for index in range(len(states["gate"])):
        gate = float(states["gate"][index])
        gap = float(states["logit_gap"][index])
        rows.append(
            {
                "decision_index": int(states["decision_index"][index]),
                "profile": str(states["profile"][index]),
                "adaptive_gate": gate,
                "base_recommended_probability": float(
                    states["base_probability"][index]
                ),
                "base_follows_recommendation": int(
                    states["base_follows"][index]
                ),
                "recommended_action_logit_gap": gap,
                "adaptive_break_even_beta": (
                    gap / gate if gate > 1e-12 else ""
                ),
                "fixed_break_even_beta": gap / 0.5,
            }
        )
    return rows


def _plot_sweep(
    rows: Sequence[Mapping[str, object]],
    recommended_beta: float | None,
    path: Path,
) -> None:
    beta = np.asarray([row["beta"] for row in rows], dtype=float)
    with plt.rc_context(
        {
            "font.family": "DejaVu Sans",
            "axes.grid": True,
            "grid.alpha": 0.25,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    ):
        fig, axes = plt.subplots(
            2, 2, figsize=(12.5, 8.2), dpi=160, constrained_layout=True
        )
        axes[0, 0].plot(
            beta,
            [row["median_tv_adaptive_fixed"] for row in rows],
            marker="o",
            label="adaptive vs fixed",
        )
        axes[0, 0].plot(
            beta,
            [row["median_tv_adaptive_unguided"] for row in rows],
            marker="s",
            label="adaptive vs unguided",
        )
        axes[0, 0].axhline(0.003, color="#d62828", linestyle="--")
        axes[0, 0].set(ylabel="Median total variation", title="Policy distance")
        axes[0, 0].legend(fontsize=8)

        axes[0, 1].plot(
            beta,
            [
                100.0 * row["adaptive_fixed_argmax_change_rate"]
                for row in rows
            ],
            marker="o",
            label="adaptive vs fixed",
        )
        axes[0, 1].plot(
            beta,
            [
                100.0 * row["adaptive_unguided_argmax_change_rate"]
                for row in rows
            ],
            marker="s",
            label="adaptive vs unguided",
        )
        axes[0, 1].axhspan(1.0, 10.0, color="#2a9d8f", alpha=0.12)
        axes[0, 1].set(ylabel="Argmax change [%]", title="Action influence")
        axes[0, 1].legend(fontsize=8)

        axes[1, 0].plot(
            beta,
            [100.0 * row["fresh_adaptive_follow_rate"] for row in rows],
            marker="o",
            label="fresh/feasible",
        )
        axes[1, 0].plot(
            beta,
            [
                100.0 * row["combined_stale_adaptive_follow_rate"]
                for row in rows
            ],
            marker="s",
            label="combined stale/deviated",
        )
        axes[1, 0].set(
            xlabel="Guidance beta",
            ylabel="ALNS-following argmax rate [%]",
            title="Intended regime separation",
        )
        axes[1, 0].legend(fontsize=8)

        axes[1, 1].plot(
            beta,
            [
                100.0 * row["recommended_probability_saturation_rate"]
                for row in rows
            ],
            marker="o",
            color="#e76f51",
        )
        axes[1, 1].axhline(5.0, color="#d62828", linestyle="--")
        axes[1, 1].set(
            xlabel="Guidance beta",
            ylabel="Recommended probability > 0.95 [%]",
            title="Guidance saturation",
        )
        if recommended_beta is not None:
            for ax in axes.flat:
                ax.axvline(
                    recommended_beta,
                    color="#6a4c93",
                    linestyle=":",
                    linewidth=1.5,
                )
        fig.suptitle(
            "Offline ALNS guidance-strength calibration",
            fontsize=13,
            fontweight="bold",
        )
        fig.savefig(path, facecolor="white")
        plt.close(fig)


def _plot_break_even(
    rows: Sequence[Mapping[str, object]],
    path: Path,
) -> None:
    with plt.rc_context(
        {
            "font.family": "DejaVu Sans",
            "axes.grid": True,
            "grid.alpha": 0.25,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    ):
        fig, ax = plt.subplots(figsize=(8.8, 5.5), dpi=160, constrained_layout=True)
        for profile, label, color in (
            (FRESH_PROFILE, "fresh/feasible", "#2a9d8f"),
            (STALE_PROFILE, "combined stale/deviated", "#d62828"),
        ):
            values = sorted(
                float(row["adaptive_break_even_beta"])
                for row in rows
                if row["profile"] == profile
                and row["adaptive_break_even_beta"] != ""
            )
            y = np.arange(1, len(values) + 1) / max(len(values), 1)
            ax.plot(values, y, label=label, color=color, linewidth=2)
        ax.set(
            xlabel="Break-even beta for ALNS recommendation to become argmax",
            ylabel="Empirical cumulative fraction",
            title="Matched-state guidance break-even distribution",
        )
        ax.legend()
        fig.savefig(path, facecolor="white")
        plt.close(fig)


def calibrate(
    *,
    validation_dir: Path,
    output_dir: Path,
    betas: Sequence[float] | None = None,
    minimum_tv: float = 0.003,
    minimum_argmax_change: float = 0.01,
    maximum_argmax_change: float = 0.10,
    minimum_fresh_stale_gap: float = 0.05,
    maximum_saturation: float = 0.05,
) -> Dict[str, object]:
    states = load_calibration_states(validation_dir)
    candidates = (
        sorted({float(value) for value in betas})
        if betas is not None
        else derive_beta_candidates(states)
    )
    sweep = [
        evaluate_beta(
            states,
            beta,
            minimum_tv=minimum_tv,
            minimum_argmax_change=minimum_argmax_change,
            maximum_argmax_change=maximum_argmax_change,
            minimum_fresh_stale_gap=minimum_fresh_stale_gap,
            maximum_saturation=maximum_saturation,
        )
        for beta in candidates
    ]
    eligible = [row for row in sweep if row["eligible"]]
    recommended = min(eligible, key=lambda row: row["beta"]) if eligible else None
    break_even = break_even_rows(states)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "guidance_strength_sweep.csv", sweep, SWEEP_FIELDS)
    _write_csv(
        output_dir / "guidance_break_even.csv",
        break_even,
        (
            "decision_index",
            "profile",
            "adaptive_gate",
            "base_recommended_probability",
            "base_follows_recommendation",
            "recommended_action_logit_gap",
            "adaptive_break_even_beta",
            "fixed_break_even_beta",
        ),
    )
    recommendation = {
        "status": "RECOMMENDED_BETA_FOUND" if recommended else "NO_SAFE_BETA",
        "recommended_beta": (
            float(recommended["beta"]) if recommended else None
        ),
        "recommended_metrics": recommended,
        "acceptance_thresholds": {
            "minimum_median_tv_adaptive_fixed": minimum_tv,
            "minimum_argmax_change_rate": minimum_argmax_change,
            "maximum_argmax_change_rate": maximum_argmax_change,
            "minimum_fresh_minus_stale_follow_rate": minimum_fresh_stale_gap,
            "maximum_probability_saturation_rate": maximum_saturation,
        },
        "candidate_betas": candidates,
        "state_profile_count": int(len(states["gate"])),
        "source_validation_dir": str(validation_dir.resolve()),
        "method": (
            "deterministic offline one-hot logit intervention; no replay, "
            "sampling, training, or checkpoint mutation"
        ),
    }
    _write_json(
        output_dir / "guidance_strength_recommendation.json",
        recommendation,
    )
    _plot_sweep(
        sweep,
        recommendation["recommended_beta"],
        output_dir / "guidance_strength_sweep.png",
    )
    _plot_break_even(
        break_even,
        output_dir / "guidance_break_even_distribution.png",
    )
    return recommendation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validation-dir",
        type=Path,
        default=Path("results/gate_learning_final/validation"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/guidance_strength_calibration"),
    )
    parser.add_argument(
        "--betas",
        help=(
            "Optional comma-separated beta candidates. By default, coarse "
            "values and data-derived fresh break-even quantiles are tested."
        ),
    )
    parser.add_argument("--minimum-tv", type=float, default=0.003)
    parser.add_argument("--minimum-argmax-change", type=float, default=0.01)
    parser.add_argument("--maximum-argmax-change", type=float, default=0.10)
    parser.add_argument("--minimum-fresh-stale-gap", type=float, default=0.05)
    parser.add_argument("--maximum-saturation", type=float, default=0.05)
    return parser


def main() -> int:
    args = _parser().parse_args()
    recommendation = calibrate(
        validation_dir=args.validation_dir,
        output_dir=args.output,
        betas=_parse_betas(args.betas),
        minimum_tv=args.minimum_tv,
        minimum_argmax_change=args.minimum_argmax_change,
        maximum_argmax_change=args.maximum_argmax_change,
        minimum_fresh_stale_gap=args.minimum_fresh_stale_gap,
        maximum_saturation=args.maximum_saturation,
    )
    print(json.dumps(recommendation, indent=2, sort_keys=True))
    if recommendation["status"] != "RECOMMENDED_BETA_FOUND":
        raise SystemExit(2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
