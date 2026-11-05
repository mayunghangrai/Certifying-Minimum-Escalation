from fractions import Fraction as F

import pytest

from env.scenario import Scenario
from env.intervention_scope import release_sets
from env.fixed_plan import evaluate_plan
from env.wind_dependency import diagnose_wind_update
from recovery.linear import LinearProblem, Row, solve_linear, verify_exclusion
from recovery.physics import flight_duration, UnsupportedArithmetic
from recovery.transfers import build_transfer_problem, materialize, BranchRejected
from search_cases import tiny
from recovery_cases import worked


def problem(rows):
    return LinearProblem(('x','y'), tuple(Row(tuple(map(F,a)), F(b), str(i))
                         for i,(a,b) in enumerate(rows)), True)


def test_continuous_solution_satisfies_exact_fractional_equalities():
    p = problem([([1,1],1),([-1,-1],-1),([-3,0],-1),([3,0],1),([0,-1],0)])
    r = solve_linear(p)
    assert r.status == 'WITNESS' and r.exact
    assert r.values == (F(1,3),F(2,3))


def test_infeasibility_has_independently_checkable_nonnegative_combination():
    p = problem([([1,1],1),([-1,-1],-2)])
    r = solve_linear(p)
    assert r.status == 'EMPTY' and verify_exclusion(p,r.certificate)
    corrupt = {**r.certificate,'multipliers':{'0':'-1','1':'1'}}
    assert not verify_exclusion(p,corrupt)
    assert not verify_exclusion(p,{'kind':'farkas','multipliers':{'0':'1'}})


def test_elimination_budget_cannot_be_misreported_as_empty():
    r = solve_linear(problem([([1,1],1),([-1,-1],-2)]), max_operations=0, numerical=False)
    assert r.status == 'UNRESOLVED'


def test_rational_wind_integrates_headwind_and_return_exactly():
    s = Scenario.from_dict(tiny())
    assert flight_duration(s,'U1',[[0,0],[1,0]],F(0),exact=True) == 2
    assert flight_duration(s,'U1',[[1,0],[0,0]],F(2),exact=True) == F(2,3)
    assert flight_duration(s,'U1',[[0,0]],F(4),exact=True) == 0
    assert flight_duration(s,'U1',[[0,0],[1,0]],F(3),exact=True) is None


def test_rational_wind_splits_time_bins_without_extrapolation():
    p = tiny(); p['wind']['time_knots_h'] = [0,1,4]
    p['wind']['previous']['values'] = [[[0,0],[0,0]],[[0,0],[0,0]]]
    p['wind']['received']['values'] = [[[0,0],[0,0]],[[-.5,0],[0,0]]]
    p['wind']['update_support'] = [['east',0]]
    s = Scenario.from_dict(p)
    assert flight_duration(s,'U1',[[0,0],[1,0]],F(0),exact=True) == F(3,2)


def test_irrational_length_is_explicitly_unsupported_for_exact_certificates():
    s = Scenario.from_dict(tiny())
    with pytest.raises(UnsupportedArithmetic):
        flight_duration(s,'U1',[[0,0],[1,1]],F(0),exact=True)
    assert flight_duration(s,'U1',[[0,0],[1,1]],0,exact=False) > 0


def compile_case(p, *, level=2, exact=True):
    s = Scenario.from_dict(p)
    releases = release_sets(s,level,diagnose_wind_update(s).affected_tasks)
    compiled = build_transfer_problem(s,p['incumbent'],p['reserve_paths'],releases,exact=exact)
    return s,compiled


def test_transfer_lp_delivers_fractional_mandatory_quantity_and_validates():
    p = tiny(); p['mission']['tasks'][0].update(demand=.375,mandatory=.375)
    p['state']['depot_stock'] = .375
    p['incumbent']['routes']['U1']['loads'][0] = .375
    p['incumbent']['routes']['U1']['deliveries'][1] = .375
    s,c = compile_case(p)
    r = solve_linear(c.problem)
    assert r.status == 'WITNESS' and r.exact
    plan = materialize(c,r.values)
    assert plan['routes']['U1']['deliveries'][1] == .375
    assert evaluate_plan(s,plan,reserve_paths=p['reserve_paths']).status == 'feasible'


def test_late_visit_is_zero_delivery_constraint_and_positive_mandatory_is_empty():
    p = tiny(); p['mission']['tasks'][0]['deadline_h'] = 1.5
    s,c = compile_case(p)
    r = solve_linear(c.problem)
    assert r.status == 'EMPTY' and verify_exclusion(c.problem,r.certificate)
    assert any(row.label.startswith('deadline:') for row in c.problem.rows)


def test_known_worked_branches_have_exact_opposite_feasibility():
    from recovery_cases import permutation
    p = worked('A'); s,c = compile_case(p,level=3)
    assert solve_linear(c.problem).status == 'EMPTY'
    plan,reserves = permutation(p,[2,1,3,4])
    c = build_transfer_problem(s,plan,reserves,release_sets(s,3,{'T1','T2'}),exact=True)
    assert solve_linear(c.problem).status == 'WITNESS'


