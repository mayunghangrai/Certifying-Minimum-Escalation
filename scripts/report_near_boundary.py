"""Audit and report the frozen conditional Study-3 panel, with static figures."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from final_benchmark.near_boundary import summarize_near
from final_benchmark.analysis import load_records, distribution, _stats, LEVELS
from recovery.local_search import digest

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

COLORS = {0:'#245B86',1:'#238B76',2:'#C28016',3:'#805394',4:'#BF493A','infinity':'#252525',None:'#B8B8B8'}
STRATA = [('incumbent','above'),('incumbent','below'),('fixed_sequence','above'),('fixed_sequence','below')]
STRATUM_LABELS = ['Incumbent, above','Incumbent, below','Path repair, above','Path repair, below']
COMPONENTS = ['setup_s','static_screen_s','proposal_s','represented_proof_s','physical_proof_s','audit_s']


def observations(records):
    rows = []
    for r in records:
        a, meta = r['result'], r['request']['metadata']
        w = a['witness']
        rows.append(dict(case_id=r['case_id'],anchor=meta['anchor'],side=meta['side'],seed=meta['seed'],
            N=meta['n'],M=meta['m'],family=meta['family'],critical_task=meta['critical_task'],
            previous_delivery=meta['previous_delivery'],updated_delivery=meta['updated_delivery'],
            boundary_delivery=meta['boundary_delivery'],reference_delay=meta['delay'],
            k_R=a['represented']['minimum'] if a['represented']['minimum'] is not None else 'unresolved',
            k_full=a['full_domain']['minimum'] if a['full_domain']['minimum'] is not None else 'unresolved',
            lower_R=a['represented']['lower'],upper_R=a['represented']['upper'],
            lower_full=a['full_domain']['lower'],upper_full=a['full_domain']['upper'],
            affected=a['affected']['count'],affected_fraction=a['affected']['fraction'],
            structural_closure=a['affected']['structural_nodes'],material_support=a['affected']['material_nodes'],
            witness_level=w['validation']['level'] if w else None,
            changed=a['change']['changed_uav_count'] if w else None,
            outside_changed=a['change']['outside_changed'] if w else None,
            unchanged_fraction=a['change']['preserved_fraction'] if w else None,
            held_fixed=a['preservation']['held_fixed_count'] if w else None,
            held_fixed_fraction=a['preservation']['held_fixed_fraction'] if w else None,
            release_mask_collapse=a['scope3_equals_scope4'],
            candidate_checks=a['effort']['candidate_checks'],
            represented_certificate_s=a['effort']['represented_certificate_s'],
            full_certificate_s=a['effort']['full_domain_certificate_s'],
            solve_s=r['timing']['solve_s'],audit_s=r['timing']['audit_s'],
            **{key:a['effort'][key] for key in COMPONENTS if key!='audit_s'}))
    return rows


def csv_write(path, rows):
    if not rows: return
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)


def figures(records, rows, output):
    plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
        'font.size':8,'axes.titlesize':8.5,'legend.fontsize':7,'svg.fonttype':'none','pdf.fonttype':42,
        'axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':.7,'savefig.dpi':300})
    fig, axes=plt.subplots(2,2,figsize=(7.16,5.3),layout='constrained')
    cats=[*LEVELS,None]
    for ax, domain, title in zip(axes[0],('represented','full_domain'),
            ['(a) Represented minimum $k_R^F$','(b) Full-domain minimum $k^F$']):
        for j,(anchor,side) in enumerate(STRATA):
            subset=[r for r in records if (r['request']['metadata']['anchor'],r['request']['metadata']['side'])==(anchor,side)]
            count=Counter(r['result'][domain]['minimum'] for r in subset)
            left=0
            for k in cats:
                width=100*count[k]/len(subset) if subset else 0
                ax.barh(j,width,left=left,color=COLORS[k],height=.63,edgecolor='white',linewidth=.6,
                        hatch='///' if k is None else None)
                if width>=9: ax.text(left+width/2,j,str(count[k]),ha='center',va='center',fontsize=7,
                                    color='black' if k is None else 'white')
                left+=width
        ns=[sum((r['anchor'],r['side'])==key for r in rows) for key in STRATA]
        ax.set(yticks=range(4),yticklabels=[f'{name} (n={n})' for name,n in zip(STRATUM_LABELS,ns)],
               xlim=(0,100),xticks=[0,50,100],xlabel='Cases (%) · labels show counts',title=title)
        ax.invert_yaxis()
    stressed=[r for r in rows if r['side']=='below']
    witnessed=[r for r in stressed if r['changed'] is not None]
    ax=axes[1,0]
    for anchor,marker,color,label in [('incumbent','o','#238B76','Incumbent boundary'),
                                       ('fixed_sequence','s','#805394','Path-repair boundary')]:
        counts=Counter((r['affected_fraction'],r['changed']/r['M']) for r in witnessed if r['anchor']==anchor)
        for (x,y),count in counts.items():
            ax.scatter(x,y,s=20+5*count,marker=marker,color=color,alpha=.55,edgecolor='white',linewidth=.5)
        ax.scatter([],[],s=25,marker=marker,color=color,label=label)
    ax.plot([0,1],[0,1],':',color='#888888',lw=.8)
    ax.set(xlim=(-.04,1.04),ylim=(-.04,1.04),xticks=[0,.25,.5,.75,1],yticks=[0,.25,.5,.75,1],
           xlabel='Affected UAVs / M',ylabel='Changed UAV plans / M',
           title=f'(c) Tighter deadlines · {len(witnessed)}/{len(stressed)} witnesses')
    ax.legend(loc='upper left',frameon=False)
    ax=axes[1,1]
    sizes=sorted({(r['N'],r['M']) for r in stressed})
    labels=['Setup','Exact path screens','Repair proposals','Represented proofs','Physical proofs','Replay']
    colors=['#B8C6D3','#245B86','#C28016','#805394','#238B76','#A0A0A0']
    bottom=[0.]*len(sizes)
    for key,label,color in zip(COMPONENTS,labels,colors):
        heights=[statistics.mean(r[key] for r in stressed if (r['N'],r['M'])==size) for size in sizes]
        ax.bar(range(len(sizes)),heights,bottom=bottom,color=color,width=.66,label=label)
        bottom=[a+b for a,b in zip(bottom,heights)]
    ax.set(xticks=range(len(sizes)),xticklabels=[f'{n}/{m}' for n,m in sizes],xlabel='Tasks / UAVs',
           ylabel='Mean wall time per case (s)',title='(d) Evidence cost · all tighter-deadline cases')
    ax.legend(loc='upper left',bbox_to_anchor=(0,-.2),ncol=2,frameon=False)
    handles=[Patch(facecolor=COLORS[k],hatch='///' if k is None else None,
                   label='Unresolved' if k is None else '∞' if k=='infinity' else f'Level {k}') for k in cats]
    fig.legend(handles=handles,loc='upper center',bbox_to_anchor=(.5,1.06),ncol=7,frameon=False)
    for ext in ('png','pdf','svg'): fig.savefig(output/f'study3_near_boundary.{ext}',bbox_inches='tight')
    plt.close(fig)


def report(summary, rows, records, output, run):
    lines=['# Refined Study 3: deliberate deadline-boundary stress','',
        'These results describe a conditional synthetic stress population. They do not estimate deployment frequencies. '
        'The two boundary anchors and the two deadline sides are reported separately.','',
        '## Sampling and evidence','',
        f"Requested {summary['sampling']['requested_bases']} base pairs; accepted {summary['sampling']['accepted_bases']}; "
        f"generation failures {summary['sampling']['failed_bases']}. Each accepted base supplies a tighter and a looser deadline.",
        '', 'The incumbent anchor crosses retention feasibility. The path-repair anchor crosses the best represented fixed-sequence '
        'path repair. The latter is a boundary within the stored path library. Both members were exactly feasible before the update. '
        'The update, geometry, assignment, and resource settings agree within each pair; only the critical deadline differs.',
        '', 'Critical deadlines lie 10% of the positive reference wind delay below or above that reference delivery time. '
        'Battery capacity has declared slack relative to both incumbent forecasts. The stationary wind and generous horizon isolate '
        'the deadline mechanism. This cohort does not explore all combinations of battery, duration, geometry, or execution state.',
        '', '## 1. Which intervention levels were certified?','']
    for field,title in [('represented','Represented minimum, k_R^F'),('full_domain','Full-domain minimum, k^F')]:
        lines.extend([f'### {title}','','| Boundary / deadline side | n | 0 | 1 | 2 | 3 | 4 | ∞ | Unresolved |',
                      '|---|---:|---:|---:|---:|---:|---:|---:|---:|'])
        for (anchor,side),label in zip(STRATA,STRATUM_LABELS):
            d=summary['strata'][anchor+'_'+side][field]
            lines.append('| '+label+' | '+' | '.join(map(str,[d['n'],*[d['certified'][str(k)] for k in LEVELS],d['unresolved']]))+' |')
        lines.append('')
    lines.extend(['Unknown minima remain in the denominator. An unknown minimum can still have an exactly verified repair and useful '
                  'lower/upper bounds. A represented infinity does not establish unrestricted impossibility. The level-frequency export '
                  'contains identification intervals, which account for unresolved labels. Sampling confidence intervals are omitted '
                  'because this small balanced panel shares seeded random draws across strata.','',
                  '## 2. Propagation and actual change','',
                  '| Tighter-deadline cohort | Witnesses / cases | Mean affected UAVs | Mean changed UAVs among witnesses | Median dependency closure |',
                  '|---|---:|---:|---:|---:|'])
    for anchor,label in [('incumbent','Incumbent boundary'),('fixed_sequence','Path-repair boundary')]:
        subset=[r for r in rows if r['anchor']==anchor and r['side']=='below']
        witnesses=[r for r in subset if r['changed'] is not None]
        avg=lambda key,rs: f'{statistics.mean(r[key] for r in rs):.2f}' if rs else '—'
        med=statistics.median(r['structural_closure'] for r in subset) if subset else '—'
        lines.append(f'| {label} | {len(witnesses)}/{len(subset)} | {avg("affected",subset)} | {avg("changed",witnesses)} | {med} |')
    lines.extend(['','Dependency-graph nodes, affected UAVs, and changed UAV plans are different objects. Changed sets describe the returned '
                  'witness; the solver does not minimize their cardinality within a scope.','',
                  '## 3. Locality and preservation','',
                  '| Tighter-deadline cohort | Mean plans held fixed by witness scope | Mean plans unchanged in witness | Witnesses changing an outsider |',
                  '|---|---:|---:|---:|'])
    for anchor,label in [('incumbent','Incumbent boundary'),('fixed_sequence','Path-repair boundary')]:
        subset=[r for r in rows if r['anchor']==anchor and r['side']=='below' and r['changed'] is not None]
        avg=lambda key: f'{100*statistics.mean(r[key] for r in subset):.1f}%' if subset else '—'
        lines.append(f'| {label} | {avg("held_fixed_fraction")} | {avg("unchanged_fraction")} | {sum(r["outside_changed"]>0 for r in subset)}/{len(subset)} |')
    lines.extend(['','These are feasible preservation guarantees, not a causal comparison against a globally released solver. '
                  'A certified minimum scope does not prove that every UAV it permits must participate. '
                  'The generator conditions on 0 < |U0| <= floor(M/2); the small affected sets are a design condition. '
                  'With b=1 and these fleet sizes this also prevents the complete Level-3 release mask from equaling Level 4 by construction. '
                  'Collapse frequency for the broad population remains a result of the original randomized study.','',
                  '## 4. Cost of obtaining evidence','',
                  '| Tighter-deadline cohort | Median solve (s) | Maximum solve (s) | Median replay (s) | Total solve + replay (s) |',
                  '|---|---:|---:|---:|---:|'])
    for anchor,label in [('incumbent','Incumbent boundary'),('fixed_sequence','Path-repair boundary')]:
        subset=[r for r in rows if r['anchor']==anchor and r['side']=='below']
        if not subset: continue
        lines.append(f'| {label} | {statistics.median(r["solve_s"] for r in subset):.2f} | '
                     f'{max(r["solve_s"] for r in subset):.2f} | {statistics.median(r["audit_s"] for r in subset):.2f} | '
                     f'{sum(r["solve_s"]+r["audit_s"] for r in subset):.1f} |')
    lines.extend(['',f"Generation used {summary['sampling']['generation_s']:.1f} s. Recorded solve plus first replay for all cases used "
                  f"{sum(r['solve_s']+r['audit_s'] for r in rows):.1f} s. Later reporting/replay overhead is additional.",'',
                  'The five-second cap applies to generic repair proposals, with a 120-proposal ceiling. Exact screens, proof construction, '
                  'setup, and replay are recorded separately and can increase total case time. Both solved and unresolved cases enter the cost panel. '
                  'This asks for minimum-scope evidence; it is not an H-versus-G speed contest.','',
                  '## Figure and reproducibility','',
                  '![Study 3: levels, propagation, and evidence cost](study3_near_boundary.png)','',
                  'The bars show certified labels and unresolved cases. The propagation panel uses only tighter-deadline cases with exact '
                  'witnesses; its title gives the denominator. Circle/square size reflects repeated coordinates. The cost panel includes all '
                  'tighter-deadline cases and includes represented proof time.','',
                  f'Run directory: `{run.resolve()}`. The run manifest binds source and configuration, and every case and exclusion was replay-audited. '
                  'The accompanying analysis manifest binds all source inputs and exports. The earlier September 30 benchmark and both '
                  'development pilots remain separate.',''])
    (output/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    summary=summarize_near(args.run)  # source archive, paired ledgers, and exact evidence replay
    records=load_records(args.run,audit=False)
    rows=observations(records)
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'report_data.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    csv_write(args.output/'observations.csv',rows)
    frequencies=[]
    for (anchor,side),label in zip(STRATA,STRATUM_LABELS):
        for field in ('represented','full_domain'):
            d=summary['strata'][anchor+'_'+side][field]
            for k in LEVELS:
                interval=d['identification_intervals'][str(k)]
                frequencies.append(dict(stratum=label,domain=field,level=k,n=d['n'],certified=d['certified'][str(k)],
                                        unresolved=d['unresolved'],frequency_lower=interval[0],frequency_upper=interval[1]))
    csv_write(args.output/'level_frequencies.csv',frequencies)
    figures(records,rows,args.output)
    report(summary,rows,records,args.output,args.run)
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    inputs=[args.run/'manifest.json',args.run/'source.zip',*sorted((args.run/'records').glob('*.json')),
            *sorted((args.run/'sampling').glob('*.json'))]
    sources=[Path(__file__),ROOT/'src/final_benchmark/near_boundary.py',ROOT/'src/final_benchmark/analysis.py']
    outputs=[args.output/name for name in ['REPORT.md','report_data.json','observations.csv','level_frequencies.csv',
                                         'study3_near_boundary.png','study3_near_boundary.pdf','study3_near_boundary.svg']]
    manifest=dict(version='near-boundary-analysis-v1',audited_records=len(records),
                  inputs={str(p.resolve()):sha(p) for p in inputs},sources={str(p.resolve()):sha(p) for p in sources},
                  outputs={str(p.resolve()):sha(p) for p in outputs})
    manifest['content_hash']=digest(manifest)
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(audited_records=len(records),sampling=summary['sampling'],report=str((args.output/'REPORT.md').resolve())),indent=2))


if __name__=='__main__': main()
