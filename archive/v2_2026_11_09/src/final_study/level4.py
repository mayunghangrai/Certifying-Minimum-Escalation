"""Level-4 constructions for the level suite: a witness first, then deadlines that need it.

Review of 15 October: the earlier Level-4 recipe rarely produced Level-4 cases. Each
construction here builds an explicit plan W that changes two UAVs outside U0, so no
Level-3 patch (U0 plus one helper, b = 1) contains it, and sets deadlines W meets:

- the tasks W moves get W's delivery time, never below the previous plan's certified
  delivery time under the previous forecast (so the previous plan stays feasible; these
  tasks have no slack beyond the previous schedule);
- the affected UAVs' remaining tasks are urgent: W's delivery time, with the same floor;
- any other task on a route W changes keeps its deadline unless W would be late, in
  which case it rises to W's delivery time; all other deadlines stay.

Mechanisms:

- ``deficit``: two tasks the affected UAVs are now in trouble with (typically one each of
  two affected UAVs, in different sectors, slowed by a 2 x 2 block update) go to two
  different helpers; no affected UAV can deliver either on time and no single helper can
  deliver both.
- ``chain``: a task u is now in trouble with goes to the only helper h1 that can deliver it
  on time; h1 then cannot keep one of its own tasks, which goes to a second helper h2.

A task is in trouble when the affected UAV now delivers it after the previous plan's time,
or can no longer reach it on its battery (amended 16 October): every task from the first
stop at which the route's estimated battery or return reserve runs short. In W, an affected
UAV's remaining route must be within battery, with a recharge stop if one makes it so.
Battery is estimated as ``Routes.cost`` does, except that a UAV in the air carries everything
on board until it reaches the depot. Every candidate W that passes the screen below is put
through the exact checker with its deadlines (at most ``EXACT_CHECKS`` per draw); a
candidate that fails is skipped and the search goes on.

Times come from the received-wind scenario (``Routes``), with every leg's path improved
once, and only steer the construction. A screen of alternatives (insertions into fixed
orders, with a depot stop where the load needs one, and a helper trading one of its own
tasks back) rejects draws in which U0 alone or U0 with one helper evidently meets the
deadlines. Nothing here labels a
draw: the caller checks W with the exact checker, and the reference run alone decides
the class.
"""
from copy import deepcopy
from fractions import Fraction

from certify_v2.accounting import Clock
from certify_v2.baselines import Routes, _clean
from certify_v2.levels import Instance
from continuous_benchmark.cases import _decimal
from env.fixed_plan import evaluate_plan
from env.local_scope import affected_uavs, scope_family
from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update
from escalation_study.ladder import witness_level
from level2.quantities import verify_quantity_witness
from recovery.local_search import bounds

MECHANISMS = ('deficit', 'chain')
EXACT_CHECKS = 6        # candidates per draw put through the exact checker
MARGIN = Fraction(1, 10**9)     # hours above the witness's delivery time
SEPARATION = Fraction(1, 10**6)     # hours a lower-level plan must be later to be excluded


def _leg(R, uid, a, b):
    """Achieved flight time of a leg after one path improvement (a solver finds such paths)."""
    if a != b and (uid, a, b) not in R.improved:
        R.improved.add((uid, a, b))
        if R.table.improve(uid, a, b):
            R.cache.clear()
    return R.time(uid, a, b)


def finish_times(R, uid, stops):
    """Service-completion time of each task's first visit on a stop list."""
    m = R.models[uid]
    full = R.full(uid, stops)
    t, prev, out = m.departure(bool(full)), m.start, {}
    for site in full:
        p = m.depot if site == 'DEPOT' else m.position[site]
        t += _leg(R, uid, prev, p)
        if site == 'DEPOT':
            t += m.preparation
        else:
            t += m.service
            out.setdefault(site, t)
        prev = p
    return out


