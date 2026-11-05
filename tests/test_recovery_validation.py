import copy
import json

import pytest

from env.scenario import Scenario
from recovery_cases import worked, permutation, diagnostic_cases


def validate(p=None, order=(2,1,3,4), level=3, **kwargs):
    from env.recovery_validation import validate_recovery_plan
    p = worked('A') if p is None else p
    candidate, paths = permutation(p,order)
    return validate_recovery_plan(Scenario.from_dict(p),candidate,level,
                                  reserve_paths=kwargs.get('reserve_paths',paths))


def test_success_combines_scope_physics_and_reserves_but_only_bounds_level():
    r = validate()
    assert r.status == 'witness'
    assert r.structure['valid'] and r.commitments['valid'] and r.scope['allowed']
    assert r.mission['status'] == 'feasible'
    assert all(c['status'] == 'witness' for c in r.reserves['checks'].values())
    assert r.feasible_level_upper_bound == 3 and not r.minimum_certified
    assert r.scope['memberships'] == [False,False,False,True,True]
    assert r.diagnostic.neighborhood == {'T1','T2'}
    json.dumps(r.to_dict(), allow_nan=False)


def test_feasible_candidate_at_wrong_declared_level_reports_permission_failure():
    r = validate(level=2)
    assert r.structure['valid'] and r.commitments['valid']
    assert not r.scope['allowed'] and r.mission['status'] == 'feasible'
    assert r.status == 'rejected' and r.feasible_level_upper_bound is None


def test_success_at_level_four_can_provide_a_tighter_candidate_upper_bound():
    r = validate(level=4)
    assert r.feasible_level_upper_bound == 3
    assert not r.minimum_certified


def test_scope_allowed_but_infeasible_candidate_does_not_exclude_any_level():
    r = validate(order=(1,2,3,4),level=4)
    assert r.scope['allowed'] and r.status == 'rejected'
    assert 'deadline:U1:1:T1' in r.mission['violations']
    assert r.feasible_level_upper_bound is None and not r.minimum_certified


@pytest.mark.parametrize('candidate', [None, {}, {'assignment':{},'routes':{}}, [1,2], float('nan')])
def test_malformed_candidates_return_structural_report_instead_of_crashing(candidate):
    from env.recovery_validation import validate_recovery_plan
    r = validate_recovery_plan(Scenario.from_dict(worked()),candidate,4,reserve_paths={})
    assert r.status == 'rejected' and not r.structure['valid']
    assert r.mission['status'] == 'not_evaluated'
    assert r.feasible_level_upper_bound is None


def test_commitment_violation_is_reported_separately_from_structural_validity():
    r = validate(order=(3,2,1,4),level=4)
    assert r.structure['valid'] and not r.commitments['valid']
    assert any('P:U1:1' in v for v in r.commitments['violations'])
    assert r.status == 'rejected' and r.feasible_level_upper_bound is None


def test_missing_witness_is_unresolved_and_never_an_empty_scope_certificate():
    r = validate(reserve_paths={})
    assert r.scope['allowed'] and r.reserves['input_valid']
    assert r.status == 'unresolved' and r.feasible_level_upper_bound is None
    assert r.mission['status'] == 'unresolved'


@pytest.mark.parametrize('paths',[[],{'unknown':{}},{'U1':[]},{'U1':{'wrong':[[0,0]]}},
                                 {'U1':{'1':[[0,0]]}},{'U1':{'1':[[1,0],[float('nan'),0]]}}])
def test_invalid_witness_data_cannot_generate_a_bound_or_hide_mission_checks(paths):
    r = validate(order=(1,2,3,4),reserve_paths=paths)
    assert not r.reserves['input_valid'] and r.reserves['errors']
    assert 'deadline:U1:1:T1' in r.mission['violations']
    assert r.status == 'rejected' and r.feasible_level_upper_bound is None


def test_initial_reserve_only_failure_remains_unresolved_in_combined_report():
    from env.recovery_validation import validate_recovery_plan
    p = diagnostic_cases()['reserve_only']
    r = validate_recovery_plan(Scenario.from_dict(p),p['incumbent'],0,reserve_paths=p['reserve_paths'])
    assert r.scope['allowed'] and not r.mission['violations']
    assert r.status == 'unresolved' and r.feasible_level_upper_bound is None


@pytest.mark.parametrize('level',[True,-1,5,'3',1.5])
def test_invalid_requested_level_is_rejected(level):
    with pytest.raises(ValueError): validate(level=level)


@pytest.mark.parametrize('field',['load','path','reserve'])
def test_unrepresentable_external_numbers_return_a_json_safe_rejection(field):
    from env.recovery_validation import validate_recovery_plan
    p = worked('A'); candidate,paths = permutation(p,[2,1,3,4])
    paths = copy.deepcopy(paths)
    if field == 'load': candidate['routes']['U1']['loads'][0] = 10**400
    elif field == 'path': candidate['routes']['U1']['paths'][0][0][0] = 10**400
    else: paths['U1']['1'][0][0] = 10**400
    r = validate_recovery_plan(Scenario.from_dict(p),candidate,4,reserve_paths=paths)
    assert r.status == 'rejected' and r.feasible_level_upper_bound is None
    json.dumps(r.to_dict(),allow_nan=False)


def test_finite_inputs_that_overflow_arithmetic_remain_explicit_and_json_safe():
    from env.recovery_validation import validate_recovery_plan
    p = worked('A'); candidate,paths = permutation(p,[2,1,3,4])
    for u in ('U1','U2'): candidate['routes'][u]['loads'][0] = 1e308
    r = validate_recovery_plan(Scenario.from_dict(p),candidate,4,reserve_paths=paths)
    assert r.status == 'rejected' and r.feasible_level_upper_bound is None
    assert 'inventory' in r.mission['violations']
    assert any(reason.startswith('numerical:') for reason in r.mission['unresolved'])
    assert r.mission['evaluation']['conservation_error'] is None
    json.dumps(r.to_dict(),allow_nan=False)
