"""Rational outward enclosures for stationary arbitrary-angle flight paths.

No path library enters these checks. Geometry is split using rational line
intersections, and each constant-wind displacement has a closed-form duration.
"""
from fractions import Fraction
from math import isfinite, isqrt

from recovery.linear import rational
from recovery.physics import _covers, _cross, _sub


def sqrt_bounds(value, digits=18):
    value = Fraction(value)
    if value < 0 or isinstance(digits, bool) or not isinstance(digits, int) or not 1 <= digits <= 60:
        raise ValueError('invalid square-root enclosure')
    n, d = isqrt(value.numerator), isqrt(value.denominator)
    if n*n == value.numerator and d*d == value.denominator:
        return Fraction(n, d), Fraction(n, d)
    scale = 10**digits
    root = isqrt(value.numerator*scale*scale // value.denominator)
    return Fraction(root, scale), Fraction(root+1, scale)


def stationary_wind_guard(scenario):
    w = scenario.data['wind']['received']
    if 'missing' in w['coverage']:
        return 'incomplete wind coverage'
    if any(not all(row) for row in w['admissible']):
        return 'inadmissible wind cells'
    if any(any(tuple(map(rational, v)) != tuple(map(rational, row[0])) for v in row)
           for row in w['values']):
        return 'time-dependent wind'
    return None


def stationary_guard(scenario):
    d = scenario.data
    if d['schema_version'] != 'wind-benchmark-v2':
        return 'requires revised local scope formulation'
    if d['operations']['depot_bays'] is not None:
        return 'coupled depot preparation'
    # An airborne UAV starts its first leg at the observed position, epoch,
    # battery and payload. Unfinished ground operations remain unsupported.
    if any(s['mode'] != 'airborne' and (s['mode'] != 'idle' or tuple(s['position_xy']) != tuple(d['mission']['depot_xy']))
           for s in d['state']['fleet'].values()):
        return 'requires idle depot or airborne origins'
    return stationary_wind_guard(scenario)


def depot_origin(scenario, uid):
    """Same predicate as the evaluator: only a ground depot origin prepares and recharges."""
    d = scenario.data
    s = d['state']['fleet'][uid]
    return tuple(s['position_xy']) == tuple(d['mission']['depot_xy']) and s['mode'] in ('idle', 'preparing')


def _vertices(points):
    return [tuple(map(rational, p)) for p in points]


def split_static_path(scenario, path):
    """Yield rational displacements and exact owning cell indices.

    Include region edges in the split so midpoint coverage checks also reject
    excursions outside a nonconvex operating region. Shared interfaces follow
    the scenario's lowest-cell-id convention.
    """
    if not path or any(len(p) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float))
            or not isfinite(v) for v in p) for p in path):
        raise ValueError('path must contain finite XY coordinates')
    points = _vertices(path)
    region = _vertices(scenario.data['mission']['operating_region_xy'])
    cells = [(c['id'], _vertices(c['polygon_xy']), i)
             for i, c in enumerate(scenario.data['wind']['cells'])]
    if any(not _covers(region, p) for p in points):
        raise ValueError('path outside operating region')
    boundaries = [region, *[vertices for _, vertices, _ in cells]]
    for a, b in zip(points, points[1:]):
        direction = _sub(b, a)
        if direction == (0, 0):
            continue
        cuts = {Fraction(0), Fraction(1)}
        for vertices in boundaries:
            for p, q in zip(vertices, vertices[1:]+vertices[:1]):
                edge, offset = _sub(q, p), _sub(p, a)
                denominator = _cross(direction, edge)
                if denominator:
                    t, s = _cross(offset, edge)/denominator, _cross(offset, direction)/denominator
                    if 0 <= t <= 1 and 0 <= s <= 1:
                        cuts.add(t)
                elif _cross(offset, direction) == 0:
                    axis = 0 if direction[0] else 1
                    cuts.update(t for point in (p, q)
                                if 0 <= (t := (point[axis]-a[axis])/direction[axis]) <= 1)
        cuts = sorted(cuts)
        for left, right in zip(cuts, cuts[1:]):
            middle = tuple(a[j]+direction[j]*(left+right)/2 for j in (0, 1))
            if not _covers(region, middle):
                raise ValueError('path outside operating region')
            owners = [(name, i) for name, vertices, i in cells if _covers(vertices, middle)]
            if not owners:
                raise ValueError('path outside wind coverage')
            yield (tuple(a[j]+direction[j]*left for j in (0, 1)),
                   tuple(a[j]+direction[j]*right for j in (0, 1)), min(owners)[1])


def displacement_duration(speed, wind, displacement, digits=18):
    """Constant-wind displacement cost, independent of region geometry."""
    speed = Fraction(speed)
    wind, displacement = tuple(map(Fraction, wind)), tuple(map(Fraction, displacement))
    along = sum(w*d for w, d in zip(wind, displacement))
    delta = speed*speed-sum(w*w for w in wind)
    if delta <= 0: raise ValueError('wind must be strictly below airspeed')
    length2 = sum(d*d for d in displacement)
    root_lo, root_hi = sqrt_bounds(along*along+delta*length2, digits)
    return max(Fraction(0), (root_lo-along)/delta), (root_hi-along)/delta


def stationary_duration(scenario, uid, path, digits=18):
    reason = stationary_wind_guard(scenario)
    if reason:
        raise ValueError(reason)
    speed = rational(next(u['airspeed_kmh'] for u in scenario.data['mission']['vehicles'] if u['id'] == uid))
    sqrt_bounds(0, digits)
    lo = hi = Fraction(0)
    for a, b, cell in split_static_path(scenario, path):
        wind = tuple(map(rational, scenario.data['wind']['received']['values'][cell][0]))
        left, right = displacement_duration(speed, wind, _sub(b, a), digits)
        lo, hi = lo+left, hi+right
    return lo, hi
