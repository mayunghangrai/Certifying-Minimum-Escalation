"""Comparator policies on P1 variants with a certified lower bound of at least 1.

C1 searches the finite axis-path library with the Study 3 method. C2 releases
every decision at once. C3 escalates by fixed time slices without exclusions.
Each reports the level its returned plan actually needs, so the result can be
compared with the certified minimum of the same variant.
"""
import math
from time import perf_counter, process_time

from continuous.oracle import ContinuousOracle
from continuous.search import _optimistic_candidate, continuous_plan
from continuous.validation import certify_witness
from env.local_scope import affected_uavs, change_metrics, scope_family
from env.wind_dependency import diagnose_wind_update
from final_benchmark.controlled import make_plan
from final_benchmark.generators import axis_library
from final_benchmark.near_search import _proposals, recover_near_boundary
from level4.search import search_level4
from recovery.local_search import digest
from .ladder import witness_level

POLICIES = ('C1_finite_library', 'C2_global_first', 'C3_time_sliced')


def _priority(scenario, diagnostic):
    d = scenario.data
    times = {r['site']: r['delivery_h'] for rows in diagnostic.received.records.values()
             for r in rows if r['site'] not in ('ORIGIN', 'DEPOT')}
    return {t['id']: (t['deadline_h'] if t['deadline_h'] is not None else d['mission']['horizon_h'])-times.get(t['id'], 0)
            for t in d['mission']['tasks']}


def _candidate(scenario, seq, patch):
    """A proposal keeps every coordinate its patch does not release."""
    plan, reserves = make_plan(scenario.to_dict(), seq)
    old = scenario.to_dict()['incumbent']
    for uid in plan['routes']:
        if uid not in patch.participants:
            plan['routes'][uid] = old['routes'][uid]
        else:
            for h in range(len(plan['routes'][uid]['paths'])):
                if f'{uid}:{h+1}' not in patch.releases['P']:
                    plan['routes'][uid]['paths'][h] = old['routes'][uid]['paths'][h]
    return plan, reserves


class _Clock:
    def __init__(self):
        self.wall, self.cpu = perf_counter(), process_time()

    def elapsed(self):
        return perf_counter()-self.wall, process_time()-self.cpu


def _outcome(policy, scenario, u0, clock, witness=None, *, level=None, minimality=False, extra=None):
    wall, cpu = clock.elapsed()
    result = dict(policy=policy, found=witness is not None, level=level, minimality_certified=minimality,
                  first_plan_wall_s=None, first_plan_cpu_s=None, elapsed_wall_s=wall, elapsed_cpu_s=cpu,
                  change=None, witness=witness, **(extra or {}))
    return result


def _found(result, scenario, u0, clock, witness, level, plan, exact=None):
    wall, cpu = clock.elapsed()
    result.update(found=True, level=level, witness=witness, first_plan_wall_s=wall, first_plan_cpu_s=cpu,
                  change=change_metrics(scenario, plan, u0, exact_quantities=exact))


def _proposal_loop(scenario, oracle, levels, u0, priority, *, stop, clock, max_proposals, effort):
    """Generic Level-2..4 proposals; returns (plan, reserves, check) or None."""
    attempted = {digest(scenario.to_dict()['incumbent'])}
    for level in levels:
        for patch in scope_family(scenario, level, u0):
            for seq in _proposals(scenario, patch.participants, level, priority):
                if stop(level) or effort['proposals'] >= max_proposals:
                    break
                effort['proposals'] += 1
                try:
                    plan, reserves = _candidate(scenario, seq, patch)
                    key = digest(plan)
                    if key in attempted:
                        continue
                    attempted.add(key)
                    check = certify_witness(scenario, plan, reserves, level)
                    if check['accepted']:
                        return plan, reserves, check
                    if not _optimistic_candidate(scenario, plan, reserves, patch):
                        continue
                    plan, reserves = continuous_plan(scenario, oracle, plan, patch.releases['P'])
                    check = certify_witness(scenario, plan, reserves, level)
                    if check['accepted']:
                        return plan, reserves, check
                except (ValueError, ArithmeticError):
                    continue
    return None


def finite_library(scenario, *, max_seconds, max_proposals):
    clock = _Clock()
    library = axis_library(scenario)
    report = recover_near_boundary(scenario, library, max_seconds=max_seconds, max_proposals=max_proposals)
    u0 = report['affected']['uavs']
    result = _outcome('C1_finite_library', scenario, u0, clock,
                      extra=dict(represented=report['represented'], full_domain=report['full_domain'],
                                 library_hash=library.content_hash()))
    w = report['witness']
    if w:
        wall = report['effort']['first_witness_s']
        result.update(found=True, level=w['validation']['level'], witness=dict(plan=w['plan'],
                      reserve_paths=w['reserve_paths'], certificate_level=w['certificate_level']),
                      first_plan_wall_s=wall, change=report['change'],
                      minimality_certified=report['represented']['minimum'] is not None)
    return result


