"""Run paired Event-Causal Belief-Repair ALNS experiments.

Examples
--------
Smoke verification with figures:
    python scripts/run_event_causal_repair_experiment.py --smoke --plot

Final information-obsolescence run:
    python scripts/run_event_causal_repair_experiment.py \
        --config configs/env/event_causal_hard.yaml \
        --method-config configs/method/event_causal_repair.yaml \
        --seed-start 200 --n-seeds 40 \
        --output-dir results/event_causal_repair_final --plot
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from env.events import EventType  # noqa: E402
from env.params import EnvParams  # noqa: E402
from env.scenario_generator import generate_scenario  # noqa: E402
from env.uav_env import UAMTVRPIUEnv  # noqa: E402
from methods.event_causal_repair import (
    EventCausalRepairController,
    EventPriorityHeuristicController,
    EveryEventFullReplanController,
    OptimisticBoundScreenedFullReplanController,
    PeriodicFullReplanController,
)


MAX_STEPS = 6000
METHOD_ORDER = (
    "Event-Causal Belief-Repair ALNS",
    "Optimistic-Bound-Screened Full Replan ALNS",
    "Periodic Full Replan ALNS",
    "Event-Priority Heuristic ALNS",
    "Full Event Replan ALNS",
    "Initial Plan Only",
)


class FollowInitialPlanController:
    name = "Initial Plan Only"

    @staticmethod
    def act(env, obs, masks, deciders):
        del obs, masks
        return {u: env.A_FOLLOW for u in deciders}


# class FullEventReplanController:
#     name = "Full Event Replan ALNS"

#     @staticmethod
#     def act(env, obs, masks, deciders):
#         del obs
#         actions = {u: env.A_FOLLOW for u in deciders}
#         if (
#             deciders
#             and env.last_decision_event_type in OPERATIONAL_REPAIR_EVENTS
#             and env.K_rem > 0
#         ):
#             requester = next(
#                 (u for u in deciders if masks[u][env.A_RESOLVE]), None)
#             if requester is not None:
#                 actions[requester] = env.A_RESOLVE
#         return actions


def _controllers(
    solve_cost=None,
    proxy_threshold_fraction=0.0,
    shadow_audit_screened_events=False,
    trigger_mode="both",
    periodic_replan_period=2.0,
    event_priority_budget=6,
):
    return (
        EventCausalRepairController(
            solve_cost=solve_cost,
            proxy_threshold_fraction=(
                proxy_threshold_fraction
            ),
            shadow_audit_screened_events=(
                shadow_audit_screened_events
            ),
            trigger_mode=trigger_mode,
        ),
        OptimisticBoundScreenedFullReplanController(
            solve_cost=solve_cost,
            proxy_threshold_fraction=(
                proxy_threshold_fraction
            ),
        ),
        PeriodicFullReplanController(
            solve_cost=solve_cost,
            period_hours=float(periodic_replan_period),
        ),
        EventPriorityHeuristicController(
            solve_cost=solve_cost,
            budget=int(event_priority_budget),
        ),
        EveryEventFullReplanController(
            solve_cost=solve_cost,
        ),
        FollowInitialPlanController(),
    )

# def _run_episode(env, scenario, controller):
#     episode_started = time.perf_counter()
#     if hasattr(controller, "reset"):
#         controller.reset()
#     obs, info = env.reset(scenario=scenario)
#     total_reward = 0.0
#     violations = 0.0
#     steps = 0
#     step_resolve_wall_time_s = 0.0
#     step_resolve_solver_calls = 0
#     while not env.done and steps < MAX_STEPS:
#         resolves_before = int(env.metrics.n_resolves)
#         actions = controller.act(
#             env, obs, info["masks"], info["deciders"])
#         resolves_after_act = int(env.metrics.n_resolves)
#         step_started = time.perf_counter()
#         obs, reward, _, info = env.step(actions)
#         step_wall_time_s = time.perf_counter() - step_started
#         resolves_after_step = int(env.metrics.n_resolves)
#         step_solver_calls = max(
#             resolves_after_step - resolves_after_act, 0)
#         if step_solver_calls:
#             step_resolve_wall_time_s += step_wall_time_s
#             step_resolve_solver_calls += step_solver_calls
#         if resolves_after_act < resolves_before:
#             raise RuntimeError("Resolve counter decreased during controller act")
#         total_reward += float(reward)
#         violations += float(info["reward_terms"]["P_viol"])
#         steps += 1
#     if not env.done:
#         raise RuntimeError(
#             f"{controller.name} exceeded {MAX_STEPS} decisions")
#     metrics = env.metrics.summary()
#     repair_wall_time_s = (
#         float(getattr(controller, "repair_wall_time_s", 0.0))
#         + step_resolve_wall_time_s
#     )
#     repair_solver_calls = (
#         int(getattr(controller, "repair_solver_calls", 0))
#         + step_resolve_solver_calls
#     )
#     episode_wall_time_s = time.perf_counter() - episode_started
#     mean_repair_wall_time_s = (
#         repair_wall_time_s / repair_solver_calls
#         if repair_solver_calls else 0.0
#     )
#     composite = (
#         metrics["J_dep_true"]
#         + env.p.hybrid.xi_E * metrics["J_energy"]
#         + env.p.hybrid.xi_R * metrics["J_risk"]
#         + env.p.hybrid.xi_C * metrics["n_resolves"]
#     )
#     row = {
#         "method": controller.name,
#         "seed": int(scenario.seed),
#         "reward": total_reward,
#         "J_dep_true": float(metrics["J_dep_true"]),
#         "J_dep_belief": float(metrics["J_dep_belief"]),
#         "J_energy": float(metrics["J_energy"]),
#         "J_risk": float(metrics["J_risk"]),
#         "J_fair_gini": float(metrics["J_fair_gini"]),
#         "J_fair_max": float(metrics["J_fair_max"]),
#         "J_composite": float(composite),
#         "fill_rate": float(metrics["fill_rate"]),
#         "n_resolves": int(metrics["n_resolves"]),
#         "repair_solver_calls": int(repair_solver_calls),
#         "repair_wall_time_s": float(repair_wall_time_s),
#         "mean_repair_wall_time_s": float(mean_repair_wall_time_s),
#         "episode_wall_time_s": float(episode_wall_time_s),
#         "violations": violations,
#         "steps": steps,
#         "termination": metrics["termination_reason"],
#     }
#     diagnostics = []
#     for record in getattr(controller, "diagnostics", []):
#         diagnostics.append({
#             "method": controller.name,
#             "seed": int(scenario.seed),
#             **record,
#         })
#     return row, diagnostics

def _run_episode(env, scenario, controller):
    episode_started = time.perf_counter()

    if hasattr(controller, "reset"):
        controller.reset()

    obs, info = env.reset(scenario=scenario)

    total_reward = 0.0
    violations = 0.0
    steps = 0

    while not env.done and steps < MAX_STEPS:
        resolves_before = int(
            env.metrics.n_resolves
        )

        actions = controller.act(
            env,
            obs,
            info["masks"],
            info["deciders"],
        )

        resolves_after_act = int(
            env.metrics.n_resolves
        )

        if resolves_after_act < resolves_before:
            raise RuntimeError(
                "Resolve counter decreased during controller act"
            )

        obs, reward, _, info = env.step(actions)

        total_reward += float(reward)
        violations += float(
            info["reward_terms"]["P_viol"]
        )
        steps += 1

    if not env.done:
        raise RuntimeError(
            f"{controller.name} exceeded "
            f"{MAX_STEPS} decisions"
        )

    metrics = env.metrics.summary()

    # These counters measure planner.solve() only. They exclude
    # environment advancement, observation construction and masks.
    repair_solver_calls = int(
        env.repair_solver_calls
    )
    repair_wall_time_s = float(
        env.repair_solver_wall_time_s
    )
    shadow_audit_solver_calls = int(
    env.shadow_audit_solver_calls
    )

    shadow_audit_wall_time_s = float(
    env.shadow_audit_wall_time_s
    )

    episode_wall_time_s = (
        time.perf_counter() - episode_started
    )

    mean_repair_wall_time_s = (
        repair_wall_time_s / repair_solver_calls
        if repair_solver_calls
        else 0.0
    )

    composite = (
        metrics["J_dep_true"]
        + env.p.hybrid.xi_E * metrics["J_energy"]
        + env.p.hybrid.xi_R * metrics["J_risk"]
        + env.p.hybrid.xi_C * metrics["n_resolves"]
    )

    row = {
        "method": controller.name,
        "seed": int(scenario.seed),
        "reward": total_reward,
        "J_dep_true": float(
            metrics["J_dep_true"]
        ),
        "J_dep_belief": float(
            metrics["J_dep_belief"]
        ),
        "J_energy": float(metrics["J_energy"]),
        "J_risk": float(metrics["J_risk"]),
        "J_fair_gini": float(
            metrics["J_fair_gini"]
        ),
        "J_fair_max": float(
            metrics["J_fair_max"]
        ),
        "J_composite": float(composite),
        "fill_rate": float(metrics["fill_rate"]),
        "n_resolves": int(
            metrics["n_resolves"]
        ),
        "repair_solver_calls": (
            repair_solver_calls
        ),
        "repair_wall_time_s": (
            repair_wall_time_s
        ),
        "mean_repair_wall_time_s": (
            mean_repair_wall_time_s
        ),
        "episode_wall_time_s": float(
            episode_wall_time_s
        ),
        "violations": violations,
        "steps": steps,
        "termination": metrics[
            "termination_reason"
        ],
        "shadow_audit_solver_calls": (
            shadow_audit_solver_calls
        ),
        "shadow_audit_wall_time_s": (
            shadow_audit_wall_time_s
        ),
    }

    diagnostics = []

    for record in getattr(
        controller,
        "diagnostics",
        [],
    ):
        diagnostics.append({
            "method": controller.name,
            "seed": int(scenario.seed),
            **record,
        })


    shadow_audit_rows = []

    for record in getattr(
        controller,
        "shadow_audit_records",
        [],
    ):
        shadow_audit_rows.append({
            "method": controller.name,
            "seed": int(scenario.seed),
            **record,
        })


    recorded_shadow_calls = sum(
        int(record.get(
            "shadow_audit_solver_calls",
            0,
        ))
        for record in shadow_audit_rows
    )

    if recorded_shadow_calls != (
        shadow_audit_solver_calls
    ):
        raise RuntimeError(
            "Shadow-audit solver-call accounting mismatch: "
            f"environment={shadow_audit_solver_calls}, "
            f"records={recorded_shadow_calls}"
        )


    return row, diagnostics, shadow_audit_rows

    


def _write_csv(path: Path, rows: Sequence[Dict[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: List[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _aggregate(rows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    metrics = (
        "J_dep_true", "J_composite", "fill_rate", "n_resolves",
        "repair_solver_calls", "repair_wall_time_s",
        "mean_repair_wall_time_s", "shadow_audit_solver_calls",
    "shadow_audit_wall_time_s","episode_wall_time_s",
        "violations", "reward",
    )
    summary: Dict[str, object] = {}
    for method in METHOD_ORDER:
        selected = [row for row in rows if row["method"] == method]
        if not selected:
            continue
        method_summary: Dict[str, object] = {"episodes": len(selected)}
        for metric in metrics:
            values = [float(row[metric]) for row in selected]
            method_summary[metric] = {
                "mean": statistics.fmean(values),
                "std": statistics.stdev(values) if len(values) > 1 else 0.0,
                "median": statistics.median(values),
                "min": min(values),
                "max": max(values),
            }
        summary[method] = method_summary
    return summary


def _paired_rows(rows: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    by_key = {
        (str(row["method"]), int(row["seed"])): row for row in rows
    }
    proposed = METHOD_ORDER[0]
    seeds = sorted({
        int(row["seed"]) for row in rows if row["method"] == proposed
    })
    paired: List[Dict[str, object]] = []
    for seed in seeds:
        p = by_key[(proposed, seed)]
        for comparator in METHOD_ORDER[1:]:
            c = by_key[(comparator, seed)]
            baseline_j = float(c["J_composite"])
            delta = float(p["J_composite"]) - baseline_j
            paired.append({
                "seed": seed,
                "proposed": proposed,
                "comparator": comparator,
                "delta_J_composite": delta,
                "relative_delta_J_composite_pct": (
                    100.0 * delta / baseline_j
                    if abs(baseline_j) > 1e-12 else math.nan
                ),
                "delta_J_dep_true": (
                    float(p["J_dep_true"]) - float(c["J_dep_true"])
                ),
                "delta_fill_rate": (
                    float(p["fill_rate"]) - float(c["fill_rate"])
                ),
                "delta_n_resolves": (
                    int(p["n_resolves"]) - int(c["n_resolves"])
                ),
                "delta_repair_solver_calls": (
                    int(p["repair_solver_calls"])
                    - int(c["repair_solver_calls"])
                ),
                "delta_repair_wall_time_s": (
                    float(p["repair_wall_time_s"])
                    - float(c["repair_wall_time_s"])
                ),
                "delta_episode_wall_time_s": (
                    float(p["episode_wall_time_s"])
                    - float(c["episode_wall_time_s"])
                ),
            })
    return paired


def _resolve_seeds(args) -> List[int]:
    if args.seeds:
        seeds = list(dict.fromkeys(args.seeds))
    else:
        seeds = list(range(args.seed_start, args.seed_start + args.n_seeds))
    if args.smoke:
        seeds = seeds[:2]
    if not seeds:
        raise ValueError("At least one seed is required")
    return seeds


def _resolve_calibration_seeds(args) -> List[int]:
    if args.calibration_seeds:
        return list(dict.fromkeys(args.calibration_seeds))
    return list(range(300, 310))


def _sha256_file(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_git_dir(start: Path) -> Optional[Path]:
    """Locate the .git directory by walking up from ``start``."""
    current = start.resolve()
    for candidate in (current, *current.parents):
        git_path = candidate / ".git"
        if git_path.is_dir():
            return git_path
        if git_path.is_file():
            # Worktree/submodule pointer: "gitdir: <path>"
            try:
                text = git_path.read_text(encoding="utf-8").strip()
            except OSError:
                return None
            if text.startswith("gitdir:"):
                target = Path(text.split(":", 1)[1].strip())
                if not target.is_absolute():
                    target = (candidate / target).resolve()
                return target if target.is_dir() else None
    return None


def _read_head_from_disk(git_dir: Path) -> Optional[str]:
    """Resolve HEAD without invoking git (bulletproof provenance)."""
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not head.startswith("ref:"):
        return head if head else None  # detached HEAD
    ref = head.split(":", 1)[1].strip()
    ref_file = git_dir / ref
    try:
        return ref_file.read_text(encoding="utf-8").strip() or None
    except OSError:
        pass
    # Ref may only exist in packed-refs.
    try:
        for line in (git_dir / "packed-refs").read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            if line.startswith("#") or line.startswith("^"):
                continue
            parts = line.split(" ", 1)
            if len(parts) == 2 and parts[1].strip() == ref:
                return parts[0].strip()
    except OSError:
        pass
    return None


def _git_commit_hash() -> Optional[str]:
    git_dir = _find_git_dir(Path(__file__).resolve().parent)
    if git_dir is not None:
        commit = _read_head_from_disk(git_dir)
        if commit:
            return commit
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parent,
        )
        return result.stdout.strip()
    except Exception:
        return None


def _git_dirty_source_files() -> List[str]:
    """Dirty/untracked files under source dirs (results excluded)."""
    code_root = Path(__file__).resolve().parent.parent
    tracked_roots = ("src/", "scripts/", "configs/", "tests/")
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", *tracked_roots],
            capture_output=True,
            text=True,
            check=True,
            cwd=code_root,
        )
    except Exception:
        return []
    dirty: List[str] = []
    for line in result.stdout.splitlines():
        if len(line) > 3:
            dirty.append(line[3:].strip())
    return dirty


def _provenance_manifest(
    env_config_path: Optional[Path],
    method_config_path: Optional[Path],
    output_dir: Path,
    seeds: List[int],
    method_settings: Dict[str, object],
) -> Dict[str, object]:
    """Build a manifest of source/config files with SHA-256 hashes."""
    code_root = Path(__file__).resolve().parent.parent
    candidate_files = {
        "controller": code_root / "src" / "methods" / "event_causal_repair.py",
        "runner": code_root / "scripts" / "run_event_causal_repair_experiment.py",
        "scenario_generator": code_root / "src" / "env" / "scenario_generator.py",
        "env_uav_env": code_root / "src" / "env" / "uav_env.py",
        "env_alns_scaffold": code_root / "src" / "env" / "alns_scaffold.py",
        "env_belief": code_root / "src" / "env" / "belief.py",
        "env_entities": code_root / "src" / "env" / "entities.py",
        "env_graph": code_root / "src" / "env" / "graph.py",
        "env_events": code_root / "src" / "env" / "events.py",
        "env_params": code_root / "src" / "env" / "params.py",
        "env_scenario": code_root / "src" / "env" / "scenario.py",
        "env_metrics": code_root / "src" / "env" / "metrics.py",
        "env_energy": code_root / "src" / "env" / "energy.py",
        "env_deprivation": code_root / "src" / "env" / "deprivation.py",
        "env_units": code_root / "src" / "env" / "units.py",
        "env_observation_contract": code_root / "src" / "env" / "observation_contract.py",
        "env_config": env_config_path,
        "method_config": method_config_path,
    }
    files = {}
    for label, path in candidate_files.items():
        if path is None:
            continue
        digest = _sha256_file(path)
        if digest is not None:
            files[label] = {
                "path": str(path.resolve()),
                "sha256": digest,
            }
    dirty_source = _git_dirty_source_files()
    return {
        "git_commit": _git_commit_hash(),
        "git_tree_clean": len(dirty_source) == 0,
        "git_dirty_source_files": dirty_source,
        "command": " ".join(sys.argv),
        "output_dir": str(output_dir.resolve()),
        "seeds": seeds,
        "method": method_settings,
        "files": files,
    }


def _run_threshold_sensitivity(
    params: EnvParams,
    solve_cost: Optional[float],
    calibration_seeds: List[int],
    trigger_mode: str,
    output_dir: Path,
) -> List[Dict[str, object]]:
    """Run Event-Causal across thresholds on calibration seeds."""
    rows: List[Dict[str, object]] = []
    rows: List[Dict[str, object]] = []
    thresholds = [0.05, 0.10, 0.20, 0.30]
    print(
        f"threshold sensitivity: {len(calibration_seeds)} seeds x "
        f"{len(thresholds)} thresholds"
    )
    for threshold in thresholds:
        for seed in calibration_seeds:
            scenario = generate_scenario(seed, params)
            controller = EventCausalRepairController(
                solve_cost=solve_cost,
                proxy_threshold_fraction=threshold,
                shadow_audit_screened_events=True,
                trigger_mode=trigger_mode,
            )
            env = UAMTVRPIUEnv(params)
            row, _, audit_rows = _run_episode(env, scenario, controller)
            false_negatives = sum(
                int(r.get("screen_false_negative", 0)) for r in audit_rows
            )
            rows.append({
                "threshold": threshold,
                "seed": seed,
                "J_composite": row["J_composite"],
                "n_resolves": row["n_resolves"],
                "fill_rate": row["fill_rate"],
                "shadow_audit_false_negatives": false_negatives,
                "shadow_audit_solver_calls": row["shadow_audit_solver_calls"],
            })
            print(
                f"  threshold={threshold:.2f} seed={seed} "
                f"J={row['J_composite']:.2f} repairs={row['n_resolves']} "
                f"fn={false_negatives}"
            )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument(
        "--method-config", type=Path,
        default=Path("configs/method/event_causal_repair.yaml"))
    parser.add_argument("--seeds", type=int, nargs="*", default=None)
    parser.add_argument("--seed-start", type=int, default=400)
    parser.add_argument("--n-seeds", type=int, default=40)
    parser.add_argument("--repair-budget", type=int, default=None)
    parser.add_argument("--alns-iterations", type=int, default=None)
    parser.add_argument(
        "--proxy-threshold-fraction", type=float, default=None,
        help=(
            "Soft-event proxy threshold as a fraction of the current "
            "optimistic relief-value upper bound."
        ),
    )
    parser.add_argument(
        "--trigger-mode", type=str, default="both",
        choices=["certificate", "proxy", "both"],
        help="Event-Causal trigger mode: certificate, proxy, or both.",
    )
    parser.add_argument(
        "--periodic-replan-period", type=float, default=2.0,
        help="Period in hours for the periodic full-replan baseline.",
    )
    parser.add_argument(
        "--event-priority-budget", type=int, default=6,
        help="Per-episode repair budget for the event-priority heuristic.",
    )
    parser.add_argument(
        "--calibration-seeds", type=int, nargs="*", default=None,
        help="Seeds used for threshold sensitivity (default 300-309).",
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path("results/event_causal_repair"))
    parser.add_argument(
        "--shadow-audit-screened-events",
        action="store_true",
        help=(
            "Counterfactually evaluate proxy-screened events "
            "without modifying the executed episode."
        ),
    )
    parser.add_argument(
        "--skip-threshold-sensitivity",
        action="store_true",
        help="Skip the calibration-seed threshold sensitivity sweep.",
    )

    parser.add_argument(
        "--smoke",
        action="store_true",
    )

    parser.add_argument(
        "--plot",
        action="store_true",
    )
    args = parser.parse_args()

    params = (
        EnvParams.from_yaml(str(args.config))
        if args.config is not None else EnvParams()
    )
    method_payload = {}
    if args.method_config is not None:
        with args.method_config.open("r", encoding="utf-8") as handle:
            method_payload = (yaml.safe_load(handle) or {}).get("method", {})
    repair_budget = (
        args.repair_budget
        if args.repair_budget is not None
        else method_payload.get("repair_budget")
    )
    alns_iterations = (
        args.alns_iterations
        if args.alns_iterations is not None
        else method_payload.get("alns_iterations")
    )
    solve_cost = method_payload.get("solve_cost")
    proxy_threshold_fraction = (
        args.proxy_threshold_fraction
        if args.proxy_threshold_fraction is not None
        else method_payload.get("proxy_threshold_fraction", 0.0)
    )
    if proxy_threshold_fraction < 0.0:
        raise ValueError(
            "--proxy-threshold-fraction must be nonnegative")
    if repair_budget is not None:
        if repair_budget < 0:
            raise ValueError("--repair-budget must be nonnegative")
        params.hybrid.K_max = int(repair_budget)
    if alns_iterations is not None:
        if alns_iterations < 0:
            raise ValueError("--alns-iterations must be nonnegative")
        params.hybrid.alns_iterations = int(alns_iterations)

    # Save a copy of the *input* config before smoke overrides.
    resolved_env = params.to_dict()

    if args.smoke:
        params.mission.T = min(params.mission.T, 2.0)
        params.map.n_nodes = min(params.map.n_nodes, 8)
        params.map.n_hidden = min(params.map.n_hidden, 2)
        params.mission.n_replenish = min(params.mission.n_replenish, 1)
        params.hybrid.K_max = 6
        params.hybrid.alns_iterations = min(
            params.hybrid.alns_iterations, 4)

    seeds = _resolve_seeds(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    episode_rows: List[
        Dict[str, object]
    ] = []

    diagnostic_rows: List[
        Dict[str, object]
    ] = []

    shadow_audit_rows: List[
        Dict[str, object]
    ] = []
    print(
        f"event-causal ALNS experiment: {len(seeds)} paired seeds, "
        f"K_max={params.hybrid.K_max}, "
        f"ALNS iterations={params.hybrid.alns_iterations}, "
        f"proxy threshold={proxy_threshold_fraction:.3f} of upper bound, "
        f"trigger_mode={args.trigger_mode}"
    )
    for seed_index, seed in enumerate(seeds, start=1):
        scenario = generate_scenario(seed, params)
        for controller in _controllers(
            solve_cost=solve_cost,
            proxy_threshold_fraction=(
                proxy_threshold_fraction
            ),
            shadow_audit_screened_events=(
                args.shadow_audit_screened_events
            ),
            trigger_mode=args.trigger_mode,
            periodic_replan_period=args.periodic_replan_period,
            event_priority_budget=args.event_priority_budget,
        ):
            env = UAMTVRPIUEnv(params)
            row, diagnostics, episode_audit_rows = (
                _run_episode(
                    env,
                    scenario,
                    controller,
                )
            )

            episode_rows.append(row)
            diagnostic_rows.extend(diagnostics)
            shadow_audit_rows.extend(
                episode_audit_rows
            )
            print(
                f"  seed {seed:5d} [{seed_index}/{len(seeds)}] "
                f"{controller.name:<34} "
                f"J={row['J_composite']:9.2f} "
                f"repairs={row['n_resolves']:2d} "
                f"repair_s={row['repair_wall_time_s']:7.3f} "
                f"fill={row['fill_rate']:.3f}"
            )

    paired = _paired_rows(episode_rows)
    _write_csv(args.output_dir / "episode_metrics.csv", episode_rows)
    _write_csv(args.output_dir / "repair_diagnostics.csv", diagnostic_rows)
    _write_csv(args.output_dir / "paired_comparisons.csv", paired)
    _write_csv(
        args.output_dir / "counterfactual_screen_audit.csv",
        shadow_audit_rows,
    )

    # Threshold sensitivity on calibration seeds.
    if not args.skip_threshold_sensitivity:
        calibration_seeds = _resolve_calibration_seeds(args)
        if args.smoke:
            calibration_seeds = calibration_seeds[:2]
        threshold_rows = _run_threshold_sensitivity(
            params=params,
            solve_cost=solve_cost,
            calibration_seeds=calibration_seeds,
            trigger_mode=args.trigger_mode,
            output_dir=args.output_dir,
        )
        _write_csv(
            args.output_dir / "threshold_sensitivity.csv",
            threshold_rows,
        )

    summary = {
        "method_order": list(METHOD_ORDER),
        "seeds": seeds,
        "environment": params.to_dict(),
        "method": {
            "solve_cost": solve_cost,
            "proxy_threshold_fraction": proxy_threshold_fraction,
            "repair_budget": params.hybrid.K_max,
            "alns_iterations": params.hybrid.alns_iterations,
            "trigger_mode": args.trigger_mode,
            "periodic_replan_period": args.periodic_replan_period,
            "event_priority_budget": args.event_priority_budget,
            "shadow_audit_screened_events": bool(
                args.shadow_audit_screened_events
            ),
        },
        "aggregate": _aggregate(episode_rows),
        "diagnostic_rows": len(diagnostic_rows),
        "shadow_audit_rows": len(shadow_audit_rows),
    }
    with (args.output_dir / "summary.json").open(
        "w", encoding="utf-8",
    ) as handle:
        json.dump(summary, handle, indent=2)

    # Save the resolved configuration actually used after CLI overrides.
    resolved_config = {
        "environment": params.to_dict(),
        "method": summary["method"],
    }
    with (args.output_dir / "resolved_config.yaml").open(
        "w", encoding="utf-8",
    ) as handle:
        yaml.safe_dump(resolved_config, handle, sort_keys=False)

    # Provenance manifest with hashes for existing source/config files.
    method_settings = dict(summary["method"])
    method_settings["seeds"] = seeds
    provenance = _provenance_manifest(
        env_config_path=args.config,
        method_config_path=args.method_config,
        output_dir=args.output_dir,
        seeds=seeds,
        method_settings=method_settings,
    )
    with (args.output_dir / "provenance.json").open(
        "w", encoding="utf-8",
    ) as handle:
        json.dump(provenance, handle, indent=2)

    if args.plot:
        from plot_event_causal_repair import plot

        figures = plot(args.output_dir)
        print("figures:")
        for figure in figures:
            print(f"  {figure}")

    # Legacy run manifest for backward compatibility. Only list files
    # that actually exist on disk.
    candidate_outputs = [
        "episode_metrics.csv",
        "repair_diagnostics.csv",
        "paired_comparisons.csv",
        "counterfactual_screen_audit.csv",
        "threshold_sensitivity.csv",
        "summary.json",
        "resolved_config.yaml",
        "provenance.json",
    ]
    existing_files = [
        name
        for name in candidate_outputs
        if (args.output_dir / name).exists()
    ]
    figures_dir = args.output_dir / "figures"
    if figures_dir.is_dir():
        existing_files.extend(
            f"figures/{path.name}"
            for path in sorted(figures_dir.iterdir())
            if path.is_file()
        )
    manifest = {
        "command": " ".join(sys.argv),
        "config": str(args.config) if args.config is not None else None,
        "method_config": (
            str(args.method_config)
            if args.method_config is not None else None
        ),
        "output_dir": str(args.output_dir.resolve()),
        "smoke": bool(args.smoke),
        "method": method_settings,
        "files": existing_files,
    }
    with (args.output_dir / "run_manifest.json").open(
        "w", encoding="utf-8",
    ) as handle:
        json.dump(manifest, handle, indent=2)
    print(f"results -> {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
