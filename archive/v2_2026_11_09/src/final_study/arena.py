"""Equal-resource arena (comparison protocol F1-F7).

Each instance is solved by every arm back to back in a random order fixed by the
instance id, each arm from the scenario payload alone (cold start), each with the
same CPU-time budget. Every result is replayed right away by the independent
checker; the replay time is recorded (Q3). Plans are scored with the original
level masks and the decision counts of ``certify_v2.metrics``.
"""
from copy import deepcopy
import json
import random
from time import process_time

from certify_v2.baselines import run_gr, run_lr
from certify_v2.ladder import run_cmi, run_ph
from certify_v2.metrics import plan_decisions
from certify_v2.replay import verify_run
from env.scenario import Scenario
from recovery.local_search import digest

# PH-strict schedules (docs/EXPERIMENT_REDESIGN_RAL_2026_10_30.md, Section 12): doubling shares,
# Levels 0-1 ending at 0.5 s and 2 s whatever the budget, and a guaranteed share per level.
PH_SCHEDULES = ('PH-strict-dbl', 'PH-strict-fix', 'PH-strict-gs')
ARMS = ('GR', 'GR-c', 'LR', 'PH', 'CMI', 'noAF', 'noER', 'PH-strict', *PH_SCHEDULES, 'CMI-mu')


def method_config(budget_s, settings=None):
    """CMI settings by budget: no refinement-16 fields under short budgets (they cost seconds)."""
    settings = settings or {}
    config = dict(max_refinement=8 if budget_s < 30 else 16, exhaust_limit=4000 if budget_s < 30 else 20000)
    config.update(settings.get('cmi', {}))
    return config


def run_arm(arm, payload, budget_s, settings=None, *, seed=0):
    scenario = Scenario(payload)
    config = method_config(budget_s, settings)
    slice_s = (settings or {}).get('base_slice_fraction', 1/40)*budget_s
    if arm == 'GR':
        return run_gr(scenario, budget_s, config, seed=seed)
    if arm == 'GR-c':
        return run_gr(scenario, budget_s, config, from_incumbent=True, seed=seed)
    if arm == 'LR':
        return run_lr(scenario, budget_s, config)
    if arm in ('PH', 'PH-strict', *PH_SCHEDULES):
        shares = tuple((settings or {}).get('ph_shares', (0.05, 0.15, 0.2, 0.3, 0.3)))
        if arm == 'PH-strict-dbl':
            shares = tuple(2**k/31 for k in range(5))
        elif arm == 'PH-strict-fix':
            rest = 1-2/budget_s
            shares = (0.5/budget_s, 1.5/budget_s, *(w*rest/8 for w in (2, 3, 3)))
        extra = {} if arm == 'PH' else dict(fixed_exclusions=False)
        return run_ph(scenario, budget_s, {**config, **extra}, shares=shares, arm=arm,
                      guaranteed=arm == 'PH-strict-gs')
    if arm == 'CMI':
        return run_cmi(scenario, budget_s, config, base_slice=slice_s)
    if arm == 'CMI-mu':     # CMI, then fewer outside UAVs (docs/EXPERIMENT_REDESIGN_RAL_2026_10_30.md, Section 14)
        return run_cmi(scenario, budget_s, config, base_slice=slice_s, arm='CMI-mu', mu_refine=True)
    if arm == 'noAF':
        return run_cmi(scenario, budget_s, config, u0=sorted(scenario.data['state']['fleet']), arm='noAF',
                       base_slice=slice_s)
    if arm == 'noER':
        return run_cmi(scenario, budget_s, {**config, 'share': False}, arm='noER', base_slice=slice_s)
    raise ValueError('unknown arm: '+arm)


def _audit(payload, result):
    scenario = Scenario(payload)
    start = process_time()
    try:
        summary = verify_run(scenario, result)
        return dict(ok=True, cpu_s=process_time()-start, summary=summary)
    except Exception as error:      # every failure is recorded and reported, never hidden
        return dict(ok=False, cpu_s=process_time()-start, error=f'{type(error).__name__}: {error}')


def _decisions(payload, result):
    if not result.get('plan'):
        return None
    scenario = Scenario(payload)
    return plan_decisions(scenario, result['plan']['witness'], result['affected'])


def lean(result):
    """The result without its evidence and records; keeps plans and everything the analysis reads."""
    out = {k: v for k, v in result.items() if k not in ('evidence', 'records')}
    if result.get('evidence') is not None:
        out['evidence_size'] = dict(certificates=sum(len(b['certificates']) for b in result['evidence']),
                                    proofs=sum(len(b['proofs']) for b in result['evidence']),
                                    level_records=len(result.get('records') or []))
    return out


def detach(result):
    """(lean result, proof): the proof is the evidence and records an independent replay needs.

    The store writes proofs to a separate file the record cites (``Store.save``)."""
    if result.get('records') is None:
        return result, None
    return lean(result), dict(evidence=result['evidence'], records=result['records'])


