import pytest

from env.scenario import Scenario
from recovery.representation import PathLibrary
from recovery.search import recover, verify_witness
from recovery_cases import worked


def test_direct_level_four_uses_only_that_scope_without_claiming_minimality():
    s = Scenario.from_dict(worked('B'))
    lib = PathLibrary.build(s)
    r = recover(s, lib, strategy='level4', total_branches=128, numerical=False)
    assert [row['level'] for row in r['levels']] == [4]
    assert r['status'] == 'WITNESS_WITH_GAP_R'
    assert r['lower_bound'] == 0 and r['upper_bound'] == 3
    assert verify_witness(s, lib, r['witness']['plan'], r['witness']['reserve_paths'],
                          4, exact_transfers=r['witness']['exact_transfers'])['exact']


@pytest.mark.parametrize('strategy', ['ascending', 'level4'])
@pytest.mark.parametrize('cap', [0, 1, 2, 4])
def test_branch_budget_is_shared_across_scopes_and_never_reset(strategy, cap):
    s = Scenario.from_dict(worked('B'))
    r = recover(s, PathLibrary.build(s), strategy=strategy, total_branches=cap,
                total_nodes=64, max_branches=100, numerical=False)
    actual = [row for row in r['levels'] if 'equivalent_to' not in row]
    assert sum(row['branches'] for row in actual) == r['branches_used'] <= cap
    assert sum(row['nodes'] for row in actual) == r['nodes_used'] <= 64
    assert r['total_branch_budget'] == cap
    if cap == 0:
        assert r['status'] == 'UNRESOLVED_R'
        assert r['certified_empty_levels'] == []


def test_mask_reuse_does_not_charge_branches_twice():
    s = Scenario.from_dict(worked('B'))
    r = recover(s, PathLibrary.build(s), exhaustive=True, total_branches=100, numerical=False)
    assert r['levels'][4]['equivalent_to'] == 3
    assert r['branches_used'] == sum(row['branches'] for row in r['levels'][:4])


@pytest.mark.parametrize('kwargs', [dict(strategy='greedy'), dict(total_branches=-1),
                                   dict(total_branches=True), dict(total_branches=1.5)])
def test_invalid_comparison_controls_rejected(kwargs):
    s = Scenario.from_dict(worked('B'))
    with pytest.raises(ValueError):
        recover(s, PathLibrary.build(s), **kwargs)
