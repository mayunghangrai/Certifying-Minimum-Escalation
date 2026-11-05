"""Bounded continuous repairs with independently replayable conclusions.

Only verified spatial potentials, fixed-path interval bounds and the existing
all-path physical relaxation exclude scopes. Exhausted numerical proposals
leave an unresolved interval for the minimum intervention level.
"""
from copy import deepcopy
from fractions import Fraction
import math
from time import perf_counter

from env.local_scope import affected_uavs, scope_family, change_metrics, preservation_metrics
from env.plan import active_count
from env.wind_dependency import diagnose_wind_update
from recovery.linear import rational
from recovery.local_search import bounds, digest
from recovery.physical_proofs import physical_certificate, verify_physical_certificate
from recovery.transfers import build_transfer_problem
from final_benchmark.controlled import make_plan
from final_benchmark.near_search import _proposals
from .oracle import ContinuousOracle, verify_query
from .physics import depot_origin, stationary_guard, stationary_duration
from .potential import propose_potential, verify_potential
from .validation import certify_witness, previous_premise


class BudgetExpired(RuntimeError):
    pass


def _optimistic_candidate(scenario, plan, reserves, patch):
    """Reject a fixed-quantity candidate only when zero flight costs still fail."""
    try:
        compiled = build_transfer_problem(scenario, plan, reserves, patch.releases, exact=True,
                                          duration_provider=lambda uid, path, time: 0)
        values = tuple(rational(plan['routes'][uid]['deliveries' if a == 'x' else 'loads'][h])
                       for uid, h, a in compiled.columns)
        return compiled.problem.accepts(values)
    except ValueError:
        # Geometry may still be repaired, particularly in nonconvex regions.
        return True


def continuous_plan(scenario, oracle, plan, released_paths, *, check_budget=lambda: None):
    """Optimize released nominal paths and every auxiliary reserve curve."""
    plan = deepcopy(plan)
    d = scenario.data
    tasks = {t['id']: t['position_xy'] for t in d['mission']['tasks']}
    depot, reserves = list(d['mission']['depot_xy']), {}
    for uid, route in sorted(plan['routes'].items()):
        n = active_count(route)
        reserves[uid] = {'initial': [depot]} if n else {}
        if n and not depot_origin(scenario, uid):
            # An airborne origin needs a return from its observed position.
            check_budget()
            warm = list(d['reserve_paths'].get(uid, {}).values())
            reserves[uid]['initial'] = oracle.query(uid, d['state']['fleet'][uid]['position_xy'], depot,
                                                    warm, bound=False)['path']
        for h, path in enumerate(route['paths'][:n], 1):
            if f'{uid}:{h}' in released_paths:
                check_budget()
                route['paths'][h-1] = oracle.query(uid, path[0], path[-1], [path], bound=False)['path']
            site = route['stops'][h-1]
            if site != 'DEPOT':
                check_budget()
                warm = list(d['reserve_paths'].get(uid, {}).values())+list(route['paths'][:n])
                reserves[uid][str(h)] = oracle.query(uid, tasks[site], depot, warm, bound=False)['path']
    return plan, reserves


