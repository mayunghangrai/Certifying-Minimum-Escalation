"""
create_map.py — seeded dynamic map ("scenario") generation + visualization.

    python scripts/create_map.py --seed 42 [--out results/maps] [--fps 5]
                                 [--frames 120] [--no-gif]

Produces, for the chosen seed:
  scenario_seed{N}.json        the full pre-sampled dynamic scenario — the
                               exact world used by UAMTVRPIUEnv for training
                               and demos (same file, same seed, same map);
  map_seed{N}_overview.png     publication-style static overview at t = 0;
  map_seed{N}_dynamics.gif     animated timeline of the map over the mission
                               horizon: LEFT = latent ground truth (cohort
                               demand, P3 mutation flashes, hazard field,
                               edge closures), RIGHT = command-center belief
                               (known nodes only, risk-adjusted demand
                               d_tilde, P2 popup bursts, report-age fading),
                               with a scrolling event ticker underneath.

The two-panel design shows the belief-truth distinction at the heart of the
manuscript's system model: what the world is versus what the fleet knows.
"""

import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation, PillowWriter
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Rectangle

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from env.params import COMMODITY_NAMES, EnvParams  # noqa: E402
from env.scenario import Scenario  # noqa: E402
from env.scenario_generator import generate_scenario  # noqa: E402

TRUTH_COLOR = "#c0392b"
BELIEF_COLOR = "#2471a3"
HIDDEN_COLOR = "#95a5a6"
DEPOT_COLOR = "#1a1a1a"
HAZARD_CMAP = "YlOrRd"
VULN_CMAP = "viridis"
RADIUS_COLOR = "#7d3c98"
WIND_COLOR = "#2e86c1"
P2_COLOR = "#e67e22"
P3_COLOR = "#8e44ad"

# publication-style typography shared by both figures
PUB_STYLE = {
    "font.family": "serif",
    "mathtext.fontset": "stix",
    "axes.linewidth": 0.8,
    "axes.edgecolor": "#444444",
}

HALO = [pe.withStroke(linewidth=2.2, foreground="white")]


# ---------------------------------------------------------------------------
def _demand_sizes(demands, scale=55.0, floor=15.0):
    return floor + scale * np.sqrt(np.maximum(demands, 0.0))


def _hazard_grid(scn: Scenario, t: float, n: int = 120):
    p = scn.env_params()
    R = p.map.region_km
    xs = np.linspace(0, R, n)
    gx, gy = np.meshgrid(xs, xs)
    pts = np.stack([gx, gy], axis=-1)
    H = scn.fields().H(pts, t)
    return xs, H


def _closed_edges(scn: Scenario, t: float):
    state = scn.availability_at(t)
    return [(i, j) for (i, j), open_ in state.items() if not open_]


def _edge_endpoints(scn: Scenario, i: int, j: int):
    depot = np.array(scn.depot)
    pi = depot if i == -1 else np.array([scn.nodes[i].x, scn.nodes[i].y])
    pj = depot if j == -1 else np.array([scn.nodes[j].x, scn.nodes[j].y])
    return pi, pj


def _event_log(scn: Scenario):
    """Chronological human-readable exogenous event list."""
    events = []
    for n in scn.nodes:
        if n.reveal_time > 0:
            events.append((n.reveal_time,
                           f"P2 popup: node {n.idx} revealed "
                           f"(onset {n.onset_time:.1f} h)"))
    for m in scn.p3_mutations:
        k = int(np.argmax(m.delta_d))
        events.append((m.t, f"P3 mutation: node {m.node} "
                            f"+{m.delta_d[k]:.0f} {COMMODITY_NAMES[k]}"))
    for r in scn.p1_reports:
        events.append((r.t, f"P1 report: node {r.node} reassessed"))
    for a in scn.avail_changes:
        lbl = "reopened" if a.available else "CLOSED"
        i = "depot" if a.i == -1 else f"n{a.i}"
        events.append((a.t, f"route {i}-n{a.j} {lbl}"))
    for rp in scn.replenishments:
        events.append((rp.t, f"depot replenished (+{sum(rp.R):.0f} units)"))
    events.sort(key=lambda e: e[0])
    return events


