"""Certify P1 variants with a fixed ladder and monotone evidence along slack.

Within one mission and wind strength the variants differ only in deadlines.
Tightening every deadline removes plans and keeps U0 and every release space,
so an exclusion at a looser variant holds at each tighter one, and a witness
at a tighter variant is feasible at each looser one. Transfers are recorded
explicitly and re-checked by the audit; nothing is inferred silently.
"""
from fractions import Fraction
from time import perf_counter, process_time

from continuous.search import recover_continuous
from continuous.validation import certify_witness
from env.local_scope import patch_contains, scope_family, scope_membership
from level2.quantities import verify_quantity_witness
from level2.search import search_level2
from level3.search import search_level3
from level4.search import search_level4
from recovery.local_search import _coordinate_point, bounds

STAGES = ('screen', 'level2', 'level3', 'level4')
_SEARCH = {'level2': search_level2, 'level3': search_level3, 'level4': search_level4}


def _key(q):
    return q['uid'], tuple(q['start']), tuple(q['goal'])


def add_seeds(seeds, queries):
    """Keep the strongest verified lower bound per directed endpoint pair."""
    for q in queries:
        key = _key(q)
        old = seeds.get(key)
        if old is None or (q['bound_attempted'], Fraction(q['lower'])) > (old['bound_attempted'], Fraction(old['lower'])):
            seeds[key] = q


def stage_queries(stage, report):
    """Verified path queries carried by one stage report."""
    if report is None or report.get('unsupported'):
        return []
    if stage == 'screen':
        return report['paths']
    if stage == 'level2':
        return report['leg_bounds']
    entries = report['patches'] if stage == 'level3' else [report['tree']]
    return [q for entry in entries for node in entry['nodes'] if node['kind'] == 'sequence'
            for q in node['proof']['leg_bounds']]


def _level2_seeds(scenario, seeds, u0):
    """Only pairs the Level-2 domain can query; other seeds would bloat its table."""
    d = scenario.data
    points = {}
    for uid in u0:
        tasks = [t['position_xy'] for t in d['mission']['tasks'] if d['incumbent']['assignment'].get(t['id']) == uid]
        points[uid] = {tuple(d['mission']['depot_xy']), tuple(d['state']['fleet'][uid]['position_xy']),
                       *map(tuple, tasks)}
    return [q for (uid, a, b), q in seeds.items() if uid in points and a in points[uid] and b in points[uid]]


def witness_level(scenario, witness, u0):
    """Smallest scope level containing a witness, using exact quantities."""
    if witness.get('kind') == 'quantity_primal_v1':
        exact = {':'.join(map(str, c)): v for c, v in zip(witness['columns'], witness['values'])}
        point = _coordinate_point(scenario, witness['plan'], exact)
    else:
        point = _coordinate_point(scenario, witness['plan'], None)
    return next((k for k in range(5) if scope_membership(scenario, point, k, u0)), None), point


def revalidate(scenario, witness, u0, digits):
    """Check a witness found for another deadline variant against this scenario."""
    try:
        if witness.get('kind') == 'quantity_primal_v1':
            level, point = witness_level(scenario, witness, u0)
            if level is None:
                return dict(accepted=False, reason='outside scope union')
            moved = {**witness, 'scenario_hash': scenario.content_hash()}
            for k in range(level, 5):
                for patch in scope_family(scenario, k, u0):
                    if patch_contains(scenario, point, patch) and verify_quantity_witness(scenario, moved, patch.releases):
                        return dict(accepted=True, level=level, kind='quantity_primal_v1')
            return dict(accepted=False, reason='exact quantity constraints fail')
        check = certify_witness(scenario, witness['plan'], witness['reserve_paths'], witness['certificate_level'], digits)
        return dict(accepted=check['accepted'], level=check.get('level'), kind='stationary_interval_witness_v1',
                    reason=check.get('reason'))
    except (ValueError, TypeError, KeyError, ArithmeticError, StopIteration) as error:
        return dict(accepted=False, reason=str(error))


def own_witness(scenario, result):
    """The lowest-level witness produced by this variant's own stages."""
    best = None
    u0 = result['affected']
    for stage in STAGES:
        report = result['stages'].get(stage)
        if not report or not report.get('witness'):
            continue
        witness = report['witness']
        if stage == 'screen':
            level = witness['validation']['level']
        else:
            level = witness_level(scenario, witness, u0)[0]
        if level is not None and (best is None or level < best[0]):
            best = (level, stage, witness)
    return best


def _stop(stage, report, budget):
    if report.get('unsupported'):
        return 'unsupported'
    effort = report['effort']
    if stage == 'screen':
        if effort['budget_exhausted']:
            return 'time'
        return 'proposals' if effort['generated_proposals'] >= budget['max_proposals'] else 'complete'
    if not effort['budget_exhausted']:
        return 'complete'
    nodes = effort['visited'] if stage == 'level2' else effort['assignment_nodes']+effort['sequence_nodes']
    return 'nodes' if nodes >= budget['max_nodes'] else 'time'


def combine(excluded, upper, stage, report, scenario, u0):
    """Fold one stage's verified conclusion into the variant bounds."""
    if stage == 'screen':
        own = report['full_domain']
        excluded |= set(own['excluded_levels'])
        if own['upper'] is not None:
            upper = own['upper'] if upper is None else min(upper, own['upper'])
        return excluded, upper
    level = int(stage[-1])
    if report['status'] == 'EMPTY':
        excluded |= set(range(level+1))
    elif report['status'] == 'WITNESS':
        k = witness_level(scenario, report['witness'], u0)[0]
        k = level if k is None else min(k, level)
        upper = k if upper is None else min(upper, k)
    return excluded, upper


