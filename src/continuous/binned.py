"""Exact outward enclosures of flight times in time-binned piecewise-constant wind.

A path is split exactly at cell boundaries (`split_static_path`). On one piece
in one (cell, bin) the ground speed is constant, so progress through the piece
is linear in time and the piece's full duration T_j under bin j's wind has the
closed form of `displacement_duration`. A pass walks the pieces in order,
cutting at every bin knot it crosses.

With abs(w) < airspeed everywhere (FIFO), arrival is monotone in departure
time and in every T_j. A pass with the lower enclosures of all T_j from the
earliest possible departure therefore bounds the arrival from below, and a
pass with the upper enclosures from the latest departure bounds it from above.
"""
from bisect import bisect_right
from fractions import Fraction

from env import units
from .physics import displacement_duration, split_static_path


class BeyondHorizon(ValueError):
    """The pass reaches the last wind knot before arriving."""


def binned_guard(scenario):
    d = scenario.data
    if d['schema_version'] != units.V3:
        return 'requires wind-benchmark-v3'
    if d['operations']['depot_bays'] is not None:
        return 'coupled depot preparation'
    if any(s['mode'] != 'airborne' and (s['mode'] != 'idle' or tuple(s['position_xy']) != tuple(d['mission']['depot_xy']))
           for s in d['state']['fleet'].values()):
        return 'requires idle depot or airborne origins'
    w = d['wind']['received']
    if 'missing' in w['coverage']:
        return 'incomplete wind coverage'
    if any(not all(row) for row in w['admissible']):
        return 'inadmissible wind cells'
    slowest = min(units.airspeed(d, u) for u in d['mission']['vehicles'])
    if any(x*x + y*y >= slowest*slowest for row in units.wind_values(d, 'received') for x, y in row):
        return 'FIFO condition fails: wind not strictly below airspeed'
    return None


class _Path:
    """Pieces of one path with lazily computed per-bin duration enclosures."""

    def __init__(self, scenario, uid, path, digits):
        data = scenario.data
        vehicle = next(u for u in data['mission']['vehicles'] if u['id'] == uid)
        self.speed = units.airspeed(data, vehicle)
        self.wind = units.wind_values(data, 'received')
        self.knots = units.time_knots(data)
        self.digits = digits
        self.pieces = [(a, b, cell) for a, b, cell in split_static_path(scenario, path) if a != b]
        self._cache = {}

    def duration(self, k, j, side):
        key = k, j
        if key not in self._cache:
            a, b, cell = self.pieces[k]
            self._cache[key] = displacement_duration(self.speed, self.wind[cell][j],
                                                     (b[0]-a[0], b[1]-a[1]), self.digits)
        return self._cache[key][side]

    def walk(self, departure, side, stop=None):
        """Return (time, piece, fraction done) at arrival, or at `stop` if earlier."""
        knots, t = self.knots, Fraction(departure)
        if t < knots[0]:
            raise ValueError('departure precedes the first wind knot')
        for k in range(len(self.pieces)):
            q = Fraction(1)                       # fraction of piece k still to fly
            while q:
                if t >= knots[-1]:
                    raise BeyondHorizon('flight reaches the wind horizon')
                j = bisect_right(knots, t) - 1
                T = self.duration(k, j, side)
                end = min(t + q*T, knots[j+1])
                if stop is not None and stop <= end:
                    return stop, k, 1 - q + (stop - t)/T
                q -= (end - t)/T
                t = end
        return t, len(self.pieces), Fraction(0)


def binned_interval(scenario, uid, path, departure_lo, departure_hi, digits=18):
    """[earliest, latest] arrival for any departure in [departure_lo, departure_hi].

    Either bound is None when its pass reaches the wind horizon first.
    """
    walker = _Path(scenario, uid, path, digits)
    bounds = []
    for departure, side in ((departure_lo, 0), (departure_hi, 1)):
        try:
            bounds.append(walker.walk(departure, side)[0])
        except BeyondHorizon:
            bounds.append(None)
    return tuple(bounds)


def binned_duration(scenario, uid, path, departure, digits=18):
    """[lo, hi] flight duration for an exact departure time."""
    lo, hi = binned_interval(scenario, uid, path, departure, departure, digits)
    if lo is None or hi is None:
        raise BeyondHorizon('flight reaches the wind horizon')
    departure = Fraction(departure)
    return lo - departure, hi - departure


def position_at(scenario, uid, path, departure_lo, departure_hi, time, digits=18):
    """(behind, ahead): exact points on the path bracketing the position at `time`
    for any departure in [departure_lo, departure_hi]."""
    walker = _Path(scenario, uid, path, digits)
    points = []
    # The slow pass from the latest departure is behind, the fast pass from the earliest ahead.
    for departure, side in ((departure_hi, 1), (departure_lo, 0)):
        _, k, done = walker.walk(departure, side, stop=Fraction(time))
        if k == len(walker.pieces):
            points.append(walker.pieces[-1][1] if walker.pieces else tuple(map(Fraction, path[-1])))
        else:
            a, b, _ = walker.pieces[k]
            points.append(tuple(a[i] + (b[i]-a[i])*done for i in (0, 1)))
    return tuple(points)


def interval_provider(scenario, digits=18):
    """Cached `binned_interval` in the transfer compiler's provider signature."""
    cache = {}

    def provide(uid, path, departure_lo, departure_hi):
        key = uid, tuple(tuple(p) for p in path), departure_lo, departure_hi
        if key not in cache:
            cache[key] = binned_interval(scenario, uid, path, departure_lo, departure_hi, digits)
        return cache[key]
    return provide
