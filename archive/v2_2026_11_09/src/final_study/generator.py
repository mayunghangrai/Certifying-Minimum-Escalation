"""Factorial-study (FS) missions: six factors, disrupted plans only.

docs/SCENARIO_DESIGN_2026_10_14.md, Sections 2-3. The base mission is P1's
(``escalation_study.missions._geometry``: random_pair geometry, round-robin sweep
assignment, nearest-neighbour order, straight legs, calm previous forecast,
airspeeds 1, 1.275, 1.56 km/h, service and preparation 0.01 h, 4 x 4 cells).
What changes:

- fleet size m and tasks per UAV k are factors (n = m k tasks);
- deadline u_i + max(1 min, c_i sigma tau) with urgency class c_i in {1, 10, 50}
  (balanced thirds at random) and slack level sigma a factor; tau is the makespan;
- battery capacity = requirement + beta x scale (``battery_reference``), beta a factor;
- the update is one cell crossed by a leg that starts after half the makespan and
  ends at a task, with a direction uniform over 12; strengths 2/5, 3/5, 4/5 of the
  slowest airspeed (speed bound 4/5);
- update times 0, 1/4 and 1/2 of the makespan (snapshots under D1');
- admission: the previous plan is feasible, 1 <= |U0| <= m/2 at the reference
  variant (3/5, t = 0) and Level 0 is certified infeasible there.

Every attempt, accepted or not, stays in the ledger. No label is read.
"""
from copy import deepcopy
from fractions import Fraction
import random

from certify_v2.accounting import BudgetExpired, Clock
from certify_v2.levels import Instance
from continuous.physics import split_static_path, stationary_duration
from continuous.validation import previous_premise
from continuous_benchmark.cases import _decimal
from env.local_scope import affected_uavs
from env.plan import active_count
from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update
from escalation_study.missions import DIRECTIONS, _decimal_vector, _geometry, battery_reference, previous_delivery_times
from escalation_study.snapshots import build_snapshot, conservation, timeline

STRENGTHS = ('2/5', '3/5', '4/5')
TIMES = ('0', '1/4', '1/2')
CLASSES = (1, 10, 50)
SIGMA = {'tight': '1/400', 'medium': '1/100', 'loose': '1/25'}       # kept after the pilot (14 Oct)
BETA = {'tight': '3/20', 'medium': '1/2', 'ample': '4'}
MINUTE = Fraction(1, 60)
REFERENCE = (1, 0)          # strength index of 3/5, update time 0


def mission_id(prefix, m, k, sigma, beta, family, seed):
    return f'{prefix}_{m}x{k}_{sigma}_{beta}_{family}_{seed}'


def variant_id(mission, ri, ti):
    return f'{mission}_r{ri}_t{ti}'


def leg_windows(p):
    """Previous-forecast start interval and end site of every incumbent leg."""
    s = Scenario(p)
    events = timeline(s)
    out = []
    for uid, items in events.items():
        route = p['incumbent']['routes'][uid]
        for kind, h, start, end in items:
            if kind == 'fly':
                out.append(dict(uid=uid, slot=h, start=start, end=end, site=route['stops'][h-1],
                                path=route['paths'][h-1]))
    return out


def crossed_cells(scenario, path):
    cells = []
    for a, b, cell in split_static_path(scenario, path):
        if a != b and cell not in cells:
            cells.append(cell)
    return cells


def eligible_cells(p, tau):
    """(uid, slot, cell) where a leg into a task enters the cell after half the makespan.

    Under the calm previous forecast a UAV reaches each piece of its leg at the leg's
    start time plus the flight time of the pieces before it. A cell entered after
    tau/2 still lies ahead of that UAV at every update time (0, tau/4, tau/2).
    """
    s = Scenario(p)
    out = set()
    for leg in leg_windows(p):
        if leg['site'] == 'DEPOT':
            continue
        t = leg['start'][0]
        for a, b, cell in split_static_path(s, leg['path']):
            if a == b:
                continue
            if t >= tau/2:
                out.add((leg['uid'], leg['slot'], cell))
            t += stationary_duration(s, leg['uid'], [list(map(float, a)), list(map(float, b))])[0]
    return sorted(out)