def _label_offsets(positions: np.ndarray, depot: np.ndarray,
                   sizes: np.ndarray):
    """Per-node label offset (in points) pointing away from crowded space.

    Each node's label is pushed along the repulsion vector from its nearby
    neighbours (inverse-square weighted, depot included), so labels land on
    the open side of a node instead of colliding inside dense clusters.
    """
    pts = np.vstack([positions, depot[None, :]])
    offsets, aligns = [], []
    for i in range(len(positions)):
        d = pts - positions[i]
        d = np.delete(d, i, axis=0)
        dist = np.linalg.norm(d, axis=1)
        near = dist < 1.8
        if near.any():
            w = 1.0 / np.maximum(dist[near], 0.15) ** 2
            v = -(d[near] * w[:, None]).sum(axis=0)
        else:
            v = np.array([0.7, 0.7])
        norm = np.linalg.norm(v)
        v = v / norm if norm > 1e-9 else np.array([0.7, 0.7]) / np.hypot(0.7, 0.7)
        r_pts = 3.0 + 0.55 * np.sqrt(sizes[i])   # clear the marker radius
        offsets.append(v * r_pts)
        ha = "left" if v[0] > 0.35 else ("right" if v[0] < -0.35 else "center")
        va = "bottom" if v[1] > 0.35 else ("top" if v[1] < -0.35 else "center")
        aligns.append((ha, va))
    return offsets, aligns


