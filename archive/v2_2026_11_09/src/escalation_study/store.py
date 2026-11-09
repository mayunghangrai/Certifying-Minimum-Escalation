"""Immutable P1 run directory: manifest, sampling ledgers and chain records.

A chain (one mission and wind strength, all slacks) is published as one
directory renamed into place, so an interrupted run resumes at chain level.
"""
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import tempfile

from final_benchmark.records import ROOT, atomic_json, publish_archive, verify_archive
from recovery.local_search import digest


def source_files():
    paths = [*ROOT.glob('src/**/*.py'), *ROOT.glob('schemas/*.json'), *ROOT.glob('requirements*.txt'),
             *ROOT.glob('configs/escalation_study/*.json'), ROOT/'scripts/run_escalation_study.py']
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths) if p.is_file()}


def record_hash(record):
    return digest({k: v for k, v in record.items() if k != 'record_hash'})


def write_gzip_json(path, value):
    with gzip.open(path, 'wt', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, separators=(',', ':'), allow_nan=False)


def read_gzip_json(path):
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        return json.load(stream)


def _packages():
    versions = {}
    for name in ('numpy', 'scipy', 'clarabel', 'shapely', 'jsonschema'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


class RunStore:
    """Bind a run directory to its configuration and source snapshot."""

    def __init__(self, path, config, *, workers=1, create=True):
        self.path = Path(path)
        self.config = config
        files = source_files()
        binding = dict(config=config, source_hash=digest(files))
        self.run_hash = digest(binding)
        manifest = self.path/'manifest.json'
        if manifest.exists():
            self.manifest = json.loads(manifest.read_text(encoding='utf-8'))
            if self.manifest['run_hash'] != self.run_hash:
                raise ValueError('source or configuration changed; use a new run directory')
            verify_archive(self.path/'source.zip', files)
        elif create:
            self.path.mkdir(parents=True, exist_ok=True)
            publish_archive(self.path/'source.zip', files)
            self.manifest = dict(version='escalation-study-run-v1', run_hash=self.run_hash, **binding,
                                 source_files=files, created_utc=datetime.now(timezone.utc).isoformat(),
                                 runtime=dict(python=platform.python_version(), platform=platform.platform(),
                                              logical_cpus=os.cpu_count(), worker_processes=workers,
                                              packages=_packages()),
                                 timing='Per-stage soft wall caps checked between operations; process CPU time '
                                        'recorded per stage. Workers run concurrently, so wall times include '
                                        'contention.')
            atomic_json(manifest, self.manifest)
        else:
            raise ValueError('run directory has no manifest')

    def ledger_path(self, mission):
        return self.path/'missions'/f'{mission}.json'

    def chain_dir(self, phase, mission, strength_index):
        return self.path/'records'/phase/f'{mission}_r{strength_index}'

    def load_ledger(self, mission):
        path = self.ledger_path(mission)
        if not path.exists():
            return None
        item = json.loads(path.read_text(encoding='utf-8'))
        if item['run_hash'] != self.run_hash or item['binding_hash'] != digest(
                {k: v for k, v in item.items() if k != 'binding_hash'}):
            raise ValueError('sampling ledger binding failed: '+mission)
        return item

    def save_ledger(self, mission, ledger, scenarios, generation_s):
        item = dict(version='escalation-p1-ledger-v1', run_hash=self.run_hash, ledger=ledger,
                    scenarios=scenarios, generation_s=generation_s)
        item['binding_hash'] = digest(item)
        atomic_json(self.ledger_path(mission), item)
        return item

    def chain_records(self, phase, mission, strength_index):
        directory = self.chain_dir(phase, mission, strength_index)
        if not directory.exists():
            return None
        records = {}
        for path in sorted(directory.glob('*.json.gz')):
            record = read_gzip_json(path)
            if record['run_hash'] != self.run_hash or record['record_hash'] != record_hash(record):
                raise ValueError('stored record failed binding: '+path.name)
            records[record['case_id']] = record
        return records

    def publish_chain(self, phase, mission, strength_index, records):
        """Write every record of one chain, then rename the directory into place."""
        target = self.chain_dir(phase, mission, strength_index)
        if target.exists():
            raise ValueError('chain records already published: '+target.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=target.name+'.', suffix='.tmp', dir=target.parent))
        try:
            for record in records:
                write_gzip_json(temporary/f"{record['case_id']}.json.gz", record)
            os.rename(temporary, target)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def all_records(self, phase):
        root = self.path/'records'/phase
        records = {}
        if root.exists():
            for directory in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.endswith('.tmp')):
                for path in sorted(directory.glob('*.json.gz')):
                    record = read_gzip_json(path)
                    records[record['case_id']] = record
        return records