def _energy_short(R, uid, stops):
    """Estimated battery and return-reserve shortfall of one route: ``Routes.cost``'s estimate,
    except that a UAV in the air carries everything on board until it reaches the depot (it
    cannot shed load in flight)."""
    m = R.models[uid]
    full = R.full(uid, stops)
    sorties, current, seen = [], Fraction(0), set()
    for site in full:
        if site == 'DEPOT':
            sorties.append(current)
            current = Fraction(0)
        elif site not in seen:
            seen.add(site)
            current += m.required[site]
    load = m.onboard if not m.origin else min(m.capacity, sorties[0]) if sorties else Fraction(0)
    energy, k, short, prev, seen = m.budget(bool(full)), 0, Fraction(0), m.start, set()
    for h, site in enumerate(full, 1):
        p = m.depot if site == 'DEPOT' else m.position[site]
        energy -= m.coef_v*(m.empty+m.mass*load)*R.time(uid, prev, p)
        if site == 'DEPOT':
            short += max(Fraction(0), -energy)
            k += 1
            if h < len(full):
                energy = m.cap-m.reserve_wh
                load = min(m.capacity, sorties[k])
        else:
            energy -= m.service_energy
            if site not in seen:
                seen.add(site)
                load = max(Fraction(0), load-m.required[site])
            short += max(Fraction(0), m.coef_v*(m.empty+m.mass*load)*R.time(uid, p, m.depot)-energy)
        prev = p
    return short


def _movable(R, uid, stops):
    first = R.models[uid].first is not None
    return [s for i, s in enumerate(stops) if s != 'DEPOT' and s not in R.committed_a and not (first and i == 0)]


def _loads_ok(R, uid, stops):
    """Every sortie within the payload capacity and no estimated energy shortfall."""
    m = R.models[uid]
    load, capacity, seen = Fraction(0), (m.capacity if m.origin else m.onboard), set()
    for site in stops:
        if site == 'DEPOT':
            load, capacity = Fraction(0), m.capacity
        elif site not in seen:
            seen.add(site)
            load += m.required[site]
            if load > capacity:
                return False
    return _energy_short(R, uid, stops) == 0


def _within_battery(R, uid, stops):
    """The route itself if it is within load and battery, else the variant with one recharge
    stop that delivers earliest, else None."""
    if _loads_ok(R, uid, stops):
        return stops
    m = R.models[uid]
    options = []
    for i in range(1 if m.first is not None or m.origin else 0, len(stops)+1):
        new = _clean(stops[:i]+['DEPOT']+stops[i:], m.origin)
        if new != stops and _loads_ok(R, uid, new):
            options.append((sum(finish_times(R, uid, new).values()), new))
    return min(options)[1] if options else None


def _insertions(R, uid, stops, site):
    """Every position of ``site``; when the load or energy fails, also with one depot stop
    before it."""
    m = R.models[uid]
    lowest = 1 if m.first is not None else 0
    for j in range(lowest, len(stops)+1):
        new = stops[:j]+[site]+stops[j:]
        if _loads_ok(R, uid, new):
            yield new
            continue
        for i in range(max(lowest, 0 if not m.origin else 1), j+1):
            depot = _clean(new[:i]+['DEPOT']+new[i:], m.origin)
            if depot != new and _loads_ok(R, uid, depot):
                yield depot


def _best(R, uid, stops, site):
    """The insertion that delivers ``site`` earliest: (finish of site, new stops); (None, None)
    if no insertion keeps the load and energy."""
    options = [(finish_times(R, uid, new)[site], new) for new in _insertions(R, uid, stops, site)]
    return min(options, key=lambda x: (x[0], len(x[1]))) if options else (None, None)


def _earliest(R, routes, uids, site):
    """(finish, uid) of the UAV among ``uids`` that delivers ``site`` earliest, or None."""
    options = [(f, v) for f, v in ((_best(R, v, routes[v], site)[0], v) for v in uids) if f is not None]
    return min(options) if options else None


def _can_take(R, uid, stops, sites, due):
    """Some insertion of ``sites`` (in this order of insertion) keeps every task on time."""
    if not sites:
        f = finish_times(R, uid, stops)
        return all(f[s] <= due[s] for s in f if s in due)
    return any(_can_take(R, uid, new, sites[1:], due) for new in _insertions(R, uid, stops, sites[0]))


def _without(stops, *sites):
    out = [s for s in stops if s not in sites]
    while out and out[-1] == 'DEPOT':
        out.pop()
    return out


def _patch_takes(R, routes, plan, u0, v, sites, due):
    """U0 plus helper v evidently meets ``due`` with ``sites`` off the affected UAVs: v takes them
    (in either order), possibly after giving one of its own tasks to an affected UAV."""
    orders = [list(sites), list(reversed(sites))] if len(sites) > 1 else [list(sites)]
    if any(_can_take(R, v, routes[v], order, due) for order in orders):
        return True
    for r in _movable(R, v, routes[v]):
        rest = _without(routes[v], r)
        if (any(_can_take(R, v, rest, order, due) for order in orders)
                and any(_can_take(R, u, plan[u], [r], due) for u in u0)):
            return True
    return False


