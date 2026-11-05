"""Seeded rational-compatible mission and boundary generators."""
from copy import deepcopy
from fractions import Fraction
import math
import random
from time import perf_counter

from env.fixed_plan import evaluate_plan
from env.scenario import Scenario
from recovery.representation import PathLibrary
from recovery.local_search import recover_local,verify_local_witness
from recovery.physical_proofs import physical_certificate
from .controlled import Case,base_payload,make_plan,controlled_case,add_witness,add_physical_certificate


def axis_path(a,b,horizontal_first=True):
    return [list(a),[b[0],a[1]] if horizontal_first else [a[0],b[1]],list(b)]


def axis_plan(p,sequences):
    plan,reserves = make_plan(p,sequences)
    for route in plan['routes'].values():
        route['paths'] = [axis_path(path[0],path[-1]) for path in route['paths']]
    for paths in reserves.values():
        for label,path in paths.items(): paths[label] = axis_path(path[0],path[-1])
    return plan,reserves


def axis_library(scenario):
    d = scenario.data
    points = sorted({tuple(d['mission']['depot_xy']),*(tuple(t['position_xy']) for t in d['mission']['tasks'])})
    paths = [axis_path(a,b,order) for a in points for b in points for order in (True,False)]
    returns = [p for p in paths if p[-1] == list(d['mission']['depot_xy'])]
    return PathLibrary.build(scenario,nominal_paths=paths,return_paths=returns,direct=False)


def _capacity_reference(p, *, common=False,slack=.2):
    s = Scenario(p)
    before = evaluate_plan(s,projection='previous')
    if before.status!='feasible': raise ValueError('reference mission not feasible: '+str(before.violations))
    requirements = {}
    for u in p['mission']['vehicles']:
        uid = u['id']
        capacity = u['battery_capacity_wh']
        required = capacity-before.final_states[uid]['battery_wh']+u['reserve_wh']
        for key,r in before.reserve_checks.items():
            if key.startswith('reserve:'+uid+':'):
                required = max(required,capacity-r['state']['battery_wh']+r['energy_wh']+u['reserve_wh'])
        requirements[uid] = required
    scale = max(1,max(requirements.values())-min(u['reserve_wh'] for u in p['mission']['vehicles']))
    common_requirement = max(requirements.values())
    for u in p['mission']['vehicles']:
        value = round((common_requirement if common else requirements[u['id']])+slack*scale,12)
        u['battery_capacity_wh'] = value
        p['state']['fleet'][u['id']]['battery_wh'] = value
    return before,scale


