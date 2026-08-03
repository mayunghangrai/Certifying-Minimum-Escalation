"""Run one paired adaptive causal-mix ALNS experiment family."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence

import numpy as np
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from env.params import EnvParams  # noqa: E402
from env.scenario_generator import generate_scenario  # noqa: E402
from env.uav_env import UAMTVRPIUEnv  # noqa: E402
from methods.event_causal_repair import (  # noqa: E402
    AdaptiveCausalMixRepairController,
    OptimisticBoundScreenedFullReplanController,
    PeriodicFullReplanController,
    SoftBoundaryEventCausalRepairController,
)
from run_event_causal_repair_experiment import (  # noqa: E402
    _provenance_manifest,
    _run_episode,
    _sha256_file,
    _write_csv,
)
from run_soft_boundary_experiment import (  # noqa: E402
    _aggregate,
    _paired_rows,
)


PRIMARY = "Adaptive Causal-Mix ALNS"
FIXED_CAUSAL = "Fixed Causal-Bias Soft-Boundary ALNS"
SAME_RULE_GLOBAL = "Same-Trigger-Rule Uniform Full Replan ALNS"
EXOGENOUS_ADAPTIVE = "Exogenous-Gated Adaptive Causal-Mix ALNS"
EXOGENOUS_GLOBAL = "Exogenous-Gated Uniform Full Replan ALNS"
BUDGET_REFERENCE = "Budget-Matched K18 Periodic Full Replan ALNS"
WALL_REFERENCE = "Approx-Wall-Matched K18 Periodic ALNS"
SPARSE_PERIODIC = "2-Hour Periodic Full Replan ALNS"


def _candidate_name(decay: float, minimum_probability: float) -> str:
    return (
        f"Adaptive Mix d={decay:.2f} "
        f"pmin={minimum_probability:.2f}"
    )


def _controllers(
    mode: str,
    solve_cost,
    proxy_threshold_fraction: float,
    budget_pacing: bool,
    periodic_replan_period: float,
    matched_periodic_target_count: int,
    wall_matched_iterations: int,
    adaptive_reaction: float,
    development_decays: Sequence[float],
    development_min_probabilities: Sequence[float],
    selected_decay: float | None,
    selected_min_probability: float | None,
):
    if mode == "screen":
        controllers = [
            AdaptiveCausalMixRepairController(
                solve_cost=solve_cost,
                proxy_threshold_fraction=proxy_threshold_fraction,
                causal_decay=decay,
                adaptive_reaction=adaptive_reaction,
                adaptive_min_probability=minimum_probability,
                gate_fleet_service_triggers=False,
                budget_pacing=budget_pacing,
                name=_candidate_name(decay, minimum_probability),
            )
            for decay in development_decays
            for minimum_probability in development_min_probabilities
        ]
        controllers.append(PeriodicFullReplanController(
            solve_cost=solve_cost,
            target_count=matched_periodic_target_count,
            name=BUDGET_REFERENCE,
        ))
        return controllers

    if selected_decay is None or selected_min_probability is None:
        raise ValueError(
            "confirmation/final mode requires selected decay and "
            "minimum probability"
        )

    adaptive = AdaptiveCausalMixRepairController(
        solve_cost=solve_cost,
        proxy_threshold_fraction=proxy_threshold_fraction,
        causal_decay=selected_decay,
        adaptive_reaction=adaptive_reaction,
        adaptive_min_probability=selected_min_probability,
        gate_fleet_service_triggers=False,
        budget_pacing=budget_pacing,
        name=PRIMARY,
    )
    fixed = SoftBoundaryEventCausalRepairController(
        solve_cost=solve_cost,
        proxy_threshold_fraction=proxy_threshold_fraction,
        boundary_decay=selected_decay,
        gate_fleet_service_triggers=False,
        budget_pacing=budget_pacing,
        name=FIXED_CAUSAL,
    )
    global_same_rule = OptimisticBoundScreenedFullReplanController(
        solve_cost=solve_cost,
        proxy_threshold_fraction=proxy_threshold_fraction,
        trigger_mode="proxy",
        gate_fleet_service_triggers=False,
        budget_pacing=budget_pacing,
    )
    global_same_rule.name = SAME_RULE_GLOBAL
    exogenous_adaptive = AdaptiveCausalMixRepairController(
        solve_cost=solve_cost,
        proxy_threshold_fraction=proxy_threshold_fraction,
        causal_decay=selected_decay,
        adaptive_reaction=adaptive_reaction,
        adaptive_min_probability=selected_min_probability,
        gate_fleet_service_triggers=True,
        budget_pacing=budget_pacing,
        name=EXOGENOUS_ADAPTIVE,
    )
    exogenous_global = OptimisticBoundScreenedFullReplanController(
        solve_cost=solve_cost,
        proxy_threshold_fraction=proxy_threshold_fraction,
        trigger_mode="proxy",
        gate_fleet_service_triggers=True,
        budget_pacing=budget_pacing,
    )
    exogenous_global.name = EXOGENOUS_GLOBAL
    return [
        adaptive,
        fixed,
        global_same_rule,
        exogenous_adaptive,
        exogenous_global,
        PeriodicFullReplanController(
            solve_cost=solve_cost,
            target_count=matched_periodic_target_count,
            name=BUDGET_REFERENCE,
        ),
        PeriodicFullReplanController(
            solve_cost=solve_cost,
            target_count=matched_periodic_target_count,
            iterations_override=wall_matched_iterations,
            name=WALL_REFERENCE,
        ),
        PeriodicFullReplanController(
            solve_cost=solve_cost,
            period_hours=periodic_replan_period,
            name=SPARSE_PERIODIC,
        ),
    ]


def main() -> None:
    started_at = datetime.now(timezone.utc).isoformat()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--method-config",
        type=Path,
        default=Path(
            "configs/method/adaptive_causal_mix_development.yaml"
        ),
    )
    parser.add_argument(
        "--mode", choices=("screen", "confirm", "final"), required=True,
    )
    parser.add_argument("--seed-start", type=int, required=True)
    parser.add_argument("--n-seeds", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--selected-decay", type=float, default=None)
    parser.add_argument(
        "--selected-min-probability", type=float, default=None,
    )
    args = parser.parse_args()

    params = EnvParams.from_yaml(str(args.config))
    payload = yaml.safe_load(
        args.method_config.read_text(encoding="utf-8")
    )["method"]
    params.hybrid.K_max = int(payload["repair_budget"])
    params.hybrid.alns_iterations = int(payload["alns_iterations"])
    solve_cost = payload.get("solve_cost")
    threshold = float(payload["proxy_threshold_fraction"])
    budget_pacing = bool(payload["budget_pacing"])
    period = float(payload["periodic_replan_period"])
    matched_count = int(payload["matched_periodic_target_count"])
    wall_iterations = int(payload["wall_matched_alns_iterations"])
    reaction = float(payload["adaptive_reaction"])
    decays = [
        float(value) for value in payload["development_causal_decays"]
    ]
    minimum_probabilities = [
        float(value)
        for value in payload["development_min_probabilities"]
    ]
    randomize = bool(payload.get("randomize_method_order", True))
    selected_decay = (
        args.selected_decay
        if args.selected_decay is not None
        else payload.get("selected_causal_decay")
    )
    selected_min_probability = (
        args.selected_min_probability
        if args.selected_min_probability is not None
        else payload.get("selected_min_probability")
    )
    if selected_decay is not None:
        selected_decay = float(selected_decay)
    if selected_min_probability is not None:
        selected_min_probability = float(selected_min_probability)
    if any(not 0.0 < value <= 1.0 for value in decays):
        raise ValueError("development decays must be in (0, 1]")
    if any(not 0.0 <= value < 0.5 for value in minimum_probabilities):
        raise ValueError("minimum probabilities must be in [0, 0.5)")
    if args.n_seeds < 1:
        raise ValueError("--n-seeds must be positive")

    seeds = list(range(args.seed_start, args.seed_start + args.n_seeds))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    episode_rows: List[Dict[str, object]] = []
    diagnostic_rows: List[Dict[str, object]] = []

    for seed_index, seed in enumerate(seeds, start=1):
        scenario = generate_scenario(seed, params)
        controllers = _controllers(
            mode=args.mode,
            solve_cost=solve_cost,
            proxy_threshold_fraction=threshold,
            budget_pacing=budget_pacing,
            periodic_replan_period=period,
            matched_periodic_target_count=matched_count,
            wall_matched_iterations=wall_iterations,
            adaptive_reaction=reaction,
            development_decays=decays,
            development_min_probabilities=minimum_probabilities,
            selected_decay=selected_decay,
            selected_min_probability=selected_min_probability,
        )
        if randomize and len(controllers) > 1:
            rng = np.random.default_rng(seed + 294_491)
            rng.shuffle(controllers)
        for execution_index, controller in enumerate(controllers, start=1):
            row, diagnostics, _ = _run_episode(
                UAMTVRPIUEnv(params), scenario, controller
            )
            row["execution_order"] = execution_index
            episode_rows.append(row)
            diagnostic_rows.extend(diagnostics)
            print(
                f"seed {seed} [{seed_index}/{len(seeds)}] "
                f"{controller.name:<48} dep={row['J_dep_true']:.1f} "
                f"calls={row['repair_solver_calls']} "
                f"fill={row['fill_rate']:.3f}",
                flush=True,
            )

    methods = list(dict.fromkeys(
        str(row["method"]) for row in episode_rows
    ))
    references = [BUDGET_REFERENCE] if args.mode == "screen" else [
        PRIMARY,
        FIXED_CAUSAL,
        SAME_RULE_GLOBAL,
        EXOGENOUS_ADAPTIVE,
        EXOGENOUS_GLOBAL,
        BUDGET_REFERENCE,
        WALL_REFERENCE,
        SPARSE_PERIODIC,
    ]
    paired = _paired_rows(episode_rows, references)
    _write_csv(args.output_dir / "episode_metrics.csv", episode_rows)
    _write_csv(args.output_dir / "repair_diagnostics.csv", diagnostic_rows)
    _write_csv(args.output_dir / "pairwise_comparisons.csv", paired)

    settings = {
        "mode": args.mode,
        "seed_start": args.seed_start,
        "n_seeds": args.n_seeds,
        "repair_budget": params.hybrid.K_max,
        "alns_iterations": params.hybrid.alns_iterations,
        "wall_matched_alns_iterations": wall_iterations,
        "solve_cost": solve_cost,
        "proxy_threshold_fraction": threshold,
        "trigger_mode": "proxy",
        "budget_pacing": budget_pacing,
        "periodic_replan_period": period,
        "matched_periodic_target_count": matched_count,
        "adaptive_reaction": reaction,
        "development_causal_decays": decays,
        "development_min_probabilities": minimum_probabilities,
        "selected_causal_decay": selected_decay,
        "selected_min_probability": selected_min_probability,
        "randomize_method_order": randomize,
    }
    summary = {
        "methods": methods,
        "seeds": seeds,
        "environment": params.to_dict(),
        "method": settings,
        "aggregate": _aggregate(episode_rows),
        "diagnostic_rows": len(diagnostic_rows),
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (args.output_dir / "resolved_config.yaml").write_text(
        yaml.safe_dump(
            {"environment": params.to_dict(), "method": settings},
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    provenance = _provenance_manifest(
        env_config_path=args.config,
        method_config_path=args.method_config,
        output_dir=args.output_dir,
        seeds=seeds,
        method_settings=settings,
    )
    cycle_runner = Path(__file__).resolve()
    provenance["files"]["cycle_runner"] = {
        "path": str(cycle_runner),
        "sha256": _sha256_file(cycle_runner),
    }
    provenance["started_at_utc"] = started_at
    provenance["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    (args.output_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2), encoding="utf-8"
    )

    output_names = [
        "episode_metrics.csv",
        "repair_diagnostics.csv",
        "pairwise_comparisons.csv",
        "summary.json",
        "resolved_config.yaml",
        "provenance.json",
    ]
    manifest = {
        "command": " ".join(sys.argv),
        "files": output_names,
        "file_sha256": {
            name: _sha256_file(args.output_dir / name)
            for name in output_names
        },
    }
    (args.output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"results -> {args.output_dir.resolve()}", flush=True)


if __name__ == "__main__":
    main()
