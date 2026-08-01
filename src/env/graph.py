"""
Time-varying relief graph G(t) = (V(t), E(t)) (manuscript sec: environment).

  DynamicFields   hazard intensity H(x,t) and wind penalty W(x,t) as sums of
                  Gaussian bumps with piecewise-linear keyframe amplitudes,
                  plus a global wind vector timeline for visualization.
  ReliefGraph     edge attributes e_ij(t) = [L_ij, tau_ij, R_ij, A_ij]
                  (eq:edge_attributes):
                    L_ij  : Euclidean length (obstacle-free benchmark) or the
                            discretized weighted-path functional (eq:feasible_path)
                            via A* over a grid with cost 1 + a_h H + a_w W;
                    tau_ij: L_ij / v_uav;
                    R_ij  : line integral of H along the path;
                    A_ij  : availability from pre-sampled closure intervals.
"""

from __future__ import annotations

import heapq
import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from .params import EnvParams

DEPOT = -1  # node index convention for the depot v0 in edge queries


# ---------------------------------------------------------------------------
def _interp_keyframes(keyframes: List[Tuple[float, float]], t: float) -> float:
    """Piecewise-linear interpolation of (time, value) keyframes, clamped at ends."""
    if not keyframes:
        return 0.0
    if t <= keyframes[0][0]:
        return keyframes[0][1]
    if t >= keyframes[-1][0]:
        return keyframes[-1][1]
    for (t0, v0), (t1, v1) in zip(keyframes[:-1], keyframes[1:]):
        if t0 <= t <= t1:
            if t1 - t0 <= 1e-12:
                return v1
            w = (t - t0) / (t1 - t0)
            return v0 + w * (v1 - v0)
    return keyframes[-1][1]


class DynamicFields:
    """H(x,t) and W(x,t) evaluated from the scenario's bump/keyframe spec."""

    def __init__(self, hazard_bumps: List[dict], wind_spec: dict):
        # each bump: {"center": [x,y], "drift": [vx,vy], "radius": r,
        #             "amp_keyframes": [[t, amp], ...]}
        self.hazard_bumps = hazard_bumps
        # wind_spec: {"base_keyframes": [[t, w], ...],
        #             "dir_keyframes": [[t, theta_rad], ...],
        #             "speed_keyframes": [[t, speed], ...],
        #             "gusts": [bump dicts like hazard]}
        self.wind_spec = wind_spec

    # -- scalar fields ---------------------------------------------------
    @staticmethod
    def _bump_value(bump: dict, x: np.ndarray, t: float) -> np.ndarray:
        amp = _interp_keyframes([tuple(k) for k in bump["amp_keyframes"]], t)
        if amp <= 0.0:
            return np.zeros(x.shape[:-1])
        center = np.asarray(bump["center"], dtype=float)
        drift = np.asarray(bump.get("drift", [0.0, 0.0]), dtype=float)
        c = center + drift * t
        r = float(bump["radius"])
        d2 = np.sum((x - c) ** 2, axis=-1)
        return amp * np.exp(-d2 / (2.0 * r * r))

    def H(self, x: np.ndarray, t: float) -> np.ndarray:
        """Local hazard intensity H(x,t) >= 0 (eq:feasible_path)."""
        x = np.asarray(x, dtype=float)
        total = np.zeros(x.shape[:-1])
        for bump in self.hazard_bumps:
            total = total + self._bump_value(bump, x, t)
        return total

    def W(self, x: np.ndarray, t: float) -> np.ndarray:
        """Wind-related traversal penalty W(x,t) >= 0 (eq:feasible_path)."""
        x = np.asarray(x, dtype=float)
        base = _interp_keyframes([tuple(k) for k in self.wind_spec.get("base_keyframes", [])], t)
        total = np.full(x.shape[:-1], max(base, 0.0))
        for bump in self.wind_spec.get("gusts", []):
            total = total + self._bump_value(bump, x, t)
        return total

    def wind_vector(self, t: float) -> np.ndarray:
        """Global wind vector (for visualization): direction/speed keyframes."""
        theta = _interp_keyframes([tuple(k) for k in self.wind_spec.get("dir_keyframes", [])], t)
        speed = _interp_keyframes([tuple(k) for k in self.wind_spec.get("speed_keyframes", [])], t)
        return np.array([math.cos(theta), math.sin(theta)]) * speed