def attach(result, proof):
    """Inverse of ``detach``: the full result for ``verify_run``."""
    return result if proof is None else dict(result, **proof)


def replay_saved(payload, record, proofs):
    """Replay a saved arena or label record from its proof file: audit per arm."""
    entries = record['arms'] if 'arms' in record else {'CMI': record}
    return {arm: _audit(payload, attach(entry['result'], (proofs or {}).get(arm))) for arm, entry in entries.items()}


def run_instance(instance_id, payload, budget_s, arms, settings=None, *, seed=0):
    """All arms on one instance, in a random order fixed by the instance id and budget."""
    order = list(arms)
    random.Random(digest(dict(instance=instance_id, budget=budget_s, seed=seed))).shuffle(order)
    input_hash = Scenario(payload).content_hash()
    out = dict(version='final-study-arena-v1', instance=instance_id, budget_s=budget_s, order=order,
               input_hash=input_hash, arms={}, proofs={})
    for arm in order:
        start = process_time()
        result = json.loads(json.dumps(run_arm(arm, deepcopy(payload), budget_s, settings, seed=seed)))
        elapsed = process_time()-start
        audit = _audit(payload, result)
        result, proof = detach(result)
        if proof is not None:
            out['proofs'][arm] = proof
        entry = dict(result=result, audit=audit,
                     decisions=_decisions(payload, result), process_cpu_s=elapsed,
                     input_hash=Scenario(payload).content_hash())
        out['arms'][arm] = entry
    return out


def label(instance_id, payload, budget_s, settings=None):
    """Reference label: CMI with the long budget, one pass, no reuse, replayed."""
    record = run_instance(instance_id, payload, budget_s, ('CMI',), settings)
    entry = record['arms']['CMI']
    return dict(version='final-study-label-v1', instance=instance_id, budget_s=budget_s,
                input_hash=record['input_hash'], result=entry['result'], audit=entry['audit'],
                decisions=entry['decisions'], proofs=record['proofs'])


# ---- XR: reuse across the deadline variants of one P1 mission and strength ---------------
def run_chain(cases, budget_s, settings=None):
    """Solve the slack variants of one mission and strength in order, sharing evidence.

    ``cases`` = [(case id, payload)] from loosest to tightest deadlines. Shared: the
    flight-time table (same wind); exclusions move from looser to tighter variants
    (tightening deadlines removes plans); plans found for tighter variants are checked
    exactly on looser ones. Each variant keeps its own CPU budget.
    """
    from certify_v2.accounting import Clock
    from certify_v2.levels import Instance
    from escalation_study.ladder import witness_level
    from level2.quantities import verify_quantity_witness
    from env.local_scope import scope_family
    from recovery.local_search import bounds
    config = method_config(budget_s, settings)
    slice_s = (settings or {}).get('base_slice_fraction', 1/40)*budget_s
    shared_table = None
    results = []
    inherited = set()
    for case, payload in cases:
        scenario = Scenario(payload)
        result = run_cmi(scenario, budget_s, config, base_slice=slice_s, arm='XR', table=shared_table,
                         excluded=inherited)
        shared_table = result.pop('_table')
        result = json.loads(json.dumps(result))
        results.append([case, payload, result])
        inherited = set(result['bounds']['excluded_levels'])
    # Back-propagate plans from tighter to looser variants.
    for j in range(len(results)-1, -1, -1):
        case_j, payload_j, result_j = results[j]
        plan = result_j.get('plan')
        if not plan:
            continue
        for i in range(j):
            case_i, payload_i, result_i = results[i]
            b = result_i['bounds']
            if b['minimum'] is not None or (b['upper'] is not None and b['upper'] <= plan['level']):
                continue
            scenario_i = Scenario(payload_i)
            witness = dict(plan['witness'], scenario_hash=scenario_i.content_hash())
            patch = next(p for p in scope_family(scenario_i, witness['patch']['level'], result_i['mask_u0'])
                         if list(p.participants) == witness['patch']['participants'])
            if verify_quantity_witness(scenario_i, witness, patch.releases):
                level = witness_level(scenario_i, witness, result_i['affected'])[0]
                result_i['plan'] = dict(witness=witness, level=level, found_by='back_propagated', source=case_j)
                result_i['bounds'] = bounds(b['excluded_levels'], level)
                result_i['events'].append(dict(kind='plan', level=level, source=case_j, cpu_s=None))
    return results


def audit_chain(results):
    """Replay a chain in order: each variant may cite only exclusions verified on the one before."""
    previous = set()
    out = []
    for case, payload, result in results:
        start = process_time()
        try:
            summary = verify_run(Scenario(payload), result, transferred=previous)
            previous = set(summary['bounds']['excluded_levels'])
            out.append(dict(case=case, ok=True, cpu_s=process_time()-start))
        except Exception as error:
            previous = set()
            out.append(dict(case=case, ok=False, cpu_s=process_time()-start, error=f'{type(error).__name__}: {error}'))
    return out
