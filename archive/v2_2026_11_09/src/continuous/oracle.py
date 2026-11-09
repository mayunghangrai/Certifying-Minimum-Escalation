"""Continuous cell-crossing optimization with independent path/global bounds.

Spatial seeds initialize cell itineraries. They never define the path domain:
crossings are continuously optimized and missing itineraries remain unresolved.
"""
from copy import deepcopy
from fractions import Fraction
from heapq import heappop, heappush
from itertools import product
from time import perf_counter

from env.geometry import canonical_path
from recovery.linear import rational
from .physics import stationary_duration, stationary_wind_guard, split_static_path
from .potential import partition, propose_potential, uniform_certificate, verify_potential


def verify_query(scenario, query, digits=18):
    try:
        q = query
        lo, hi = stationary_duration(scenario, q['uid'], q['path'], digits)
        if q['path'][0] != q['start'] or q['path'][-1] != q['goal']: return False
        if q['path_interval'] != list(map(str, (lo, hi))) or Fraction(q['upper']) != hi: return False
        lower, field = Fraction(q['lower']), q['lower_certificate']
        if field is None:
            if lower != 0: return False
        elif (field['start'] != q['start'] or field['goal'] != q['goal']
              or not verify_potential(scenario, q['uid'], field) or lower != Fraction(field['lower'])): return False
        return 0 <= lower <= hi and Fraction(q['gap']) == hi-lower
    except (ValueError, TypeError, KeyError, ArithmeticError, IndexError): return False


