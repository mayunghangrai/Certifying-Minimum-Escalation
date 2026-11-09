"""Single-process commands for controlled, paired, cohort, audit and report."""
import argparse
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
from time import perf_counter

from continuous.physics import stationary_duration
from continuous.search import verify_deadline_certificate
from continuous.validation import certify_witness, previous_premise
from env.local_scope import affected_uavs
from env.plan import active_count
from env.geometry import canonical_path
from env.wind_dependency import diagnose_wind_update
from recovery.local_search import digest
from .cases import Case, controlled_cases, boundary_pair, _deliveries, _decimal
from .records import (ROOT, Scenario, ContinuousRunStore, load_paired_bank, atomic_json,
                      audit_record, verify_archive)


def slots(config):
    return [(n, m, family, seed) for n, m in config['sizes'] for family in config['families'] for seed in config['seeds']]


def _slot_id(n, m, family, seed):
    return f'CB_{n}_{m}_{family}_{seed}'


def _baseline(r):
    return dict(case_id=r['case_id'], record_hash=r['record_hash'], run_hash=r['run_hash'],
                scenario_hash=r['request']['scenario_hash'], library_hash=r['request']['library_hash'],
                represented=r['result']['represented'], full_domain=r['result']['full_domain'],
                timing=r['timing'], metadata=r['request']['metadata'], budget=r['request']['budget'])


def run_controlled(path, config):
    store = ContinuousRunStore(path, config)
    selected = set(config.get('cases', [c.name for c in controlled_cases()]))
    for c in controlled_cases():
        if c.name not in selected: continue
        r = store.run_case(c, budget=config['budget'], metadata=dict(phase=config['phase'], control=c.name))
        if r['result']['full_domain']['minimum'] != c.expected:
            raise ValueError('controlled expectation was not established: '+c.name)
        print(c.name, r['result']['full_domain'], flush=True)


def run_paired(path, config):
    bank_path = Path(config['input_bank'])
    if not bank_path.is_absolute(): bank_path = ROOT/bank_path
    records, binding = load_paired_bank(bank_path)
    store = ContinuousRunStore(path, config, binding)
    for r in records:
        c = Case(r['case_id'], Scenario(r['scenario']))
        result = store.run_case(c, budget=config['budget'], metadata=deepcopy(r['request']['metadata']), baseline=_baseline(r))
        print(c.name, result['result']['full_domain'], flush=True)


def run_cohort(path, config):
    store = ContinuousRunStore(path, config)
    for n, m, family, seed in slots(config):
        name = _slot_id(n, m, family, seed)
        target = store.path/'sampling'/f'{name}.json'
        if target.exists():
            item = json.loads(target.read_text(encoding='utf-8'))
            if item['run_hash'] != store.run_hash or item['binding_hash'] != digest({k:v for k,v in item.items() if k != 'binding_hash'}):
                raise ValueError('sampling ledger binding failed')
        else:
            start = perf_counter()
            cases, meta = boundary_pair(n, m, family, seed, max_attempts=config['max_attempts'],
                                       offset=config['offset'], refinements=tuple(config['generation_refinements']))
            item = dict(version='continuous-sampling-v1', run_hash=store.run_hash, slot=name, metadata=meta,
                        generation_s=perf_counter()-start, scenarios={c.name:c.scenario.to_dict() for c in cases})
            item['binding_hash'] = digest(item)
            atomic_json(target, item)
        print(name, item['metadata']['status'], len(item['metadata']['attempts']), 'attempts', flush=True)
        for case_id, payload in item['scenarios'].items():
            meta = item['metadata']
            metadata = dict(phase=config['phase'], n=n, m=m, family=family, seed=seed,
                            side=case_id.rsplit('_', 1)[1], base_mission=name, critical_task=meta['critical_task'],
                            sampling_hash=item['binding_hash'])
            r = store.run_case(Case(case_id, Scenario(payload)), budget=config['budget'], metadata=metadata)
            print(case_id, r['result']['full_domain'], flush=True)


