"""Certified reassignment wraps complete fixed-slot sequence coverage."""
from copy import deepcopy
import importlib

from env.local_scope import affected_uavs, scope_family
from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update
from final_benchmark.controlled import controlled_case


def test_level3_finds_reassignment_witness_against_original_scenario():
    search = importlib.import_module('level3.search')
    replay = importlib.import_module('level3.replay')
    s = controlled_case('C3').scenario
    r = search.search_level3(s, max_seconds=30, refinements=(1,))
    assert r['status'] == 'WITNESS'
    assert r['scenario_hash'] == s.content_hash()
    assert r['witness']['plan']['assignment'] != s.to_dict()['incumbent']['assignment']
    assert replay.verify_tree(s, r)


def test_all_helper_patches_and_raw_assignment_children_are_recorded():
    search = importlib.import_module('level3.search')
    replay = importlib.import_module('level3.replay')
    s = controlled_case('C3').scenario
    r = search.search_level3(s, max_seconds=30, refinements=(1,))
    u0 = affected_uavs(s, diagnose_wind_update(s))['uavs']
    assert [p['patch'] for p in r['patches']] == [p.to_dict() for p in scope_family(s, 3, u0)]
    assert len(r['patches']) == 2
    assert replay.verify_tree(s, r)
    changed = deepcopy(r)
    changed['patches'].pop()
    assert not replay.verify_tree(s, changed)


def test_zero_shared_budget_leaves_every_patch_explicitly_open():
    search = importlib.import_module('level3.search')
    replay = importlib.import_module('level3.replay')
    s = controlled_case('C3').scenario
    r = search.search_level3(s, max_seconds=0, max_nodes=0)
    assert r['status'] == 'UNRESOLVED'
    assert all(p['nodes'] == [{'prefix': [], 'kind': 'open', 'reason': 'shared search budget'}]
               for p in r['patches'])
    assert replay.verify_tree(s, r)


def test_complete_level3_exclusion_requires_all_patches():
    search = importlib.import_module('level3.search')
    replay = importlib.import_module('level3.replay')
    s = controlled_case('Cinf').scenario
    r = search.search_level3(s, max_seconds=30, refinements=(1,))
    assert r['status'] == 'EMPTY'
    assert all(p['status'] == 'EMPTY' for p in r['patches'])
    assert replay.verify_tree(s, r)


def test_cache_warming_cannot_change_the_semantic_outer_proof():
    search = importlib.import_module('level3.search')
    cache_mod = importlib.import_module('level3.cache')
    s = controlled_case('C3').scenario
    cache = cache_mod.SharedContinuousCache(s, refinements=(1,))
    cache.view().query('U3', [0, 0], [-1, 0])
    a = search.search_level3(s, max_seconds=60, max_nodes=10000, refinements=(1,))
    b = search.search_level3(s, max_seconds=60, max_nodes=10000, refinements=(1,), cache=cache)
    def semantic(value):
        if isinstance(value, dict):
            return {k: semantic(v) for k, v in value.items() if k not in ('effort', 'budget')}
        if isinstance(value, list):
            return [semantic(v) for v in value]
        return value
    assert semantic(a) == semantic(b)


def test_unsupported_physics_remains_unresolved_in_both_layers():
    search = importlib.import_module('level3.search')
    replay = importlib.import_module('level3.replay')
    p = controlled_case('C3').scenario.to_dict()
    p['operations']['depot_bays'] = 1
    s = Scenario(p)
    r = search.search_level3(s)
    assert r['status'] == 'UNRESOLVED'
    assert replay.verify_tree(s, r)


def test_an_attached_unfinished_sequence_keeps_outer_assignment_open():
    search = importlib.import_module('level3.search')
    replay = importlib.import_module('level3.replay')
    s = controlled_case('C2').scenario
    r = search.search_level3(s, max_seconds=30, max_nodes=5, refinements=(1,))
    attached = [n['proof'] for p in r['patches'] for n in p['nodes'] if n['kind'] == 'sequence']
    assert attached and any(p['status'] == 'UNRESOLVED' for p in attached)
    assert r['status'] == 'UNRESOLVED'
    assert replay.verify_tree(s, r)
