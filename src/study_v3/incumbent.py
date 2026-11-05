"""A4: the incumbent plan of design 4.3 (regret-2 insertion plus local search).

A route is a list of stops: task ids and 'DEPOT' reload stops. It starts at the
depot after one preparation and ends with an implicit return to the depot.
Rules 1 and 2 hold by construction: each task appears once, there is no ground
waiting, and a route never starts or ends with 'DEPOT' or repeats it.

Times are floats (Q17). Comparisons use a 1e-6 s threshold, so rounding can
never decide between two moves. The exact pass happens afterwards
(`study_v3.missions`).
"""
from dataclasses import dataclass

EPS = 1e-6
DEPOT = 'DEPOT'


@dataclass(frozen=True)
class Problem:
    depot: tuple
    positions: dict          # task id -> (x, y)
    demands: dict            # task id -> packages
    speeds: dict             # uid -> airspeed in m/s
    k: dict                  # uid -> tasks it must take (n // m or one more)
    capacity: int            # packages per sortie
    service_s: float
    preparation_s: float
    legs: object             # FloatLegs


def _number(name):
    return int(name[1:])


def valid(problem, stops):
    if stops and (stops[0] == DEPOT or stops[-1] == DEPOT):
        return False
    load = 0
    for a, b in zip(stops, stops[1:] + [None]):
        if a == DEPOT:
            if b == DEPOT:
                return False
            load = 0
        else:
            load += problem.demands[a]
            if load > problem.capacity:
                return False
    return True


def simulate(problem, uid, stops):
    """(finish time, flight time, delivery times) of one route."""
    legs, speed = problem.legs, problem.speeds[uid]
    t = problem.preparation_s if stops else 0.0
    flight, position, deliveries = 0.0, problem.depot, {}
    for stop in stops + [None]:
        target = problem.depot if stop in (DEPOT, None) else problem.positions[stop]
        dt = legs.duration(speed, position, target, t)
        t += dt
        flight += dt
        position = target
        if stop == DEPOT:
            t += problem.preparation_s
        elif stop is not None:
            t += problem.service_s
            deliveries[stop] = t
    return t, flight, deliveries


def _better(a, b):
    """Lexicographic (makespan, flight) with the 1e-6 s threshold on both."""
    if a[0] < b[0] - EPS:
        return True
    return abs(a[0] - b[0]) <= EPS and a[1] < b[1] - EPS


def _insertions(problem, stops, task):
    for p in range(len(stops) + 1):
        for piece in ([task], [DEPOT, task], [task, DEPOT]):
            candidate = stops[:p] + piece + stops[p:]
            if valid(problem, candidate):
                yield candidate


def construct(problem, uids):
    routes = {u: [] for u in uids}
    finish = {u: 0.0 for u in uids}
    unassigned = sorted(problem.positions, key=_number)
    while unassigned:
        choice = None              # (regret, task, uid, route)
        for task in unassigned:
            best = {}
            for u in uids:
                if sum(s != DEPOT for s in routes[u]) >= problem.k[u]:
                    continue
                for candidate in _insertions(problem, routes[u], task):
                    cost = simulate(problem, u, candidate)[0] - finish[u]
                    if u not in best or cost < best[u][0] - EPS:
                        best[u] = (cost, candidate)
            if not best:
                raise ValueError('no UAV has room for a task')
            ranked = sorted(best.items(), key=lambda item: (item[1][0], _number(item[0])))
            regret = float('inf') if len(ranked) == 1 else ranked[1][1][0] - ranked[0][1][0]
            if choice is None or regret > choice[0] + EPS:      # ties keep the lower task number
                choice = (regret, task, ranked[0][0], ranked[0][1][1])
        _, task, u, candidate = choice
        routes[u] = candidate
        finish[u] = simulate(problem, u, candidate)[0]
        unassigned.remove(task)
    return routes


def _moves(problem, routes):
    """All neighbours in the fixed order: relocate, 2-opt, swap, depot move."""
    uids = sorted(routes, key=_number)
    for u in uids:                                     # relocate within a route
        stops = routes[u]
        for task in sorted((s for s in stops if s != DEPOT), key=_number):
            rest = [s for s in stops if s != task]
            for p in range(len(rest) + 1):
                candidate = rest[:p] + [task] + rest[p:]
                if candidate != stops:
                    yield {u: candidate}
    for u in uids:                                     # 2-opt within a route
        stops = routes[u]
        for i in range(len(stops)):
            for j in range(i + 1, len(stops)):
                yield {u: stops[:i] + stops[i:j+1][::-1] + stops[j+1:]}
    for a, u in enumerate(uids):                       # swap between UAVs
        for v in uids[a+1:]:
            for x in sorted((s for s in routes[u] if s != DEPOT), key=_number):
                for y in sorted((s for s in routes[v] if s != DEPOT), key=_number):
                    yield {u: [y if s == x else s for s in routes[u]],
                           v: [x if s == y else s for s in routes[v]]}
    for u in uids:                                     # move a depot stop
        stops = routes[u]
        for d in [i for i, s in enumerate(stops) if s == DEPOT]:
            rest = stops[:d] + stops[d+1:]
            for p in range(len(rest) + 1):
                candidate = rest[:p] + [DEPOT] + rest[p:]
                if candidate != stops:
                    yield {u: candidate}


def improve(problem, routes, iterations=2000):
    state = {u: simulate(problem, u, s)[:2] for u, s in routes.items()}

    def score(changed):
        values = {**state, **changed}
        return max(v[0] for v in values.values()), sum(v[1] for v in values.values())

    current = score({})
    for _ in range(iterations):
        best = None
        for move in _moves(problem, routes):
            if not all(valid(problem, s) for s in move.values()):
                continue
            changed = {u: simulate(problem, u, s)[:2] for u, s in move.items()}
            value = score(changed)
            if _better(value, current) and (best is None or _better(value, best[0])):
                best = (value, move, changed)
        if best is None:
            break
        current, move, changed = best
        routes = {**routes, **move}
        state.update(changed)
    return routes


def build_incumbent(problem, uids, iterations=2000):
    return improve(problem, construct(problem, uids), iterations)
