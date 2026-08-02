"""
Seeded, feasibility-aware scenario ("map") generation.

``generate_scenario(seed, params)`` pre-samples the entire exogenous world:

  geography      depot at region center; demand nodes in disaster clusters,
                 every node within feasible_frac * r_max of the depot, where
                 r_max is the conservative single-stop service radius derived
                 from the manuscript physics (energy.max_service_radius) —
                 guaranteeing C5-serviceability at full payload;
  demand         initial cohorts (Poisson units per commodity), vulnerability;
  information    initial imperfect assessments for known nodes, P2 reveal
                 times + report content for hidden nodes, P1 correction
                 schedules (pre-sampled noise), P3 compound-Poisson/Gamma
                 mutation schedules;
  environment    hazard bumps (decaying, drifting), wind keyframes/gusts,
                 edge closure/reopen intervals correlated with hazard;
  logistics      finite depot stock S0_k(0) and replenishment events.

Only P4 is policy-dependent; its RNG stream seed (seed + 1000) is stored in
the scenario so that a fixed policy replays bit-identically.
"""

from __future__ import annotations

import math
from typing import List

import numpy as np

from .energy import max_service_radius
from .params import N_COMMODITIES, EnvParams
from .scenario import (AvailabilityChange, P1Report, P3Mutation, Replenishment,
                       Scenario, ScenarioNode)


# ---------------------------------------------------------------------------
def _place_nodes(rng: np.random.Generator, p: EnvParams,
                 depot: np.ndarray, r_place: float):
    """Clustered placement within the feasible service disk around the depot.

    Cluster centers are angularly spread with an enforced pairwise separation
    (rejection-sampled) so clusters read as distinct disaster pockets; node
    counts are balanced (each cluster gets a guaranteed minimum before the
    Dirichlet-weighted remainder); nodes keep min_node_sep_km from each other
    and from the depot so markers never overlap in the map figures.
    """
    mp = p.map
    n_c = mp.n_clusters

    # cluster centers: even angular spread + jitter, rejection-sampled so no
    # two centers merge visually
    base = rng.uniform(0.0, 2.0 * math.pi)
    centers = None
    for _ in range(300):
        angles = base + np.arange(n_c) * (2.0 * math.pi / n_c) \
            + rng.uniform(-0.35, 0.35, n_c)
        radii = rng.uniform(0.35 * r_place, 0.80 * r_place, n_c)
        cand = depot + np.stack([radii * np.cos(angles),
                                 radii * np.sin(angles)], axis=1)
        if n_c == 1:
            centers = cand
            break
        pair_d = np.linalg.norm(cand[:, None] - cand[None, :], axis=-1)
        if pair_d[np.triu_indices(n_c, 1)].min() >= 0.70 * r_place:
            centers = cand
            break
    if centers is None:  # deterministic fallback: even ring at 60% radius
        angles = base + np.arange(n_c) * (2.0 * math.pi / n_c)
        centers = depot + 0.60 * r_place * np.stack(
            [np.cos(angles), np.sin(angles)], axis=1)

    # balanced assignment: guaranteed minimum per cluster, remainder weighted
    n_min = mp.n_nodes // (2 * n_c)
    assignments = np.repeat(np.arange(n_c), n_min)
    weights = rng.dirichlet(np.full(n_c, 3.0))
    extra = rng.choice(n_c, size=mp.n_nodes - len(assignments), p=weights)
    assignments = np.concatenate([assignments, extra])
    rng.shuffle(assignments)

    positions: List[np.ndarray] = []
    sep = mp.min_node_sep_km
    for ci in assignments:
        for _ in range(300):
            pos = centers[ci] + rng.normal(0.0, mp.cluster_std_km, 2)
            r_depot = np.linalg.norm(pos - depot)
            if r_depot > r_place or r_depot < sep:  # inside disk, off the depot
                continue
            if positions and min(np.linalg.norm(pos - q) for q in positions) < sep:
                continue
            positions.append(pos)
            break
        else:  # fall back: uniform in disk
            theta = rng.uniform(0.0, 2.0 * math.pi)
            r = r_place * math.sqrt(rng.uniform(0.05, 1.0))
            positions.append(depot + np.array([r * math.cos(theta), r * math.sin(theta)]))
    return np.array(positions), assignments


