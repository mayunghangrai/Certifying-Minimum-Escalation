"""Fail-fast acceptance audit for a calibrated guidance-strength pilot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping


def evaluate_acceptance(
    metrics: Mapping[str, object],
    *,
    minimum_tv: float = 0.003,
    minimum_argmax_change: float = 0.01,
    maximum_argmax_change: float = 0.10,
    minimum_fresh_stale_gap: float = 0.05,
    maximum_saturation: float = 0.05,
) -> dict:
    """Evaluate gate validity and logistics performance without mutation."""
    adaptive_fixed_tv = float(
        metrics["matched_profile_median_adaptive_fixed_tv"]
    )
    adaptive_fixed_argmax = float(
        metrics["matched_profile_adaptive_fixed_argmax_rate"]
    )
    adaptive_unguided_argmax = float(
        metrics["matched_profile_adaptive_unguided_argmax_rate"]
    )
    fresh_stale_gap = float(
        metrics["matched_fresh_minus_stale_follow_rate"]
    )
    saturation = float(
        metrics["matched_recommended_probability_saturation_rate"]
    )
    performance = metrics.get("performance_by_branch", {})
    adaptive_performance = performance.get(
        "graph_mappo_adaptive_alns", {}
    )
    fixed_performance = performance.get("graph_mappo_fixed_alns", {})
    adaptive_cost = float(
        metrics.get(
            "adaptive_true_deprivation",
            adaptive_performance.get("mean_true_deprivation_cost", float("inf")),
        )
    )
    fixed_cost = float(
        metrics.get(
            "fixed_true_deprivation",
            fixed_performance.get("mean_true_deprivation_cost", -float("inf")),
        )
    )
    adaptive_fill = float(
        metrics.get(
            "adaptive_fill_rate",
            adaptive_performance.get("mean_fill_rate", -float("inf")),
        )
    )
    fixed_fill = float(
        metrics.get(
            "fixed_fill_rate",
            fixed_performance.get("mean_fill_rate", float("inf")),
        )
    )
    adaptive_reward = float(
        metrics.get(
            "adaptive_reward",
            adaptive_performance.get("mean_reward", -float("inf")),
        )
    )
    fixed_reward = float(
        metrics.get(
            "fixed_reward",
            fixed_performance.get("mean_reward", float("inf")),
        )
    )
    logistics_competitive = all(
        (
            adaptive_cost <= fixed_cost,
            adaptive_fill >= fixed_fill,
            adaptive_reward >= fixed_reward,
        )
    )
    checks = {
        "valid_run": not list(metrics.get("invalid_conditions", [])),
        "finite_nonzero_gate_gradients": bool(
            metrics.get("gate_gradients_finite_nonzero", False)
        ),
        "fresh_above_stale_gate": (
            float(metrics.get("paired_effect", 0.0)) >= 0.05
            and float(metrics.get("paired_ci_low", 0.0)) > 0.0
            and int(metrics.get("stale_regimes_below_fresh", 0)) >= 3
        ),
        "measurable_adaptive_fixed_influence": (
            adaptive_fixed_tv >= minimum_tv
            or adaptive_fixed_argmax >= minimum_argmax_change
        ),
        "controlled_adaptive_unguided_argmax_change": (
            minimum_argmax_change
            <= adaptive_unguided_argmax
            <= maximum_argmax_change
        ),
        "fresh_stale_follow_separation": (
            fresh_stale_gap >= minimum_fresh_stale_gap
        ),
        "non_saturated_recommendation_probability": (
            saturation <= maximum_saturation
        ),
        "no_catastrophic_performance_collapse": bool(
            metrics.get("development_stability_ok", False)
        ),
        "logistics_competitive_with_fixed_guidance": logistics_competitive,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "status": "PILOT_ACCEPTED" if not failed else "PILOT_REJECTED",
        "checks": checks,
        "failed_checks": failed,
        "thresholds": {
            "minimum_median_tv_adaptive_fixed": minimum_tv,
            "minimum_argmax_change_rate": minimum_argmax_change,
            "maximum_argmax_change_rate": maximum_argmax_change,
            "minimum_fresh_minus_stale_follow_rate": (
                minimum_fresh_stale_gap
            ),
            "maximum_probability_saturation_rate": maximum_saturation,
        },
        "observed": {
            "matched_profile_median_adaptive_fixed_tv": adaptive_fixed_tv,
            "matched_profile_adaptive_fixed_argmax_rate": (
                adaptive_fixed_argmax
            ),
            "matched_profile_adaptive_unguided_argmax_rate": (
                adaptive_unguided_argmax
            ),
            "matched_fresh_minus_stale_follow_rate": fresh_stale_gap,
            "matched_recommended_probability_saturation_rate": saturation,
            "adaptive_true_deprivation": adaptive_cost,
            "fixed_true_deprivation": fixed_cost,
            "adaptive_fill_rate": adaptive_fill,
            "fixed_fill_rate": fixed_fill,
            "adaptive_reward": adaptive_reward,
            "fixed_reward": fixed_reward,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results",
        type=Path,
        default=Path("results/gate_learning_beta_pilot"),
    )
    parser.add_argument("--minimum-tv", type=float, default=0.003)
    parser.add_argument("--minimum-argmax-change", type=float, default=0.01)
    parser.add_argument("--maximum-argmax-change", type=float, default=0.10)
    parser.add_argument("--minimum-fresh-stale-gap", type=float, default=0.05)
    parser.add_argument("--maximum-saturation", type=float, default=0.05)
    return parser


def main() -> int:
    args = _parser().parse_args()
    metrics_path = args.results / "validation" / "validation_metrics.json"
    if not metrics_path.is_file():
        raise FileNotFoundError(
            f"Run validation first; missing {metrics_path}"
        )
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    audit = evaluate_acceptance(
        metrics,
        minimum_tv=args.minimum_tv,
        minimum_argmax_change=args.minimum_argmax_change,
        maximum_argmax_change=args.maximum_argmax_change,
        minimum_fresh_stale_gap=args.minimum_fresh_stale_gap,
        maximum_saturation=args.maximum_saturation,
    )
    output = args.results / "guidance_pilot_acceptance.json"
    output.write_text(
        json.dumps(audit, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit, indent=2, sort_keys=True))
    print(f"acceptance audit -> {output.resolve()}")
    return 0 if audit["status"] == "PILOT_ACCEPTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
