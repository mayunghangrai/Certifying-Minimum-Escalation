"""Serial laptop runner. Run through scripts/final_benchmark.py."""
import argparse
from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path
from time import perf_counter

from .controlled import controlled_case
from .generators import random_pair,boundary_case
from .records import RunStore, atomic_json
from .analysis import write_summary,load_records


def run_near(store, config):
    for n, m in config['sizes']:
        for family in config['families']:
            for seed in config['seeds']:
                for anchor in config.get('anchors', ['incumbent']):
                    _run_near_pair(store, config, n, m, family, seed, anchor)


def _run_near_pair(store, config, n, m, family, seed, anchor):
    from .near_boundary import near_boundary_pair
    from recovery.local_search import digest
    start = perf_counter()
    cases, meta = near_boundary_pair(n, m, family, seed,
        max_attempts=config['max_attempts'], offset=config['offset'], anchor=anchor)
    sampling = dict(version='near-boundary-sampling-v1', run_hash=store.run_hash, metadata=meta,
                    scenario_hashes=[c.scenario.content_hash() for c in cases])
    path = store.path/'sampling'/f"{meta['base_mission']}.json"
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        if old['binding_hash'] != digest(sampling): raise ValueError('sampling ledger differs from frozen generation')
        if old['binding_hash'] != digest({k:v for k,v in old.items() if k not in ('binding_hash', 'generation_s')}):
            raise ValueError('sampling ledger hash mismatch')
    else:
        atomic_json(path, dict(**sampling, binding_hash=digest(sampling), generation_s=perf_counter()-start))
    print(f"generated {meta['base_mission']}: {meta['status']}, {len(meta['attempts'])} attempts", flush=True)
    for case in cases:
        side = case.name.rsplit('_', 1)[1]
        metadata = dict(meta, study='near_boundary', phase=config['phase'], side=side)
        r = store.run_case(case, method='near_boundary', budget=config['budget'], metadata=metadata)
        print(f"  {side}: k_R={r['result']['represented']['minimum']}, full={r['result']['full_domain']['minimum']}, "
              f"bounds_R=[{r['result']['represented']['lower']},{r['result']['represented']['upper']}]", flush=True)


def run_random(store,config):
    total = len(config['sizes'])*len(config['families'])*len(config['seeds'])*2
    done = 0
    for n,m in config['sizes']:
        for family in config['families']:
            for index,seed in enumerate(config['seeds']):
                for case in random_pair(n,m,family,seed):
                    meta = dict(study='random',n=n,m=m,family=family,seed=seed,
                                base_mission=case.name.rsplit('_',1)[0],update=case.name[-1])
                    record = store.run_case(case,budget=config['budget'],metadata=meta)
                    done += 1
                    print(f"{done}/{total} {case.name}: k_R={record['result']['represented']['minimum']} U0={record['result']['affected']['count']}/{m}",flush=True)
                    if index in config.get('paired_seed_indices',[]):
                        store.run_case(replace(case,name=case.name+'_G'),budget=config['budget'],metadata=meta,strategy='G')


