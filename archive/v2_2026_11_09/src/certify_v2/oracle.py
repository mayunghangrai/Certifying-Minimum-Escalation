"""Per-UAV route evidence shared by every level of one instance.

For a UAV u and a task set S the oracle answers three questions:

- ``relax``: does the optimistic route check (``route.solve`` with certified lower
  bounds) admit S? A negative answer is a proof for S and for every superset of S,
  because dropping a task from a feasible route keeps it feasible.
- ``plan``: a route serving S whose one-UAV rows hold with the times of actual
  paths, found from the achievable route check and depot insertions.
- ``exhaust``: a complete search over u's stop sequences for S, closed by prefix
  bounds and by Farkas proofs on u's rows with lower flight times, or a route.

Lower bounds enter proofs on a 1e-12 h grid (rounded down), so a proof stays valid
when a leg's certificate is later replaced by a stronger one.
"""
from fractions import Fraction
import math

from env.plan import active_count
from recovery.linear import rational
from recovery.local_search import digest
from recovery.transfers import BranchRejected
from .route import RouteInput, closure, floor_ticks, ceil_ticks, hops, solve, TICK
from .uav import depot_origin, solve_uav, uav_problem, verify_uav_exclusion
from . import skeleton


def _point(p):
    return tuple(p)


class UavModel:
    """Static data of one UAV in one scenario."""

    def __init__(self, scenario, uid):
        d = scenario.data
        m, st, op = d['mission'], d['state'], d['operations']
        u = next(v for v in m['vehicles'] if v['id'] == uid)
        s = st['fleet'][uid]
        self.uid = uid
        self.depot = _point(m['depot_xy'])
        self.origin = depot_origin(d, uid)
        self.start = self.depot if self.origin else _point(s['position_xy'])
        self.epoch, self.horizon = rational(m['epoch_h']), rational(m['horizon_h'])
        self.service, self.service_energy = rational(op['service_duration_h']), rational(op['service_energy_wh'])
        self.preparation = rational(op['preparation_duration_h'])
        self.cap, self.reserve_wh = rational(u['battery_capacity_wh']), rational(u['reserve_wh'])
        self.battery = rational(s['battery_wh'])
        self.coef_v = rational(u['energy_coefficient_wh_per_kg_km'])*rational(u['airspeed_kmh'])
        self.empty = rational(u['empty_mass_kg'])
        self.rate = self.empty*self.coef_v
        mass = rational(m['commodity_unit_mass_kg'])
        self.mass = mass
        self.capacity = rational(u['payload_capacity_kg'])/mass
        self.onboard = rational(s['onboard'])
        self.slots = int(u['slot_bound'])
        self.position = {t['id']: _point(t['position_xy']) for t in m['tasks']}
        self.deadline, self.required = {}, {}
        for t in m['tasks']:
            owed = rational(t['mandatory'])-rational(st['cumulative_delivered'][t['id']])
            self.required[t['id']] = max(Fraction(0), owed)
            self.deadline[t['id']] = (rational(t['deadline_h']) if owed > 0 and t['deadline_h'] is not None
                                      else None)
        committed = [k for k in d['commitments']['S'] if k.split(':')[0] == uid]
        if any(k != f'{uid}:1' for k in committed):
            raise ValueError('only a committed first stop is supported')
        self.first = d['incumbent']['routes'][uid]['stops'][0] if committed else None
        if any(k.split(':')[0] == uid for a in ('P', 'L') for k in d['commitments'][a]):
            raise ValueError('committed paths or quantities are not supported')

    def nodes(self, tasks):
        return [self.position[i] for i in tasks]+[self.start, self.depot]

    def stops_needed(self, tasks):
        demand = sum((self.required[i] for i in tasks), Fraction(0))
        start = self.capacity if self.origin else self.onboard
        return max(0, math.ceil((demand-start)/self.capacity)) if demand > start else 0

    def departure(self, nonempty):
        return self.epoch+(self.preparation if self.origin and nonempty else 0)

    def budget(self, nonempty):
        return (self.cap if self.origin and nonempty else self.battery)-self.reserve_wh


def _energy(rate, ticks, up):
    value = rate*ticks
    return math.ceil(value) if up else math.floor(value)