def headwind(leg_path):
    """The direction among the 12 with the most negative dot product with the leg."""
    (ax, ay), (bx, by) = leg_path[0], leg_path[-1]
    dx, dy = Fraction(str(bx))-Fraction(str(ax)), Fraction(str(by))-Fraction(str(ay))
    return min(DIRECTIONS, key=lambda v: Fraction(v[0])*dx+Fraction(v[1])*dy)


def assign_classes(tasks, rng):
    order = sorted(tasks)
    classes = [CLASSES[j % 3] for j in range(len(order))]
    rng.shuffle(classes)
    return dict(zip(order, classes))


def deadlines(times, tau, classes, sigma):
    return {t: _decimal(hi+max(MINUTE, classes[t]*Fraction(sigma)*tau), True)
            for t, (_, hi) in sorted(times.items())}


def level0_screen(scenario, seconds=30):
    """The disruption admission check: 'disrupted' (Level 0 certified infeasible),
    'not_disrupted' (a Level-0 plan), 'screening_unresolved' (no proof and no plan within
    the time) or 'screening_error: ...'. Only a proof admits; only a plan is no disruption."""
    clock = Clock(seconds)
    try:
        search = Instance(scenario, clock).level0()
        while True:
            clock.check()
            next(search)
    except StopIteration as stop:
        return {'proof': 'disrupted', 'plan': 'not_disrupted'}.get(stop.value[0], 'screening_unresolved')
    except BudgetExpired:
        return 'screening_unresolved'
    except Exception as error:      # recorded in the ledger, never read as "not disrupted"
        return f'screening_error: {type(error).__name__}: {error}'


def build_variants(p, cell, direction, strengths, times, *, rule='D1p'):
    """Scenario payloads for every strength and update time of one update draw.

    ``cell``: one cell index, or a tuple of them (the LS deficit recipe's 2 x 2 block) that
    all receive the same wind."""
    cells = (cell,) if isinstance(cell, int) else tuple(cell)
    v_min = min(Fraction(str(u['airspeed_kmh'])) for u in p['mission']['vehicles'])
    out = {}
    for ri, r in enumerate(strengths):
        wind = _decimal_vector(tuple(Fraction(r)*v_min*Fraction(c) for c in direction))
        q = deepcopy(p)
        for c in cells:
            q['wind']['received']['values'][c][0] = wind
        q['wind']['update_support'] = [[q['wind']['cells'][c]['id'], 0] for c in cells]
        base = Scenario(q).to_dict()
        for ti, t in enumerate(times):
            if Fraction(t) == 0:
                out[ri, ti] = base
            else:
                snap, provenance = build_snapshot(base, t, received_wind=(cells[0], wind), rule=rule)
                # The snapshot applies the received wind only at its end, to one cell; the
                # other cells of a block get the same wind there.
                for c in cells[1:]:
                    snap['wind']['received']['values'][c][0] = list(wind)
                    snap['wind']['update_support'].append([snap['wind']['cells'][c]['id'], 0])
                snap = Scenario(snap).to_dict()
                if not conservation(base, snap):
                    raise ValueError('snapshot breaks stock conservation')
                out[ri, ti] = snap
    return out


