"""Complete finite Level-2 route-slot domain, independent of path proposals.

Every mutable slot branches over inactivity, depot, and every assigned task.
Repeated visits and depot revisits are retained. Rejections use only necessary
common-domain structural conditions; a released direct chord is just an oracle
initialization and need not be a valid path through a nonconvex region.
"""
from fractions import Fraction

from env.geometry import canonical_path
from env.local_scope import ScopePatch, affected_uavs, scope_family
from env.wind_dependency import diagnose_wind_update


class SkeletonDomain:
    def __init__(self, scenario, *, u0=None, assignment=None, patch=None, scope_level=3):
        self.scenario = scenario
        if assignment is not None or patch is not None:
            diagnosed = affected_uavs(scenario, diagnose_wind_update(scenario))['uavs']
            if u0 is not None and set(u0) != set(diagnosed):
                raise ValueError('explicit scope must use the original affected UAV set')
            u0 = diagnosed
        elif u0 is None:
            u0 = affected_uavs(scenario, diagnose_wind_update(scenario))['uavs']
        self.affected = tuple(sorted(u0))
        self.data = scenario.data
        self.fleet = {u['id']: u for u in self.data['mission']['vehicles']}
        original = self.data['incumbent']['assignment']
        if assignment is None and patch is None:
            self.patch, = scope_family(scenario, 2, u0)
            self.assignment = dict(original)
        else:
            if assignment is None or patch is None:
                raise ValueError('explicit assignment and permitted scope patch are required together')
            if type(scope_level) is not int or scope_level not in (3, 4):
                raise ValueError('explicit sequence scope level must be 3 or 4')
            permitted = scope_family(scenario, scope_level, u0)
            if not isinstance(patch, ScopePatch) or patch not in permitted:
                raise ValueError('patch is not a permitted scope of the original scenario')
            # Retain the original reference and use exactly its validated mask.
            self.patch = next(p for p in permitted if p == patch)
            if (not isinstance(assignment, dict) or set(assignment) != set(original)
                    or any(owner is not None and (not isinstance(owner, str) or owner not in self.fleet)
                           for owner in assignment.values())):
                raise ValueError('assignment must contain every remaining task and known UAV owners')
            if any(owner != original[i] for i, owner in assignment.items() if i not in self.patch.releases['A']):
                raise ValueError('candidate changes an unreleased assignment coordinate')
            self.assignment = dict(assignment)
        self.assigned = {u: tuple(sorted(i for i, owner in self.assignment.items()
                                        if owner == u)) for u in sorted(self.fleet)}
        self.slots = tuple((u, h) for u in sorted(self.fleet)
                           for h in range(1, self.fleet[u]['slot_bound']+1))
        self.points = {i['id']: tuple(i['position_xy']) for i in self.data['mission']['tasks']}
        self.depot = tuple(self.data['mission']['depot_xy'])

    def children(self, prefix):
        """Raw complete branch alphabet; no structural pruning is hidden here."""
        if len(prefix) > len(self.slots):
            raise ValueError('prefix exceeds route-slot domain')
        if self.complete(prefix):
            return ()
        uid, h = self.slots[len(prefix)]
        if f'{uid}:{h}' not in self.patch.releases['S']:
            return (self.data['incumbent']['routes'][uid]['stops'][h-1],)
        return (None, 'DEPOT', *self.assigned[uid])

    def complete(self, prefix):
        return len(prefix) == len(self.slots)

    def reject(self, prefix):
        """Return a replayable necessary structural contradiction, if any."""
        if len(prefix) > len(self.slots):
            raise ValueError('prefix exceeds route-slot domain')
        routes = {u: [] for u in self.fleet}
        for index, stop in enumerate(prefix):
            uid, h = self.slots[index]
            if stop not in self.children(prefix[:index]):
                return 'coordinate_domain'
            if stop not in (None, 'DEPOT') and stop not in self.assigned[uid]:
                return 'assignment_visit_owner'
            routes[uid].append(stop)
        for uid in sorted(routes):
            stops = routes[uid]
            if not stops:
                continue
            original = self.data['incumbent']['routes'][uid]
            observed = self.data['state']['fleet'][uid]
            bound = self.fleet[uid]['slot_bound']
            n = next((h for h, stop in enumerate(stops) if stop is None), len(stops))
            padded, finished = n < len(stops), len(stops) == bound
            if any(stop is not None for stop in stops[n:]):
                return 'padding'
            if (padded or finished) and n and stops[n-1] != 'DEPOT':
                return 'termination'
            if padded and not n and (observed['mode'] != 'idle'
                                      or tuple(observed['position_xy']) != self.depot):
                return 'idle_origin'
            if observed['mode'] == 'servicing':
                if stops[0] in (None, 'DEPOT') or self.points[stops[0]] != tuple(observed['position_xy']):
                    return 'pending_service'
            missing = set(self.assigned[uid])-set(stops)
            if missing and ((padded or finished) or len(missing)+1 > bound-len(stops)):
                return 'assignment_coverage'
            previous = tuple(observed['position_xy'])
            for h, stop in enumerate(stops, 1):
                point = self.depot if stop in (None, 'DEPOT') else self.points[stop]
                if f'{uid}:{h}' not in self.patch.releases['P']:
                    path = canonical_path(original['paths'][h-1])
                    if (stop is None and path != (self.depot,)) or (
                            stop is not None and (path[0] != previous or path[-1] != point)):
                        return 'fixed_path_endpoints'
                for a, key in (('x', 'deliveries'), ('y', 'loads')):
                    if f'{uid}:{h}:{a}' in self.patch.releases['L']:
                        continue
                    value = Fraction(str(original[key][h]))
                    if value and (stop is None or (a == 'x' and stop == 'DEPOT')
                                  or (a == 'y' and stop != 'DEPOT')):
                        return 'fixed_transfer_eligibility'
                previous = point
            depot_origin = tuple(observed['position_xy']) == self.depot and observed['mode'] in ('idle', 'preparing')
            for h, a, key, invalid in (
                    (0, 'x', 'deliveries', True),
                    (0, 'y', 'loads', not depot_origin),
                    (n, 'y', 'loads', padded or finished)):
                if invalid and f'{uid}:{h}:{a}' not in self.patch.releases['L'] and Fraction(str(original[key][h])):
                    return 'fixed_transfer_eligibility'
        return None

    def skeleton(self, prefix):
        """Initialize paths/transfers, preserving every unreleased coordinate."""
        if not self.complete(prefix) or self.reject(prefix) is not None:
            raise ValueError('skeleton needs a complete structurally permitted prefix')
        plan = self.scenario.to_dict()['incumbent']
        plan['assignment'] = dict(self.assignment)
        for uid, route in plan['routes'].items():
            for h in range(len(route['loads'])):
                for a, key in (('x', 'deliveries'), ('y', 'loads')):
                    if f'{uid}:{h}:{a}' in self.patch.releases['L']:
                        route[key][h] = 0
        previous = {u: tuple(self.data['state']['fleet'][u]['position_xy']) for u in self.fleet}
        for (uid, h), stop in zip(self.slots, prefix):
            route = plan['routes'][uid]
            route['stops'][h-1] = stop
            point = self.depot if stop in (None, 'DEPOT') else self.points[stop]
            if f'{uid}:{h}' in self.patch.releases['P']:
                path = (self.depot,) if stop is None else canonical_path((previous[uid], point))
                route['paths'][h-1] = [list(p) for p in path]
            previous[uid] = point
        return plan

    def prefixes(self):
        """Depth-first enumeration of all structurally permitted full prefixes."""
        stack = [()]
        while stack:
            prefix = stack.pop()
            if self.reject(prefix) is not None:
                continue
            if self.complete(prefix):
                yield prefix
            else:
                stack.extend(prefix+(stop,) for stop in reversed(self.children(prefix)))

    def iter_skeletons(self):
        for prefix in self.prefixes():
            yield self.skeleton(prefix)
