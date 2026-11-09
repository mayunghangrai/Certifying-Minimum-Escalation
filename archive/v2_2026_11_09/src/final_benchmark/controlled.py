"""Six analytic cases; expected outcomes are checked, never used as evidence."""
from dataclasses import dataclass
from time import perf_counter

from env.scenario import Scenario
from env.local_scope import change_metrics,preservation_metrics
from recovery.local_search import recover_local, verify_local_witness, bounds
from recovery.physical_proofs import physical_certificate, verify_physical_certificate
from recovery.representation import PathLibrary


@dataclass(frozen=True)
class Case:
    name: str
    scenario: Scenario
    library: PathLibrary
    expected: object = None
    witness_plan: dict | None = None
    witness_reserves: dict | None = None


def make_plan(payload,sequences):
    tasks = {t['id']:t for t in payload['mission']['tasks']}
    depot = payload['mission']['depot_xy']
    plan = dict(assignment={i:None for i in tasks},routes={})
    reserves = {}
    for u in payload['mission']['vehicles']:
        uid = u['id']
        ids = sequences.get(uid,[])
        sites = [*ids,'DEPOT'] if ids else []
        positions = [depot]+[depot if i=='DEPOT' else tasks[i]['position_xy'] for i in sites]
        paths = [[a,b] for a,b in zip(positions,positions[1:])]
        bound = u['slot_bound']
        if len(sites)>bound: raise ValueError('sequence exceeds slot bound')
        deliveries = [0]+[tasks[i]['demand'] if i!='DEPOT' else 0 for i in sites]
        plan['routes'][uid] = dict(stops=sites+[None]*(bound-len(sites)),
            paths=paths+[[depot]]*(bound-len(sites)),
            loads=[sum(tasks[i]['demand'] for i in ids)]+[0]*bound,
            deliveries=deliveries+[0]*(bound+1-len(deliveries)))
        reserves[uid] = {'initial':[depot]} if ids else {}
        for h,i in enumerate(ids,1):
            plan['assignment'][i] = uid
            reserves[uid][str(h)] = [tasks[i]['position_xy'],depot]
    return plan,reserves


def base_payload(name,tasks,speeds,*,alpha=.2,operation_time=0,helper_budget=1):
    p = dict(schema_version='wind-benchmark-v2',formulation_date='2026-09-30',benchmark_id=name,
        units=dict(distance='km',time='h',mass='kg',energy='Wh',quantity='commodity_unit'),
        hierarchy=dict(helper_budget=helper_budget,affected_set_rule='directed_incumbent_union'),
        mission=dict(epoch_h=0,horizon_h=20,commodity_unit_mass_kg=1,
            operating_region_xy=[[-2,-1],[3,-1],[3,3],[-2,3]],depot_xy=[0,0],
            tasks=[dict(id=i,position_xy=xy,demand=1,mandatory=1,deadline_h=d) for i,xy,d in tasks],
            vehicles=[dict(id=f'U{j}',airspeed_kmh=v,empty_mass_kg=1,
                energy_coefficient_wh_per_kg_km=1,battery_capacity_wh=100,reserve_wh=1,
                payload_capacity_kg=max(2,len(tasks)),slot_bound=3) for j,v in enumerate(speeds,1)]),
        operations=dict(service_duration_h=operation_time,service_energy_wh=operation_time,
                        preparation_duration_h=operation_time,depot_bays=None),
        commitments={a:[] for a in 'ASPL'})
    p['state'] = dict(depot_stock=len(tasks),cumulative_delivered={i:0 for i,_,_ in tasks},
        fleet={u['id']:dict(position_xy=[0,0],battery_wh=100,onboard=0,mode='idle',residual_operation=None)
               for u in p['mission']['vehicles']})
    p['wind'] = dict(cells=[dict(id='WEST',polygon_xy=[[-2,-1],[0,-1],[0,3],[-2,3]]),
                               dict(id='east',polygon_xy=[[0,-1],[3,-1],[3,3],[0,3]])],
        boundary_owner='lowest_cell_id',time_knots_h=[0,20],speed_bound_kmh=max(.9,abs(alpha)),
        previous=dict(issued_at_h=0,values=[[[0,0]],[[0,0]]],admissible=[[True],[True]],coverage=['forecast']),
        received=dict(issued_at_h=0,values=[[[0,0]],[[-alpha,0]]],admissible=[[True],[True]],coverage=['forecast']),
        update_support=[['east',0]])
    return p


