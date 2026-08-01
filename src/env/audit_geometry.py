"""Geometry, fixed-reference risk, and directed corridor evaluation."""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np

from .audit_model import Corridor, CorridorCondition


def sample_polyline(
    waypoints_m: Sequence[Sequence[float]], spacing_m: float = 25.0
) -> np.ndarray:
    """Return deterministic, approximately equally spaced polyline samples."""
    parts: List[np.ndarray] = []
    pts = np.asarray(waypoints_m, dtype=float)
    for index, (a, b) in enumerate(zip(pts[:-1], pts[1:])):
        length = float(np.linalg.norm(b - a))
        count = max(2, int(math.ceil(length / spacing_m)) + 1)
        segment = np.linspace(a, b, count)
        if index:
            segment = segment[1:]
        parts.append(segment)
    return np.vstack(parts) if parts else pts.copy()


def polyline_length(waypoints_m: Sequence[Sequence[float]]) -> float:
    pts = np.asarray(waypoints_m, dtype=float)
    return float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())


def _point_rectangle_distance(points: np.ndarray, rectangle: Dict) -> np.ndarray:
    dx = np.maximum.reduce(
        [
            np.full(len(points), rectangle["min_x_m"]) - points[:, 0],
            np.zeros(len(points)),
            points[:, 0] - rectangle["max_x_m"],
        ]
    )
    dy = np.maximum.reduce(
        [
            np.full(len(points), rectangle["min_y_m"]) - points[:, 1],
            np.zeros(len(points)),
            points[:, 1] - rectangle["max_y_m"],
        ]
    )
    return np.hypot(dx, dy)


def minimum_static_clearance_m(
    waypoints_m: Sequence[Sequence[float]], geography: Dict
) -> float:
    points = sample_polyline(waypoints_m)
    distances: List[np.ndarray] = []
    for obstacle in geography["obstacles"]:
        distances.append(_point_rectangle_distance(points, obstacle))
    for zone in geography["permanent_nfz"]:
        center = np.array([zone["center_x_m"], zone["center_y_m"]])
        distances.append(
            np.maximum(np.linalg.norm(points - center, axis=1) - zone["radius_m"], 0.0)
        )
    if not distances:
        return float("inf")
    return float(np.min(np.concatenate(distances)))


def static_feasible(
    waypoints_m: Sequence[Sequence[float]], geography: Dict, clearance_m: float
) -> bool:
    points = sample_polyline(waypoints_m)
    width = geography["width_m"]
    height = geography["height_m"]
    if np.any(points[:, 0] < 0) or np.any(points[:, 0] > width):
        return False
    if np.any(points[:, 1] < 0) or np.any(points[:, 1] > height):
        return False
    for obstacle in geography["obstacles"]:
        if np.any(_point_rectangle_distance(points, obstacle) < clearance_m - 1e-9):
            return False
    for zone in geography["permanent_nfz"]:
        center = np.array([zone["center_x_m"], zone["center_y_m"]])
        distance = np.linalg.norm(points - center, axis=1)
        if np.any(distance < zone["radius_m"] + clearance_m - 1e-9):
            return False
    return True


def intersects_zone(corridor: Corridor, zone: Dict) -> bool:
    points = sample_polyline(corridor.waypoints_m)
    center = np.array([zone["center_x_m"], zone["center_y_m"]])
    delta = points - center
    if zone["shape"] == "circle":
        return bool(np.any(np.linalg.norm(delta, axis=1) <= zone["radius_m"]))
    scaled = (delta[:, 0] / zone["radius_x_m"]) ** 2 + (
        delta[:, 1] / zone["radius_y_m"]
    ) ** 2
    return bool(np.any(scaled <= 1.0))


def terrain_elevation_m(x_m: np.ndarray, y_m: np.ndarray, geography: Dict) -> np.ndarray:
    terrain = geography["terrain_spec"]
    result = np.full_like(np.asarray(x_m, dtype=float), 12.0)
    for peak in terrain["peaks"]:
        d2 = (x_m - peak["x_m"]) ** 2 + (y_m - peak["y_m"]) ** 2
        result += peak["amplitude_m"] * np.exp(
            -d2 / (2.0 * peak["sigma_m"] ** 2)
        )
    amplitude = terrain["seeded_detail_amplitude_m"]
    phase_x, phase_y = terrain["detail_phase"]
    result += amplitude * (
        0.55 * np.sin(np.asarray(x_m) / 620.0 + phase_x)
        + 0.45 * np.cos(np.asarray(y_m) / 710.0 + phase_y)
    )
    return np.maximum(result, 0.0)


def _fixed_normalize(value: np.ndarray, bounds: Sequence[float]) -> np.ndarray:
    lo, hi = float(bounds[0]), float(bounds[1])
    if hi <= lo:
        raise ValueError(f"Invalid fixed normalization reference: {bounds}")
    return np.clip((value - lo) / (hi - lo), 0.0, 1.0)