def deadline_certificate(scenario, level, oracle, *, digits=18, diagnostic=None, check_budget=lambda: None):
    if level not in (0, 1) or stationary_guard(scenario): return None
    diagnostic = diagnostic or diagnose_wind_update(scenario)
    u0 = affected_uavs(scenario, diagnostic)['uavs']
    released = scope_family(scenario, level, u0)[0].releases['P']
    d, terms = scenario.data, []
    tasks = {t['id']: t for t in d['mission']['tasks']}
    op = d['operations']
    def deadline_slots(route):
        return [h for h, site in enumerate(route['stops'][:active_count(route)], 1)
                if site != 'DEPOT' and route['deliveries'][h] > 0 and tasks[site]['deadline_h'] is not None]
    def priority(item):
        uid, route = item
        return min((rational(tasks[route['stops'][h-1]]['deadline_h']) for h in deadline_slots(route)),
                   default=rational(d['mission']['horizon_h'])), uid
    for uid, route in sorted(d['incumbent']['routes'].items(), key=priority):
        n = active_count(route)
        relevant = deadline_slots(route)
        # Only a ground depot origin prepares before its first flight.
        start = rational(d['mission']['epoch_h'])+(rational(op['preparation_duration_h'])
                                                   if n and depot_origin(scenario, uid) else 0)
        horizon_upper = start
        for h, path in enumerate(route['paths'][:n], 1):
            horizon_upper += stationary_duration(scenario, uid, path, digits)[1]
            if route['stops'][h-1] != 'DEPOT': horizon_upper += rational(op['service_duration_h'])
            elif h < n: horizon_upper += rational(op['preparation_duration_h'])
        horizon_feasible = horizon_upper <= rational(d['mission']['horizon_h'])
        if not relevant and horizon_feasible: continue
        last_needed = max(relevant) if horizon_feasible else n
        time = start
        terms = []
        for h, path in enumerate(route['paths'][:last_needed], 1):
            field = None
            if f'{uid}:{h}' in released:
                check_budget()
                query = oracle.query(uid, path[0], path[-1], [path], bound=True)
                lower, field = Fraction(query['lower']), query['lower_certificate']
            else:
                lower = stationary_duration(scenario, uid, path, digits)[0]
            terms.append(dict(slot=h, lower=str(lower), potential=field))
            time += lower
            site = route['stops'][h-1]
            if site != 'DEPOT': time += rational(op['service_duration_h'])
            deadline = tasks[site]['deadline_h'] if site != 'DEPOT' else None
            kind, limit = None, None
            if route['deliveries'][h] > 0 and deadline is not None and time > rational(deadline):
                kind, limit = 'deadline', rational(deadline)
            elif time > rational(d['mission']['horizon_h']):
                kind, limit = 'horizon', rational(d['mission']['horizon_h'])
            if kind:
                return dict(kind='continuous_prefix_lower_v1', scenario_hash=scenario.content_hash(),
                            excluded_through=level, digits=digits, uav=uid, slot=h, task=site,
                            violation=kind, terms=terms, earliest=str(time), limit=str(limit))
            if site == 'DEPOT' and h < n: time += rational(op['preparation_duration_h'])
    return None


def verify_deadline_certificate(scenario, certificate, *, diagnostic=None):
    try:
        c, d = certificate, scenario.data
        if c['kind'] != 'continuous_prefix_lower_v1' or c['scenario_hash'] != scenario.content_hash(): return False
        level, digits, uid, slot = c['excluded_through'], c['digits'], c['uav'], c['slot']
        if isinstance(level, bool) or level not in (0, 1) or stationary_guard(scenario): return False
        if isinstance(digits, bool) or not isinstance(digits, int) or not 1 <= digits <= 60: return False
        diagnostic = diagnostic or diagnose_wind_update(scenario)
        u0 = affected_uavs(scenario, diagnostic)['uavs']
        released = scope_family(scenario, level, u0)[0].releases['P']
        route, op = d['incumbent']['routes'][uid], d['operations']
        if isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= active_count(route): return False
        if len(c['terms']) != slot: return False
        tasks = {t['id']: t for t in d['mission']['tasks']}
        time = rational(d['mission']['epoch_h'])+(rational(op['preparation_duration_h'])
                                                  if depot_origin(scenario, uid) else 0)
        for h, (path, term) in enumerate(zip(route['paths'][:slot], c['terms']), 1):
            lower, field = Fraction(term['lower']), term['potential']
            if term['slot'] != h or lower < 0: return False
            if f'{uid}:{h}' in released:
                if field is None:
                    if lower: return False
                elif (field['start'] != list(path[0]) or field['goal'] != list(path[-1])
                      or not verify_potential(scenario, uid, field) or lower != Fraction(field['lower'])):
                    return False
            elif field is not None or lower != stationary_duration(scenario, uid, path, digits)[0]:
                return False
            time += lower
            site = route['stops'][h-1]
            if site != 'DEPOT': time += rational(op['service_duration_h'])
            elif h < slot: time += rational(op['preparation_duration_h'])
        if c['task'] != site or Fraction(c['earliest']) != time: return False
        if c['violation'] == 'deadline':
            if site == 'DEPOT' or route['deliveries'][slot] <= 0 or tasks[site]['deadline_h'] is None: return False
            limit = rational(tasks[site]['deadline_h'])
        elif c['violation'] == 'horizon': limit = rational(d['mission']['horizon_h'])
        else: return False
        return Fraction(c['limit']) == limit and time > limit
    except (KeyError, ValueError, TypeError, ArithmeticError, IndexError):
        return False