def run_boundary(store,config):
    observations = []
    def run(template,q,d,deadline,battery,round_,plane='wind_duration'):
        qq = Fraction(str(q)); severity = 2*qq/(1+qq*qq)
        case = boundary_case(template,severity=str(severity),duration=d,deadline_scale=deadline,battery_slack=battery)
        meta = dict(study='boundary',template=template,q=str(qq),severity=str(severity),duration=d,
                    deadline_scale=deadline,battery_slack=battery,round=round_,plane=plane,
                    base_mission=case.name)
        record = store.run_case(case,method='boundary',budget=config['budget'],metadata=meta)
        observations.append((meta,record))
        print(f"boundary {case.name}: k_R={record['result']['represented']['minimum']} full={record['result']['full_domain']['minimum']}",flush=True)
    for template in config['templates']:
        for deadline in config['deadline_scales']:
            for battery in config['battery_slacks']:
                for q in config['q_values']:
                    for duration in config['durations']:
                        run(template,q,duration,deadline,battery,0)
        for deadline in config['margin_deadlines']:
            for battery in config['margin_batteries']:
                run(template,config['margin_q'],config['margin_duration'],deadline,battery,0,'deadline_battery')
    # Refine only adjacent known, different labels in the SAME evidence domain.
    # Unknown cells are retained and never interpreted as transition evidence.
    remaining = config.get('max_refinements',0)
    for round_ in range(1,config.get('refinement_rounds',0)+1):
        proposals = {}
        for axis in ('q','duration'):
            groups = {}
            for meta,record in observations:
                if meta['plane']!='wind_duration': continue
                other = 'duration' if axis=='q' else 'q'
                key = (meta['template'],meta['deadline_scale'],meta['battery_slack'],meta[other])
                groups.setdefault(key,[]).append((Fraction(str(meta[axis])),meta,record))
            for key,points in sorted(groups.items(),key=lambda x:str(x[0])):
                points.sort(key=lambda x:x[0])
                for left,right in zip(points,points[1:]):
                    labels = [v[2]['result']['represented']['minimum'] for v in (left,right)]
                    if None in labels or labels[0]==labels[1] or left[0]==right[0]: continue
                    middle = (left[0]+right[0])/2
                    m = dict(left[1]);m[axis]=str(middle) if axis=='q' else float(middle)
                    ident=(m['template'],m['q'],m['duration'],m['deadline_scale'],m['battery_slack'])
                    if not any((x['template'],x['q'],x['duration'],x['deadline_scale'],x['battery_slack'])==ident for x,_ in observations):
                        proposals[ident] = m
        for ident,m in sorted(proposals.items(),key=lambda x:str(x[0]))[:remaining]:
            run(m['template'],m['q'],m['duration'],m['deadline_scale'],m['battery_slack'],round_)
            remaining -= 1
        if not remaining or not proposals: break


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['controlled','sensitivity','pilot','random','boundary','near','audit','summarize'])
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--config',type=Path)
    args = parser.parse_args(argv)
    is_near = False
    if args.command in ('audit','summarize') and (args.output/'manifest.json').exists():
        is_near = json.loads((args.output/'manifest.json').read_text(encoding='utf-8'))['config'].get('study')=='near_boundary'
    if args.command=='audit':
        if is_near:
            from .near_boundary import summarize_near
            summary = summarize_near(args.output)
            print(f"{summary['below']['records']+summary['above']['records']} records and all paired sampling ledgers passed replay")
            return
        records = load_records(args.output,audit=True)
        print(f'{len(records)} records passed hash and certificate replay')
        return
    if args.command=='summarize':
        if is_near:
            from .near_boundary import summarize_near
            summary = summarize_near(args.output)
            (args.output/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        else:
            summary = write_summary(args.output)
        print(json.dumps(summary,indent=2))
        return
    if args.config:
        config = json.loads(args.config.read_text(encoding='utf-8'))
    elif args.command=='controlled':
        config = dict(study='controlled',cases=['C0','C1','C2','C3','C4','Cinf'])
    elif args.command=='sensitivity':
        config = dict(study='supplementary_controlled',helper_budgets=[0,1,2],operation_times=[0,.01],cases=['C0','C1','C2','C3','C4','Cinf'])
    elif args.command=='pilot':
        config = dict(study='development_only',sizes=[[3,3],[6,3],[12,4]],families=['uniform','clustered'],
            seeds=[1001,1002],budget=dict(max_nodes=12000,max_branches=1200,max_seconds=2),paired_seed_indices=[])
    else:
        parser.error('primary studies require a frozen --config')
    store = RunStore(args.output,config)
    if args.command=='controlled':
        for name in config['cases']:
            r=store.run_case(controlled_case(name),method='controlled',metadata=dict(study='controlled'))
            print(name,r['result']['full_domain'],flush=True)
    elif args.command=='sensitivity':
        for b in config['helper_budgets']:
            for ground in config['operation_times']:
                for name in config['cases']:
                    case=controlled_case(name,helper_budget=b,operation_time=ground)
                    case=replace(case,name=f'{name}_b{b}_g{str(ground).replace(".","p")}')
                    r=store.run_case(case,method='controlled',metadata=dict(study='supplementary',helper_budget=b,operation_time=ground))
                    print(case.name,r['result']['full_domain']['minimum'],flush=True)
    elif args.command=='boundary':
        run_boundary(store,config)
    elif args.command=='near':
        run_near(store,config)
    else:
        run_random(store,config)
    if args.command=='near':
        from .near_boundary import summarize_near
        summary = summarize_near(args.output)
        (args.output/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    else:
        summary = write_summary(args.output)
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__': main()
