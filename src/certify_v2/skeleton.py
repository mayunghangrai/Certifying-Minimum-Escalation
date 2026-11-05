"""Complete search over one UAV's stop sequences for a task set (plan Section 5.4).

A stop sequence lists tasks (repeats allowed) and depot stops and ends at the
depot. Two reductions keep the search finite and small; each excluded sequence
is dominated by merging two stops into the first one (the UAV's paths, order and
quantities are released, so later slots may shift):

- no two consecutive depot stops, and a ground depot origin is never followed by a
  depot stop (its preparation already recharged and loaded);
- no two consecutive visits to the same task.

A prefix is closed when its own timeline (lower bounds) breaks a rule or when the
optimistic route check from its end cannot serve the unvisited tasks. A complete
sequence is closed by a Farkas combination of the UAV's rows with lower flight
times. Lower bounds come from one tick matrix fixed when the search starts and
stored with the proof.
"""
from fractions import Fraction
import math

from recovery.transfers import BranchRejected
from .route import RouteInput, TICK, ceil_ticks, closure, floor_ticks, solve
from .uav import solve_uav, uav_problem, verify_uav_exclusion


def _energy(rate, ticks):
    return math.floor(rate*ticks)


class Frame:
    """Optimistic timeline of a prefix, in ticks."""

    def __init__(self, model, tasks, matrix):
        self.model, self.tasks, self.matrix = model, list(tasks), matrix
        self.index = {t: i for i, t in enumerate(self.tasks)}
        n = len(self.tasks)
        self.start, self.depot = n, n+1
        nonempty = True
        self.t0 = floor_ticks(model.departure(nonempty))
        self.r0 = ceil_ticks(model.budget(nonempty))
        self.recharge = ceil_ticks(model.cap-model.reserve_wh)
        self.s, self.se, self.p = floor_ticks(model.service), floor_ticks(model.service_energy), floor_ticks(model.preparation)
        self.H = ceil_ticks(model.horizon)
        self.deadline = [None if model.deadline[t] is None else ceil_ticks(model.deadline[t]) for t in self.tasks]

    def node(self, stop):
        return self.depot if stop == 'DEPOT' else self.index[stop]

    def walk(self, stops):
        """Return (failure or None, state) after the prefix ``stops``."""
        m, rate = self.matrix, self.model.rate
        x, t, r, used, seen = self.start, self.t0, self.r0, 0, set()
        if r < _energy(rate, m[x][self.depot]):
            return 'initial_reserve', None
        for h, stop in enumerate(stops, 1):
            y = self.node(stop)
            t += m[x][y]
            r -= _energy(rate, m[x][y])
            if stop == 'DEPOT':
                # Every depot stop of a prefix is intermediate: the final one is added by 'END'.
                if r < 0:
                    return f'depot_arrival:{h}', None
                t += self.p
                r = self.recharge
                used += 1
            else:
                t += self.s
                r -= self.se
                if r < _energy(rate, m[y][self.depot]):
                    return f'reserve:{h}', None
                if y not in seen:
                    seen.add(y)
                    dl = self.deadline[y]
                    if dl is not None and t > dl:
                        return f'deadline:{h}', None
            if t > self.H:
                return f'horizon:{h}', None
            x = y
        return None, (x, t, r, used, seen)

    def remaining(self, stops, state):
        """Optimistic route check for the unvisited tasks from the end of the prefix."""
        x, t, r, used, seen = state
        model = self.model
        rest = [i for i in range(len(self.tasks)) if i not in seen]
        nodes = rest+[x, self.depot]
        sub = [[self.matrix[a][b] for b in nodes] for a in nodes]
        n = len(rest)
        D = closure(sub, n)
        E = [[_energy(model.rate, v) for v in row] for row in D]
        R = [_energy(model.rate, sub[i][n+1]) for i in range(n+2)]
        demand = sum((model.required[self.tasks[i]] for i in rest), Fraction(0))
        carried = model.capacity if (model.origin or 'DEPOT' in stops) else min(model.capacity, model.onboard)
        stops_needed = max(0, math.ceil((demand-carried)/model.capacity)) if demand > carried else 0
        problem = RouteInput(n=n, deadline=[self.deadline[i] for i in rest], dist=D, reserve=R, energy=E,
                             t0=t, r0=r, recharge=self.recharge, service=self.s, service_energy=self.se,
                             preparation=self.p, horizon=self.H, stops=stops_needed,
                             slots=model.slots-len(stops), end_stops=True)
        return solve(problem).feasible


