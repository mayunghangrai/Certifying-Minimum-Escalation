import json
from pathlib import Path
import subprocess
import sys

import pytest

from env.scenario import Scenario
from recovery.representation import PathLibrary
from recovery.search import search_level, recover, verify_level_evidence, verify_witness
from recovery_cases import worked
from search_cases import tiny


@pytest.mark.parametrize('case,counts', [('A',[0,0,0,1,2]),('B',[0,0,0,6,6])])
def test_exhaustive_worked_search_recovers_counts_and_certified_minimum(case,counts):
    s = Scenario.from_dict(worked(case)); lib = PathLibrary.build(s)
    result = recover(s,lib,exhaustive=True)
    assert result['status'] == 'MINIMUM_CERTIFIED_R'
    assert result['lower_bound'] == result['upper_bound'] == 3
    assert [r['feasible_branches'] for r in result['levels']] == counts
    assert result['witness']['exact']
    for r in result['levels'][:3]:
        assert r['status'] == 'EMPTY' and verify_level_evidence(s,lib,r)
    if case == 'B':
        assert result['levels'][4]['equivalent_to'] == 3


def test_budget_exhaustion_and_live_cursor_resume_preserve_unexamined_space():
    s = Scenario.from_dict(worked('A')); lib = PathLibrary.build(s)
    first = search_level(s,lib,3,max_nodes=1,exhaustive=True)
    assert first.status == 'UNRESOLVED' and not first.to_dict()['enumeration_complete']
    second = search_level(s,lib,3,cursor=first.cursor,exhaustive=True)
    assert second.status == 'WITNESS' and second.to_dict()['enumeration_complete']
    assert second.to_dict()['feasible_branches'] == 1
    assert first.to_dict()['nodes'] == 1 and not first.to_dict()['enumeration_complete']
    with pytest.raises(ValueError,match='cursor'):
        search_level(s,lib,4,cursor=first.cursor)


def test_zero_budget_produces_no_false_infeasibility_or_bound():
    s = Scenario.from_dict(tiny()); lib = PathLibrary.build(s)
    r = recover(s,lib,max_nodes=0)
    assert r['status'] == 'UNRESOLVED_R'
    assert r['lower_bound'] == 0 and r['upper_bound'] is None


def test_irrelevant_wind_retains_plan_at_certified_level_zero():
    s = Scenario.from_dict(tiny())
    r = recover(s,PathLibrary.build(s))
    assert r['status'] == 'MINIMUM_CERTIFIED_R' and r['upper_bound'] == 0


def test_direct_path_repairs_detoured_incumbent_at_level_one():
    p = tiny(); p['mission']['tasks'][0]['deadline_h'] = 2.25
    p['incumbent']['routes']['U1']['paths'][0] = [[0,0],[-.25,0],[1,0]]
    s = Scenario.from_dict(p)
    r = recover(s,PathLibrary.build(s))
    assert r['status'] == 'MINIMUM_CERTIFIED_R' and r['upper_bound'] == 1


def test_sequence_recovery_at_level_two_preserves_assignment():
    p = tiny()
    p['mission']['vehicles'][0].update(slot_bound=3,payload_capacity_kg=2)
    p['mission']['tasks'][0]['deadline_h'] = 2.3
    p['mission']['tasks'].append(dict(id='T2',position_xy=[1,0],demand=1,mandatory=1,deadline_h=3))
    p['state']['cumulative_delivered']['T2'] = 0
    p['operations']['service_duration_h'] = .2
    p['incumbent']['assignment']['T2'] = 'U1'
    p['incumbent']['routes']['U1'] = dict(stops=['T2','T1','DEPOT'],paths=[[[0,0],[1,0]],[[1,0]],[[1,0],[0,0]]],
                                         deliveries=[0,1,1,0],loads=[2,0,0,0])
    p['reserve_paths']['U1']['2'] = [[1,0],[0,0]]
    p['commitments']['S'] = ['U1:3']
    s = Scenario.from_dict(p)
    r = recover(s,PathLibrary.build(s))
    assert r['status'] == 'MINIMUM_CERTIFIED_R' and r['upper_bound'] == 2
    assert r['witness']['plan']['assignment'] == p['incumbent']['assignment']


def test_numerical_geometry_witness_never_claims_exact_minimum():
    p = tiny()
    p['mission']['tasks'][0]['position_xy'] = [1,.1]
    route = p['incumbent']['routes']['U1']
    route['paths'] = [[[0,0],[1,.1]],[[1,.1],[0,0]]]
    p['reserve_paths']['U1']['1'] = [[1,.1],[0,0]]
    s = Scenario.from_dict(p)
    r = recover(s,PathLibrary.build(s))
    assert r['status'] == 'NUMERICAL_WITNESS_R'
    assert r['upper_bound'] is None and r['numerical_upper_bound'] == 0


