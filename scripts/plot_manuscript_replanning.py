"""Manuscript figures: the environment and the plan change at each certified level.

Opens the archived final-study run read-only and draws level-suite (LS) instances as stored:
the incumbent plan, the local wind update, and the label's certified minimum-level plan.

- ``environment``: one instance before the update (cells, depot, tasks by urgency, routes).
- ``replanning_depot``: Levels 1-4, update received with every UAV at the depot (t = 0).
- ``replanning_airborne``: Levels 1-4, update received in flight (t = tau/4 or tau/2).

    .venv\\Scripts\\python.exe scripts\\plot_manuscript_replanning.py RUN_DIR OUT_DIR
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from env.plan import active_count  # noqa: E402
from final_study.store import Store  # noqa: E402

import matplotlib  # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch, Rectangle  # noqa: E402

# 4-UAV instances, uniform layout where available, each showing one mechanism clearly.
ENVIRONMENT = 'LS_L1_m4_0072'
DEPOT = ['LS_L1_m4_0072', 'LS_L2_m4_0078', 'LS_inf_m4_0027', 'LS_L4_m4_0159']
AIRBORNE = ['LS_L3_m4_0008', 'LS_L2_m4_0056', 'LS_L3_m4_0020', 'LS_L4_m4_0067']
LEVELS = {1: 'path repair', 2: 'sequence/transfer repair', 3: 'local reassignment', 4: 'global reassignment'}

# Okabe-Ito colours, one per UAV.
UAV_COLOR = {'U1': '#0072B2', 'U2': '#D55E00', 'U3': '#009E73', 'U4': '#CC79A7'}
GREY = '#b0b0b0'
WIND_FILL = '#56B4E9'
URGENCY = {1: ('urgent', 'black'), 10: ('normal', '#8c8c8c'), 50: ('routine', 'white')}
WIND_SCALE = .45            # km of arrow per km/h of wind


def load(store, name):
    draw = store.load('ls', 'draws', name)
    result = store.load('ls', 'labels', name)['result']
    if result['plan'] is None or result['plan_level'] != result['bounds']['minimum']:
        raise ValueError(name+': label plan is not at the certified minimum')
    return draw['ledger'], draw['payload'], result['plan']['witness']['plan'], result


def legs(route):
    n = active_count(route)
    return route['stops'][:n], route['paths'][:n]


def changed(old, new):
    keys = ('stops', 'paths', 'deliveries', 'loads')
    return sorted(u for u in old['routes'] if any(old['routes'][u][k] != new['routes'][u][k] for k in keys))


def sequence(route, airborne):
    stops = ['D' if s == 'DEPOT' else s for s in legs(route)[0]]
    return '→'.join((['▲'] if airborne else ['D'])+stops)


def draw_base(ax, payload, axis_labels):
    for cell in payload['wind']['cells']:
        xs, ys = zip(*cell['polygon_xy'])
        ax.add_patch(Rectangle((min(xs), min(ys)), max(xs)-min(xs), max(ys)-min(ys), fill=False,
                               edgecolor='#d9d9d9', linewidth=.4, zorder=0))
    index = {c['id']: i for i, c in enumerate(payload['wind']['cells'])}
    speeds = []
    for cell_id, b in payload['wind']['update_support']:
        cell = payload['wind']['cells'][index[cell_id]]
        xs, ys = zip(*cell['polygon_xy'])
        ax.add_patch(Rectangle((min(xs), min(ys)), max(xs)-min(xs), max(ys)-min(ys), facecolor=WIND_FILL,
                               alpha=.22, edgecolor='none', zorder=0))
        wx, wy = payload['wind']['received']['values'][index[cell_id]][b]
        cx, cy = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2
        dx, dy = WIND_SCALE*wx, WIND_SCALE*wy
        ax.annotate('', xy=(cx+dx/2, cy+dy/2), xytext=(cx-dx/2, cy-dy/2), zorder=1,
                    arrowprops=dict(arrowstyle='-|>,head_length=.35,head_width=.18', color='#1f4e79', linewidth=1.1))
        speeds.append((wx*wx+wy*wy)**.5)
    x0, y0 = payload['mission']['depot_xy']
    ax.plot(x0, y0, marker='s', markersize=4.5, color='black', zorder=6, linestyle='none')
    ax.set_xlim(-1.06, 1.06)
    ax.set_ylim(-1.06, 1.06)
    ax.set_aspect('equal')
    ax.set_xticks([-1, 0, 1])
    ax.set_yticks([-1, 0, 1])
    ax.tick_params(length=2, pad=1.5)
    if axis_labels:
        ax.set_xlabel('$x$ (km)', labelpad=1)
        ax.set_ylabel('$y$ (km)', labelpad=0)
    return max(speeds)


def draw_route(ax, route, **style):
    for path in legs(route)[1]:
        xs, ys = zip(*path)
        ax.plot(xs, ys, solid_capstyle='round', **style)


def draw_arrows(ax, route, color):
    """A small arrowhead at the middle of every leg, in the direction of flight."""
    for path in legs(route)[1]:
        (ax0, ay0), (bx, by) = path[0], path[-1]
        if abs(bx-ax0)+abs(by-ay0) < 1e-6:
            continue
        lengths = [((q[0]-p[0])**2+(q[1]-p[1])**2)**.5 for p, q in zip(path, path[1:])]
        half, run = sum(lengths)/2, 0.
        for (p, q), length in zip(zip(path, path[1:]), lengths):
            if run+length >= half and length > 0:
                f = (half-run)/length
                mx, my = p[0]+f*(q[0]-p[0]), p[1]+f*(q[1]-p[1])
                ux, uy = (q[0]-p[0])/length, (q[1]-p[1])/length
                ax.annotate('', xy=(mx+.03*ux, my+.03*uy), xytext=(mx-.03*ux, my-.03*uy), zorder=5,
                            arrowprops=dict(arrowstyle='-|>,head_length=.45,head_width=.22', color=color,
                                            linewidth=0))
                break
            run += length


def label_task(ax, task, xy, size):
    """Upper right of the task; upper left near the right edge of the region, so it stays inside."""
    right = xy[0] > .8
    ax.annotate(task, xy, xytext=(-2.5 if right else 2.5, 2.5), textcoords='offset points', fontsize=size,
                ha='right' if right else 'left', zorder=7)


def task_positions(payload):
    return {t['id']: t['position_xy'] for t in payload['mission']['tasks']}


def delivered(payload):
    state = payload['state']['cumulative_delivered']
    return {t['id'] for t in payload['mission']['tasks'] if state[t['id']] >= t['demand']}


def environment(store, out):
    ledger, payload, _, _ = load(store, ENVIRONMENT)
    fig, ax = plt.subplots(figsize=(3.45, 3.6))
    speed = draw_base(ax, payload, True)
    routes = payload['incumbent']['routes']
    for uid, route in sorted(routes.items()):
        draw_route(ax, route, color=UAV_COLOR[uid], linewidth=1.1, zorder=3)
        draw_arrows(ax, route, UAV_COLOR[uid])
    position = task_positions(payload)
    for task, xy in position.items():
        _, colour = URGENCY[ledger['classes'][task]]
        ax.plot(*xy, marker='o', markersize=4.2, markerfacecolor=colour, markeredgecolor='black',
                markeredgewidth=.6, zorder=6, linestyle='none')
        label_task(ax, task, xy, 6)
    handles = [Line2D([], [], color=UAV_COLOR[u], linewidth=1.1, label=f'{u}: {sequence(routes[u], False)}')
               for u in sorted(routes)]
    handles += [Line2D([], [], marker='s', color='black', linestyle='none', markersize=4.5, label='depot')]
    handles += [Line2D([], [], marker='o', markerfacecolor=c, markeredgecolor='black', markeredgewidth=.6,
                       linestyle='none', markersize=4.2, label=f'{name} task ($c_i$={k})')
                for k, (name, c) in URGENCY.items()]
    handles += [Patch(facecolor=WIND_FILL, alpha=.35, label=f'updated cell ($\\|w\\|$ = {speed:.2f} km/h)')]
    ax.legend(handles=handles, loc='upper center', bbox_to_anchor=(.5, -.13), ncol=2, frameon=False, fontsize=6.5,
              handlelength=1.6, columnspacing=1, borderaxespad=0)
    fig.tight_layout(pad=.3)
    fig.savefig(out/'environment.pdf', bbox_inches='tight', pad_inches=.03)
    fig.savefig(out/'environment.png', dpi=300, bbox_inches='tight', pad_inches=.03)
    plt.close(fig)
    print('environment', ENVIRONMENT, 'm', ledger['fleet'], 'tasks', len(position), 'cell', ledger['cell'])


def replanning(store, names, airborne, out, stem):
    """Top row: the incumbent at the update. Bottom row: the certified plan. Only changed UAVs are drawn."""
    fig, axes = plt.subplots(2, 4, figsize=(7.16, 4.3), sharex=True, sharey=True)
    shown = set()
    for j, name in enumerate(names):
        ledger, payload, plan, result = load(store, name)
        level = result['plan_level']
        if level != j+1 or (ledger['time'] != '0') == (not airborne):
            raise ValueError(name+': level or update time does not match its panel')
        old = payload['incumbent']
        moved = changed(old, plan)
        shown.update(moved)
        done, position = delivered(payload), task_positions(payload)
        involved = {t for u in moved for r in (old, plan) for t in legs(r['routes'][u])[0] if t in position}
        reassigned = sorted((t for t in old['assignment'] if plan['assignment'][t] != old['assignment'][t]),
                            key=lambda t: int(t[1:]))
        for ax, routes in zip(axes[:, j], (old, plan)):
            draw_base(ax, payload, False)
            for uid in moved:
                draw_route(ax, routes['routes'][uid], color=UAV_COLOR[uid], linewidth=1.3, zorder=4)
                draw_arrows(ax, routes['routes'][uid], UAV_COLOR[uid])
            for task, xy in position.items():
                if task in done:
                    continue
                if task not in involved:
                    ax.plot(*xy, marker='o', markersize=2.8, color=GREY, zorder=5, linestyle='none')
                    continue
                ax.plot(*xy, marker='o', markersize=3.6, color='black', zorder=6, linestyle='none')
                if task in reassigned:
                    ax.plot(*xy, marker='o', markersize=8.5, markerfacecolor='none', markeredgecolor='black',
                            markeredgewidth=.8, zorder=6, linestyle='none')
                label_task(ax, task, xy, 6)
            if airborne:
                for uid in moved:
                    f = payload['state']['fleet'][uid]
                    if f['mode'] == 'airborne':
                        ax.plot(*f['position_xy'], marker='^', markersize=5, color=UAV_COLOR[uid],
                                markeredgecolor='black', markeredgewidth=.5, zorder=7, linestyle='none')
            ax.set_xlabel('$x$ (km)', labelpad=1)
        when = '$t = 0$' if not airborne else f"$t = \\tau/{ledger['time'][2:]}$"
        axes[0, j].set_title(f'({"abcd"[j]}) Level {level}: {LEVELS[level]}\n'
                             f'$U_0$ = {{{", ".join(result["affected"])}}},  {when}', fontsize=7.5, pad=3)
        print(stem, name, 'level', level, 't', ledger['time'], 'U0', result['affected'], 'changed', moved,
              'reassigned', reassigned)
    axes[0, 0].set_ylabel('incumbent\n$y$ (km)', labelpad=0)
    axes[1, 0].set_ylabel('certified plan\n$y$ (km)', labelpad=0)
    for ax in axes.flat:
        ax.label_outer()
    handles = [Line2D([], [], color=UAV_COLOR[u], linewidth=1.3, label=u) for u in sorted(shown)]
    handles += [Patch(facecolor=WIND_FILL, alpha=.35, label='updated wind cell'),
                Line2D([], [], marker='s', color='black', linestyle='none', markersize=4.5, label='depot'),
                Line2D([], [], marker='o', color='black', linestyle='none', markersize=3.6, label='task on a changed route'),
                Line2D([], [], marker='o', markerfacecolor='none', markeredgecolor='black', linestyle='none',
                       markersize=7, label='reassigned task'),
                Line2D([], [], marker='o', color=GREY, linestyle='none', markersize=2.8, label='other pending task')]
    if airborne:
        handles += [Line2D([], [], marker='^', color=GREY, markeredgecolor='black', markeredgewidth=.5,
                           linestyle='none', markersize=5, label='UAV position')]
    fig.legend(handles=handles, loc='upper center', ncol=len(handles), frameon=False, fontsize=6,
               handlelength=1.6, columnspacing=.9, handletextpad=.4, borderaxespad=.1)
    fig.subplots_adjust(left=.075, right=.995, top=.895, bottom=.075, wspace=.08, hspace=.06)
    fig.savefig(out/f'{stem}.pdf')
    fig.savefig(out/f'{stem}.png', dpi=300)
    plt.close(fig)


def main(run_dir, out_dir):
    run = Path(run_dir)
    config = json.loads((run/'manifest.json').read_text())['config']
    store = Store(run, config, bind=False)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({'font.family': 'serif', 'font.serif': ['Times New Roman', 'DejaVu Serif'],
                         'mathtext.fontset': 'stix', 'font.size': 7, 'pdf.fonttype': 42,
                         'axes.linewidth': .5, 'xtick.major.width': .5, 'ytick.major.width': .5,
                         'xtick.labelsize': 6, 'ytick.labelsize': 6})
    environment(store, out)
    replanning(store, DEPOT, False, out, 'replanning_depot')
    replanning(store, AIRBORNE, True, out, 'replanning_airborne')
    print('wrote', out)


if __name__ == '__main__':
    main(*sys.argv[1:3])