def raw_risk_layers(
    x_m: np.ndarray, y_m: np.ndarray, geography: Dict, hazard_intensity: float = 0.0
) -> Dict[str, np.ndarray]:
    x = np.asarray(x_m, dtype=float)
    y = np.asarray(y_m, dtype=float)
    nodes = geography["risk_anchors"]
    population = np.zeros_like(x)
    infrastructure = np.zeros_like(x)
    for anchor in nodes:
        d2 = (x - anchor["x_m"]) ** 2 + (y - anchor["y_m"]) ** 2
        population += anchor["population_peak"] * np.exp(
            -d2 / (2.0 * 650.0**2)
        )
        infrastructure += anchor["infrastructure_peak"] * np.exp(
            -d2 / (2.0 * 850.0**2)
        )
    elevation = terrain_elevation_m(x, y, geography)
    terrain_obstacle = np.clip(elevation / 150.0, 0.0, 1.0)
    return {
        "population": population,
        "infrastructure": np.clip(infrastructure, 0.0, 1.5),
        "terrain_obstacle": terrain_obstacle,
        "dynamic_hazard": np.broadcast_to(
            np.asarray(hazard_intensity, dtype=float), x.shape
        ).copy(),
        "landing_difficulty": np.clip(0.25 + 0.5 * terrain_obstacle, 0.0, 1.0),
    }


def normalized_risk_layers(
    x_m: np.ndarray, y_m: np.ndarray, geography: Dict, hazard_intensity: float = 0.0
) -> Dict[str, np.ndarray]:
    raw = raw_risk_layers(x_m, y_m, geography, hazard_intensity)
    refs = geography["risk_reference_ranges"]
    return {
        "population": _fixed_normalize(
            raw["population"], refs["population_people_per_km2"]
        ),
        "infrastructure": _fixed_normalize(
            raw["infrastructure"], refs["infrastructure_index"]
        ),
        "terrain_obstacle": _fixed_normalize(
            raw["terrain_obstacle"], refs["terrain_obstacle_index"]
        ),
        "dynamic_hazard": _fixed_normalize(
            raw["dynamic_hazard"], refs["dynamic_hazard_intensity"]
        ),
        "landing_difficulty": _fixed_normalize(
            raw["landing_difficulty"], refs["landing_difficulty_index"]
        ),
    }


def composite_risk(
    x_m: np.ndarray, y_m: np.ndarray, geography: Dict, hazard_intensity: float = 0.0
) -> np.ndarray:
    layers = normalized_risk_layers(x_m, y_m, geography, hazard_intensity)
    weights = geography["risk_weights"]
    return np.clip(
        weights["population"] * layers["population"]
        + weights["infrastructure"] * layers["infrastructure"]
        + weights["terrain_obstacle"] * layers["terrain_obstacle"]
        + weights["dynamic_hazard"] * layers["dynamic_hazard"],
        0.0,
        1.0,
    )


def condition_at(
    corridor: Corridor, scenario_dict: Dict, time_s: float, operational: bool
) -> CorridorCondition:
    """Evaluate true or received-information corridor condition."""
    if not corridor.static_feasible:
        return CorridorCondition.CLOSED
    condition = CorridorCondition.NORMAL
    for zone in scenario_dict["geography"]["dynamic_zones"]:
        active = zone["active_from_s"] <= time_s < zone["active_to_s"]
        if operational:
            received_on = time_s >= zone["activation_notice_reception_s"]
            received_off = time_s >= zone["expiration_notice_reception_s"]
            active = received_on and not received_off
        if not active or not intersects_zone(corridor, zone):
            continue
        if zone["zone_type"] == "temporary_nfz":
            return CorridorCondition.CLOSED
        condition = CorridorCondition.DEGRADED
    return condition


def directed_corridor_metrics(
    waypoints_m: Sequence[Sequence[float]],
    geography: Dict,
    fleet: Dict,
    payload_kg: float,
    time_s: float = 0.0,
    condition: CorridorCondition = CorridorCondition.NORMAL,
) -> Dict[str, float]:
    pts = np.asarray(waypoints_m, dtype=float)
    elevations = terrain_elevation_m(pts[:, 0], pts[:, 1], geography)
    dz = np.diff(elevations)
    climb = float(np.maximum(dz, 0.0).sum())
    descent = float(np.maximum(-dz, 0.0).sum())
    mass = fleet["empty_mass_kg"] + max(payload_kg, 0.0)
    wind_angle = 0.35 + 2.0 * math.pi * (time_s / 43200.0)
    wind = np.array([4.0 * math.cos(wind_angle), 2.5 * math.sin(wind_angle)])
    travel_s = 0.0
    length_m = 0.0
    for a, b in zip(pts[:-1], pts[1:]):
        vector = b - a
        length = float(np.linalg.norm(vector))
        if length <= 1e-12:
            continue
        direction = vector / length
        ground_speed = max(
            fleet["minimum_ground_speed_m_per_s"],
            fleet["airspeed_m_per_s"] + float(np.dot(wind, direction)),
        )
        travel_s += length / ground_speed
        length_m += length
    energy = (
        length_m * fleet["horizontal_energy_wh_per_m_per_kg"] * mass
        + climb * fleet["climb_energy_wh_per_m_per_kg"] * mass
        + descent * fleet["descent_energy_wh_per_m_per_kg"] * mass
    )
    samples = sample_polyline(waypoints_m)
    risk = float(
        np.mean(composite_risk(samples[:, 0], samples[:, 1], geography))
        * length_m
        / max(geography["width_m"], 1.0)
    )
    if condition == CorridorCondition.DEGRADED:
        multipliers = geography["condition_multipliers"]
        travel_s *= multipliers["time"]
        energy *= multipliers["energy"]
        risk *= multipliers["risk"]
    if condition == CorridorCondition.CLOSED:
        return {
            "length_m": length_m,
            "climb_m": climb,
            "descent_m": descent,
            "travel_time_s": float("inf"),
            "energy_wh": float("inf"),
            "risk": risk,
        }
    return {
        "length_m": length_m,
        "climb_m": climb,
        "descent_m": descent,
        "travel_time_s": travel_s,
        "energy_wh": energy,
        "risk": risk,
    }