def children(model, tasks, prefix):
    """Next stops after ``prefix`` under the reductions; 'END' closes the sequence at the depot.

    ``room`` counts the slots left, the final depot included. A task needs room for
    the tasks still unvisited after it and the final depot; an intermediate depot stop
    must be followed by at least one visit.
    """
    if model.first is not None and not prefix:
        return [model.first]
    last = prefix[-1] if prefix else ('DEPOT' if model.origin else None)
    visited = {s for s in prefix if s != 'DEPOT'}
    room = model.slots-len(prefix)
    missing = len(set(tasks)-visited)
    out = []
    for t in tasks:
        after = missing-(t not in visited)
        if t != last and room >= after+2:
            out.append(t)
    if last != 'DEPOT' and room >= max(missing, 1)+2:
        out.append('DEPOT')
    if not missing and last != 'DEPOT' and room >= 1 and (prefix or not model.origin):
        out.append('END')
    return out


def leg_times(frame, stops):
    """Lower flight times of each leg and reserve return of a complete sequence, as Fractions."""
    m = frame.matrix
    x, legs, reserves = frame.start, [], {}
    if not frame.model.origin:
        reserves['initial'] = Fraction(m[frame.start][frame.depot], TICK)
    else:
        reserves['initial'] = Fraction(0)
    for h, stop in enumerate(stops, 1):
        y = frame.node(stop)
        legs.append(Fraction(m[x][y], TICK))
        if stop != 'DEPOT':
            reserves[str(h)] = Fraction(m[y][frame.depot], TICK)
        x = y
    return legs, reserves


def leaf_proof(scenario, frame, stops):
    """('closed', proof data) or ('open', None) for a complete sequence with lower times."""
    legs, reserves = leg_times(frame, stops)
    try:
        built = uav_problem(scenario, frame.model.uid, stops, legs, reserves)
    except BranchRejected as error:
        return 'closed', dict(rejected=str(error))
    status, value = solve_uav(built, exclusion=True)
    if status == 'EMPTY':
        return 'closed', dict(farkas={k: str(v) for k, v in value.items()})
    return 'open', None


def verify_leaf(scenario, frame, stops, data):
    legs, reserves = leg_times(frame, stops)
    try:
        built = uav_problem(scenario, frame.model.uid, stops, legs, reserves)
    except BranchRejected as error:
        return data.get('rejected') == str(error)
    return 'farkas' in data and verify_uav_exclusion(built, data['farkas'])


def search(scenario, frame, *, route_for, limit, budget_check=None):
    """Depth-first search. Generator returning ('infeasible', tree) | ('route', route) | ('open', reason).

    ``route_for(stops)`` returns a route accepted by the UAV's rows with actual path
    times, or None. ``tree`` maps prefix keys to closure records.
    """
    tasks = frame.tasks
    model = frame.model
    tree = {}
    stack = [()]
    nodes = 0
    open_leaves = []
    while stack:
        prefix = stack.pop()
        nodes += 1
        if nodes > limit:
            return 'open', dict(reason='node limit', nodes=nodes, sequences=open_leaves)
        if nodes % 25 == 0:
            yield
        key = '|'.join(prefix)
        failure, state = frame.walk(list(prefix))
        if failure:
            tree[key] = dict(kind='prefix', reason=failure)
            continue
        if not frame.remaining(list(prefix), state):
            tree[key] = dict(kind='bound')
            continue
        options = children(model, tasks, list(prefix))
        for option in options:
            if option == 'END':
                stops = list(prefix)+['DEPOT']
                status, data = leaf_proof(scenario, frame, stops)
                yield
                leaf_key = key+'|END' if key else 'END'
                if status == 'closed':
                    tree[leaf_key] = dict(kind='leaf', **data)
                    continue
                route = route_for(stops)
                yield
                if route is not None:
                    return 'route', route
                open_leaves.append(stops)
                tree[leaf_key] = dict(kind='open')
        tree[key] = dict(kind='branch', children=[o for o in options])
        for option in reversed([o for o in options if o != 'END']):
            stack.append(prefix+(option,))
    if open_leaves:
        return 'open', dict(reason='gap between lower and achieved times', nodes=nodes, sequences=open_leaves)
    return 'infeasible', dict(tree=tree, nodes=nodes)


def verify_tree(scenario, frame, tree, *, limit=10**6):
    """Replay a closed search tree from the root without optimizers."""
    model, tasks = frame.model, frame.tasks
    stack, visited = [()], 0
    while stack:
        prefix = stack.pop()
        visited += 1
        if visited > limit:
            return False
        key = '|'.join(prefix)
        record = tree.get(key)
        if record is None:
            return False
        failure, state = frame.walk(list(prefix))
        if record['kind'] == 'prefix':
            if failure is None or failure != record['reason']:
                return False
            continue
        if failure is not None:
            return False
        if record['kind'] == 'bound':
            if frame.remaining(list(prefix), state):
                return False
            continue
        if record['kind'] != 'branch':
            return False
        options = children(model, tasks, list(prefix))
        if record['children'] != options:
            return False
        for option in options:
            if option == 'END':
                leaf = tree.get(key+'|END' if key else 'END')
                if leaf is None or leaf['kind'] != 'leaf' or not verify_leaf(scenario, frame, list(prefix)+['DEPOT'], leaf):
                    return False
            else:
                stack.append(prefix+(option,))
    return True
