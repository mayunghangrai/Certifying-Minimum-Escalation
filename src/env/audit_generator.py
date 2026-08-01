"""Deterministic scenario-v2 generator for the hand-auditable prototype."""

from __future__ import annotations

import hashlib
import heapq
import json
import math
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import networkx as nx
import numpy as np
import yaml

from .audit_geometry import (
    composite_risk,
    directed_corridor_metrics,
    minimum_static_clearance_m,
    sample_polyline,
    static_feasible,
    terrain_elevation_m,
)
from .audit_model import (
    GENERATOR_VERSION,
    SCHEMA_VERSION,
    AuditScenario,
    Corridor,
    CorridorCondition,
    ExogenousEvent,
    P4Potential,
)
from .params import COMMODITY_NAMES
from .units import CANONICAL_UNITS


STREAM_NAMES = (
    "geography",
    "node_placement",
    "demand",
    "vulnerability",
    "reports",
    "p3_mutations",
    "nfzs",
    "hazards",
    "wind",
    "replenishment",
    "corridors",
    "p4_potential_outcomes",
)


class NamedRandomStreams:
    """Stable named child streams derived without Python's process hash."""

    def __init__(self, master_seed: int):
        self.master_seed = int(master_seed)
        children = np.random.SeedSequence(self.master_seed).spawn(len(STREAM_NAMES))
        self._seed_sequences = dict(zip(STREAM_NAMES, children))
        self._generators = {
            name: np.random.default_rng(seed_sequence)
            for name, seed_sequence in self._seed_sequences.items()
        }

    def rng(self, name: str) -> np.random.Generator:
        return self._generators[name]

    def metadata(self) -> Dict[str, List[int]]:
        return {
            name: [int(v) for v in seq.generate_state(4)]
            for name, seq in self._seed_sequences.items()
        }


def load_prototype_config(path: str | Path) -> Dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"Prototype configuration is not a mapping: {path}")
    return config


