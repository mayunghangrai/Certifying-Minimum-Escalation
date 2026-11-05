"""E1: the P1 update arriving during execution at fractions of the makespan.

Each P1 mission is regenerated from its seed, executed under the previous wind
to t, and the same local update (at the E1 strength) is applied there. All slack
variants of one snapshot share its state and differ only in deadlines, so the
P1 ladder, transfers, records and audit apply unchanged.
"""
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from fractions import Fraction
import multiprocessing
from time import perf_counter

from continuous.validation import previous_premise
from env.local_scope import affected_uavs
from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update
from .ladder import STAGES, add_seeds, certify_chain, stage_queries
from .missions import base_mission, exposure, mission_id, speed_ranks, variant_id
from .runner import _summary, make_records
from .snapshots import build_snapshot, conservation
from .store import RunStore


def unit_id(n, m, family, seed, k):
    return f'{mission_id(n, m, family, seed)}_t{k}'


def units(config):
    return [(n, family, seed, k) for n in config['tasks'] for family in config['families']
            for seed in config['seeds'] for k in range(1, len(config['update_fractions'])+1)]


def _normalized(payload):
    p = deepcopy(payload)
    p['benchmark_id'] = ''
    for t in p['mission']['tasks']:
        t['deadline_h'] = None
    return p


def snapshot_ledger(config, n, family, seed, k):
    """Return (scenarios, ledger) for one mission and update time."""
    m = config['uavs']
    name = unit_id(n, m, family, seed, k)
    fraction = config['update_fractions'][k-1]
    ledger = dict(version='escalation-e1-sampling-v1', status='generation_failed', mission=name,
                  parent=mission_id(n, m, family, seed), n=n, m=m, family=family, seed=seed,
                  update_fraction=fraction, strengths=[config['e1_strength']], slacks=list(config['slacks']),
                  selection_uses_recovery_labels=False, attempts=[])
    variants, parent = base_mission(n, m, family, seed, max_attempts=config['max_attempts'],
                                    battery_slack=config['battery_slack'], strengths=config['strengths'],
                                    slacks=config['slacks'])
    ledger['parent_status'] = parent['status']
    if parent['status'] != 'accepted':
        ledger['attempts'].append(dict(attempt=0, outcome='parent_generation_failed'))
        return {}, ledger
    ri = [str(Fraction(r)) for r in config['strengths']].index(str(Fraction(config['e1_strength'])))
    cell = parent['cell_index']
    scenarios, provenance = {}, None
    for si in range(len(config['slacks'])):
        source = variants[variant_id(parent['mission'], ri, si)]
        wind = source['wind']['received']['values'][cell][0]
        snap, record = build_snapshot(source, fraction, received_wind=(cell, wind))
        snap['benchmark_id'] = variant_id(name, 0, si)
        if provenance is None:
            provenance = record
        elif record != provenance:
            raise ValueError('snapshot state depends on deadlines: '+name)
        scenarios[snap['benchmark_id']] = dict(source_hash=Scenario(source).content_hash(),
                                              payload=Scenario(snap).to_dict())
    payloads = {k_: v['payload'] for k_, v in scenarios.items()}
    first = Scenario(next(iter(payloads.values())))
    if any(_normalized(p) != _normalized(next(iter(payloads.values()))) for p in payloads.values()):
        raise ValueError('snapshot variants differ in more than deadlines: '+name)
    u0 = affected_uavs(first, diagnose_wind_update(first))['uavs']
    log = dict(attempt=0, affected_count=len(u0))
    ledger['attempts'].append(log)
    for case, payload in payloads.items():
        if not conservation(variants[variant_id(parent['mission'], ri, 0)], payload):
            log['outcome'] = 'conservation_failed'
            return {}, ledger
        s = Scenario(payload)
        if affected_uavs(s, diagnose_wind_update(s))['uavs'] != u0:
            log['outcome'] = 'affected_set_varies'
            return {}, ledger
        if not previous_premise(s)['accepted']:
            log['outcome'] = 'previous_premise_failed'
            return {}, ledger
    log['outcome'] = 'accepted'
    wind = tuple(Fraction(str(v)) for v in first.data['wind']['received']['values'][cell][0])
    ledger.update(status='accepted', cell=parent['cell'], cell_index=cell, direction=parent['direction'],
                  affected=u0, provenance=provenance, parent_ledger_variants={
                      case: scenarios[case]['source_hash'] for case in payloads},
                  speed_ranks=speed_ranks(first.to_dict()),
                  exposure={str(Fraction(config['e1_strength'])): exposure(first, cell, wind)},
                  variants={case: dict(strength=str(Fraction(config['e1_strength'])), slack=str(Fraction(config['slacks'][si])),
                                       strength_index=0, slack_index=si, scenario_hash=Scenario(payloads[case]).content_hash())
                            for si, case in enumerate(payloads)})
    return payloads, ledger


