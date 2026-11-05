"""Global sequence proofs explicitly authorize the original Level-4 mask."""
import importlib

import pytest

from env.local_scope import ScopePatch, affected_uavs, scope_family
from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update
from final_benchmark.controlled import controlled_case, make_plan
from level2.skeletons import SkeletonDomain


def global_scene():
    scenario = controlled_case('C4').scenario
    affected = affected_uavs(scenario, diagnose_wind_update(scenario))['uavs']
    patch, = scope_family(scenario, 4, affected)
    assignment = {'C': 'U3', 'E': 'U2', 'D': 'U2'}
    return scenario, assignment, patch


def test_global_assignment_and_all_route_slots_use_the_original_scope():
    scenario, assignment, patch = global_scene()
    original = scenario.to_dict()
    domain = SkeletonDomain(scenario, assignment=assignment, patch=patch, scope_level=4)
    assert domain.scenario is scenario
    assert domain.patch.to_dict() == patch.to_dict()
    assert domain.children((None, None, None, 'E', 'D', 'DEPOT')) == (None, 'DEPOT', 'C')
    prefix = (None, None, None, 'E', 'D', 'DEPOT', 'C', 'DEPOT', None)
    plan = domain.skeleton(prefix)
    scenario.validate_candidate(plan)
    assert plan['assignment'] == assignment
    assert plan['routes']['U3']['stops'] == ['C', 'DEPOT', None]
    assert scenario.to_dict() == original


def test_global_domain_keeps_repeated_tasks_depot_revisits_and_inactive_slots():
    payload = controlled_case('C4').scenario.to_dict()
    payload['mission']['vehicles'][2]['slot_bound'] = 4
    payload['incumbent'], payload['reserve_paths'] = make_plan(payload, {'U1': ['C'], 'U2': ['E'], 'U3': ['D']})
    scenario = Scenario(payload)
    affected = affected_uavs(scenario, diagnose_wind_update(scenario))['uavs']
    patch, = scope_family(scenario, 4, affected)
    assignment = {'C': 'U3', 'E': 'U2', 'D': 'U2'}
    domain = SkeletonDomain(scenario, assignment=assignment, patch=patch, scope_level=4)
    prefix = (None, None, None, 'E', 'D', 'DEPOT', 'C', 'DEPOT', 'C', 'DEPOT')
    assert domain.reject(prefix) is None
    plan = domain.skeleton(prefix)
    scenario.validate_candidate(plan)
    assert plan['routes']['U3']['stops'] == ['C', 'DEPOT', 'C', 'DEPOT']


def test_global_mask_preserves_original_assignment_and_slot_commitments():
    payload = controlled_case('C4').scenario.to_dict()
    payload['commitments'].update(A=['E'], S=['U1:3'], P=['U1:3'], L=['U1:0:x'])
    scenario = Scenario(payload)
    affected = affected_uavs(scenario, diagnose_wind_update(scenario))['uavs']
    patch, = scope_family(scenario, 4, affected)
    assignment = {'C': 'U3', 'E': 'U2', 'D': 'U2'}
    domain = SkeletonDomain(scenario, assignment=assignment, patch=patch, scope_level=4)
    plan = domain.skeleton((None, None, None, 'E', 'D', 'DEPOT', 'C', 'DEPOT', None))
    scenario.validate_candidate(plan)
    assert 'E' not in patch.releases['A']
    assert 'U1:3' not in patch.releases['S'] | patch.releases['P']
    assert 'U1:0:x' not in patch.releases['L']
    assert plan['routes']['U1']['paths'][2] == payload['incumbent']['routes']['U1']['paths'][2]
    illegal = dict(assignment, E='U1')
    with pytest.raises(ValueError, match='unreleased assignment'):
        SkeletonDomain(scenario, assignment=illegal, patch=patch, scope_level=4)


@pytest.mark.parametrize('requested_level, patch_level', [(3, 4), (4, 3), (4, 2)])
def test_sequence_rejects_patch_from_a_different_explicit_scope_level(requested_level, patch_level):
    search = importlib.import_module('level2.search')
    scenario = controlled_case('C3').scenario
    affected = affected_uavs(scenario, diagnose_wind_update(scenario))['uavs']
    patch = scope_family(scenario, patch_level, affected)[0]
    assignment = dict(scenario.data['incumbent']['assignment'])
    with pytest.raises(ValueError, match='permitted scope'):
        search.search_sequence(scenario, assignment, patch, scope_level=requested_level,
                               max_seconds=0, max_nodes=0)


@pytest.mark.parametrize('level', [None, True, '4', 4.0, 2, 5])
def test_sequence_rejects_invalid_scope_level(level):
    search = importlib.import_module('level2.search')
    scenario, assignment, patch = global_scene()
    with pytest.raises(ValueError, match='scope level'):
        search.search_sequence(scenario, assignment, patch, scope_level=level,
                               max_seconds=0, max_nodes=0)


def test_global_sequence_zero_budget_has_explicit_level_and_original_binding():
    search = importlib.import_module('level2.search')
    scenario, assignment, patch = global_scene()
    result = search.search_sequence(scenario, assignment, patch, scope_level=4,
                                   max_seconds=0, max_nodes=0)
    assert result['status'] == 'UNRESOLVED'
    assert result['scope_level'] == 4
    assert result['scenario_hash'] == scenario.content_hash()
    assert result['affected'] == ['U1']
    assert result['assignment'] == assignment and result['patch'] == patch.to_dict()


def test_global_sequence_finds_exact_witness_using_formerly_fixed_vehicle():
    search = importlib.import_module('level2.search')
    scenario, assignment, patch = global_scene()
    result = search.search_sequence(scenario, assignment, patch, scope_level=4,
                                   max_seconds=20, max_nodes=5000, refinements=(1,))
    assert result['status'] == 'WITNESS'
    assert result['scope_level'] == 4
    assert result['witness']['scenario_hash'] == scenario.content_hash()
    assert result['witness']['plan']['assignment'] == assignment
    assert result['patch'] == patch.to_dict()


def test_global_sequence_rejects_forged_release_of_an_original_commitment():
    payload = controlled_case('C4').scenario.to_dict()
    payload['commitments']['S'] = ['U3:3']
    scenario = Scenario(payload)
    affected = affected_uavs(scenario, diagnose_wind_update(scenario))['uavs']
    patch, = scope_family(scenario, 4, affected)
    releases = dict(patch.releases)
    releases['S'] = releases['S'] | {'U3:3'}
    with pytest.raises(ValueError, match='permitted scope'):
        SkeletonDomain(scenario, assignment=dict(scenario.data['incumbent']['assignment']),
                       patch=ScopePatch(patch.participants, releases), scope_level=4)


def test_default_level3_sequence_keeps_saved_schema_and_semantics():
    search = importlib.import_module('level2.search')
    scenario = controlled_case('C3').scenario
    affected = affected_uavs(scenario, diagnose_wind_update(scenario))['uavs']
    patch = scope_family(scenario, 3, affected)[0]
    assignment = {'C': 'U2', 'E': 'U1', 'D': 'U3'}
    default = search.search_sequence(scenario, assignment, patch, max_seconds=0, max_nodes=0)
    explicit = search.search_sequence(scenario, assignment, patch, scope_level=3, max_seconds=0, max_nodes=0)
    assert 'scope_level' not in default and 'scope_level' not in explicit
    for report in (default, explicit):
        assert report['version'] == 'sequence_exhaustive_v1'
    assert {k: v for k, v in default.items() if k != 'effort'} == {
        k: v for k, v in explicit.items() if k != 'effort'}