def _committed_failure(scenario, uid, lower):
    """A rule every candidate violates, given a lower bound on the committed flight.

    The first stop of an airborne UAV is committed at every level, and a task
    stop is then owned by that UAV, so each candidate flies the observed position
    to that stop first with the observed payload, and serves the task no earlier.
    """
    d = scenario.data
    state, op = d['state']['fleet'][uid], d['operations']
    u = next(v for v in d['mission']['vehicles'] if v['id'] == uid)
    site = d['incumbent']['routes'][uid]['stops'][0]
    arrival = rational(d['mission']['epoch_h'])+lower
    mass = rational(u['empty_mass_kg'])+rational(d['mission']['commodity_unit_mass_kg'])*rational(state['onboard'])
    battery = rational(state['battery_wh'])-mass*rational(u['energy_coefficient_wh_per_kg_km'])*rational(u['airspeed_kmh'])*lower
    if battery < 0:
        return 'battery', battery, Fraction(0)
    if arrival > rational(d['mission']['horizon_h']):
        return 'horizon', arrival, rational(d['mission']['horizon_h'])
    if site == 'DEPOT':
        return ('depot_arrival_reserve', battery, rational(u['reserve_wh'])) if battery < rational(u['reserve_wh']) else None
    task = next(t for t in d['mission']['tasks'] if t['id'] == site)
    required = rational(task['mandatory'])-rational(d['state']['cumulative_delivered'][site])
    completion = arrival+rational(op['service_duration_h'])
    if required > 0 and task['deadline_h'] is not None and completion > rational(task['deadline_h']):
        return 'deadline', completion, rational(task['deadline_h'])
    return None


def committed_prefix_certificate(scenario, oracle, *, digits=18, check_budget=lambda: None):
    """Exclude every level when an airborne UAV cannot complete its committed first stop."""
    if stationary_guard(scenario): return None
    d = scenario.data
    tasks = {t['id']: t['position_xy'] for t in d['mission']['tasks']}
    for uid, state in sorted(d['state']['fleet'].items()):
        if state['mode'] != 'airborne' or f'{uid}:1' not in d['commitments']['S']: continue
        route = d['incumbent']['routes'][uid]
        site = route['stops'][0]
        goal = d['mission']['depot_xy'] if site == 'DEPOT' else tasks[site]
        check_budget()
        query = oracle.query(uid, state['position_xy'], goal, [route['paths'][0]], bound=True)
        lower, field = Fraction(query['lower']), query['lower_certificate']
        found = _committed_failure(scenario, uid, lower)
        if not found and field is not None and _committed_failure(scenario, uid, Fraction(query['upper'])):
            # The best path fails but the bound does not: try finer verified potentials.
            for refinement in (8, 16):
                check_budget()
                try:
                    candidate = propose_potential(scenario, uid, state['position_xy'], goal, refinement, digits)
                except (ValueError, ArithmeticError):
                    continue
                if Fraction(candidate['lower']) > lower:
                    lower, field = Fraction(candidate['lower']), candidate
                    found = _committed_failure(scenario, uid, lower)
                    if found:
                        break
        if found:
            rule, value, limit = found
            return dict(kind='committed_prefix_lower_v1', scenario_hash=scenario.content_hash(), excluded_through=4,
                        digits=digits, uav=uid, stop=site, rule=rule, lower=str(lower),
                        potential=field, value=str(value), limit=str(limit))
    return None


