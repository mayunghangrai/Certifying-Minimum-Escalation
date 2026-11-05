"""The five level questions as resumable searches (plan Sections 4-6).

Each level search is a generator: it yields after every unit of work (a route
check, a bound refinement, a path improvement, a linear check) so the ladder can
share one CPU budget between levels, and returns

- ('plan', witness): a plan accepted by the exact checker, or
- ('proof', record id): no plan exists in the level's patch union, or
- ('open', reason): the level could not be decided.

``Instance`` holds what all levels share: the flight-time table, the route
oracle and the evidence store. Under the noER ablation every level gets its own.
"""
from copy import deepcopy
from fractions import Fraction
import math

from continuous.physics import stationary_duration
from env.local_scope import affected_uavs, patch_contains, scope_family
from env.plan import active_count, coordinates
from env.scenario import _thaw
from env.wind_dependency import diagnose_wind_update
from escalation_study.ladder import witness_level
from level2.quantities import _solve
from recovery.local_search import digest
from recovery.transfers import build_transfer_problem, materialize
from recovery.linear import rational
from recovery.transfers import BranchRejected
from .oracle import Evidence, RouteOracle, UavModel
from .route import TICK, ceil_ticks, floor_ticks
from .table import FlightTable
from .uav import solve_uav, uav_problem

DEFAULTS = dict(tier=3, final_tier=None, max_refinement=16, exhaust_limit=4000, proofs=True, share=True,
                digits=18, max_operations=100000, max_rows=10000, fixed_exclusions=True)


class Context:
    """Table, oracle and evidence used by one search (shared by all levels unless noER)."""

    def __init__(self, scenario, clock, config, table=None):
        if table is not None:
            table.clock = clock
            self.table = table
        else:
            self.table = FlightTable(scenario, digits=config['digits'], max_refinement=config['max_refinement'],
                                     clock=clock)
        self.evidence = Evidence()
        self.oracle = RouteOracle(scenario, self.table, self.evidence, tier=config['tier'],
                                  final_tier=config['final_tier'], clock=clock,
                                  exhaust_limit=config['exhaust_limit'])


