"""Static, publication-style audit figures for scenario-v2."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Ellipse, Rectangle

from .audit_artifacts import MANDATORY_FIGURES
from .audit_geometry import composite_risk, terrain_elevation_m
from .audit_model import AuditScenario
from .audit_replay import ScenarioReplay, urgency_score
from .units import seconds_to_hours


STYLE = {
    "font.family": "DejaVu Sans",
    "axes.grid": True,
    "grid.linestyle": ":",
    "grid.alpha": 0.3,
    "axes.spines.top": False,
    "axes.spines.right": False,
}

CONDITION_STYLE = {
    "NORMAL": ("#2a9d8f", "-", 0.65),
    "DEGRADED": ("#e9c46a", "--", 0.9),
    "CLOSED": ("#d62828", ":", 1.0),
}


def _hazard_field(
    scenario: AuditScenario, x: np.ndarray, y: np.ndarray, active_ids: Sequence[str]
) -> np.ndarray:
    field = np.zeros_like(x)
    for zone in scenario.geography["dynamic_zones"]:
        if zone["zone_type"] != "hazard" or zone["zone_id"] not in active_ids:
            continue
        scaled = ((x - zone["center_x_m"]) / zone["radius_x_m"]) ** 2 + (
            (y - zone["center_y_m"]) / zone["radius_y_m"]
        ) ** 2
        field += zone["intensity"] * np.exp(-2.0 * scaled)
    return field


def _map_background(
    ax,
    scenario: AuditScenario,
    replay: ScenarioReplay,
    time_s: float,
    view: str,
) -> None:
    physical, controller = replay.snapshot(time_s)
    extent_km = scenario.geography["width_m"] / 1000.0
    grid = np.linspace(0.0, scenario.geography["width_m"], 101)
    gx, gy = np.meshgrid(grid, grid, indexing="xy")
    if view == "truth":
        active_hazards = physical.active_hazard_ids
        active_temp = physical.active_temporary_nfz_ids
        conditions = physical.corridor_conditions
        known = {
            node["node_id"]
            for node in scenario.nodes
            if node["onset_time_s"] <= time_s
        }
        cohorts = physical.node_cohorts
        vulnerability = physical.true_vulnerability
    else:
        active_hazards = [
            zone_id
            for zone_id in physical.active_hazard_ids
            if zone_id in controller.received_zone_notices
        ]
        active_temp = [
            zone_id
            for zone_id in physical.active_temporary_nfz_ids
            if zone_id in controller.received_zone_notices
        ]
        conditions = controller.believed_corridor_conditions
        known = set(controller.known_nodes)
        cohorts = controller.operational_cohorts
        vulnerability = controller.reported_vulnerability
    hazard = _hazard_field(scenario, gx, gy, active_hazards)
    risk = composite_risk(gx, gy, scenario.geography, hazard)
    image = ax.imshow(
        risk,
        origin="lower",
        extent=[0.0, extent_km, 0.0, extent_km],
        vmin=0.0,
        vmax=1.0,
        cmap="YlOrRd",
        alpha=0.62,
        zorder=0,
    )
    terrain = terrain_elevation_m(gx, gy, scenario.geography)
    ax.contour(
        gx / 1000.0,
        gy / 1000.0,
        terrain,
        levels=np.arange(20.0, 141.0, 20.0),
        colors="#6b705c",
        linewidths=0.35,
        alpha=0.55,
        zorder=1,
    )
    for obstacle in scenario.geography["obstacles"]:
        ax.add_patch(
            Rectangle(
                (obstacle["min_x_m"] / 1000.0, obstacle["min_y_m"] / 1000.0),
                (obstacle["max_x_m"] - obstacle["min_x_m"]) / 1000.0,
                (obstacle["max_y_m"] - obstacle["min_y_m"]) / 1000.0,
                facecolor="#5b5b5b",
                edgecolor="black",
                alpha=0.75,
                zorder=4,
            )
        )
        ax.text(
            (obstacle["min_x_m"] + obstacle["max_x_m"]) / 2000.0,
            (obstacle["min_y_m"] + obstacle["max_y_m"]) / 2000.0,
            f"{obstacle['obstacle_id']}\n{obstacle['height_m']:.0f} m",
            ha="center",
            va="center",
            fontsize=6,
            color="white",
            zorder=5,
        )
    for zone in scenario.geography["permanent_nfz"]:
        ax.add_patch(
            Circle(
                (zone["center_x_m"] / 1000.0, zone["center_y_m"] / 1000.0),
                zone["radius_m"] / 1000.0,
                facecolor="none",
                edgecolor="black",
                hatch="////",
                linewidth=1.1,
                zorder=5,
            )
        )
    for zone in scenario.geography["dynamic_zones"]:
        if zone["zone_id"] in active_temp:
            ax.add_patch(
                Circle(
                    (zone["center_x_m"] / 1000.0, zone["center_y_m"] / 1000.0),
                    zone["radius_m"] / 1000.0,
                    facecolor="#d62828",
                    edgecolor="#8b0000",
                    alpha=0.25,
                    linewidth=1.8,
                    zorder=4,
                )
            )
        if zone["zone_id"] in active_hazards:
            ax.add_patch(
                Ellipse(
                    (zone["center_x_m"] / 1000.0, zone["center_y_m"] / 1000.0),
                    2 * zone["radius_x_m"] / 1000.0,
                    2 * zone["radius_y_m"] / 1000.0,
                    facecolor="#f4a261",
                    edgecolor="#e76f51",
                    alpha=0.18,
                    linewidth=1.8,
                    zorder=3,
                )
            )
    for corridor in scenario.corridors:
        if corridor.origin not in known and corridor.origin != "DEPOT":
            continue
        if corridor.destination not in known and corridor.destination != "DEPOT":
            continue
        condition = conditions.get(corridor.corridor_id, "NORMAL")
        color, linestyle, alpha = CONDITION_STYLE[condition]
        points = np.asarray(corridor.waypoints_m) / 1000.0
        is_fixture = corridor.fixture_role is not None
        ax.plot(
            points[:, 0],
            points[:, 1],
            color=color,
            linestyle=linestyle,
            linewidth=1.7 if is_fixture else 0.45,
            alpha=alpha if is_fixture else 0.20,
            zorder=2 if not is_fixture else 6,
        )
    for node in scenario.nodes:
        node_id = node["node_id"]
        if node_id not in known:
            continue
        demand = sum(item["quantity"] for item in cohorts.get(node_id, []))
        size = 45.0 + 18.0 * vulnerability[node_id]
        ax.scatter(
            node["x_m"] / 1000.0,
            node["y_m"] / 1000.0,
            s=size,
            c="#264653" if view == "truth" else "#457b9d",
            edgecolors="white",
            linewidths=0.7,
            zorder=8,
        )
        label_left = node["x_m"] > 0.80 * scenario.geography["width_m"]
        ax.annotate(
            f"{node_id}\nD={demand:.0f}",
            (node["x_m"] / 1000.0, node["y_m"] / 1000.0),
            xytext=(-4 if label_left else 4, 4),
            textcoords="offset points",
            ha="right" if label_left else "left",
            fontsize=6.5,
            zorder=9,
        )
    ax.scatter(
        scenario.depot["x_m"] / 1000.0,
        scenario.depot["y_m"] / 1000.0,
        marker="*",
        s=190,
        c="gold",
        edgecolors="black",
        zorder=9,
    )
    ax.set_xlim(0.0, extent_km)
    ax.set_ylim(0.0, extent_km)
    ax.set_aspect("equal")
    ax.set_xlabel("x [km]")
    ax.set_ylabel("y [km]")
    title = "Physical truth" if view == "truth" else "Controller view"
    ax.set_title(f"{title} at t = {seconds_to_hours(time_s):.1f} h", fontweight="bold")
    return image


def _save_single_map(
    scenario: AuditScenario,
    replay: ScenarioReplay,
    time_s: float,
    view: str,
    path: Path,
) -> None:
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(8.4, 7.2), dpi=170)
        image = _map_background(ax, scenario, replay, time_s, view)
        fig.colorbar(image, ax=ax, fraction=0.045, label="Composite geographical risk [0,1]")
        handles = [
            Line2D([0], [0], color=CONDITION_STYLE[name][0],
                   linestyle=CONDITION_STYLE[name][1], label=name)
            for name in ("NORMAL", "DEGRADED", "CLOSED")
        ]
        ax.legend(handles=handles, loc="upper left", fontsize=7)
        fig.tight_layout()
        fig.savefig(path, dpi=170, bbox_inches="tight", facecolor="white")
        plt.close(fig)


def _save_comparison(
    scenario: AuditScenario, replay: ScenarioReplay, time_s: float, path: Path
) -> None:
    with plt.rc_context(STYLE):
        fig, axes = plt.subplots(1, 2, figsize=(14.8, 6.6), dpi=170, sharex=True, sharey=True)
        image = _map_background(axes[0], scenario, replay, time_s, "truth")
        _map_background(axes[1], scenario, replay, time_s, "controller")
        colorbar_axis = fig.add_axes([0.925, 0.14, 0.014, 0.72])
        fig.colorbar(
            image,
            cax=colorbar_axis,
            label="Composite geographical risk [0,1]",
        )
        fig.suptitle(
            "Truth versus controller information — identical extent, time, and risk scale",
            fontsize=12,
            fontweight="bold",
        )
        fig.subplots_adjust(left=0.06, right=0.89, top=0.90, bottom=0.09, wspace=0.12)
        fig.savefig(path, dpi=170, bbox_inches="tight", facecolor="white")
        plt.close(fig)


def _save_event_timeline(scenario: AuditScenario, path: Path) -> None:
    with plt.rc_context(STYLE):
        events = scenario.exogenous_events
        fig, ax = plt.subplots(figsize=(12.5, 7.4), dpi=170)
        for y, event in enumerate(events):
            physical_h = seconds_to_hours(event.physical_occurrence_time_s)
            ax.scatter(physical_h, y, marker="o", c="#264653", s=28, zorder=4)
            if event.report_generation_time_s is not None:
                generation_h = seconds_to_hours(event.report_generation_time_s)
                ax.scatter(generation_h, y, marker="^", c="#e9c46a", s=34, zorder=4)
                ax.plot([physical_h, generation_h], [y, y], color="#999999", lw=1)
            if event.report_reception_time_s is not None:
                reception_h = seconds_to_hours(event.report_reception_time_s)
                ax.scatter(reception_h, y, marker="s", c="#2a9d8f", s=30, zorder=4)
                ax.plot([physical_h, reception_h], [y, y], color="#d62828", lw=1.4)
            elif event.report_lost:
                ax.scatter(
                    seconds_to_hours(event.report_generation_time_s or event.physical_occurrence_time_s),
                    y,
                    marker="x",
                    c="#d62828",
                    s=45,
                    zorder=5,
                )
        ax.set_yticks(range(len(events)))
        ax.set_yticklabels([f"{event.event_id}: {event.event_type}" for event in events], fontsize=6.6)
        ax.set_xlabel("Mission time [h]")
        ax.set_title("Exogenous event and report timeline", fontweight="bold")
        ax.legend(
            handles=[
                Line2D([0], [0], marker="o", color="w", markerfacecolor="#264653", label="Physical occurrence"),
                Line2D([0], [0], marker="^", color="w", markerfacecolor="#e9c46a", label="Report generation"),
                Line2D([0], [0], marker="s", color="w", markerfacecolor="#2a9d8f", label="Report reception"),
                Line2D([0], [0], marker="x", color="#d62828", label="Lost report"),
            ],
            loc="lower right",
            fontsize=7,
        )
        fig.tight_layout()
        fig.savefig(path, dpi=170, bbox_inches="tight", facecolor="white")
        plt.close(fig)


def _save_corridor_timeline(
    scenario: AuditScenario, replay: ScenarioReplay, path: Path
) -> None:
    ids = [
        "corridor_depot_n3_south_outbound",
        "corridor_depot_n3_north_alternative",
        "corridor_n1_n5_hazard_outbound",
        "corridor_n1_n5_north_alternative",
    ]
    times_s = np.linspace(0.0, 8.0 * 3600.0, 161)
    mapping = {"NORMAL": 0, "DEGRADED": 1, "CLOSED": 2}
    true_data = np.zeros((len(ids), len(times_s)), dtype=int)
    operational_data = np.zeros_like(true_data)
    for column, time_s in enumerate(times_s):
        physical, controller = replay.snapshot(float(time_s))
        for row, corridor_id in enumerate(ids):
            true_data[row, column] = mapping[physical.corridor_conditions[corridor_id]]
            operational_data[row, column] = mapping[
                controller.believed_corridor_conditions[corridor_id]
            ]
    cmap = ListedColormap(["#2a9d8f", "#e9c46a", "#d62828"])
    with plt.rc_context(STYLE):
        fig, axes = plt.subplots(2, 1, figsize=(12.0, 5.8), dpi=170, sharex=True)
        for ax, data, title in zip(
            axes, [true_data, operational_data], ["Physical condition", "Operational belief"]
        ):
            ax.imshow(
                data,
                aspect="auto",
                origin="upper",
                extent=[0.0, 8.0, len(ids) - 0.5, -0.5],
                cmap=cmap,
                vmin=-0.5,
                vmax=2.5,
                interpolation="nearest",
            )
            ax.set_yticks(range(len(ids)))
            ax.set_yticklabels(ids, fontsize=7)
            ax.set_title(title, fontweight="bold")
            ax.axvline(4.2, color="black", lw=1.1, linestyle="--")
        axes[-1].set_xlabel("Mission time [h]")
        fig.legend(
            handles=[
                Line2D([0], [0], color="#2a9d8f", lw=6, label="NORMAL"),
                Line2D([0], [0], color="#e9c46a", lw=6, label="DEGRADED"),
                Line2D([0], [0], color="#d62828", lw=6, label="CLOSED"),
            ],
            loc="lower center",
            ncol=3,
            fontsize=8,
        )
        fig.suptitle("Named corridor physical and operational status", fontweight="bold")
        fig.tight_layout(rect=[0, 0.08, 1, 0.94])
        fig.savefig(path, dpi=170, bbox_inches="tight", facecolor="white")
        plt.close(fig)


def _cohort_total(cohorts: Dict[str, List[Dict]], node: str, commodity_index: int) -> float:
    return float(
        sum(
            item["quantity"]
            for item in cohorts.get(node, [])
            if item["commodity_index"] == commodity_index
        )
    )


def _save_demand_plot(replay: ScenarioReplay, path: Path) -> None:
    times_s = np.linspace(0.0, 8.0 * 3600.0, 241)
    truth, operational = [], []
    for time_s in times_s:
        physical, controller = replay.snapshot(float(time_s))
        truth.append(_cohort_total(physical.node_cohorts, "N3", 2))
        operational.append(_cohort_total(controller.operational_cohorts, "N3", 2))
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(10.5, 5.5), dpi=170)
        ax.step(times_s / 3600.0, truth, where="post", lw=2.2, color="#d62828", label="True water demand")
        ax.step(times_s / 3600.0, operational, where="post", lw=2.0, color="#457b9d", label="Operational water demand")
        for time_h, color, label in [
            (3.6, "#8e44ad", "Hidden P3"),
            (5.1, "#2a9d8f", "P1 received"),
            (6.0, "#f4a261", "Audit delivery"),
            (6.32, "#264653", "P4 received"),
        ]:
            ax.axvline(time_h, color=color, linestyle="--", lw=1.1, label=label)
        ax.set_xlabel("Mission time [h]")
        ax.set_ylabel("Residual standardized water units")
        ax.set_title("N3 truth versus reported water demand", fontweight="bold")
        ax.legend(ncol=3, fontsize=7.5)
        fig.tight_layout()
        fig.savefig(path, dpi=170, bbox_inches="tight", facecolor="white")
        plt.close(fig)


def _save_urgency_plot(
    scenario: AuditScenario, replay: ScenarioReplay, path: Path
) -> None:
    times_s = np.linspace(0.05 * 3600.0, 8.0 * 3600.0, 241)
    node_ids = [node["node_id"] for node in scenario.nodes]
    values = {node_id: [] for node_id in node_ids}
    commodity = scenario.config["commodities"]
    for time_s in times_s:
        physical, _ = replay.snapshot(float(time_s))
        for node_id in node_ids:
            values[node_id].append(
                urgency_score(
                    physical.node_cohorts.get(node_id, []),
                    physical.true_vulnerability.get(node_id, 1.0),
                    float(time_s),
                    commodity,
                )
            )
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(10.8, 6.0), dpi=170)
        for node_id in node_ids:
            ax.plot(times_s / 3600.0, values[node_id], lw=1.8, label=node_id)
        for time_h, label in [(3.6, "P3"), (5.1, "P1"), (6.0, "delivery")]:
            ax.axvline(time_h, color="black", linestyle="--", lw=0.9)
            ax.text(time_h + 0.03, ax.get_ylim()[1] * 0.92, label, rotation=90, fontsize=7)
        ax.set_xlabel("Mission time [h]")
        ax.set_ylabel("True urgency rate")
        ax.set_title("Continuous cohort-based true urgency evolution", fontweight="bold")
        ax.legend(ncol=3, fontsize=8)
        fig.tight_layout()
        fig.savefig(path, dpi=170, bbox_inches="tight", facecolor="white")
        plt.close(fig)


def generate_audit_figures(
    scenario: AuditScenario,
    replay: ScenarioReplay,
    output_dir: str | Path,
    time_s: float,
) -> List[Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    _save_single_map(scenario, replay, time_s, "truth", output / MANDATORY_FIGURES[0])
    _save_single_map(scenario, replay, time_s, "controller", output / MANDATORY_FIGURES[1])
    _save_comparison(scenario, replay, time_s, output / MANDATORY_FIGURES[2])
    _save_event_timeline(scenario, output / MANDATORY_FIGURES[3])
    _save_corridor_timeline(scenario, replay, output / MANDATORY_FIGURES[4])
    _save_demand_plot(replay, output / MANDATORY_FIGURES[5])
    _save_urgency_plot(scenario, replay, output / MANDATORY_FIGURES[6])
    return [output / name for name in MANDATORY_FIGURES]
