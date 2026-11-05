"""Comparison arms without proofs: GR, GR-c and LR (comparison protocol, Section 3).

All arms share CMI's flight-time table (chord times and the same path
improvement), the one-UAV quantity rows and the exact checker, so differences come
from the strategy. A plan counts only when the exact checker accepts it.

- GR: global replanning from scratch. Regret-2 insertion of every task into empty
  routes, then local moves (relocate, swap, segment reversal, add or remove a depot
  stop), minimizing lateness first and total flight time second.
- GR-c: the same local search started from the incumbent, minimizing lateness first
  and the number of changed decisions second.
- LR: local greedy repair. Late deliveries in deadline order; for each, re-route the
  late leg, move the task earlier in its route, or move it to the cheapest position
  of another route; keep the first change that fixes it without making another
  delivery late, and never undo a change. Then UAVs whose estimated energy falls short
  (battery or return reserve), one at a time: re-route their legs, add a depot stop,
  or move one of their tasks to the cheapest position of another route; keep the first
  change that clears the shortfall without a late delivery or a new shortfall. A
  shortfall LR cannot clear is left to the exact checker.

Lateness and the payload and energy penalties use achieved flight times and a
loaded-energy estimate; they only steer the search. The exact checker decides.
"""
from fractions import Fraction
import random

from env.plan import active_count
from recovery.local_search import bounds
from .accounting import BudgetExpired, Clock
from .levels import Instance

BIG = Fraction(10**6)


class _Fail(Exception):
    pass


class Routes:
    """Stop lists per UAV (final depot implied), evaluated with achieved flight times."""

    def __init__(self, instance):
        self.instance = instance
        ctx = instance.context(4)
        self.table, self.oracle = ctx.table, ctx.oracle
        self.models = self.oracle.models
        d = instance.scenario.data
        self.incumbent = {}
        for u, r in d['incumbent']['routes'].items():
            stops = list(r['stops'][:active_count(r)])
            if stops and stops[-1] == 'DEPOT':
                stops.pop()
            self.incumbent[u] = stops
        self.owner = dict(d['incumbent']['assignment'])
        self.committed_a = set(d['commitments']['A'])
        self.affected = set(instance.true_u0)
        self.cache = {}
        self.short = {}

    def time(self, uid, a, b):
        return Fraction(0) if a == b else self.table.upper(uid, a, b)

    def full(self, uid, stops):
        m = self.models[uid]
        return list(stops)+['DEPOT'] if (stops or not m.origin) else []

    def cost(self, uid, stops):
        """(lateness + penalties, flight time) of one route with achieved times."""
        key = uid, tuple(stops)
        if key in self.cache:
            return self.cache[key]
        m = self.models[uid]
        full = self.full(uid, stops)
        # Load per sortie: the mandatory demand of the first visits it contains.
        sorties, current, seen = [], Fraction(0), set()
        for site in full:
            if site == 'DEPOT':
                sorties.append(current)
                current = Fraction(0)
            elif site not in seen:
                seen.add(site)
                current += m.required[site]
        start_load = m.capacity if m.origin else m.onboard
        t = m.departure(bool(full))
        prev, seen, late, flight, penalty = m.start, set(), Fraction(0), Fraction(0), Fraction(0)
        short = Fraction(0)         # energy below zero at a depot or below the return to it
        load = min(start_load, sorties[0]) if sorties else Fraction(0)
        penalty += max(Fraction(0), (sorties[0] if sorties else 0)-start_load)
        energy, k = m.budget(bool(full)), 0
        for h, site in enumerate(full, 1):
            p = m.depot if site == 'DEPOT' else m.position[site]
            dt = self.time(uid, prev, p)
            t += dt
            flight += dt
            energy -= m.coef_v*(m.empty+m.mass*load)*dt
            if site == 'DEPOT':
                short += max(Fraction(0), -energy)
                k += 1
                if h < len(full):
                    t += m.preparation
                    energy = m.cap-m.reserve_wh
                    load = min(m.capacity, sorties[k])
                    penalty += max(Fraction(0), sorties[k]-m.capacity)
            else:
                t += m.service
                energy -= m.service_energy
                if site not in seen:
                    seen.add(site)
                    load = max(Fraction(0), load-m.required[site])
                    if m.deadline[site] is not None and t > m.deadline[site]:
                        late += t-m.deadline[site]
                back = self.time(uid, p, m.depot)
                short += max(Fraction(0), m.coef_v*(m.empty+m.mass*load)*back-energy)
            prev = p
        penalty += short
        late += max(Fraction(0), t-m.horizon)
        penalty += max(0, len(full)-m.slots)
        if m.first is not None and (not full or full[0] != m.first):
            penalty += BIG
        result = (late+penalty, flight)
        self.cache[key] = result
        self.short[key] = short
        return result

    def energy_short(self, uid, stops):
        """The energy (battery and return-reserve) part of the penalty of one route."""
        self.cost(uid, stops)
        return self.short[uid, tuple(stops)]

    def total(self, routes):
        late = flight = Fraction(0)
        for uid, stops in routes.items():
            a, b = self.cost(uid, stops)
            late += a
            flight += b
        return late, flight

    def changes(self, routes):
        """Reassigned tasks, sequence edits and changed UAVs against the incumbent."""
        count = 0
        for uid, stops in routes.items():
            old = [t for t in self.incumbent[uid] if t != 'DEPOT']
            if list(stops) != self.incumbent[uid]:
                count += 1
            before = {t: (old[i-1] if i else None) for i, t in enumerate(old)}
            tasks = [t for t in stops if t != 'DEPOT']
            for i, t in enumerate(tasks):
                if self.owner.get(t) != uid or before.get(t, '-') != (tasks[i-1] if i else None):
                    count += 1
        return count

    def realize(self, routes):
        """Quantity rows per changed or affected UAV, then the exact checker."""
        built = {}
        for uid, stops in routes.items():
            m = self.models[uid]
            tasks = tuple(sorted({t for t in stops if t != 'DEPOT'}))
            if (uid not in self.affected and list(stops) == self.incumbent[uid]
                    and all(self.owner.get(t) == uid for t in tasks)):
                continue
            route = None
            for variant in self.oracle._variants(m, self.full(uid, stops), limit=8):
                route = self.oracle._route(m, tasks, variant)
                if route is not None:
                    break
            if route is None:
                return None, None
            built[uid] = route
        plan, reserves = self.instance.assemble(built)
        return self.instance.exact(plan, reserves, start=0)

    def improve_late(self, routes):
        """Better paths on the legs of late routes (shared optimizer); True if a time dropped."""
        changed = False
        for uid, stops in routes.items():
            if self.cost(uid, stops)[0] == 0:
                continue
            m = self.models[uid]
            prev = m.start
            for site in self.full(uid, stops):
                p = m.depot if site == 'DEPOT' else m.position[site]
                if prev != p and self.table.improve(uid, prev, p):
                    changed = True
                prev = p
        if changed:
            self.cache.clear()
        return changed


