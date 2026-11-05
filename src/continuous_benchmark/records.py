"""Immutable continuous experiment records and frozen legacy input bindings."""
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
from time import perf_counter

from env.scenario import Scenario
from recovery.local_search import digest
from continuous.search import recover_continuous, verify_continuous_evidence
from continuous.oracle import ContinuousOracle
from final_benchmark.records import (ROOT, source_files as legacy_sources, atomic_json,
    publish_archive, verify_archive, record_hash, audit_record as audit_legacy_record)


def load_paired_bank(path, *, expected_count=128, audit=True):
    path = Path(path)
    manifest = json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    verify_archive(path/'source.zip', manifest['source_files'])
    records, hashes, byte_hashes = [], {}, {}
    for f in sorted((path/'records').glob('*.json')):
        r = json.loads(f.read_text(encoding='utf-8'))
        if (r['record_hash'] != record_hash(r) or r['run_hash'] != manifest['run_hash']
                or r['request_hash'] != digest(r['request']) or f.stem != r['case_id']
                or r['request']['scenario_hash'] != Scenario(r['scenario']).content_hash()):
            raise ValueError('paired input record binding failed: '+f.name)
        if audit and not audit_legacy_record(r): raise ValueError('legacy evidence replay failed: '+f.name)
        hashes[r['case_id']] = r['record_hash']
        byte_hashes[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
        records.append(r)
    if len(records) != expected_count or len(hashes) != len(records):
        raise ValueError('paired input bank count differs from the declared panel')
    binding = dict(kind='frozen_study3_bank_v1', count=len(records), records=hashes, file_hashes=byte_hashes,
                   manifest_hash=digest(manifest), source_hash=manifest['source_hash'])
    return records, binding


def source_files():
    paths = [*ROOT.glob('requirements*.txt'), *ROOT.glob('configs/continuous_benchmark/*.json'),
             ROOT/'scripts/run_continuous_benchmark.py']
    return {**legacy_sources(), **{p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sorted(paths) if p.is_file()}}


def audit_record(record):
    try:
        if (record['version'] != 'continuous-benchmark-case-v1' or record_hash(record) != record['record_hash']
                or record['request_hash'] != digest(record['request'])): return False
        scenario = Scenario(record['scenario'])
        if record['request']['scenario_hash'] != scenario.content_hash(): return False
        if record['request']['baseline_hash'] != (digest(record['baseline']) if record['baseline'] else None): return False
        return verify_continuous_evidence(scenario, record['result'])
    except (KeyError, TypeError, ValueError, ArithmeticError): return False


class ContinuousRunStore:
    def __init__(self, path, config, input_binding=None):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        files = source_files()
        binding = dict(config=config, source_hash=digest(files), input_binding=input_binding)
        self.run_hash = digest(binding)
        manifest_path = self.path/'manifest.json'
        if manifest_path.exists():
            self.manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            if self.manifest['run_hash'] != self.run_hash:
                raise ValueError('frozen source/configuration/input bank changed; use a new directory')
            verify_archive(self.path/'source.zip', files)
        else:
            publish_archive(self.path/'source.zip', files)
            self.manifest = dict(version='continuous-benchmark-run-v1', run_hash=self.run_hash, **binding,
                source_files=files, created_utc=datetime.now(timezone.utc).isoformat(),
                runtime=dict(python=platform.python_version(), platform=platform.platform(),
                    logical_cpus=os.cpu_count(), worker_processes=1,
                    packages={p: importlib.metadata.version(p) for p in ('numpy', 'scipy', 'clarabel', 'shapely', 'jsonschema')}),
                timing='All new search operations use the total soft clock. Generation and replay are measured separately. Archived baseline timings are historical.')
            atomic_json(manifest_path, self.manifest)

    def run_case(self, case, *, budget, metadata=None, baseline=None):
        request = dict(scenario_hash=case.scenario.content_hash(), budget=budget, metadata=metadata or {},
                       baseline_hash=digest(baseline) if baseline else None, expected=case.expected)
        request_hash = digest(request)
        path = self.path/'records'/f'{case.name}.json'
        if path.exists():
            r = json.loads(path.read_text(encoding='utf-8'))
            if r['run_hash'] != self.run_hash or r['request_hash'] != request_hash or not audit_record(r):
                raise ValueError('stored continuous record failed request binding or replay')
            return r
        start = perf_counter()
        result = recover_continuous(case.scenario, **budget)
        solve_s, observation_start = perf_counter()-start, perf_counter()
        if self.manifest['config']['stage'] == 'controlled' and not result['unsupported']:
            oracle = ContinuousOracle(case.scenario, budget.get('refinements', (2, 4)), budget.get('digits', 18))
            for uid, route in case.scenario.data['incumbent']['routes'].items():
                for curve in route['paths']:
                    if tuple(curve[0]) != tuple(curve[-1]):
                        oracle.query(uid, curve[0], curve[-1], [curve])
                        break
            result['paths'].extend(oracle.cache.values())
            result['effort']['controlled_observations'] = oracle.effort
        observation_s, audit_start = perf_counter()-observation_start, perf_counter()
        if not verify_continuous_evidence(case.scenario, result):
            raise ValueError('new continuous evidence failed independent replay')
        r = dict(version='continuous-benchmark-case-v1', run_hash=self.run_hash, case_id=case.name,
                 request=request, request_hash=request_hash, scenario=case.scenario.to_dict(), baseline=baseline,
                 result=result, audit_passed=True,
                 timing=dict(solve_s=solve_s, observation_s=observation_s, audit_s=perf_counter()-audit_start))
        r['record_hash'] = record_hash(r)
        atomic_json(path, r)
        return r