class ContinuousOracle:
    def __init__(self, scenario, refinements=(2, 4), digits=18):
        reason = stationary_wind_guard(scenario)
        if reason: raise ValueError(reason)
        if not refinements or any(isinstance(r, bool) or not isinstance(r, int) or not 1 <= r <= 16 for r in refinements):
            raise ValueError('invalid potential refinements')
        self.scenario, self.refinements, self.digits = scenario, tuple(refinements), digits
        self.cache, self.seed_cache, self.used = {}, {}, set()
        self.effort = dict(queries=0, cache_hits=0, path_s=0., bound_s=0., conic_paths=0, potential_fields=0)
        self.uniform = len({tuple(map(rational, row[0])) for row in scenario.data['wind']['received']['values']}) == 1

    def _duration(self, uid, path):
        return stationary_duration(self.scenario, uid, path, self.digits)

    def _seed(self, uid, start, goal):
        _, _, xs, ys = partition(self.scenario)
        if uid not in self.seed_cache:
            points = [(float(x), float(y)) for y in ys for x in xs]
            graph = [[] for _ in points]
            for j in range(len(ys)):
                for i in range(len(xs)):
                    a = j*len(xs)+i
                    for dx, dy in ((1, 0), (0, 1), (1, 1), (-1, 1)):
                        x, y = i+dx, j+dy
                        if not 0 <= x < len(xs) or not 0 <= y < len(ys): continue
                        b = y*len(xs)+x
                        for left, right in ((a, b), (b, a)):
                            cost = float(self._duration(uid, [points[left], points[right]])[1])
                            graph[left].append((right, cost))
            self.seed_cache[uid] = points, graph
        points, graph = self.seed_cache[uid]
        points = [*points, tuple(start), tuple(goal)]
        graph = [list(row) for row in graph]+[[], []]
        source, target = len(points)-2, len(points)-1
        for a in (source, target):
            for b in range(len(points)):
                if a == b: continue
                graph[a].append((b, float(self._duration(uid, [points[a], points[b]])[1])))
                graph[b].append((a, float(self._duration(uid, [points[b], points[a]])[1])))
        distance, parent, queue = {source: 0.}, {}, [(0., source)]
        while queue:
            cost, a = heappop(queue)
            if cost != distance[a]: continue
            if a == target: break
            for b, dt in graph[a]:
                value = cost+dt
                if value < distance.get(b, float('inf')):
                    distance[b], parent[b] = value, a
                    heappush(queue, (value, b))
        ids = [target]
        while ids[-1] != source: ids.append(parent[ids[-1]])
        return [list(points[i]) for i in reversed(ids)]

    def _optimize(self, uid, path):
        from .conic import solve
        _, boxes, _, _ = partition(self.scenario)
        itinerary = []
        for _, _, cell in split_static_path(self.scenario, path):
            if not itinerary or itinerary[-1] != cell: itinerary.append(cell)
        if len(itinerary) <= 1: return [path[0], path[-1]]
        portals = []
        for left, right in zip(itinerary, itinerary[1:]):
            a, b = boxes[left], boxes[right]
            x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
            if x0 > x1 or y0 > y1 or (x0 < x1 and y0 < y1):
                raise ValueError('unsupported wind-cell itinerary')
            portals.append(((x0, y0), (x1-x0, y1-y0)))
        k, m = len(portals), len(itinerary)
        points = [(tuple(map(rational, path[0])), {})]
        points.extend((a, {j: d}) for j, (a, d) in enumerate(portals))
        points.append((tuple(map(rational, path[-1])), {}))
        rows, rhs, cones = [], [], []
        for j in range(k):
            rows.extend(({j: -1}, {j: 1})); rhs.extend((0, 1)); cones.extend((('nonnegative', 1),)*2)
        speed = rational(next(u['airspeed_kmh'] for u in self.scenario.data['mission']['vehicles'] if u['id'] == uid))
        for i, cell in enumerate(itinerary):
            a, aa = points[i]; b, bb = points[i+1]
            wind = tuple(map(rational, self.scenario.data['wind']['received']['values'][cell][0]))
            rows.append({k+i: -speed}); rhs.append(0)
            for axis in (0, 1):
                row = {j: aa.get(j, (0, 0))[axis]-bb.get(j, (0, 0))[axis] for j in set(aa)|set(bb)}
                row[k+i] = wind[axis]
                rows.append(row); rhs.append(b[axis]-a[axis])
            cones.append(('soc', 3))
        values = solve([0.]*k+[1.]*m, rows, rhs, cones)
        result = [list(path[0])]
        for j, (a, direction) in enumerate(portals):
            fraction = rational(round(min(1., max(0., values[j])), 12))
            result.append([float(a[axis]+fraction*direction[axis]) for axis in (0, 1)])
        result.append(list(path[-1]))
        self.effort['conic_paths'] += 1
        # A conic optimum can follow an interface owned by a different cell.
        # Move that segment into the intended rectangle, then integrate again.
        interior = [result[0]]
        for a, b, cell in zip(result, result[1:], itinerary):
            if tuple(a) != tuple(b) and any(owner != cell for _, _, owner in split_static_path(self.scenario, [a, b])):
                box = boxes[cell]
                center = ((box[0]+box[2])/2, (box[1]+box[3])/2)
                midpoint = tuple((rational(a[j])+rational(b[j]))/2 for j in (0, 1))
                epsilon = Fraction(1, 10**5)
                interior.append([float((1-epsilon)*midpoint[j]+epsilon*center[j]) for j in (0, 1)])
            interior.append(b)
        return interior

    def query(self, uid, start, goal, warm_paths=(), *, bound=True):
        self.effort['queries'] += 1
        key = uid, tuple(start), tuple(goal)
        self.used.add(key)
        if key in self.cache and (not bound or self.cache[key]['bound_attempted']):
            self.effort['cache_hits'] += 1
            return deepcopy(self.cache[key])
        begin = perf_counter()
        paths = [[list(start), list(goal)], *warm_paths]
        if key in self.cache: paths.append(self.cache[key]['path'])
        zero_chord = False
        if not bound:
            try:
                zero_chord = all(tuple(self.scenario.data['wind']['received']['values'][cell][0]) == (0, 0)
                                 for _, _, cell in split_static_path(self.scenario, paths[0]))
            except ValueError: pass
        # A feasibility proposal may keep a valid zero-wind chord. Bounds still
        # explore detours; this shortcut makes no shortest-path claim.
        if not self.uniform and not zero_chord and tuple(start) != tuple(goal):
            # Probe either side of interfaces to initialize detour itineraries.
            # The subsequent crossing coordinates are continuous variables.
            try:
                outer, _, xs, ys = partition(self.scenario)
                for axis, cuts in ((0, xs), (1, ys)):
                    low, high = float(outer[axis]), float(outer[axis+2])
                    epsilon = (high-low)*1e-4
                    for cut in cuts[1:-1]:
                        for value in (float(cut)-epsilon, float(cut)+epsilon):
                            if not low < value < high: continue
                            a, b = list(start), list(goal)
                            a[axis] = b[axis] = value
                            paths.append([list(start), a, b, list(goal)])
            except ValueError: pass
            try: paths.append(self._seed(uid, start, goal))
            except (ValueError, ArithmeticError): pass
            for path in list(paths):
                try: paths.append(self._optimize(uid, path))
                except (ValueError, ArithmeticError): pass
        choices = []
        for path in paths:
            try:
                if tuple(path[0]) != tuple(start) or tuple(path[-1]) != tuple(goal): continue
                path = [list(p) for p in canonical_path(path)]
                lo, hi = self._duration(uid, path)
                choices.append((hi, path, lo))
            except (ValueError, ArithmeticError): continue
        if not choices: raise ValueError('no admissible candidate path generated')
        upper, path, path_lower = min(choices)
        self.effort['path_s'] += perf_counter()-begin
        lower, certificate = Fraction(0), None
        begin = perf_counter()
        if bound and tuple(start) != tuple(goal):
            if self.uniform:
                certificate = uniform_certificate(self.scenario, uid, start, goal, self.digits)
                lower = Fraction(certificate['lower'])
            else:
                for refinement in self.refinements:
                    try:
                        candidate = propose_potential(self.scenario, uid, start, goal, refinement, self.digits)
                        self.effort['potential_fields'] += 1
                        if Fraction(candidate['lower']) > lower:
                            lower, certificate = Fraction(candidate['lower']), candidate
                        if upper-lower <= Fraction(1, 10**6): break
                    except (ValueError, ArithmeticError): continue
        self.effort['bound_s'] += perf_counter()-begin
        if lower > upper: raise ArithmeticError('inconsistent path upper and global lower bounds')
        result = dict(uid=uid, start=list(start), goal=list(goal), path=path,
            path_interval=list(map(str, (path_lower, upper))), lower=str(lower), upper=str(upper),
            gap=str(upper-lower), lower_certificate=certificate, bound_attempted=bound)
        self.cache[key] = result
        return deepcopy(result)
