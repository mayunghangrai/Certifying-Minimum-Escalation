from copy import deepcopy
import pytest
from env.scenario import Scenario
from final_benchmark.controlled import controlled_case
from level2.search import search_level2
from level2.replay import verify_tree
from level2.skeletons import SkeletonDomain


def test_preferred_prefix_reaches_witness_with_full_branch_accounting():
    s = controlled_case('C2').scenario
    d = SkeletonDomain(s)
    ordinary = search_level2(s, max_seconds=20, refinements=(1,))
    prefix = next(n['prefix'] for n in ordinary['nodes'] if n['kind'] == 'witness')
    r = search_level2(s, max_seconds=20, refinements=(1,), preferred_prefix=prefix)
    assert r['status'] == 'WITNESS'
    assert r['effort']['complete_skeletons'] == 1
    assert verify_tree(s, r)
    assert any(n['kind'] == 'open' for n in r['nodes'])


def test_invalid_preferred_prefix_cannot_change_domain():
    s = controlled_case('C2').scenario
    with pytest.raises(ValueError, match='preferred prefix'):
        search_level2(s, preferred_prefix=['unknown'])


def test_route_proposal_is_admissible_and_bounded():
    from level2.proposals import propose_routes
    s = controlled_case('C2').scenario
    r = propose_routes(s, max_candidates=100)
    assert r['prefix'] is not None
    d = SkeletonDomain(s)
    assert d.complete(r['prefix']) and d.reject(r['prefix']) is None
    stopped = propose_routes(s, max_candidates=0)
    assert stopped['prefix'] is None
    assert stopped['attempts'] == 0
