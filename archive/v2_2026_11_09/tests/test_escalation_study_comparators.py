import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))

import pytest

from continuous_benchmark.cases import controlled_cases
from escalation_study.comparators import finite_library, global_first, time_sliced, verify_comparator


@pytest.fixture(scope='module')
def control():
    return next(c for c in controlled_cases() if c.name == 'C1').scenario


def test_time_sliced_returns_the_first_feasible_level(control):
    result = time_sliced(control, slice_seconds=2)
    assert result['found'] and result['level'] == 1 and not result['minimality_certified']
    assert verify_comparator(control, result)


def test_global_first_plan_is_feasible_and_never_below_the_minimum(control):
    result = global_first(control, max_seconds=5, max_proposals=30, search_seconds=5, max_nodes=20000)
    assert result['found'] and result['level'] >= 1
    assert verify_comparator(control, result)
    forged = deepcopy(result)
    forged['level'] = result['level']-1
    assert not verify_comparator(control, forged)


def test_finite_library_claims_are_rechecked_in_its_library(control):
    result = finite_library(control, max_seconds=5, max_proposals=30)
    assert verify_comparator(control, result)
    if result['found']:
        forged = deepcopy(result)
        forged['library_hash'] = '0'*64
        assert not verify_comparator(control, forged)
