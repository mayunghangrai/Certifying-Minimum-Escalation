from copy import deepcopy

import pytest

from final_benchmark.controlled import controlled_case, controlled_record
from env.local_scope import affected_uavs
from env.wind_dependency import diagnose_wind_update
from recovery.local_search import verify_local_evidence, verify_local_witness
from recovery.physical_proofs import verify_physical_certificate


@pytest.mark.parametrize('name,level',[('C0',0),('C1',1),('C2',2),('C3',3),('C4',4),('Cinf','infinity')])
def test_six_operationally_distinct_certified_cases(name,level):
    case = controlled_case(name)
    result = controlled_record(case)
    assert result['previous_premise']['exact_feasible'] is True
    assert result['full_domain']['minimum'] == level
    assert result['represented']['minimum'] == level
    assert result['affected']['uavs'] == ['U1']
    assert verify_local_evidence(case.scenario,case.library,result)
    if level != 'infinity':
        assert result['witness']['validation']['level'] == level
        assert result['witness']['exact']
    if level in (1,2):
        assert result['change']['assignment_changes'] == 0
    if level == 3: assert result['change']['outside_changed'] == 1
    if level == 4: assert result['change']['outside_changed'] == 2


def test_physical_certificate_is_input_bound_and_rejects_forged_level():
    c = controlled_case('C3')
    cert = controlled_record(c)['physical_certificates'][0]
    assert verify_physical_certificate(c.scenario,cert)
    bad = deepcopy(cert)
    bad['excluded_through'] = 4
    assert not verify_physical_certificate(c.scenario,bad)
    assert not verify_physical_certificate(controlled_case('C0').scenario,cert)


def test_a_path_library_failure_never_implies_full_infeasibility():
    c = controlled_case('C1', include_bypass=False)
    from recovery.local_search import recover_local
    r = recover_local(c.scenario,c.library,max_nodes=15000,max_branches=1500)
    assert r['represented']['minimum'] == 'infinity'
    assert r['full_domain']['minimum'] is None
    assert r['full_domain']['excluded_levels'] == [0]
    assert verify_local_evidence(c.scenario,c.library,r)


def test_incomplete_helper_patch_coverage_cannot_certify_level_three_empty():
    from recovery.local_search import recover_local
    c = controlled_case('Cinf')
    r = recover_local(c.scenario,c.library,max_nodes=15000,max_branches=1500)
    third = next(x for x in r['levels'] if x['level']==3)
    assert third['status']=='EMPTY' and len(third['patches'])==2
    third['patches'].pop()
    assert not verify_local_evidence(c.scenario,c.library,r)


@pytest.mark.parametrize('name',['C0','C1','C2','C3','C4','Cinf'])
def test_nonzero_operation_companions(name):
    c = controlled_case(name, operation_time=.01)
    r = controlled_record(c)
    assert r['full_domain']['minimum'] == c.expected


def test_scope_collapse_is_recorded_as_a_sufficient_equality():
    c = controlled_case('C3', helper_budget=2)
    r = controlled_record(c)
    assert r['scope3_equals_scope4'] == 'certified_equal'


def test_first_helper_can_fail_while_another_patch_succeeds():
    from env.scenario import Scenario
    from recovery.representation import PathLibrary
    from final_benchmark.controlled import make_plan
    from recovery.physical_proofs import physical_certificate
    from env.local_scope import scope_family, patch_contains
    from env.plan import coordinates
    p = controlled_case('C3').scenario.to_dict()
    p['mission']['vehicles'][1]['airspeed_kmh'] = 2.5
    p['mission']['vehicles'][2]['airspeed_kmh'] = 1.5
    p['incumbent'],p['reserve_paths'] = make_plan(p,dict(U1=['C'],U2=['D'],U3=['E']))
    s = Scenario(p)
    candidate,reserves = make_plan(p,dict(U1=['E'],U2=['D'],U3=['C']))
    first,second = scope_family(s,3,{'U1'})
    assert not patch_contains(s,coordinates(s.data,candidate),first)
    assert patch_contains(s,coordinates(s.data,candidate),second)
    assert verify_local_witness(s,PathLibrary.build(s),candidate,reserves,3)['exact']
    assert physical_certificate(s,3) is None