def _config_hash(config: Dict) -> str:
    canonical = json.dumps(
        config, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _derive_active_mask(config: Dict) -> List[int]:
    configured = tuple(config["commodities"]["canonical_names"])
    repository = tuple(COMMODITY_NAMES)
    if configured != repository:
        raise ValueError(
            "Canonical commodity mapping mismatch: "
            f"repository={repository}, configuration={configured}"
        )
    active = set(config["commodities"]["active_names"])
    mask = [int(name in active) for name in repository]
    expected = [1, 0, 1, 0]
    if mask != expected:
        raise ValueError(
            "Medical/water mapping invariant failed: "
            f"expected {expected} from {repository}, obtained {mask}"
        )
    return mask


def _build_geography(config: Dict, streams: NamedRandomStreams) -> Dict:
    region = config["region"]
    risk = config["risk"]
    rng = streams.rng("geography")
    detail_phase = [float(rng.uniform(0.0, 2.0 * math.pi)) for _ in range(2)]
    anchors = []
    for node in config["nodes"]:
        total = float(sum(node["true_demand"]))
        anchors.append(
            {
                "node_id": node["node_id"],
                "x_m": node["x_m"],
                "y_m": node["y_m"],
                "population_peak": min(900.0 + 115.0 * total, 4200.0),
                "infrastructure_peak": min(
                    0.15 + 0.12 * node["true_vulnerability"], 0.75
                ),
            }
        )
    geography = {
        "width_m": float(region["width_m"]),
        "height_m": float(region["height_m"]),
        "fine_cell_m": float(region["fine_cell_m"]),
        "coarse_cell_m": float(region["coarse_cell_m"]),
        "altitude_increment_m": float(region["altitude_increment_m"]),
        "minimum_horizontal_clearance_m": float(
            region["minimum_horizontal_clearance_m"]
        ),
        "minimum_vertical_clearance_m": float(
            region["minimum_vertical_clearance_m"]
        ),
        "terrain_spec": {
            "peaks": config["terrain"]["peaks"],
            "seeded_detail_amplitude_m": config["terrain"][
                "seeded_detail_amplitude_m"
            ],
            "detail_phase": detail_phase,
        },
        "obstacles": config["obstacles"],
        "permanent_nfz": config["permanent_nfz"],
        "dynamic_zones": config["dynamic_zones"],
        "risk_reference_ranges": risk["reference_ranges"],
        "risk_weights": risk["weights"],
        "risk_anchors": anchors,
        "condition_multipliers": {
            "time": config["corridors"]["degraded_time_multiplier"],
            "energy": config["corridors"]["degraded_energy_multiplier"],
            "risk": config["corridors"]["degraded_risk_multiplier"],
        },
    }
    cell = geography["coarse_cell_m"]
    xs = np.arange(0.0, geography["width_m"] + 0.5 * cell, cell)
    ys = np.arange(0.0, geography["height_m"] + 0.5 * cell, cell)
    gx, gy = np.meshgrid(xs, ys, indexing="xy")
    terrain = terrain_elevation_m(gx, gy, geography)
    base_risk = composite_risk(gx, gy, geography)
    geography["coarse_grid"] = {
        "x_m": [round(float(v), 6) for v in xs],
        "y_m": [round(float(v), 6) for v in ys],
        "terrain_elevation_m": np.round(terrain, 6).tolist(),
        "base_composite_risk": np.round(base_risk, 8).tolist(),
    }
    return geography


def _positions(config: Dict) -> Dict[str, np.ndarray]:
    result = {
        config["depot"]["depot_id"]: np.array(
            [config["depot"]["x_m"], config["depot"]["y_m"]], dtype=float
        )
    }
    result.update(
        {
            node["node_id"]: np.array([node["x_m"], node["y_m"]], dtype=float)
            for node in config["nodes"]
        }
    )
    return result


def _topology_pairs(config: Dict) -> List[Tuple[str, str]]:
    pos = _positions(config)
    ids = list(pos)
    complete = nx.Graph()
    complete.add_nodes_from(ids)
    for i, left in enumerate(ids):
        for right in ids[i + 1 :]:
            complete.add_edge(
                left, right, weight=float(np.linalg.norm(pos[left] - pos[right]))
            )
    mst = nx.minimum_spanning_tree(complete, weight="weight")
    pairs = {tuple(sorted(edge)) for edge in mst.edges()}
    k = int(config["corridors"]["nearest_neighbours"])
    for node in ids:
        neighbours = sorted(
            (other for other in ids if other != node),
            key=lambda other: (float(np.linalg.norm(pos[node] - pos[other])), other),
        )[:k]
        pairs.update(tuple(sorted((node, other))) for other in neighbours)
    pairs.add(tuple(sorted(("DEPOT", "N3"))))
    pairs.add(tuple(sorted(("N1", "N5"))))
    return sorted(pairs)


def _grid_cell(point: np.ndarray, cell_m: float, size: int) -> Tuple[int, int]:
    return (
        int(np.clip(round(point[0] / cell_m), 0, size - 1)),
        int(np.clip(round(point[1] / cell_m), 0, size - 1)),
    )


def _astar_alternatives(
    origin: np.ndarray,
    destination: np.ndarray,
    geography: Dict,
    count: int,
    path_penalty: float,
) -> List[List[List[float]]]:
    cell = geography["coarse_cell_m"]
    size = int(round(geography["width_m"] / cell)) + 1
    grid_x, grid_y = np.meshgrid(
        np.arange(size) * cell, np.arange(size) * cell, indexing="ij"
    )
    flat = np.stack([grid_x.ravel(), grid_y.ravel()], axis=1)
    clearance = geography["minimum_horizontal_clearance_m"]
    blocked = np.zeros((size, size), dtype=bool)
    for ix in range(size):
        for iy in range(size):
            p = [[float(ix * cell), float(iy * cell)]]
            blocked[ix, iy] = not static_feasible(p, geography, clearance)
    start = _grid_cell(origin, cell, size)
    goal = _grid_cell(destination, cell, size)
    blocked[start] = False
    blocked[goal] = False
    penalties = np.zeros((size, size), dtype=float)
    alternatives: List[List[List[float]]] = []
    accepted_cells: List[set] = []
    moves = [
        (-1, -1),
        (-1, 0),
        (-1, 1),
        (0, -1),
        (0, 1),
        (1, -1),
        (1, 0),
        (1, 1),
    ]
    for _ in range(max(count * 4, count)):
        gcost = {start: 0.0}
        parent: Dict[Tuple[int, int], Tuple[int, int]] = {}
        queue = [(0.0, start)]
        while queue:
            _, current = heapq.heappop(queue)
            if current == goal:
                break
            for dx, dy in moves:
                nxt = (current[0] + dx, current[1] + dy)
                if not (0 <= nxt[0] < size and 0 <= nxt[1] < size):
                    continue
                if blocked[nxt]:
                    continue
                step = cell * math.hypot(dx, dy)
                point = np.array([[nxt[0] * cell, nxt[1] * cell]])
                risk = float(composite_risk(point[:, 0], point[:, 1], geography)[0])
                new_cost = (
                    gcost[current]
                    + step * (1.0 + 1.5 * risk + penalties[nxt])
                )
                if new_cost < gcost.get(nxt, float("inf")) - 1e-9:
                    gcost[nxt] = new_cost
                    parent[nxt] = current
                    heuristic = cell * math.hypot(
                        goal[0] - nxt[0], goal[1] - nxt[1]
                    )
                    heapq.heappush(queue, (new_cost + heuristic, nxt))
        if goal != start and goal not in parent:
            break
        cells = [goal]
        while cells[-1] != start:
            cells.append(parent[cells[-1]])
        cells.reverse()
        cell_set = set(cells)
        overlap_ok = all(
            len(cell_set & old) / max(len(cell_set | old), 1) <= 0.82
            for old in accepted_cells
        )
        for item in cells:
            penalties[item] += path_penalty
        if not overlap_ok:
            continue
        simplified = [cells[0]]
        for index in range(1, len(cells) - 1):
            prev = simplified[-1]
            cur = cells[index]
            nxt = cells[index + 1]
            if (cur[0] - prev[0], cur[1] - prev[1]) == (
                nxt[0] - cur[0],
                nxt[1] - cur[1],
            ):
                continue
            simplified.append(cur)
        simplified.append(cells[-1])
        points = [[float(x * cell), float(y * cell)] for x, y in simplified]
        points[0] = [float(origin[0]), float(origin[1])]
        points[-1] = [float(destination[0]), float(destination[1])]
        if static_feasible(points, geography, clearance):
            alternatives.append(points)
            accepted_cells.append(cell_set)
        if len(alternatives) >= count:
            break
    return alternatives


def _make_corridor(
    corridor_id: str,
    origin: str,
    destination: str,
    waypoints: Sequence[Sequence[float]],
    geography: Dict,
    fleet: Dict,
    fixture_role: str | None = None,
) -> Corridor:
    clearance = geography["minimum_horizontal_clearance_m"]
    metrics = directed_corridor_metrics(
        waypoints,
        geography,
        fleet,
        payload_kg=fleet["nominal_payload_kg"],
        condition=CorridorCondition.NORMAL,
    )
    vehicle_feasible = (
        fleet["nominal_payload_kg"] <= fleet["payload_capacity_kg"]
        and metrics["energy_wh"]
        <= fleet["battery_capacity_wh"] - fleet["safety_reserve_wh"]
        and math.isfinite(metrics["travel_time_s"])
    )
    feasible = (
        static_feasible(waypoints, geography, clearance)
        and vehicle_feasible
    )
    samples = sample_polyline(waypoints, spacing_m=geography["fine_cell_m"])
    elevations = terrain_elevation_m(samples[:, 0], samples[:, 1], geography)
    required_altitude = float(elevations.max() + geography["minimum_vertical_clearance_m"])
    increment = geography["altitude_increment_m"]
    cruise_altitude = math.ceil(required_altitude / increment) * increment
    return Corridor(
        corridor_id=corridor_id,
        origin=origin,
        destination=destination,
        waypoints_m=[[round(float(v), 6) for v in point] for point in waypoints],
        nominal_length_m=round(metrics["length_m"], 6),
        accumulated_climb_m=round(metrics["climb_m"], 6),
        accumulated_descent_m=round(metrics["descent_m"], 6),
        cruise_altitude_m=round(cruise_altitude, 6),
        nominal_travel_time_s=round(metrics["travel_time_s"], 6),
        nominal_energy_wh=round(metrics["energy_wh"], 6),
        integrated_geographical_risk=round(metrics["risk"], 8),
        minimum_obstacle_clearance_m=round(
            minimum_static_clearance_m(waypoints, geography), 6
        ),
        static_feasible=bool(feasible),
        generation_seed_stream="corridors",
        fixture_role=fixture_role,
    )


def _build_corridors(config: Dict, geography: Dict) -> List[Corridor]:
    positions = _positions(config)
    fleet_config = dict(config["fleet"])
    fleet_config.update(
        {
            "minimum_ground_speed_m_per_s": config["corridors"][
                "minimum_ground_speed_m_per_s"
            ],
            "nominal_payload_kg": config["corridors"]["nominal_payload_kg"],
        }
    )
    corridors: List[Corridor] = []
    fixed_by_pair: Dict[Tuple[str, str], List[Dict]] = {}
    for fixture in config["audit"]["fixed_corridors"]:
        fixed_by_pair.setdefault(
            tuple(sorted((fixture["origin"], fixture["destination"]))), []
        ).append(fixture)
        forward = _make_corridor(
            fixture["corridor_id"],
            fixture["origin"],
            fixture["destination"],
            fixture["waypoints_m"],
            geography,
            fleet_config,
            fixture["fixture_role"],
        )
        corridors.append(forward)
        reverse_id = fixture["corridor_id"].replace("_outbound", "_reverse")
        if reverse_id == fixture["corridor_id"]:
            reverse_id += "_reverse"
        corridors.append(
            _make_corridor(
                reverse_id,
                fixture["destination"],
                fixture["origin"],
                list(reversed(fixture["waypoints_m"])),
                geography,
                fleet_config,
                fixture["fixture_role"] + "_reverse",
            )
        )
    alternatives_count = int(config["corridors"]["alternatives_per_direction"])
    for left, right in _topology_pairs(config):
        fixtures = fixed_by_pair.get((left, right), [])
        generated_needed = max(1, alternatives_count - len(fixtures))
        alternatives = _astar_alternatives(
            positions[left],
            positions[right],
            geography,
            generated_needed,
            float(config["corridors"]["astar_path_penalty"]),
        )
        if not alternatives:
            raise ValueError(f"No statically feasible corridor for nominal edge {left}-{right}")
        for index, path in enumerate(alternatives, start=1):
            base = f"corridor_{left.lower()}_{right.lower()}_astar_{index}"
            corridors.append(
                _make_corridor(
                    base + "_forward",
                    left,
                    right,
                    path,
                    geography,
                    fleet_config,
                )
            )
            corridors.append(
                _make_corridor(
                    base + "_reverse",
                    right,
                    left,
                    list(reversed(path)),
                    geography,
                    fleet_config,
                )
            )
    corridors.sort(key=lambda item: item.corridor_id)
    return corridors


def _cohorts(config: Dict, active_mask: Sequence[int]):
    true_rows: List[Dict] = []
    operational_rows: List[Dict] = []
    commodity_names = config["commodities"]["canonical_names"]
    for node in config["nodes"]:
        for index, name in enumerate(commodity_names):
            if not active_mask[index]:
                if node["true_demand"][index] != 0 or node["reported_demand"][index] != 0:
                    raise ValueError(
                        f"Inactive commodity {name} is nonzero at {node['node_id']}"
                    )
                continue
            quantity = float(node["true_demand"][index])
            if quantity > 0:
                true_rows.append(
                    {
                        "node_id": node["node_id"],
                        "commodity_index": index,
                        "commodity": name,
                        "cohort_id": f"{node['node_id']}_{name}_initial",
                        "onset_time_s": float(node["onset_s"]),
                        "quantity": quantity,
                    }
                )
            reported = float(node["reported_demand"][index])
            if node["initially_known"] and reported > 0:
                operational_rows.append(
                    {
                        "node_id": node["node_id"],
                        "commodity_index": index,
                        "commodity": name,
                        "cohort_id": f"{node['node_id']}_{name}_reported_initial",
                        "reported_onset_time_s": float(node["onset_s"]),
                        "quantity": reported,
                    }
                )
    return true_rows, operational_rows


def _events() -> List[ExogenousEvent]:
    events = [
        ExogenousEvent(
            "E_N6_P2",
            "P2_NODE_REVEAL",
            2520.0,
            16200.0,
            18000.0,
            "N6",
            None,
            {"reported_demand": [4.0, 0.0, 7.0, 0.0], "reported_vulnerability": 1.3},
            False,
            False,
            "reports",
        ),
        ExogenousEvent(
            "E_N5_ONSET",
            "ORDINARY_DEMAND_ONSET",
            5400.0,
            None,
            None,
            "N5",
            None,
            {"demand": [3.0, 0.0, 14.0, 0.0]},
            False,
            False,
            "demand",
        ),
        ExogenousEvent(
            "E_N5_P1",
            "P1_REPORT",
            6120.0,
            6120.0,
            7560.0,
            "N5",
            None,
            {"reported_demand": [3.0, 0.0, 14.0, 0.0], "reported_vulnerability": 1.0},
            False,
            False,
            "reports",
        ),
        ExogenousEvent(
            "E_N4_LOST_P1",
            "P1_REPORT",
            7920.0,
            7920.0,
            None,
            "N4",
            None,
            {"reported_demand": [5.0, 0.0, 8.0, 0.0]},
            False,
            True,
            "reports",
        ),
        ExogenousEvent(
            "E_N2_DELAYED_P1",
            "P1_REPORT",
            8640.0,
            8640.0,
            11160.0,
            "N2",
            None,
            {"reported_demand": [4.0, 0.0, 12.0, 0.0], "reported_vulnerability": 1.2},
            False,
            False,
            "reports",
        ),
        ExogenousEvent(
            "E_HAZ1_ACTIVATE",
            "HAZARD_ACTIVATE",
            10440.0,
            12240.0,
            17640.0,
            "HAZ1",
            None,
            {"intensity": 1.0},
            False,
            False,
            "hazards",
        ),
        ExogenousEvent(
            "E_TNFZ1_ACTIVATE",
            "TEMP_NFZ_ACTIVATE",
            11520.0,
            12600.0,
            17280.0,
            "TNFZ1",
            None,
            {"active": True},
            False,
            False,
            "nfzs",
        ),
        ExogenousEvent(
            "E_N3_P3",
            "P3_MUTATION",
            12960.0,
            None,
            None,
            "N3",
            "water",
            {"delta": [0.0, 0.0, 10.0, 0.0]},
            False,
            False,
            "p3_mutations",
        ),
        ExogenousEvent(
            "E_CORRIDOR_OBS",
            "CORRIDOR_CONDITION_REPORT",
            13320.0,
            14400.0,
            18720.0,
            "corridor_n1_n5_hazard_outbound",
            None,
            {"condition": "DEGRADED"},
            False,
            False,
            "reports",
        ),
        ExogenousEvent(
            "E_N3_P1",
            "P1_REPORT",
            16560.0,
            16560.0,
            18360.0,
            "N3",
            None,
            {
                "reported_cohorts": [
                    {"commodity_index": 0, "onset_time_s": 0.0, "quantity": 10.0},
                    {"commodity_index": 2, "onset_time_s": 0.0, "quantity": 6.0},
                    {"commodity_index": 2, "onset_time_s": 12960.0, "quantity": 10.0},
                ],
                "reported_vulnerability": 1.5,
                "confidence": 1.0,
            },
            False,
            False,
            "reports",
        ),
        ExogenousEvent(
            "E_REPLENISH",
            "DEPOT_REPLENISHMENT",
            20880.0,
            20880.0,
            20880.0,
            "DEPOT",
            None,
            {"quantity": [10.0, 0.0, 20.0, 0.0]},
            True,
            False,
            "replenishment",
        ),
        ExogenousEvent(
            "E_TNFZ1_EXPIRE",
            "TEMP_NFZ_EXPIRE",
            22320.0,
            22680.0,
            23400.0,
            "TNFZ1",
            None,
            {"active": False},
            False,
            False,
            "nfzs",
        ),
        ExogenousEvent(
            "E_HAZ1_DEACTIVATE",
            "HAZARD_DEACTIVATE",
            25200.0,
            25560.0,
            26280.0,
            "HAZ1",
            None,
            {"intensity": 0.0},
            False,
            False,
            "hazards",
        ),
    ]
    return sorted(events, key=lambda item: (item.physical_occurrence_time_s, item.event_id))


def generate_audit_scenario(
    master_seed: int, config: Dict | None = None, config_path: str | Path | None = None
) -> AuditScenario:
    if config is None:
        if config_path is None:
            raise ValueError("Either config or config_path is required")
        config = load_prototype_config(config_path)
    if int(master_seed) <= 0:
        raise ValueError("master_seed must be a positive integer")
    streams = NamedRandomStreams(master_seed)
    active_mask = _derive_active_mask(config)
    geography = _build_geography(config, streams)
    true_cohorts, operational_cohorts = _cohorts(config, active_mask)
    fleet = dict(config["fleet"])
    fleet["minimum_ground_speed_m_per_s"] = config["corridors"][
        "minimum_ground_speed_m_per_s"
    ]
    fleet["nominal_payload_kg"] = config["corridors"]["nominal_payload_kg"]
    fleet["uavs"] = [
        {"uav_id": f"UAV{index}", "type": "canonical"}
        for index in range(int(config["fleet"]["uav_count"]))
    ]
    corridors = _build_corridors(config, geography)
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "master_seed": int(master_seed),
        "substream_seeds": streams.metadata(),
        "configuration_hash": _config_hash(config),
        "canonical_units": CANONICAL_UNITS,
        "active_commodity_mask": active_mask,
        "commodity_names": list(COMMODITY_NAMES),
    }
    nodes = []
    for node in config["nodes"]:
        nodes.append(
            {
                "node_id": node["node_id"],
                "x_m": float(node["x_m"]),
                "y_m": float(node["y_m"]),
                "true_vulnerability": float(node["true_vulnerability"]),
                "reported_vulnerability": float(node["reported_vulnerability"]),
                "onset_time_s": float(node["onset_s"]),
                "initially_known": bool(node["initially_known"]),
            }
        )
    p4 = [
        P4Potential(
            node_id="N3",
            service_visit_index=1,
            will_generate=True,
            report_delay_s=1152.0,
            report_lost=False,
            confidence=1.0,
            noise_by_commodity=[0.0, 0.0, 0.0, 0.0],
            source_seed_stream="p4_potential_outcomes",
        )
    ]
    return AuditScenario(
        metadata=metadata,
        config=config,
        geography=geography,
        nodes=nodes,
        true_initial_cohorts=true_cohorts,
        operational_initial_cohorts=operational_cohorts,
        corridors=corridors,
        fleet=fleet,
        depot={
            "depot_id": config["depot"]["depot_id"],
            "x_m": float(config["depot"]["x_m"]),
            "y_m": float(config["depot"]["y_m"]),
            "initial_inventory": [
                float(v) for v in config["depot"]["initial_inventory"]
            ],
        },
        exogenous_events=_events(),
        p4_potential_outcomes=p4,
    )