def _clean(stops, origin):
    """No consecutive depot stops, no leading depot stop after a ground origin, no trailing one."""
    out = []
    for s in stops:
        if s == 'DEPOT' and ((out and out[-1] == 'DEPOT') or (not out and origin)):
            continue
        out.append(s)
    while out and out[-1] == 'DEPOT':
        out.pop()
    return out


def _neighbours(R, routes, rng):
    """Relocate, swap, reverse and depot moves in random order (commitments respected)."""
    uids = sorted(routes)
    fixed_first = {u: R.models[u].first is not None for u in uids}
    moves = []
    for u in uids:
        stops = routes[u]
        for i, t in enumerate(stops):
            if fixed_first[u] and i == 0:
                continue
            if t == 'DEPOT':
                moves.append(('drop', u, i))
                continue
            for v in uids:
                if v != u and t in R.committed_a:
                    continue
                for j in range(1 if fixed_first[v] else 0, len(routes[v])+(0 if v == u else 1)):
                    if v != u or j != i:
                        moves.append(('relocate', u, i, v, j))
        for i in range(1 if fixed_first[u] else 0, len(stops)):
            for j in range(i+2, len(stops)+1):
                moves.append(('reverse', u, i, j))
        for j in range(1 if fixed_first[u] else 0, len(stops)+1):
            moves.append(('depot', u, j))
    for a in range(len(uids)):
        for b in range(a, len(uids)):
            u, v = uids[a], uids[b]
            for i, t in enumerate(routes[u]):
                for j, s in enumerate(routes[v]):
                    if (u == v and j <= i) or 'DEPOT' in (t, s):
                        continue
                    if (fixed_first[u] and i == 0) or (fixed_first[v] and j == 0):
                        continue
                    if u != v and (t in R.committed_a or s in R.committed_a):
                        continue
                    moves.append(('swap', u, i, v, j))
    rng.shuffle(moves)
    return moves


def _apply(R, routes, move):
    new = {u: list(s) for u, s in routes.items()}
    kind = move[0]
    if kind == 'drop':
        del new[move[1]][move[2]]
    elif kind == 'relocate':
        _, u, i, v, j = move
        new[v].insert(j, new[u].pop(i))
    elif kind == 'reverse':
        _, u, i, j = move
        new[u][i:j] = reversed(new[u][i:j])
    elif kind == 'depot':
        new[move[1]].insert(move[2], 'DEPOT')
    else:
        _, u, i, v, j = move
        new[u][i], new[v][j] = new[v][j], new[u][i]
    return {u: _clean(s, R.models[u].origin) for u, s in new.items()}