@pytest.mark.parametrize('constraint', ['stock','payload','battery','reserve','bays'])
def test_each_hard_resource_constraint_rejects_a_fixed_branch(constraint):
    p = worked('A')
    # Use calm received wind so only the selected physical failure remains.
    p['wind']['received']['values'] = p['wind']['previous']['values']
    if constraint == 'stock': p['state']['depot_stock'] = 3
    if constraint == 'payload': p['mission']['vehicles'][0]['payload_capacity_kg'] = .5
    if constraint == 'battery': p['mission']['vehicles'][0]['energy_coefficient_wh_per_kg_km'] = 20
    if constraint == 'reserve': p['mission']['vehicles'][0]['reserve_wh'] = 9.9
    if constraint == 'bays': p['operations'].update(depot_bays=1,preparation_duration_h=.1)
    s = Scenario.from_dict(p)
    if constraint == 'bays':
        with pytest.raises(BranchRejected, match='depot_bays'):
            build_transfer_problem(s,p['incumbent'],p['reserve_paths'],release_sets(s,0),exact=True)
    else:
        c = build_transfer_problem(s,p['incumbent'],p['reserve_paths'],release_sets(s,0),exact=True)
        r = solve_linear(c.problem)
        assert r.status == 'EMPTY' and verify_exclusion(c.problem,r.certificate)


def test_intermediate_depot_retains_payload_and_restores_battery():
    p = tiny()
    p['mission']['horizon_h'] = 8
    p['wind']['time_knots_h'] = [0,8]
    p['wind']['received']['values'] = p['wind']['previous']['values']
    p['mission']['tasks'][0].update(demand=1.25,mandatory=1.25,deadline_h=7)
    p['mission']['vehicles'][0]['slot_bound'] = 4
    p['state']['depot_stock'] = 1.25
    p['incumbent']['routes']['U1'] = dict(stops=['T1','DEPOT','T1','DEPOT'],
        paths=[[[0,0],[1,0]],[[1,0],[0,0]]]*2,
        loads=[1,0,.25,0,0],deliveries=[0,.5,0,.75,0])
    p['reserve_paths']['U1']['3'] = [[1,0],[0,0]]
    s,c = compile_case(p,level=0)
    result = solve_linear(c.problem)
    assert result.status == 'WITNESS' and result.exact
    run = evaluate_plan(s,materialize(c,result.values),reserve_paths=p['reserve_paths'])
    assert run.status == 'feasible' and run.depot_stock_remaining == 0
    assert run.records['U1'][2]['onboard_after'] == .75
    assert run.records['U1'][2]['battery_after'] == 10


def test_residual_preparation_only_uses_unfinished_load_and_duration():
    p = tiny()
    p['state']['fleet']['U1'].update(mode='preparing',onboard=.25,battery_wh=0,
        residual_operation=dict(duration_h=.125,energy_wh=0,delivery=0,load=.75))
    p['incumbent']['routes']['U1']['loads'][0] = .75
    p['commitments']['L'] = ['U1:0:y']
    p['operations']['preparation_duration_h'] = .5
    s,c = compile_case(p,level=0)
    r = solve_linear(c.problem)
    assert r.status == 'WITNESS' and c.times[0]['departure'] == F(1,8)
    run = evaluate_plan(s,materialize(c,r.values),reserve_paths=p['reserve_paths'])
    assert run.records['U1'][0]['onboard_after'] == 1
    assert run.records['U1'][0]['battery_after'] == 10


def test_colocated_residual_service_does_not_invent_depot_preparation():
    p = tiny()
    p['mission']['tasks'][0]['position_xy'] = [0,0]
    p['state']['fleet']['U1'].update(mode='servicing',onboard=1,battery_wh=2,
        residual_operation=dict(duration_h=.125,energy_wh=.25,delivery=1,load=0))
    p['incumbent']['routes']['U1'].update(paths=[[[0,0]],[[0,0]]],loads=[0,0,0])
    p['commitments'].update(S=['U1:1','U1:2'],P=['U1:1'],L=['U1:1:x'])
    p['reserve_paths']['U1']['1'] = [[0,0]]
    p['operations'].update(service_duration_h=.5,service_energy_wh=1,preparation_duration_h=.5)
    s,c = compile_case(p,level=0)
    r = solve_linear(c.problem)
    assert r.status == 'WITNESS' and c.times[0]['departure'] == 0
    assert c.times[1]['delivery'] == F(1,8)
    assert evaluate_plan(s,materialize(c,r.values),reserve_paths=p['reserve_paths']).final_states['U1']['battery_wh'] == 1.75


def test_rational_shared_boundary_uses_lowest_cell_id():
    p = tiny()
    # On x=0, WEST owns the edge; its zero wind gives a one-hour traversal.
    s = Scenario.from_dict(p)
    assert flight_duration(s,'U1',[[0,0],[0,1]],F(0),exact=True) == 1


def test_zero_delivery_can_visit_after_deadline_without_rejecting_whole_skeleton():
    p = tiny()
    p['mission']['tasks'][0].update(mandatory=0,deadline_h=1.5)
    p['incumbent']['routes']['U1']['deliveries'][1] = 0
    s,c = compile_case(p)
    r = solve_linear(c.problem)
    assert r.status == 'WITNESS'
    assert materialize(c,r.values)['routes']['U1']['deliveries'][1] == 0


@pytest.mark.parametrize('weights',[None,[],1,'wrong'])
def test_malformed_exclusion_certificate_is_rejected(weights):
    p = problem([([1,1],1),([-1,-1],-2)])
    assert not verify_exclusion(p,{'kind':'farkas','multipliers':weights})
