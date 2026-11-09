"""Frozen inputs, proof replay, and conditional continuous boundary sampling."""
from copy import deepcopy
from fractions import Fraction
import importlib
import json
from pathlib import Path

from continuous.search import verify_deadline_certificate
from continuous.validation import certify_witness, previous_premise


def test_all_128_paired_inputs_keep_the_original_scenario_and_policy():
    mod = importlib.import_module('continuous_benchmark.records')
    bank = Path(__file__).resolve().parents[1]/'results/study3_near_boundary_2026_10_01/primary'
    records, binding = mod.load_paired_bank(bank, audit=False)
    assert len(records) == binding['count'] == 128
    for r in records:
        assert r['request']['scenario_hash'] == mod.Scenario(r['scenario']).content_hash()
        original = json.loads((bank/'records'/f"{r['case_id']}.json").read_text())
        assert r['scenario'] == original['scenario']
        assert r['request']['metadata'] == original['request']['metadata']
    assert len(binding['records']) == 128


def test_continuous_record_replay_rejects_tampering(tmp_path):
    records = importlib.import_module('continuous_benchmark.records')
    cases = importlib.import_module('continuous_benchmark.cases').controlled_cases()
    case = next(c for c in cases if c.name == 'arbitrary_angle')
    store = records.ContinuousRunStore(tmp_path, {'stage': 'controlled'})
    r = store.run_case(case, budget=dict(max_seconds=10, max_proposals=30, refinements=[1]))
    assert records.audit_record(r)
    bad = deepcopy(r)
    bad['scenario']['hierarchy']['helper_budget'] = 0
    bad['record_hash'] = records.record_hash(bad)
    assert not records.audit_record(bad)
    assert store.run_case(case, budget=dict(max_seconds=10, max_proposals=30, refinements=[1])) == r


def test_fresh_cohort_brackets_a_certified_continuous_level_one_boundary():
    cases = importlib.import_module('continuous_benchmark.cases')
    pair, meta = cases.boundary_pair(3, 3, 'uniform', 51001, max_attempts=12, refinements=(1,))
    assert meta['status'] == 'accepted'
    below, above = pair
    assert meta['selection_uses_recovery_labels'] is False
    assert verify_deadline_certificate(below.scenario, meta['boundary_certificate'])
    assert meta['boundary_certificate']['excluded_through'] == 1
    assert all(previous_premise(c.scenario)['accepted'] for c in pair)
    assert certify_witness(above.scenario, meta['reference_plan'], meta['reference_reserves'], 1)['accepted']
    task = meta['critical_task']
    low_deadline = next(t['deadline_h'] for t in below.scenario.data['mission']['tasks'] if t['id'] == task)
    high_deadline = next(t['deadline_h'] for t in above.scenario.data['mission']['tasks'] if t['id'] == task)
    assert Fraction(str(low_deadline)) < Fraction(meta['updated_lower'])
    assert Fraction(str(high_deadline)) > Fraction(meta['updated_upper'])


def test_cohort_generation_is_deterministic_and_retains_failed_slots():
    cases = importlib.import_module('continuous_benchmark.cases')
    a, ma = cases.boundary_pair(3, 3, 'uniform', 51001, max_attempts=12, refinements=(1,))
    b, mb = cases.boundary_pair(3, 3, 'uniform', 51001, max_attempts=12, refinements=(1,))
    assert [c.scenario.content_hash() for c in a] == [c.scenario.content_hash() for c in b]
    assert ma == mb
    failed, ledger = cases.boundary_pair(3, 3, 'uniform', 51002, max_attempts=0)
    assert failed == ()
    assert ledger['status'] == 'generation_failed'
    assert ledger['attempts'] == []


def test_runner_audits_failed_sampling_slots_without_replacement(tmp_path):
    mod = importlib.import_module('continuous_benchmark.cli')
    config = dict(stage='cohort', phase='test', sizes=[[3, 3]], families=['uniform'], seeds=[51002],
                  max_attempts=0, offset='1/10', generation_refinements=[1],
                  budget=dict(max_seconds=1, max_proposals=0, refinements=[1]))
    mod.run_cohort(tmp_path, config)
    audit = mod.audit_run(tmp_path)
    assert audit['sampling'] == dict(requested=1, accepted=0, failed=1)
    assert audit['records'] == 0
    report = importlib.import_module('continuous_benchmark.report').write_report(tmp_path)
    assert report['cases'] == 0
    assert report['sampling']['failed'] == 1
    assert (tmp_path/'analysis/cases.csv').is_file()
    ledger = next((tmp_path/'sampling').glob('*.json'))
    ledger.unlink()
    import pytest
    with pytest.raises(ValueError, match='sampling'):
        mod.audit_run(tmp_path)


def test_sampling_replay_rejects_rehashed_admission_and_attempt_tampering():
    import pytest
    mod = importlib.import_module('continuous_benchmark.cli')
    ledger_path = Path(__file__).resolve().parents[1]/'results/continuous_paths_2026_10_05/pilot/cohort/sampling/CB_3_3_uniform_51001.json'
    item = json.loads(ledger_path.read_text())
    for key, value in [('previous_upper', '999999'), ('delay', '-10'), ('reference_gap', '-1'),
                       ('affected_count', 999), ('locality_limit', 0), ('attempts', [])]:
        bad = deepcopy(item)
        bad['metadata'][key] = value
        bad['binding_hash'] = mod.digest({k:v for k,v in bad.items() if k != 'binding_hash'})
        with pytest.raises(ValueError):
            mod._audit_sampling(bad)
