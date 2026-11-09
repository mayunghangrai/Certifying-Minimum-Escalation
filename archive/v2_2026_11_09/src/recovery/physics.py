"""Independent rational path integration for reference certificates."""
from bisect import bisect_right
from fractions import Fraction
from math import isqrt, isfinite

from env.route_evaluator import evaluate_path
from .linear import rational


class UnsupportedArithmetic(ArithmeticError):
    pass


class InadmissiblePath(ValueError):
    pass


def _sqrt(value):
    n,d = isqrt(value.numerator),isqrt(value.denominator)
    if n*n != value.numerator or d*d != value.denominator:
        raise UnsupportedArithmetic('irrational length or ground speed')
    return Fraction(n,d)


def _cross(a,b):
    return a[0]*b[1]-a[1]*b[0]


def _sub(a,b):
    return a[0]-b[0],a[1]-b[1]


def _covers(vertices,p):
    inside = False
    for a,b in zip(vertices,vertices[1:]+vertices[:1]):
        if _cross(_sub(b,a),_sub(p,a)) == 0 and all(min(a[j],b[j]) <= p[j] <= max(a[j],b[j]) for j in (0,1)):
            return True
        if (a[1]>p[1]) != (b[1]>p[1]) and p[0] < a[0]+(p[1]-a[1])*(b[0]-a[0])/(b[1]-a[1]):
            inside = not inside
    return inside


def _pieces(scenario,path):
    cells = [(c['id'],[tuple(map(rational,p)) for p in c['polygon_xy']],i)
             for i,c in enumerate(scenario.data['wind']['cells'])]
    points = [tuple(map(rational,p)) for p in path]
    for a,b in zip(points,points[1:]):
        direction = _sub(b,a)
        if direction == (0,0):
            continue
        length = _sqrt(sum(v*v for v in direction))
        cuts = {Fraction(0),Fraction(1)}
        for _,vertices,_ in cells:
            for p,q in zip(vertices,vertices[1:]+vertices[:1]):
                edge,offset = _sub(q,p),_sub(p,a)
                denominator = _cross(direction,edge)
                if denominator:
                    t,s = _cross(offset,edge)/denominator,_cross(offset,direction)/denominator
                    if 0 <= t <= 1 and 0 <= s <= 1:
                        cuts.add(t)
                elif _cross(offset,direction) == 0:
                    axis = 0 if direction[0] else 1
                    for point in (p,q):
                        t = (point[axis]-a[axis])/direction[axis]
                        if 0 <= t <= 1:
                            cuts.add(t)
        cuts = sorted(cuts)
        for left,right in zip(cuts,cuts[1:]):
            middle = tuple(a[j]+direction[j]*(left+right)/2 for j in (0,1))
            owners = [(name,index) for name,vertices,index in cells if _covers(vertices,middle)]
            if not owners:
                raise UnsupportedArithmetic('rational path interval outside wind coverage')
            yield length*(right-left),tuple(v/length for v in direction),min(owners)[1]


def flight_duration(scenario, uid, path, departure, *, exact):
    if not exact:
        result = evaluate_path(scenario,uid,path,float(departure),0)
        if result.status == 'closed':
            raise InadmissiblePath('closed cell-time interval')
        if result.duration_h is not None and not isfinite(result.duration_h):
            raise UnsupportedArithmetic('nonfinite flight duration')
        return result.duration_h
    wind = scenario.data['wind']
    knots = tuple(map(rational,wind['time_knots_h']))
    airspeed = rational(next(u['airspeed_kmh'] for u in scenario.data['mission']['vehicles'] if u['id']==uid))
    start = time = rational(departure)
    if time < knots[0]:
        raise ValueError('pre-epoch departure')
    if time > knots[-1]:
        return None
    for distance,direction,cell in _pieces(scenario,path):
        while distance > 0:
            if time >= knots[-1]:
                return None
            j = bisect_right(knots,time)-1
            if wind['received'].get('coverage', ('forecast',)*(len(knots)-1))[j] == 'missing':
                raise UnsupportedArithmetic('missing forecast coverage')
            if not wind['received'].get('admissible', ((True,)*(len(knots)-1),)*len(wind['cells']))[cell][j]:
                raise InadmissiblePath('closed cell-time interval')
            vector = tuple(map(rational,wind['received']['values'][cell][j]))
            along = sum(x*y for x,y in zip(vector,direction))
            cross = _cross(direction,vector)
            speed = along+_sqrt(airspeed*airspeed-cross*cross)
            dt = min(distance/speed,knots[j+1]-time)
            time += dt
            distance -= speed*dt
    return time-start
