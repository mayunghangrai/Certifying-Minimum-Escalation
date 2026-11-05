"""Five nested coordinate-release spaces, independent of mission feasibility."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from .plan import COMPONENTS, coordinates, remaining_tasks


def potential_task_slots(scenario):
    """Necessary structural conditions only; never prune using feasibility/slack.

    Committed adjacent path endpoints can restrict recipient identities while
    leaving co-located tasks interchangeable. Other domain restrictions may
    further shrink these supersets, which is safe for constraint attribution.
    """
    data = scenario.data
    tasks = {t['id']:tuple(t['position_xy']) for t in data['mission']['tasks']
             if t['id'] in remaining_tasks(data)}
    commitments, plan = data['commitments'], data['incumbent']
    result = {}
    for uid,route in plan['routes'].items():
        bound = len(route['stops'])
        for h in range(1,bound+1):
            key = f'{uid}:{h}'
            possible = {i for i in tasks if i not in commitments['A'] or plan['assignment'][i] == uid}
            if h == bound or (f'{key}:y' in commitments['L'] and route['loads'][h] > 0):
                possible.clear()  # Last slot cannot be a relief visit.
            if key in commitments['S']:
                possible &= {route['stops'][h-1]}
            if key in commitments['P']:
                possible = {i for i in possible if tasks[i] == tuple(route['paths'][h-1][-1])}
            if h < bound and f'{uid}:{h+1}' in commitments['P']:
                possible = {i for i in possible if tasks[i] == tuple(route['paths'][h][0])}
            result[key] = frozenset(possible)
    return result


class InterventionScope(IntEnum):
    RETAIN = 0
    PATH_ONLY = 1
    SEQUENCE_AND_TRANSFERS = 2
    NEIGHBORHOOD_REASSIGNMENT = 3
    ALL_MUTABLE = 4


def _level(value):
    if isinstance(value, bool) or not isinstance(value, int) or value not in range(5):
        raise ValueError('scope must be an integer from 0 through 4')
    return InterventionScope(value)


def task_closure(tasks, seeds, task_supports):
    tasks, seeds = set(tasks), set(seeds)
    supports = [set(support) for support in task_supports.values()]
    if not seeds <= tasks or any(not support <= tasks for support in supports):
        raise ValueError('seeds and constraint supports must name remaining tasks')
    incidence = {i: [] for i in tasks}
    for g,support in enumerate(supports):
        for i in support:
            incidence[i].append(g)
    closure, queue, seen = set(seeds), list(seeds), set()
    while queue:
        i = queue.pop()
        for g in incidence[i]:
            if g not in seen:
                seen.add(g)
                new = supports[g]-closure
                closure.update(new)
                queue.extend(new)
    return frozenset(closure)


def reassignment_neighborhood(tasks, seeds, task_supports, mutable_assignments):
    if not set(mutable_assignments) <= set(tasks):
        raise ValueError('mutable assignments must name remaining tasks')
    # Committed assignments remain in the graph: they can be bridge vertices.
    return task_closure(tasks, seeds, task_supports) & set(mutable_assignments)


def constraint_coordinate_supports(scenario):
    """Conservative D_g over all domain branches, not just incumbent slack.

    Each UAV predicate retains all its mutable route coordinates, including
    activation guards and upstream states. Global stock/service/bay predicates
    remain individual constraints. Over-approximation may enlarge Level 3.
    """
    data = scenario.data
    values = coordinates(data)
    mutable = {(a,key) for a in COMPONENTS for key in values[a] if key not in data['commitments'][a]}
    route = {u['id']: frozenset((a,key) for a,key in mutable if a != 'A' and key.split(':')[0] == u['id']) for u in data['mission']['vehicles']}
    # Inactive and terminal loads are structurally zero. Summing every load
    # coordinate removes artificial sequence dependence when loads are fixed.
    result = {'inventory': frozenset((a,key) for a,key in mutable if a == 'L' and key.endswith(':y'))}
    slots = potential_task_slots(scenario)
    for i in remaining_tasks(data):
        support = set()
        for key,possible in slots.items():
            if i not in possible:
                continue
            uid,h = key.split(':')
            x = ('L',f'{key}:x')
            if x in mutable:
                support.add(x)
            if x in mutable or data['incumbent']['routes'][uid]['deliveries'][int(h)] > 0:
                if ('S',key) in mutable:
                    support.add(('S',key))
        result[f'service:{i}'] = frozenset(support)
    if data['operations']['depot_bays'] is not None:
        result['depot_bays'] = frozenset().union(*route.values())
    for u in data['mission']['vehicles']:
        uid, support = u['id'], route[u['id']]
        result[f'terminal:{uid}'] = support
        result[f'reserve:{uid}:initial'] = support
        for h in range(u['slot_bound']+1):
            for family in ('ground_completion','delivery_availability','payload','battery_arrival','battery_service'):
                result[f'{family}:{uid}:{h}'] = support
            if h:
                for family in ('flight_completion','depot_arrival_reserve','deadline','reserve'):
                    result[f'{family}:{uid}:{h}'] = support
    return result


def constraint_task_supports(scenario):
    data = scenario.data
    tasks = remaining_tasks(data)
    slots = potential_task_slots(scenario)
    eligible = {u['id']: set().union(*(support for key,support in slots.items()
                                      if key.split(':')[0] == u['id']))
                for u in data['mission']['vehicles']}
    result = {}
    for g, support in constraint_coordinate_supports(scenario).items():
        attributed = set()
        for a,key in support:
            attributed.update({key} if a == 'A' else eligible[key.split(':')[0]])
        result[g] = frozenset(attributed)
    return result


def release_sets(scenario, level, affected_tasks=(), task_supports=None):
    level = _level(level)
    if scenario.data['schema_version'] == 'wind-benchmark-v2' and level != 0:
        raise ValueError('v2 requires local_scope.scope_family; Level 3 is a union of patches')
    data = scenario.data
    values = coordinates(data)
    mutable = {a: frozenset(values[a])-set(data['commitments'][a]) for a in COMPONENTS}
    supports = constraint_task_supports(scenario) if task_supports is None else task_supports
    neighborhood = reassignment_neighborhood(remaining_tasks(data), affected_tasks, supports, mutable['A'])
    released = {a: frozenset() for a in COMPONENTS}
    if level >= 1:
        released['P'] = mutable['P']
    if level >= 2:
        released['S'], released['L'] = mutable['S'], mutable['L']
    if level == 3:
        released['A'] = neighborhood
    if level == 4:
        released['A'] = mutable['A']
    return released


@dataclass(frozen=True)
class ScopeCheck:
    allowed: bool
    violations: tuple[str, ...]


def check_scope(scenario, candidate, level, *, affected_tasks=(), task_supports=None):
    """Check X_k membership only; success is not a feasibility certificate."""
    releases = release_sets(scenario, level, affected_tasks, task_supports)
    try:
        candidate = scenario.validate_candidate(candidate)
    except ValueError as error:
        return ScopeCheck(False, (f'domain: {error}',))
    old, new = coordinates(scenario.data), coordinates(scenario.data, candidate)
    violations = tuple(f'fixed:{a}:{key}' for a in COMPONENTS for key in old[a] if key not in releases[a] and old[a][key] != new[a][key])
    return ScopeCheck(not violations, violations)
