"""Shared interval table of fastest flight times for one stationary wind field.

Lower ends hold for every admissible path between two points (Section 5.1 of the v2
plan): a linear potential (any stationary wind), the closed form under uniform wind,
or a verified per-pair potential field at refinement 2, 4, 8 or 16, computed only
when a decision depends on that leg. Upper ends are exact flight times of actual
paths: the straight chord first, then detour and conic-optimized paths on demand.

UAVs with the same airspeed share entries; a certificate is relabelled for the UAV
that cites it, which leaves its physics hash unchanged.
"""
from fractions import Fraction

from continuous.oracle import ContinuousOracle
from continuous.physics import displacement_duration, sqrt_bounds, stationary_duration, stationary_wind_guard
from continuous.potential import partition, physics_hash, propose_potential, uniform_certificate, verify_potential
from env.geometry import canonical_path
from recovery.linear import rational

REFINEMENTS = (2, 4, 8, 16)
TIGHT = Fraction(1, 10**9)


def _speed(scenario, uid):
    return rational(next(u['airspeed_kmh'] for u in scenario.data['mission']['vehicles'] if u['id'] == uid))


def _winds(scenario):
    return [tuple(map(rational, row[0])) for row in scenario.data['wind']['received']['values']]


def linear_certificate(scenario, uid, start, goal, digits=18, *, _hash=None, _speed_value=None, _wind_list=None):
    """Gradient g of a linear potential with w.g + v|g| <= 1 in every cell.

    Along any admissible path the potential grows at most at unit rate, so the
    flight time from start to goal is at least g.(goal - start).
    """
    speed = _speed(scenario, uid) if _speed_value is None else _speed_value
    winds = _winds(scenario) if _wind_list is None else _wind_list
    d = tuple(rational(b)-rational(a) for a, b in zip(start, goal))
    gradient = (Fraction(0), Fraction(0))
    if d != (0, 0):
        length = sqrt_bounds(d[0]*d[0]+d[1]*d[1], digits)[1]
        e = (d[0]/length, d[1]/length)
        worst = max(w[0]*e[0]+w[1]*e[1] for w in winds)
        mu = 1/(speed+worst)
        gradient = (mu*e[0], mu*e[1])
    lower = max(Fraction(0), gradient[0]*d[0]+gradient[1]*d[1])
    return dict(kind='linear_potential_v2', physics_hash=physics_hash(scenario, uid) if _hash is None else _hash,
                uid=uid, start=list(start), goal=list(goal), gradient=[str(g) for g in gradient], lower=str(lower))


def chord_upper(speed, windy, start, goal, digits=18):
    """Exact-or-larger flight time of the straight chord when only ``windy`` cells have wind.

    ``windy`` lists (box, wind) of the cells with nonzero wind; elsewhere the ground
    speed is the airspeed. Returns None when the chord runs along a windy cell's
    boundary, where the owner convention decides and the caller must integrate.
    """
    a = tuple(map(rational, start))
    d = tuple(rational(g)-x for g, x in zip(goal, a))
    if d == (0, 0):
        return Fraction(0)
    inside = Fraction(0)
    total = Fraction(0)
    for (x0, y0, x1, y1), wind in windy:
        lo, hi = Fraction(0), Fraction(1)
        for axis, (low, high) in enumerate(((x0, x1), (y0, y1))):
            if d[axis] == 0:
                if not low <= a[axis] <= high:
                    lo, hi = Fraction(1), Fraction(0)
                    break
                if a[axis] in (low, high):
                    return None
                continue
            t1, t2 = (low-a[axis])/d[axis], (high-a[axis])/d[axis]
            if t1 > t2:
                t1, t2 = t2, t1
            lo, hi = max(lo, t1), min(hi, t2)
        if hi > lo:
            inside += hi-lo
            total += displacement_duration(speed, wind, (d[0]*(hi-lo), d[1]*(hi-lo)), digits)[1]
    calm = 1-inside
    if calm > 0:
        total += calm*sqrt_bounds(d[0]*d[0]+d[1]*d[1], digits)[1]/speed
    # Square roots are bounded separately from the official integrator; this margin
    # keeps the value at or above its upper end (differences are below 1e-17 h).
    return total+Fraction(1, 10**15)


