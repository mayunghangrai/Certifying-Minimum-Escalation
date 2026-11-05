"""Run directory of the final study: manifest, source archive, one file per unit.

The manifest binds the configuration and a hash of every source file. A rerun with
the same code and configuration resumes: finished units are skipped. Changing code
or configuration requires a new run directory, so results never mix versions.
"""
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import tempfile

from final_benchmark.records import ROOT, atomic_json, publish_archive, verify_archive
from recovery.local_search import digest


def source_files():
    paths = [*ROOT.glob('src/**/*.py'), *ROOT.glob('schemas/*.json'), *ROOT.glob('requirements*.txt'),
             *ROOT.glob('configs/final_study/*.json'), ROOT/'scripts/run_final_study.py']
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths) if p.is_file() and '__pycache__' not in p.parts}


def write_gzip_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.name+'.', suffix='.tmp', dir=path.parent)
    os.close(handle)
    try:
        with gzip.open(temporary, 'wt', encoding='utf-8') as stream:
            json.dump(value, stream, sort_keys=True, separators=(',', ':'), allow_nan=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def read_gzip_json(path):
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        return json.load(stream)


def _packages():
    out = {}
    for name in ('numpy', 'scipy', 'clarabel', 'shapely', 'jsonschema', 'matplotlib'):
        try:
            out[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            out[name] = None
    return out


class Store:
    def __init__(self, path, config, *, workers=1, create=True, bind=True):
        """``bind=False`` opens an existing run read-only under any code version (reports only)."""
        self.path = Path(path)
        self.config = config
        if not bind:
            self.manifest = json.loads((self.path/'manifest.json').read_text(encoding='utf-8'))
            self.run_hash = self.manifest['run_hash']
            return
        files = source_files()
        binding = dict(config=config, source_hash=digest(files))
        self.run_hash = digest(binding)
        manifest = self.path/'manifest.json'
        if manifest.exists():
            self.manifest = json.loads(manifest.read_text(encoding='utf-8'))
            if self.manifest['run_hash'] != self.run_hash:
                raise ValueError('source or configuration changed since this run started; '
                                 'use a new --out directory (or restore the code)')
            verify_archive(self.path/'source.zip', files)
        elif create:
            self.path.mkdir(parents=True, exist_ok=True)
            publish_archive(self.path/'source.zip', files)
            self.manifest = dict(version='final-study-run-v1', run_hash=self.run_hash, **binding, source_files=files,
                                 created_utc=datetime.now(timezone.utc).isoformat(),
                                 runtime=dict(python=platform.python_version(), platform=platform.platform(),
                                              processor=platform.processor(), logical_cpus=os.cpu_count(),
                                              worker_processes=workers, packages=_packages()),
                                 timing='CPU-time budgets (process_time) per arm; wall times include contention.')
            atomic_json(manifest, self.manifest)
        else:
            raise ValueError('run directory has no manifest')

    def unit(self, *parts):
        return self.path.joinpath(*parts[:-1], parts[-1]+'.json.gz')

    def exists(self, *parts):
        return self.unit(*parts).exists()

    def proof_unit(self, *parts):
        return self.path.joinpath('proofs', *parts[:-1], parts[-1]+'.json.gz')

    def save(self, record, *parts):
        """A top-level ``proofs`` entry goes to its own file under ``proofs/``; the record keeps
        its path and digest, which the record hash covers."""
        record = dict(record, run_hash=self.run_hash)
        proofs = record.pop('proofs', None)
        if proofs:
            path = self.proof_unit(*parts)
            write_gzip_json(path, proofs)       # before the record, so a record never cites a missing file
            record['proofs'] = dict(file=path.relative_to(self.path).as_posix(), digest=digest(proofs),
                                    keys=sorted(proofs))
        record['record_hash'] = digest({k: v for k, v in record.items() if k != 'record_hash'})
        write_gzip_json(self.unit(*parts), record)
        return record

    def load_proofs(self, record):
        """The proofs a record cites, checked against its digest; None if it cites none."""
        ref = record.get('proofs')
        if not ref:
            return None
        proofs = read_gzip_json(self.path/ref['file'])
        if digest(proofs) != ref['digest']:
            raise ValueError('proof file failed its binding: '+ref['file'])
        return proofs

    def load(self, *parts, check=True):
        path = self.unit(*parts)
        if not path.exists():
            return None
        record = read_gzip_json(path)
        if check and (record.get('run_hash') != self.run_hash
                      or record.get('record_hash') != digest({k: v for k, v in record.items() if k != 'record_hash'})):
            raise ValueError('record failed its binding: '+str(path))
        return record

    def all(self, *parts):
        root = self.path.joinpath(*parts)
        if not root.exists():
            return []
        return sorted(p for p in root.glob('*.json.gz'))