def _search(R, routes, score, clock, rng, events, found):
    """First-improvement local search; logs the first plan the exact checker accepts."""
    best, value = routes, score(routes)
    found['routes'], found['value'] = best, value
    improved = True
    while improved:
        clock.check()
        improved = False
        for move in _neighbours(R, best, rng):
            clock.check()
            candidate = _apply(R, best, move)
            v = score(candidate)
            if v < value:
                best, value, improved = candidate, v, True
                found['routes'], found['value'] = best, value
                break
        if not improved and value[0] > 0 and R.improve_late(best):
            value = score(best)
            found['value'] = value
            improved = True
        if found.get('first') is None and value[0] == 0:
            witness, level = R.realize(best)
            if witness is not None:
                found['first'] = (witness, level, clock.cpu())
                events.append(dict(kind='plan', level=level, cpu_s=clock.cpu(), wall_s=clock.wall(), first=True))
            else:
                found['first'] = False
    return best, value


def _regret(R, clock):
    """Regret-2 insertion of every remaining task into empty routes (commitments first)."""
    d = R.instance.scenario.data
    routes = {u: ([m.first] if m.first not in (None, 'DEPOT') else ['DEPOT'] if m.first == 'DEPOT' else [])
              for u, m in R.models.items()}
    placed = {s for stops in routes.values() for s in stops}
    pending = [t for t in sorted(d['incumbent']['assignment']) if t not in placed]
    while pending:
        clock.check()
        choice = None
        for t in pending:
            options = []
            for u in ([R.owner[t]] if t in R.committed_a else sorted(routes)):
                base = R.cost(u, routes[u])
                for j in range(1 if R.models[u].first is not None else 0, len(routes[u])+1):
                    c = R.cost(u, routes[u][:j]+[t]+routes[u][j:])
                    options.append(((c[0]-base[0])*BIG+(c[1]-base[1]), u, j))
            options.sort()
            regret = options[1][0]-options[0][0] if len(options) > 1 else BIG*BIG
            key = (regret, -options[0][0], t)
            if choice is None or key > choice[0]:
                choice = (key, options[0][1], options[0][2], t)
        _, u, j, t = choice
        routes[u].insert(j, t)
        pending.remove(t)
    return routes


def _result(instance, clock, best, events, arm, status):
    upper = None if best is None else best[1]
    out = dict(version='certify-v2-run', arm=arm, bounds=bounds(set(), upper), events=events,
               level_status=status, affected=instance.true_u0, mask_u0=instance.u0, plan=None,
               plan_level=upper, clock=clock.summary(), effort=dict(instance.effort))
    if best is not None:
        out['plan'] = dict(witness=best[0], level=best[1], cpu_s=best[2])
    return out


def run_gr(scenario, budget_s, config=None, *, from_incumbent=False, seed=0):
    clock = Clock(budget_s)
    with clock.charge('setup'):
        instance = Instance(scenario, clock, {**(config or {}), 'proofs': False})
        R = Routes(instance)
    rng = random.Random(seed)
    events, found, status = [], {}, 'running'
    best = None
    try:
        with clock.charge('search'):
            if from_incumbent:
                routes = {u: list(s) for u, s in R.incumbent.items()}

                def score(rs):
                    late, flight = R.total(rs)
                    return (late, R.changes(rs), flight)
            else:
                routes = _regret(R, clock)

                def score(rs):
                    return R.total(rs)
            routes, value = _search(R, routes, score, clock, rng, events, found)
            status = 'local_optimum'
            if value[0] == 0:
                witness, level = R.realize(routes)
                if witness is not None:
                    best = (witness, level, clock.cpu())
                    events.append(dict(kind='plan', level=level, cpu_s=clock.cpu(), wall_s=clock.wall(), final=True))
    except BudgetExpired:
        status = 'budget'
    if best is None and found.get('first'):
        best = found['first']
    return _result(instance, clock, best, events, 'GR-c' if from_incumbent else 'GR', status)