def test_complete_exact_failure_can_certify_no_represented_continuation():
    p = tiny(); p['mission']['tasks'][0]['deadline_h'] = 1.5
    s = Scenario.from_dict(p); lib = PathLibrary.build(s)
    r = recover(s,lib)
    assert r['status'] == 'NO_CONTINUATION_R'
    assert r['upper_bound'] is None and r['lower_bound'] is None
    assert verify_level_evidence(s,lib,r['levels'][-1])
    corrupt = json.loads(json.dumps(r['levels'][-1])); corrupt['branch_evidence'].clear()
    assert not verify_level_evidence(s,lib,corrupt)


def test_witness_checker_rejects_out_of_library_curve_and_wrong_scope():
    p = worked('A'); s = Scenario.from_dict(p); lib = PathLibrary.build(s)
    r = recover(s,lib)
    witness = r['witness']
    assert not verify_witness(s,lib,witness['plan'],witness['reserve_paths'],0)['accepted']
    candidate = json.loads(json.dumps(witness['plan']))
    candidate['routes']['U1']['paths'][0] = [[0,0],[0,.1],[1,0]]
    assert not verify_witness(s,lib,candidate,witness['reserve_paths'],4)['accepted']


def test_cli_replays_deterministically_from_another_directory(tmp_path):
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable,str(root/'scripts/search_recovery.py'),'--scenario',
               str(root/'scenarios/worked/four_uav_case_a.json'),'--exhaustive']
    first = subprocess.run(command,cwd=tmp_path,capture_output=True,text=True,check=True)
    second = subprocess.run(command,cwd=tmp_path,capture_output=True,text=True,check=True)
    assert first.stdout == second.stdout
    assert json.loads(first.stdout)['upper_bound'] == 3


def test_exact_transfer_change_cannot_hide_behind_float_scope_equality():
    p = tiny()
    p['mission'].update(horizon_h=10,commodity_unit_mass_kg=3)
    p['mission']['tasks'][0].update(demand=1,mandatory=1,deadline_h=10)
    p['mission']['vehicles'][0].update(slot_bound=6,payload_capacity_kg=1)
    p['wind']['time_knots_h'] = [0,10]
    p['state']['depot_stock'] = 1
    q = 1/3
    p['incumbent']['routes']['U1'] = dict(stops=['T1','DEPOT']*3,
        paths=[[[0,0],[1,0]],[[1,0],[0,0]]]*3,
        deliveries=[0,q,0,q,0,q,0],loads=[q,0,q,0,q,0,0])
    p['reserve_paths']['U1'] = {'initial':[[0,0]],**{str(h):[[1,0],[0,0]] for h in (1,3,5)}}
    s = Scenario.from_dict(p)
    r = recover(s,PathLibrary.build(s),max_nodes=10000,max_branches=20)
    assert r['lower_bound'] == r['upper_bound'] == 2
    assert r['witness']['validation']['level'] == 2
    assert r['witness']['validation']['numerical_level'] == 0
    assert r['previous_premise']['numerical_feasible']
    assert r['previous_premise']['exact_feasible'] is False


def test_larger_witness_does_not_exclude_unfinished_lower_level():
    p = tiny(); p['mission']['tasks'][0]['deadline_h'] = 2.25
    p['incumbent']['routes']['U1']['paths'][0] = [[0,0],[1,0],[.75,0],[1,0]]
    s = Scenario.from_dict(p)
    r = recover(s,PathLibrary.build(s),max_branches=1)
    assert r['status'] == 'WITNESS_WITH_GAP_R'
    assert (r['lower_bound'],r['upper_bound']) == (0,1)
    assert r['certified_empty_levels'] == []


def test_reserve_search_can_retain_nominal_plan_after_diagnostic_witness_fails():
    p = tiny()
    p['reserve_paths']['U1']['1'] = [[1,0],[-1,0],[0,0]]
    p['wind']['received']['values'] = [[[-.5,0]],[[0,0]]]
    p['wind']['update_support'] = [['WEST',0]]
    s = Scenario.from_dict(p)
    r = recover(s,PathLibrary.build(s))
    assert r['status'] == 'MINIMUM_CERTIFIED_R' and r['upper_bound'] == 0
    restricted = recover(s,PathLibrary.build(s,direct=False))
    assert restricted['status'] == 'NO_CONTINUATION_R'


def test_nonrational_failed_branches_remain_unresolved_after_complete_enumeration():
    p = tiny(); p['mission']['tasks'][0].update(position_xy=[1,.1],deadline_h=1.5)
    p['incumbent']['routes']['U1']['paths'] = [[[0,0],[1,.1]],[[1,.1],[0,0]]]
    p['reserve_paths']['U1']['1'] = [[1,.1],[0,0]]
    s = Scenario.from_dict(p)
    r = search_level(s,PathLibrary.build(s),0,exhaustive=True)
    assert r.status == 'UNRESOLVED' and r.to_dict()['enumeration_complete']
    assert r.to_dict()['excluded_branches'] == 0