def factorial_mission(m, k, sigma, beta, family, seed, *, prefix='FS', max_attempts=48,
                      strengths=STRENGTHS, times=TIMES, sigma_values=None, beta_values=None, rule='D1p',
                      admission_seconds=30):
    """Return (variants, ledger): variants map variant id -> payload (9 for the full design)."""
    sigma_value = Fraction((sigma_values or SIGMA)[sigma])
    beta_value = Fraction((beta_values or BETA)[beta])
    n = m*k
    rng = random.Random(seed)
    name = mission_id(prefix, m, k, sigma, beta, family, seed)
    ledger = dict(version='final-study-fs-sampling-v1', status='generation_failed', mission=name, m=m, k=k, n=n,
                  family=family, seed=seed, sigma=sigma, sigma_value=str(sigma_value), beta=beta,
                  beta_value=str(beta_value), strengths=list(strengths), times=list(times), rule=rule,
                  locality_limit=m//2, selection_uses_recovery_labels=False, attempts=[])
    p = None
    for attempt in range(max_attempts):
        if attempt % 12 == 0:
            geometry_seed = seed*100+attempt//12
            p = _geometry(n, m, family, geometry_seed, rng)
            p['wind']['speed_bound_kmh'] = .8
            battery = battery_reference(p, beta_value)
            times_prev = previous_delivery_times(p)
            tau = max(hi for _, hi in times_prev.values())
            classes = assign_classes(times_prev, rng)
            due = deadlines(times_prev, tau, classes, sigma_value)
            for t in p['mission']['tasks']:
                t['deadline_h'] = due[t['id']]
            options = eligible_cells(p, tau)
        log = dict(attempt=attempt, geometry_seed=geometry_seed)
        ledger['attempts'].append(log)
        if not options:
            log['outcome'] = 'no_eligible_leg'
            continue
        uid, slot, cell = rng.choice(options)
        direction = rng.choice(DIRECTIONS)
        log.update(leg=[uid, slot], cell=p['wind']['cells'][cell]['id'], direction=list(map(str, direction)))
        # The reference variant (3/5, t = 0) decides admission; build the others only then.
        reference = Scenario(build_variants(p, cell, direction, (strengths[REFERENCE[0]],), ('0',))[0, 0])
        u0 = affected_uavs(reference, diagnose_wind_update(reference))['uavs']
        log['affected_count'] = len(u0)
        if not 0 < len(u0) <= m//2:
            log['outcome'] = 'not_local'
            continue
        if not previous_premise(reference)['accepted']:
            log['outcome'] = 'previous_premise_failed'
            continue
        screen = level0_screen(reference, admission_seconds)
        if screen != 'disrupted':
            log['outcome'] = screen
            continue
        try:
            variants = build_variants(p, cell, direction, strengths, times, rule=rule)
        except ValueError as error:
            log['outcome'] = 'snapshot_failed: '+str(error)
            continue
        failure = None
        for key, payload in variants.items():
            if not previous_premise(Scenario(payload))['accepted']:
                failure = 'previous_premise_failed'
                break
        if failure:
            log['outcome'] = failure
            continue
        log['outcome'] = 'accepted'
        out, info = {}, {}
        for (ri, ti), payload in sorted(variants.items()):
            vid = variant_id(name, ri, ti)
            payload['benchmark_id'] = vid
            s = Scenario(payload)
            out[vid] = s.to_dict()
            affected = affected_uavs(s, diagnose_wind_update(s))['uavs']
            info[vid] = dict(strength=str(Fraction(strengths[ri])), time=str(Fraction(times[ti])),
                             strength_index=ri, time_index=ti, affected=affected, scenario_hash=s.content_hash(),
                             epoch=str(Fraction(str(payload['mission']['epoch_h']))))
        ledger.update(status='accepted', geometry_seed=geometry_seed, leg=[uid, slot],
                      cell=p['wind']['cells'][cell]['id'], cell_index=cell, direction=list(map(str, direction)),
                      affected=u0, battery=battery, tau=str(tau), classes=classes,
                      deadlines={t: str(Fraction(str(v))) for t, v in due.items()},
                      previous_delivery={t: [str(lo), str(hi)] for t, (lo, hi) in sorted(times_prev.items())},
                      variants=info)
        return out, ledger
    return {}, ledger