def verify_committed_prefix_certificate(scenario, certificate):
    try:
        c, d = certificate, scenario.data
        if (c['kind'] != 'committed_prefix_lower_v1' or c['scenario_hash'] != scenario.content_hash()
                or c['excluded_through'] != 4 or stationary_guard(scenario)): return False
        uid, site = c['uav'], c['stop']
        state, route = d['state']['fleet'][uid], d['incumbent']['routes'][uid]
        if state['mode'] != 'airborne' or f'{uid}:1' not in d['commitments']['S'] or route['stops'][0] != site:
            return False
        goal = d['mission']['depot_xy'] if site == 'DEPOT' else next(
            t['position_xy'] for t in d['mission']['tasks'] if t['id'] == site)
        lower, field = Fraction(c['lower']), c['potential']
        if field is None:
            if lower: return False
        elif (field['start'] != list(state['position_xy']) or field['goal'] != list(goal)
              or not verify_potential(scenario, uid, field) or lower != Fraction(field['lower'])):
            return False
        found = _committed_failure(scenario, uid, lower)
        return found is not None and (found[0], str(found[1]), str(found[2])) == (c['rule'], c['value'], c['limit'])
    except (KeyError, ValueError, TypeError, ArithmeticError, IndexError, StopIteration):
        return False


def verify_exclusion_certificate(scenario, certificate, *, diagnostic=None):
    if certificate.get('kind') == 'committed_prefix_lower_v1':
        return verify_committed_prefix_certificate(scenario, certificate)
    return verify_deadline_certificate(scenario, certificate, diagnostic=diagnostic)