def random_pair(n,m,family,seed):
    if n<1 or m<1 or family not in ('uniform','clustered'):
        raise ValueError('invalid generator setting')
    rng = random.Random(seed)
    grid = [(x/10,y/10) for x in range(-10,11) for y in range(-10,11) if (x,y)!=(0,0)]
    if family=='uniform':
        locations = [rng.choice(grid) for _ in range(n)]
    else:
        weights = [(1+100*min((x+.5)**2+y*y,(x-.5)**2+y*y))**-2 for x,y in grid]
        locations = rng.choices(grid,weights=weights,k=n)
    p = base_payload(f'R_{n}_{m}_{family}_{seed}',[(f'T{i+1}',list(xy),None) for i,xy in enumerate(locations)],[1]*m)
    p['mission'].update(horizon_h=1000,operating_region_xy=[[-1,-1],[1,-1],[1,1],[-1,1]])
    p['operations'].update(service_duration_h=.01,service_energy_wh=.01,preparation_duration_h=.01)
    demands = {t['id']:rng.choice([.5,1,1.5]) for t in p['mission']['tasks']}
    for t in p['mission']['tasks']: t.update(demand=demands[t['id']],mandatory=demands[t['id']])
    tasks = {t['id']:t for t in p['mission']['tasks']}
    ordered = sorted(tasks,key=lambda i:(math.atan2(tasks[i]['position_xy'][1],tasks[i]['position_xy'][0]),i))
    if seed%2: rng.shuffle(ordered)
    sequences = {u['id']:[] for u in p['mission']['vehicles']}
    for j,i in enumerate(ordered): sequences[f'U{1+j%m}'].append(i)
    for uid,assigned in sequences.items():
        point = [0,0]
        route = []
        while assigned:
            i = min(assigned,key=lambda i:(sum(abs(a-b) for a,b in zip(point,tasks[i]['position_xy'])),i))
            route.append(i);assigned.remove(i);point=tasks[i]['position_xy']
        sequences[uid] = route
    for u in p['mission']['vehicles']:
        uid = u['id']
        u.update(slot_bound=2*math.ceil(n/m)+3,battery_capacity_wh=10000,
                 energy_coefficient_wh_per_kg_km=rng.choice([.8,1,1.2]),
                 payload_capacity_kg=max(1,sum(demands[i] for i in sequences[uid]))*rng.choice([1,1.25,1.5]))
        p['state']['fleet'][uid]['battery_wh'] = 10000
    p['state']['depot_stock'] = sum(demands.values())*rng.choice([1,1.25,1.5])
    p['incumbent'],p['reserve_paths'] = axis_plan(p,sequences)
    cells = [dict(id=f'C{x}{y}',polygon_xy=[[x/2-1,y/2-1],[(x+1)/2-1,y/2-1],
                    [(x+1)/2-1,(y+1)/2-1],[x/2-1,(y+1)/2-1]]) for x in range(4) for y in range(4)]
    p['wind'].update(cells=cells,time_knots_h=[0,1000],update_support=[])
    for projection in ('previous','received'):
        p['wind'][projection].update(values=[[[0,0]] for _ in cells],admissible=[[True] for _ in cells],coverage=['forecast'])
    before,_ = _capacity_reference(p,slack=[.05,.2,.5][seed%3])
    tau = max(s['time_h'] for s in before.final_states.values())
    horizon = round(max(1,2*tau),12)
    p['mission']['horizon_h'] = horizon
    for uid,records in before.records.items():
        for r in records[1:]:
            if r['site'] in tasks:
                tasks[r['site']]['deadline_h'] = round(r['delivery_h']+[.1,.25,.5][seed%3]*tau,12)
    p['wind']['time_knots_h'] = [round(j*horizon/8,12) for j in range(9)]
    for projection in ('previous','received'):
        p['wind'][projection].update(values=[[[0,0] for j in range(8)] for _ in cells],
                                    admissible=[[True]*8 for _ in cells],coverage=['forecast']*8)
    previous = evaluate_plan(Scenario(p),projection='previous')
    support = [(q['cell_id'],q['bin_index']) for records in previous.records.values()
               for r in records for q in r['wind_queries']]
    result = []
    for update in ('A','B'):
        q = deepcopy(p)
        if update=='B' and support:
            cell,j = rng.choice(support)
            x,y = map(int,cell[1:])
        else:
            x,y,j = rng.randrange(4),rng.randrange(4),rng.randrange(8)
        side,duration = rng.choice([1,2]),rng.choice([1,2,4])
        left,bottom = min(x,4-side),min(y,4-side)
        first = min(max(0,j-rng.randrange(duration)),8-duration)
        qq = Fraction(rng.randint(1,8),16)
        magnitude = 2*qq/(1+qq*qq)
        axis,sign = rng.randrange(2),rng.choice([-1,1])
        vector = [0,0];vector[axis] = wire_rational(sign*magnitude)
        q['wind']['update_support'] = []
        for xx in range(left,left+side):
            for yy in range(bottom,bottom+side):
                r = 4*xx+yy
                for jj in range(first,first+duration):
                    q['wind']['received']['values'][r][jj] = vector
                    q['wind']['update_support'].append([cells[r]['id'],jj])
        name = p['benchmark_id']+'_'+update
        q['benchmark_id'] = name
        scenario = Scenario(q)
        result.append(Case(name,scenario,axis_library(scenario)))
    return tuple(result)