def _due(R, plan, key, previous, urgent):
    """Deadlines of every task with a deadline once ``plan`` is the witness (module docstring);
    ``urgent``: the affected UAVs whose remaining tasks become urgent."""
    current = next(iter(R.models.values())).deadline
    due = {s: d for s, d in current.items() if d is not None}
    for uid, stops in plan.items():
        if stops == R.incumbent[uid] and uid not in R.affected:
            continue
        for site, t in finish_times(R, uid, stops).items():
            if site in key:
                due[site] = key[site]
            elif uid in urgent:
                due[site] = max(previous[site], t)
            elif site in due:
                due[site] = max(due[site], t)
    return due


def _troubled(R, routes, u, previous):
    """u's movable tasks it now delivers after the previous plan's previous-forecast time, or
    can no longer reach on its battery (from the first stop at which the estimated battery or
    return reserve runs short)."""
    stops = routes[u]
    f = finish_times(R, u, stops)
    short_from = next((i for i, s in enumerate(stops) if s != 'DEPOT' and _energy_short(R, u, stops[:i+1]) > 0),
                      len(stops))
    movable = set(_movable(R, u, stops))
    return [s for i, s in enumerate(stops) if s in movable and (f[s] > previous[s] or i >= short_from)]


def _deficit(R, routes, u0, outside, previous, exact):
    late = [t for u in u0 for t in _troubled(R, routes, u, previous)]
    for t1 in late:
        for t2 in late:
            if t1 >= t2:
                continue
            # Any two helpers, those that deliver earliest first.
            times = {t: {v: f for v in outside for f in [_best(R, v, routes[v], t)[0]] if f is not None}
                     for t in (t1, t2)}
            pairs = sorted((max(f1, f2), h1, h2, f1, f2) for h1, f1 in times[t1].items()
                           for h2, f2 in times[t2].items() if h1 != h2)
            for _, h1, h2, f1, f2 in pairs:
                plan = dict(routes)
                for u in u0:
                    plan[u] = _within_battery(R, u, _without(routes[u], t1, t2))
                if any(plan[u] is None for u in u0):
                    continue
                plan[h1] = _best(R, h1, routes[h1], t1)[1]
                plan[h2] = _best(R, h2, routes[h2], t2)[1]
                due = _due(R, plan, {t1: max(previous[t1], f1), t2: max(previous[t2], f2)},
                           previous, set(u0))
                # No affected UAV keeps either; no single helper takes both.
                if any(_can_take(R, u, plan[u], [t], due) for u in u0 for t in (t1, t2)):
                    continue
                if any(_patch_takes(R, routes, plan, u0, v, [t1, t2], due) for v in outside):
                    continue
                if not exact(plan, due):
                    continue
                owners = sorted({u for u in u0 if t1 in routes[u] or t2 in routes[u]})
                return plan, due, dict(u=owners, helpers=[h1, h2], tasks=[t1, t2])
    return None


def _chain(R, routes, u, outside, previous, exact):
    for t1 in _troubled(R, routes, u, previous):
        first = _earliest(R, routes, outside, t1)
        if first is None:
            continue
        h1 = first[1]
        others = [v for v in outside if v != h1]
        for s1 in _movable(R, h1, routes[h1]):
            g1, h1_route = _best(R, h1, _without(routes[h1], s1), t1)
            second = _earliest(R, routes, others, s1)
            if g1 is None or second is None:
                continue
            f2, h2 = second
            plan = dict(routes)
            plan[u] = _within_battery(R, u, _without(routes[u], t1))
            if plan[u] is None:
                continue
            plan[h1] = h1_route
            plan[h2] = _best(R, h2, routes[h2], s1)[1]
            due = _due(R, plan, {t1: max(previous[t1], g1), s1: max(previous[s1], f2)}, previous,
                       {u})
            # Only h1 takes t1, and then not s1 as well (nor after giving u another task); u takes
            # neither.
            if any(_patch_takes(R, routes, plan, [u], v, [t1], due) for v in others):
                continue
            if _can_take(R, h1, routes[h1], [t1], due) or any(
                    _can_take(R, h1, _without(routes[h1], r), [t1], due) and _can_take(R, u, plan[u], [r], due)
                    for r in _movable(R, h1, routes[h1]) if r != s1):
                continue
            if _can_take(R, u, plan[u], [t1], due) or _can_take(R, u, plan[u], [s1], due):
                continue
            if not exact(plan, due):
                continue
            return plan, due, dict(u=u, helpers=[h1, h2], tasks=[t1, s1])
    return None


