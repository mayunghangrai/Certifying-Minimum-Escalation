"""Exact represented Level 0/1 screen for stationary, uncoupled flight times.

At fixed sequence and quantities, shorter flights cannot increase delivery
times or energy use. Reserve flights are auxiliary choices and can be minimized
independently. This dominance argument applies only under the guards below;
it says nothing about paths absent from the supplied representation.
"""
from env.local_scope import affected_uavs, scope_family
from env.wind_dependency import diagnose_wind_update
from .linear import rational
from .physics import flight_duration, InadmissiblePath, UnsupportedArithmetic
from .transfers import build_transfer_problem, BranchRejected


def _guard(scenario):
    d = scenario.data
    if d['schema_version'] != 'wind-benchmark-v2': return 'requires revised formulation'
    if d['operations']['depot_bays'] is not None: return 'depot preparation is coupled'
    if any(s['mode'] != 'idle' or tuple(s['position_xy']) != tuple(d['mission']['depot_xy'])
           for s in d['state']['fleet'].values()): return 'requires idle depot origins'
    w = d['wind']['received']
    if 'missing' in w['coverage']: return 'incomplete wind'
    if any(not all(row) for row in w['admissible']): return 'requires admissible wind cells'
    if any(any(tuple(map(rational, v)) != tuple(map(rational, row[0])) for v in row) for row in w['values']):
        return 'wind varies in time'
    from .local_search import previous_premise
    if previous_premise(scenario)['exact_feasible'] is not True: return 'prior fixed quantities not exactly feasible'
    return None


def fastest_static_plan(scenario, library, plan, movable, *, cache=None):
    """Minimize nominal and reserve flight times; all alternatives must be exact.

    The caller must check _guard before using failure as an exclusion. This
    helper is also used to propose witnesses, whose feasibility is rechecked.
    """
    from copy import deepcopy
    plan = deepcopy(plan)
    d = scenario.data
    epoch, depot = d['mission']['epoch_h'], d['mission']['depot_xy']
    tasks = {t['id']: t['position_xy'] for t in d['mission']['tasks']}
    cache = {} if cache is None else cache

    def choose(uid, paths):
        key = (uid, tuple(tuple(tuple(p) for p in path) for path in paths))
        if key in cache: return deepcopy(cache[key])
        ranked = []
        for path in paths:
            dt = flight_duration(scenario, uid, path, epoch, exact=True)
            if dt is not None: ranked.append((dt, path))
        if not ranked: raise BranchRejected('no represented flight within horizon', exact=True)
        selected = [list(p) for p in min(ranked)[1]]
        cache[key] = selected
        return deepcopy(selected)

    reserves = {}
    for uid, route in plan['routes'].items():
        point = d['state']['fleet'][uid]['position_xy']
        reserves[uid] = {}
        active = [s for s in route['stops'] if s is not None]
        if active:
            reserves[uid]['initial'] = choose(uid, library.paths(point, depot, reserve=True))
        for h, site in enumerate(active, 1):
            end = depot if site == 'DEPOT' else tasks[site]
            if f'{uid}:{h}' in movable:
                route['paths'][h-1] = choose(uid, library.paths(point, end))
            else:
                # Certifying a dominated plan requires exact fixed flight times too.
                route['paths'][h-1] = choose(uid, [route['paths'][h-1]])
            if site != 'DEPOT':
                reserves[uid][str(h)] = choose(uid, library.paths(end, depot, reserve=True))
            point = end
    return plan, reserves


def static_path_screen(scenario, library, level):
    if isinstance(level, bool) or level not in (0, 1): raise ValueError('static screen supports Levels 0 and 1')
    library.validate(scenario)
    reason = _guard(scenario)
    if reason: return dict(status='UNRESOLVED', reason=reason)
    from .local_search import digest
    u0 = affected_uavs(scenario, diagnose_wind_update(scenario))['uavs']
    patch = scope_family(scenario, level, u0)[0]
    try:
        plan, reserves = fastest_static_plan(scenario, library, scenario.to_dict()['incumbent'], patch.releases['P'])
        compiled = build_transfer_problem(scenario, plan, reserves, patch.releases, exact=True)
        if compiled.problem.variables: raise ValueError('fixed-quantity screen has variables')
        if compiled.problem.accepts(()):
            return dict(status='WITNESS', plan=plan, reserves=reserves)
        failure = dict(kind='constant_constraint', labels=[r.label for r in compiled.problem.rows if r.bound < 0],
                       plan_hash=digest(plan), reserve_hash=digest(reserves))
    except BranchRejected as error:
        if not error.exact: return dict(status='UNRESOLVED', reason=str(error))
        failure = dict(kind='exact_branch_rejection', reason=str(error))
    except (UnsupportedArithmetic, InadmissiblePath) as error:
        return dict(status='UNRESOLVED', reason=str(error))
    certificate = dict(kind='static_path_dominance_v1', domain='represented', level=level,
                       scenario_hash=scenario.content_hash(), library_hash=library.content_hash(), failure=failure)
    return dict(status='EMPTY', certificate=certificate)


def verify_static_certificate(scenario, library, certificate):
    try:
        if certificate['kind'] != 'static_path_dominance_v1' or certificate['domain'] != 'represented': return False
        replay = static_path_screen(scenario, library, certificate['level'])
        return replay['status'] == 'EMPTY' and replay['certificate'] == certificate
    except (KeyError, ValueError, TypeError, ArithmeticError):
        return False