def certify_variant(scenario, budget, *, seeds=None, transfer=None, prior=None):
    """Run the ladder on one scenario.

    ``transfer`` = (looser case certified earlier in this chain, excluded_through).
    ``prior`` = this case's bounds from an earlier pass of the same run.
    """
    seeds = {} if seeds is None else seeds
    start, cpu_start = perf_counter(), process_time()
    common = dict(refinements=tuple(budget['refinements']), digits=budget['digits'])
    excluded = set(range(transfer[1]+1)) if transfer else set()
    upper = None
    if prior:
        excluded |= set(prior['excluded_levels'])
        upper = prior['upper']
    result = dict(version='escalation-variant-v1', scenario_hash=scenario.content_hash(), budget=budget,
                  transfer=None if transfer is None else dict(kind='monotone_transfer_v1', source=transfer[0],
                                                               excluded_through=transfer[1]),
                  prior=None if prior is None else dict(kind='same_case_prior_v1',
                                                        excluded_levels=sorted(prior['excluded_levels']),
                                                        upper=prior['upper']),
                  seed_queries=len(seeds), stages={s: None for s in STAGES}, stop={s: 'skipped' for s in STAGES},
                  timing={}, events=[], revalidated=[], affected=None)
    if transfer:
        result['events'].append(dict(stage='transfer', kind='exclusion', level=transfer[1], wall_s=0., cpu_s=0.))
    for stage in STAGES:
        b = bounds(excluded, upper)
        if b['minimum'] is not None:
            break
        if stage == 'level2' and (2 in excluded or (upper is not None and upper <= 2)):
            continue
        if stage == 'level3' and (2 not in excluded or 3 in excluded or (upper is not None and upper <= 3)):
            continue
        if stage == 'level4' and (3 not in excluded or 4 in excluded or upper is not None):
            continue
        cap = budget[stage]
        offset, cpu_offset = perf_counter()-start, process_time()-cpu_start
        if stage == 'screen':
            report = recover_continuous(scenario, max_seconds=cap['max_seconds'], max_proposals=cap['max_proposals'],
                                        initial_bounds=list(seeds.values()), **common)
            result['affected'] = report['affected']['uavs'] if not report['unsupported'] else None
            for event in report['effort']['events']:
                result['events'].append(dict(stage=stage, kind=event['kind'], level=event['level'],
                                             wall_s=offset+event['wall_s'], cpu_s=None))
        else:
            initial = (_level2_seeds(scenario, seeds, result['affected']) if stage == 'level2'
                       else list(seeds.values()))
            report = _SEARCH[stage](scenario, max_seconds=cap['max_seconds'], max_nodes=cap['max_nodes'],
                                    max_operations=budget['max_operations'], max_rows=budget['max_rows'],
                                    initial_bounds=initial, **common)
            if report['status'] in ('WITNESS', 'EMPTY'):
                result['events'].append(dict(stage=stage, kind='witness' if report['status'] == 'WITNESS'
                                             else 'exclusion', level=int(stage[-1]),
                                             wall_s=perf_counter()-start, cpu_s=process_time()-cpu_start))
        result['timing'][stage] = dict(wall_s=perf_counter()-start-offset, cpu_s=process_time()-cpu_start-cpu_offset)
        result['stages'][stage] = report
        result['stop'][stage] = _stop(stage, report, cap)
        if report.get('unsupported'):
            break
        excluded, upper = combine(excluded, upper, stage, report, scenario, result['affected'])
        add_seeds(seeds, stage_queries(stage, report))
    result['timing']['total'] = dict(wall_s=perf_counter()-start, cpu_s=process_time()-cpu_start)
    result['bounds'] = bounds(excluded, upper)
    return result


def certify_chain(cases, budget, *, seeds=None, prior=None):
    """Certify variants of one mission and strength, loosest deadlines first.

    ``prior`` optionally maps case id -> bounds from an earlier pass.
    """
    seeds = {} if seeds is None else seeds
    results = []
    for i, (case, scenario) in enumerate(cases):
        transfer = None
        if results and results[-1]['bounds']['excluded_levels']:
            transfer = (cases[i-1][0], max(results[-1]['bounds']['excluded_levels']))
        results.append(certify_variant(scenario, budget, seeds=seeds, transfer=transfer,
                                       prior=(prior or {}).get(case)))
    backpropagate(cases, results, budget['digits'])
    check_monotone(cases, results)
    return results


def backpropagate(cases, results, digits):
    """Re-validate each own witness on looser variants with a weaker upper bound."""
    for i, ((case, scenario), result) in enumerate(zip(cases, results)):
        best = own_witness(scenario, result)
        if best is None:
            continue
        level, stage, witness = best
        for j in range(i):
            target_case, target = cases[j]
            b = results[j]['bounds']
            if b['minimum'] is not None or (b['upper'] is not None and b['upper'] <= level):
                continue
            check = revalidate(target, witness, results[j]['affected'], digits)
            if check['accepted']:
                results[j]['revalidated'].append(dict(source=case, stage=stage, level=check['level'],
                                                      kind=check['kind'], witness=witness))
                upper = check['level'] if b['upper'] is None else min(b['upper'], check['level'])
                results[j]['bounds'] = bounds(b['excluded_levels'], upper)


def check_monotone(cases, results):
    """A tighter variant can never need less intervention than a looser one."""
    order = [None if r['bounds']['minimum'] is None else 5 if r['bounds']['minimum'] == 'infinity'
             else r['bounds']['minimum'] for r in results]
    for j in range(len(results)):
        for i in range(j+1, len(results)):
            if order[j] is not None and order[i] is not None and order[j] > order[i]:
                raise ValueError(f'monotonicity defect between {cases[j][0]} and {cases[i][0]}')
