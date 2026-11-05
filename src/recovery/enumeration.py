"""Lazy, deterministic enumeration of structurally allowed route skeletons.

None events account for partial expansions, so budgets also bound work before
the first complete plan. A non-None event is (plan, selected return paths).
"""
from itertools import product

from env.geometry import canonical_path
from env.plan import coordinates, remaining_tasks, active_count
from env.scenario import _thaw


def enumerate_events(scenario, library, releases):
    library.validate(scenario)
    d = scenario.data
    old = coordinates(d)
    depot = tuple(d['mission']['depot_xy'])
    sites = {t['id']: tuple(t['position_xy']) for t in d['mission']['tasks']}
    sites['DEPOT'] = depot
    tasks = sorted(remaining_tasks(d))
    vehicles = sorted(d['state']['fleet'])

    def vehicle_routes(uid):
        reference = d['incumbent']['routes'][uid]
        initial = d['state']['fleet'][uid]
        bound = len(reference['stops'])

        def extend(stops, paths, previous, ended):
            h = len(stops)+1
            if h > bound:
                if stops and next((s for s in reversed(stops) if s is not None), 'DEPOT') != 'DEPOT':
                    return
                n = next((i for i,s in enumerate(stops) if s is None),bound)
                if not n and (tuple(initial['position_xy']) != depot or initial['mode'] != 'idle'):
                    return
                route = dict(stops=list(stops), paths=[list(p) for p in paths], deliveries=[], loads=[])
                for i in range(bound+1):
                    for field,a in [('deliveries','x'),('loads','y')]:
                        key = f'{uid}:{i}:{a}'
                        value = 0 if key in releases['L'] else old['L'][key]
                        route[field].append(value)
                yield route
                return
            key = f'{uid}:{h}'
            allowed = [reference['stops'][h-1]] if key not in releases['S'] else [None,'DEPOT',*tasks]
            # Try the incumbent stop first without changing the declared domain.
            allowed = sorted(set(allowed), key=lambda s:(s != reference['stops'][h-1],s is not None,str(s)))
            for stop in allowed:
                yield None
                if ended and stop is not None:
                    continue
                if stop is None and stops and stops[-1] not in (None,'DEPOT'):
                    continue
                if h == bound and stop not in (None,'DEPOT'):
                    continue
                if stop in tasks and stop not in releases['A'] and old['A'][stop] != uid:
                    continue
                xkey,ykey = f'{key}:x',f'{key}:y'
                if stop in (None,'DEPOT') and xkey not in releases['L'] and old['L'][xkey] != 0:
                    continue
                if stop != 'DEPOT' and ykey not in releases['L'] and old['L'][ykey] != 0:
                    continue
                target = depot if stop is None else sites[stop]
                paths_here = ((depot,),) if stop is None else library.paths(previous,target)
                if key not in releases['P']:
                    paths_here = tuple(p for p in paths_here if p == old['P'][key])
                for path in paths_here:
                    yield None
                    yield from extend(stops+[stop],paths+[path],target,ended or stop is None)
        yield from extend([],[],tuple(initial['position_xy']),False)

    def fleet(index, routes, owners):
        if index < len(vehicles):
            uid = vehicles[index]
            for route in vehicle_routes(uid):
                if route is None:
                    yield None
                    continue
                visited = {s for s in route['stops'] if s in tasks}
                if visited.intersection(owners):
                    continue
                yield from fleet(index+1,{**routes,uid:route},{**owners,**{s:uid for s in visited}})
            return
        assignment = {t:owners.get(t) for t in tasks}
        if any(t not in releases['A'] and assignment[t] != old['A'][t] for t in tasks):
            return
        plan = dict(assignment=assignment,routes=routes)
        try:
            plan = _thaw(scenario.validate_candidate(plan))
        except ValueError:
            return
        keys, choices = [], []
        for uid,route in plan['routes'].items():
            n = active_count(route)
            initial = d['state']['fleet'][uid]
            if n or tuple(initial['position_xy']) != depot:
                keys.append((uid,'initial'))
                choices.append(library.paths(initial['position_xy'],depot,reserve=True))
            for h,stop in enumerate(route['stops'][:n],1):
                if stop != 'DEPOT':
                    keys.append((uid,str(h)))
                    choices.append(library.paths(sites[stop],depot,reserve=True))
        for selected in product(*choices):
            yield None
            reserves = {uid:{} for uid in vehicles}
            for (uid,label),path in zip(keys,selected):
                reserves[uid][label] = [list(point) for point in path]
            yield plan,reserves
    yield from fleet(0,{}, {})
