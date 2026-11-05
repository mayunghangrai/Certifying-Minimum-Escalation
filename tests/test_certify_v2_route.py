"""Route check: soundness and exactness against explicit route enumeration."""
from itertools import permutations, product
import random

from certify_v2.route import RouteInput, closure, solve


def _instance(rng, n, *, metric, energy=True):
    nodes = n+2
    if metric:
        points = [(rng.randint(0, 40), rng.randint(0, 40)) for _ in range(nodes)]
        points[n+1] = (20, 20)
        dist = [[round(((a[0]-b[0])**2+(a[1]-b[1])**2)**.5*10) for b in points] for a in points]
    else:
        dist = [[0 if i == j else rng.randint(1, 400) for j in range(nodes)] for i in range(nodes)]
    rate = rng.choice([0, 1, 2]) if energy else 0
    E = [[d*rate for d in row] for row in dist]
    s, p = rng.choice([0, 5, 10]), rng.choice([0, 5, 20])
    se = rng.choice([0, 3]) if energy else 0
    reserve = [E[i][n+1] for i in range(nodes)]
    deadline = [rng.choice([None, rng.randint(50, 1500)]) for _ in range(n)]
    budget = rng.randint(200, 3000) if energy and rate else 10**9
    return RouteInput(n=n, deadline=deadline, dist=dist, reserve=reserve, energy=E, t0=rng.randint(0, 30),
                      r0=budget if rng.random() < .5 else budget//2, recharge=budget, service=s, service_energy=se,
                      preparation=p, horizon=rng.randint(800, 3000), stops=rng.choice([0, 0, 1, 2]),
                      slots=rng.randint(n+1, n+4), end_stops=True)


def _explicit(problem, stops):
    """Simulate one explicit stop sequence (tasks may repeat, 'D' is a depot stop) in the same model."""
    n, depot = problem.n, problem.n+1
    D, E, R = problem.dist, problem.energy, problem.reserve
    if len(stops)+1 > problem.slots or set(range(n)) - {q for q in stops if q != 'D'}:
        return False
    if problem.r0 < R[n] or sum(q == 'D' for q in stops) < problem.stops:
        return False
    t, r, x, seen = problem.t0, problem.r0, n, set()
    for q in stops:
        if q == 'D':
            t += D[x][depot]
            r -= E[x][depot]
            if r < 0:
                return False
            t += problem.preparation
            r, x = problem.recharge, depot
            continue
        t += D[x][q]+problem.service
        r -= E[x][q]+problem.service_energy
        if r < R[q]:
            return False
        if q not in seen:
            seen.add(q)
            if problem.deadline[q] is not None and t > problem.deadline[q]:
                return False
        x = q
    return t+D[x][depot] <= problem.horizon and r >= E[x][depot]


def _brute(problem):
    n = problem.n
    alphabet = list(range(n))+['D']
    for length in range(n, problem.slots):
        for stops in product(alphabet, repeat=length):
            if any(a == b for a, b in zip(stops, stops[1:])):
                continue
            if _explicit(problem, list(stops)):
                return True
    return False


def _optimistic(problem):
    D = closure(problem.dist, problem.n)
    E = closure(problem.energy, problem.n)
    return RouteInput(**{**problem.__dict__, 'dist': D, 'energy': E})


def test_optimistic_run_never_rejects_a_feasible_explicit_route():
    rng = random.Random(7)
    checked = feasible = 0
    for _ in range(400):
        problem = _instance(rng, rng.randint(0, 3), metric=rng.random() < .5)
        truth = _brute(problem)
        relaxed = solve(_optimistic(problem)).feasible
        checked += 1
        feasible += truth
        assert relaxed or not truth
    assert feasible > 50 and checked-feasible > 50


def test_timing_check_is_exact_for_metric_times_without_stops():
    rng = random.Random(11)
    for _ in range(300):
        problem = _instance(rng, rng.randint(1, 5), metric=True, energy=False)
        problem.stops, problem.preparation, problem.slots = 0, 0, problem.n+1
        truth = any(_explicit(problem, list(order)) for order in permutations(range(problem.n)))
        assert solve(_optimistic(problem)).feasible == truth


def test_achievable_order_is_an_explicit_feasible_route():
    rng = random.Random(5)
    found = 0
    for _ in range(300):
        problem = _instance(rng, rng.randint(1, 4), metric=rng.random() < .5)
        problem.end_stops = False
        result = solve(problem, want_order=True)
        if not result.feasible:
            continue
        stops = []
        for q, via in result.order:
            stops += ['D']*via+[q]
        assert _explicit(problem, stops)
        found += 1
    assert found > 50
