"""Safe continuous-domain pruning and explicit finite-budget frontiers."""
from copy import deepcopy
import importlib

from env.scenario import Scenario
from final_benchmark.controlled import controlled_case


def test_full_slot_search_finds_sequence_repair_and_replays():
    search = importlib.import_module('level2.search')
    replay = importlib.import_module('level2.replay')
    s = controlled_case('C2').scenario
    r = search.search_level2(s, max_seconds=20, max_nodes=5000, refinements=(1,))
    assert r['status'] == 'WITNESS'
    assert r['witness']['plan']['assignment'] == s.to_dict()['incumbent']['assignment']
    assert replay.verify_tree(s, r)


def test_complete_exclusion_covers_all_repetitions_depots_and_padding():
    search = importlib.import_module('level2.search')
    replay = importlib.import_module('level2.replay')
    s = controlled_case('C3').scenario
    r = search.search_level2(s, max_seconds=20, max_nodes=5000, refinements=(1,))
    assert r['status'] == 'EMPTY'
    assert all(n['kind'] != 'open' for n in r['nodes'])
    assert replay.verify_tree(s, r)


def test_zero_budget_is_an_explicit_unresolved_frontier():
    search = importlib.import_module('level2.search')
    replay = importlib.import_module('level2.replay')
    s = controlled_case('C2').scenario
    r = search.search_level2(s, max_seconds=0, max_nodes=0, refinements=(1,))
    assert r['status'] == 'UNRESOLVED'
    assert r['nodes'] == [{'prefix': [], 'kind': 'open', 'reason': 'search budget'}]
    assert replay.verify_tree(s, r)


def test_unsupported_physics_never_excludes_level2():
    search = importlib.import_module('level2.search')
    replay = importlib.import_module('level2.replay')
    p = controlled_case('C3').scenario.to_dict()
    p['operations']['depot_bays'] = 1
    s = Scenario(p)
    r = search.search_level2(s)
    assert r['status'] == 'UNRESOLVED'
    assert r['unsupported'] == 'coupled depot preparation'
    assert replay.verify_tree(s, r)


def test_deadline_pruning_requires_task_not_yet_visited():
    domain = importlib.import_module('level2.skeletons').SkeletonDomain
    bounds = importlib.import_module('level2.bounds')
    p = controlled_case('C2').scenario.to_dict()
    s = Scenario(p)
    d = domain(s)
    # Once B occurs, a late second B visit may legally deliver zero.
    assert bounds.prefix_exclusion(s, d, ['B', 'B'], {}) is None


def test_initial_depot_recharge_is_included_in_optimistic_energy():
    domain = importlib.import_module('level2.skeletons').SkeletonDomain
    bounds = importlib.import_module('level2.bounds')
    p = controlled_case('C2').scenario.to_dict()
    p['state']['fleet']['U1']['battery_wh'] = 0
    s = Scenario(p)
    d = domain(s)
    assert bounds.prefix_exclusion(s, d, ['A'], {}) is None