# ---------------------------------------------------------------------------
def draw_static_overview(scn: Scenario, out_path: str) -> str:
    p = scn.env_params()
    R = p.map.region_km
    nu_lo, nu_hi = p.map.nu_range
    depot = np.array(scn.depot)

    with plt.rc_context(PUB_STYLE):
        fig, ax = plt.subplots(figsize=(9.8, 8.2), dpi=300)
        fig.patch.set_facecolor("white")

        # hazard field at t=0 (filled + faint iso-lines)
        xs, H = _hazard_grid(scn, 0.0)
        im = ax.contourf(xs, xs, H, levels=12, cmap=HAZARD_CMAP, alpha=0.50,
                         zorder=0)
        ax.contour(xs, xs, H, levels=12, colors="#8c6d31", linewidths=0.25,
                   alpha=0.35, zorder=0)

        # stacked colorbars: hazard (top), vulnerability (bottom)
        cax_h = ax.inset_axes([1.025, 0.55, 0.025, 0.45])
        cb_h = fig.colorbar(im, cax=cax_h)
        cb_h.set_label("Hazard intensity $H(x, 0)$", fontsize=8.5)
        cb_h.ax.tick_params(labelsize=7.5)
        sm_nu = plt.cm.ScalarMappable(norm=Normalize(nu_lo, nu_hi),
                                      cmap=VULN_CMAP)
        cax_v = ax.inset_axes([1.025, 0.0, 0.025, 0.45])
        cb_v = fig.colorbar(sm_nu, cax=cax_v)
        cb_v.set_label("Vulnerability $\\nu_i$", fontsize=8.5)
        cb_v.ax.tick_params(labelsize=7.5)

        # feasible service radius, labelled on the open bottom arc
        ax.add_patch(Circle(depot, scn.r_feasible, fill=False, ls="--",
                            lw=1.2, ec=RADIUS_COLOR, zorder=2))
        ax.annotate("energy-feasible service radius "
                    f"$r_{{\\max}}$ = {scn.r_feasible:.2f} km",
                    xy=(depot[0], depot[1] - scn.r_feasible),
                    xytext=(0, -11), textcoords="offset points",
                    ha="center", va="top", fontsize=8, color=RADIUS_COLOR,
                    path_effects=HALO)

        # wind vector (global, at t=0) — lower-left, above the scale bar
        wv = scn.fields().wind_vector(0.0)
        ax.quiver(0.07 * R, 0.20 * R, wv[0], wv[1], scale=6, width=0.004,
                  color=WIND_COLOR, zorder=6)
        ax.text(0.07 * R, 0.235 * R, "wind", fontsize=8, color=WIND_COLOR,
                ha="center", path_effects=HALO)

        # closed edges at t=0 (usually none)
        for (i, j) in _closed_edges(scn, 0.0):
            pi, pj = _edge_endpoints(scn, i, j)
            ax.plot([pi[0], pj[0]], [pi[1], pj[1]], ":", color=TRUTH_COLOR,
                    lw=1.0, alpha=0.8, zorder=1)

        # nodes: size = total initial demand, fill = vulnerability
        known = [n for n in scn.nodes if n.reveal_time <= 0.0]
        hidden = [n for n in scn.nodes if n.reveal_time > 0.0]
        d_known = np.array([sum(n.d0) for n in known])
        d_hidden = np.array([sum(n.d0) for n in hidden])
        ax.scatter([n.x for n in known], [n.y for n in known],
                   s=_demand_sizes(d_known), c=[n.nu for n in known],
                   cmap=VULN_CMAP, vmin=nu_lo, vmax=nu_hi,
                   edgecolors="black", linewidths=0.7, zorder=5)
        ax.scatter([n.x for n in hidden], [n.y for n in hidden],
                   s=_demand_sizes(d_hidden), c=HIDDEN_COLOR, marker="o",
                   edgecolors="black", linewidths=0.7, alpha=0.75,
                   hatch="///", zorder=4)

        # anti-overlap node index labels (pushed toward open space)
        positions = scn.node_positions()
        sizes = _demand_sizes(np.array([sum(n.d0) for n in scn.nodes]))
        offsets, aligns = _label_offsets(positions, depot, sizes)
        for n, off, (ha, va) in zip(scn.nodes, offsets, aligns):
            ax.annotate(str(n.idx), (n.x, n.y), xytext=off,
                        textcoords="offset points", fontsize=6.5,
                        ha=ha, va=va, zorder=8, path_effects=HALO)

        # depot
        ax.scatter(*depot, marker="*", s=520, c="gold", edgecolors="black",
                   linewidths=1.2, zorder=7)
        ax.annotate("$v_0$", depot, xytext=(10, -3),
                    textcoords="offset points", fontsize=10, zorder=8,
                    path_effects=HALO)

        # main legend (inside, upper left)
        cmap_nu = plt.get_cmap(VULN_CMAP)
        handles = [
            Line2D([0], [0], marker="*", color="w", markerfacecolor="gold",
                   markeredgecolor="black", markersize=14, label="Depot $v_0$"),
            Line2D([0], [0], marker="o", color="w",
                   markerfacecolor=cmap_nu(0.6), markeredgecolor="black",
                   markersize=9,
                   label="Demand node (fill = $\\nu_i$, size = demand)"),
            Line2D([0], [0], marker="o", color="w",
                   markerfacecolor=HIDDEN_COLOR, markeredgecolor="black",
                   markersize=9, label="Hidden node (P2 popup)"),
            Line2D([0], [0], ls="--", color=RADIUS_COLOR,
                   label="Feasible service radius"),
            Line2D([0], [0], ls=":", color=TRUTH_COLOR, label="Closed route"),
        ]
        leg = ax.legend(handles=handles, loc="upper left", fontsize=7.5,
                        frameon=True, framealpha=0.9, edgecolor="#666666",
                        borderpad=0.7, labelspacing=0.55)
        leg.set_zorder(10)

        # size legend (lower right): total outstanding demand
        size_handles = [
            Line2D([0], [0], marker="o", color="w", markerfacecolor="none",
                   markeredgecolor="black",
                   markersize=np.sqrt(_demand_sizes(np.array([d]))[0]),
                   label=f"{d} units")
            for d in (5, 15, 30)
        ]
        size_leg = ax.legend(handles=size_handles, loc="lower right",
                             fontsize=7.5, frameon=True, framealpha=0.9,
                             edgecolor="#666666", title="Total demand",
                             title_fontsize=8, borderpad=0.7,
                             labelspacing=1.1)
        size_leg.set_zorder(10)
        ax.add_artist(leg)

        # title + stats footer
        n_p3 = len(scn.p3_mutations)
        n_p1 = len(scn.p1_reports)
        n_cl = sum(1 for a in scn.avail_changes if not a.available)
        stats = (f"seed = {scn.seed}   |   N = {len(scn.nodes)} nodes "
                 f"({len(hidden)} hidden)   |   M = {p.mission.M} UAVs   |   "
                 f"T = {p.mission.T:.0f} h\n"
                 f"timeline: {n_p1} P1 corrections, {len(hidden)} P2 popups, "
                 f"{n_p3} P3 mutations, {n_cl} route closures, "
                 f"{len(scn.replenishments)} replenishments   |   "
                 f"$S^0$(0) = {[int(v) for v in scn.S0_init]}")
        ax.set_title("UA-MTVRP-IU dynamic scenario — "
                     "initial operational picture ($t = 0$)",
                     fontsize=12.5, fontweight="bold", pad=10)
        ax.text(0.5, -0.115, stats, transform=ax.transAxes, ha="center",
                fontsize=8, color="#333333")
        ax.set_xlabel("x [km]")
        ax.set_ylabel("y [km]")
        ax.set_xlim(0, R)
        ax.set_ylim(0, R)
        ax.set_aspect("equal")
        ax.grid(True, ls=":", lw=0.4, alpha=0.4)

        # scale bar + north arrow
        ax.plot([0.05 * R, 0.05 * R + 2.0], [0.04 * R] * 2, "k-", lw=2.5,
                zorder=8)
        ax.text(0.05 * R + 1.0, 0.055 * R, "2 km", ha="center", fontsize=8,
                path_effects=HALO, zorder=8)
        ax.annotate("N", xy=(0.95 * R, 0.90 * R),
                    xytext=(0.95 * R, 0.955 * R),
                    arrowprops=dict(arrowstyle="<-", lw=1.4), fontsize=11,
                    fontweight="bold", ha="center", zorder=8)

        fig.savefig(out_path, dpi=300, bbox_inches="tight", facecolor="white")
        plt.close(fig)
    return out_path


