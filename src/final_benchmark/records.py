"""Immutable case records, source snapshots, and case-level restart support."""
from datetime import datetime, timezone
import importlib.metadata
import hashlib
import json
import os
from pathlib import Path
import platform
import tempfile
from time import perf_counter
import zipfile

from env.scenario import Scenario
from recovery.representation import PathLibrary
from recovery.local_search import digest, recover_local, verify_local_evidence
from .controlled import controlled_record

ROOT = Path(__file__).resolve().parents[2]


def source_files():
    paths = [*ROOT.glob('src/**/*.py'),*ROOT.glob('schemas/*.json'),ROOT/'requirements.txt',
             ROOT/'scripts/final_benchmark.py',ROOT/'scripts/plot_final_benchmark.py',ROOT/'scripts/report_near_boundary.py',
             *ROOT.glob('configs/final_benchmark/*.json')]
    import hashlib
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths) if p.is_file()}


def verify_archive(path,files):
    try:
        with zipfile.ZipFile(path) as z:
            if sorted(z.namelist()) != sorted(files): raise ValueError('source archive member mismatch')
            if any(hashlib.sha256(z.read(name)).hexdigest()!=expected for name,expected in files.items()):
                raise ValueError('source archive content mismatch')
    except (zipfile.BadZipFile,KeyError,OSError) as error:
        raise ValueError('source archive is missing, corrupt, or incomplete') from error


def publish_archive(path,files):
    if path.exists():
        verify_archive(path,files)
        return
    fd,name=tempfile.mkstemp(prefix='source.',suffix='.zip.tmp',dir=path.parent)
    os.close(fd)
    temporary=Path(name)
    try:
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as z:
            for relative in files: z.write(ROOT/relative,relative)
        verify_archive(temporary,files)
        os.link(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path,value):
    """Publish a complete new file without overwriting an existing record."""
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary,path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def record_hash(record):
    return digest({k:v for k,v in record.items() if k!='record_hash'})


def audit_record(record):
    try:
        if record_hash(record) != record['record_hash']: return False
        scenario = Scenario(record['scenario'])
        library = PathLibrary.from_dict(scenario,record['library'])
        return verify_local_evidence(scenario,library,record['result'])
    except (KeyError,TypeError,ValueError):
        return False


class RunStore:
    def __init__(self,path,config):
        self.path = Path(path)
        self.path.mkdir(parents=True,exist_ok=True)
        files = source_files()
        binding = dict(config=config,source_hash=digest(files))
        self.run_hash = digest(binding)
        manifest_path = self.path/'manifest.json'
        if manifest_path.exists():
            self.manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            if self.manifest['run_hash'] != self.run_hash:
                raise ValueError('frozen run configuration or source changed; use a new run directory')
            verify_archive(self.path/'source.zip',files)
        else:
            archive = self.path/'source.zip'
            publish_archive(archive,files)
            self.manifest = dict(version='final-benchmark-run-v1',run_hash=self.run_hash,**binding,
                created_utc=datetime.now(timezone.utc).isoformat(),source_files=files,
                runtime=dict(python=platform.python_version(),platform=platform.platform(),
                    processor=platform.processor(),logical_cpus=os.cpu_count(),worker_processes=1,
                    packages={p:importlib.metadata.version(p) for p in ('scipy','shapely','jsonschema','pytest','matplotlib')}),
                restart='Completed cases are verified and reused. Interrupted cases restart from their input.',
                timing='Search wall caps are soft and checked between operations. Setup, generation, and audit overhead are reported separately from search.')
            atomic_json(manifest_path,self.manifest)

    def run_case(self,case,*,method='search',budget=None,metadata=None,strategy='H'):
        path = self.path/'records'/f'{case.name}.json'
        request = dict(scenario_hash=case.scenario.content_hash(),library_hash=case.library.content_hash(),
                       method=method,budget=budget or {},strategy=strategy,metadata=metadata or {})
        request_hash = digest(request)
        if path.exists():
            record = json.loads(path.read_text(encoding='utf-8'))
            if record_hash(record) != record.get('record_hash'):
                raise ValueError('record hash mismatch')
            if record['run_hash'] != self.run_hash or record['request_hash'] != request_hash:
                raise ValueError('record belongs to another frozen request')
            if not audit_record(record): raise ValueError('stored certificate replay failed')
            return record
        start = perf_counter()
        if method=='controlled':
            result = controlled_record(case)
        elif method=='boundary':
            from .generators import boundary_record
            result = boundary_record(case,budget or {})
        elif method=='search':
            result = recover_local(case.scenario,case.library,strategy=strategy,**(budget or {}))
        elif method=='near_boundary':
            if strategy != 'H': raise ValueError('near-boundary search requests minimum-scope evidence')
            from .near_search import recover_near_boundary
            result = recover_near_boundary(case.scenario,case.library,**(budget or {}))
        else:
            raise ValueError('unknown record method')
        solve_time = perf_counter()-start
        audit_start = perf_counter()
        if not verify_local_evidence(case.scenario,case.library,result):
            raise ValueError('new certificate replay failed; no completed record written')
        record = dict(version='final-benchmark-case-v1',run_hash=self.run_hash,request_hash=request_hash,
            request=request,case_id=case.name,scenario=case.scenario.to_dict(),library=case.library.to_dict(),
            result=result,timing=dict(solve_s=solve_time,audit_s=perf_counter()-audit_start),audit_passed=True)
        record['record_hash'] = record_hash(record)
        atomic_json(path,record)
        return record
