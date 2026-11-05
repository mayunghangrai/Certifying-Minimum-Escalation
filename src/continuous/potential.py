"""Global all-path lower bounds from verified continuous spatial potentials.

The structured mesh covers the complete rectangular operating region and is
aligned with every wind interface. Potential values are shared at vertices.
Each triangle's rational gradient obeys the Hamiltonian inequality throughout
its owning cell. Along an interface, use a triangle of the declared wind owner;
continuity gives the same tangential derivative from either side.
"""
from fractions import Fraction
from itertools import product

from env.scenario import _thaw
from recovery.linear import rational
from recovery.local_search import digest
from .physics import sqrt_bounds, stationary_duration, stationary_wind_guard, displacement_duration


def rectangle(points):
    points = {tuple(map(rational, p)) for p in points}
    xs, ys = sorted({p[0] for p in points}), sorted({p[1] for p in points})
    if len(xs) != 2 or len(ys) != 2 or points != set(product(xs, ys)):
        raise ValueError('potential construction requires rectangular cells and region')
    return xs[0], ys[0], xs[-1], ys[-1]


def physics_hash(scenario, uid):
    d = scenario.data
    speed = next(u['airspeed_kmh'] for u in d['mission']['vehicles'] if u['id'] == uid)
    return digest(_thaw(dict(region=d['mission']['operating_region_xy'], cells=d['wind']['cells'],
        wind=[row[0] for row in d['wind']['received']['values']], speed=speed,
        boundary_owner=d['wind']['boundary_owner'])))


def partition(scenario):
    outer = rectangle(scenario.data['mission']['operating_region_xy'])
    boxes = [rectangle(c['polygon_xy']) for c in scenario.data['wind']['cells']]
    xs = sorted({outer[0], outer[2], *[x for b in boxes for x in (b[0], b[2]) if outer[0] < x < outer[2]]})
    ys = sorted({outer[1], outer[3], *[y for b in boxes for y in (b[1], b[3]) if outer[1] < y < outer[3]]})
    for x0, x1 in zip(xs, xs[1:]):
        for y0, y1 in zip(ys, ys[1:]):
            owners = [b for b in boxes if b[0] <= x0 and x1 <= b[2] and b[1] <= y0 and y1 <= b[3]]
            if len(owners) != 1:
                raise ValueError('wind cells must tile the region without interior overlap')
    return outer, boxes, xs, ys


def mesh(scenario, start, goal, refinement):
    if isinstance(refinement, bool) or not isinstance(refinement, int) or not 1 <= refinement <= 16:
        raise ValueError('mesh refinement must be an integer from 1 through 16')
    outer, boxes, xbase, ybase = partition(scenario)
    start, goal = tuple(map(rational, start)), tuple(map(rational, goal))
    if any(not (outer[0] <= p[0] <= outer[2] and outer[1] <= p[1] <= outer[3]) for p in (start, goal)):
        raise ValueError('potential endpoints outside region')
    def refine(base, additions):
        return sorted({*additions, base[-1], *[a+(b-a)*j/refinement
            for a, b in zip(base, base[1:]) for j in range(refinement)]})
    xs, ys = refine(xbase, (start[0], goal[0])), refine(ybase, (start[1], goal[1]))
    vertices = [(x, y) for y in ys for x in xs]
    if len(vertices) > 5000:
        raise ValueError('potential mesh exceeds work limit')
    triangles = []
    for j in range(len(ys)-1):
        for i in range(len(xs)-1):
            x, y = (xs[i]+xs[i+1])/2, (ys[j]+ys[j+1])/2
            cell = next(r for r, b in enumerate(boxes) if b[0] < x < b[2] and b[1] < y < b[3])
            a = j*len(xs)+i
            triangles.extend([((a, a+1, a+len(xs)+1), cell),
                              ((a, a+len(xs)+1, a+len(xs)), cell)])
    return vertices, triangles, vertices.index(start), vertices.index(goal)


def gradient_coefficients(vertices, indices):
    a, b, c = (vertices[i] for i in indices)
    dx1, dy1, dx2, dy2 = b[0]-a[0], b[1]-a[1], c[0]-a[0], c[1]-a[1]
    det = dx1*dy2-dx2*dy1
    return ((dy1-dy2)/det, dy2/det, -dy1/det), ((dx2-dx1)/det, -dx2/det, dx1/det)


def _gradients(vertices, triangles, values):
    for indices, cell in triangles:
        gx, gy = gradient_coefficients(vertices, indices)
        yield (sum(a*values[i] for a, i in zip(gx, indices)),
               sum(a*values[i] for a, i in zip(gy, indices))), cell