# ---------------------------------------------------------------------------
def draw_dynamics_gif(scn: Scenario, out_path: str, n_frames: int = 120,
                      fps: int = 5) -> str:
    p = scn.env_params()
    R = p.map.region_km
    T = p.mission.T
    depot = np.array(scn.depot)
    times = np.linspace(0.0, T, n_frames)
    events = _event_log(scn)
    w_k, lambda_k, alpha_k, kappa_k = p.commodities.as_arrays()

    # precompute per-frame passive states (no fleet: pure map dynamics)
    truth_states = [scn.passive_truth_at(t) for t in times]
    belief_states = [scn.passive_belief_at(t) for t in times]

    from env.deprivation import true_deprivation_rate
    max_dep = 1.0
    for t, nodes in zip(times, truth_states):
        for nt in nodes:
            max_dep = max(max_dep, true_deprivation_rate(
                nt.nu, nt.cohorts, t, lambda_k, alpha_k, kappa_k))

    # global hazard scale so colors stay comparable across frames
    H_max = 1e-6
    for t in times[:: max(1, n_frames // 16)]:
        _, H = _hazard_grid(scn, t, n=60)
        H_max = max(H_max, float(H.max()))
    levels = np.linspace(0.0, H_max, 11)

    with plt.rc_context(PUB_STYLE):
        fig = plt.figure(figsize=(14.5, 7.8), dpi=110)
        fig.patch.set_facecolor("white")
        gs = fig.add_gridspec(1, 2, left=0.045, right=0.925, top=0.855,
                              bottom=0.225, wspace=0.10)
        ax_t = fig.add_subplot(gs[0])
        ax_b = fig.add_subplot(gs[1])

        # shared hazard colorbar (fixed scale, created once)
        cax = fig.add_axes([0.94, 0.30, 0.012, 0.48])
        sm = plt.cm.ScalarMappable(norm=Normalize(0.0, H_max),
                                   cmap=HAZARD_CMAP)
        cb = fig.colorbar(sm, cax=cax)
        cb.set_label("Hazard $H(x,t)$", fontsize=8)
        cb.ax.tick_params(labelsize=7)

        # static figure-level text (created once, updated per frame)
        fig.suptitle(f"UA-MTVRP-IU dynamic map — seed {scn.seed}",
                     fontsize=13, fontweight="bold", x=0.485, y=0.975)
        clock = fig.text(0.925, 0.955, "", ha="right", fontsize=11,
                         family="monospace", color="#333333")
        pos_t = ax_t.get_position()
        pos_b = ax_b.get_position()
        fig.text(pos_t.x0 + pos_t.width / 2, pos_t.y0 - 0.045,
                 "size = outstanding demand,  fill = deprivation severity,  "
                 "dashed edge = not yet revealed,\n"
                 "purple ring = P3 surge,  dotted red = closed route",
                 ha="center", va="top", fontsize=7.5, color="#555555")
        fig.text(pos_b.x0 + pos_b.width / 2, pos_b.y0 - 0.045,
                 "fill fades to gray as the last report ages ($\\eta$),  "
                 "orange ring = P2 popup burst,\n"
                 "small open circles = not yet in $\\widehat{V}(t)$",
                 ha="center", va="top", fontsize=7.5, color="#555555")
        ticker = fig.text(0.485, 0.055, "", ha="center", fontsize=8.5,
                          family="monospace", color="#333333")

        # progress bar (created once; width updated per frame)
        bar_x0, bar_x1 = pos_t.x0, pos_b.x1
        bar_w = bar_x1 - bar_x0
        fig.text(bar_x0, 0.031, "mission timeline", fontsize=7,
                 color="#555555")
        fig.add_artist(Rectangle((bar_x0, 0.014), bar_w, 0.012,
                                 transform=fig.transFigure, fc="#dddddd",
                                 ec="black", lw=0.4))
        bar_fg = Rectangle((bar_x0, 0.014), 0.0, 0.012,
                           transform=fig.transFigure, fc=WIND_COLOR,
                           ec="none")
        fig.add_artist(bar_fg)

        def draw_frame(fi):
            t = times[fi]
            for ax in (ax_t, ax_b):
                ax.clear()
                ax.set_xlim(0, R)
                ax.set_ylim(0, R)
                ax.set_aspect("equal")
                ax.grid(True, ls=":", lw=0.35, alpha=0.4)
                ax.tick_params(labelsize=7)
            belief = belief_states[fi]
            # ---- LEFT: latent truth ---------------------------------------
            xs, H = _hazard_grid(scn, t, n=90)
            ax_t.contourf(xs, xs, H, levels=levels, cmap=HAZARD_CMAP,
                          alpha=0.45, extend="max", zorder=0)
            for (i, j) in _closed_edges(scn, t):
                pi, pj = _edge_endpoints(scn, i, j)
                ax_t.plot([pi[0], pj[0]], [pi[1], pj[1]], ":",
                          color=TRUTH_COLOR, lw=1.0, alpha=0.85, zorder=1)
            recent_mut = {m.node for m in scn.p3_mutations if 0 <= t - m.t < 0.5}
            for nt in truth_states[fi]:
                if nt.onset_time > t:
                    continue
                d = nt.demand_vector().sum()
                dep = true_deprivation_rate(nt.nu, nt.cohorts, t,
                                            lambda_k, alpha_k, kappa_k)
                color = plt.cm.Reds(0.15 + 0.85 * min(dep / max_dep, 1.0))
                latent = nt.idx not in belief.known
                ax_t.scatter(nt.pos[0], nt.pos[1], s=_demand_sizes(d),
                             c=[color],
                             edgecolors=P2_COLOR if latent else "black",
                             linestyle=(0, (2, 1.2)) if latent else "solid",
                             linewidths=1.2 if latent else 0.6, zorder=5)
                if nt.idx in recent_mut:
                    ax_t.scatter(nt.pos[0], nt.pos[1], s=_demand_sizes(d) + 260,
                                 facecolors="none", edgecolors=P3_COLOR,
                                 linewidths=2.0, zorder=6)
            ax_t.scatter(*depot, marker="*", s=380, c="gold",
                         edgecolors="black", linewidths=1.0, zorder=7)
            wv = scn.fields().wind_vector(t)
            ax_t.quiver(0.08 * R, 0.90 * R, wv[0], wv[1], scale=6,
                        width=0.005, color=WIND_COLOR, zorder=6)
            ax_t.text(0.08 * R, 0.935 * R, "wind", fontsize=7,
                      color=WIND_COLOR, ha="center")
            ax_t.set_title("Latent ground truth  $\\mathbf{d}_i(t)$",
                           fontsize=10.5)
            # ---- RIGHT: command-center belief -----------------------------
            recent_reveal = {n.idx for n in scn.nodes
                             if n.reveal_time > 0 and 0 <= t - n.reveal_time < 0.6}
            for n in scn.nodes:
                pos = (n.x, n.y)
                if n.idx not in belief.known:
                    ax_b.scatter(*pos, s=26, c="white", edgecolors="#bbbbbb",
                                 linewidths=0.8, zorder=3)
                    continue
                e = belief.entries[n.idx]
                d_t = belief.d_tilde(n.idx).sum()
                # report age fades node toward gray (eta grows -> staler)
                eta = min(e.eta(t) / 3.0, 1.0)
                base = np.array([0.14, 0.44, 0.64])
                gray = np.array([0.65, 0.65, 0.65])
                color = (1 - eta) * base + eta * gray
                ax_b.scatter(*pos, s=_demand_sizes(d_t), c=[color],
                             edgecolors="black", linewidths=0.6, zorder=5)
                if n.idx in recent_reveal:
                    ax_b.scatter(*pos, s=_demand_sizes(d_t) + 320,
                                 facecolors="none", edgecolors=P2_COLOR,
                                 linewidths=2.2, zorder=6)
                    ax_b.annotate("P2!", pos, xytext=(6, 8),
                                  textcoords="offset points", fontsize=8,
                                  color=P2_COLOR, fontweight="bold", zorder=7)
            ax_b.scatter(*depot, marker="*", s=380, c="gold",
                         edgecolors="black", linewidths=1.0, zorder=7)
            ax_b.set_title("Command-center belief  "
                           "$\\widetilde{d}_{i}(t)=\\mu+\\rho\\sigma$ over "
                           "$\\widehat{V}(t)$", fontsize=10.5)
            # ---- clock, ticker, progress ----------------------------------
            clock.set_text(f"t = {t:5.2f} / {T:.0f} h")
            recent = [f"t={et:5.2f} h  {msg}" for et, msg in events
                      if 0 <= t - et < 1.2][-3:]
            ticker.set_text("\n".join(recent) if recent else " ")
            bar_fg.set_width(bar_w * (t / T))
            return []

        anim = FuncAnimation(fig, draw_frame, frames=n_frames, blit=False)
        anim.save(out_path, writer=PillowWriter(fps=fps))
        plt.close(fig)
    return out_path


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out", type=str,
                    default=os.path.join(os.path.dirname(__file__), "..",
                                         "results", "maps"))
    ap.add_argument("--frames", type=int, default=120)
    ap.add_argument("--fps", type=int, default=5)
    ap.add_argument("--no-gif", action="store_true")
    ap.add_argument("--config", type=str, default=None,
                    help="optional env-params YAML (defaults to manuscript values)")
    args = ap.parse_args()

    params = EnvParams.from_yaml(args.config) if args.config else EnvParams()
    os.makedirs(args.out, exist_ok=True)

    print(f"[create_map] generating scenario for seed {args.seed} ...")
    scn = generate_scenario(args.seed, params)
    json_path = os.path.join(args.out, f"scenario_seed{args.seed}.json")
    scn.to_json(json_path)
    print(f"[create_map] scenario  -> {json_path}")
    print(f"[create_map]   hash       {scn.content_hash()[:16]}...")
    print(f"[create_map]   nodes      {len(scn.nodes)} "
          f"({sum(1 for n in scn.nodes if n.reveal_time > 0)} hidden)")
    print(f"[create_map]   events     {len(scn.p1_reports)} P1 / "
          f"{sum(1 for n in scn.nodes if n.reveal_time > 0)} P2 / "
          f"{len(scn.p3_mutations)} P3 / "
          f"{len(scn.avail_changes)} availability changes")
    print(f"[create_map]   r_feasible {scn.r_feasible:.2f} km")

    png_path = os.path.join(args.out, f"map_seed{args.seed}_overview.png")
    draw_static_overview(scn, png_path)
    print(f"[create_map] overview  -> {png_path}")

    if not args.no_gif:
        gif_path = os.path.join(args.out, f"map_seed{args.seed}_dynamics.gif")
        print(f"[create_map] rendering {args.frames} frames "
              f"(this takes a minute) ...")
        draw_dynamics_gif(scn, gif_path, n_frames=args.frames, fps=args.fps)
        print(f"[create_map] dynamics  -> {gif_path}")


if __name__ == "__main__":
    main()