def boundary_case(template,*,severity,duration,deadline_scale=1,battery_slack=.2):
    base = controlled_case(template)
    p = base.scenario.to_dict()
    old = evaluate_plan(base.scenario,projection='previous')
    arrivals = {r['site']:r['delivery_h'] for records in old.records.values() for r in records if r['site'] not in ('ORIGIN','DEPOT')}
    tau = max(arrivals.values())
    for t in p['mission']['tasks']:
        t['deadline_h'] = round(arrivals[t['id']]+deadline_scale*(t['deadline_h']-arrivals[t['id']]),12)
    _capacity_reference(p,common=True,slack=battery_slack)
    # A common partition includes all first- and second-round duration midpoints.
    knots = sorted({0,20,*[round(j*tau/8,12) for j in range(1,33) if j*tau/8<20]})
    end = round(duration*tau,12)
    if end not in knots and end!=0: raise ValueError('duration outside the frozen reference partition')
    p['wind']['time_knots_h'] = knots
    wind_scale = 5 if template=='C1' else 1
    alpha = rational_number(severity)*wind_scale
    p['wind']['speed_bound_kmh'] = .9*wind_scale
    for projection in ('previous','received'):
        p['wind'][projection].update(values=[[[0,0] for _ in knots[:-1]] for _ in p['wind']['cells']],
            admissible=[[True]*(len(knots)-1) for _ in p['wind']['cells']],coverage=['forecast']*(len(knots)-1))
    p['wind']['update_support'] = []
    for j,t in enumerate(knots[:-1]):
        if t<end and alpha:
            p['wind']['received']['values'][1][j] = [wire_rational(-alpha),0]
            p['wind']['update_support'].append([p['wind']['cells'][1]['id'],j])
    from recovery.local_search import digest
    name = 'B_'+template+'_'+digest(dict(severity=str(severity),duration=duration,
        deadline_scale=deadline_scale,battery_slack=battery_slack))[:12]
    p['benchmark_id'] = name
    scenario = Scenario(p)
    library = PathLibrary.build(scenario,nominal_paths=base.library.nominal,return_paths=base.library.returns,direct=False)
    return Case(name,scenario,library,witness_plan=base.witness_plan,witness_reserves=base.witness_reserves)


def rational_number(value):
    return Fraction(str(value))


def wire_rational(value):
    value = Fraction(value)
    return value.numerator if value.denominator == 1 else str(value)


def boundary_record(case,budget):
    start = perf_counter()
    result = recover_local(case.scenario,case.library,**budget)
    search_elapsed = result['effort']['elapsed_s']
    candidates = [(case.scenario.to_dict()['incumbent'],case.scenario.to_dict()['reserve_paths'])]
    if len(case.scenario.data['mission']['tasks'])==3:
        candidates.extend((controlled_case(k).witness_plan,controlled_case(k).witness_reserves) for k in ('C3','C4'))
    if case.witness_plan is not None: candidates.append((case.witness_plan,case.witness_reserves))
    for plan,reserves in candidates:
        checked = verify_local_witness(case.scenario,case.library,plan,reserves,4)
        if checked['accepted'] and checked['exact'] and (result['represented']['upper'] is None or checked['level']<result['represented']['upper']):
            add_witness(result,case.scenario,case.library,plan,reserves,clock_start=start)
    upper = result['full_domain']['upper']
    # Strongest affordable independent physical exclusion, including true infinity.
    for k in range(4 if upper is None else upper-1,-1,-1):
        cert = physical_certificate(case.scenario,k)
        if cert is not None:
            add_physical_certificate(result,case.scenario,cert,clock_start=start)
            break
    result['effort']['method'] = 'bounded search plus fixed template proposals and physical proof checks'
    result['effort']['elapsed_s'] = perf_counter()-start
    result['effort']['supplemental_evidence_s'] = result['effort']['elapsed_s']-search_elapsed
    return result