class Instance:
    def __init__(self, scenario, clock, config=None, *, u0=None, table=None):
        self.scenario, self.clock = scenario, clock
        self.config = {**DEFAULTS, **(config or {})}
        d = scenario.data
        self.diagnostic = diagnose_wind_update(scenario)
        self.true_u0 = affected_uavs(scenario, self.diagnostic)['uavs']
        self.u0 = sorted(self.true_u0 if u0 is None else u0)
        self.fleet = sorted(d['state']['fleet'])
        self.patches = {k: scope_family(scenario, k, self.u0) for k in range(5)}
        self.allowance_patches = {}     # Level-3 patches at another helper allowance b (CMI-mu)
        self.shared = Context(scenario, clock, self.config, table) if self.config['share'] else None
        self.contexts = {}
        self.records = []           # level proof records (L0/L1 fixed routes, assignment trees)
        self.effort = dict(exact_checks=0, exact_accepted=0, assignment_nodes=0, leaves=0)

    def _record(self, record):
        record['id'] = len(self.records)
        self.records.append(record)
        return record['id']

    def patches_at(self, b):
        if b not in self.allowance_patches:
            self.allowance_patches[b] = scope_family(self.scenario, 3, self.u0, helper_budget=b)
        return self.allowance_patches[b]

    def context(self, level):
        if self.shared is not None:
            return self.shared
        if level not in self.contexts:
            self.contexts[level] = Context(self.scenario, self.clock, self.config)
        return self.contexts[level]

    # ---- exact check ---------------------------------------------------------------
    def assemble(self, routes, *, keep_quantities=False):
        p = self.scenario.to_dict()
        plan, reserves = p['incumbent'], p['reserve_paths']
        depot = p['mission']['depot_xy']
        bounds = {u['id']: u['slot_bound'] for u in p['mission']['vehicles']}
        for uid, route in routes.items():
            bound, stops = bounds[uid], route['stops']
            r = plan['routes'][uid]
            n = len(stops)
            r['stops'] = stops+[None]*(bound-n)
            r['paths'] = [list(map(list, path)) for path in route['paths']]+[[list(depot)]]*(bound-n)
            if not keep_quantities:
                r['deliveries'], r['loads'] = [0]*(bound+1), [0]*(bound+1)
                for key, value in route.get('quantities', {}).items():
                    h, a = key.split(':')
                    (r['deliveries'] if a == 'x' else r['loads'])[int(h)] = float(Fraction(value))
            reserves[uid] = deepcopy(route['reserves'])
            for t in route['tasks']:
                plan['assignment'][t] = uid
        return plan, reserves

    def exact(self, plan, reserves, *, start=0, stop=4, allowance=None):
        """Exact checker over the smallest patch (levels ``start`` to ``stop``) whose A/S/P
        mask contains the plan. A level search passes its own level as ``stop``, so it never
        accepts a plan that needs a higher level's quantity releases. With ``allowance`` b,
        only the Level-3 patches at allowance b are tried, so no quantity outside them moves.

        Released quantities are solved exactly; unreleased ones keep incumbent values.
        Returns (witness, level) or (None, None).
        """
        old = coordinates(self.scenario.data)
        new = coordinates(self.scenario.data, plan)
        candidates = ([(k, p) for k in range(start, stop+1) for p in self.patches[k]] if allowance is None
                      else [(3, p) for p in self.patches_at(allowance)])
        for k, patch in candidates:
            if any(new[a][key] != old[a][key] for a in 'ASP' for key in old[a] if key not in patch.releases[a]):
                continue
            candidate = deepcopy(plan)
            for key in old['L']:
                if key not in patch.releases['L']:
                    uid, h, a = key.split(':')
                    candidate['routes'][uid]['deliveries' if a == 'x' else 'loads'][int(h)] = old['L'][key]
            self.effort['exact_checks'] += 1
            with self.clock.charge('exact'):
                witness = self._quantity_witness(candidate, reserves, patch)
            if witness is not None:
                self.effort['exact_accepted'] += 1
                witness['patch'] = dict(level=k, participants=list(patch.participants))
                if allowance is not None:
                    witness['patch']['allowance'] = allowance
                level = witness_level(self.scenario, witness, self.true_u0)[0]
                return witness, level
        return None, None

    def _quantity_witness(self, plan, reserves, patch):
        """The exact quantity witness of ``level2.quantities.evaluate_quantities`` (same rows,
        same upper path times from the official integrator, same record), with path times
        cached for this run. The independent replay re-checks it with
        ``verify_quantity_witness``."""
        table = self.context(4).table
        try:
            compiled = build_transfer_problem(self.scenario, plan, reserves, patch.releases, exact=True,
                                              duration_provider=lambda uid, path, time: table.exact_duration(uid, path)[1])
        except (BranchRejected, ValueError, ArithmeticError):
            return None
        result = _solve(compiled.problem, self.config['max_operations'], self.config['max_rows'], exclusion=False)
        if not (result.status == 'WITNESS' and result.exact and compiled.problem.accepts(result.values)):
            return None
        projected = materialize(compiled, result.values)
        reserves = _thaw(reserves) if not isinstance(reserves, dict) else deepcopy(reserves)
        return dict(kind='quantity_primal_v1', scenario_hash=self.scenario.content_hash(), plan=projected,
                    reserve_paths=reserves, values=[str(v) for v in result.values],
                    columns=[list(c) for c in compiled.columns], digits=self.config['digits'],
                    candidate_hash=digest(projected), reserve_hash=digest(reserves))

    # ---- Levels 0 and 1: the incumbent sequence ----------------------------------------
    def _fixed_route(self, ctx, uid, level, *, upper):
        """One UAV's incumbent sequence and quantities with lower or achieved times.

        Returns (status, data): ('EMPTY', proof dict) | ('WITNESS', paths) | ('UNRESOLVED', reason).
        """
        d = self.scenario.data
        route = d['incumbent']['routes'][uid]
        n = active_count(route)
        if not n:
            return 'WITNESS', ([], {})
        model = ctx.oracle.models[uid]
        released = {k for p in self.patches[level] for k in p.releases['P']}
        stops = list(route['stops'][:n])
        legs, paths, sources = [], [], []
        prev = model.start
        for h, path in enumerate(route['paths'][:n], 1):
            goal = model.depot if stops[h-1] == 'DEPOT' else model.position[stops[h-1]]
            if f'{uid}:{h}' in released and prev != goal:
                if upper:
                    legs.append(ctx.table.upper(uid, prev, goal))
                    paths.append(ctx.table.path(uid, prev, goal))
                else:
                    legs.append(Fraction(ctx.evidence.cite(ctx.table, uid, prev, goal), TICK))
                sources.append(['pair', list(prev), list(goal)])
            else:
                lo, hi = ctx.table.exact_duration(uid, path)
                legs.append(hi if upper else Fraction(floor_ticks(lo), TICK))
                paths.append([list(p) for p in path])
                sources.append(['path', h])
            prev = goal
        reserves, reserve_paths = {}, {}
        if model.origin:
            reserves['initial'], reserve_paths['initial'] = Fraction(0), [list(model.depot)]
        else:
            a = model.start
            reserves['initial'] = (ctx.table.upper(uid, a, model.depot) if upper
                                   else Fraction(ctx.evidence.cite(ctx.table, uid, a, model.depot), TICK))
            reserve_paths['initial'] = ctx.table.path(uid, a, model.depot)
        for h, s in enumerate(stops, 1):
            if s != 'DEPOT':
                a = model.position[s]
                if a == model.depot:
                    reserves[str(h)], reserve_paths[str(h)] = Fraction(0), [list(a)]
                elif upper:
                    reserves[str(h)], reserve_paths[str(h)] = ctx.table.upper(uid, a, model.depot), ctx.table.path(uid, a, model.depot)
                else:
                    reserves[str(h)] = Fraction(ctx.evidence.cite(ctx.table, uid, a, model.depot), TICK)
        fixed = {}
        for h in range(n+1):
            fixed[h, 'x'] = rational(route['deliveries'][h])
            fixed[h, 'y'] = rational(route['loads'][h])
        try:
            built = uav_problem(self.scenario, uid, stops, legs, reserves, released=set(), fixed=fixed)
        except BranchRejected as error:
            if upper:
                return 'UNRESOLVED', str(error)
            return 'EMPTY', dict(rejected=str(error), legs=[str(x) for x in legs], sources=sources,
                                 reserves={k: str(v) for k, v in reserves.items()})
        status, value = solve_uav(built, exclusion=not upper)
        if status == 'EMPTY' and not upper:
            return 'EMPTY', dict(farkas={k: str(v) for k, v in value.items()}, legs=[str(x) for x in legs],
                                 sources=sources, reserves={k: str(v) for k, v in reserves.items()})
        if status == 'WITNESS' and upper:
            return 'WITNESS', (paths, reserve_paths)
        return 'UNRESOLVED', str(value)

    def _fixed_legs(self, ctx, uid, level):
        """Legs whose time the level may still improve: released paths and reserve returns."""
        model = ctx.oracle.models[uid]
        r = self.scenario.data['incumbent']['routes'][uid]
        released = {k for p in self.patches[level] for k in p.releases['P']}
        prev, pairs = model.start, []
        if not model.origin and model.start != model.depot:
            pairs.append((model.start, model.depot))
        for h, s in enumerate(r['stops'][:active_count(r)], 1):
            goal = model.depot if s == 'DEPOT' else model.position[s]
            if f'{uid}:{h}' in released and prev != goal:
                pairs.append((prev, goal))
            if s != 'DEPOT' and goal != model.depot:
                pairs.append((goal, model.depot))
            prev = goal
        return pairs

    def _fixed_level(self, level):
        """Levels 0 and 1. Every UAV keeps its sequence and quantities; Level 1 frees U0 paths.

        Each round checks the undecided UAVs with lower and with achieved times; then the
        leg with the widest interval among them is improved (a better path) or refined (a
        finer potential), one leg at a time, until every UAV is decided or no leg can move.

        With ``fixed_exclusions`` off (strict PH) there are no lower-time checks and no
        refinements: each leg gets a quick and a deep path search, and the level ends open.
        """
        ctx = self.context(level)
        table = ctx.table
        exclusions = self.config['fixed_exclusions']
        undecided = list(self.fleet if level == 0 else self.u0)
        witnesses = {}
        while True:
            for uid in list(undecided):
                if exclusions:
                    status, data = self._fixed_route(ctx, uid, level, upper=False)
                    yield
                    if status == 'EMPTY':
                        return 'proof', self._record(dict(kind='fixed_route_lower_v2', level=level, uid=uid, **data))
                status, data = self._fixed_route(ctx, uid, level, upper=True)
                yield
                if status == 'WITNESS':
                    witnesses[uid] = data
                    undecided.remove(uid)
            if not undecided:
                routes = {}
                d = self.scenario.data
                for uid, (paths, reserves) in witnesses.items():
                    r = d['incumbent']['routes'][uid]
                    n = active_count(r)
                    routes[uid] = dict(stops=list(r['stops'][:n]), paths=paths, reserves=reserves,
                                       tasks=[t for t in r['stops'][:n] if t != 'DEPOT'])
                plan, reserves = self.assemble(routes, keep_quantities=True)
                witness, k = self.exact(plan, reserves, start=0, stop=level)
                yield
                if witness is not None:
                    return 'plan', (witness, k)
                return 'open', 'per-UAV rows hold but the exact check failed'
            options = []
            for uid in undecided:
                for a, b in self._fixed_legs(ctx, uid, level):
                    entry = table.entry(uid, a, b)
                    table.upper(uid, a, b)
                    if exclusions and entry.tight():
                        continue
                    refine = exclusions and table.refinable(uid, a, b) and entry.tier < ctx.oracle.final_tier
                    # Per leg: a quick path search, bounds up to refinement 4, a deep path
                    # search, then the finest bounds.
                    if entry.improved == 0:
                        action = 'quick'
                    elif refine and entry.tier < 3:
                        action = 'refine'
                    elif entry.improved == 1:
                        action = 'deep'
                    elif refine:
                        action = 'refine'
                    else:
                        continue
                    options.append((entry.upper-entry.lower, uid, a, b, action))
            if not options:
                return 'open', 'interval gap at the finest refinement' if exclusions else 'path improvements exhausted'
            _, uid, a, b, action = max(options, key=lambda o: o[0])
            if action == 'quick':
                table.improve(uid, a, b)
            elif action == 'deep':
                table.improve(uid, a, b, deep=True)
            else:
                table.refine(uid, a, b)
            yield

    def level0(self):
        return (yield from self._fixed_level(0))

    def level1(self):
        return (yield from self._fixed_level(1))

    # ---- Level 2: reorder each affected UAV's own tasks -------------------------------
    def level2(self, proofs=None):
        proofs = self.config['proofs'] if proofs is None else proofs if proofs is None else proofs
        ctx = self.context(2)
        oracle = ctx.oracle
        d = self.scenario.data
        own = {uid: [t for t, o in d['incumbent']['assignment'].items() if o == uid] for uid in self.u0}
        if proofs:
            for uid in self.u0:
                status, pid = yield from oracle.relax(uid, own[uid])
                if status == 'infeasible':
                    return 'proof', self._record(dict(kind='level2_route_v2', uid=uid, tasks=sorted(own[uid]),
                                                      proof=pid))
        routes, failed = {}, []
        for uid in self.u0:
            route = yield from oracle.plan(uid, own[uid])
            if route is None:
                failed.append(uid)
            else:
                routes[uid] = route
        if not failed:
            plan, reserves = self.assemble(routes)
            witness, k = self.exact(plan, reserves, start=1, stop=2)
            yield
            if witness is not None:
                return 'plan', (witness, k)
        if not proofs:
            return 'open', 'no plan found'
        for uid in failed or self.u0:
            status, data = yield from oracle.exhaust(uid, own[uid])
            if status == 'infeasible':
                return 'proof', self._record(dict(kind='level2_route_v2', uid=uid, tasks=sorted(own[uid]),
                                                  proof=data))
            if status == 'route':
                routes[uid] = data
        if all(uid in routes for uid in self.u0):
            plan, reserves = self.assemble(routes)
            witness, k = self.exact(plan, reserves, start=1, stop=2)
            yield
            if witness is not None:
                return 'plan', (witness, k)
        return 'open', 'Level 2 undecided'

    # ---- Levels 3 and 4: assignment search -------------------------------------------
    def _assignment(self, level, patch, ctx, proofs=None, allowance=None):
        """Search owners of the released tasks in one patch. Generator, see module doc.
        ``allowance``: the patch is a Level-3 patch at that helper allowance (``exact``)."""
        oracle, d = ctx.oracle, self.scenario.data
        proofs = self.config['proofs'] if proofs is None else proofs
        participants = list(patch.participants)
        pool = sorted(patch.releases['A'])
        old = d['incumbent']['assignment']
        fixed = {u: sorted(t for t, o in old.items() if o == u and t not in patch.releases['A']) for u in participants}
        models = oracle.models

        def urgency(t):
            m = models[participants[0]]
            return (m.deadline[t] is None, m.deadline[t] or 0, t)
        # Most constrained first: tasks no participant can serve alone come first.
        single = {}
        for t in pool:
            feasible = 0
            for u in participants:
                if proofs:
                    status, _ = yield from oracle.relax(u, fixed[u]+[t])
                    feasible += status == 'feasible'
                else:
                    feasible += 1
            single[t] = feasible
        order = sorted(pool, key=lambda t: (single[t], urgency(t)))
        nodes = {}
        record = dict(kind='assignment_tree_v2', level=level, participants=participants, order=order,
                      fixed=fixed, nodes=nodes)
        deferred, open_leaves = [], 0

        def owner_sets(choice):
            sets = {u: list(fixed[u]) for u in participants}
            for t, u in zip(order, choice):
                sets[u].append(t)
            return sets

        def distance(u, t, sets):
            m = models[u]
            p = m.position[t]
            points = [m.start]+[m.position[x] for x in sets[u]]
            return min((a[0]-p[0])**2+(a[1]-p[1])**2 for a in points)

        # Root: every participant's fixed tasks alone.
        stack = [()]
        while stack:
            choice = stack.pop()
            key = ','.join(choice)
            self.effort['assignment_nodes'] += 1
            sets = owner_sets(choice)
            closed = None
            check = [choice[-1]] if choice else participants
            if proofs:
                for u in check:
                    status, pid = yield from oracle.relax(u, sets[u])
                    if status == 'infeasible':
                        closed = dict(kind='route', uid=u, proof=pid)
                        break
            if closed:
                nodes[key] = closed
                continue
            if len(choice) == len(order):
                self.effort['leaves'] += 1
                routes, failed = {}, []
                for u in participants:
                    route = yield from oracle.plan(u, sets[u])
                    if route is None:
                        failed.append(u)
                    else:
                        routes[u] = route
                if not failed:
                    plan, reserves = self.assemble(routes)
                    witness, k = self.exact(plan, reserves, start=1, stop=level, allowance=allowance)
                    yield
                    if witness is not None:
                        return 'plan', (witness, k)
                deferred.append((key, sets, failed))
                nodes[key] = dict(kind='open')
                continue
            t = order[len(choice)]
            current = old.get(t)
            ranked = sorted(participants, key=lambda u: (u != current, distance(u, t, sets), u))
            nodes[key] = dict(kind='branch')
            for u in reversed(ranked):
                stack.append(choice+(u,))
        if not proofs:
            return 'open', 'no plan found'
        # Complete searches for the owners whose route could not be planned.
        for key, sets, failed in deferred:
            closed = None
            for u in failed or participants:
                status, data = yield from oracle.exhaust(u, sets[u])
                if status == 'infeasible':
                    closed = dict(kind='route', uid=u, proof=data)
                    break
            if closed:
                nodes[key] = closed
                continue
            routes = {}
            for u in participants:
                route = oracle.routes.get((u, frozenset(sets[u])))
                if route is None and oracle.exhausted.get((u, frozenset(sets[u])), ('',))[0] == 'route':
                    route = oracle.exhausted[(u, frozenset(sets[u]))][1]
                if route is None:
                    break
                routes[u] = route
            if len(routes) == len(participants):
                plan, reserves = self.assemble(routes)
                witness, k = self.exact(plan, reserves, start=1, stop=level, allowance=allowance)
                yield
                if witness is not None:
                    return 'plan', (witness, k)
            open_leaves += 1
        if open_leaves:
            return 'open', f'{open_leaves} assignments undecided'
        return 'proof', self._record(record)

    def level3(self, proofs=None, allowance=None):
        """``allowance`` b: Level 3 with b helpers outside U0 instead of the scenario's (CMI-mu).
        A plan then changes at most b UAVs outside U0; a proof shows every plan changes more."""
        ctx = self.context(3)
        patches = list(self.patches[3] if allowance is None else self.patches_at(allowance))
        searches = [self._assignment(3, patch, ctx, proofs, allowance) for patch in patches]
        results = [None]*len(searches)
        while any(r is None for r in results):
            for i, search in enumerate(searches):
                if results[i] is not None:
                    continue
                try:
                    next(search)
                except StopIteration as stop:
                    results[i] = stop.value
                    if results[i][0] == 'plan':
                        return results[i]
                yield
        if all(r[0] == 'proof' for r in results):
            if allowance is not None:
                return 'proof', self._record(dict(kind='allowance_patches_v1', allowance=allowance,
                                                  trees=[r[1] for r in results]))
            return 'proof', self._record(dict(kind='level3_patches_v2', trees=[r[1] for r in results]))
        return 'open', '; '.join(r[1] for r in results if r[0] == 'open')

    def level4(self, proofs=None):
        ctx = self.context(4)
        return (yield from self._assignment(4, self.patches[4][0], ctx, proofs))

    def search(self, level, proofs=None):
        """The level's search; ``proofs=False`` looks for plans only (PH, and CMI above its lowest open level)."""
        if level <= 1:
            return (self.level0, self.level1)[level]()
        return (self.level2, self.level3, self.level4)[level-2](proofs)
