"""Common remaining-plan domain: fixed coordinates, padding and commitments."""
from __future__ import annotations

from .geometry import canonical_path, polygon, validate_path


COMPONENTS = ('A', 'S', 'P', 'L')


def coordinates(data, plan=None):
    plan = data['incumbent'] if plan is None else plan
    result = {a: {} for a in COMPONENTS}
    result['A'].update(plan['assignment'])
    for u, route in plan['routes'].items():
        for h, (stop, path) in enumerate(zip(route['stops'], route['paths']), 1):
            result['S'][f'{u}:{h}'] = stop
            result['P'][f'{u}:{h}'] = canonical_path(path)
        for h, (x, y) in enumerate(zip(route['deliveries'], route['loads'])):
            result['L'][f'{u}:{h}:x'] = x
            result['L'][f'{u}:{h}:y'] = y
    return result


def active_count(route):
    return next((h for h, s in enumerate(route['stops']) if s is None), len(route['stops']))


def remaining_tasks(data):
    return {i['id'] for i in data['mission']['tasks'] if i['demand'] > data['state']['cumulative_delivered'][i['id']]}


def validate_plan(data, plan, *, enforce_commitments=True):
    """Validate Y only. Resource/time feasibility is a separate evaluation."""
    mission, state = data['mission'], data['state']
    tasks = {i['id']: i for i in mission['tasks']}
    fleet = {u['id']: u for u in mission['vehicles']}
    if set(plan['assignment']) != remaining_tasks(data) or set(plan['routes']) != set(fleet):
        raise ValueError('plan must represent every remaining task and every UAV')
    if any(a is not None and a not in fleet for a in plan['assignment'].values()):
        raise ValueError('unknown assignment UAV')
    region = polygon(mission['operating_region_xy'])
    depot = tuple(mission['depot_xy'])
    visits = {i: set() for i in remaining_tasks(data)}
    for u, route in plan['routes'].items():
        bound, observed = fleet[u]['slot_bound'], state['fleet'][u]
        if any(len(route[k]) != bound for k in ('stops', 'paths')) or any(len(route[k]) != bound+1 for k in ('deliveries', 'loads')):
            raise ValueError('plan coordinate dimensions differ from fixed slot bounds')
        n = active_count(route)
        if any(s is not None for s in route['stops'][n:]):
            raise ValueError('active stops must form a prefix')
        if n and route['stops'][n-1] != 'DEPOT':
            raise ValueError('active route must terminate at depot')
        if not n and (tuple(observed['position_xy']) != depot or observed['mode'] != 'idle'):
            raise ValueError('zero-slot route requires an idle UAV at depot')
        if route['deliveries'][0] != 0 or route['loads'][n] != 0:
            raise ValueError('initial delivery and terminal loading must be zero')
        depot_origin = tuple(observed['position_xy']) == depot and observed['mode'] in ('idle', 'preparing')
        if not depot_origin and route['loads'][0] != 0:
            raise ValueError('initial loading requires an available ground depot origin')
        prev = tuple(observed['position_xy'])
        for h, stop in enumerate(route['stops'], 1):
            x, y = route['deliveries'][h], route['loads'][h]
            if h > n:
                if x != 0 or y != 0 or canonical_path(route['paths'][h-1]) != (depot,):
                    raise ValueError('inactive coordinates require canonical depot padding and zero transfers')
                continue
            if stop != 'DEPOT' and stop not in visits:
                raise ValueError('visit must identify a remaining task or depot')
            point = depot if stop == 'DEPOT' else tuple(tasks[stop]['position_xy'])
            validate_path(route['paths'][h-1], region, prev, point)
            if stop == 'DEPOT':
                if x != 0:
                    raise ValueError('delivery requires a relief site')
            else:
                if y != 0:
                    raise ValueError('loading requires a depot')
                visits[stop].add(u)
            prev = point
        residual = observed['residual_operation']
        if observed['mode'] == 'servicing':
            if n == 0 or route['stops'][0] == 'DEPOT' or tuple(tasks[route['stops'][0]]['position_xy']) != tuple(observed['position_xy']):
                raise ValueError('pending service needs a leading visit at its observed site')
            if canonical_path(route['paths'][0]) != (tuple(observed['position_xy']),):
                raise ValueError('pending service incoming path must be constant')
            if route['deliveries'][1] != residual['delivery'] or residual['load'] != 0:
                raise ValueError('pending service must use only its residual transfer')
            required = {'S': [f'{u}:1'], 'P': [f'{u}:1'], 'L': [f'{u}:1:x']}
            if any(not set(labels) <= set(data['commitments'][a]) for a, labels in required.items()):
                raise ValueError('residual service coordinates must be committed')
        if observed['mode'] == 'preparing':
            if not n or tuple(observed['position_xy']) != depot or route['loads'][0] != residual['load'] or residual['delivery'] != 0 or residual['energy_wh'] != 0:
                raise ValueError('pending preparation must use its residual depot load')
            if f'{u}:0:y' not in data['commitments']['L']:
                raise ValueError('residual loading coordinate must be committed')
    for i, owners in visits.items():
        owner = plan['assignment'][i]
        if owners != (set() if owner is None else {owner}):
            raise ValueError('assignment must match every visit and cannot split a task across UAVs')
    values = coordinates(data, plan)
    reference = coordinates(data)
    for a in COMPONENTS:
        if not set(data['commitments'][a]) <= set(reference[a]):
            raise ValueError('commitment names an unknown coordinate')
        if enforce_commitments and any(values[a][key] != reference[a][key] for key in data['commitments'][a]):
            raise ValueError('candidate changes a committed coordinate')