# ---------------------------------------------------------------------------
def _hazard_and_wind(rng: np.random.Generator, p: EnvParams,
                     centers: np.ndarray, T: float):
    """Hazard bumps near demand clusters (decaying, one possible secondary
    hazard mid-horizon) and a smoothly rotating wind field with gusts."""
    mp = p.map
    n_bumps = int(rng.integers(mp.n_hazard_bumps[0], mp.n_hazard_bumps[1] + 1))
    bumps = []
    for b in range(n_bumps):
        anchor = centers[int(rng.integers(len(centers)))]
        center = anchor + rng.normal(0.0, 1.0, 2)
        amp = rng.uniform(*mp.hazard_amp_range)
        radius = rng.uniform(*mp.hazard_radius_range)
        if b == n_bumps - 1 and rng.random() < 0.5:
            # secondary hazard igniting mid-horizon (pairs with P3 activity)
            t_on = rng.uniform(0.25 * T, 0.6 * T)
            amp_kf = [[0.0, 0.0], [t_on, 0.0], [t_on + 0.5, amp],
                      [min(t_on + 0.5 * T, T), 0.3 * amp], [T, 0.15 * amp]]
        else:
            # primary hazard decaying from mission start (aftershock-like)
            amp_kf = [[0.0, amp], [0.4 * T, 0.45 * amp], [T, 0.15 * amp]]
        bumps.append({
            "center": [float(center[0]), float(center[1])],
            "drift": [float(v) for v in rng.normal(0.0, 0.08, 2)],
            "radius": float(radius),
            "amp_keyframes": [[float(a), float(v)] for a, v in amp_kf],
        })

    theta0 = rng.uniform(0.0, 2.0 * math.pi)
    dtheta = rng.uniform(-1.5, 1.5)
    n_kf = 5
    times = np.linspace(0.0, T, n_kf)
    wind_spec = {
        "base_keyframes": [[float(t), float(max(0.0, rng.uniform(0.05, 0.3)))]
                           for t in times],
        "dir_keyframes": [[float(t), float(theta0 + dtheta * t / T)] for t in times],
        "speed_keyframes": [[float(t), float(rng.uniform(0.2, 0.8))] for t in times],
        "gusts": [],
    }
    if rng.random() < 0.6:
        gust_c = centers[int(rng.integers(len(centers)))] + rng.normal(0.0, 1.5, 2)
        t_g = rng.uniform(0.2 * T, 0.8 * T)
        wind_spec["gusts"].append({
            "center": [float(gust_c[0]), float(gust_c[1])],
            "drift": [0.0, 0.0],
            "radius": float(rng.uniform(2.0, 4.0)),
            "amp_keyframes": [[0.0, 0.0], [float(t_g - 0.5), 0.0],
                              [float(t_g), float(rng.uniform(0.4, 1.0))],
                              [float(min(t_g + 2.0, T)), 0.0], [float(T), 0.0]],
        })
    return bumps, wind_spec