def recover_continuous(scenario, *, max_seconds=10, max_proposals=120, refinements=(2, 4), digits=18,
                       initial_bounds=()):
    """``initial_bounds`` are verified path queries for the same wind physics.

    They only pre-fill the oracle cache; ``paths`` reports the queries used.
    """
    if (isinstance(max_proposals, bool) or not isinstance(max_proposals, int) or max_proposals < 0
            or isinstance(max_seconds, bool) or not math.isfinite(max_seconds) or max_seconds < 0):
        raise ValueError('invalid continuous search budget')
    start = perf_counter()
    report = dict(version='continuous_recovery_v1', domain='all_admissible_continuous_polylines',
                  scenario_hash=scenario.content_hash(), witness=None, exclusions=[], physical_certificates=[], paths=[],
                  full_domain=bounds([], None), unsupported=stationary_guard(scenario), change=None, preservation=None,
                  budget=dict(seconds=max_seconds, proposals=max_proposals, refinements=list(refinements), digits=digits,
                              clock='total soft limit checked between path, proof and proposal operations'),
                  effort=dict(candidate_checks=0, generated_proposals=0, first_witness_s=None, proof_s=0.,
                              setup_s=0., screen_s=0., proposal_s=0., elapsed_s=0., budget_exhausted=False,
                              events=[]))
    if report['unsupported']:
        report['effort']['elapsed_s'] = perf_counter()-start
        return report
    diagnostic = diagnose_wind_update(scenario)
    report['affected'] = affected_uavs(scenario, diagnostic)
    report['previous_premise'] = previous_premise(scenario, digits)
    if not report['previous_premise']['accepted']:
        report['unsupported'] = 'previous incumbent not certified by interval checker'
        report['effort']['elapsed_s'] = perf_counter()-start
        return report
    oracle = ContinuousOracle(scenario, refinements, digits)
    for q in initial_bounds:
        if not verify_query(scenario, q, digits):
            raise ValueError('invalid supplied continuous bound')
        oracle.cache[q['uid'], tuple(q['start']), tuple(q['goal'])] = deepcopy(q)
    effort, u0 = report['effort'], report['affected']['uavs']
    effort['setup_s'] = perf_counter()-start
    excluded = set()

    def check_budget():
        if perf_counter()-start >= max_seconds:
            effort['budget_exhausted'] = True
            raise BudgetExpired()

    def accept(plan, reserves, level, source):
        effort['candidate_checks'] += 1
        check = certify_witness(scenario, plan, reserves, level, digits, _diagnostic=diagnostic)
        if not check['accepted']: return False
        k = check['level']
        report['witness'] = dict(plan=plan, reserve_paths=reserves, validation=check,
                                 certificate_level=level, source=source)
        report['full_domain'] = bounds(excluded, k)
        report['change'] = change_metrics(scenario, plan, u0)
        report['preservation'] = preservation_metrics(scenario, plan, k, u0)
        effort['first_witness_s'] = perf_counter()-start
        effort['events'].append(dict(kind='witness', level=k, wall_s=effort['first_witness_s']))
        return True

    def exclude(certificate, physical=False):
        if not certificate: return
        verifier = verify_physical_certificate if physical else verify_exclusion_certificate
        if not verifier(scenario, certificate): raise ArithmeticError('generated exclusion failed replay')
        report['physical_certificates' if physical else 'exclusions'].append(certificate)
        excluded.update(range(certificate['excluded_through']+1))
        upper = report['witness']['validation']['level'] if report['witness'] else None
        report['full_domain'] = bounds(excluded, upper)
        effort['events'].append(dict(kind='exclusion', level=certificate['excluded_through'],
                                     wall_s=perf_counter()-start))

    screen_start = perf_counter()
    try:
        proof_start = perf_counter()
        exclude(committed_prefix_certificate(scenario, oracle, digits=digits, check_budget=check_budget))
        effort['proof_s'] += perf_counter()-proof_start
        for level in (0, 1):
            if 4 in excluded: break
            check_budget()
            old = scenario.to_dict()
            if level == 0 and accept(old['incumbent'], old['reserve_paths'], 0, 'incumbent_interval_check'):
                break
            patch = scope_family(scenario, level, u0)[0]
            direct = deepcopy(old['incumbent'])
            reserves = {}
            depot = old['mission']['depot_xy']
            tasks = {t['id']: t['position_xy'] for t in old['mission']['tasks']}
            for uid, route in direct['routes'].items():
                n = active_count(route)
                reserves[uid] = {'initial': [depot]} if n else {}
                if n and not depot_origin(scenario, uid):
                    reserves[uid]['initial'] = [old['state']['fleet'][uid]['position_xy'], depot]
                for h, path in enumerate(route['paths'][:n], 1):
                    if f'{uid}:{h}' in patch.releases['P']: route['paths'][h-1] = [path[0], path[-1]]
                    site = route['stops'][h-1]
                    if site != 'DEPOT': reserves[uid][str(h)] = [tasks[site], depot]
            if accept(direct, reserves, level, 'direct_path_interval_screen'): break
            proof_start = perf_counter()
            exclude(deadline_certificate(scenario, level, oracle, digits=digits, diagnostic=diagnostic,
                                         check_budget=check_budget))
            effort['proof_s'] += perf_counter()-proof_start
            if level in excluded: continue
            try:
                plan, reserves = continuous_plan(scenario, oracle, scenario.to_dict()['incumbent'],
                                                 patch.releases['P'], check_budget=check_budget)
            except ValueError:
                continue
            if accept(plan, reserves, level, 'continuous_path_and_reserve_screen'): break
    except BudgetExpired: pass
    effort['screen_s'] = perf_counter()-screen_start
    proposal_start, attempted = perf_counter(), {digest(scenario.to_dict()['incumbent'])}
    if report['witness'] is None and 4 not in excluded:
        d = scenario.data
        times = {r['site']: r['delivery_h'] for rows in diagnostic.received.records.values()
                 for r in rows if r['site'] not in ('ORIGIN', 'DEPOT')}
        priority = {t['id']: (t['deadline_h'] if t['deadline_h'] is not None else d['mission']['horizon_h'])-times.get(t['id'], 0)
                    for t in d['mission']['tasks']}
        try:
            for level, share in ((2, .4), (3, .8), (4, 1.)):
                for patch in scope_family(scenario, level, u0):
                    for seq in _proposals(scenario, patch.participants, level, priority):
                        check_budget()
                        if effort['generated_proposals'] >= math.ceil(max_proposals*share): break
                        effort['generated_proposals'] += 1
                        try:
                            plan, reserves = make_plan(scenario.to_dict(), seq)
                            old = scenario.to_dict()['incumbent']
                            for uid in plan['routes']:
                                if uid not in patch.participants: plan['routes'][uid] = old['routes'][uid]
                                else:
                                    for h in range(len(plan['routes'][uid]['paths'])):
                                        if f'{uid}:{h+1}' not in patch.releases['P']:
                                            plan['routes'][uid]['paths'][h] = old['routes'][uid]['paths'][h]
                            key = digest(plan)
                            if key in attempted: continue
                            attempted.add(key)
                            if accept(plan, reserves, level, 'direct_sequence_assignment_proposal'): break
                            if not _optimistic_candidate(scenario, plan, reserves, patch): continue
                            plan, reserves = continuous_plan(scenario, oracle, plan, patch.releases['P'], check_budget=check_budget)
                            if accept(plan, reserves, level, 'generic_sequence_assignment_proposal'): break
                        except (ValueError, ArithmeticError): continue
                    if report['witness']: break
                if report['witness']: break
        except BudgetExpired: pass
    effort['proposal_s'] = perf_counter()-proposal_start
    proof_start = perf_counter()
    upper = report['full_domain']['upper']
    try:
        # A committed-prefix proof already excludes every level.
        for level in range(1 if 4 in excluded else 4 if upper is None else upper-1, 1, -1):
            check_budget()
            c = physical_certificate(scenario, level)
            if c:
                exclude(c, physical=True)
                break
    except BudgetExpired: pass
    effort['proof_s'] += perf_counter()-proof_start
    effort['oracle'] = deepcopy(oracle.effort)
    report['paths'] = [deepcopy(q) for key, q in oracle.cache.items() if key in oracle.used]
    effort['elapsed_s'] = perf_counter()-start
    return report