def test_structural_reachability_survives_unchanged_crosswind_speed():
    from env.scenario import Scenario
    p = controlled_case('Cinf').scenario.to_dict()
    p['mission']['tasks'][0]['deadline_h'] = 2
    p['wind']['previous']['values'][1][0] = [0,.6]
    p['wind']['received']['values'][1][0] = [0,-.6]
    s = Scenario(p)
    d = diagnose_wind_update(s)
    assert affected_uavs(s,d)['uavs'] == ['U1']
    assert d.previous.records['U1'][1]['arrival_h'] == d.received.records['U1'][1]['arrival_h']


def test_irrelevant_update_has_empty_u0():
    from env.scenario import Scenario
    p = controlled_case('Cinf').scenario.to_dict()
    p['wind']['time_knots_h'] = [0,10,20]
    for projection in ('previous','received'):
        p['wind'][projection].update(values=[[[0,0],[0,0]],[[0,0],[0,0]]],
                                    admissible=[[True,True],[True,True]],coverage=['forecast','forecast'])
    p['wind']['received']['values'][1][1] = [-.2,0]
    p['wind']['update_support'] = [['east',1]]
    s = Scenario(p)
    assert affected_uavs(s,diagnose_wind_update(s))['uavs'] == []


def test_auxiliary_return_can_change_at_level_zero_after_airspace_closure():
    from env.scenario import Scenario
    from recovery.representation import PathLibrary
    from recovery.local_search import recover_local
    p = controlled_case('C0').scenario.to_dict()
    p['wind']['cells'] = [p['wind']['cells'][0],
        dict(id='ELOW',polygon_xy=[[0,-1],[3,-1],[3,.5],[0,.5]]),
        dict(id='EUPPER',polygon_xy=[[0,.5],[3,.5],[3,3],[0,3]])]
    for projection in ('previous','received'):
        p['wind'][projection].update(values=[[[0,0]],[[0,0]],[[0,0]]],admissible=[[True],[True],[True]])
    p['wind']['received']['admissible'][2][0] = False
    p['wind']['update_support'] = [['EUPPER',0]]
    p['reserve_paths']['U1']['1'] = [[1,0],[1,1],[0,1],[0,0]]
    s = Scenario(p)
    r = recover_local(s,PathLibrary.build(s),max_nodes=1000,max_branches=100)
    assert r['full_domain']['minimum'] == 0
    assert r['change']['changed_uavs'] == []
    assert r['witness']['reserve_paths']['U1']['1'] != p['reserve_paths']['U1']['1']
    assert verify_local_evidence(s,PathLibrary.build(s),r)


@pytest.mark.parametrize('threshold,offset,expected',[
    ('1/11',-1,0),('1/11',0,0),('1/11',1,3),
    ('13/22',-1,3),('13/22',0,3),('13/22',1,4)])
def test_exact_cascade_transition_sides(threshold,offset,expected):
    from fractions import Fraction
    from dataclasses import replace
    from env.scenario import Scenario
    from recovery.representation import PathLibrary
    from final_benchmark.controlled import Case
    base = controlled_case('C3')
    p = base.scenario.to_dict()
    p['wind']['received']['values'][1][0] = [str(-(Fraction(threshold)+offset*Fraction(1,2200))),0]
    s = Scenario(p)
    candidate = controlled_case({0:'C0',3:'C3',4:'C4'}[expected])
    c = Case('transition',s,PathLibrary.build(s),expected,candidate.witness_plan,candidate.witness_reserves)
    assert controlled_record(c)['full_domain']['minimum'] == expected
