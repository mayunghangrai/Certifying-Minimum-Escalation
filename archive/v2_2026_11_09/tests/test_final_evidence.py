from copy import deepcopy
from fractions import Fraction
import hashlib
import json

import pytest

from test_final_scope import revised
from env.scenario import Scenario
from env.fixed_plan import evaluate_plan
from env.route_evaluator import evaluate_path
from env.wind_dependency import diagnose_wind_update
from env.local_scope import affected_uavs
from recovery.physics import flight_duration, UnsupportedArithmetic
from recovery.representation import PathLibrary
from recovery.local_search import recover_local, verify_local_evidence, verify_local_witness


def test_missing_forecast_is_unknown_not_physical_exclusion():
    p = revised()
    p['wind']['received']['coverage'] = ['missing']*len(p['wind']['received']['coverage'])
    s = Scenario(p)
    e = evaluate_plan(s)
    assert e.status == 'unresolved'
    assert any('coverage' in key for key in e.unresolved)
    result = recover_local(s,PathLibrary.build(s),max_nodes=80,max_branches=5)
    assert result['represented']['minimum'] is None
    assert result['full_domain']['minimum'] is None
    assert result['represented']['excluded_levels'] == []


def test_explicit_retained_tail_checks_provenance_and_values():
    p = revised()
    p['wind']['received']['values'] = deepcopy(p['wind']['previous']['values'])
    p['wind']['received']['coverage'] = ['retained']*len(p['wind']['previous']['coverage'])
    p['wind']['received']['retained_from'] = hashlib.sha256(json.dumps(
        p['wind']['previous'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    s = Scenario(p)
    assert evaluate_plan(s).status == 'feasible'
    assert affected_uavs(s,diagnose_wind_update(s))['uavs'] == []
    p['wind']['received']['retained_from'] = '0'*64
    with pytest.raises(ValueError,match='retained'): Scenario(p)


def test_closed_nominal_path_has_counterfactual_time_but_no_witness():
    p = revised()
    # A closure is allowed only in the declared local support.
    cell, j = p['wind']['update_support'][0]
    r = next(i for i,c in enumerate(p['wind']['cells']) if c['id']==cell)
    p['wind']['received']['admissible'][r][j] = False
    s = Scenario(p)
    d = diagnose_wind_update(s)
    assert affected_uavs(s,d)['count'] > 0
    assert d.received.status != 'feasible'
    assert any('admissibility' in v for v in d.received.violations)


def test_rational_wind_survives_json_and_exact_crosswind_integration():
    p = revised()
    for projection in ('previous','received'):
        p['wind'][projection]['values'] = [[[0,'3/5'] for _ in row]
                                         for row in p['wind'][projection]['values']]
    p['wind']['speed_bound_kmh'] = .9
    s = Scenario(p)
    uid = s.data['mission']['vehicles'][0]['id']
    v = s.data['mission']['vehicles'][0]['airspeed_kmh']
    assert s.to_dict()['wind']['received']['values'][0][0][1] == '3/5'
    # An axis-aligned path is integrated without rounding the rational input.
    assert evaluate_path(s,uid,[[0,0],[.1,0]],0,0).status == 'complete'


def test_zero_budget_retains_unknown_and_domain_separation():
    s = Scenario(revised())
    r = recover_local(s,PathLibrary.build(s),max_nodes=0,max_branches=0)
    assert r['represented']['status'] == 'unresolved'
    assert r['full_domain']['minimum'] is None
    assert r['represented']['excluded_levels'] == []
    assert verify_local_evidence(s,PathLibrary.build(s),r)


def test_policy_and_input_tampering_invalidates_replay():
    s = Scenario(revised())
    library = PathLibrary.build(s)
    r = recover_local(s,library,max_nodes=0,max_branches=0)
    r['scenario_hash'] = '0'*64
    assert not verify_local_evidence(s,library,r)


def test_common_retention_screen_runs_before_scope_budget_allocation():
    from final_benchmark.controlled import controlled_case
    c = controlled_case('C0')
    r = recover_local(c.scenario,c.library,max_nodes=200,max_branches=20,max_seconds=.001)
    assert r['represented']['minimum'] == 0
    assert r['effort']['retention_screen'] == 'exact_witness'
    assert verify_local_evidence(c.scenario,c.library,r)


def test_reported_intervention_and_policy_are_checked_during_replay():
    from final_benchmark.controlled import controlled_case,controlled_record
    c = controlled_case('C3')
    r = controlled_record(c)
    r['change']['changed_uav_count'] += 1
    assert not verify_local_evidence(c.scenario,c.library,r)
    r = controlled_record(c)
    r['policy']['helper_budget'] = 7
    assert not verify_local_evidence(c.scenario,c.library,r)


def test_equivalent_rational_encoding_is_not_a_forecast_change():
    from final_benchmark.controlled import controlled_case
    p = controlled_case('C0').scenario.to_dict()
    p['wind']['received']['values'] = [[['0/1',0]],[['0/1',0]]]
    p['wind']['update_support'] = []
    s = Scenario(p)
    assert affected_uavs(s,diagnose_wind_update(s))['uavs'] == []
