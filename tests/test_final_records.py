import json

import pytest

from final_benchmark.controlled import controlled_case
from final_benchmark.records import RunStore, audit_record
from final_benchmark.generators import random_pair, boundary_case


def test_records_resume_identical_cases_and_reject_corruption(tmp_path):
    store = RunStore(tmp_path,{'study':'controlled'})
    case = controlled_case('C3')
    first = store.run_case(case,method='controlled')
    second = store.run_case(case,method='controlled')
    assert first == second
    assert audit_record(first)
    path = tmp_path/'records'/'C3.json'
    damaged = json.loads(path.read_text())
    damaged['result']['full_domain']['minimum'] = 4
    path.write_text(json.dumps(damaged))
    with pytest.raises(ValueError,match='hash'): store.run_case(case,method='controlled')


def test_run_config_cannot_change_after_freeze(tmp_path):
    RunStore(tmp_path,{'seconds':1})
    with pytest.raises(ValueError,match='frozen'): RunStore(tmp_path,{'seconds':2})


def test_failed_case_does_not_create_completed_record(tmp_path):
    store = RunStore(tmp_path,{'study':'controlled'})
    with pytest.raises(ValueError): store.run_case(controlled_case('C1',include_bypass=False),method='controlled')
    assert not (tmp_path/'records'/'C1.json').exists()


@pytest.mark.parametrize('family',['uniform','clustered'])
def test_random_generator_is_reproducible_and_feasible_before_update(family):
    a = random_pair(6,3,family,901)
    b = random_pair(6,3,family,901)
    assert [c.scenario.content_hash() for c in a] == [c.scenario.content_hash() for c in b]
    from recovery.local_search import previous_premise
    from env.wind_dependency import diagnose_wind_update
    for c in a:
        assert previous_premise(c.scenario)['exact_feasible']
        assert diagnose_wind_update(c.scenario).previous.status == 'feasible'
        c.library.validate(c.scenario)


def test_boundary_factors_preserve_previous_premise_and_reference():
    c = boundary_case('C3',severity=.3,duration=2,deadline_scale=1,battery_slack=.2)
    from recovery.local_search import previous_premise
    assert previous_premise(c.scenario)['exact_feasible']
    assert c.scenario.data['hierarchy']['helper_budget'] == 1


def test_retained_calm_tail_after_all_deadlines_does_not_weaken_physical_proof():
    from recovery.physical_proofs import physical_certificate
    c = boundary_case('C3',severity=.3,duration=2,deadline_scale=1,battery_slack=1)
    assert physical_certificate(c.scenario,2) is not None


def test_integer_wind_after_airspeed_scaling_has_valid_exact_encoding():
    c = boundary_case('C1',severity='4/5',duration=2,deadline_scale=1,battery_slack=1)
    assert c.scenario.data['wind']['received']['values'][1][0] == (-4,0)


def test_summaries_reject_corrupt_records_even_without_expensive_replay(tmp_path):
    from final_benchmark.analysis import load_records
    store = RunStore(tmp_path,{'study':'controlled'})
    store.run_case(controlled_case('C3'),method='controlled')
    path = tmp_path/'records/C3.json'
    r = json.loads(path.read_text());r['result']['represented']['minimum']=4
    path.write_text(json.dumps(r))
    with pytest.raises(ValueError,match='hash'): load_records(tmp_path,audit=False)


def test_interrupted_source_archive_cannot_acquire_a_new_manifest(tmp_path):
    (tmp_path/'source.zip').write_bytes(b'interrupted archive')
    with pytest.raises(ValueError,match='archive'): RunStore(tmp_path,{'study':'controlled'})
    assert not (tmp_path/'manifest.json').exists()


def test_external_witness_and_physical_certificate_have_acquisition_times():
    from final_benchmark.controlled import controlled_record
    r = controlled_record(controlled_case('C3'))
    e = r['effort']
    assert e['first_witness_s'] is not None
    assert e['first_witness_s'] <= e['represented_certificate_s'] <= e['elapsed_s']


def test_recoverability_membership_retains_gaps_and_ignores_numerical_candidates():
    from final_benchmark.analysis import recoverability_membership
    from recovery.local_search import bounds
    gap = bounds({0},3)
    assert [recoverability_membership(gap,k) for k in range(5)] == [
        'outside','unresolved','unresolved','inside','inside']
    assert [recoverability_membership(bounds(set(),None,1),k) for k in range(5)] == ['unresolved']*5
    assert [recoverability_membership(bounds(set(range(5)),None),k) for k in range(5)] == ['outside']*5
    assert [recoverability_membership(bounds(set(),0),k) for k in range(5)] == ['inside']*5
