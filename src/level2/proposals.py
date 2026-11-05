"""Bounded numerical route proposals; only full exact search can certify them.

The per-UAV LP drops inventory and all rows involving other UAVs. Its result
only orders a search path. It never excludes any part of the route domain.
"""
from itertools import permutations
from time import perf_counter

from continuous.oracle import verify_query
from continuous.physics import stationary_duration, stationary_guard
from env.plan import active_count
from recovery.transfers import build_transfer_problem, BranchRejected
from .skeletons import SkeletonDomain


def propose_routes(scenario, *, initial_bounds=(), max_candidates=1000, max_seconds=60, digits=18):
    from scipy.optimize import linprog
    start = perf_counter()
    report = dict(prefix=None, attempts=0, elapsed_s=0., routes={})
    if stationary_guard(scenario):
        return report
    domain = SkeletonDomain(scenario)
    data = scenario.data
    depot = list(data['mission']['depot_xy'])
    tasks = {t['id']: t for t in data['mission']['tasks']}
    paths, durations = {}, {}
    for query in initial_bounds:
        if not verify_query(scenario, query, digits):
            raise ValueError('invalid proposal seed')
        paths[query['uid'], tuple(query['start']), tuple(query['goal'])] = query['path']

    def duration(uid, path, time):
        key = uid, tuple(map(tuple, path))
        if key not in durations:
            durations[key] = stationary_duration(scenario, uid, path, digits)[1]
        return durations[key]

    def prefix_for(routes):
        prefix = []
        for uid in sorted(domain.fleet):
            route = routes.get(uid, list(data['incumbent']['routes'][uid]['stops']))
            prefix.extend([*route, *([None]*(domain.fleet[uid]['slot_bound']-len(route)))])
        return prefix

    def carriers(plan):
        reserves = {}
        for uid, route in plan['routes'].items():
            previous = depot
            reserves[uid] = {'initial': [depot]}
            for h, site in enumerate(route['stops'][:active_count(route)], 1):
                goal = depot if site == 'DEPOT' else list(tasks[site]['position_xy'])
                if f'{uid}:{h}' in domain.patch.releases['P']:
                    route['paths'][h-1] = paths.get((uid, tuple(previous), tuple(goal)), [previous, goal])
                if site != 'DEPOT':
                    reserves[uid][str(h)] = paths.get((uid, tuple(goal), tuple(depot)), [goal, depot])
                previous = goal
        return reserves

    for uid in sorted(domain.fleet):
        if uid not in domain.patch.participants:
            report['routes'][uid] = list(data['incumbent']['routes'][uid]['stops'])
            continue
        found = None
        ordered = sorted(domain.assigned[uid], key=lambda t: (tasks[t]['deadline_h']
                         if tasks[t]['deadline_h'] is not None else float('inf'), t))
        for sequence in permutations(ordered):
            if found is not None:
                break
            for mask in range(1 << max(0, len(sequence)-1)):
                if report['attempts'] >= max_candidates or perf_counter()-start >= max_seconds:
                    report['elapsed_s'] = perf_counter()-start
                    return report
                route = []
                for j, site in enumerate(sequence):
                    route.append(site)
                    if j < len(sequence)-1 and mask & (1 << j):
                        route.append('DEPOT')
                route.append('DEPOT')
                if len(route) > domain.fleet[uid]['slot_bound']:
                    continue
                prefix = prefix_for({**report['routes'], uid: route})
                if domain.reject(prefix):
                    continue
                report['attempts'] += 1
                try:
                    plan = domain.skeleton(prefix)
                    reserves = carriers(plan)
                    compiled = build_transfer_problem(scenario, plan, reserves, domain.patch.releases,
                                                       exact=True, duration_provider=duration)
                    indices = [j for j, c in enumerate(compiled.columns) if c[0] == uid]
                    if not indices:
                        continue
                    rows = []
                    for row in compiled.problem.rows:
                        support = {compiled.columns[j][0] for j, a in enumerate(row.coefficients) if a}
                        if row.label == 'inventory':
                            continue
                        if support == {uid} or (not support and
                                (':'+uid+':' in row.label or row.label.endswith(':'+uid))):
                            rows.append(row)
                    answer = linprog([0.]*len(indices),
                        A_ub=[[float(row.coefficients[j]) for j in indices] for row in rows],
                        b_ub=[float(row.bound) for row in rows], bounds=(None, None), method='highs')
                    if answer.success:
                        found = route
                        break
                except (ValueError, ArithmeticError, BranchRejected):
                    continue
        if found is None:
            report['elapsed_s'] = perf_counter()-start
            return report
        report['routes'][uid] = found
    report['prefix'] = prefix_for(report['routes'])
    report['elapsed_s'] = perf_counter()-start
    return report
