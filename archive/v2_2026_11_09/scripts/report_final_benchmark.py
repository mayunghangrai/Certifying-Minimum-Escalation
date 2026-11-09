"""Derive report tables from immutable records, with certificate replay by default."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from final_benchmark.analysis import load_records, summarize, recoverability_membership
from final_benchmark.records import verify_archive
from recovery.local_search import bounds


def stats(values):
    values=list(values)
    return dict(n=len(values),median=statistics.median(values),mean=statistics.mean(values),
                minimum=min(values),maximum=max(values),total=sum(values)) if values else dict(n=0)


def rows_csv(path,rows):
    if not rows:return
    with path.open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)


def diagnostics(records):
    primary=[r for r in records if r['request']['strategy']=='H']
    witnesses=[r for r in primary if r['result']['witness']]
    changed=[r for r in witnesses if r['result']['change']['changed_uav_count']>0]
    exposed=[r for r in primary if r['result']['affected']['count']>0]
    strata=defaultdict(list)
    for r in primary:
        m=r['scenario']['mission'];strata[f"{len(m['tasks'])}/{len(m['vehicles'])}"].append(r)
    return dict(summary=summarize(records),
        exposed=summarize(exposed),
        structural_closure_nodes=stats(r['result']['affected']['structural_nodes'] for r in primary),
        material_closure_nodes=stats(r['result']['affected']['material_nodes'] for r in primary),
        affected_uavs=stats(r['result']['affected']['count'] for r in primary),
        exact_witness_count=len(witnesses),nonzero_witness_count=len(changed),
        affected_but_retained=sum(r['result']['affected']['count']>0 and r['result']['represented']['minimum']==0 for r in primary),
        change_less_than_affected=sum(r['result']['change']['changed_uav_count']<r['result']['affected']['count'] for r in witnesses),
        nonzero_preserving_outsiders=sum(r['result']['preservation']['held_fixed_count']>0 for r in changed),
        nonzero_witnesses=[dict(case_id=r['case_id'],level=r['result']['witness']['validation']['level'],
            k_R=r['result']['represented']['minimum'],k_full=r['result']['full_domain']['minimum'],
            affected=r['result']['affected']['count'],M=len(r['scenario']['mission']['vehicles']),
            changed=r['result']['change']['changed_uav_count'],
            held_fixed=r['result']['preservation']['held_fixed_count']) for r in changed],
        witness_time_s=stats(r['result']['effort']['first_witness_s'] for r in witnesses),
        represented_certificate_time_s=stats(r['result']['effort']['represented_certificate_s'] for r in primary
            if r['result']['effort']['represented_certificate_s'] is not None),
        setup_s=stats(r['result']['effort']['setup_s'] for r in primary),
        search_s=stats(r['result']['effort']['search_s'] for r in primary),
        solve_s=stats(r['timing']['solve_s'] for r in primary),
        audit_s=stats(r['timing']['audit_s'] for r in primary),
        by_size={key:dict(n=len(group),certified=dict(Counter(str(r['result']['represented']['minimum']) for r in group)),
            witnesses=sum(r['result']['witness'] is not None for r in group),
            solve_s=stats(r['timing']['solve_s'] for r in group),
            audit_s=stats(r['timing']['audit_s'] for r in group),
            nodes=stats(r['result']['effort']['nodes'] for r in group),
            branches=stats(r['result']['effort']['branches'] for r in group)) for key,group in strata.items()})


def budget_comparison(primary,extra):
    old={r['case_id']:r for r in primary if r['request']['strategy']=='H'}
    new={r['case_id']:r for r in extra}
    if set(old)!=set(new):raise ValueError('budget sensitivity must contain every primary H update')
    rows=[];combined=defaultdict(Counter)
    for key,a in old.items():
        b=new[key]
        if (a['scenario']!=b['scenario'] or a['library']!=b['library']):
            raise ValueError('budget sensitivity changed the mission or representation')
        row=dict(case_id=key)
        for domain in ('represented','full_domain'):
            x,y=a['result'][domain],b['result'][domain]
            upper=[z['upper'] for z in (x,y) if z['upper'] is not None]
            merged=bounds(set(x['excluded_levels'])|set(y['excluded_levels']),min(upper) if upper else None)
            combined[domain][str(merged['minimum'])]+=1
            row.update({domain+'_5s':x['minimum'],domain+'_60s':y['minimum'],
                        domain+'_combined':merged['minimum'],domain+'_combined_lower':merged['lower'],
                        domain+'_combined_upper':merged['upper']})
        row.update(solve_5s=a['timing']['solve_s'],solve_60s=b['timing']['solve_s'],
                   witness_5s=a['result']['effort']['first_witness_s'],witness_60s=b['result']['effort']['first_witness_s'])
        rows.append(row)
    return rows,{k:dict(v) for k,v in combined.items()}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True,type=Path)
    args=parser.parse_args();root=args.root;out=root/'analysis';out.mkdir(parents=True,exist_ok=True)
    required=dict(controlled=6,sensitivity=36,boundary=231,random=128,random_budget60=96)
    data={};manifests={}
    for name,count in required.items():
        manifest=json.loads((root/name/'manifest.json').read_text(encoding='utf-8'))
        verify_archive(root/name/'source.zip',manifest['source_files'])
        records=load_records(root/name)
        if len(records)!=count:raise ValueError(f'{name}: expected {count} completed records, got {len(records)}')
        if any(r['run_hash']!=manifest['run_hash'] for r in records):raise ValueError('run binding mismatch')
        data[name]=records;manifests[name]=manifest
    membership=[]
    for domain in ('represented','full_domain'):
        for k in range(5):
            count=Counter(recoverability_membership(r['result'][domain],k) for r in data['boundary'])
            membership.append(dict(domain=domain,level=k,inside=count['inside'],outside=count['outside'],unresolved=count['unresolved']))
    rows_csv(out/'boundary_membership_counts.csv',membership)
    compare,combined=budget_comparison(data['random'],data['random_budget60'])
    rows_csv(out/'budget_comparison.csv',compare)
    primary=[r for r in data['random'] if r['request']['strategy']=='H']
    lookup={r['case_id']:r for r in primary}
    pairs=[]
    for g in data['random']:
        if g['request']['strategy']!='G':continue
        h=lookup[g['case_id'][:-2]]
        if h['scenario']!=g['scenario'] or h['library']!=g['library']:raise ValueError('H/G inputs differ')
        pairs.append((h,g))
    both=[(h,g) for h,g in pairs if h['result']['witness'] and g['result']['witness']]
    output=dict(record_counts={k:len(v) for k,v in data.items()},
        primary=diagnostics(data['random']),budget60=diagnostics(data['random_budget60']),
        combined_budget_labels=combined,
        boundary=dict(summary=summarize(data['boundary']),membership_counts=membership,
            refined_by_template=dict(Counter(r['request']['metadata']['template'] for r in data['boundary']
                                      if r['request']['metadata']['round']>0))),
        paired_H_G=dict(n=len(pairs),H_witnesses=sum(bool(h['result']['witness']) for h,g in pairs),
            G_witnesses=sum(bool(g['result']['witness']) for h,g in pairs),both_witnesses=len(both),
            H_certificates=sum(h['result']['represented']['minimum'] is not None for h,g in pairs),
            H_witness_s_among_both=stats(h['result']['effort']['first_witness_s'] for h,g in both),
            G_witness_s_among_both=stats(g['result']['effort']['first_witness_s'] for h,g in both),
            G_stronger_certificate='not_requested'),
        audit='All source archives, record hashes, run bindings and certificate claims replayed successfully.',
        interpretation='Primary 5-second results and post-run 60-second sensitivity remain separate. Combined labels use only compatible exact evidence on identical inputs; never mix represented and full-domain exclusions.')
    (out/'report_data.json').write_text(json.dumps(output,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    source=Path(__file__).read_bytes();(out/'report_final_benchmark.py').write_bytes(source)
    analysis_source=Path(__file__).resolve().parents[1]/'src/final_benchmark/analysis.py'
    (out/'analysis_source.py').write_bytes(analysis_source.read_bytes())
    provenance=dict(report_source_sha256=hashlib.sha256(source).hexdigest(),
        run_hashes={k:v['run_hash'] for k,v in manifests.items()},
        input_record_hashes={name:{r['case_id']:r['record_hash'] for r in rr} for name,rr in data.items()},
        output_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir()
                       if p.is_file() and p.name!='manifest.json'})
    (out/'manifest.json').write_text(json.dumps(provenance,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(audited_records=sum(map(len,data.values())),combined_budget_labels=combined,
                         report=str(out/'report_data.json')),indent=2),flush=True)


if __name__=='__main__':main()