def verify_linear(scenario, uid, certificate):
    try:
        c = certificate
        if (c['kind'] != 'linear_potential_v2' or c['uid'] != uid or stationary_wind_guard(scenario)
                or c['physics_hash'] != physics_hash(scenario, uid)):
            return False
        speed = _speed(scenario, uid)
        g = tuple(map(Fraction, c['gradient']))
        if len(g) != 2:
            return False
        for w in _winds(scenario):
            margin = 1-w[0]*g[0]-w[1]*g[1]
            if margin < 0 or speed*speed*(g[0]*g[0]+g[1]*g[1]) > margin*margin:
                return False
        d = tuple(rational(b)-rational(a) for a, b in zip(c['start'], c['goal']))
        return Fraction(c['lower']) == max(Fraction(0), g[0]*d[0]+g[1]*d[1])
    except (KeyError, ValueError, TypeError, ArithmeticError, StopIteration):
        return False


def verify_lower(scenario, uid, start, goal, certificate, lower):
    """True iff ``lower`` is certified for every admissible path from start to goal."""
    lower = Fraction(lower)
    if certificate is None:
        return lower == 0 or (tuple(start) == tuple(goal) and lower == 0)
    try:
        if list(certificate['start']) != list(start) or list(certificate['goal']) != list(goal):
            return False
        if Fraction(certificate['lower']) != lower:
            return False
        if certificate['kind'] == 'linear_potential_v2':
            return verify_linear(scenario, uid, certificate)
        if certificate['kind'] in ('continuous_potential_v1', 'uniform_wind_lower_v1'):
            return verify_potential(scenario, uid, certificate)
    except (KeyError, ValueError, TypeError, ArithmeticError):
        return False
    return False


class Entry:
    __slots__ = ('lower', 'certificate', 'tier', 'upper', 'path', 'improved')

    def __init__(self):
        self.lower, self.certificate, self.tier = Fraction(0), None, 0
        self.upper, self.path, self.improved = None, None, 0     # improved: 0 none, 1 quick, 2 deep

    def tight(self):
        return self.upper is not None and self.upper-self.lower <= TIGHT


