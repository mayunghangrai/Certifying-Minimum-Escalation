"""Render saved controlled-benchmark evidence at a two-column report width.

Contract: recovery coverage and minimum certificates are different outcomes;
computation is consumed work under equal ceilings. Counts use configuration
labels, including repeated OFAT controls, never timing repeats. No significance
claims. Source: summary.json; vector PDF/SVG and 300-dpi PNG are exported.
"""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def plot(run):
    summary = json.loads((run/'summary.json').read_text(encoding='utf-8'))
    rows = {(r['budget'],r['strategy']):r for r in summary['by_budget_strategy']}
    tiers = ['low','medium','high']
    labels = ['Low\n64 / 4','Medium\n256 / 16','High\n2048 / 128']
    # Standalone subset of the IEEE figure skill's documented matplotlib style.
    plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
        'font.size':8,'axes.linewidth':.8,'axes.spines.top':False,'axes.spines.right':False,
        'legend.frameon':False,'svg.fonttype':'none','pdf.fonttype':42})
    fig,axes = plt.subplots(1,3,figsize=(7.16,2.8))
    x = np.arange(3)
    for index,(metric,title,ylabel) in enumerate([
            ('exact_recoveries','(a) Exact recovery','Configurations'),
            ('minimum_certificates','(b) Minimum certified','Configurations'),
            ('total_nodes','(c) Enumeration used','Nodes across all configurations')]):
        ax = axes[index]
        for j,(strategy,label,color,hatch) in enumerate([
                ('ascending','Ascending scopes','#1f5b96',''),('level4','Direct Level 4','#b56c20','///')]):
            values = [rows[tier,strategy][metric] for tier in tiers]
            bars = ax.bar(x+(j-.5)*.36,values,width=.34,label=label,color=color,hatch=hatch,
                          edgecolor='white',linewidth=.5)
            if index<2:
                ax.bar_label(bars,padding=2,fontsize=7)
        ax.set_title(title,fontsize=9,loc='left')
        ax.set_ylabel(ylabel)
        ax.set_xticks(x,labels,fontsize=7)
        ax.set_axisbelow(True)
        ax.grid(axis='y',alpha=.2)
        ax.set_ylim(bottom=0)
        if index<2:
            ax.set_ylim(0,summary['configuration_count']*1.09)
            ax.set_yticks([0,22,44,66,88])
    fig.legend(*axes[0].get_legend_handles_labels(),loc='upper center',ncol=2,bbox_to_anchor=(.5,1.04))
    fig.supxlabel('Shared ceiling per search: nodes / branches',fontsize=8,y=.02)
    fig.subplots_adjust(left=.07,right=.99,bottom=.25,top=.81,wspace=.5)
    output = run/'figures'
    output.mkdir(exist_ok=True)
    for extension in ('png','svg','pdf'):
        fig.savefig(output/f'comparison.{extension}',dpi=300,bbox_inches='tight')
    (output/'metadata.json').write_text(json.dumps(dict(matplotlib=matplotlib.__version__,
        source_summary_sha256=hashlib.sha256((run/'summary.json').read_bytes()).hexdigest(),
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        intended_width_inches=7.16,minimum_font_points=7,statistical_tests=None),indent=2)+'\n',encoding='utf-8')
    plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    plot(parser.parse_args().run)
