"""Deterministic one-factor sweeps, separate from the pinned source fixtures."""
from copy import deepcopy
import json

from env.scenario import Scenario
from recovery.representation import PathLibrary


def _divisible(base):
    p = deepcopy(base)
    p['mission']['tasks'] = [dict(id='T1',position_xy=[1,0],demand=.75,mandatory=.75,deadline_h=2.3),
                             dict(id='T2',position_xy=[1,0],demand=.5,mandatory=.5,deadline_h=3)]
    p['mission']['vehicles'] = [p['mission']['vehicles'][0]]
    p['mission']['vehicles'][0].update(slot_bound=3,payload_capacity_kg=2)
    p['state']['fleet'] = {'U1':p['state']['fleet']['U1']}
    p['state']['depot_stock'] = 1.25
    p['state']['cumulative_delivered'] = dict(T1=0,T2=0)
    p['operations']['service_duration_h'] = .2
    p['incumbent'] = dict(assignment=dict(T1='U1',T2='U1'),routes=dict(U1=dict(
        stops=['T2','T1','DEPOT'],paths=[[[0,0],[1,0]],[[1,0]],[[1,0],[0,0]]],
        loads=[1.25,0,0,0],deliveries=[0,.5,.75,0])))
    p['reserve_paths'] = dict(U1={'initial':[[0,0]],'1':[[1,0],[0,0]],'2':[[1,0],[0,0]]})
    p['commitments'] = dict(A=[],S=['U1:3'],P=[],L=[])
    return p


def _bypass(base):
    p = deepcopy(base)
    p['benchmark_id'] = 'controlled_bypass'
    p['mission'].update(horizon_h=3,operating_region_xy=[[-1,-1],[3,-1],[3,3],[-1,3]])
    p['mission']['tasks'] = [dict(id='T1',position_xy=[2,0],demand=1,mandatory=1,deadline_h=.75)]
    p['mission']['vehicles'] = [p['mission']['vehicles'][0]]
    p['mission']['vehicles'][0]['airspeed_kmh'] = 5
    p['state']['fleet'] = {'U1':p['state']['fleet']['U1']}
    p['state']['depot_stock'] = 1
    p['state']['cumulative_delivered'] = dict(T1=0)
    p['incumbent'] = dict(assignment=dict(T1='U1'),routes=dict(U1=dict(stops=['T1','DEPOT'],
        paths=[[[0,0],[2,0]],[[2,0],[0,0]]],loads=[1,0,0],deliveries=[0,1,0])))
    p['reserve_paths'] = dict(U1={'initial':[[0,0]],'1':[[2,0],[0,0]]})
    p['commitments'] = dict(A=[],S=['U1:2'],P=[],L=[f'U1:{h}:{a}' for h in range(3) for a in ('x','y')])
    p['wind'].update(cells=[
        dict(id='EAST_LOW',polygon_xy=[[0,-1],[3,-1],[3,.25],[0,.25]]),
        dict(id='WEST_LOW',polygon_xy=[[-1,-1],[0,-1],[0,.25],[-1,.25]]),
        dict(id='UPPER',polygon_xy=[[-1,.25],[3,.25],[3,3],[-1,3]])],
        time_knots_h=[0,3],speed_bound_kmh=3.5,update_support=[['EAST_LOW',0]])
    p['wind']['previous']['values'] = [[[0,0]],[[0,0]],[[0,0]]]
    p['wind']['received']['values'] = [[[-3,0]],[[0,0]],[[0,0]]]
    return p


def _library(scenario, count, bypass=False):
    extra = []
    if bypass:
        extra = [[[0,0],[0,h],[2,h],[2,0]] for h in (.5,1,1.5)[:count-1]]
    else:
        depot = list(scenario.data['mission']['depot_xy'])
        points = sorted({tuple(t['position_xy']) for t in scenario.data['mission']['tasks']})
        for fraction in (.25,.5)[:count-1]:
            for point in points:
                extra.append([depot,[d+fraction*(v-d) for d,v in zip(depot,point)],depot,list(point)])
    return PathLibrary.build(scenario,nominal_paths=extra)


def build_instances(root):
    """Return 88 labeled conditions; duplicates are explicit within-sweep controls."""
    bases = {name:json.loads((root/'scenarios'/'worked'/f'four_uav_case_{name.lower()}.json').read_text(encoding='utf-8'))
             for name in ('A','B')}
    bases['divisible'] = _divisible(bases['B'])
    result = []

    def add(family,factor,value,p,count=1):
        s = Scenario.from_dict(p)
        lib = _library(s,count,bypass=family=='bypass')
        result.append(dict(id=f'{family}/{factor}/{value}',family=family,factor=factor,value=value,
                           scenario=s.to_dict(),representation=lib.to_dict()))

    for family,base in bases.items():
        base['benchmark_id'] = f'controlled_{family.lower()}'
        base['wind']['speed_bound_kmh'] = .875
        for magnitude in (0,.125,.25,.375,.5,.625,.75):
            p = deepcopy(base)
            p['wind']['received']['values'][1] = [[-float(magnitude),0.0]]
            p['wind']['update_support'] = [['east',0]] if magnitude else []
            add(family,'wind_magnitude',magnitude,p)
        for bins in range(4):
            p = deepcopy(base)
            p['wind']['time_knots_h'] = [0,1,2,4]
            p['wind']['previous']['values'] = [[[0,0] for _ in range(3)] for _ in range(2)]
            p['wind']['received']['values'] = [[[0,0] for _ in range(3)],
                                               [[-.5,0] if j<bins else [0,0] for j in range(3)]]
            p['wind']['update_support'] = [['east',j] for j in range(bins)]
            add(family,'wind_duration',bins,p)
        deadlines = (1.4,1.5,2,2.2,2.3,2.4,3) if family=='divisible' else (1,1.25,1.5,1.75,2,2.5,3)
        for deadline in deadlines:
            p = deepcopy(base)
            p['mission']['tasks'][0]['deadline_h'] = float(deadline)
            add(family,'deadline',deadline,p)
        capacities = (1.4,1.45,1.5,1.55,1.6,2,10) if family=='divisible' else (1.3,1.35,1.4,1.45,1.5,2,10)
        for capacity in capacities:
            p = deepcopy(base)
            for vehicle in p['mission']['vehicles']:
                vehicle['battery_capacity_wh'] = float(capacity)
                p['state']['fleet'][vehicle['id']]['battery_wh'] = float(capacity)
            add(family,'battery',capacity,p)
        for count in (1,2,3):
            add(family,'paths',count,base,count)
    for count in (1,2,3,4):
        add('bypass','paths',count,_bypass(bases['B']),count)
    return result