def verify_continuous_evidence(scenario, report):
    """Replay every claimed bound without generating paths or solving cones."""
    try:
        if (report['version'] != 'continuous_recovery_v1' or report['scenario_hash'] != scenario.content_hash()
                or report['domain'] != 'all_admissible_continuous_polylines'): return False
        if report['unsupported']:
            reason = stationary_guard(scenario)
            if reason is None and not previous_premise(scenario, report['budget']['digits'])['accepted']:
                reason = 'previous incumbent not certified by interval checker'
            return (report['unsupported'] == reason and report['witness'] is None
                    and not report['exclusions'] and not report['physical_certificates'] and not report['paths']
                    and report['full_domain'] == bounds([], None))
        diagnostic = diagnose_wind_update(scenario)
        if report['affected'] != affected_uavs(scenario, diagnostic): return False
        if report['previous_premise'] != previous_premise(scenario, report['budget']['digits']): return False
        if not report['previous_premise']['accepted']: return False
        if not all(verify_query(scenario, q, report['budget']['digits']) for q in report['paths']): return False
        excluded = set()
        for c in report['exclusions']:
            if not verify_exclusion_certificate(scenario, c, diagnostic=diagnostic): return False
            excluded.update(range(c['excluded_through']+1))
        for c in report['physical_certificates']:
            if not verify_physical_certificate(scenario, c): return False
            excluded.update(range(c['excluded_through']+1))
        upper, w = None, report['witness']
        if w:
            validation = certify_witness(scenario, w['plan'], w['reserve_paths'], w['certificate_level'],
                                         w['validation']['digits'], _diagnostic=diagnostic)
            if not validation['accepted'] or validation != w['validation']: return False
            upper = validation['level']
            if report['change'] != change_metrics(scenario, w['plan'], report['affected']['uavs']): return False
            if report['preservation'] != preservation_metrics(scenario, w['plan'], upper, report['affected']['uavs']): return False
        elif report['change'] is not None or report['preservation'] is not None: return False
        return report['full_domain'] == bounds(excluded, upper)
    except (ValueError, TypeError, KeyError, ArithmeticError, IndexError):
        return False