def propose_potential(scenario, uid, start, goal, refinement=2, digits=18):
    reason = stationary_wind_guard(scenario)
    if reason:
        raise ValueError(reason)
    from .conic import solve
    vertices, triangles, source, target = mesh(scenario, start, goal, refinement)
    speed = rational(next(u['airspeed_kmh'] for u in scenario.data['mission']['vehicles'] if u['id'] == uid))
    winds = [tuple(map(rational, row[0])) for row in scenario.data['wind']['received']['values']]
    rows, rhs, cones = [], [], []
    # The first vertex has potential zero; eliminate that variable to fix the gauge.
    for indices, cell in triangles:
        gx, gy = gradient_coefficients(vertices, indices)
        wx, wy = winds[cell]
        rows.extend([{i-1: wx*x+wy*y for i, x, y in zip(indices, gx, gy) if i},
                     {i-1: -speed*x for i, x in zip(indices, gx) if i},
                     {i-1: -speed*y for i, y in zip(indices, gy) if i}])
        rhs.extend((1, 0, 0)); cones.append(('soc', 3))
    q = [0.]*(len(vertices)-1)
    if source: q[source-1] += 1
    if target: q[target-1] -= 1
    proposal = solve(q, rows, rhs, cones)
    values = [Fraction(0), *[rational(round(float(v), 12)) for v in proposal]]
    # Scale the rounded numerical proposal using an outward rational norm.
    ceiling = Fraction(1)
    for (gx, gy), cell in _gradients(vertices, triangles, values):
        norm_hi = sqrt_bounds(gx*gx+gy*gy, digits)[1]
        wx, wy = winds[cell]
        ceiling = max(ceiling, wx*gx+wy*gy+speed*norm_hi)
    scale = Fraction((Fraction(1, 1)/ceiling*10**15).__floor__(), 10**15)
    values = [v*scale for v in values]
    certificate = dict(kind='continuous_potential_v1', physics_hash=physics_hash(scenario, uid),
        uid=uid, start=list(start), goal=list(goal), refinement=refinement,
        values=list(map(str, values)), lower=str(max(Fraction(0), values[target]-values[source])))
    if not verify_potential(scenario, uid, certificate):
        raise ArithmeticError('potential proposal failed rational verification')
    return certificate


def uniform_certificate(scenario, uid, start, goal, digits=18):
    reason = stationary_wind_guard(scenario)
    if reason: raise ValueError(reason)
    if len({tuple(map(rational, row[0])) for row in scenario.data['wind']['received']['values']}) != 1:
        raise ValueError('wind is not spatially uniform')
    # Validate endpoints without requiring the chord to stay in a nonconvex region.
    for point in (start, goal): stationary_duration(scenario, uid, [point], digits)
    speed = rational(next(u['airspeed_kmh'] for u in scenario.data['mission']['vehicles'] if u['id'] == uid))
    wind = tuple(map(rational, scenario.data['wind']['received']['values'][0][0]))
    displacement = tuple(rational(b)-rational(a) for a,b in zip(start, goal))
    lower, _ = displacement_duration(speed, wind, displacement, digits)
    return dict(kind='uniform_wind_lower_v1', physics_hash=physics_hash(scenario, uid),
        uid=uid, start=list(start), goal=list(goal), digits=digits, lower=str(lower))


def verify_potential(scenario, uid, certificate):
    """Check the entire certificate with rational arithmetic, without a solver."""
    try:
        if stationary_wind_guard(scenario) or certificate['uid'] != uid:
            return False
        if certificate['physics_hash'] != physics_hash(scenario, uid):
            return False
        if certificate['kind'] == 'uniform_wind_lower_v1':
            return certificate == uniform_certificate(scenario, uid, certificate['start'], certificate['goal'], certificate['digits'])
        if certificate['kind'] != 'continuous_potential_v1':
            return False
        vertices, triangles, source, target = mesh(scenario, certificate['start'], certificate['goal'], certificate['refinement'])
        values = list(map(Fraction, certificate['values']))
        if len(values) != len(vertices) or values[0] != 0:
            return False
        speed = rational(next(u['airspeed_kmh'] for u in scenario.data['mission']['vehicles'] if u['id'] == uid))
        for (gx, gy), cell in _gradients(vertices, triangles, values):
            wx, wy = map(rational, scenario.data['wind']['received']['values'][cell][0])
            margin = 1-wx*gx-wy*gy
            if margin < 0 or speed*speed*(gx*gx+gy*gy) > margin*margin:
                return False
        return Fraction(certificate['lower']) == max(Fraction(0), values[target]-values[source])
    except (ValueError, KeyError, TypeError, IndexError, ArithmeticError, StopIteration):
        return False