def controlled_case(name,*,include_bypass=True,operation_time=0,helper_budget=1):
    if name in ('C0','C3','C4'):
        alpha = dict(C0=.05,C3=.3,C4=.8)[name]
        p = base_payload(name,[('C',[1,0],1.1),('E',[-.2,0],.3),('D',[-1,0],.8)],
                         [1,1.5,2.5],alpha=alpha,operation_time=operation_time,helper_budget=helper_budget)
        original = dict(U1=['C'],U2=['E'],U3=['D'])
        recovered = dict(C0=original,C3=dict(U1=['E'],U2=['C'],U3=['D']),
                         C4=dict(U1=[],U2=['E','D'],U3=['C']))[name]
        expected = dict(C0=0,C3=3,C4=4)[name]
        if name=='C4' and helper_budget>=2: expected=3
    elif name=='C1':
        p = base_payload(name,[('C',[2,0],.75)],[5,5,5],alpha=3,
                         operation_time=operation_time,helper_budget=helper_budget)
        p['wind']['cells'] = [dict(id='WEST',polygon_xy=[[-2,-1],[0,-1],[0,3],[-2,3]]),
            dict(id='EAST',polygon_xy=[[0,-1],[3,-1],[3,.25],[0,.25]]),
            dict(id='UPPER',polygon_xy=[[0,.25],[3,.25],[3,3],[0,3]])]
        for projection in ('previous','received'):
            p['wind'][projection]['values'].append([[0,0]])
            p['wind'][projection]['admissible'].append([True])
        p['wind']['update_support'] = [['EAST',0]]
        original = recovered = dict(U1=['C'])
        expected = 1
    elif name=='C2':
        p = base_payload(name,[('B',[1,0],1.7),('A',[.5,0],1.6)],[1,1,1],alpha=.2,
                         operation_time=operation_time,helper_budget=helper_budget)
        original,recovered,expected = dict(U1=['B','A']),dict(U1=['A','B']),2
    elif name=='Cinf':
        p = base_payload(name,[('C',[1,0],1.1)],[1,1,1],alpha=.2,
                         operation_time=operation_time,helper_budget=helper_budget)
        original,recovered,expected = dict(U1=['C']),None,'infinity'
    else:
        raise ValueError('unknown controlled case')
    p['incumbent'],p['reserve_paths'] = make_plan(p,original)
    candidate,reserves = make_plan(p,recovered) if recovered is not None else (None,None)
    extra = []
    if name=='C1' and include_bypass:
        bypass = [[0,0],[0,.5],[2,.5],[2,0]]
        candidate['routes']['U1']['paths'][0] = bypass
        extra.append(bypass)
    scenario = Scenario(p)
    return Case(name,scenario,PathLibrary.build(scenario,nominal_paths=extra),expected,candidate,reserves)


def add_witness(report,scenario,library,plan,reserves,*,clock_start):
    validation = verify_local_witness(scenario,library,plan,reserves,4)
    if not validation['accepted'] or not validation['exact']:
        raise ValueError('external controlled witness failed exact validation: '+str(validation))
    report['witness'] = dict(plan=plan,reserve_paths=reserves,exact=True,exact_transfers=None,
                             validation=validation,certificate_level=4,source='supplied_and_independently_checked')
    k = validation['level']
    report['represented'] = bounds(report['represented']['excluded_levels'],k)
    report['full_domain'] = bounds(report['full_domain']['excluded_levels'],k)
    report['change'] = change_metrics(scenario,plan,report['affected']['uavs'])
    report['preservation'] = preservation_metrics(scenario,plan,k,report['affected']['uavs'])
    now = perf_counter()-clock_start
    if report['effort']['first_witness_s'] is None: report['effort']['first_witness_s']=now
    for domain,key in (('represented','represented_certificate_s'),('full_domain','full_domain_certificate_s')):
        if report[domain]['minimum'] is not None: report['effort'][key]=now


def add_physical_certificate(report,scenario,certificate,*,clock_start):
    if not verify_physical_certificate(scenario,certificate):
        raise ValueError('invalid physical exclusion')
    report['physical_certificates'].append(certificate)
    excluded = set(report['full_domain']['excluded_levels']) | set(range(certificate['excluded_through']+1))
    for field,extra in (('full_domain',set()),('represented',set(report['represented']['excluded_levels']))):
        old = report[field]
        report[field] = bounds(excluded|extra,old['upper'],old['numerical_upper'])
    for domain,key in (('represented','represented_certificate_s'),('full_domain','full_domain_certificate_s')):
        if report[domain]['minimum'] is not None and report['effort'][key] is None:
            report['effort'][key]=perf_counter()-clock_start


def controlled_record(case):
    start = perf_counter()
    result = recover_local(case.scenario,case.library,max_nodes=0,max_branches=0)
    if case.witness_plan is not None:
        add_witness(result,case.scenario,case.library,case.witness_plan,case.witness_reserves,clock_start=start)
    upper = result['full_domain']['upper']
    target = 4 if upper is None else upper-1
    if target>=0:
        cert = physical_certificate(case.scenario,target)
        if cert is None: raise ValueError(f'{case.name}: physical exclusion not established')
        add_physical_certificate(result,case.scenario,cert,clock_start=start)
    result['effort']['controlled_evidence_s'] = perf_counter()-start
    result['effort']['elapsed_s'] = perf_counter()-start
    result['effort']['method'] = 'supplied witness plus independent physical relaxation'
    return result