def e1_job(run_path, config, unit):
    n, family, seed, k = unit
    store = RunStore(run_path, config, create=False)
    name = unit_id(n, config['uavs'], family, seed, k)
    item = store.load_ledger(name)
    if item is None:
        start = perf_counter()
        scenarios, ledger = snapshot_ledger(config, n, family, seed, k)
        item = store.save_ledger(name, ledger, scenarios, perf_counter()-start)
    if item['ledger']['status'] != 'accepted' or store.chain_dir('pass1', name, 0).exists():
        return dict(mission=name, status=item['ledger']['status'], records=[])
    cases = [(variant_id(name, 0, si), Scenario(item['scenarios'][variant_id(name, 0, si)]))
             for si in range(len(config['slacks']))]
    results = certify_chain(cases, config['budget'])
    records = make_records(store, item, cases, results, 'pass1')
    store.publish_chain('pass1', name, 0, records)
    return dict(mission=name, status='accepted', records=_summary(name, 'pass1', records))


def e1_pass2_job(run_path, config, unit):
    n, family, seed, k = unit
    store = RunStore(run_path, config, create=False)
    name = unit_id(n, config['uavs'], family, seed, k)
    item = store.load_ledger(name)
    if item is None or item['ledger']['status'] != 'accepted':
        return dict(mission=name, status='no_mission', records=[])
    first = store.chain_records('pass1', name, 0)
    if first is None:
        raise ValueError('pass 1 is incomplete for '+name)
    order = [variant_id(name, 0, si) for si in range(len(config['slacks']))]
    open_cases = [c for c in order if first[c]['result']['bounds']['minimum'] is None]
    if not open_cases or store.chain_dir('pass2', name, 0).exists():
        return dict(mission=name, status='accepted', records=[])
    seeds = {}
    for record in first.values():
        for stage in STAGES:
            add_seeds(seeds, stage_queries(stage, record['result']['stages'][stage]))
    cases = [(c, Scenario(item['scenarios'][c])) for c in open_cases]
    results = certify_chain(cases, config['pass2_budget'], seeds=seeds,
                            prior={c: first[c]['result']['bounds'] for c in open_cases})
    records = make_records(store, item, cases, results, 'pass2',
                           prior_hashes={c: first[c]['record_hash'] for c in open_cases})
    store.publish_chain('pass2', name, 0, records)
    return dict(mission=name, status='accepted', records=_summary(name, 'pass2', records))


def run_e1(run_path, config, *, phase='pass1', workers=1, log=print):
    RunStore(run_path, config, workers=workers)
    job = e1_job if phase == 'pass1' else e1_pass2_job
    todo = units(config)
    outcomes = []
    if workers <= 1:
        for unit in todo:
            outcomes.append(job(str(run_path), config, unit))
            log(_line(outcomes[-1]))
        return outcomes
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('spawn')) as pool:
        for future in as_completed([pool.submit(job, str(run_path), config, unit) for unit in todo]):
            outcomes.append(future.result())
            log(_line(outcomes[-1]))
    return outcomes


def _line(outcome):
    certified = sum(r['bounds']['minimum'] is not None for r in outcome['records'])
    return f"{outcome['mission']}: {outcome['status']}, {len(outcome['records'])} new records, {certified} certified"
