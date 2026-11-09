"""Manuscript figure: FS anytime curves at 10 s (plan at the reference minimum; certified).

Opens the archived final-study run read-only and reuses the report's own loading,
pooling and curve functions, so the curve endpoints equal the report's primary endpoints.

    .venv\\Scripts\\python.exe scripts\\plot_manuscript_anytime.py RUN_DIR OUT_PDF
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from final_study.store import Store  # noqa: E402
from final_study.analysis import load, pooled, _arm_rows, _attach, _anytime  # noqa: E402

import matplotlib  # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

# Okabe-Ito colours with distinct line styles, legible in greyscale.
STYLE = {
    'CMI':  dict(color='#000000', linestyle='-', linewidth=1.6),
    'PH':   dict(color='#E69F00', linestyle='--', linewidth=1.2),
    'LR':   dict(color='#0072B2', linestyle='-.', linewidth=1.2),
    'GR-c': dict(color='#009E73', linestyle=':', linewidth=1.4),
    'GR':   dict(color='#D55E00', linestyle=(0, (6, 2)), linewidth=1.2),
}


def main(run_dir, out_pdf):
    run = Path(run_dir)
    config = json.loads((run/'manifest.json').read_text())['config']
    store = Store(run, config, bind=False)
    instances, arenas, _ = load(store)
    ref = pooled(instances, arenas)
    budget = config['arena']['budget_short']
    by_arm = {a: _attach(rows, instances, ref) for a, rows in _arm_rows(arenas, 'fs', budget).items()}
    by_arm = {a: by_arm[a] for a in STYLE}

    plt.rcParams.update({'font.family': 'serif', 'font.serif': ['Times New Roman', 'DejaVu Serif'],
                         'mathtext.fontset': 'stix', 'font.size': 8, 'pdf.fonttype': 42})
    fig, axes = plt.subplots(1, 2, figsize=(3.45, 1.7), sharey=True)
    panels = (('at_min', '(a) Minimum level'), ('certified', '(b) Certified'))
    for ax, (key, label) in zip(axes, panels):
        grid, curves = _anytime(by_arm, float(budget), key)
        for arm, style in STYLE.items():
            ax.plot(grid, [100*v for v in curves[arm]], label=arm, **style)
            print(f'{key:9s} {arm:5s} end {100*curves[arm][-1]:.1f}%')
        ax.set_ylim(0, 100)
        ax.set_xlim(0, float(budget))
        ax.set_xticks([0, 2, 4, 6, 8, 10])
        ax.set_xlabel('CPU time (s)')
        ax.text(0.04, 0.97, label, transform=ax.transAxes, va='top')
        ax.grid(True, linewidth=0.3, color='#cccccc')
    axes[0].set_ylabel('Variants (%)')
    axes[1].text(9.8, 20, 'PH, LR, GR-c', ha='right', va='bottom', fontsize=7)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper center', ncol=5, frameon=False, fontsize=7.5,
               handlelength=2.2, columnspacing=0.9, borderaxespad=0.1)
    fig.tight_layout(pad=0.3, w_pad=0.6, rect=(0, 0, 1, 0.88))
    fig.savefig(out_pdf)
    print('wrote', out_pdf)


if __name__ == '__main__':
    main(*sys.argv[1:3])
