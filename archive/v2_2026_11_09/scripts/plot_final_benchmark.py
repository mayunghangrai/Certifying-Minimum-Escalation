"""Rebuild static manuscript figures and tables from audited case records."""
import argparse
from collections import Counter,defaultdict
import csv
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from final_benchmark.analysis import load_records,summarize,LEVELS,recoverability_membership

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
    'font.size':8,'axes.titlesize':8.5,'legend.fontsize':8,'svg.fonttype':'none','pdf.fonttype':42,
    'axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':.8,'savefig.dpi':300})
COLORS={0:'#245B86',1:'#238B76',2:'#C28016',3:'#805394',4:'#BF493A','infinity':'#252525',None:'#777777'}
MARKERS={0:'o',1:'s',2:'^',3:'D',4:'v','infinity':'P',None:'x'}


def label(k): return '?' if k is None else '∞' if k=='infinity' else str(k)


def save(fig,stem):
    stem.parent.mkdir(parents=True,exist_ok=True)
    for ext in ('svg','pdf','png'): fig.savefig(stem.with_suffix('.'+ext),bbox_inches='tight')
    plt.close(fig)


def csv_write(path,rows):
    if not rows: return
    with path.open('w',newline='',encoding='utf-8') as stream:
        w=csv.DictWriter(stream,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def observed_rows(records):
    rows=[]
    for r in records:
        a=r['result'];meta=r['request']['metadata'];m=len(r['scenario']['mission']['vehicles'])
        w=a['witness'];k=w['validation']['level'] if w else None
        changed=a['change']['changed_uav_count'] if w else None
        held=a['preservation']['held_fixed_count'] if w else None
        rows.append(dict(case_id=r['case_id'],base_mission=meta.get('base_mission',r['case_id']),
            strategy=r['request']['strategy'],N=len(r['scenario']['mission']['tasks']),M=m,
            k_R=a['represented']['minimum'] if a['represented']['minimum'] is not None else 'unresolved',
            k_full=a['full_domain']['minimum'] if a['full_domain']['minimum'] is not None else 'unresolved',
            witness_level=k,affected=a['affected']['count'],affected_fraction=a['affected']['fraction'],
            structural_nodes=a['affected']['structural_nodes'],material_nodes=a['affected']['material_nodes'],
            changed=changed,preserved=m-changed if w else None,held_fixed_by_scope=held,
            scope3_equals_scope4=a['scope3_equals_scope4'],nodes=a['effort']['nodes'],branches=a['effort']['branches'],
            setup_s=a['effort'].get('setup_s'),search_s=a['effort'].get('search_s'),
            solve_s=r['timing']['solve_s'],audit_s=r['timing']['audit_s'],
            witness_s=a['effort']['first_witness_s'],certificate_s=a['effort']['represented_certificate_s']))
    return rows


def random_figure(records,out):
    primary=[r for r in records if r['request']['strategy']=='H']
    rows=observed_rows(primary);summary=summarize(primary)
    csv_write(out/'random_observations.csv',observed_rows(records))
    freq=[]
    for domain in ('represented','full_domain'):
        d=summary[domain]
        for k in LEVELS:
            interval=d['identification_intervals'][str(k)]
            freq.append(dict(domain=domain,level=k,certified=d['certified'][str(k)],
                             total=d['n'],frequency_lower=interval[0],frequency_upper=interval[1],unresolved=d['unresolved']))
    csv_write(out/'level_frequencies.csv',freq)
    fig,axes=plt.subplots(2,2,figsize=(7.16,5.05),layout='constrained')
    ax=axes[0,0];cats=[*LEVELS,None]
    counts=Counter(r['result']['represented']['minimum'] for r in primary)
    heights=[100*counts[k]/len(primary) for k in cats]
    ax.bar(range(7),heights,color=[COLORS[k] for k in cats],edgecolor='black',linewidth=.5)
    ci=summary['represented_certified_frequency_cluster_bootstrap_95']
    ax.errorbar(range(7),heights,yerr=[[max(0,h-100*ci[str(k)][0]) for k,h in zip(cats,heights)],
        [max(0,100*ci[str(k)][1]-h) for k,h in zip(cats,heights)]],fmt='none',ecolor='black',capsize=2,lw=.7)
    ax.set(xticks=range(7),xticklabels=[label(k) for k in cats],ylabel='Updates (%)',xlabel='Certified represented minimum $k_R^F$',
           title=f'(a) Level frequencies · {len(primary)} updates',ylim=(0,105))
    ax=axes[0,1]
    bubbles=Counter((r['affected_fraction'],r['changed']/r['M']) for r in rows if r['changed'] is not None)
    for (x,y),count in bubbles.items():
        ax.scatter(x,y,s=18+9*count,color='#245B86',alpha=.65,edgecolor='white',linewidth=.5)
        if count>=3: ax.annotate(str(count),(x,y),xytext=(5,4),textcoords='offset points',fontsize=8)
    ax.plot([0,1],[0,1],':',color='#888888',lw=.8)
    ax.set(xlim=(-.05,1.08),ylim=(-.05,1.08),xlabel='Affected UAVs / M',ylabel='Changed UAV plans / M',
           title=f"(b) Propagation and change · {sum(r['changed'] is not None for r in rows)} witnesses")
    ax=axes[1,0]
    kept=[r['preserved']/r['M'] for r in rows if r['preserved'] is not None]
    fixed=[r['held_fixed_by_scope']/r['M'] for r in rows if r['held_fixed_by_scope'] is not None]
    for pos,values,color in [(0,fixed,'#238B76'),(1,kept,'#245B86')]:
        counter=Counter(values)
        for value,count in counter.items():
            ax.scatter(pos,value,s=15+9*count,color=color,alpha=.7)
            if count>=3: ax.annotate(str(count),(pos,value),xytext=(7,0),textcoords='offset points',fontsize=8)
    ax.set(xticks=[0,1],xticklabels=['Held fixed by scope','Unchanged in witness'],xlim=(-.45,1.6),ylim=(-.08,1.18),yticks=[0,.25,.5,.75,1],
           ylabel='Fraction of UAV plans',title='(c) Preservation · feasible witnesses')
    ax=axes[1,1]
    grouped=defaultdict(list)
    for r in rows: grouped[(r['N'],r['M'],r['k_R']=='unresolved')].append(r['solve_s'])
    sizes=sorted({(r['N'],r['M']) for r in rows})
    for (n,m,unresolved),times in grouped.items():
        x=sizes.index((n,m))
        for j,t in enumerate(sorted(times)):
            ax.scatter(x+(j-(len(times)-1)/2)*.018,t,marker='x' if unresolved else 'o',s=16,
                       color='#BF493A' if unresolved else '#245B86',alpha=.7,lw=.7)
    ax.set(xticks=range(len(sizes)),xticklabels=[f'{n}/{m}' for n,m in sizes],xlabel='Tasks / UAVs',ylabel='Search + setup wall time (s)',
           title='(d) Certification effort; × = unresolved',ylim=(0,None))
    save(fig,out/'random_primary')
    exposed=[r for r in primary if r['result']['affected']['count']>0]
    (out/'exposed_update_summary.json').write_text(json.dumps(summarize(exposed),indent=2)+'\n')
    paired=[]
    by_key={(r['request']['metadata'].get('base_mission'),r['request']['metadata'].get('update'),r['request']['strategy']):r for r in records}
    for (base,update,strategy),g in by_key.items():
        if strategy!='G':continue
        h=by_key[(base,update,'H')]
        paired.append(dict(base_mission=base,update=update,H_witness_s=h['result']['effort']['first_witness_s'],
            G_witness_s=g['result']['effort']['first_witness_s'],H_certificate_s=h['result']['effort']['represented_certificate_s'],
            H_k_R=h['result']['represented']['minimum'],G_witness_level=g['result']['witness']['validation']['level'] if g['result']['witness'] else None,
            H_total_s=h['timing']['solve_s'],G_total_s=g['timing']['solve_s'],G_certificate_target='not_requested'))
    csv_write(out/'supplement_H_G_evidence_cost.csv',paired)


def boundary_figures(records,out):
    rows=[]
    membership=[]
    for r in records:
        m=r['request']['metadata'];a=r['result']
        rows.append({**m,'case_id':r['case_id'],'k_R':a['represented']['minimum'] if a['represented']['minimum'] is not None else 'unresolved',
                     'k_full':a['full_domain']['minimum'] if a['full_domain']['minimum'] is not None else 'unresolved'})
        for domain in ('represented','full_domain'):
            for k in range(5):
                membership.append(dict(case_id=r['case_id'],domain=domain,level=k,
                    membership=recoverability_membership(a[domain],k),
                    lower=a[domain]['lower'],upper=a[domain]['upper'],record_hash=r['record_hash']))
    csv_write(out/'boundary_observations.csv',rows)
    csv_write(out/'recoverability_membership.csv',membership)
    wind=[r for r in records if r['request']['metadata']['plane']=='wind_duration']
    regimes=sorted({(r['request']['metadata']['deadline_scale'],r['request']['metadata']['battery_slack']) for r in wind})
    legend=[Line2D([],[],marker=MARKERS[k],ls='',color=COLORS[k],label=label(k),markersize=5) for k in [*LEVELS,None]]
    for deadline,battery in regimes:
        fig,axes=plt.subplots(2,3,figsize=(7.16,4.75),layout='constrained')
        for j,template in enumerate(['C1','C2','C3']):
            subset=[r for r in wind if (r['request']['metadata']['template'],r['request']['metadata']['deadline_scale'],r['request']['metadata']['battery_slack'])==(template,deadline,battery)]
            for i,domain in enumerate(['represented','full_domain']):
                ax=axes[i,j]
                for r in subset:
                    meta=r['request']['metadata'];k=r['result'][domain]['minimum']
                    ax.scatter(float(Fraction(meta['severity'])),meta['duration'],c=COLORS[k],marker=MARKERS[k],s=22,linewidths=.7)
                ax.set(xlim=(-.035,.84),ylim=(.15,4.3),xlabel='Relative wind severity',ylabel='Duration / reference time' if j==0 else '',
                    title=template+(' · represented $k_R^F$' if i==0 else ' · full-domain $k^F$'))
                ax.set_yticks([.5,2,4]);ax.set_xticks([0,.4,.8]);ax.grid(alpha=.15)
        fig.legend(handles=legend,loc='outside upper center',ncols=7,title=f'Deadline multiplier {deadline}; battery slack {battery} · ? unresolved')
        save(fig,out/f'boundary_D{deadline}_B{str(battery).replace(".","p")}')
    margin=[r for r in records if r['request']['metadata']['plane']=='deadline_battery']
    fig,axes=plt.subplots(2,3,figsize=(7.16,4.5),layout='constrained')
    for j,template in enumerate(['C1','C2','C3']):
        for i,domain in enumerate(['represented','full_domain']):
            ax=axes[i,j]
            for r in margin:
                meta=r['request']['metadata']
                if meta['template']!=template:continue
                k=r['result'][domain]['minimum']
                ax.scatter(meta['deadline_scale'],meta['battery_slack'],c=COLORS[k],marker=MARKERS[k],s=38)
            ax.set(xlim=(.9,2.1),ylim=(-.08,1.65),xticks=[1,1.5,2],yticks=[.05,.5,1.5],xlabel='Deadline multiplier',
                ylabel='Battery slack' if j==0 else '',title=template+(' · represented $k_R^F$' if i==0 else ' · full-domain $k^F$'))
    fig.legend(handles=legend,loc='outside upper center',ncols=7,title='Fixed q=5/16; duration=2 reference times · ? unresolved')
    save(fig,out/'boundary_deadline_battery')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);args=parser.parse_args()
    out=args.root/'figures';out.mkdir(parents=True,exist_ok=True)
    if (args.root/'random'/'records').exists(): random_figure(load_records(args.root/'random'),out)
    if (args.root/'boundary'/'records').exists(): boundary_figures(load_records(args.root/'boundary'),out)
    if (args.root/'controlled'/'records').exists(): csv_write(out/'controlled_cases.csv',observed_rows(load_records(args.root/'controlled')))
    captions='''# Figure captions and interpretation

## Randomized primary results

The four panels show (a) certified represented minimum-scope frequencies, (b) affected versus changed UAV plans, (c) plans held fixed by the returned witness scope and plans actually unchanged, and (d) wall time by mission size. Every unresolved classification is retained as ?. Error bars in (a) are 95% percentile intervals from 2,000 bootstrap resamples of whole base missions; A/B updates stay together. These intervals concern certified observations. The accompanying frequency table provides identification bounds that also include unresolved cases. Bubble size denotes multiplicity; printed numbers identify larger groups. Panels (b,c) condition on a feasible witness and do not claim minimum coordinate change. Timing includes setup and capped search, and excludes separately recorded audit time. Red crosses denote unfinished certification. This figure reports the finite represented domain, not unrestricted path-domain impossibility.

## Boundary observations

Rows distinguish represented and full-domain minima. Markers show only evaluated parameter combinations; no contour or interpolated region is implied. Unknowns remain explicit. Reference quantities, fixed libraries, deadline multipliers, battery normalization and duration normalization are defined in docs/FINAL_BENCHMARK_IMPLEMENTATION.md. Adaptive points were added only between adjacent differing certified represented labels. The deadline/battery plot fixes q=5/16 and duration=2 reference times. The recoverability membership table labels each observation inside, outside, or unresolved for each D_{<=k}; a feasible witness can establish membership even when its minimum scope remains unknown.

## Supplementary H/G table

H seeks minimum-scope evidence; G seeks a feasible recovery after the common retention screen. Compare witness times on their common target. H certificate time is the cost of the stronger evidence request. Empty times are censored/unavailable; a G certificate was not requested. Do not interpret this table as a contest for general algorithm superiority.

## Export and provenance

Vector PDF/SVG and 300 dpi PNG are generated from immutable JSON case records. CSV files expose the plotted values. The intended figure width is 7.16 inches with 8 pt body text. Categorical marker shapes supplement color. Statistical uncertainty is shown for randomized certified frequencies; boundary observations are deterministic, conditional samples rather than interpolated estimates.
'''
    (out/'CAPTIONS.md').write_text(captions,encoding='utf-8')
    # Bind post-run layout/export changes to their source and immutable inputs.
    source_paths=[Path(__file__),Path(__file__).resolve().parents[1]/'src/final_benchmark/analysis.py']
    sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    inputs={str(p.relative_to(args.root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for name in ('controlled','boundary','random') for p in sorted((args.root/name/'records').glob('*.json'))}
    outputs={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir()
             if p.is_file() and p.name!='figure_manifest.json'}
    (out/'figure_manifest.json').write_text(json.dumps(dict(source_sha256=sources,input_sha256=inputs,output_sha256=outputs),indent=2)+'\n',encoding='utf-8')
    print(out)


if __name__=='__main__':main()
