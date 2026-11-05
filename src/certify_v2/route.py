"""Route check for one UAV: can it serve a task set from a given state?

First-visit relaxation (plan Section 5.2 with the 10 October amendments). The
route visits every task of R at least once; a task that still owes mandatory
demand needs its first visit by the deadline, because later visits are later.
Between consecutive first visits the UAV may stop at the depot (preparation,
recharge, reload) or revisit tasks. The optimistic run

- times each gap by the shortest path over certified lower bounds (repeat and
  depot visits included, their ground time dropped), or, for a gap with a depot
  stop, by the bounds to and from the depot plus one preparation;
- charges at least the empty-mass energy rate for every flight and the service
  energy at each first visit, recharges to capacity at a depot stop, and keeps
  the reserve return (empty mass) and the depot-arrival reserve;
- needs at least k intermediate depot stops, k = ceil((Q - L0) / C), where Q is
  the remaining mandatory demand, C the payload capacity and L0 the most the UAV
  can carry before its first intermediate stop; extra stops may sit at the end;
- respects the slot bound: first visits + intermediate stops + final depot.

Every relaxed rule only removes constraints or shortens times, so an empty
search proves that no route serves R, for every path, order, depot visit and
quantity. The same search with achievable times (direct legs, at most one depot
stop per gap) proposes a route for the exact check.

Times are integers in 1e-12 h, energies in 1e-12 Wh. The optimistic run rounds
flight times and energies down and deadlines, horizon and budgets up; the
achievable run rounds the other way.
"""
from dataclasses import dataclass, field
from fractions import Fraction
import math

TICK = 10**12
INF = None


def floor_ticks(value):
    return math.floor(Fraction(value)*TICK)


def ceil_ticks(value):
    return math.ceil(Fraction(value)*TICK)


@dataclass
class RouteInput:
    """One route check in integer ticks. Nodes: tasks 0..n-1, start n, depot n+1."""
    n: int
    deadline: list            # per task: int ticks or None
    dist: list                # (n+2) x (n+2) gap flight times (closure applied when optimistic)
    reserve: list             # per node: energy ticks needed to return directly to the depot
    energy: list              # (n+2) x (n+2) energy ticks of each gap flight
    t0: int                   # departure time from the start node
    r0: int                   # energy budget at the start (battery - reserve), energy ticks
    recharge: int             # budget after a depot stop (capacity - reserve)
    service: int
    service_energy: int
    preparation: int
    horizon: int
    stops: int                # required intermediate depot stops
    slots: int                # slots left for first visits, intermediate stops and the final depot
    end_stops: bool           # optimistic: extra required stops may sit at the end
    first: int | None = None  # committed first task: reached by a direct leg, no stop before it
    first_dist: int = 0
    first_energy: int = 0


@dataclass
class RouteResult:
    feasible: bool
    order: list = field(default_factory=list)    # [(task index, depot stop before it)]
    end_stops: int = 0
    finish: int | None = None
    states: int = 0


def _insert(items, t, r, parent, value, via):
    """Keep only Pareto-optimal (earliest time, largest budget) entries."""
    for et, er, *_ in items:
        if et <= t and er >= r:
            return False
    items[:] = [e for e in items if not (t <= e[0] and r >= e[1])]
    items.append((t, r, parent, value, via))
    return True


def solve(problem, *, want_order=False):
    """Forward search over (visited set, last node, stops used) with Pareto (time, budget)."""
    n, start, depot = problem.n, problem.n, problem.n+1
    D, E, R = problem.dist, problem.energy, problem.reserve
    s, se, p, H = problem.service, problem.service_energy, problem.preparation, problem.horizon
    if problem.slots < n+problem.stops+1 or problem.r0 < R[start]:
        return RouteResult(False)
    max_stops = problem.slots-n-1
    layers = [{(0, start, 0): [(problem.t0, problem.r0, None, None, 0)]}]
    count = 1
    full = (1 << n)-1
    best = None
    for size in range(n+1):
        layer, following = layers[-1], {}
        for (mask, x, used), entries in layer.items():
            if size == n:
                extra = max(0, problem.stops-used)
                if (extra and not problem.end_stops) or used+extra+n+1 > problem.slots:
                    continue
                for index, (t, r, *_) in enumerate(entries):
                    finish = t+D[x][depot]+extra*p
                    if finish <= H and r >= E[x][depot]:
                        if not want_order:
                            return RouteResult(True, states=count)
                        if best is None or finish < best[0]:
                            best = (finish, (mask, x, used), index, extra)
                continue
            for q in range(n):
                bit = 1 << q
                if mask & bit:
                    continue
                dl = problem.deadline[q]
                gap, gap_energy = D[x][q], E[x][q]
                via = D[x][depot]+p+D[depot][q]
                via_ok = used < max_stops
                if size == 0 and problem.first is not None:
                    if q != problem.first:
                        continue
                    gap, gap_energy, via_ok = problem.first_dist, problem.first_energy, False
                for t, r, *_ in entries:
                    t1, r1 = t+gap+s, r-gap_energy-se
                    if (dl is None or t1 <= dl) and r1 >= R[q]:
                        if _insert(following.setdefault((mask | bit, q, used), []), t1, r1,
                                   (mask, x, used), (t, r), 0):
                            count += 1
                    if via_ok and r >= E[x][depot]:
                        t2, r2 = t+via+s, problem.recharge-E[depot][q]-se
                        if (dl is None or t2 <= dl) and r2 >= R[q]:
                            if _insert(following.setdefault((mask | bit, q, used+1), []), t2, r2,
                                       (mask, x, used), (t, r), 1):
                                count += 1
        if size == n:
            break
        layers.append(following)
    if best is None:
        return RouteResult(False, states=count)
    finish, key, index, extra = best
    order = []
    entry = layers[n][key][index]
    while entry[2] is not None:
        order.append((key[1], entry[4]))
        key, (pt, pr) = entry[2], entry[3]
        entry = next(e for e in layers[bin(key[0]).count('1')][key] if e[0] == pt and e[1] == pr)
    order.reverse()
    return RouteResult(True, order=order, end_stops=extra, finish=finish, states=count)


def closure(dist, n, *, paths=False):
    """Shortest paths through tasks and the depot; the start is never an intermediate stop.

    With ``paths`` also return next-hop pointers: nxt[i][j] is the first node after i.
    """
    nodes = n+2
    D = [row[:] for row in dist]
    nxt = [list(range(nodes)) for _ in range(nodes)] if paths else None
    for k in list(range(n))+[n+1]:
        Dk = D[k]
        for i in range(nodes):
            dik = D[i][k]
            Di = D[i]
            for j in range(nodes):
                value = dik+Dk[j]
                if value < Di[j]:
                    Di[j] = value
                    if paths:
                        nxt[i][j] = nxt[i][k]
    return (D, nxt) if paths else D


def hops(nxt, i, j):
    """Direct legs of the closure path from i to j."""
    legs = []
    while i != j:
        k = nxt[i][j]
        legs.append((i, k))
        i = k
    return legs
