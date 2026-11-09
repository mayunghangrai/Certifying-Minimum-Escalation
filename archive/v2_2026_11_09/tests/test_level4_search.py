"""Global assignment coverage reuses the certified sequence machinery."""
from copy import deepcopy
import importlib

import pytest

from env.local_scope import affected_uavs, scope_family
from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update
from final_benchmark.controlled import controlled_case


def _modules():
    return importlib.import_module('level4.search'), importlib.import_module('level4.replay')


def test_one_global_tree_releases_all_uncommitted_coordinates():
    search, replay = _modules()
    s = controlled_case('C4', helper_budget=0).scenario
    r = search.search_level4(s, max_seconds=0, max_nodes=0)
    affected = affected_uavs(s, diagnose_wind_update(s))['uavs']
    assert 'patches' not in r
    assert r['scope_level'] == 4
    assert r['tree']['patch'] == scope_family(s, 4, affected)[0].to_dict()
    assert r['tree']['patch']['participants'] == sorted(s.data['state']['fleet'])
    assert r['status'] == 'UNRESOLVED'
    assert replay.verify_tree(s, r)


def test_global_search_finds_reassignment_with_original_context():
    search, replay = _modules()
    s = controlled_case('C4').scenario
    r = search.search_level4(s, max_seconds=30, refinements=(1,))
    assert r['status'] == 'WITNESS'
    assert r['scenario_hash'] == s.content_hash()
    proofs = [n['proof'] for n in r['tree']['nodes'] if n['kind'] == 'sequence']
    assert proofs and all(p['scope_level'] == 4 for p in proofs)
    assert all(p['patch'] == r['tree']['patch'] for p in proofs)
    assert replay.verify_tree(s, r)


def test_explored_global_branches_account_for_every_raw_owner():
    search, replay = _modules()
    s = controlled_case('C3').scenario
    r = search.search_level4(s, max_seconds=30, max_nodes=2, refinements=(1,))
    assert r['status'] == 'UNRESOLVED'
    root = r['tree']['nodes'][0]
    assert [r['tree']['nodes'][i]['prefix'][-1] for i in root['children']] == [None, *sorted(s.data['state']['fleet'])]
    assert replay.verify_tree(s, r)
    changed = deepcopy(r)
    changed['tree']['nodes'][0]['children'].pop()
    assert not replay.verify_tree(s, changed)


def test_global_release_preserves_assignment_and_route_commitments():
    search, replay = _modules()
    p = controlled_case('C0').scenario.to_dict()
    p['commitments']['A'] = ['C']
    p['commitments']['S'] = ['U1:1']
    s = Scenario(p)
    r = search.search_level4(s, max_seconds=30, refinements=(1,))
    assert 'C' not in r['tree']['patch']['releases']['A']
    assert 'U1:1' not in r['tree']['patch']['releases']['S']
    root = r['tree']['nodes'][0]
    assert len(root['children']) == 1
    assert r['tree']['nodes'][root['children'][0]]['prefix'] == ['U1']
    assert replay.verify_tree(s, r)


def test_an_unfinished_inner_tree_keeps_global_search_unresolved():
    search, replay = _modules()
    s = controlled_case('C2').scenario
    r = search.search_level4(s, max_seconds=30, max_nodes=5, refinements=(1,))
    proofs = [n['proof'] for n in r['tree']['nodes'] if n['kind'] == 'sequence']
    assert proofs and any(p['status'] == 'UNRESOLVED' for p in proofs)
    assert r['status'] == 'UNRESOLVED'
    assert replay.verify_tree(s, r)


def test_cache_warming_preserves_global_mathematical_evidence():
    search, replay = _modules()
    cache_mod = importlib.import_module('level3.cache')
    s = controlled_case('Cinf').scenario
    cache = cache_mod.SharedContinuousCache(s, refinements=(1,))
    cache.view().query('U3', [0, 0], [-1, 0])
    a = search.search_level4(s, max_seconds=30, refinements=(1,))
    b = search.search_level4(s, max_seconds=30, refinements=(1,), cache=cache)
    def semantic(v):
        if isinstance(v, dict):
            return {k:semantic(x) for k,x in v.items() if k not in ('effort', 'budget')}
        if isinstance(v, list):
            return [semantic(x) for x in v]
        return v
    assert semantic(a) == semantic(b)
    assert replay.verify_tree(s, b)


def test_unsupported_physics_cannot_claim_global_exclusion():
    search, replay = _modules()
    p = controlled_case('C3').scenario.to_dict()
    p['operations']['depot_bays'] = 1
    s = Scenario(p)
    r = search.search_level4(s)
    assert r['status'] == 'UNRESOLVED'
    assert replay.verify_tree(s, r)


@pytest.mark.parametrize('options', [{'max_nodes':-1}, {'max_seconds':float('inf')}])
def test_global_search_rejects_invalid_budgets(options):
    search, _ = _modules()
    with pytest.raises(ValueError, match='budget'):
        search.search_level4(controlled_case('C3').scenario, **options)


