"""Exhaustive Level-2 route-slot search with an explicit auditable frontier.

Exhaustive describes the enumerated domain. Finite budgets and continuous path
gaps can leave it unresolved; failed numerical proposals never exclude a leaf.
"""
from copy import deepcopy
from fractions import Fraction
from itertools import product
import math
from time import perf_counter

from continuous.oracle import ContinuousOracle, verify_query
from continuous.physics import depot_origin, stationary_guard
from env.plan import active_count
from .bounds import prefix_exclusion
from .quantities import evaluate_quantities
from .skeletons import SkeletonDomain


class _Limit(Exception):
    pass


def search_level2(scenario, *, max_seconds=60, max_nodes=100000, refinements=(2, 4),
                  digits=18, initial_bounds=(), max_operations=100000, max_rows=10000,
                  preferred_prefix=None):
    """Legacy Level-2 entry point; preserve its proof version and record schema."""
    return _search(scenario, max_seconds=max_seconds, max_nodes=max_nodes,
                   refinements=refinements, digits=digits, initial_bounds=initial_bounds,
                   max_operations=max_operations, max_rows=max_rows, preferred_prefix=preferred_prefix)


def search_sequence(scenario, assignment, patch, *, scope_level=3, oracle=None,
                    max_seconds=60, max_nodes=100000, refinements=(2, 4),
                    digits=18, initial_bounds=(), max_operations=100000, max_rows=10000):
    """Search every slot skeleton for a chosen assignment in its original mask.

    The scenario is never rebased to the candidate. An injected oracle owns a
    local evidence view; only that view's cache is attached to this proof.
    """
    if assignment is None or patch is None:
        raise ValueError('explicit assignment and permitted scope patch are required together')
    return _search(scenario, assignment=assignment, patch=patch, scope_level=scope_level, oracle=oracle,
                   max_seconds=max_seconds, max_nodes=max_nodes, refinements=refinements,
                   digits=digits, initial_bounds=initial_bounds,
                   max_operations=max_operations, max_rows=max_rows)