def test_cli_manifest_replay_and_input_overwrite_protection(tmp_path):
    root = Path(__file__).resolve().parents[1]
    scenario = root/'scenarios/worked/four_uav_case_a.json'
    s = Scenario.from_json(scenario)
    manifest = tmp_path/'paths.json'
    manifest.write_text(json.dumps(PathLibrary.build(s).to_dict()))
    command = [sys.executable,str(root/'scripts/search_recovery.py'),'--scenario',str(scenario),
               '--manifest',str(manifest),'--max-nodes','0']
    good = subprocess.run(command,cwd=tmp_path,capture_output=True,text=True)
    assert good.returncode == 0 and json.loads(good.stdout)['status'] == 'UNRESOLVED_R'
    before = manifest.read_bytes()
    bad = subprocess.run(command+['--output',str(manifest)],capture_output=True,text=True)
    assert bad.returncode == 2 and manifest.read_bytes() == before


@pytest.mark.parametrize('budget', ['max_nodes','max_branches','max_operations','max_rows','max_iterations','total_nodes'])
def test_negative_budget_is_rejected(budget):
    s = Scenario.from_dict(tiny())
    with pytest.raises(ValueError,match='budget|total_nodes'):
        recover(s,PathLibrary.build(s),**{budget:-1})


def test_cursor_retries_unresolved_linear_branch_when_given_more_budget():
    s = Scenario.from_dict(tiny()); lib = PathLibrary.build(s)
    first = search_level(s,lib,2,max_operations=0,numerical=False,exhaustive=True)
    assert first.status == 'UNRESOLVED' and first.to_dict()['enumeration_complete']
    second = search_level(s,lib,2,cursor=first.cursor,exhaustive=True)
    assert second.status == 'WITNESS' and second.to_dict()['branches'] == 1
    assert second.to_dict()['retry_attempts'] == 1
    assert first.to_dict()['unresolved_branches'] == 1


def test_malformed_witness_is_rejected_before_representation_lookup():
    s = Scenario.from_dict(tiny()); lib = PathLibrary.build(s)
    for plan in ({'routes':[]},{'routes':None},None,[]):
        assert not verify_witness(s,lib,plan,{},0)['accepted']


def test_malformed_manifest_is_a_cli_input_error(tmp_path):
    root = Path(__file__).resolve().parents[1]
    manifest = tmp_path/'paths.json'; manifest.write_text('null')
    result = subprocess.run([sys.executable,str(root/'scripts/search_recovery.py'),'--scenario',
        str(root/'scenarios/worked/four_uav_case_a.json'),'--manifest',str(manifest)],capture_output=True,text=True)
    assert result.returncode == 2 and 'Traceback' not in result.stderr


def test_retry_can_finish_an_exact_exclusion_and_proof_replay():
    p = tiny(); p['mission']['tasks'][0]['deadline_h'] = 1.5
    s = Scenario.from_dict(p); lib = PathLibrary.build(s)
    first = search_level(s,lib,2,max_operations=0,numerical=False,exhaustive=True)
    assert first.status == 'UNRESOLVED'
    final = search_level(s,lib,2,cursor=first.cursor,exhaustive=True)
    assert final.status == 'EMPTY'
    assert verify_level_evidence(s,lib,final.to_dict())


def test_malformed_saved_level_proof_returns_false():
    p = tiny(); p['mission']['tasks'][0]['deadline_h'] = 1.5
    s = Scenario.from_dict(p); lib = PathLibrary.build(s)
    report = recover(s,lib)['levels'][0]
    assert verify_level_evidence(s,lib,report)
    report['branch_evidence'][0]['certificate']['multipliers'] = None
    assert not verify_level_evidence(s,lib,report)


@pytest.mark.parametrize('case', ['A','B'])
def test_worked_previous_premise_is_verified_in_exact_arithmetic(case):
    s = Scenario.from_dict(worked(case))
    result = recover(s,PathLibrary.build(s))
    assert result['previous_premise']['exact_feasible'] is True


def test_unchanged_retry_budget_cannot_starve_unexamined_branches():
    p = tiny()
    p['incumbent']['routes']['U1']['paths'][0] = [[0,0],[.5,.1],[1,0]]
    s = Scenario.from_dict(p); lib = PathLibrary.build(s)
    first = search_level(s,lib,1,max_branches=1,numerical=False,exhaustive=True)
    assert first.status == 'UNRESOLVED'
    second = search_level(s,lib,1,cursor=first.cursor,max_branches=1,numerical=False,exhaustive=True)
    assert second.status == 'WITNESS'
    assert second.to_dict()['branches'] == 2
