"""Fixed-assignment sequence search binds the original Level-3 scope."""
from copy import deepcopy
import importlib

import pytest

from continuous.oracle import ContinuousOracle
from env.local_scope import ScopePatch, affected_uavs, scope_family
from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update
from final_benchmark.controlled import controlled_case
from level2.skeletons import SkeletonDomain


def helper_patch(scenario):
    affected = affected_uavs(scenario, diagnose_wind_update(scenario))['uavs']
    return next(p for p in scope_family(scenario, 3, affected)
                if p.participants == ('U1', 'U2'))


def reassigned_scene():
    scenario = controlled_case('C3').scenario
    assignment = dict(scenario.data['incumbent']['assignment'])
    assignment.update(C='U2', E='U1')
    return scenario, assignment, helper_patch(scenario)


def test_explicit_assignment_changes_route_alphabet_and_keeps_original_scenario():
    scenario, assignment, patch = reassigned_scene()
    original = scenario.to_dict()
    domain = SkeletonDomain(scenario, assignment=assignment, patch=patch)
    assert domain.scenario is scenario
    assert domain.children(()) == (None, 'DEPOT', 'E')
    prefix = ('E', 'DEPOT', None, 'C', 'DEPOT', None, 'D', 'DEPOT', None)
    plan = domain.skeleton(prefix)
    scenario.validate_candidate(plan)
    assert plan['assignment'] == assignment
    assert plan['routes']['U3'] == original['incumbent']['routes']['U3']
    assert scenario.to_dict() == original


def test_original_helper_release_mask_survives_unchanged_assignment():
    scenario = controlled_case('C2').scenario
    assignment = dict(scenario.data['incumbent']['assignment'])
    patch = helper_patch(scenario)
    domain = SkeletonDomain(scenario, assignment=assignment, patch=patch)
    prefix = ('A', 'B', 'DEPOT', 'DEPOT', 'DEPOT', 'DEPOT', None, None, None)
    plan = domain.skeleton(prefix)
    scenario.validate_candidate(plan)
    assert domain.patch.to_dict() == patch.to_dict()
    assert plan['routes']['U2']['stops'] == ['DEPOT', 'DEPOT', 'DEPOT']
    assert SkeletonDomain(scenario).children(prefix[:3]) == (None,)


def test_original_committed_slots_and_transfers_are_preserved():
    payload = controlled_case('C3').scenario.to_dict()
    payload['commitments'].update(S=['U1:3'], P=['U1:3'], L=['U1:0:x'])
    scenario = Scenario(payload)
    assignment = dict(scenario.data['incumbent']['assignment'])
    assignment.update(C='U2', E='U1')
    patch = helper_patch(scenario)
    domain = SkeletonDomain(scenario, assignment=assignment, patch=patch)
    plan = domain.skeleton(('E', 'DEPOT', None, 'C', 'DEPOT', None, 'D', 'DEPOT', None))
    scenario.validate_candidate(plan)
    assert 'U1:3' not in domain.patch.releases['S']
    assert plan['routes']['U1']['paths'][2] == payload['incumbent']['routes']['U1']['paths'][2]
    assert plan['routes']['U1']['deliveries'][0] == 0


@pytest.mark.parametrize('change', ['missing', 'extra', 'unknown_owner', 'unhashable_owner'])
def test_explicit_assignment_rejects_invalid_coordinates(change):
    scenario, assignment, patch = reassigned_scene()
    if change == 'missing':
        assignment.pop('C')
    elif change == 'extra':
        assignment['UNKNOWN'] = 'U1'
    elif change == 'unknown_owner':
        assignment['C'] = 'UNKNOWN'
    else:
        assignment['C'] = ['U1']
    with pytest.raises(ValueError, match='assignment'):
        SkeletonDomain(scenario, assignment=assignment, patch=patch)


def test_explicit_assignment_cannot_change_original_committed_owner():
    payload = controlled_case('C3').scenario.to_dict()
    payload['commitments']['A'] = ['C']
    scenario = Scenario(payload)
    assignment = dict(scenario.data['incumbent']['assignment'])
    assignment['C'] = 'U2'
    with pytest.raises(ValueError, match='unreleased assignment'):
        SkeletonDomain(scenario, assignment=assignment, patch=helper_patch(scenario))