def run_lr(scenario, budget_s, config=None):
    clock = Clock(budget_s)
    with clock.charge('setup'):
        instance = Instance(scenario, clock, {**(config or {}), 'proofs': False})
        R = Routes(instance)
    events, best, status = [], None, 'running'
    routes = {u: list(s) for u, s in R.incumbent.items()}

    def late_tasks(rs):
        out = []
        for uid, stops in rs.items():
            m = R.models[uid]
            full = R.full(uid, stops)
            t = m.departure(bool(full))
            prev, seen = m.start, set()
            for site in full:
                p = m.depot if site == 'DEPOT' else m.position[site]
                t += R.time(uid, prev, p)
                if site == 'DEPOT':
                    t += m.preparation
                else:
                    t += m.service
                    if site not in seen:
                        seen.add(site)
                        if m.deadline[site] is not None and t > m.deadline[site]:
                            out.append((m.deadline[site], site, uid))
                prev = p
        return sorted(out)

    def acceptable(rs, site, before):
        now = {s for _, s, _ in late_tasks(rs)}
        return site not in now and now <= before-{site}

    def short_uavs(rs):
        return {u for u, stops in rs.items() if R.energy_short(u, stops) > 0}

    def recharged(rs, uid, before):
        return not late_tasks(rs) and short_uavs(rs) <= before-{uid}

    def repair_energy(uid):
        """Clear one UAV's energy shortfall; returns the new routes or None."""
        before = short_uavs(routes)
        m = R.models[uid]
        # (a) Re-route its legs.
        prev = m.start
        for s in R.full(uid, routes[uid]):
            p = m.depot if s == 'DEPOT' else m.position[s]
            if prev != p:
                R.table.improve(uid, prev, p)
            clock.check()
            prev = p
        R.cache.clear()
        if recharged(routes, uid, before):
            return routes
        # (b) Add a depot stop, latest position first.
        for j in range(len(routes[uid]), 0 if m.first is not None else -1, -1):
            trial = {u: list(s) for u, s in routes.items()}
            trial[uid] = _clean(trial[uid][:j]+['DEPOT']+trial[uid][j:], m.origin)
            clock.check()
            if trial[uid] != routes[uid] and recharged(trial, uid, before):
                return trial
        # (c) Move one of its tasks to the cheapest position of another route, last task first.
        for i in range(len(routes[uid])-1, -1, -1):
            site = routes[uid][i]
            if site == 'DEPOT' or site in R.committed_a or (m.first is not None and i == 0):
                continue
            options = []
            for v in sorted(routes):
                if v == uid:
                    continue
                base = R.cost(v, routes[v])[1]
                for j in range(1 if R.models[v].first is not None else 0, len(routes[v])+1):
                    options.append((R.cost(v, routes[v][:j]+[site]+routes[v][j:])[1]-base, v, j))
            for _, v, j in sorted(options):
                clock.check()
                trial = {u: list(s) for u, s in routes.items()}
                del trial[uid][i]
                trial[uid] = _clean(trial[uid], m.origin)
                trial[v].insert(j, site)
                if recharged(trial, uid, before):
                    return trial
        return None

    given_up = set()
    try:
        with clock.charge('search'):
            while True:
                clock.check()
                late = late_tasks(routes)
                if not late:
                    short = sorted(short_uavs(routes)-given_up)
                    if not short:
                        break
                    repaired = repair_energy(short[0])
                    if repaired is None:
                        given_up.add(short[0])      # the exact checker decides
                    else:
                        routes = repaired
                    continue
                _, site, uid = late[0]
                before = {s for _, s, _ in late}
                m = R.models[uid]
                fixed = False
                # (a) Re-route the late leg and the legs before it.
                prev = m.start
                for s in R.full(uid, routes[uid]):
                    p = m.depot if s == 'DEPOT' else m.position[s]
                    if prev != p:
                        R.table.improve(uid, prev, p)
                    clock.check()
                    if s == site:
                        break
                    prev = p
                R.cache.clear()
                fixed = acceptable(routes, site, before)
                # (b) Move the task earlier in its own route.
                if not fixed:
                    i = routes[uid].index(site)
                    for j in range(i-1, -1, -1):
                        if m.first is not None and j == 0:
                            continue
                        trial = {u: list(s) for u, s in routes.items()}
                        trial[uid].insert(j, trial[uid].pop(i))
                        clock.check()
                        if acceptable(trial, site, before):
                            routes, fixed = trial, True
                            break
                # (c) Move it to the cheapest position of another route.
                if not fixed and site not in R.committed_a:
                    options = []
                    for v in sorted(routes):
                        if v == uid:
                            continue
                        base = R.cost(v, routes[v])[1]
                        for j in range(1 if R.models[v].first is not None else 0, len(routes[v])+1):
                            options.append((R.cost(v, routes[v][:j]+[site]+routes[v][j:])[1]-base, v, j))
                    for _, v, j in sorted(options):
                        clock.check()
                        trial = {u: list(s) for u, s in routes.items()}
                        trial[uid].remove(site)
                        trial[v].insert(j, site)
                        if acceptable(trial, site, before):
                            routes, fixed = trial, True
                            break
                if not fixed:
                    raise _Fail()
            witness, level = R.realize(routes)
            if witness is not None:
                best = (witness, level, clock.cpu())
                events.append(dict(kind='plan', level=level, cpu_s=clock.cpu(), wall_s=clock.wall()))
                status = 'repaired'
            else:
                status = 'exact_check_failed'
    except _Fail:
        status = 'no_repair'
    except BudgetExpired:
        status = 'budget'
    return _result(instance, clock, best, events, 'LR', status)
