import copy
import pytest
from env.scenario import Scenario
from env.fixed_plan import evaluate_plan
from test_benchmark_contract import raw


def depot_pair():
    p=raw()
    p['state']['fleet']['U2']={'position_xy':[1.,1.],'battery_wh':90.,'onboard':.5,'mode':'idle','residual_operation':None}
    p['incumbent']['routes']['U2']['paths'][0]=[[1.,1.],[3.,5.]]
    p['reserve_paths']['U2']['initial']=[[1.,1.]]
    return p


def test_bay_conflict_is_infeasible_without_inventing_a_queue():
    p=depot_pair(); p['operations']['depot_bays']=1
    r=evaluate_plan(Scenario.from_dict(p),projection='previous')
    assert 'depot_bays' in r.violations
    assert r.records['U1'][0]['departure_h']==r.records['U2'][0]['departure_h']==1.1
    p['operations']['depot_bays']=None
    r=evaluate_plan(Scenario.from_dict(p),projection='previous')
    assert 'depot_bays' not in r.violations


def test_pending_service_uses_residual_duration_energy_and_transfers():
    p=raw(); p['operations']['service_duration_h']=.2; p['operations']['service_energy_wh']=2.
    p['state']['fleet']['U2']['residual_operation'].update(duration_h=.02,energy_wh=.1)
    r=evaluate_plan(Scenario.from_dict(p),projection='previous')
    first=r.records['U2'][1]
    assert first['delivery_h']==pytest.approx(1.02)
    assert first['battery_after']==pytest.approx(89.9)
    assert first['onboard_after']==0.
    assert r.records['U2'][3]['service_energy_wh']==2.


def test_pending_preparation_keeps_onboard_load_and_uses_only_unfinished_loading():
    p=raw()
    p['state']['fleet']['U1'].update(onboard=1.,mode='preparing',residual_operation={'duration_h':.03,'energy_wh':0.,'delivery':0.,'load':1.})
    p['incumbent']['routes']['U1']['loads'][0]=1.
    p['commitments']['L'].append('U1:0:y')
    r=evaluate_plan(Scenario.from_dict(p),projection='previous')
    assert r.records['U1'][0]['departure_h']==pytest.approx(1.03)
    assert r.records['U1'][0]['onboard_after']==2.
    assert r.records['U1'][0]['battery_after']==100.
    assert r.depot_stock_remaining==pytest.approx(1.5)
    assert r.conservation_error==pytest.approx(0.)


def test_idle_terminal_does_not_recharge_and_zero_demand_needs_no_assignment():
    p=raw()
    for t in p['mission']['tasks']:
        p['state']['cumulative_delivered'][t['id']]=t['demand']
    p['incumbent']['assignment']={}
    for u in ('U1','U2'):
        p['state']['fleet'][u]={'position_xy':[1.,1.],'battery_wh':9.,'onboard':0.,'mode':'idle','residual_operation':None}
        p['incumbent']['routes'][u]={'stops':[None]*5,'paths':[[[1.,1.]]]*5,'loads':[0.]*6,'deliveries':[0.]*6}
        p['reserve_paths'][u]={}
    p['commitments']={a:[] for a in ('A','S','P','L')}
    r=evaluate_plan(Scenario.from_dict(p),projection='previous')
    assert r.complete and r.status=='infeasible'
    assert r.final_states['U1']['battery_wh']==9.
    assert 'terminal:U1' in r.violations


def test_initial_depot_battery_below_reserve_can_be_prepared():
    p=raw(); p['state']['fleet']['U1']['battery_wh']=0.
    assert evaluate_plan(Scenario.from_dict(p),projection='previous').status=='feasible'


def test_positive_delivery_deadline_is_service_completion_not_arrival():
    p=raw(); p['mission']['tasks'][0]['deadline_h']=1.92
    r=evaluate_plan(Scenario.from_dict(p),projection='previous')
    assert r.records['U1'][1]['arrival_h']<1.92<r.records['U1'][1]['delivery_h']
    assert 'deadline:U1:1:A' in r.violations


def test_late_ground_operation_does_not_credit_unfinished_delivery_or_load():
    p=raw(); p['state']['fleet']['U2']['residual_operation']['duration_h']=8.
    r=evaluate_plan(Scenario.from_dict(p),projection='previous')
    assert 'horizon:U2:1:ground' in r.violations
    assert r.records['U2'][1]['delivery_h'] is None
    assert r.records['U2'][1]['onboard_after'] is None
    assert r.delivered['C']==0.
    assert r.records['U2'][2]['arrival_h'] is None


def test_scope_permission_is_not_a_mission_feasibility_certificate():
    from env.intervention_scope import check_scope
    s=Scenario.from_dict(raw()); p=s.to_dict()['incumbent']
    p['routes']['U1']['deliveries'][3]=0.
    assert check_scope(s,p,2).allowed
    r=evaluate_plan(s,p,projection='previous',reserve_paths={})
    assert r.status=='infeasible' and 'service:A' in r.violations


def colocated_service():
    def replace(value):
        if value==[3.,5.]: return [1.,1.]
        if isinstance(value,list): return [replace(v) for v in value]
        if isinstance(value,dict): return {k:replace(v) for k,v in value.items()}
        return value
    return replace(raw())


def test_service_at_depot_coordinates_finishes_before_any_depot_preparation():
    r=evaluate_plan(Scenario.from_dict(colocated_service()),projection='previous')
    assert r.records['U2'][0]['departure_h']==1.
    assert r.records['U2'][0]['battery_after']==90.
    assert r.records['U2'][1]['delivery_h']==pytest.approx(1.05)
    assert r.records['U2'][1]['battery_after']==pytest.approx(89.8)
    # Only the subsequent explicit DEPOT visit prepares/recharges.
    assert r.records['U2'][2]['departure_h']==pytest.approx(1.15)
    assert r.records['U2'][2]['battery_after']==100.


def test_unfinished_service_cannot_load_before_it_completes():
    p=colocated_service(); p['incumbent']['routes']['U2']['loads'][0]=.5
    with pytest.raises(ValueError): Scenario.from_dict(p)


def test_airborne_virtual_origin_at_depot_coordinates_cannot_recharge_or_load():
    p=raw(); p['state']['fleet']['U1'].update(mode='airborne',onboard=2.)
    p['incumbent']['routes']['U1']['loads'][0]=0.
    r=evaluate_plan(Scenario.from_dict(p),projection='previous')
    assert r.records['U1'][0]['departure_h']==1.
    assert r.records['U1'][0]['battery_after']==80.
    p['incumbent']['routes']['U1']['loads'][0]=1.
    with pytest.raises(ValueError): Scenario.from_dict(p)
