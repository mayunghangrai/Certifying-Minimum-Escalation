"""Independent replay of a P1 run.

Stage evidence is replayed with the existing optimizer-free checkers. Transfers
are accepted only when the source record replays, the two scenarios differ only
in deadlines, every target deadline is no later than its source deadline, and
both have the same affected fleet. Bounds are recomputed from verified parts.
"""
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from fractions import Fraction
import json
import multiprocessing
from pathlib import Path

from continuous.search import verify_continuous_evidence
from env.local_scope import affected_uavs
from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update
from final_benchmark.records import verify_archive
from level2.replay import replay_tree as replay_level2
from level3.replay import replay_tree as replay_level3
from level4.replay import replay_tree as replay_level4
from recovery.local_search import bounds, digest
from .ladder import STAGES, revalidate, witness_level
from .store import read_gzip_json, record_hash

_REPLAY = {'level2': replay_level2, 'level3': replay_level3, 'level4': replay_level4}


class AuditError(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise AuditError(reason)


def _normalized(payload):
    p = deepcopy(payload)
    p['benchmark_id'] = ''
    for t in p['mission']['tasks']:
        t['deadline_h'] = None
    return p


def deadlines_no_later(target, source):
    """Every target deadline is at most the source deadline (None = no deadline)."""
    old = {t['id']: t['deadline_h'] for t in source['mission']['tasks']}
    for t in target['mission']['tasks']:
        before, after = old[t['id']], t['deadline_h']
        if before is not None and (after is None or Fraction(str(after)) > Fraction(str(before))):
            return False
    return True


class Auditor:
    def __init__(self, run_path):
        self.path = Path(run_path)
        self.manifest = json.loads((self.path/'manifest.json').read_text(encoding='utf-8'))
        self.records, self.memo, self.ledgers, self.u0 = {}, {}, {}, {}

    def ledger(self, mission):
        if mission not in self.ledgers:
            item = json.loads((self.path/'missions'/f'{mission}.json').read_text(encoding='utf-8'))
            _require(item['run_hash'] == self.manifest['run_hash'], 'ledger run mismatch: '+mission)
            _require(item['binding_hash'] == digest({k: v for k, v in item.items() if k != 'binding_hash'}),
                     'ledger binding mismatch: '+mission)
            for case, info in item['ledger'].get('variants', {}).items():
                _require(Scenario(item['scenarios'][case]).content_hash() == info['scenario_hash'],
                         'ledger scenario hash mismatch: '+case)
            self.ledgers[mission] = item
        return self.ledgers[mission]

    def record(self, phase, mission, case):
        key = phase, case
        if key not in self.records:
            strength = self.ledger(mission)['ledger']['variants'][case]['strength_index']
            path = self.path/'records'/phase/f'{mission}_r{strength}'/f'{case}.json.gz'
            _require(path.exists(), 'missing record: '+str(path))
            self.records[key] = read_gzip_json(path)
        return self.records[key]

    def affected(self, scenario):
        h = scenario.content_hash()
        if h not in self.u0:
            self.u0[h] = affected_uavs(scenario, diagnose_wind_update(scenario))['uavs']
        return self.u0[h]

    def audit(self, phase, mission, case):
        key = phase, case
        if key in self.memo:
            return self.memo[key]
        r = self.record(phase, mission, case)
        _require(r['record_hash'] == record_hash(r) and r['run_hash'] == self.manifest['run_hash'],
                 'record binding failed: '+case)
        item = self.ledger(mission)
        _require(r['sampling_hash'] == item['binding_hash'] and r['scenario'] == item['scenarios'][case],
                 'record scenario differs from its sampling ledger: '+case)
        scenario = Scenario(r['scenario'])
        result = r['result']
        _require(result['scenario_hash'] == scenario.content_hash(), 'result scenario mismatch: '+case)
        u0 = self.affected(scenario)
        _require(u0 == item['ledger']['affected'], 'affected fleet differs from admission: '+case)
        _require(result['affected'] in (None, u0), 'recorded affected fleet mismatch: '+case)
        excluded, upper = set(), None
        transfer = result['transfer']
        if transfer:
            _require(transfer['kind'] == 'monotone_transfer_v1', 'unknown transfer kind')
            source = self.record(transfer['source_phase'], mission, transfer['source'])
            _require(source['record_hash'] == transfer['source_record_hash'], 'transfer source hash mismatch')
            _require(_normalized(source['scenario']) == _normalized(r['scenario']),
                     'transfer source differs in more than deadlines')
            _require(deadlines_no_later(r['scenario'], source['scenario']), 'transfer target deadline is later')
            source_bounds = self.audit(transfer['source_phase'], mission, transfer['source'])
            _require(transfer['excluded_through'] in source_bounds['excluded_levels'],
                     'transfer claims an unverified exclusion')
            excluded |= set(range(transfer['excluded_through']+1))
        prior = result['prior']
        if prior:
            _require(prior['kind'] == 'same_case_prior_v1' and r['phase'] != prior['source_phase'],
                     'invalid same-case prior')
            source = self.record(prior['source_phase'], mission, case)
            _require(source['record_hash'] == prior['source_record_hash'], 'prior record hash mismatch')
            source_bounds = self.audit(prior['source_phase'], mission, case)
            _require(set(prior['excluded_levels']) <= set(source_bounds['excluded_levels']),
                     'prior claims an unverified exclusion')
            _require(prior['upper'] is None or (source_bounds['upper'] is not None
                                                and source_bounds['upper'] <= prior['upper']),
                     'prior claims an unverified witness')
            excluded |= set(prior['excluded_levels'])
            upper = prior['upper']
        digits = result['budget']['digits']
        for stage in STAGES:
            report = result['stages'][stage]
            if report is None:
                continue
            if stage == 'screen':
                _require(verify_continuous_evidence(scenario, report), 'screen evidence failed replay: '+case)
                excluded |= set(report['full_domain']['excluded_levels'])
                if report['full_domain']['upper'] is not None:
                    upper = report['full_domain']['upper'] if upper is None else min(upper, report['full_domain']['upper'])
                continue
            checked = _REPLAY[stage](scenario, report)
            _require(checked['valid'] and checked['status'] == report['status'],
                     f'{stage} evidence failed replay: {case}: {checked.get("reason")}')
            level = int(stage[-1])
            if report['status'] == 'EMPTY':
                excluded |= set(range(level+1))
            elif report['status'] == 'WITNESS':
                k = witness_level(scenario, report['witness'], u0)[0]
                k = level if k is None else min(k, level)
                upper = k if upper is None else min(upper, k)
        for item_ in result['revalidated']:
            check = revalidate(scenario, item_['witness'], u0, digits)
            _require(check['accepted'] and check['level'] == item_['level'], 'revalidated witness failed: '+case)
            upper = item_['level'] if upper is None else min(upper, item_['level'])
        derived = bounds(excluded, upper)
        _require(derived == result['bounds'], f'recorded bounds differ from verified evidence: {case}')
        self.memo[key] = derived
        return derived


def _mission_audit(run_path, mission):
    auditor = Auditor(run_path)
    item = auditor.ledger(mission)
    checked = {}
    if item['ledger']['status'] != 'accepted':
        _require(not item['scenarios'], 'failed slot carries scenarios: '+mission)
        return dict(mission=mission, status=item['ledger']['status'], checked=checked)
    for phase in ('pass1', 'pass2'):
        for case, info in item['ledger']['variants'].items():
            path = auditor.path/'records'/phase/f"{mission}_r{info['strength_index']}"/f'{case}.json.gz'
            if path.exists():
                checked[f'{phase}:{case}'] = auditor.audit(phase, mission, case)
    return dict(mission=mission, status='accepted', checked=checked)


def audit_run(run_path, *, workers=1, log=print):
    path = Path(run_path)
    manifest = json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    verify_archive(path/'source.zip', manifest['source_files'])
    missions = sorted(p.stem for p in (path/'missions').glob('*.json'))
    outcomes = []
    if workers <= 1:
        for mission in missions:
            outcomes.append(_mission_audit(str(path), mission))
            log(f"{mission}: {len(outcomes[-1]['checked'])} records verified")
    else:
        context = multiprocessing.get_context('spawn')
        with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
            futures = [pool.submit(_mission_audit, str(path), mission) for mission in missions]
            for future in as_completed(futures):
                outcome = future.result()
                outcomes.append(outcome)
                log(f"{outcome['mission']}: {len(outcome['checked'])} records verified")
    return dict(valid=True, missions=len(missions), records=sum(len(o['checked']) for o in outcomes),
                outcomes=sorted(outcomes, key=lambda o: o['mission']))
