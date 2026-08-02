"""Run one paired soft-boundary causal-repair experiment family."""

from __future__ import annotations

import argparse
import json
import os
import statistics
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
    EventCausalRepairController,
    OptimisticBoundScreenedFullReplanController,
    PeriodicFullReplanController,
    SoftBoundaryEventCausalRepairController,
)
from run_event_causal_repair_experiment import (  # noqa: E402
    FollowInitialPlanController,
    _provenance_manifest,
    _run_episode,
    _sha256_file,
    _write_csv,
)


SCREEN_REFERENCE = "Budget-Matched Periodic Full Replan ALNS"
PRIMARY = "Soft-Boundary Event-Causal ALNS"


def _soft_name(decay: float, gate: bool) -> str:
    return f"Soft Boundary d={decay:.2f} Gate={'On' if gate else 'Off'}"


def _controllers(
    mode: str,
    solve_cost,
    proxy_threshold_fraction: float,
    budget_pacing: bool,
    periodic_replan_period: float,
    matched_periodic_target_count: int,
    development_decays: Sequence[float],
    development_gate_modes: Sequence[bool],
    selected_decay: float | None,
    selected_gate: bool | None,
):
    if mode == "screen":
        controllers = [
            SoftBoundaryEventCausalRepairController(
                solve_cost=solve_cost,
                proxy_threshold_fraction=proxy_threshold_fraction,
                boundary_decay=decay,
                gate_fleet_service_triggers=gate,
                budget_pacing=budget_pacing,
                name=_soft_name(decay, gate),
            )
            for decay in development_decays
            for gate in development_gate_modes
        ]
        controllers.append(
            PeriodicFullReplanController(
                solve_cost=solve_cost,
                target_count=matched_periodic_target_count,
                name=SCREEN_REFERENCE,
            )
        )
        return controllers

    if selected_decay is None or selected_gate is None:
        raise ValueError(
            "confirmation/final mode requires selected decay and gate"
        )

    soft = SoftBoundaryEventCausalRepairController(
        solve_cost=solve_cost,
        proxy_threshold_fraction=proxy_threshold_fraction,
        boundary_decay=selected_decay,
        gate_fleet_service_triggers=selected_gate,
        budget_pacing=budget_pacing,
        name=PRIMARY,
    )
    hard = EventCausalRepairController(
        solve_cost=solve_cost,
        proxy_threshold_fraction=proxy_threshold_fraction,
        trigger_mode="proxy",
        gate_fleet_service_triggers=selected_gate,
        budget_pacing=budget_pacing,
    )
    hard.name = "Hard-Freeze Event-Causal ALNS"
    full = OptimisticBoundScreenedFullReplanController(
        solve_cost=solve_cost,
        proxy_threshold_fraction=proxy_threshold_fraction,
        trigger_mode="proxy",
        gate_fleet_service_triggers=selected_gate,
        budget_pacing=budget_pacing,
    )
    full.name = "Identical-Trigger Full Replan ALNS"
    return [
        soft,
        hard,
        full,
        PeriodicFullReplanController(
            solve_cost=solve_cost,
            target_count=matched_periodic_target_count,
            name=SCREEN_REFERENCE,
        ),
        PeriodicFullReplanController(
            solve_cost=solve_cost,
            period_hours=periodic_replan_period,
        ),
        FollowInitialPlanController(),
    ]