def _search(scenario, *, assignment=None, patch=None, scope_level=3, oracle=None,
            max_seconds=60, max_nodes=100000, refinements=(2, 4),
            digits=18, initial_bounds=(), max_operations=100000, max_rows=10000,
            preferred_prefix=None):
    if (isinstance(max_seconds, bool) or not math.isfinite(max_seconds) or max_seconds < 0
            or isinstance(max_nodes, bool) or not isinstance(max_nodes, int) or max_nodes < 0):
        raise ValueError('invalid Level-2 budget')
    start = perf_counter()
    explicit = assignment is not None or patch is not None
    domain = SkeletonDomain(scenario, assignment=assignment, patch=patch, scope_level=scope_level)
    if preferred_prefix is not None:
        if not domain.complete(preferred_prefix) or domain.reject(preferred_prefix):
            raise ValueError('preferred prefix must be a complete permitted skeleton')
        preferred_prefix = list(preferred_prefix)
    report = dict(version='sequence_exhaustive_v1' if explicit else 'level2_exhaustive_v1',
                  domain='all_admissible_continuous_polylines',
                  scenario_hash=scenario.content_hash(), digits=digits,
                  unsupported=stationary_guard(scenario), affected=list(domain.affected),
                  leg_bounds=[], nodes=[dict(prefix=[], kind='open', reason='search budget')], root=0,
                  status='UNRESOLVED', witness=None,
                  budget=dict(max_seconds=max_seconds, max_nodes=max_nodes,
                              refinements=list(refinements), max_operations=max_operations, max_rows=max_rows),
                  effort=dict(visited=0, structural=0, resource=0, quantity=0, complete_skeletons=0,
                              geometry_open=0, budget_exhausted=False, elapsed_s=0.))
    if explicit:
        report.update(assignment=dict(domain.assignment), patch=domain.patch.to_dict())
        if scope_level == 4:
            report['scope_level'] = 4
    effort = report['effort']
    if report['unsupported']:
        effort['elapsed_s'] = perf_counter()-start
        return report
    if oracle is None:
        oracle = ContinuousOracle(scenario, refinements, digits)
    lower = {}
    d = scenario.data
    depot = tuple(d['mission']['depot_xy'])
    tasks = {t['id']: tuple(t['position_xy']) for t in d['mission']['tasks']}
    warm = {uid: [*d['incumbent']['routes'][uid]['paths'], *d['reserve_paths'].get(uid, {}).values()]
            for uid in d['state']['fleet']}
    # A ground depot origin departs from the depot; an airborne origin from its observed position.
    origin = {uid: depot if depot_origin(scenario, uid) else tuple(s['position_xy'])
              for uid, s in d['state']['fleet'].items()}

    def check():
        if perf_counter()-start >= max_seconds or effort['visited'] >= max_nodes:
            effort['budget_exhausted'] = True
            raise _Limit()

    def query(uid, a, b):
        check()
        result = oracle.query(uid, a, b, warm[uid], bound=True)
        lower[uid, tuple(a), tuple(b)] = Fraction(result['lower'])
        return result

    def prequery(uid, a, b):
        # An oracle proposal failure leaves the valid zero lower bound. It
        # cannot remove an endpoint pair from the continuous path domain.
        try:
            query(uid, a, b)
        except (ValueError, ArithmeticError):
            pass

    def reserves_for(plan):
        reserves = {}
        for uid, route in plan['routes'].items():
            n = active_count(route)
            reserves[uid] = {'initial': [list(depot)]} if n else {}
            if n and origin[uid] != depot:
                reserves[uid]['initial'] = query(uid, origin[uid], depot)['path']
            for h, site in enumerate(route['stops'][:n], 1):
                if site != 'DEPOT':
                    reserves[uid][str(h)] = query(uid, tasks[site], depot)['path']
        return reserves

    def evaluate(prefix):
        plan = domain.skeleton(prefix)
        # All-path bounds do not require a particular chord to be admissible.
        # Admissible oracle paths are only carriers for the existing compiler.
        for uid, route in plan['routes'].items():
            previous = origin[uid]
            for h, site in enumerate(route['stops'][:active_count(route)], 1):
                goal = depot if site == 'DEPOT' else tasks[site]
                if f'{uid}:{h}' in domain.patch.releases['P']:
                    route['paths'][h-1] = query(uid, previous, goal)['path']
                previous = goal
        reserves = reserves_for(plan)
        result = evaluate_quantities(scenario, plan, reserves, domain.patch.releases,
            lower_durations=lower, digits=digits, max_operations=max_operations, max_rows=max_rows)
        if result['status'] == 'EMPTY':
            effort['quantity'] += 1
            return dict(kind='quantity', plan=plan, reserve_paths=reserves, proof=result['proof'])
        check()
        result = evaluate_quantities(scenario, plan, reserves, domain.patch.releases,
            digits=digits, max_operations=max_operations, max_rows=max_rows)
        if result['status'] == 'WITNESS' and result.get('witness'):
            report['witness'] = result['witness']
            return dict(kind='witness', witness=result['witness'])
        effort['geometry_open'] += 1
        return dict(kind='open', reason='continuous geometry or rational quantity gap')

    try:
        check()
        for result in initial_bounds:
            if not verify_query(scenario, result, digits):
                raise ValueError('invalid supplied continuous bound')
            key = result['uid'], tuple(result['start']), tuple(result['goal'])
            if key not in oracle.cache or Fraction(result['lower']) > Fraction(oracle.cache[key]['lower']):
                oracle.cache[key] = deepcopy(result)
                lower[key] = Fraction(result['lower'])
        # Depot-to-task bounds can eliminate whole sequence domains before
        # branching. Other directed pairs remain relevant for repeated visits.
        for uid in sorted(domain.patch.participants):
            for site in domain.assigned[uid]:
                prequery(uid, origin[uid], tasks[site])
                proof = prefix_exclusion(scenario, domain, [], lower, digits=digits)
                if proof:
                    report['nodes'][0] = dict(prefix=[], kind='resource', proof=proof)
                    effort['resource'] += 1
                    break
            if report['nodes'][0]['kind'] == 'resource':
                break
        if report['nodes'][0]['kind'] != 'resource':
            for uid in sorted(domain.patch.participants):
                points = [depot, *[tasks[t] for t in domain.assigned[uid]]]
                for a, b in product(points, repeat=2):
                    if a != b:
                        prequery(uid, a, b)
                if origin[uid] != depot:
                    for b in points:
                        if b != origin[uid]:
                            prequery(uid, origin[uid], b)
            stack = [0]
            while stack:
                check()
                index = stack.pop()
                node = report['nodes'][index]
                prefix = node['prefix']
                effort['visited'] += 1
                reason = domain.reject(prefix)
                if reason:
                    node.update(kind='structural', reason=reason)
                    effort['structural'] += 1
                    continue
                proof = prefix_exclusion(scenario, domain, prefix, lower, digits=digits)
                if proof:
                    node.pop('reason', None)
                    node.update(kind='resource', proof=proof)
                    effort['resource'] += 1
                    continue
                if domain.complete(prefix):
                    effort['complete_skeletons'] += 1
                    node.pop('reason', None)
                    # An interrupted leaf stays explicit in the coverage tree.
                    try:
                        node.update(evaluate(prefix))
                    except (ValueError, ArithmeticError) as error:
                        node.update(kind='open', reason='path/quantity evaluation: '+str(error))
                        effort['geometry_open'] += 1
                    if report['witness']:
                        break
                    continue
                choices = domain.children(prefix)
                children = []
                for site in choices:
                    children.append(len(report['nodes']))
                    report['nodes'].append(dict(prefix=[*prefix, site], kind='open', reason='search budget'))
                node.pop('reason', None)
                node.update(kind='branch', children=children)
                # Try earliest-deadline tasks first; every alternative remains
                # in children, including repeats, depot stops and inactivity.
                deadline = {t['id']: t['deadline_h'] if t['deadline_h'] is not None else math.inf
                            for t in d['mission']['tasks']}
                ranked = sorted(children, key=lambda j: (deadline.get(report['nodes'][j]['prefix'][-1], math.inf),
                                                         str(report['nodes'][j]['prefix'][-1])))
                if preferred_prefix is not None and prefix == preferred_prefix[:len(prefix)]:
                    preferred = preferred_prefix[len(prefix)]
                    ranked.sort(key=lambda j: report['nodes'][j]['prefix'][-1] != preferred)
                stack.extend(reversed(ranked))
    except _Limit:
        for node in report['nodes']:
            if node['kind'] == 'open' and 'reason' not in node:
                node['reason'] = 'search budget'
    report['leg_bounds'] = list(deepcopy(oracle.cache).values())
    if report['witness']:
        report['status'] = 'WITNESS'
    elif not any(n['kind'] == 'open' for n in report['nodes']):
        report['status'] = 'EMPTY'
    effort['oracle'] = deepcopy(oracle.effort)
    effort['elapsed_s'] = perf_counter()-start
    return report