def construct(payload, mechanism, previous):
    """(plan routes, deadlines, info) or None. ``previous``: previous-forecast upper delivery
    time per task."""
    R = Routes(Instance(Scenario(payload), Clock()))
    R.improved = set()
    routes = {u: list(s) for u, s in R.incumbent.items()}
    outside = sorted(set(routes)-R.affected)
    checks = []

    def exact(plan, due):
        """The candidate passes the exact checker at Level 4 once its deadlines are set."""
        if len(checks) >= EXACT_CHECKS:
            return False
        q = deepcopy(payload)
        for t in q['mission']['tasks']:
            if t['id'] in due and t['deadline_h'] is not None and due[t['id']] != Fraction(str(t['deadline_h'])):
                t['deadline_h'] = _decimal(due[t['id']], True)
        checks.append(witness(q, plan)[1] == 4)
        return checks[-1]
    if mechanism == 'deficit':
        return _deficit(R, routes, sorted(R.affected), outside, previous, exact)
    for u in sorted(R.affected):
        found = _chain(R, routes, u, outside, previous, exact)
        if found:
            return found
    return None


def delivery_times(payload, witness):
    """Latest time each task receives a positive delivery in a witness's plan (received wind,
    the witness's reserve paths): the time its deadline constrains."""
    plan = witness['plan']
    evaluation = evaluate_plan(Scenario(payload), plan, projection='received', reserve_paths=witness['reserve_paths'])
    out = {}
    for uid, route in plan['routes'].items():
        for h, site in enumerate(route['stops'], 1):
            if site not in (None, 'DEPOT') and route['deliveries'][h] > 0:
                t = Fraction(str(evaluation.records[uid][h]['delivery_h']))
                out[site] = max(out.get(site, t), t)
    return out


def tighten(payload, w_times, p_times, floor):
    """Deadlines that exclude a plan P found below Level 4 and keep the witness W (amended
    16 October): each task P delivers later than W gets W's time (plus 1e-9 h, rounded up to
    the stored decimals), never below the previous plan's ``floor``, when that lies below the
    current deadline and at least ``SEPARATION`` below P's time (beyond the checkers'
    tolerance). Empty when P is no later than W wherever a deadline could drop."""
    current = {t['id']: t['deadline_h'] for t in payload['mission']['tasks']}
    out = {}
    for site, tp in p_times.items():
        if site not in w_times or current.get(site) is None:
            continue
        new = Fraction(str(_decimal(max(floor[site], w_times[site]+MARGIN), True)))
        if new+SEPARATION < tp and new < Fraction(str(current[site])):
            out[site] = new
    return out


def verify_witness(payload, w):
    """(ok, level) of a construction witness, checked as the replay checks a plan: the exact
    quantity checker on its patch (true U0 mask), and its level against the true U0."""
    scenario = Scenario(payload)
    true_u0 = affected_uavs(scenario, diagnose_wind_update(scenario))['uavs']
    patch = next((p for p in scope_family(scenario, w['patch']['level'], true_u0)
                  if list(p.participants) == w['patch']['participants']), None)
    if patch is None or not verify_quantity_witness(scenario, w, patch.releases):
        return False, None
    return True, witness_level(scenario, w, true_u0)[0]


def pool(payload, label, w):
    """A level-suite label pooled with its draw's construction witness (amended 16 October):
    the label's exclusions (replayed with the label) and the witness's level as an upper
    bound, as the protocol pools plans with reference proofs. Minimum 4 when the label
    excludes Levels 0-3 and the witness checks at Level 4. The label itself is unchanged."""
    ok, level = verify_witness(payload, w)
    b = label['result']['bounds']
    excluded = set(b['excluded_levels']) if label['audit']['ok'] else set()
    upper = b['upper']
    if ok:
        upper = level if upper is None else min(upper, level)
    return dict(witness_ok=ok, witness_level=level, bounds=bounds(excluded, upper))


def witness(payload, plan):
    """The exact checker's verdict on ``plan`` (with the improved paths the construction
    timed): (witness, level) or (None, None)."""
    R = Routes(Instance(Scenario(payload), Clock()))
    R.improved = set()
    for uid, stops in plan.items():
        finish_times(R, uid, stops)
    return R.realize(plan)