def global_first(scenario, *, max_seconds, max_proposals, search_seconds, max_nodes, refinements=(2, 4), digits=18):
    clock = _Clock()
    diagnostic = diagnose_wind_update(scenario)
    u0 = affected_uavs(scenario, diagnostic)['uavs']
    oracle = ContinuousOracle(scenario, refinements, digits)
    effort = dict(proposals=0)
    result = _outcome('C2_global_first', scenario, u0, clock, extra=dict(effort=effort, search_status=None))
    start = perf_counter()
    found = _proposal_loop(scenario, oracle, (4,), u0, _priority(scenario, diagnostic),
                           stop=lambda level: perf_counter()-start >= max_seconds, clock=clock,
                           max_proposals=max_proposals, effort=effort)
    if found:
        plan, reserves, check = found
        _found(result, scenario, u0, clock, dict(plan=plan, reserve_paths=reserves, certificate_level=4),
               check['level'], plan)
        return result
    report = search_level4(scenario, max_seconds=search_seconds, max_nodes=max_nodes, refinements=refinements,
                           digits=digits)
    result['search_status'] = report['status']
    if report['status'] == 'WITNESS':
        w = report['witness']
        exact = {':'.join(map(str, c)): v for c, v in zip(w['columns'], w['values'])}
        _found(result, scenario, u0, clock, w, witness_level(scenario, w, u0)[0], w['plan'], exact)
    return result


def time_sliced(scenario, *, slice_seconds, refinements=(2, 4), digits=18):
    """Levels 0..4 in order, each given one fixed slice; no exclusion is attempted."""
    clock = _Clock()
    diagnostic = diagnose_wind_update(scenario)
    u0 = affected_uavs(scenario, diagnostic)['uavs']
    oracle = ContinuousOracle(scenario, refinements, digits)
    effort = dict(proposals=0)
    result = _outcome('C3_time_sliced', scenario, u0, clock, extra=dict(effort=effort))
    old = scenario.to_dict()
    check = certify_witness(scenario, old['incumbent'], old['reserve_paths'], 0)
    if check['accepted']:
        _found(result, scenario, u0, clock, dict(plan=old['incumbent'], reserve_paths=old['reserve_paths'],
                                                certificate_level=0), check['level'], old['incumbent'])
        result['minimality_certified'] = True
        return result
    patch = scope_family(scenario, 1, u0)[0]
    try:
        plan, reserves = continuous_plan(scenario, oracle, old['incumbent'], patch.releases['P'])
        check = certify_witness(scenario, plan, reserves, 1)
        if check['accepted']:
            _found(result, scenario, u0, clock, dict(plan=plan, reserve_paths=reserves, certificate_level=1),
                   check['level'], plan)
            return result
    except (ValueError, ArithmeticError):
        pass
    priority = _priority(scenario, diagnostic)
    for level in (2, 3, 4):
        start = perf_counter()
        found = _proposal_loop(scenario, oracle, (level,), u0, priority,
                               stop=lambda _: perf_counter()-start >= slice_seconds, clock=clock,
                               max_proposals=math.inf, effort=effort)
        if found:
            plan, reserves, check = found
            _found(result, scenario, u0, clock, dict(plan=plan, reserve_paths=reserves, certificate_level=level),
                   check['level'], plan)
            return result
    return result


def verify_comparator(scenario, result):
    """Re-check a returned plan and the membership level the result claims."""
    w = result['witness']
    if not result['found']:
        return w is None
    if w.get('kind') == 'quantity_primal_v1':
        from .ladder import revalidate
        u0 = affected_uavs(scenario, diagnose_wind_update(scenario))['uavs']
        check = revalidate(scenario, w, u0, 18)
    elif result['policy'] == 'C1_finite_library':
        from recovery.local_search import verify_local_witness
        library = axis_library(scenario)
        if library.content_hash() != result['library_hash']:
            return False
        check = verify_local_witness(scenario, library, w['plan'], w['reserve_paths'], w['certificate_level'])
        check = dict(accepted=check['accepted'] and check['exact'], level=check.get('level'))
    else:
        check = certify_witness(scenario, w['plan'], w['reserve_paths'], w['certificate_level'])
    return check['accepted'] and check['level'] == result['level']