def _audit_sampling(item, config=None):
    if item['binding_hash'] != digest({k:v for k,v in item.items() if k != 'binding_hash'}):
        raise ValueError('sampling ledger hash mismatch')
    meta = item['metadata']
    if config:
        if meta['offset'] != config['offset'] or meta['refinements'] != config['generation_refinements']:
            raise ValueError('sampling boundary configuration changed')
        if len(meta['attempts']) > config['max_attempts']: raise ValueError('sampling attempt cap exceeded')
    if meta['selection_uses_recovery_labels'] or [a['attempt'] for a in meta['attempts']] != list(range(len(meta['attempts']))):
        raise ValueError('invalid conditional sampling attempt ledger')
    for log in meta['attempts']:
        if (log['geometry_seed'] != meta['seed']*100+log['attempt']//12
                or log['outcome'] not in ('not_local', 'no_material_certified_delay', 'boundary_validation_failed', 'accepted')):
            raise ValueError('invalid sampling attempt semantics')
    if meta['status'] != 'accepted':
        if meta['status'] != 'generation_failed' or item['scenarios']: raise ValueError('invalid failed sampling slot')
        if config and len(meta['attempts']) != config['max_attempts']: raise ValueError('incomplete failed sampling attempts')
        if any(a['outcome'] == 'accepted' for a in meta['attempts']): raise ValueError('failed sampling slot contains an admission')
        return
    if (not meta['attempts'] or meta['attempts'][-1]['outcome'] != 'accepted'
            or any(a['outcome'] == 'accepted' for a in meta['attempts'][:-1])):
        raise ValueError('accepted sampling slot has no final admission attempt')
    if set(item['scenarios']) != {item['slot']+'_'+side for side in ('below', 'above')}:
        raise ValueError('sampling pair is incomplete')
    scenarios = {side: Scenario(item['scenarios'][item['slot']+'_'+side]) for side in ('below', 'above')}
    normalized = [s.to_dict() for s in scenarios.values()]
    for p in normalized:
        p['benchmark_id'] = ''
        for t in p['mission']['tasks']:
            if t['id'] == meta['critical_task']: t['deadline_h'] = None
            elif t['deadline_h'] is not None: raise ValueError('cohort has an undeclared extra deadline')
    if normalized[0] != normalized[1]: raise ValueError('cohort pair changes fixed mission inputs')
    s = scenarios['above']
    if meta['n'] != len(s.data['mission']['tasks']) or meta['m'] != len(s.data['mission']['vehicles']):
        raise ValueError('cohort dimensions changed')
    affected = affected_uavs(s, diagnose_wind_update(s))
    last = meta['attempts'][-1]
    if (meta['locality_limit'] != meta['m']//2 or not 0 < affected['count'] <= meta['locality_limit']
            or meta['affected_count'] != affected['count'] or last['affected_count'] != affected['count']
            or meta['geometry_seed'] != last['geometry_seed']
            or list(map(list, s.data['wind']['update_support'])) != [[last['cell'], 0]]):
        raise ValueError('cohort locality or accepted attempt changed')
    cell = next(i for i,c in enumerate(s.data['wind']['cells']) if c['id'] == last['cell'])
    if list(s.data['wind']['received']['values'][cell][0]) != last['wind']:
        raise ValueError('cohort accepted wind changed')
    if any(any(tuple(w) != (0, 0) for w in row) for row in s.data['wind']['previous']['values']):
        raise ValueError('cohort previous wind must be zero')
    if any(canonical_path(p) != canonical_path([p[0], p[-1]])
           for r in s.data['incumbent']['routes'].values() for p in r['paths']):
        raise ValueError('cohort incumbent must use continuous zero-wind optimal legs')
    if not all(previous_premise(s)['accepted'] for s in scenarios.values()): raise ValueError('previous cohort feasibility failed')
    if not verify_deadline_certificate(scenarios['below'], meta['boundary_certificate']):
        raise ValueError('continuous cohort boundary proof failed')
    if meta['boundary_certificate']['excluded_through'] != 1 or meta['boundary_certificate']['earliest'] != meta['updated_lower']:
        raise ValueError('cohort lower boundary mismatch')
    check = certify_witness(scenarios['above'], meta['reference_plan'], meta['reference_reserves'], 1)
    if not check['accepted'] or check != meta['upper_validation']: raise ValueError('cohort upper witness failed')
    intervals = {(uid, h): stationary_duration(scenarios['above'], uid, path)
                 for uid, r in meta['reference_plan']['routes'].items()
                 for h, path in enumerate(r['paths'], 1)}
    if str(_deliveries(scenarios['above'], meta['reference_plan'], intervals)[meta['critical_task']][1]) != meta['updated_upper']:
        raise ValueError('cohort upper boundary mismatch')
    p = s.to_dict()
    p['wind']['received'] = {**p['wind']['previous'], 'issued_at_h': p['mission']['epoch_h']}
    p['wind']['update_support'] = []
    previous = Scenario(p)
    prior_intervals = {(uid, h): stationary_duration(previous, uid, path)
                      for uid, r in p['incumbent']['routes'].items()
                      for h, path in enumerate(r['paths'][:active_count(r)], 1)}
    prior_times = _deliveries(previous, p['incumbent'], prior_intervals)
    old_upper = prior_times[meta['critical_task']][1]
    lower, upper = Fraction(meta['updated_lower']), Fraction(meta['updated_upper'])
    delta = lower-old_upper
    tau = max(hi for lo,hi in prior_times.values())
    if (Fraction(meta['previous_upper']) != old_upper or Fraction(meta['delay']) != delta
            or delta < Fraction(1, 1000)*max(Fraction(1, 10), tau)
            or Fraction(meta['reference_gap']) != upper-lower or upper < lower):
        raise ValueError('cohort positive delay or reference gap changed')
    eps = Fraction(meta['offset'])
    if not 0 < eps < 1: raise ValueError('cohort offset outside allowed range')
    task = meta['critical_task']
    low, high = [Fraction(str(next(t['deadline_h'] for t in scenarios[side].data['mission']['tasks'] if t['id'] == task)))
                 for side in ('below', 'above')]
    if not low < Fraction(meta['updated_lower']) <= Fraction(meta['updated_upper']) < high:
        raise ValueError('cohort deadlines do not bracket the continuous reference')
    if (low != Fraction(str(_decimal(lower-eps*delta, False)))
            or high != Fraction(str(_decimal(upper+eps*delta, True)))):
        raise ValueError('cohort deadlines differ from the configured offset')


