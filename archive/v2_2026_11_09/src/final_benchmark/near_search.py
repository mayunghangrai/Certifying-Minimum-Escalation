"""Bounded generic repairs for the stationary near-boundary cohort.

Heuristic proposals supply witnesses only. No proposal exhaustion is used as
an exclusion. Represented static certificates and physical proofs are replayed
by the common evidence verifier.
"""
from copy import deepcopy
from itertools import permutations
import math
from time import perf_counter

from env.local_scope import scope_family, change_metrics, preservation_metrics
from env.wind_dependency import diagnose_wind_update
from recovery.local_search import recover_local, verify_local_witness, bounds, digest
from recovery.physical_proofs import physical_certificate
from recovery.represented_proofs import represented_deadline_certificate
from recovery.static_paths import static_path_screen, fastest_static_plan, _guard
from recovery.transfers import BranchRejected
from recovery.physics import UnsupportedArithmetic, InadmissiblePath
from .controlled import add_physical_certificate
from .generators import axis_plan


def _proposals(scenario, participants, level, priority):
    d = scenario.data
    original = {u: [i for i in r['stops'] if i not in (None, 'DEPOT')]
                for u, r in d['incumbent']['routes'].items()}
    owners = d['incumbent']['assignment']
    ids = sorted((i for u in participants for i in original[u]), key=lambda i: (priority[i], i))
    deadline = {t['id']: t['deadline_h'] or d['mission']['horizon_h'] for t in d['mission']['tasks']}

    if level == 2:
        q = deepcopy(original)
        for u in participants: q[u].sort(key=lambda i: (deadline[i], i))
        yield q
        for u in sorted(participants, key=lambda u: min((priority[i] for i in original[u]), default=math.inf)):
            route = original[u]
            for i in sorted(route, key=lambda i: (priority[i], i)):
                reduced = [j for j in route if j != i]
                for h in range(len(route)):
                    q = deepcopy(original); q[u] = reduced[:h]+[i]+reduced[h:]
                    yield q
            if len(route) <= 5:
                for order in permutations(route):
                    q = deepcopy(original); q[u] = list(order)
                    yield q
        return

    for i in ids:
        src = owners[i]
        for dst in participants:
            if dst == src: continue
            for h in range(len(original[dst])+1):
                q = deepcopy(original)
                q[src].remove(i); q[dst].insert(h, i)
                yield q
                # A second relocation allows a helper to make room through a
                # different participant. All such proposals are checked anew.
                if level == 4:
                    for displaced in original[dst]:
                        for third in participants:
                            if third in (src, dst): continue
                            for j in range(len(original[third])+1):
                                r = deepcopy(q); r[dst].remove(displaced); r[third].insert(j, displaced)
                                yield r
            for j in original[dst]:
                q = deepcopy(original)
                q[src] = [j if k == i else k for k in q[src]]
                q[dst] = [i if k == j else k for k in q[dst]]
                yield q


