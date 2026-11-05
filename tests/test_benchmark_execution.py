import copy
import pytest
from env.scenario import Scenario
from test_benchmark_contract import raw


def execute(p=None, projection='received', **kwargs):
    from env.fixed_plan import evaluate_plan
    return evaluate_plan(Scenario.from_dict(raw() if p is None else p),projection=projection,**kwargs)


def test_previous_incumbent_is_a_complete_feasible_witness():
    r=execute(projection='previous')
    assert r.status=='feasible' and r.complete
    assert not r.violations and not r.unresolved
    u1=r.records['U1']
    assert u1[1]['arrival_h']==pytest.approx(1.9)
    assert u1[1]['delivery_h']==pytest.approx(1.95)
    assert u1[1]['onboard_after']==pytest.approx(.5)
    assert u1[2]['onboard_after']==pytest.approx(1.5)
    assert u1[3]['delivery_h']==pytest.approx(3.7)
    assert u1[4]['arrival_h']==pytest.approx(4.5)
    assert r.delivered==pytest.approx({'A':3.,'B':1.5,'C':1.})
    assert r.depot_stock_remaining==pytest.approx(.5)
    assert r.final_states['U2']['onboard']==pytest.approx(.5)
    assert r.conservation_error==pytest.approx(0.)


def test_residual_service_is_applied_once_and_credit_occurs_at_completion():
    r=execute(projection='previous')
    record=r.records['U2'][1]
    assert record['arrival_h']==1.
    assert record['delivery_h']==1.05
    assert record['onboard_before']==.5 and record['onboard_after']==0.
    assert record['battery_after']==pytest.approx(89.8)


def test_paired_local_update_changes_downstream_time_energy_but_no_inputs():
    from env.fixed_plan import evaluate_pair
    s=Scenario.from_dict(raw()); original=s.content_hash()
    before,after=evaluate_pair(s)
    assert before.status=='feasible'
    assert after.complete and after.status=='infeasible'
    assert 'deadline:U1:3:A' in after.violations
    assert after.records['U1'][3]['delivery_h']==pytest.approx(4.0375)
    assert after.records['U1'][1]['flight_energy_wh']>before.records['U1'][1]['flight_energy_wh']
    assert s.content_hash()==original
    assert before.input_hash==after.input_hash==original
    assert before.delivered==after.delivered


def test_benign_update_retains_feasibility_and_late_update_has_undefined_suffix():
    assert execute(raw('benign_update')).status=='feasible'
    r=execute(raw('horizon_late'))
    assert not r.complete and r.status=='infeasible'
    assert any(v.startswith('horizon:') for v in r.violations)
    assert r.records['U1'][3]['arrival_h'] is None
    assert r.records['U1'][3]['onboard_after'] is None
    assert r.final_states['U1'] is None
    # Q_i is a sum of declared transfers, hence remains defined. The later
    # deadline needs an unavailable induced completion time.
    assert 'deadline:U1:3:A' in r.unresolved
    assert 'service:A' not in r.unresolved
    assert r.conservation_error is None


@pytest.mark.parametrize('change,reason', [
    (lambda p:p['state'].update(depot_stock=5.),'inventory'),
    (lambda p:p['mission']['vehicles'][0].update(payload_capacity_kg=3.),'payload:U1:0'),
    (lambda p:p['incumbent']['routes']['U1']['deliveries'].__setitem__(1,3.),'delivery_availability:U1:1'),
    (lambda p:p['mission']['vehicles'][0].update(battery_capacity_wh=80.,reserve_wh=70.),'depot_arrival_reserve:U1:2'),
    (lambda p:p['mission']['tasks'][0].update(deadline_h=1.92),'deadline:U1:1:A'),
    (lambda p:p['operations'].update(preparation_duration_h=8.),'horizon:U1:0:ground'),
    (lambda p:p['incumbent']['routes']['U1']['deliveries'].__setitem__(3,1.),'service:A'),
])
def test_full_mission_constraints_are_enforced(change,reason):
    p=raw(); change(p)
    result=execute(p,'previous')
    assert result.status=='infeasible'
    assert reason in result.violations


def test_failed_or_missing_supplied_reserve_witness_is_unresolved_not_empty():
    p=raw()
    # A deliberately wasteful witness; nominal mission still meets every known constraint.
    p['reserve_paths']['U1']['1']=[[9,1],[1,1],[9,1],[1,1],[9,1],[1,1],[9,1],[1,1]]
    r=execute(p,'previous')
    assert r.complete and not r.violations
    assert r.status=='unresolved' and 'reserve:U1:1' in r.unresolved
    p=raw(); del p['reserve_paths']['U1']['1']
    assert execute(p,'previous').status=='unresolved'


def test_previous_infeasible_fixture_is_rejected_by_pair_runner():
    from env.fixed_plan import evaluate_pair
    p=raw(); p['state']['depot_stock']=0.
    with pytest.raises(ValueError,match='previous'):
        evaluate_pair(Scenario.from_dict(p))