def test_completion_bound_closes_the_whole_global_domain_before_branching():
    search, replay = _modules()
    s = controlled_case('Cinf').scenario
    r = search.search_level4(s, max_seconds=30, max_nodes=2, refinements=(1,))
    assert r['status'] == 'EMPTY'
    assert r['effort']['assignment_nodes'] == 1 and r['effort']['sequences'] == 0
    root = r['tree']['nodes'][0]
    assert root['kind'] == 'assignment_prune' and root['proof']['kind'] == 'assignment_completion_deadline_v1'
    assert [x['uav'] for x in root['proof']['candidates']] == sorted(s.data['state']['fleet'])
    assert replay.replay_tree(s, r)['covered']


def test_completion_bound_accounts_for_required_depot_replenishment():
    search, replay = _modules()
    from final_benchmark.controlled import make_plan
    p = controlled_case('C4').scenario.to_dict()
    for u in p['mission']['vehicles']:
        u['payload_capacity_kg'] = 1
        u['slot_bound'] = 4
    p['mission']['tasks'][0].update(demand=1.5, mandatory=1.5, deadline_h=1.25)
    p['state']['depot_stock'] = 3.5
    p['incumbent'], p['reserve_paths'] = make_plan(p, {'U1':['E'], 'U2':['D'], 'U3':['C']})
    depot, point = p['mission']['depot_xy'], p['mission']['tasks'][0]['position_xy']
    p['incumbent']['routes']['U3'] = dict(stops=['C','DEPOT','C','DEPOT'],
        paths=[[depot,point],[point,depot],[depot,point],[point,depot]],
        deliveries=[0,1,0,.5,0], loads=[1,0,.5,0,0])
    p['reserve_paths']['U3'] = {'initial':[depot], '1':[point,depot], '3':[point,depot]}
    s = Scenario(p)
    r = search.search_level4(s, max_seconds=30, max_nodes=2, refinements=(1,))
    assert r['status'] == 'EMPTY'
    proof = r['tree']['nodes'][0]['proof']
    assert proof['kind'] == 'assignment_completion_deadline_v1'
    assert all(c['sorties'] == 2 for c in proof['candidates'])
    assert replay.verify_tree(s, r)


def test_completion_bound_does_not_require_optional_quantity_by_deadline():
    search, replay = _modules()
    p = controlled_case('Cinf').scenario.to_dict()
    p['mission']['tasks'][0]['mandatory'] = 0
    s = Scenario(p)
    r = search.search_level4(s, max_seconds=30, refinements=(1,))
    assert r['status'] == 'WITNESS'
    assert replay.verify_tree(s, r)


def test_completion_bound_keeps_committed_unassigned_owner_replayable():
    search, replay = _modules()
    from final_benchmark.controlled import make_plan
    p = controlled_case('Cinf').scenario.to_dict()
    p['mission']['tasks'][0]['mandatory'] = 0
    p['incumbent'], p['reserve_paths'] = make_plan(p, {})
    p['commitments']['A'] = ['C']
    s = Scenario(p)
    r = search.search_level4(s, max_seconds=30, refinements=(1,))
    assert r['status'] == 'WITNESS'
    assert replay.verify_tree(s, r)


def test_completion_bound_prunes_selected_owner_needing_late_second_sortie():
    search, replay = _modules()
    from final_benchmark.controlled import make_plan
    p = controlled_case('C0').scenario.to_dict()
    p['mission']['vehicles'][0].update(payload_capacity_kg=.5, slot_bound=4)
    p['mission']['tasks'][0]['deadline_h'] = 3.03
    p['incumbent'], p['reserve_paths'] = make_plan(p, {'U1':['C'], 'U2':['E'], 'U3':['D']})
    depot, point = p['mission']['depot_xy'], p['mission']['tasks'][0]['position_xy']
    p['incumbent']['routes']['U1'] = dict(stops=['C','DEPOT','C','DEPOT'],
        paths=[[depot,point],[point,depot],[depot,point],[point,depot]],
        deliveries=[0,.5,0,.5,0], loads=[.5,0,.5,0,0])
    p['reserve_paths']['U1'] = {'initial':[depot], '1':[point,depot], '3':[point,depot]}
    s = Scenario(p)
    r = search.search_level4(s, max_seconds=30, max_nodes=3, refinements=(1,))
    selected = next(n for n in r['tree']['nodes'] if n['prefix'] == ['U1'])
    assert selected['kind'] == 'assignment_prune'
    proof = selected['proof']
    assert proof['kind'] == 'assignment_completion_deadline_v1'
    assert len(proof['candidates']) == 1 and proof['candidates'][0]['uav'] == 'U1'
    assert proof['candidates'][0]['sorties'] == 2
    assert r['status'] == 'UNRESOLVED' and replay.verify_tree(s, r)