def audit_run(path):
    path = Path(path)
    manifest = json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    binding = {k:manifest[k] for k in ('config', 'source_hash', 'input_binding')}
    if manifest['run_hash'] != digest(binding) or manifest['source_hash'] != digest(manifest['source_files']):
        raise ValueError('run manifest binding failed')
    verify_archive(path/'source.zip', manifest['source_files'])
    records = {}
    for f in sorted((path/'records').glob('*.json')):
        r = json.loads(f.read_text(encoding='utf-8'))
        if r['run_hash'] != manifest['run_hash'] or f.stem != r['case_id'] or not audit_record(r):
            raise ValueError('continuous record audit failed: '+f.name)
        if r['request']['budget'] != manifest['config']['budget']: raise ValueError('record budget changed')
        records[r['case_id']] = r
    config, sampling = manifest['config'], None
    if config['stage'] == 'controlled':
        expected = set(config.get('cases', [c.name for c in controlled_cases()]))
        if set(records) != expected: raise ValueError('controlled records incomplete')
        if any(r['result']['full_domain']['minimum'] != r['request']['expected'] for r in records.values()):
            raise ValueError('controlled expected conclusion failed')
    elif config['stage'] == 'paired':
        bank_path = Path(config['input_bank'])
        if not bank_path.is_absolute(): bank_path = ROOT/bank_path
        original, bank = load_paired_bank(bank_path)
        if bank != manifest['input_binding'] or set(records) != set(bank['records']):
            raise ValueError('paired bank binding or panel completeness failed')
        for old in original:
            r = records[old['case_id']]
            if (r['scenario'] != old['scenario'] or r['baseline'] != _baseline(old)
                    or r['request']['metadata'] != old['request']['metadata']):
                raise ValueError('paired input changed')
    elif config['stage'] == 'cohort':
        expected = {_slot_id(*s):s for s in slots(config)}
        items = {f.stem:json.loads(f.read_text(encoding='utf-8')) for f in (path/'sampling').glob('*.json')}
        if set(items) != set(expected): raise ValueError('sampling ledgers incomplete')
        case_ids, accepted = set(), 0
        for name, item in items.items():
            if item['run_hash'] != manifest['run_hash'] or item['slot'] != name: raise ValueError('sampling run binding failed')
            if len(item['metadata']['attempts']) > config['max_attempts']: raise ValueError('sampling attempt cap exceeded')
            n, m, family, seed = expected[name]
            if any(item['metadata'][k] != v for k,v in dict(n=n, m=m, family=family, seed=seed).items()):
                raise ValueError('sampling stratum changed')
            _audit_sampling(item, config)
            accepted += item['metadata']['status'] == 'accepted'
            for case_id, scenario in item['scenarios'].items():
                case_ids.add(case_id)
                r = records.get(case_id)
                if (r is None or r['scenario'] != scenario
                        or r['request']['metadata']['sampling_hash'] != item['binding_hash']):
                    raise ValueError('sampling case binding failed')
        if set(records) != case_ids: raise ValueError('sampling record count mismatch')
        sampling = dict(requested=len(items), accepted=accepted, failed=len(items)-accepted)
    else: raise ValueError('unknown experiment stage')
    return dict(audit_passed=True, run_hash=manifest['run_hash'], records=len(records), sampling=sampling)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['controlled', 'paired', 'cohort', 'audit', 'report'])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    if args.command in ('audit', 'report'):
        if args.command == 'audit': print(json.dumps(audit_run(args.out), indent=2))
        else:
            from .report import write_report
            print(json.dumps(write_report(args.out), indent=2))
        return
    if args.config is None: parser.error('--config is required for experiments')
    config = json.loads(args.config.read_text(encoding='utf-8'))
    if config['stage'] != args.command: parser.error('configuration stage does not match command')
    {'controlled':run_controlled, 'paired':run_paired, 'cohort':run_cohort}[args.command](args.out, config)
    print(json.dumps(audit_run(args.out), indent=2))


if __name__ == '__main__': main()