def recover_near_boundary(scenario, library, *, max_seconds=8, max_proposals=120):
    if (isinstance(max_proposals, bool) or not isinstance(max_proposals, int) or max_proposals < 0
            or isinstance(max_seconds, bool) or not math.isfinite(max_seconds) or max_seconds < 0):
        raise ValueError('invalid near-boundary search budget')
    start = perf_counter()
    report = recover_local(scenario, library, max_nodes=0, max_branches=0)
    diagnostic = diagnose_wind_update(scenario)
    u0 = report['affected']['uavs']
    setup_end = perf_counter()
    report['static_certificates'] = []
    effort = report['effort']
    effort.update(method='exact stationary screens and bounded generic proposals',
                  candidate_checks=0, generated_proposals=0, static_screens=0,
                  first_witness_s=None, represented_certificate_s=None, full_domain_certificate_s=None)

    def accept(plan, reserves, level, source):
        check = verify_local_witness(scenario, library, plan, reserves, level, _diagnostic=diagnostic)
        if not check['accepted'] or not check['exact']: return False
        k = check['level']
        report['witness'] = dict(plan=plan, reserve_paths=reserves, exact=True, exact_transfers=None,
                                 validation=check, certificate_level=level, source=source)
        for field in ('represented', 'full_domain'):
            report[field] = bounds(report[field]['excluded_levels'], k)
        report['change'] = change_metrics(scenario, plan, u0)
        report['preservation'] = preservation_metrics(scenario, plan, k, u0)
        effort['first_witness_s'] = perf_counter()-start
        if report['represented']['minimum'] is not None: effort['represented_certificate_s'] = perf_counter()-start
        if report['full_domain']['minimum'] is not None: effort['full_domain_certificate_s'] = perf_counter()-start
        return True

    screen_start = perf_counter()
    for level in (0, 1):
        screened = static_path_screen(scenario, library, level)
        effort['static_screens'] += 1
        if screened['status'] == 'WITNESS':
            if accept(screened['plan'], screened['reserves'], level, 'exact_static_path_screen'): break
        elif screened['status'] == 'EMPTY':
            report['static_certificates'].append(screened['certificate'])
            report['represented'] = bounds(set(report['represented']['excluded_levels']) | set(range(level+1)), None)
    effort['static_screen_s'] = perf_counter()-screen_start
    proposal_start = perf_counter()
    attempted = set()
    cache = {}
    if report['witness'] is None and _guard(scenario) is None:
        d = scenario.data
        times = {r['site']: r['delivery_h'] for records in diagnostic.received.records.values()
                 for r in records if r['site'] not in ('ORIGIN', 'DEPOT')}
        priority = {t['id']: (t['deadline_h'] if t['deadline_h'] is not None else d['mission']['horizon_h'])-times.get(t['id'], 0)
                    for t in d['mission']['tasks']}
        for level, share in [(2, .4), (3, .8), (4, 1.)]:
            for patch in scope_family(scenario, level, u0):
                for seq in _proposals(scenario, patch.participants, level, priority):
                    if (perf_counter()-proposal_start >= max_seconds*share
                            or effort['candidate_checks'] >= math.ceil(max_proposals*share)):
                        break
                    effort['generated_proposals'] += 1
                    try:
                        plan, _ = axis_plan(scenario.to_dict(), seq)
                        for uid in plan['routes']:
                            if uid not in patch.participants:
                                plan['routes'][uid] = scenario.to_dict()['incumbent']['routes'][uid]
                        key = digest(plan)
                        if key in attempted: continue
                        attempted.add(key)
                        effort['candidate_checks'] += 1
                        plan, reserves = fastest_static_plan(scenario, library, plan, patch.releases['P'], cache=cache)
                        if accept(plan, reserves, level, 'generic_sequence_assignment_proposal'): break
                    except (ValueError, UnsupportedArithmetic, BranchRejected, InadmissiblePath):
                        continue
                if report['witness'] is not None: break
            if report['witness'] is not None: break
    effort['proposal_s'] = perf_counter()-proposal_start
    represented_start = perf_counter()
    report['represented_certificates'] = []
    upper = report['represented']['upper']
    for level in range(4 if upper is None else upper-1, 1, -1):
        certificate = represented_deadline_certificate(scenario, library, level)
        if certificate is not None:
            report['represented_certificates'].append(certificate)
            report['represented'] = bounds(set(report['represented']['excluded_levels']) | set(range(level+1)), upper)
            if report['represented']['minimum'] is not None: effort['represented_certificate_s'] = perf_counter()-start
            break
    effort['represented_proof_s'] = perf_counter()-represented_start
    proof_start = perf_counter()
    upper = report['full_domain']['upper']
    for level in range(4 if upper is None else upper-1, -1, -1):
        certificate = physical_certificate(scenario, level)
        if certificate is not None:
            add_physical_certificate(report, scenario, certificate, clock_start=start)
            break
    effort['physical_proof_s'] = perf_counter()-proof_start
    elapsed = perf_counter()-start
    effort.update(nodes=effort['generated_proposals']+effort['static_screens'],
                  branches=effort['candidate_checks']+effort['static_screens'],
                  setup_s=setup_end-start, search_s=effort['static_screen_s']+effort['proposal_s'], elapsed_s=elapsed,
                  retention_screen='stationary_dominance_screen')
    report['budget'] = dict(proposal_seconds=max_seconds, proposals=max_proposals,
                          clock='soft_between_proposals; exact screens and physical proofs timed separately')
    return report