# ---------------------------------------------------------------------------
def generate_scenario(seed: int, params: EnvParams = None) -> Scenario:
    p = params or EnvParams()
    rng = np.random.default_rng(seed)
    T = p.mission.T
    mp = p.map

    depot = np.array([mp.region_km / 2.0, mp.region_km / 2.0])
    r_max = max_service_radius(p.physics, conservative=True)
    r_place = mp.feasible_frac * r_max
    positions, cluster_of = _place_nodes(rng, p, depot, r_place)

    # feasibility assertion: every node C5-serviceable at full payload
    dists = np.linalg.norm(positions - depot, axis=1)
    assert np.all(dists <= r_max + 1e-9), "feasibility-aware placement violated"

    # -- hidden (P2) node selection: prefer nodes deeper in clusters --------
    centroids = np.array([positions[cluster_of == c].mean(axis=0)
                          if np.any(cluster_of == c) else depot
                          for c in range(mp.n_clusters)])
    depth = np.linalg.norm(positions - centroids[cluster_of], axis=1)
    w_hidden = np.exp(-depth)                    # deeper in cluster -> likelier
    w_hidden /= w_hidden.sum()
    hidden = set(rng.choice(mp.n_nodes, size=mp.n_hidden, replace=False,
                            p=w_hidden).tolist())

    # -- per-node demand, vulnerability, reveal/onset, initial assessment ---
    demand_mean = np.asarray(mp.demand_mean_k, dtype=float)
    nodes: List[ScenarioNode] = []
    for i in range(mp.n_nodes):
        severity = rng.uniform(0.6, 1.6)
        d0 = rng.poisson(demand_mean * severity).astype(float)
        if d0.sum() == 0:                       # every node needs something
            d0[int(rng.integers(N_COMMODITIES))] = 1.0
        nu = float(rng.uniform(*mp.nu_range))
        if i in hidden:
            reveal = float(rng.uniform(p.events.p2_reveal_window[0] * T,
                                       p.events.p2_reveal_window[1] * T))
            onset = float(rng.uniform(0.0, reveal))
        else:
            reveal = 0.0
            onset = 0.0
        # initial assessment (imperfect): mu0 = d0 + noise, sigma0 proportional
        noise = rng.normal(0.0, p.belief.init_report_noise_frac
                           * np.maximum(d0, 1.0))
        mu0 = np.maximum(d0 + noise, 0.0)
        sigma0 = p.belief.sigma0_frac * np.maximum(mu0, 1.0)
        gamma0 = float(rng.uniform(*p.belief.gamma0_range))
        nodes.append(ScenarioNode(
            idx=i, x=float(positions[i][0]), y=float(positions[i][1]), nu=nu,
            onset_time=onset, reveal_time=reveal,
            d0=[float(v) for v in d0], mu0=[float(v) for v in mu0],
            sigma0=[float(v) for v in sigma0], gamma0=gamma0,
            nu_reported=float(np.clip(0.92 * nu + 0.08, 0.5, 3.0))))

    # -- P1 correction schedule (per known-at-some-point node) --------------
    p1_reports: List[P1Report] = []
    for n in nodes:
        t_cur = max(n.reveal_time, 0.0)
        while True:
            t_cur += rng.exponential(1.0 / max(p.events.p1_rate, 1e-9))
            if t_cur >= T:
                break
            eps = rng.normal(0.0, p.belief.sigma_obs, N_COMMODITIES)
            p1_reports.append(P1Report(
                t=float(t_cur), node=n.idx,
                eps=[float(v) for v in eps],
                gamma=float(rng.uniform(*p.belief.gamma0_range))))
    p1_reports.sort(key=lambda r: r.t)

    # -- P3 latent mutations: compound Poisson with Gamma marks --------------
    # hazard bumps anchor to the actual cluster centroids so the field
    # overlaps the demand pockets it is supposed to threaten
    hazard_bumps, wind_spec = _hazard_and_wind(rng, p, centroids, T)
    from .graph import DynamicFields
    fields = DynamicFields(hazard_bumps, wind_spec)
    p3_mutations: List[P3Mutation] = []
    for n in nodes:
        exposure = 1.0 + 2.0 * float(fields.H(np.array([n.x, n.y]), 0.0))
        rate = p.events.p3_rate * exposure
        t_cur = n.onset_time
        while True:
            t_cur += rng.exponential(1.0 / max(rate, 1e-9))
            if t_cur >= T:
                break
            delta = np.zeros(N_COMMODITIES)
            k = int(rng.choice(N_COMMODITIES,
                               p=np.array([0.3, 0.25, 0.3, 0.15])))
            delta[k] = float(np.round(rng.gamma(p.events.p3_gamma_shape,
                                                p.events.p3_gamma_scale)))
            if delta.sum() <= 0:
                continue
            p3_mutations.append(P3Mutation(
                t=float(t_cur), node=n.idx, delta_d=[float(v) for v in delta]))
    p3_mutations.sort(key=lambda m: m.t)

    # -- availability closures correlated with hazard exposure ---------------
    avail_changes: List[AvailabilityChange] = []
    pairs = [(-1, j) for j in range(mp.n_nodes)]
    pairs += [(i, j) for i in range(mp.n_nodes) for j in range(i + 1, mp.n_nodes)]
    for (i, j) in pairs:
        pi = depot if i == -1 else positions[i]
        pj = positions[j]
        mid = 0.5 * (pi + pj)
        exposure = float(fields.H(mid, 0.0))
        if exposure < p.events.avail_hazard_threshold:
            continue
        lam = p.events.avail_closure_rate * exposure
        t_cur = 0.0
        while True:
            t_cur += rng.exponential(1.0 / max(lam, 1e-9))
            if t_cur >= T:
                break
            dur = rng.uniform(*p.events.avail_closure_dur)
            avail_changes.append(AvailabilityChange(t=float(t_cur), i=i, j=j,
                                                    available=False))
            t_open = t_cur + dur
            if t_open < T:
                avail_changes.append(AvailabilityChange(t=float(t_open), i=i, j=j,
                                                        available=True))
            t_cur = t_open
    avail_changes.sort(key=lambda a: a.t)

    # -- depot inventory and replenishment -----------------------------------
    # Stock is sized from *initially known* demand only: hidden (P2) nodes
    # are latent at t=0, so including their demand would leak oracle
    # information into the depot inventory.
    known_demand = np.zeros(N_COMMODITIES)
    for n in nodes:
        if n.idx in hidden:
            continue
        known_demand += np.array(n.d0)
    S0 = np.ceil(p.mission.stock_mult * known_demand)
    replenishments: List[Replenishment] = []
    for _ in range(p.mission.n_replenish):
        t_r = float(rng.uniform(0.25 * T, 0.9 * T))
        R = np.ceil(p.mission.replenish_frac * S0 * rng.uniform(0.5, 1.0, N_COMMODITIES))
        replenishments.append(Replenishment(t=t_r, R=[float(v) for v in R]))
    replenishments.sort(key=lambda r: r.t)

    return Scenario(
        seed=int(seed),
        params=p.to_dict(),
        depot=[float(depot[0]), float(depot[1])],
        nodes=nodes,
        p1_reports=p1_reports,
        p3_mutations=p3_mutations,
        avail_changes=avail_changes,
        replenishments=replenishments,
        hazard_bumps=hazard_bumps,
        wind_spec=wind_spec,
        S0_init=[float(v) for v in S0],
        p4_seed=int(seed) + 1000,
        r_feasible=float(r_max),
    )
