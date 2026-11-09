import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))

import pytest

from escalation_study.audit import AuditError, Auditor, audit_run
from escalation_study.runner import run
from escalation_study.store import read_gzip_json, record_hash, write_gzip_json

BUDGET = {'refinements': [2, 4], 'digits': 18, 'max_operations': 100000, 'max_rows': 10000,
          'screen': {'max_seconds': 20, 'max_proposals': 40}, 'level2': {'max_seconds': 4, 'max_nodes': 100000},
          'level3': {'max_seconds': 2, 'max_nodes': 100000}, 'level4': {'max_seconds': 2, 'max_nodes': 100000}}
CONFIG = {'study': 'P1', 'phase': 'test', 'tasks': [8], 'uavs': 4, 'families': ['uniform'], 'seeds': [71001],
          'strengths': ['3/5'], 'slacks': ['1/50', '1/1000'], 'battery_slack': '3/2', 'max_attempts': 24,
          'budget': BUDGET, 'pass2_budget': BUDGET}
MISSION = 'P1_8_4_uniform_71001'


@pytest.fixture(scope='module')
def run_dir(tmp_path_factory):
    path = tmp_path_factory.mktemp('p1')/'run'
    run(path, CONFIG, workers=1, log=lambda line: None)
    return path


def _records(path):
    return {p.name[:-8]: p for p in sorted((path/'records'/'pass1').rglob('*.json.gz'))}


def test_run_publishes_audited_chain_and_resumes(run_dir):
    records = _records(run_dir)
    assert set(records) == {f'{MISSION}_r0_s0', f'{MISSION}_r0_s1'}
    tight = read_gzip_json(records[f'{MISSION}_r0_s1'])['result']
    loose = read_gzip_json(records[f'{MISSION}_r0_s0'])['result']
    assert tight['bounds']['lower'] >= loose['bounds']['lower']
    if loose['bounds']['excluded_levels']:
        assert tight['transfer']['source'] == f'{MISSION}_r0_s0'
    assert audit_run(run_dir, log=lambda line: None)['records'] == 2
    # A rerun finds every chain published and adds nothing.
    outcome, = run(run_dir, CONFIG, workers=1, log=lambda line: None)
    assert outcome['records'] == []


def _tamper(run_dir, tmp_path, case, change):
    copy = tmp_path/'copy'
    shutil.copytree(run_dir, copy)
    path = _records(copy)[case]
    record = read_gzip_json(path)
    change(record)
    record['record_hash'] = record_hash(record)
    path.unlink()
    write_gzip_json(path, record)
    return copy


def test_audit_rejects_overstated_bounds(run_dir, tmp_path):
    def change(record):
        record['result']['bounds'] = dict(record['result']['bounds'], minimum=4, lower=4, upper=4,
                                          excluded_levels=[0, 1, 2, 3], status='minimum_certified')
    copy = _tamper(run_dir, tmp_path, f'{MISSION}_r0_s0', change)
    with pytest.raises(AuditError):
        Auditor(copy).audit('pass1', MISSION, f'{MISSION}_r0_s0')


def test_audit_rejects_transfer_beyond_source_evidence(run_dir, tmp_path):
    def change(record):
        record['result']['transfer'] = dict(kind='monotone_transfer_v1', source=f'{MISSION}_r0_s0',
                                            excluded_through=3, source_phase='pass1',
                                            source_record_hash=read_gzip_json(_records(run_dir)[f'{MISSION}_r0_s0'])['record_hash'])
    copy = _tamper(run_dir, tmp_path, f'{MISSION}_r0_s1', change)
    with pytest.raises(AuditError):
        Auditor(copy).audit('pass1', MISSION, f'{MISSION}_r0_s1')


def test_audit_rejects_changed_deadline(run_dir, tmp_path):
    def change(record):
        record['scenario']['mission']['tasks'][0]['deadline_h'] += 1
    copy = _tamper(run_dir, tmp_path, f'{MISSION}_r0_s1', change)
    with pytest.raises(AuditError):
        Auditor(copy).audit('pass1', MISSION, f'{MISSION}_r0_s1')