def route_input(model, tasks, matrix, *, optimistic):
    """RouteInput for ``tasks`` (ordered ids) from a direct-leg tick matrix.

    Optimistic: closure over tasks and depot, quantities rounded toward feasibility.
    Achievable: direct legs, at most one depot stop per gap, rounded against it.
    Returns None when a committed first stop makes the check trivial (handled by callers).
    """
    n = len(tasks)
    rnd = floor_ticks if optimistic else ceil_ticks
    rup = ceil_ticks if optimistic else floor_ticks
    nonempty = bool(n) or not model.origin
    D = closure(matrix, n) if optimistic else [row[:] for row in matrix]
    E = [[_energy(model.rate, v, not optimistic) for v in row] for row in D]
    reserve = [_energy(model.rate, matrix[i][n+1], not optimistic) for i in range(n+2)]
    first = first_dist = first_energy = None
    if model.first is not None and model.first != 'DEPOT':
        first = tasks.index(model.first)
        first_dist = matrix[n][first]
        first_energy = _energy(model.rate, first_dist, not optimistic)
    deadline = [None if model.deadline[i] is None else rup(model.deadline[i]) for i in tasks]
    return RouteInput(n=n, deadline=deadline, dist=D, reserve=reserve, energy=E,
                      t0=rnd(model.departure(nonempty)), r0=rup(model.budget(nonempty)),
                      recharge=rup(model.cap-model.reserve_wh), service=rnd(model.service),
                      service_energy=rnd(model.service_energy), preparation=rnd(model.preparation),
                      horizon=rup(model.horizon), stops=model.stops_needed(tasks), slots=model.slots,
                      end_stops=optimistic, first=first, first_dist=first_dist or 0,
                      first_energy=first_energy or 0)


def _depot_first(model, tasks, matrix, optimistic):
    """Committed first stop at the depot: the route reaches it, then continues from there."""
    n = len(tasks)
    rnd = floor_ticks if optimistic else ceil_ticks
    rup = ceil_ticks if optimistic else floor_ticks
    leg = matrix[n][n+1]
    t = rnd(model.departure(True))+leg
    r = rup(model.budget(True))-_energy(model.rate, leg, not optimistic)
    if r < 0:
        return False, None
    if not tasks:
        return t <= rup(model.horizon), None
    inp = route_input(model, tasks, matrix, optimistic=optimistic)
    inp.first = None
    depot = n+1
    # Continue from the depot: reuse the start row for the depot and count one stop and one slot.
    inp.dist[n] = inp.dist[depot][:]
    inp.energy[n] = inp.energy[depot][:]
    inp.reserve[n] = 0
    inp.t0, inp.r0 = t+inp.preparation, inp.recharge
    inp.stops, inp.slots = max(0, inp.stops-1), inp.slots-1
    return None, inp


def check(model, tasks, matrix, *, optimistic, want_order=False):
    """Run the route check; returns RouteResult (order indexes ``tasks``)."""
    from .route import RouteResult
    if not tasks and model.origin and model.first is None:
        return RouteResult(True, order=[], finish=None)
    if model.first == 'DEPOT':
        trivial, inp = _depot_first(model, tasks, matrix, optimistic)
        if inp is None:
            return RouteResult(bool(trivial), order=[])
        result = solve(inp, want_order=want_order)
        result.depot_first = True
        return result
    inp = route_input(model, tasks, matrix, optimistic=optimistic)
    return solve(inp, want_order=want_order)


class Evidence:
    """Certificates, leg bounds and proofs of one instance (or one level under noER)."""

    def __init__(self):
        self.certificates = {}      # digest -> certificate
        self.pairs = {}             # (uid, a, b) -> digest of the strongest certificate cited
        self.proofs = []

    def cite(self, table, uid, a, b):
        """Return the tick lower bound of leg a->b and remember its certificate."""
        if tuple(a) == tuple(b):
            return 0
        cert = table.certificate(uid, a, b)
        lower = Fraction(cert['lower']) if cert else Fraction(0)
        if cert is not None and lower > 0:
            key = digest(cert)
            self.certificates.setdefault(key, cert)
            old = self.pairs.get((uid, tuple(a), tuple(b)))
            if old is None or Fraction(self.certificates[old]['lower']) < lower:
                self.pairs[uid, tuple(a), tuple(b)] = key
        return floor_ticks(lower)

    def add(self, proof):
        proof['id'] = len(self.proofs)
        self.proofs.append(proof)
        return proof['id']

    def export(self):
        used = set(self.pairs.values())
        return dict(certificates={k: v for k, v in self.certificates.items() if k in used},
                    pairs=[[uid, list(a), list(b), key] for (uid, a, b), key in sorted(self.pairs.items())],
                    proofs=self.proofs)


