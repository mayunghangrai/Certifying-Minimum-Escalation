"""Hand-written fixtures copied from the archived v2 tests (archive/v2_2026_11_09/tests).

`raw` is from test_benchmark_contract.py, `worked` from recovery_cases.py and `revised` from
test_final_scope.py, copied verbatim. Only FIXTURES changed: it points at tests/fixtures.
"""
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / 'fixtures'


def raw(name='local_delay'):
    return json.loads((FIXTURES / f'{name}.json').read_text(encoding='utf-8'))


def worked(case='A'):
    p = raw()
    p['benchmark_id'] = f'four_uav_case_{case.lower()}'
    p['mission'] = {
        'epoch_h': 0., 'horizon_h': 4., 'commodity_unit_mass_kg': 1.,
        'operating_region_xy': [[-1,-1],[1,-1],[1,1],[-1,1]], 'depot_xy': [0,0],
        'tasks': [dict(id=f'T{i}', position_xy=[1 if i < 3 else -1,0],
                       demand=1., mandatory=1., deadline_h=1.5 if i == 1 else 3.)
                  for i in range(1,5)],
        'vehicles': [dict(id=f'U{i}', airspeed_kmh=2. if i == 2 else 1.,
                          empty_mass_kg=1., energy_coefficient_wh_per_kg_km=.1,
                          battery_capacity_wh=10., reserve_wh=1.,
                          payload_capacity_kg=1., slot_bound=2) for i in range(1,5)]}
    p['state'] = dict(depot_stock=4., cumulative_delivered={f'T{i}':0. for i in range(1,5)},
                      fleet={f'U{i}': dict(position_xy=[0,0], battery_wh=10., onboard=0.,
                                          mode='idle', residual_operation=None) for i in range(1,5)})
    p['operations'] = dict(service_duration_h=0., service_energy_wh=0.,
                           preparation_duration_h=0., depot_bays=None)
    p['wind'] = dict(cells=[
        dict(id='WEST', polygon_xy=[[-1,-1],[0,-1],[0,1],[-1,1]]),
        dict(id='east', polygon_xy=[[0,-1],[1,-1],[1,1],[0,1]])],
        boundary_owner='lowest_cell_id', time_knots_h=[0.,4.], speed_bound_kmh=.6,
        previous=dict(issued_at_h=0., values=[[[0.,0.]],[[0.,0.]]]),
        received=dict(issued_at_h=0., values=[[[0.,0.]],[[-.5,0.]]]),
        update_support=[['east',0]])
    p['incumbent'] = dict(assignment={f'T{i}':f'U{i}' for i in range(1,5)}, routes={})
    p['reserve_paths'] = {}
    p['commitments'] = {a:[] for a in ('A','S','P','L')}
    for i in range(1,5):
        u = f'U{i}'; point = [1 if i < 3 else -1,0]
        p['incumbent']['routes'][u] = dict(stops=[f'T{i}','DEPOT'],
            paths=[[[0,0],point],[point,[0,0]]], loads=[1.,0.,0.], deliveries=[0.,1.,0.])
        p['reserve_paths'][u] = {'initial':[[0,0]], '1':[point,[0,0]]}
        p['commitments']['S'].append(f'{u}:2')
        p['commitments']['L'].extend(f'{u}:{h}:{a}' for h in range(3) for a in ('x','y'))
        if case == 'A': p['commitments']['P'].extend((f'{u}:1', f'{u}:2'))
    return p


def revised():
    p = worked('B')
    p.update(schema_version='wind-benchmark-v2', formulation_date='2026-09-30',
             hierarchy={'helper_budget': 1, 'affected_set_rule': 'directed_incumbent_union'})
    n = len(p['wind']['time_knots_h'])-1
    for projection in ('previous', 'received'):
        p['wind'][projection]['admissible'] = [[True]*n for _ in p['wind']['cells']]
        p['wind'][projection]['coverage'] = ['forecast']*n
    return p