def test_explicit_scope_rejects_forged_or_narrowed_release_masks():
    scenario, assignment, patch = reassigned_scene()
    releases = dict(patch.releases)
    releases['S'] = releases['S'] - {'U1:1'}
    narrowed = ScopePatch(patch.participants, releases)
    with pytest.raises(ValueError, match='permitted scope'):
        SkeletonDomain(scenario, assignment=assignment, patch=narrowed)
    releases = dict(patch.releases)
    releases['S'] = releases['S'] | {'U3:1'}
    forged = ScopePatch(patch.participants, releases)
    with pytest.raises(ValueError, match='permitted scope'):
        SkeletonDomain(scenario, assignment=assignment, patch=forged)


def test_explicit_scope_cannot_replace_the_original_affected_set():
    scenario, assignment, _ = reassigned_scene()
    forged = scope_family(scenario, 2, {'U1', 'U2'})[0]
    assignment = dict(scenario.data['incumbent']['assignment'])
    with pytest.raises(ValueError, match='original affected'):
        SkeletonDomain(scenario, assignment=assignment, patch=forged, u0={'U1', 'U2'})


@pytest.mark.parametrize('missing', ['assignment', 'patch', 'both'])
def test_explicit_search_requires_both_assignment_and_original_mask(missing):
    search = importlib.import_module('level2.search')
    scenario, assignment, patch = reassigned_scene()
    if missing in ('assignment', 'both'):
        assignment = None
    if missing in ('patch', 'both'):
        patch = None
    with pytest.raises(ValueError, match='assignment.*patch'):
        search.search_sequence(scenario, assignment, patch, max_seconds=0, max_nodes=0)


def test_fixed_route_visits_cannot_survive_a_changed_owner():
    payload = controlled_case('C3').scenario.to_dict()
    payload['commitments']['S'] = ['U1:1']
    scenario = Scenario(payload)
    assignment = dict(scenario.data['incumbent']['assignment'])
    assignment.update(C='U2', E='U1')
    domain = SkeletonDomain(scenario, assignment=assignment, patch=helper_patch(scenario))
    assert domain.reject(('C',)) == 'assignment_visit_owner'


def test_explicit_zero_budget_stays_unresolved_with_original_binding():
    search = importlib.import_module('level2.search')
    scenario, assignment, patch = reassigned_scene()
    result = search.search_sequence(scenario, assignment, patch, max_seconds=0, max_nodes=0)
    assert result['status'] == 'UNRESOLVED'
    assert result['version'] == 'sequence_exhaustive_v1'
    assert result['scenario_hash'] == scenario.content_hash()
    assert result['assignment'] == assignment
    assert result['patch'] == patch.to_dict()
    assert result['affected'] == ['U1']
    assert result['nodes'] == [{'prefix': [], 'kind': 'open', 'reason': 'search budget'}]


class LocalOracleView:
    """A real oracle adapter with evidence limited to this sequence call."""
    def __init__(self, source):
        self.source = source
        self.cache = {}
        self.effort = {'queries': 0}

    def query(self, uid, start, goal, warm_paths=(), *, bound=True):
        result = self.source.query(uid, start, goal, warm_paths, bound=bound)
        self.cache[uid, tuple(start), tuple(goal)] = deepcopy(result)
        self.effort['queries'] += 1
        return result


def test_explicit_search_uses_supplied_local_oracle_evidence_and_finds_helper_witness():
    search = importlib.import_module('level2.search')
    scenario, assignment, patch = reassigned_scene()
    source = ContinuousOracle(scenario, (1,))
    unrelated = source.query('U3', [0, 0], [.5, 0])
    view = LocalOracleView(source)
    result = search.search_sequence(scenario, assignment, patch, oracle=view,
                                   max_seconds=20, max_nodes=5000, refinements=(1,))
    assert result['status'] == 'WITNESS'
    assert result['witness']['plan']['assignment'] == assignment
    assert result['witness']['scenario_hash'] == scenario.content_hash()
    assert result['patch'] == patch.to_dict()
    assert result['effort']['oracle']['queries'] == view.effort['queries'] > 0
    assert unrelated not in result['leg_bounds']
    saved = deepcopy(result['leg_bounds'])
    for entry in view.cache.values():
        entry['lower'] = '999'
    assert result['leg_bounds'] == saved


def test_legacy_level2_report_retains_its_version_and_schema():
    search = importlib.import_module('level2.search')
    result = search.search_level2(controlled_case('C2').scenario,
                                 max_seconds=20, max_nodes=5000, refinements=(1,))
    assert result['status'] == 'WITNESS'
    assert result['version'] == 'level2_exhaustive_v1'
    assert 'assignment' not in result and 'patch' not in result