# ---------------------------------------------------------------------------
class ReliefGraph:
    """
    Edge attribute provider over the physical node set (depot + demand nodes).

    Availability A_ij(t) in {0,1} comes from pre-sampled closure intervals
    (scenario.avail_events applied by the environment); this class stores the
    *current* availability matrix and answers attribute queries.
    """

    def __init__(self, params: EnvParams, depot_pos: np.ndarray,
                 node_positions: np.ndarray, fields: DynamicFields):
        self.p = params
        self.depot_pos = np.asarray(depot_pos, dtype=float)
        self.node_pos = np.asarray(node_positions, dtype=float)  # (N, 2)
        self.fields = fields
        n = len(self.node_pos) + 1  # +1 for depot at slot 0
        self.available = np.ones((n, n), dtype=bool)  # A_ij(t); index 0 = depot
        np.fill_diagonal(self.available, True)
        self._astar_cache: Dict[Tuple[int, int, int], Tuple[float, float]] = {}

    # -- index helpers -----------------------------------------------------
    def _slot(self, i: int) -> int:
        """Map node index (DEPOT=-1 or 0..N-1) to matrix slot (0 = depot)."""
        return 0 if i == DEPOT else i + 1

    def pos_of(self, i: int) -> np.ndarray:
        return self.depot_pos if i == DEPOT else self.node_pos[i]

    # -- availability -------------------------------------------------------
    def set_available(self, i: int, j: int, available: bool) -> None:
        a, b = self._slot(i), self._slot(j)
        self.available[a, b] = available
        self.available[b, a] = available

    def A(self, i: int, j: int) -> bool:
        """A_ij(t) in {0,1} (eq:edge_attributes; constraint C2)."""
        return bool(self.available[self._slot(i), self._slot(j)])

    # -- geometry / fields ---------------------------------------------------
    def euclidean(self, i: int, j: int) -> float:
        return float(np.linalg.norm(self.pos_of(i) - self.pos_of(j)))

    def L(self, i: int, j: int, t: float) -> float:
        """Feasible path length L_ij(t); Euclidean in the obstacle-free benchmark."""
        if self.p.map.path_mode == "field_astar":
            return self._field_path(i, j, t)[0]
        return self.euclidean(i, j)

    def tau(self, i: int, j: int, t: float) -> float:
        """Flight time tau_ij(t) = L_ij(t) / v_uav."""
        return self.L(i, j, t) / self.p.physics.v_uav

    def R(self, i: int, j: int, t: float, n_samples: int = 12) -> float:
        """
        Aggregate route risk R_ij(t): line integral of H along the path,
        approximated by midpoint sampling.
        """
        if self.p.map.path_mode == "field_astar":
            return self._field_path(i, j, t)[1]
        a, b = self.pos_of(i), self.pos_of(j)
        length = float(np.linalg.norm(b - a))
        if length <= 1e-12:
            return 0.0
        fr = (np.arange(n_samples) + 0.5) / n_samples
        pts = a[None, :] + fr[:, None] * (b - a)[None, :]
        return float(np.mean(self.fields.H(pts, t)) * length)

    def edge_attributes(self, i: int, j: int, t: float):
        """e_ij(t) = [L_ij, tau_ij, R_ij, A_ij]   (eq:edge_attributes)."""
        L = self.L(i, j, t)
        return L, L / self.p.physics.v_uav, self.R(i, j, t), self.A(i, j)

    # -- discretized weighted-path functional (eq:feasible_path) -------------
    def _field_path(self, i: int, j: int, t: float) -> Tuple[float, float]:
        """
        P*_ij = argmin_P int_P [1 + a_h H + a_w W] ds, discretized as A* over
        an 8-connected grid; returns (path length, risk integral int_P H ds).
        Cached per (i, j, coarse time index).
        """
        key = (self._slot(i), self._slot(j), int(t * 2))  # 30-min cache buckets
        if key in self._astar_cache:
            return self._astar_cache[key]
        rev = (key[1], key[0], key[2])
        if rev in self._astar_cache:
            return self._astar_cache[rev]

        n = self.p.map.astar_grid
        region = self.p.map.region_km
        xs = np.linspace(0.0, region, n)
        step = xs[1] - xs[0]
        gx, gy = np.meshgrid(xs, xs, indexing="ij")
        grid_pts = np.stack([gx, gy], axis=-1)
        Hf = self.fields.H(grid_pts, t)
        Wf = self.fields.W(grid_pts, t)
        weight = 1.0 + self.p.map.alpha_h * Hf + self.p.map.alpha_w * Wf

        def cell(pos):
            return (int(np.clip(round(pos[0] / step), 0, n - 1)),
                    int(np.clip(round(pos[1] / step), 0, n - 1)))

        start, goal = cell(self.pos_of(i)), cell(self.pos_of(j))
        moves = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
        gcost = {start: 0.0}
        parent = {}
        pq = [(0.0, start)]
        goal_np = np.array(goal)
        while pq:
            f, cur = heapq.heappop(pq)
            if cur == goal:
                break
            for dx, dy in moves:
                nxt = (cur[0] + dx, cur[1] + dy)
                if not (0 <= nxt[0] < n and 0 <= nxt[1] < n):
                    continue
                ds = step * math.sqrt(dx * dx + dy * dy)
                w_mid = 0.5 * (weight[cur] + weight[nxt])
                ng = gcost[cur] + w_mid * ds
                if ng < gcost.get(nxt, float("inf")) - 1e-12:
                    gcost[nxt] = ng
                    parent[nxt] = cur
                    h = step * float(np.linalg.norm(np.array(nxt) - goal_np))
                    heapq.heappush(pq, (ng + h, nxt))
        # reconstruct path; fall back to straight line if unreachable
        if goal not in parent and goal != start:
            L = self.euclidean(i, j)
            result = (L, self.R(i, j, t) if self.p.map.path_mode != "field_astar"
                      else L * float(self.fields.H(0.5 * (self.pos_of(i) + self.pos_of(j)), t)))
            self._astar_cache[key] = result
            return result
        path = [goal]
        while path[-1] != start:
            path.append(parent[path[-1]])
        path.reverse()
        L = 0.0
        risk = 0.0
        for a, b in zip(path[:-1], path[1:]):
            ds = step * math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)
            L += ds
            risk += 0.5 * (Hf[a] + Hf[b]) * ds
        result = (L, risk)
        self._astar_cache[key] = result
        return result
