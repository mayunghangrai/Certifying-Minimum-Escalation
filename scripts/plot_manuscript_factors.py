"""Manuscript figure: FS required level by factor level, with CMI's 10 s certification.

Reads the archived final-study analysis CSVs read-only (`instances.csv`, `arena_fs_10s.csv`).
Bars: shares of the pooled 600 s reference minimum at each level of the six FS factors.
Dots: share of variants CMI certified within 10 s (within-budget rule, as in the report).

    .venv\\Scripts\\python.exe scripts\\plot_manuscript_factors.py RUN_DIR OUT_PDF
"""
import csv
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

FACTORS = (  # (column, group label, [(value, tick label)])
    ('m', 'UAVs', [('4', '4'), ('6', '6'), ('8', '8')]),
    ('k', 'Tasks/UAV', [('2', '2'), ('3', '3'), ('4', '4')]),
    ('sigma', 'Slack', [('tight', 'T'), ('medium', 'M'), ('loose', 'L')]),
    ('beta', 'Battery', [('tight', 'T'), ('medium', 'M'), ('ample', 'A')]),
    ('strength', 'Wind', [('2/5', '2/5'), ('3/5', '3/5'), ('4/5', '4/5')]),
    ('time', 'Update', [('0', '0'), ('1/4', r'$\tau$/4'), ('1/2', r'$\tau$/2')]),
)
# Stack order, bottom to top: ordinal blue ramp for the levels, then no continuation, unresolved.
CLASSES = (
    ('L0', ('0',), dict(color='#86b6ef')),
    ('L1', ('1',), dict(color='#3987e5')),
    ('L2', ('2',), dict(color='#1c5cab')),
    ('L3-4', ('3', '4'), dict(color='#0d366b')),
    ('NC', ('5',), dict(color='#9a9a9a', hatch='////')),
    ('U', ('',), dict(color='#e3e3e3')),
)


def main(run_dir, out_pdf):
    analysis = Path(run_dir)/'analysis'
    rows = [r for r in csv.DictReader(open(analysis/'instances.csv')) if r['group'] == 'fs']
    cmi = {r['instance']: r['within_budget_certified'] == 'True'
           for r in csv.DictReader(open(analysis/'arena_fs_10s.csv')) if r['arm'] == 'CMI'}
    assert len(rows) == 1440 and set(cmi) == {r['instance'] for r in rows}

    plt.rcParams.update({'font.family': 'serif', 'font.serif': ['Times New Roman', 'DejaVu Serif'],
                         'mathtext.fontset': 'stix', 'font.size': 8, 'pdf.fonttype': 42,
                         'hatch.color': '#555555', 'hatch.linewidth': 0.5})
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(3.45, 2.3), sharex=True,
                                  gridspec_kw=dict(height_ratios=(2.2, 1), hspace=0.12))
    x, ticks, labels, groups = 0.0, [], [], []
    for column, group, values in FACTORS:
        start, dots = x, []
        for value, tick in values:
            sub = [r for r in rows if r[column] == value]
            bottom = 0.0
            shares = []
            for name, minima, style in CLASSES:
                share = 100*sum(r['ref_minimum'] in minima for r in sub)/len(sub)
                ax.bar(x, share, bottom=bottom, width=0.8, edgecolor='white', linewidth=0.4,
                       label=name if not ticks else None, **style)
                bottom += share
                shares.append(f'{name} {share:.0f}')
            certified = 100*sum(cmi[r['instance']] for r in sub)/len(sub)
            dots.append((x, certified))
            print(f'{group:9s} {value:6s} n={len(sub):3d} ' + ' '.join(shares) + f' | CMI 10 s {certified:.1f}%')
            ticks.append(x)
            labels.append(tick)
            x += 1
        groups.append(((start + x - 1)/2, group))
        ax2.plot([d[0] for d in dots], [d[1] for d in dots], color='#777777', linewidth=0.7, zorder=2)
        ax2.scatter([d[0] for d in dots], [d[1] for d in dots], s=14, color='black', zorder=3)
        x += 0.7

    ax.set_ylim(0, 100)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_ylabel('(a) Level (%)')
    ax2.set_ylim(65, 100)
    ax2.set_yticks([70, 80, 90, 100])
    ax2.set_ylabel('(b) CMI 10 s (%)')
    ax2.set_xticks(ticks, labels, fontsize=7)
    ax2.set_xlim(-0.6, x - 0.7 - 0.4)
    ax.tick_params(axis='x', length=0)
    ax2.tick_params(axis='x', length=0, pad=1.5)
    for center, group in groups:
        ax2.text(center, -0.3, group, ha='center', va='top', fontsize=7.5,
                 transform=ax2.get_xaxis_transform(), clip_on=False)
    for a in (ax, ax2):
        a.grid(True, axis='y', linewidth=0.3, color='#cccccc')
        a.set_axisbelow(True)
        for side in ('top', 'right'):
            a.spines[side].set_visible(False)
    fig.align_ylabels((ax, ax2))
    handles, names = ax.get_legend_handles_labels()
    fig.legend(handles, names, loc='upper center', ncol=6, frameon=False, fontsize=7,
               handlelength=1.2, handletextpad=0.4, columnspacing=1.0, borderaxespad=0.1)
    fig.subplots_adjust(left=0.13, right=0.99, top=0.91, bottom=0.135)
    fig.savefig(out_pdf)
    print('wrote', out_pdf)


if __name__ == '__main__':
    main(*sys.argv[1:3])