class FlightTable:
    """Interval fastest times keyed by (airspeed, start, goal), filled when needed."""

    def __init__(self, scenario, *, digits=18, max_refinement=16, clock=None):
        reason = stationary_wind_guard(scenario)
        if reason:
            raise ValueError(reason)
        self.scenario, self.digits, self.clock = scenario, digits, clock
        self.max_tier = 1+sum(r <= max_refinement for r in REFINEMENTS)
        self.speed = {u['id']: rational(u['airspeed_kmh']) for u in scenario.data['mission']['vehicles']}
        self.owner = {}
        for uid in sorted(self.speed):
            self.owner.setdefault(self.speed[uid], uid)
        self.uniform = len(set(_winds(scenario))) == 1
        self.calm = [w == (0, 0) for w in _winds(scenario)]
        self.entries = {}
        self.durations = {}
        self.effort = dict(linear=0, fields=0, field_failures=0, chords=0, improved=0, conic=0)
        self._hashes = {uid: physics_hash(scenario, uid) for uid in set(self.owner.values())}
        self._winds = _winds(scenario)
        self._oracle = None
        _, self.boxes, _, _ = partition(scenario)
        self.windy = [(box, wind) for box, wind in zip(self.boxes, self._winds) if wind != (0, 0)]

    def _charge(self, category):
        from contextlib import nullcontext
        return self.clock.charge(category) if self.clock is not None else nullcontext()

    def entry(self, uid, a, b):
        key = self.speed[uid], tuple(a), tuple(b)
        item = self.entries.get(key)
        if item is None:
            item = self.entries[key] = Entry()
            if tuple(a) != tuple(b):
                self._first_lower(uid, a, b, item)
            else:
                item.tier = self.max_tier
        return item

    def _first_lower(self, uid, a, b, item):
        with self._charge('bounds'):
            owner = self.owner[self.speed[uid]]
            if self.uniform:
                cert = uniform_certificate(self.scenario, owner, list(a), list(b), self.digits)
                item.tier = self.max_tier
            else:
                cert = linear_certificate(self.scenario, owner, list(a), list(b), self.digits,
                                          _hash=self._hashes[owner], _speed_value=self.speed[owner],
                                          _wind_list=self._winds)
                item.tier = 1
                self.effort['linear'] += 1
            item.lower, item.certificate = Fraction(cert['lower']), cert

    def lower(self, uid, a, b):
        return self.entry(uid, a, b).lower

    def certificate(self, uid, a, b):
        """The current lower-bound certificate, relabelled for ``uid`` (None for a zero leg)."""
        cert = self.entry(uid, a, b).certificate
        if cert is None:
            return None
        if cert['uid'] == uid:
            return cert
        return {**cert, 'uid': uid}

    def refinable(self, uid, a, b):
        item = self.entry(uid, a, b)
        return item.tier < self.max_tier and not item.tight()

    def refine(self, uid, a, b):
        """Raise the lower bound by one tier. Return True if the bound increased."""
        item = self.entry(uid, a, b)
        if item.tier >= self.max_tier:
            return False
        refinement = REFINEMENTS[item.tier-1]
        item.tier += 1
        with self._charge('bounds'):
            try:
                cert = propose_potential(self.scenario, self.owner[self.speed[uid]], list(a), list(b),
                                         refinement, self.digits)
                self.effort['fields'] += 1
            except (ValueError, ArithmeticError):
                self.effort['field_failures'] += 1
                return False
        if Fraction(cert['lower']) > item.lower:
            item.lower, item.certificate = Fraction(cert['lower']), cert
            if item.upper is not None and item.lower > item.upper:
                raise ArithmeticError('certified lower bound exceeds an achieved flight time')
            return True
        return False

    def upper(self, uid, a, b):
        """Best achieved flight time and its path (the chord until improved)."""
        item = self.entry(uid, a, b)
        if item.upper is None:
            with self._charge('paths'):
                path = [list(a), list(b)]
                value = chord_upper(self.speed[uid], self.windy, a, b, self.digits)
                if value is None:
                    value = stationary_duration(self.scenario, self.owner[self.speed[uid]], path, self.digits)[1]
                item.upper = value
                item.path = path
                self.effort['chords'] += 1
                if item.lower > item.upper:
                    raise ArithmeticError('certified lower bound exceeds the chord time')
        return item.upper

    def path(self, uid, a, b):
        self.upper(uid, a, b)
        return [list(p) for p in self.entry(uid, a, b).path]

    def _seeds(self, a, b):
        """Chord, detours around and through every windy cell, and interface probes.

        The probes (as in ``ContinuousOracle.query``) fly just on either side of each
        interior cell boundary, so a leg along an interface can use the better side.
        """
        seeds = [[list(a), list(b)]]
        outer, _, xs, ys = partition(self.scenario)
        eps = Fraction(1, 1000)
        for box, calm in zip(self.boxes, self.calm):
            if calm:
                continue
            x0, y0, x1, y1 = box
            centre = ((x0+x1)/2, (y0+y1)/2)
            seeds.append([list(a), [float(centre[0]), float(centre[1])], list(b)])
            corners = []
            for cx, cy in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                q = (cx+(eps if cx > centre[0] else -eps), cy+(eps if cy > centre[1] else -eps))
                inside = outer[0] <= q[0] <= outer[2] and outer[1] <= q[1] <= outer[3]
                corners.append([float(q[0]), float(q[1])] if inside else None)
            for i, q in enumerate(corners):
                if q is not None:
                    seeds.append([list(a), q, list(b)])
                r = corners[(i+1) % 4]
                if q is not None and r is not None:
                    seeds.append([list(a), q, r, list(b)])
                    seeds.append([list(a), r, q, list(b)])
        for axis, cuts in ((0, xs), (1, ys)):
            low, high = float(outer[axis]), float(outer[axis+2])
            epsilon = (high-low)*1e-4
            for cut in cuts[1:-1]:
                for value in (float(cut)-epsilon, float(cut)+epsilon):
                    if low < value < high:
                        p, q = list(a), list(b)
                        p[axis] = q[axis] = value
                        seeds.append([list(a), p, q, list(b)])
        return seeds

    def exact_duration(self, uid, path):
        """``stationary_duration`` of one path (the official integrator), cached for this run."""
        key = self.speed[uid], tuple(tuple(p) for p in path)
        if key not in self.durations:
            self.durations[key] = stationary_duration(self.scenario, self.owner[self.speed[uid]], [list(p) for p in path],
                                                      self.digits)
        return self.durations[key]

    def _fast_upper(self, uid, path):
        """Sum of per-segment chord times (at or above the exact value); None if unsure."""
        total = Fraction(0)
        for p, q in zip(path, path[1:]):
            value = chord_upper(self.speed[uid], self.windy, p, q, self.digits)
            if value is None:
                return None
            total += value
        return total

    def improve(self, uid, a, b, *, keep=3, deep=False):
        """Search detour and conic-optimized paths; True if the time dropped.

        Quick (once per leg): candidates ranked with per-segment chord times, conic
        optimization of the best ``keep``. Deep (once, for a leg a decision hinges on):
        also the shortest grid path of ``ContinuousOracle``, and conic optimization of
        every candidate. The best ones are integrated exactly (the official integrator),
        which also checks the region.
        """
        item = self.entry(uid, a, b)
        self.upper(uid, a, b)
        level = 2 if deep else 1
        if item.improved >= level or item.tight() or tuple(a) == tuple(b):
            item.improved = max(item.improved, level)
            return False
        item.improved = level
        if deep:
            keep = 10**6
        owner = self.owner[self.speed[uid]]
        before = item.upper
        with self._charge('paths'):
            self.effort['improved'] += 1
            scored = []
            seeds = self._seeds(a, b)
            if deep:
                if self._oracle is None:
                    self._oracle = ContinuousOracle(self.scenario, (2,), self.digits)
                try:
                    seeds.append(self._oracle._seed(owner, list(a), list(b)))
                except (ValueError, ArithmeticError, KeyError):
                    pass
            for seed in seeds:
                path = [list(p) for p in canonical_path(seed)]
                value = self._fast_upper(uid, path)
                if value is None:
                    try:
                        value = self.exact_duration(uid, path)[1]
                    except (ValueError, ArithmeticError):
                        continue
                scored.append((value, path))
            scored.sort(key=lambda t: t[0])
            if self._oracle is None:
                self._oracle = ContinuousOracle(self.scenario, (2,), self.digits)
            candidates = list(scored)
            for _, path in scored[:keep]:
                try:
                    optimized = self._oracle._optimize(owner, path)
                    self.effort['conic'] += 1
                    optimized = [list(p) for p in canonical_path(optimized)]
                except (ValueError, ArithmeticError):
                    continue
                if tuple(optimized[0]) != tuple(a) or tuple(optimized[-1]) != tuple(b):
                    continue
                value = self._fast_upper(uid, optimized)
                if value is None:
                    try:
                        value = self.exact_duration(uid, optimized)[1]
                    except (ValueError, ArithmeticError):
                        continue
                candidates.append((value, optimized))
            candidates.sort(key=lambda t: t[0])
            checked = 0
            for value, path in candidates:
                if checked >= 3 or value >= item.upper:
                    break
                try:
                    exact = self.exact_duration(uid, path)[1]
                except (ValueError, ArithmeticError):
                    continue
                checked += 1
                if exact < item.upper:
                    if item.lower > exact:
                        raise ArithmeticError('certified lower bound exceeds an achieved flight time')
                    item.upper, item.path = exact, path
        return item.upper < before