def _aggregate(rows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    metrics = (
        "J_dep_true",
        "J_composite",
        "fill_rate",
        "n_resolves",
        "repair_solver_calls",
        "repair_wall_time_s",
        "episode_wall_time_s",
        "violations",
    )
    output: Dict[str, object] = {}
    for method in dict.fromkeys(str(row["method"]) for row in rows):
        selected = [row for row in rows if row["method"] == method]
        output[method] = {"episodes": len(selected)}
        for metric in metrics:
            values = [float(row[metric]) for row in selected]
            output[method][metric] = {
                "mean": statistics.fmean(values),
                "std": statistics.stdev(values) if len(values) > 1 else 0.0,
                "median": statistics.median(values),
            }
    return output


def _paired_rows(
    rows: Sequence[Dict[str, object]],
    references: Sequence[str],
) -> List[Dict[str, object]]:
    by_key = {
        (str(row["method"]), int(row["seed"])): row for row in rows
    }
    methods = list(dict.fromkeys(str(row["method"]) for row in rows))
    seeds = sorted({int(row["seed"]) for row in rows})
    output: List[Dict[str, object]] = []
    for method in methods:
        for reference in references:
            if method == reference:
                continue
            for seed in seeds:
                candidate = by_key.get((method, seed))
                baseline = by_key.get((reference, seed))
                if candidate is None or baseline is None:
                    continue
                dep = float(candidate["J_dep_true"])
                base_dep = float(baseline["J_dep_true"])
                output.append({
                    "seed": seed,
                    "method": method,
                    "reference": reference,
                    "delta_J_dep_true": dep - base_dep,
                    "relative_delta_J_dep_true_pct": (
                        100.0 * (dep - base_dep) / base_dep
                        if abs(base_dep) > 1e-12 else float("nan")
                    ),
                    "delta_J_composite": (
                        float(candidate["J_composite"])
                        - float(baseline["J_composite"])
                    ),
                    "delta_fill_rate": (
                        float(candidate["fill_rate"])
                        - float(baseline["fill_rate"])
                    ),
                    "delta_repair_solver_calls": (
                        int(candidate["repair_solver_calls"])
                        - int(baseline["repair_solver_calls"])
                    ),
                    "delta_repair_wall_time_s": (
                        float(candidate["repair_wall_time_s"])
                        - float(baseline["repair_wall_time_s"])
                    ),
                })
    return output


def main() -> None:
    started_at = datetime.now(timezone.utc).isoformat()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--method-config",
        type=Path,
        default=Path("configs/method/soft_boundary_development.yaml"),
    )
    parser.add_argument(
        "--mode", choices=("screen", "confirm", "final"), required=True,
    )
    parser.add_argument("--seed-start", type=int, required=True)
    parser.add_argument("--n-seeds", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--selected-decay", type=float, default=None)
    parser.add_argument(
        "--selected-gate",
        action=argparse.BooleanOptionalAction,
        default=None,
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
    decays = [float(value) for value in payload["development_boundary_decays"]]
    gate_modes = [bool(value) for value in payload["development_gate_modes"]]
    randomize = bool(payload.get("randomize_method_order", True))
    if any(not 0.0 < value <= 1.0 for value in decays):
        raise ValueError("development decays must be in (0, 1]")
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
            development_decays=decays,
            development_gate_modes=gate_modes,
            selected_decay=args.selected_decay,
            selected_gate=args.selected_gate,
        )
        if randomize and len(controllers) > 1:
            rng = np.random.default_rng(seed + 193_939)
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
                f"{controller.name:<42} dep={row['J_dep_true']:.1f} "
                f"calls={row['repair_solver_calls']} "
                f"fill={row['fill_rate']:.3f}",
                flush=True,
            )

    methods = list(dict.fromkeys(str(row["method"]) for row in episode_rows))
    references = [SCREEN_REFERENCE] if args.mode == "screen" else [
        PRIMARY,
        "Hard-Freeze Event-Causal ALNS",
        "Identical-Trigger Full Replan ALNS",
        SCREEN_REFERENCE,
        "Periodic Full Replan ALNS",
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
        "solve_cost": solve_cost,
        "proxy_threshold_fraction": threshold,
        "trigger_mode": "proxy",
        "budget_pacing": budget_pacing,
        "periodic_replan_period": period,
        "matched_periodic_target_count": matched_count,
        "development_boundary_decays": decays,
        "development_gate_modes": gate_modes,
        "selected_decay": args.selected_decay,
        "selected_gate": args.selected_gate,
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
            name: _sha256_file(args.output_dir / name) for name in output_names
        },
    }
    (args.output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"results -> {args.output_dir.resolve()}", flush=True)


if __name__ == "__main__":
    main()

