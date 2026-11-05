"""Gate A rescaling (design 5.6 "Unit invariance", generator part; Q13).

A mission rescaled by rational factors L (length) and T (time) is the same
mission in other units: lengths x L, times x T, speeds and wind x L/T, and
energies x T (power keeps its coefficients, energy = P t / 3600). Masses and
packages do not change.

With L and T powers of two every float the incumbent search computes scales
exactly, so the rebuilt incumbent can be compared exactly.
"""
from copy import deepcopy
from fractions import Fraction as F

from env.scenario import Scenario
from .flight import FloatLegs
from .incumbent import DEPOT, Problem, build_incumbent
from .missions import CAPACITY, number, task_counts
from .wind_model import wire


def _scale(value, factor):
    return number(F(str(value))*factor)


def _points(points, L):
    return [[_scale(c, L) for c in p] for p in points]


def rescale(payload, L, T):
    p = deepcopy(payload)
    L, T = F(L), F(T)
    V = L/T
    m = p['mission']
    for key in ('epoch_s', 'horizon_s'):
        m[key] = _scale(m[key], T)
    m['operating_region_xy'] = _points(m['operating_region_xy'], L)
    m['depot_xy'] = [_scale(c, L) for c in m['depot_xy']]
    for t in m['tasks']:
        t['position_xy'] = [_scale(c, L) for c in t['position_xy']]
        if t['deadline_s'] is not None:
            t['deadline_s'] = _scale(t['deadline_s'], T)
    for u in m['vehicles']:
        u['airspeed_mps'] = _scale(u['airspeed_mps'], V)
        u['battery_capacity_wh'] = _scale(u['battery_capacity_wh'], T)
        u['reserve_wh'] = _scale(u['reserve_wh'], T)
    for s in p['state']['fleet'].values():
        if s['residual_operation'] is not None:
            raise ValueError('rescaling expects no residual operation')
        s['position_xy'] = [_scale(c, L) for c in s['position_xy']]
        s['battery_wh'] = _scale(s['battery_wh'], T)
    o = p['operations']
    o['service_duration_s'] = _scale(o['service_duration_s'], T)
    o['preparation_duration_s'] = _scale(o['preparation_duration_s'], T)
    o['service_energy_wh'] = _scale(o['service_energy_wh'], T)
    w = p['wind']
    for c in w['cells']:
        c['polygon_xy'] = _points(c['polygon_xy'], L)
    w['time_knots_s'] = [_scale(k, T) for k in w['time_knots_s']]
    w['speed_bound_mps'] = _scale(w['speed_bound_mps'], V)
    for name in ('previous', 'received'):
        packet = w[name]
        packet['issued_at_s'] = _scale(packet['issued_at_s'], T)
        packet['values'] = [[[wire(F(str(x))*V) for x in v] for v in row] for row in packet['values']]
    for route in p['incumbent']['routes'].values():
        route['paths'] = [_points(path, L) for path in route['paths']]
    p['reserve_paths'] = {u: {k: _points(path, L) for k, path in paths.items()}
                          for u, paths in p['reserve_paths'].items()}
    return Scenario(p).to_dict()


def problem_from_payload(payload, wind):
    """The incumbent search's input, read from a t = 0 payload.

    `wind(cell_index, bin_index)` supplies F0 (in the payload's units) beyond
    the payload's last bin, as the generator's lazy F0 does.
    """
    m = payload['mission']
    knots = payload['wind']['time_knots_s']
    uids = [u['id'] for u in m['vehicles']]
    return Problem(tuple(m['depot_xy']), {t['id']: tuple(t['position_xy']) for t in m['tasks']},
                   {t['id']: t['demand'] for t in m['tasks']}, {u['id']: u['airspeed_mps'] for u in m['vehicles']},
                   task_counts(len(m['tasks']), len(uids)), CAPACITY,
                   float(payload['operations']['service_duration_s']),
                   float(payload['operations']['preparation_duration_s']),
                   FloatLegs(m['operating_region_xy'], payload['wind']['cells'], wind, F(str(knots[1])) - F(str(knots[0])))), uids


def incumbent_routes(payload):
    """Stop lists of the payload's incumbent, without the final 'DEPOT' return."""
    out = {}
    for uid, route in payload['incumbent']['routes'].items():
        stops = [s for s in route['stops'] if s is not None]
        out[uid] = stops[:-1] if stops and stops[-1] == DEPOT else stops
    return out


def rebuild_incumbent(payload, wind, iterations=2000):
    problem, uids = problem_from_payload(payload, wind)
    return build_incumbent(problem, uids, iterations)
