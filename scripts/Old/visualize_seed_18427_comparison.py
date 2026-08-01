"""Render an honest side-by-side seed-18427 scene comparison.

The left panel replays the exact six-node scenario-v2 audit package with its
separate scripted audit action.  The right panel runs the trained production
graph-MAPPO checkpoint (unguided, g=0) on the distinct twenty-node environment
for which that checkpoint was trained.  Normalized animation progress aligns
the panels visually; their independent clocks and schemas remain explicit.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sys
from typing import Dict, Iterable, Mapping, Sequence

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation, PillowWriter
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Ellipse, Rectangle
from PIL import Image, ImageSequence
import torch
import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for entry in (ROOT, SRC):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from env.audit_geometry import composite_risk, terrain_elevation_m  # noqa: E402
from env.audit_model import AuditScenario  # noqa: E402
from env.audit_replay import (  # noqa: E402
    ScenarioReplay,
    load_audit_actions,
    urgency_score,
)
from env.params import EnvParams  # noqa: E402
from env.scenario_generator import generate_scenario  # noqa: E402
from env.uav_env import UAMTVRPIUEnv  # noqa: E402
from methods.gate_learning_development import file_sha256  # noqa: E402
from scripts.run_gate_learning_development import _make_agent  # noqa: E402
from scripts.train_mappo import DEFAULT_AGENT_CONFIG, load_agent_config  # noqa: E402


AUDIT_HORIZON_S = 8.0 * 3600.0
TRAINED_MODE = "graph_mappo"
CONDITION_COLORS = {
    "NORMAL": "#2a9d8f",
    "DEGRADED": "#e9c46a",
    "CLOSED": "#d62828",
}
UAV_COLORS = ("#0077b6", "#9b5de5", "#f77f00")
UAV_MARKERS = ("^", "s", "D")


def _canonical_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"Cannot write an empty trajectory table: {path}")
    fields = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _array(value) -> list[float]:
    return [float(item) for item in np.asarray(value, dtype=float).tolist()]


def _dict_arrays(values: Mapping) -> Dict[str, list[float]]:
    return {str(key): _array(value) for key, value in values.items()}


def _initial_training_state(scenario, params: EnvParams) -> Dict:
    truth = scenario.passive_truth_at(0.0)
    belief = scenario.passive_belief_at(0.0)
    return {
        "time_h": 0.0,
        "uavs": [
            {
                "uav_id": index,
                "x_km": float(scenario.depot[0]),
                "y_km": float(scenario.depot[1]),
                "mode": "DEPOT",
                "battery_wh": float(params.physics.B_max),
                "payload": [0.0, 0.0, 0.0, 0.0],
                "dest_node": None,
            }
            for index in range(params.mission.M)
        ],
        "true_demand": {
            str(node.idx): _array(node.demand_vector())
            for node in truth
            if node.onset_time <= 0.0
        },
        "belief_demand": {
            str(index): _array(belief.d_tilde(index))
            for index in sorted(belief.known)
        },
        "known_nodes": [int(index) for index in sorted(belief.known)],
        "inventory": _array(scenario.S0_init),
        "available": [],
        "scaffold": {str(index): [] for index in range(params.mission.M)},
        "last_actions": [],
    }


def _training_state(env, last_actions: Sequence[Mapping[str, object]]) -> Dict:
    snapshot = env.snapshot()
    return {
        "time_h": float(env.t),
        "uavs": [
            {
                "uav_id": int(index),
                "x_km": float(item["pos"][0]),
                "y_km": float(item["pos"][1]),
                "mode": str(item["mode"]),
                "battery_wh": float(item["b"]),
                "payload": _array(item["ell"]),
                "dest_node": (
                    None if item["dest"] is None else int(item["dest"])
                ),
            }
            for index, item in enumerate(snapshot["uavs"])
        ],
        "true_demand": _dict_arrays(snapshot["true_demand"]),
        "belief_demand": _dict_arrays(snapshot["d_tilde"]),
        "known_nodes": [int(index) for index in snapshot["known"]],
        "inventory": _array(snapshot["S0"]),
        "available": np.asarray(snapshot["available"], dtype=int).tolist(),
        "scaffold": {
            str(index): [
                int(node)
                for node in env.scaffold.next_planned_nodes(index, n=8)
            ]
            for index in range(env.M)
        },
        "last_actions": [dict(row) for row in last_actions],
    }


def _append_state(states: list[Dict], state: Dict) -> None:
    if states and abs(states[-1]["time_h"] - state["time_h"]) <= 1e-12:
        states[-1] = state
    else:
        states.append(state)


def record_trained_policy_rollout(
    *,
    results_dir: Path,
    checkpoint: Path,
    seed: int,
    device: str,
) -> Dict:
    """Run and record the schema-compatible production policy deterministically."""
    metadata = json.loads((results_dir / "metadata.json").read_text(encoding="utf-8"))
    experiment = yaml.safe_load(
        (results_dir / "experiment_config.yaml").read_text(encoding="utf-8")
    )
    params = EnvParams()
    params.mission.T = float(
        experiment["development_runtime"]["mission_horizon_hours"]
    )
    params.hybrid.alns_iterations = int(
        experiment["development_runtime"]["alns_iterations"]
    )

    master_seed = int(metadata["master_seed"])
    random.seed(master_seed)
    np.random.seed(master_seed)
    torch.manual_seed(master_seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(master_seed)
    torch.use_deterministic_algorithms(True)

    scenario = generate_scenario(seed, params)
    env = UAMTVRPIUEnv(params)
    obs, info = env.reset(scenario=scenario)
    loaded, _ = load_agent_config(metadata["agent_config"])
    config = {
        **DEFAULT_AGENT_CONFIG,
        **loaded,
        "gamma_hour": params.mission.gamma_hour,
        "device": device,
        "gate_directional_regularization_coef": float(
            experiment["gate_training"]["directional_regularization_coefficient"]
        ),
        "gate_directional_margin": float(
            experiment["gate_training"]["directional_margin"]
        ),
    }
    agent = _make_agent(env, config, TRAINED_MODE)
    agent.load(checkpoint)
    agent.set_eval()

    states = [_initial_training_state(scenario, params)]
    decisions: list[Dict] = []
    step = 0
    total_reward = 0.0
    _append_state(states, _training_state(env, []))
    while not env.done and step < 6000:
        graph = env.get_operational_belief_graph()
        actions, _, _ = agent.select_actions(
            obs,
            info["masks"],
            env.get_global_state(),
            deterministic=True,
            graph=graph,
            diagnostics_enabled=True,
        )
        action_rows = []
        for uav_id in sorted(actions):
            action = int(actions[uav_id])
            kind, node, other = env.decode_action(uav_id, action)
            detail = agent.last_diagnostics[uav_id]
            row = {
                "decision_index": len(decisions),
                "time_h": float(env.t),
                "uav_id": int(uav_id),
                "action": action,
                "action_kind": str(kind),
                "target_node": "" if node is None else int(node),
                "other_uav": "" if other is None else int(other),
                "recommended_action": int(detail["recommended_action"]),
                "production_gate": float(detail["gate"]),
                "adaptive_gate_diagnostic": float(detail["gate_adaptive"]),
                "prior_nonzero": int(
                    np.any(np.asarray(detail["alns_prior"], dtype=float) > 0.0)
                ),
            }
            decisions.append(row)
            action_rows.append(row)
        _append_state(states, _training_state(env, action_rows))
        obs, reward, _, info = env.step(actions)
        total_reward += float(reward)
        step += 1
        _append_state(states, _training_state(env, action_rows))
    if step >= 6000 and not env.done:
        raise RuntimeError("Trained-policy replay exceeded the 6000-step guard")
    if not decisions:
        raise RuntimeError("Trained-policy replay produced no decisions")
    nonzero_production = [
        row for row in decisions if abs(float(row["production_gate"])) > 1e-12
    ]
    if nonzero_production:
        raise AssertionError(
            "Production graph-MAPPO replay must use g=0; "
            f"found {len(nonzero_production)} nonzero gate decisions"
        )

    metrics = env.metrics.summary()
    metrics.update(
        {
            "total_reward": float(total_reward),
            "steps": int(step),
            "scenario_seed": int(seed),
        }
    )
    return {
        "scenario": scenario,
        "states": states,
        "decisions": decisions,
        "metrics": metrics,
        "checkpoint_sha256": file_sha256(checkpoint),
        "checkpoint": str(checkpoint.resolve()),
        "mode": TRAINED_MODE,
        "production_gate": 0.0,
    }


def _demand_total(values: Mapping[str, Sequence[float]], key) -> float:
    return float(sum(values.get(str(key), [])))


def _state_at(states: Sequence[Dict], time_h: float) -> tuple[Dict, Dict, float]:
    times = [float(state["time_h"]) for state in states]
    right_index = bisect.bisect_right(times, time_h)
    left_index = max(0, right_index - 1)
    right_index = min(right_index, len(states) - 1)
    left, right = states[left_index], states[right_index]
    delta = float(right["time_h"]) - float(left["time_h"])
    weight = 0.0 if delta <= 1e-12 else (time_h - float(left["time_h"])) / delta
    return left, right, float(np.clip(weight, 0.0, 1.0))


def _uav_positions(states: Sequence[Dict], time_h: float) -> np.ndarray:
    left, right, weight = _state_at(states, time_h)
    left_by_id = {int(item["uav_id"]): item for item in left["uavs"]}
    right_by_id = {int(item["uav_id"]): item for item in right["uavs"]}
    positions = []
    for uav_id in sorted(left_by_id):
        start = np.array(
            [left_by_id[uav_id]["x_km"], left_by_id[uav_id]["y_km"]],
            dtype=float,
        )
        end = np.array(
            [right_by_id[uav_id]["x_km"], right_by_id[uav_id]["y_km"]],
            dtype=float,
        )
        positions.append(start + weight * (end - start))
    return np.asarray(positions, dtype=float)


def _audit_hazard(
    scenario: AuditScenario,
    x_m: np.ndarray,
    y_m: np.ndarray,
    active_ids: Iterable[str],
) -> np.ndarray:
    active = set(active_ids)
    field = np.zeros_like(x_m)
    for zone in scenario.geography["dynamic_zones"]:
        if zone["zone_type"] != "hazard" or zone["zone_id"] not in active:
            continue
        scaled = ((x_m - zone["center_x_m"]) / zone["radius_x_m"]) ** 2 + (
            (y_m - zone["center_y_m"]) / zone["radius_y_m"]
        ) ** 2
        field += zone["intensity"] * np.exp(-2.0 * scaled)
    return field


def _audit_leaders(
    scenario: AuditScenario,
    physical,
    controller,
    time_s: float,
) -> tuple[str, str]:
    commodity = scenario.config["commodities"]
    true_scores = {
        node_id: urgency_score(
            physical.node_cohorts.get(node_id, []),
            physical.true_vulnerability.get(node_id, 1.0),
            time_s,
            commodity,
        )
        for node_id in physical.true_vulnerability
    }
    operational_scores = {
        node_id: urgency_score(
            controller.operational_cohorts.get(node_id, []),
            controller.reported_vulnerability.get(node_id, 1.0),
            time_s,
            commodity,
        )
        for node_id in controller.known_nodes
    }
    true_leader = max(true_scores, key=true_scores.get) if true_scores else "—"
    operational_leader = (
        max(operational_scores, key=operational_scores.get)
        if operational_scores
        else "—"
    )
    return true_leader, operational_leader


def _draw_audit_panel(
    ax,
    scenario: AuditScenario,
    replay: ScenarioReplay,
    time_s: float,
) -> None:
    ax.clear()
    physical, controller = replay.snapshot(time_s)
    width_m = float(scenario.geography["width_m"])
    extent_km = width_m / 1000.0
    grid = np.linspace(0.0, width_m, 81)
    gx, gy = np.meshgrid(grid, grid, indexing="xy")
    hazard = _audit_hazard(
        scenario, gx, gy, physical.active_hazard_ids
    )
    risk = composite_risk(gx, gy, scenario.geography, hazard)
    ax.imshow(
        risk,
        origin="lower",
        extent=(0.0, extent_km, 0.0, extent_km),
        vmin=0.0,
        vmax=1.0,
        cmap="YlOrRd",
        alpha=0.58,
        zorder=0,
    )
    terrain = terrain_elevation_m(gx, gy, scenario.geography)
    ax.contour(
        gx / 1000.0,
        gy / 1000.0,
        terrain,
        levels=np.arange(20.0, 141.0, 20.0),
        colors="#596157",
        linewidths=0.28,
        alpha=0.45,
        zorder=1,
    )
    for obstacle in scenario.geography["obstacles"]:
        ax.add_patch(
            Rectangle(
                (
                    obstacle["min_x_m"] / 1000.0,
                    obstacle["min_y_m"] / 1000.0,
                ),
                (obstacle["max_x_m"] - obstacle["min_x_m"]) / 1000.0,
                (obstacle["max_y_m"] - obstacle["min_y_m"]) / 1000.0,
                facecolor="#4f4f4f",
                edgecolor="#202020",
                alpha=0.72,
                zorder=4,
            )
        )
    for zone in scenario.geography["permanent_nfz"]:
        ax.add_patch(
            Circle(
                (zone["center_x_m"] / 1000.0, zone["center_y_m"] / 1000.0),
                zone["radius_m"] / 1000.0,
                facecolor="none",
                edgecolor="#111111",
                hatch="////",
                linewidth=1.0,
                zorder=5,
            )
        )
    for zone in scenario.geography["dynamic_zones"]:
        if (
            zone["zone_type"] == "temporary_nfz"
            and zone["zone_id"] in physical.active_temporary_nfz_ids
        ):
            ax.add_patch(
                Circle(
                    (
                        zone["center_x_m"] / 1000.0,
                        zone["center_y_m"] / 1000.0,
                    ),
                    zone["radius_m"] / 1000.0,
                    color="#d62828",
                    alpha=0.22,
                    zorder=3,
                )
            )
        if (
            zone["zone_type"] == "hazard"
            and zone["zone_id"] in physical.active_hazard_ids
        ):
            ax.add_patch(
                Ellipse(
                    (
                        zone["center_x_m"] / 1000.0,
                        zone["center_y_m"] / 1000.0,
                    ),
                    2.0 * zone["radius_x_m"] / 1000.0,
                    2.0 * zone["radius_y_m"] / 1000.0,
                    color="#f4a261",
                    alpha=0.16,
                    zorder=2,
                )
            )

    mismatch_count = 0
    for corridor in scenario.corridors:
        points = np.asarray(corridor.waypoints_m, dtype=float) / 1000.0
        true_condition = physical.corridor_conditions[corridor.corridor_id]
        believed_condition = controller.believed_corridor_conditions.get(
            corridor.corridor_id
        )
        if believed_condition is not None and true_condition != believed_condition:
            mismatch_count += 1
        fixture = corridor.fixture_role is not None
        ax.plot(
            points[:, 0],
            points[:, 1],
            color=CONDITION_COLORS[true_condition],
            linewidth=1.5 if fixture else 0.35,
            alpha=0.9 if fixture else 0.16,
            zorder=5 if fixture else 2,
        )
        if (
            fixture
            and believed_condition is not None
            and believed_condition != true_condition
        ):
            ax.plot(
                points[:, 0],
                points[:, 1],
                color=CONDITION_COLORS[believed_condition],
                linewidth=2.6,
                linestyle="--",
                alpha=0.85,
                zorder=6,
            )

    for node in scenario.nodes:
        node_id = node["node_id"]
        if node["onset_time_s"] > time_s:
            continue
        true_total = sum(
            float(item["quantity"])
            for item in physical.node_cohorts.get(node_id, [])
        )
        operational_total = sum(
            float(item["quantity"])
            for item in controller.operational_cohorts.get(node_id, [])
        )
        known = node_id in controller.known_nodes
        ax.scatter(
            node["x_m"] / 1000.0,
            node["y_m"] / 1000.0,
            s=38.0 + 2.0 * true_total,
            marker="o" if known else "X",
            color="#264653" if known else "#8d99ae",
            edgecolor="white",
            linewidth=0.7,
            zorder=8,
        )
        ax.annotate(
            f"{node_id}  T/O={true_total:.0f}/{operational_total:.0f}",
            (node["x_m"] / 1000.0, node["y_m"] / 1000.0),
            xytext=(4, 4),
            textcoords="offset points",
            fontsize=6.2,
            zorder=9,
        )
    ax.scatter(
        scenario.depot["x_m"] / 1000.0,
        scenario.depot["y_m"] / 1000.0,
        marker="*",
        s=165,
        color="#ffd166",
        edgecolor="#111111",
        zorder=9,
    )

    action = replay.audit_actions["actions"][0]
    action_time = float(action["time_s"])
    if action_time <= time_s <= action_time + 0.35 * 3600.0:
        target = next(
            node for node in scenario.nodes if node["node_id"] == action["node_id"]
        )
        ax.scatter(
            target["x_m"] / 1000.0,
            target["y_m"] / 1000.0,
            marker="^",
            s=180,
            facecolor="#ff7f0e",
            edgecolor="white",
            linewidth=1.2,
            zorder=12,
        )
        ax.annotate(
            "UAV0 audited service visit",
            (target["x_m"] / 1000.0, target["y_m"] / 1000.0),
            xytext=(8, -15),
            textcoords="offset points",
            fontsize=7,
            color="#7f2704",
            zorder=13,
        )

    true_leader, operational_leader = _audit_leaders(
        scenario, physical, controller, time_s
    )
    recent_events = [
        event.event_type
        for event in scenario.exogenous_events
        if 0.0
        <= time_s - event.physical_occurrence_time_s
        <= 0.30 * 3600.0
    ]
    status = (
        f"t={time_s / 3600.0:4.2f} h  |  true/op urgency: "
        f"{true_leader}/{operational_leader}\n"
        f"corridor truth-belief mismatches: {mismatch_count}  |  "
        f"recent physical events: {', '.join(recent_events) or 'none'}\n"
        "Corridors: truth=solid, differing belief=dashed. UAV paths are "
        "unspecified; only the audited service action is marked."
    )
    ax.text(
        0.015,
        0.015,
        status,
        transform=ax.transAxes,
        fontsize=7,
        va="bottom",
        ha="left",
        bbox={"facecolor": "white", "alpha": 0.82, "edgecolor": "#777777"},
        zorder=20,
    )
    ax.set(
        xlim=(0.0, extent_km),
        ylim=(0.0, extent_km),
        xlabel="x [km]",
        ylabel="y [km]",
        title=(
            "AUDIT SCENARIO-V2 — SCRIPTED AUDIT POLICY\n"
            "6 nodes · 2 UAV IDs · exact audit JSON · 0–8 h"
        ),
    )
    ax.set_aspect("equal")


def _draw_trained_panel(
    ax,
    rollout: Dict,
    time_h: float,
    trail_times: np.ndarray,
) -> None:
    ax.clear()
    scenario = rollout["scenario"]
    states = rollout["states"]
    left, _, _ = _state_at(states, time_h)
    region = float(scenario.env_params().map.region_km)
    grid = np.linspace(0.0, region, 71)
    gx, gy = np.meshgrid(grid, grid, indexing="xy")
    points = np.stack([gx, gy], axis=-1)
    hazard = scenario.fields().H(points, time_h)
    ax.imshow(
        hazard,
        origin="lower",
        extent=(0.0, region, 0.0, region),
        vmin=0.0,
        vmax=1.5,
        cmap="magma",
        alpha=0.48,
        zorder=0,
    )

    positions = scenario.node_positions()
    known = {int(item) for item in left["known_nodes"]}
    for uav_id, nodes in left["scaffold"].items():
        if not nodes:
            continue
        current = _uav_positions(states, time_h)[int(uav_id)]
        route = [current] + [positions[int(node)] for node in nodes]
        route_array = np.asarray(route)
        ax.plot(
            route_array[:, 0],
            route_array[:, 1],
            linestyle="--",
            linewidth=1.0,
            color=UAV_COLORS[int(uav_id)],
            alpha=0.55,
            zorder=2,
        )

    availability = np.asarray(left["available"], dtype=int)
    closed_pairs = []
    if availability.size:
        for source in range(-1, len(positions)):
            for destination in range(source + 1, len(positions)):
                source_slot = 0 if source == -1 else source + 1
                destination_slot = destination + 1
                if availability[source_slot, destination_slot]:
                    continue
                a = np.asarray(scenario.depot if source == -1 else positions[source])
                b = positions[destination]
                closed_pairs.append((float(np.linalg.norm(b - a)), a, b))
        for _, a, b in sorted(closed_pairs, key=lambda item: item[0])[:8]:
            ax.plot(
                [a[0], b[0]],
                [a[1], b[1]],
                color="#d62828",
                linestyle=":",
                linewidth=1.0,
                alpha=0.48,
                zorder=1,
            )

    for index, node in enumerate(scenario.nodes):
        true_total = _demand_total(left["true_demand"], index)
        belief_total = _demand_total(left["belief_demand"], index)
        is_known = index in known
        ax.scatter(
            node.x,
            node.y,
            s=23.0 + 1.25 * true_total,
            marker="o" if is_known else "X",
            color="#1d3557" if is_known else "#8d99ae",
            edgecolor="white",
            linewidth=0.55,
            zorder=6,
        )
        ax.annotate(
            f"N{index} {true_total:.0f}/{belief_total:.0f}",
            (node.x, node.y),
            xytext=(3, 3),
            textcoords="offset points",
            fontsize=5.2,
            zorder=7,
        )
    ax.scatter(
        scenario.depot[0],
        scenario.depot[1],
        marker="*",
        s=170,
        color="#ffd166",
        edgecolor="#111111",
        zorder=8,
    )

    current_positions = _uav_positions(states, time_h)
    for uav_id, current in enumerate(current_positions):
        prior_times = trail_times[trail_times <= time_h]
        if len(prior_times):
            trail = np.asarray(
                [_uav_positions(states, value)[uav_id] for value in prior_times]
            )
            ax.plot(
                trail[:, 0],
                trail[:, 1],
                color=UAV_COLORS[uav_id],
                linewidth=1.4,
                alpha=0.75,
                zorder=8,
            )
        ax.scatter(
            current[0],
            current[1],
            marker=UAV_MARKERS[uav_id],
            s=95,
            color=UAV_COLORS[uav_id],
            edgecolor="white",
            linewidth=0.9,
            zorder=10,
        )
        ax.annotate(
            f"UAV{uav_id}",
            current,
            xytext=(5 + 2 * uav_id, -10 - 9 * uav_id),
            textcoords="offset points",
            fontsize=6.6,
            zorder=11,
        )

    wind = scenario.fields().wind_vector(time_h)
    ax.quiver(
        region * 0.84,
        region * 0.92,
        wind[0],
        wind[1],
        color="#023047",
        angles="xy",
        scale_units="xy",
        scale=max(np.linalg.norm(wind), 1e-6) / 0.75,
        width=0.006,
        zorder=12,
    )
    actions = left["last_actions"]
    action_text = ", ".join(
        f"U{row['uav_id']}:{row['action_kind']}"
        + (f" N{row['target_node']}" if row["target_node"] != "" else "")
        for row in actions
    )
    status = (
        f"t={time_h:4.2f} h  |  production gate g=0  |  "
        f"known nodes={len(known)}/{len(scenario.nodes)}\n"
        f"inventory={','.join(f'{value:.0f}' for value in left['inventory'])}  |  "
        f"closed OD pairs={len(closed_pairs)} (8 shortest shown)  |  "
        f"last actions: {action_text or 'none'}\n"
        f"checkpoint SHA-256: {rollout['checkpoint_sha256'][:16]}…"
    )
    ax.text(
        0.015,
        0.015,
        status,
        transform=ax.transAxes,
        fontsize=7,
        va="bottom",
        ha="left",
        bbox={"facecolor": "white", "alpha": 0.82, "edgecolor": "#777777"},
        zorder=20,
    )
    ax.set(
        xlim=(0.0, region),
        ylim=(0.0, region),
        xlabel="x [km]",
        ylabel="y [km]",
        title=(
            "TRAINED PRODUCTION POLICY — UNGUIDED GRAPH-MAPPO, g=0\n"
            "20 nodes · 3 UAVs · training-compatible seed 18427 · 0–1 h"
        ),
    )
    ax.set_aspect("equal")


def _draw_comparison(
    *,
    audit_scenario: AuditScenario,
    audit_replay: ScenarioReplay,
    rollout: Dict,
    progress: float,
    figure,
    axes,
    trail_times: np.ndarray,
) -> None:
    audit_time_s = progress * AUDIT_HORIZON_S
    trained_time_h = progress * float(rollout["scenario"].env_params().mission.T)
    _draw_audit_panel(axes[0], audit_scenario, audit_replay, audit_time_s)
    _draw_trained_panel(axes[1], rollout, trained_time_h, trail_times)
    figure.suptitle(
        "SEED 18427 — SCHEMA-CORRECT SIDE-BY-SIDE REPLAY "
        "(normalized progress; independent clocks)",
        fontsize=12,
        fontweight="bold",
    )


def _crop_animation(
    source: Path,
    destination: Path,
    *,
    side: str,
) -> None:
    with Image.open(source) as image:
        width, height = image.size
        if side == "left":
            box = (0, 24, width // 2, height)
        elif side == "right":
            box = (width // 2, 24, width, height)
        else:
            raise ValueError(f"Unsupported crop side: {side}")
        frames = []
        durations = []
        for frame in ImageSequence.Iterator(image):
            durations.append(int(frame.info.get("duration", image.info.get("duration", 100))))
            frames.append(frame.convert("RGB").crop(box))
        frames[0].save(
            destination,
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
            optimize=False,
            disposal=2,
        )


def render_comparison_package(
    *,
    audit_scenario: AuditScenario,
    audit_replay: ScenarioReplay,
    rollout: Dict,
    output_dir: Path,
    frames: int,
    fps: int,
) -> list[Path]:
    if frames < 2:
        raise ValueError("At least two animation frames are required")
    if fps <= 0:
        raise ValueError("Animation FPS must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    progress = np.linspace(0.0, 1.0, frames)
    trained_horizon = float(rollout["scenario"].env_params().mission.T)
    trail_times = np.linspace(0.0, trained_horizon, frames)
    with plt.rc_context(
        {
            "font.family": "DejaVu Sans",
            "axes.grid": True,
            "grid.linestyle": ":",
            "grid.alpha": 0.22,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    ):
        figure, axes = plt.subplots(
            1,
            2,
            figsize=(16.0, 7.7),
            dpi=100,
            constrained_layout=True,
        )

        def update(frame_index):
            _draw_comparison(
                audit_scenario=audit_scenario,
                audit_replay=audit_replay,
                rollout=rollout,
                progress=float(progress[frame_index]),
                figure=figure,
                axes=axes,
                trail_times=trail_times,
            )
            return []

        combined_path = output_dir / "seed_18427_side_by_side.gif"
        animation = FuncAnimation(
            figure,
            update,
            frames=frames,
            interval=1000.0 / fps,
            blit=False,
        )
        animation.save(combined_path, writer=PillowWriter(fps=fps))

        preview_path = output_dir / "seed_18427_comparison_preview.png"
        _draw_comparison(
            audit_scenario=audit_scenario,
            audit_replay=audit_replay,
            rollout=rollout,
            progress=0.525,
            figure=figure,
            axes=axes,
            trail_times=trail_times,
        )
        figure.savefig(preview_path, dpi=150, facecolor="white")
        plt.close(figure)

    audit_path = output_dir / "audit_scenario_v2_scripted.gif"
    trained_path = output_dir / "trained_graph_mappo_seed18427.gif"
    _crop_animation(combined_path, audit_path, side="left")
    _crop_animation(combined_path, trained_path, side="right")
    outputs = [combined_path, audit_path, trained_path, preview_path]
    if not all(path.is_file() and path.stat().st_size > 0 for path in outputs):
        raise RuntimeError("One or more scene-comparison visuals were not generated")
    return outputs


def _flatten_states(states: Sequence[Dict]) -> list[Dict]:
    rows = []
    for state_index, state in enumerate(states):
        for uav in state["uavs"]:
            rows.append(
                {
                    "state_index": state_index,
                    "time_h": state["time_h"],
                    "uav_id": uav["uav_id"],
                    "x_km": uav["x_km"],
                    "y_km": uav["y_km"],
                    "mode": uav["mode"],
                    "battery_wh": uav["battery_wh"],
                    "payload_0": uav["payload"][0],
                    "payload_1": uav["payload"][1],
                    "payload_2": uav["payload"][2],
                    "payload_3": uav["payload"][3],
                    "dest_node": (
                        "" if uav["dest_node"] is None else uav["dest_node"]
                    ),
                }
            )
    return rows


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audit-scenario",
        type=Path,
        default=Path("outputs/seed_18427/seed_18427.json"),
    )
    parser.add_argument(
        "--audit-actions",
        type=Path,
        default=Path("outputs/seed_18427/audit_actions.json"),
    )
    parser.add_argument(
        "--results",
        type=Path,
        default=Path("results/gate_learning_final"),
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        help="Defaults to graph_mappo/checkpoints/final.pt below --results.",
    )
    parser.add_argument("--seed", type=int, default=18427)
    parser.add_argument("--device", default="cpu")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/seed_18427_scene_comparison"),
    )
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--fps", type=int, default=6)
    return parser


def main() -> int:
    args = _parser().parse_args()
    checkpoint = args.checkpoint or (
        args.results / "graph_mappo" / "checkpoints" / "final.pt"
    )
    for required in (
        args.audit_scenario,
        args.audit_actions,
        args.results / "metadata.json",
        args.results / "experiment_config.yaml",
        checkpoint,
    ):
        if not required.is_file():
            raise FileNotFoundError(f"Required comparison input is missing: {required}")

    audit_scenario = AuditScenario.from_json(args.audit_scenario)
    audit_actions = load_audit_actions(args.audit_actions)
    if int(audit_scenario.metadata["master_seed"]) != args.seed:
        raise ValueError("Audit scenario seed does not match --seed")
    if int(audit_actions["scenario_seed"]) != args.seed:
        raise ValueError("Audit action seed does not match --seed")
    audit_replay = ScenarioReplay(audit_scenario, audit_actions)

    rollout = record_trained_policy_rollout(
        results_dir=args.results,
        checkpoint=checkpoint,
        seed=args.seed,
        device=args.device,
    )
    if len(audit_scenario.nodes) == len(rollout["scenario"].nodes):
        raise AssertionError(
            "Comparison must not conceal the audit/training schema distinction"
        )

    _write_csv(
        args.output / "trained_policy_trajectory.csv",
        _flatten_states(rollout["states"]),
    )
    _write_csv(args.output / "trained_policy_decisions.csv", rollout["decisions"])
    visuals = render_comparison_package(
        audit_scenario=audit_scenario,
        audit_replay=audit_replay,
        rollout=rollout,
        output_dir=args.output,
        frames=args.frames,
        fps=args.fps,
    )
    manifest = {
        "seed": int(args.seed),
        "comparison_semantics": (
            "Normalized visual progress only. Independent clocks and incompatible "
            "schemas are retained; the trained policy does not control audit-v2."
        ),
        "audit_panel": {
            "scenario": str(args.audit_scenario.resolve()),
            "scenario_sha256": hashlib.sha256(
                args.audit_scenario.read_bytes()
            ).hexdigest(),
            "scenario_content_hash": audit_scenario.content_hash(),
            "actions": str(args.audit_actions.resolve()),
            "actions_sha256": hashlib.sha256(
                args.audit_actions.read_bytes()
            ).hexdigest(),
            "node_count": len(audit_scenario.nodes),
            "uav_count": int(audit_scenario.fleet["uav_count"]),
            "horizon_h": AUDIT_HORIZON_S / 3600.0,
            "policy": "separate scripted audit action fixture",
            "uav_position_limitation": (
                "The audit fixture specifies a service visit but no continuous "
                "flight trajectory; no path is fabricated."
            ),
        },
        "trained_panel": {
            "checkpoint": rollout["checkpoint"],
            "checkpoint_sha256": rollout["checkpoint_sha256"],
            "mode": rollout["mode"],
            "production_gate": rollout["production_gate"],
            "node_count": len(rollout["scenario"].nodes),
            "uav_count": rollout["scenario"].env_params().mission.M,
            "horizon_h": rollout["scenario"].env_params().mission.T,
            "decision_count": len(rollout["decisions"]),
            "state_count": len(rollout["states"]),
            "metrics": rollout["metrics"],
        },
        "visuals": [str(path.resolve()) for path in visuals],
        "trajectory": str(
            (args.output / "trained_policy_trajectory.csv").resolve()
        ),
        "decisions": str(
            (args.output / "trained_policy_decisions.csv").resolve()
        ),
    }
    _canonical_json(args.output / "comparison_manifest.json", manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