class RouteOracle:
    """Route evidence for one instance; caches are shared across levels unless ``share=False``."""

    def __init__(self, scenario, table, evidence, *, tier=3, final_tier=None, clock=None, exhaust_limit=4000):
        self.scenario, self.table, self.evidence, self.clock = scenario, table, evidence, clock
        self.tier = min(tier, table.max_tier)
        self.final_tier = table.max_tier if final_tier is None else min(final_tier, table.max_tier)
        self.models = {uid: UavModel(scenario, uid) for uid in scenario.data['state']['fleet']}
        self.relaxed = {}
        self.infeasible = {uid: [] for uid in self.models}
        self.routes = {}
        self.exhausted = {}
        self.exhaust_limit = exhaust_limit
        self.effort = dict(relax=0, relax_solves=0, plan=0, plan_lp=0, exhaust=0, exhaust_nodes=0)

    # ---- helpers -------------------------------------------------------------------
    def known_infeasible(self, uid, tasks):
        tasks = frozenset(tasks)
        for proven, pid in self.infeasible[uid]:
            if proven <= tasks:
                return pid
        return None

    def _lower_matrix(self, model, tasks):
        nodes = model.nodes(tasks)
        return [[self.evidence.cite(self.table, model.uid, a, b) for b in nodes] for a in nodes]

    def _upper_matrix(self, model, tasks):
        nodes = model.nodes(tasks)
        return [[0 if a == b else ceil_ticks(self.table.upper(model.uid, a, b)) for b in nodes] for a in nodes]

    def _decisive(self, model, tasks, result, matrix):
        """Direct legs on the optimistic route: closure paths of every gap, depot legs, reserves."""
        nodes = model.nodes(tasks)
        n, depot = len(tasks), len(tasks)+1
        _, nxt = closure(matrix, n, paths=True)
        pairs = set()
        x = n
        first = True
        for q, via in result.order:
            if first and model.first is not None and model.first != 'DEPOT':
                pairs.add((x, q))
            elif via:
                pairs.update(hops(nxt, x, depot))
                pairs.update(hops(nxt, depot, q))
            else:
                pairs.update(hops(nxt, x, q))
            pairs.add((q, depot))
            x, first = q, False
        pairs.update(hops(nxt, x, depot))
        if not model.origin:
            pairs.add((n, depot))
        return [(nodes[i], nodes[j]) for i, j in pairs if nodes[i] != nodes[j]]

    def _record_route_proof(self, model, tasks, matrix):
        proof = dict(kind='route_timing_v2', uid=model.uid, tasks=list(tasks), matrix=matrix)
        pid = self.evidence.add(proof)
        key = frozenset(tasks)
        self.infeasible[model.uid] = [(t, p) for t, p in self.infeasible[model.uid] if not key <= t]
        self.infeasible[model.uid].append((key, pid))
        return pid

    # ---- relax ---------------------------------------------------------------------
    def relax(self, uid, tasks, *, tier=None):
        """Generator; returns ('infeasible', proof id) or ('feasible', None)."""
        tier = self.tier if tier is None else min(tier, self.table.max_tier)
        tasks = tuple(sorted(tasks))
        key = uid, frozenset(tasks)
        pid = self.known_infeasible(uid, tasks)
        if pid is not None:
            return 'infeasible', pid
        done = self.relaxed.get(key)
        if done is not None and done >= tier:
            return 'feasible', None
        model = self.models[uid]
        self.effort['relax'] += 1
        while True:
            matrix = self._lower_matrix(model, tasks)
            result = check(model, tasks, matrix, optimistic=True, want_order=True)
            self.effort['relax_solves'] += 1
            yield
            if not result.feasible:
                return 'infeasible', self._record_route_proof(model, tasks, matrix)
            refined = False
            for a, b in sorted(self._decisive(model, tasks, result, matrix)):
                entry = self.table.entry(uid, a, b)
                if entry.tier >= tier:
                    continue
                self.table.upper(uid, a, b)
                if self.table.refinable(uid, a, b):
                    if self.table.refine(uid, a, b):
                        refined = True
                    yield
            if not refined:
                self.relaxed[key] = tier
                return 'feasible', None

    # ---- plan ----------------------------------------------------------------------
    def _route(self, model, tasks, stops):
        """Paths, reserves and a quantity check with actual path times; None if rows fail."""
        uid, depot = model.uid, model.depot
        points = [depot if s == 'DEPOT' else model.position[s] for s in stops]
        start = model.start
        prev, paths, durations = start, [], []
        for p in points:
            paths.append(self.table.path(uid, prev, p) if prev != p else [list(p)])
            durations.append(self.table.upper(uid, prev, p) if prev != p else Fraction(0))
            prev = p
        reserves, reserve_times = {}, {}
        if stops:
            if model.origin:
                reserves['initial'], reserve_times['initial'] = [list(depot)], Fraction(0)
            else:
                reserves['initial'] = self.table.path(uid, start, depot) if start != depot else [list(depot)]
                reserve_times['initial'] = self.table.upper(uid, start, depot) if start != depot else Fraction(0)
        for h, s in enumerate(stops, 1):
            if s != 'DEPOT':
                p = model.position[s]
                reserves[str(h)] = self.table.path(uid, p, depot) if p != depot else [list(depot)]
                reserve_times[str(h)] = self.table.upper(uid, p, depot) if p != depot else Fraction(0)
        self.effort['plan_lp'] += 1
        try:
            built = uav_problem(self.scenario, uid, stops, durations, reserve_times)
        except BranchRejected:
            return None
        status, values = solve_uav(built, exclusion=False)
        if status != 'WITNESS':
            return None
        return dict(uid=uid, tasks=list(tasks), stops=list(stops), paths=paths, reserves=reserves,
                    quantities={f'{h}:{a}': str(v) for (h, a), v in zip(built.columns, values)})

    def _stops(self, model, tasks, result):
        stops = ['DEPOT'] if getattr(result, 'depot_first', False) else []
        for q, via in result.order:
            stops += ['DEPOT']*via+[tasks[q]]
        return stops+['DEPOT'] if stops or tasks or not model.origin else stops

    def _lateness(self, model, stops, upper):
        """Total lateness of first visits and of the final arrival, with lower or upper times."""
        uid = model.uid
        t = model.departure(bool(stops))
        prev, seen, late = model.start, set(), Fraction(0)
        for h, site in enumerate(stops, 1):
            p = model.depot if site == 'DEPOT' else model.position[site]
            if p != prev:
                t += self.table.upper(uid, prev, p) if upper else self.table.lower(uid, prev, p)
            if site == 'DEPOT':
                if h < len(stops):
                    t += model.preparation
            else:
                t += model.service
                if site not in seen:
                    seen.add(site)
                    if model.deadline[site] is not None and t > model.deadline[site]:
                        late += t-model.deadline[site]
            prev = p
        return late+max(Fraction(0), t-model.horizon)

    def _orders(self, model, tasks, limit):
        """Candidate visiting orders: the incumbent's first, then route-check orders."""
        uid = model.uid
        incumbent = [s for s in self.scenario.data['incumbent']['routes'][uid]['stops']
                     if s not in (None, 'DEPOT') and s in tasks]
        incumbent = list(dict.fromkeys(incumbent))
        for site in sorted(set(tasks)-set(incumbent), key=lambda i: (model.deadline[i] is None,
                                                                      model.deadline[i] or 0, i)):
            best = None
            for k in range(len(incumbent)+1):
                if model.first is not None and model.first != 'DEPOT' and k == 0:
                    continue
                trial = incumbent[:k]+[site]+incumbent[k:]
                score = self._lateness(model, trial+['DEPOT'], True)
                if best is None or score < best[0]:
                    best = (score, trial)
            incumbent = best[1]
        orders = [incumbent]
        upper = check(model, tasks, self._upper_matrix(model, tasks), optimistic=False, want_order=True)
        if upper.feasible:
            orders.append([tasks[q] for q, _ in upper.order])
        lower = check(model, tasks, self._lower_matrix(model, tasks), optimistic=True, want_order=True)
        if lower.feasible:
            orders.append([tasks[q] for q, _ in lower.order])
        if len(tasks) <= 5:
            from itertools import permutations
            ranked = []
            for order in permutations(tasks):
                if model.first is not None and model.first != 'DEPOT' and order[0] != model.first:
                    continue
                late = self._lateness(model, list(order)+['DEPOT'], False)
                if late == 0:
                    ranked.append((self._lateness(model, list(order)+['DEPOT'], True), list(order)))
            orders += [o for _, o in sorted(ranked)]
        unique = []
        for order in orders:
            if order not in unique:
                unique.append(order)
        return unique[:limit]

    def plan(self, uid, tasks, *, improve=True, limit=8):
        """Generator; returns a route dict or None. Prefers the incumbent visiting order."""
        tasks = tuple(sorted(tasks))
        key = uid, frozenset(tasks)
        if key in self.routes:
            return self.routes[key]
        model = self.models[uid]
        self.effort['plan'] += 1
        if not tasks and model.origin and model.first is None:
            self.routes[key] = dict(uid=uid, tasks=[], stops=[], paths=[], reserves={}, quantities={})
            return self.routes[key]
        orders = self._orders(model, tasks, limit)
        yield
        prefix = ['DEPOT'] if model.first == 'DEPOT' else []
        tried = set()
        for order in orders:
            stops = prefix+order+['DEPOT']
            if self._lateness(model, stops, False) > 0:
                continue
            if improve and self._lateness(model, stops, True) > 0:
                prev = model.start
                for site in stops:
                    p = model.depot if site == 'DEPOT' else model.position[site]
                    for a, b in ((prev, p), (p, model.depot)):
                        if a != b:
                            self.table.improve(uid, a, b)
                            yield
                    prev = p
            for variant in self._variants(model, stops):
                if tuple(variant) in tried or self._lateness(model, variant, True) > 0:
                    continue
                tried.add(tuple(variant))
                route = self._route(model, tasks, variant)
                yield
                if route is not None:
                    self.routes[key] = route
                    return route
        self.routes[key] = None
        return None

    def _variants(self, model, stops, limit=24):
        """The sequence itself, then with one or two extra depot stops (recharge, reload)."""
        out = [stops]
        if not stops:
            return out
        body = stops[:-1]
        gaps = [i for i in range(1 if model.origin else 0, len(body)+1)
                if (i == 0 or body[i-1] != 'DEPOT') and (i == len(body) or body[i] != 'DEPOT')]
        for i in gaps:
            candidate = body[:i]+['DEPOT']+body[i:]+['DEPOT']
            if len(candidate) <= model.slots:
                out.append(candidate)
        for i in gaps:
            for j in gaps:
                if j > i+1 and len(out) < limit:
                    candidate = body[:i]+['DEPOT']+body[i:j]+['DEPOT']+body[j:]+['DEPOT']
                    if len(candidate) <= model.slots:
                        out.append(candidate)
        return out[:limit]

    # ---- exhaust -------------------------------------------------------------------
    def _improve_route(self, model, tasks, stops):
        uid = model.uid
        if self._lateness(model, stops, True) > 0:
            prev = model.start
            for site in stops:
                p = model.depot if site == 'DEPOT' else model.position[site]
                for a, b in ((prev, p), (p, model.depot)):
                    if a != b:
                        self.table.improve(uid, a, b)
                prev = p
        if self._lateness(model, stops, True) > 0:
            return None
        return self._route(model, tasks, stops)

    def exhaust(self, uid, tasks, *, rounds=3):
        """Generator; returns ('infeasible', proof id) | ('route', route) | ('open', reason)."""
        tasks = tuple(sorted(tasks))
        key = uid, frozenset(tasks)
        pid = self.known_infeasible(uid, tasks)
        if pid is not None:
            return 'infeasible', pid
        if key in self.exhausted:
            return self.exhausted[key]
        model = self.models[uid]
        self.effort['exhaust'] += 1
        outcome = ('open', 'not started')
        for _ in range(rounds):
            matrix = self._lower_matrix(model, tasks)
            frame = skeleton.Frame(model, tasks, matrix)
            status, data = yield from skeleton.search(
                self.scenario, frame, route_for=lambda stops: self._improve_route(model, tasks, stops),
                limit=self.exhaust_limit)
            self.effort['exhaust_nodes'] += data['nodes'] if isinstance(data, dict) and 'nodes' in data else 0
            if status == 'infeasible':
                proof = dict(kind='skeleton_tree_v2', uid=uid, tasks=list(tasks), matrix=matrix, tree=data['tree'])
                pid = self.evidence.add(proof)
                self.infeasible[uid] = [(t, p) for t, p in self.infeasible[uid] if not frozenset(tasks) <= t]
                self.infeasible[uid].append((frozenset(tasks), pid))
                outcome = ('infeasible', pid)
                break
            if status == 'route':
                self.routes[key] = data
                outcome = ('route', data)
                break
            outcome = ('open', data['reason'])
            if data['reason'] == 'node limit':
                break
            refined = False
            nodes = model.nodes(tasks)
            for stops in data['sequences'][:8]:
                prev = model.start
                for site in stops:
                    p = model.depot if site == 'DEPOT' else model.position[site]
                    for a, b in ((prev, p), (p, model.depot)):
                        if a != b and self.table.entry(uid, a, b).tier < self.final_tier and self.table.refinable(uid, a, b):
                            refined |= self.table.refine(uid, a, b)
                            yield
                    prev = p
            if not refined:
                break
        self.exhausted[key] = outcome
        return outcome
