"""Small hand-specified examples; no production route search."""
import copy

from test_benchmark_contract import raw


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


def permutation(p, recipients):
    candidate = copy.deepcopy(p['incumbent'])
    paths = copy.deepcopy(p['reserve_paths'])
    for i, recipient in enumerate(recipients,1):
        u = f'U{i}'; task = f'T{recipient}'; point = [1 if recipient < 3 else -1,0]
        candidate['assignment'][task] = u
        candidate['routes'][u]['stops'][0] = task
        candidate['routes'][u]['paths'] = [[[0,0],point],[point,[0,0]]]
        paths[u]['1'] = [point,[0,0]]
    return candidate, paths


def diagnostic_cases():
    irrelevant = worked('B')
    irrelevant['wind']['time_knots_h'] = [0.,3.,4.]
    irrelevant['wind']['previous']['values'] = [[[0.,0.],[0.,0.]],[[0.,0.],[0.,0.]]]
    irrelevant['wind']['received']['values'] = [[[0.,0.],[0.,0.]],[[0.,0.],[-.5,0.]]]
    irrelevant['wind']['update_support'] = [['east',1]]
    symmetric = worked('B')
    symmetric['wind']['previous']['values'][1][0] = [0.,.2]
    symmetric['wind']['received']['values'][1][0] = [0.,-.2]
    shifted = worked('B')
    shifted['wind']['time_knots_h'] = [0.,1.5,4.]
    shifted['wind']['previous']['values'] = [[[0.,0.],[0.,0.]],[[0.,0.],[0.,0.]]]
    shifted['wind']['received']['values'] = [[[0.,0.],[0.,0.]],[[-.5,0.],[-.5,0.]]]
    shifted['wind']['update_support'] = [['east',0],['east',1]]
    reserve_only = worked('B')
    reserve_only['mission']['tasks'] = reserve_only['mission']['tasks'][:1]
    reserve_only['mission']['vehicles'] = reserve_only['mission']['vehicles'][:1]
    reserve_only['state']['fleet'] = {'U1': reserve_only['state']['fleet']['U1']}
    reserve_only['state']['cumulative_delivered'] = {'T1':0.}
    reserve_only['incumbent']['routes'] = {'U1':reserve_only['incumbent']['routes']['U1']}
    reserve_only['incumbent']['assignment'] = {'T1':'U1'}
    reserve_only['commitments'] = {a:[k for k in keys if k.startswith('U1:')] for a,keys in reserve_only['commitments'].items()}
    reserve_only['reserve_paths'] = {'U1':{'initial':[[0,0]],'1':[[1,0],[-1,0],[0,0]]}}
    reserve_only['wind']['received']['values'] = [[[-.5,0.]],[[0.,0.]]]
    reserve_only['wind']['update_support'] = [['WEST',0]]
    cases = dict(irrelevant_wind=irrelevant, unchanged_speed=symmetric,
                 shifted_bins=shifted, reserve_only=reserve_only,
                 downstream=raw(), late_undefined=raw('horizon_late'))
    for name, p in cases.items(): p['benchmark_id'] = name
    return cases
