"""Mission-level P1 jobs and the process pool that runs them.

One worker handles every chain of a mission, so path seeds and transfers stay
inside one process. Chains are published atomically; a rerun resumes after the
last complete chain.
"""
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
from time import perf_counter

from env.scenario import Scenario
from .ladder import STAGES, add_seeds, certify_chain, stage_queries
from .missions import base_mission, mission_id, variant_id
from .store import RunStore, record_hash


def slots(config):
    return [(n, family, seed) for n in config['tasks'] for family in config['families'] for seed in config['seeds']]


def make_records(store, item, cases, results, phase, *, prior_hashes=None):
    """Build chain records; transfers point at the exact source record hash."""
    ledger = item['ledger']
    hashes, records = {}, []
    for (case, scenario), result in zip(cases, results):
        if result['transfer']:
            source = result['transfer']['source']
            result['transfer'].update(source_phase=phase, source_record_hash=hashes[source])
        if result['prior']:
            result['prior'].update(source_phase='pass1', source_record_hash=prior_hashes[case])
        for item_ in result['revalidated']:
            item_['source_phase'] = phase
        info = ledger['variants'][case]
        record = dict(version='escalation-record-v1', run_hash=store.run_hash, phase=phase, case_id=case,
                      mission=ledger['mission'], sampling_hash=item['binding_hash'],
                      metadata=dict(n=ledger['n'], m=ledger['m'], family=ledger['family'], seed=ledger['seed'],
                                    strength=info['strength'], slack=info['slack'],
                                    strength_index=info['strength_index'], slack_index=info['slack_index']),
                      scenario=scenario.to_dict(), result=result)
        record['record_hash'] = record_hash(record)
        hashes[case] = record['record_hash']
        records.append(record)
    return records


def _summary(name, phase, records):
    return [dict(case=r['case_id'], phase=phase, bounds=r['result']['bounds'],
                 wall_s=r['result']['timing']['total']['wall_s']) for r in records]


def pass1_job(run_path, config, slot):
    n, family, seed = slot
    store = RunStore(run_path, config, create=False)
    name = mission_id(n, config['uavs'], family, seed)
    item = store.load_ledger(name)
    if item is None:
        start = perf_counter()
        scenarios, ledger = base_mission(n, config['uavs'], family, seed, max_attempts=config['max_attempts'],
                                         battery_slack=config['battery_slack'], strengths=config['strengths'],
                                         slacks=config['slacks'])
        item = store.save_ledger(name, ledger, scenarios, perf_counter()-start)
    if item['ledger']['status'] != 'accepted':
        return dict(mission=name, status=item['ledger']['status'], records=[])
    done = []
    for ri in range(len(config['strengths'])):
        if store.chain_dir('pass1', name, ri).exists():
            continue
        cases = [(variant_id(name, ri, si), Scenario(item['scenarios'][variant_id(name, ri, si)]))
                 for si in range(len(config['slacks']))]
        results = certify_chain(cases, config['budget'])
        records = make_records(store, item, cases, results, 'pass1')
        store.publish_chain('pass1', name, ri, records)
        done += _summary(name, 'pass1', records)
    return dict(mission=name, status='accepted', records=done)


def pass2_job(run_path, config, slot):
    n, family, seed = slot
    store = RunStore(run_path, config, create=False)
    name = mission_id(n, config['uavs'], family, seed)
    item = store.load_ledger(name)
    if item is None or item['ledger']['status'] != 'accepted':
        return dict(mission=name, status='no_mission', records=[])
    done = []
    for ri in range(len(config['strengths'])):
        first = store.chain_records('pass1', name, ri)
        if first is None:
            raise ValueError('pass 1 is incomplete for '+name)
        order = [variant_id(name, ri, si) for si in range(len(config['slacks']))]
        open_cases = [c for c in order if first[c]['result']['bounds']['minimum'] is None]
        if not open_cases or store.chain_dir('pass2', name, ri).exists():
            continue
        seeds = {}
        for record in first.values():
            for stage in STAGES:
                add_seeds(seeds, stage_queries(stage, record['result']['stages'][stage]))
        cases = [(c, Scenario(item['scenarios'][c])) for c in open_cases]
        prior = {c: first[c]['result']['bounds'] for c in open_cases}
        results = certify_chain(cases, config['pass2_budget'], seeds=seeds, prior=prior)
        records = make_records(store, item, cases, results, 'pass2',
                               prior_hashes={c: first[c]['record_hash'] for c in open_cases})
        store.publish_chain('pass2', name, ri, records)
        done += _summary(name, 'pass2', records)
    return dict(mission=name, status='accepted', records=done)


def run(run_path, config, *, phase='pass1', workers=1, log=print):
    """Create the manifest in the parent, then dispatch missions to workers."""
    RunStore(run_path, config, workers=workers)
    job = pass1_job if phase == 'pass1' else pass2_job
    todo = slots(config)
    if workers <= 1:
        outcomes = [job(str(run_path), config, slot) for slot in todo]
        for outcome in outcomes:
            log(_line(outcome))
        return outcomes
    outcomes = []
    context = multiprocessing.get_context('spawn')
    with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
        futures = {pool.submit(job, str(run_path), config, slot): slot for slot in todo}
        for future in as_completed(futures):
            outcome = future.result()
            outcomes.append(outcome)
            log(_line(outcome))
    return outcomes


def _line(outcome):
    certified = sum(r['bounds']['minimum'] is not None for r in outcome['records'])
    return (f"{outcome['mission']}: {outcome['status']}, {len(outcome['records'])} new records, "
            f"{certified} certified")
