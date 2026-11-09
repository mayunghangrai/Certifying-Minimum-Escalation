"""Shared entries are immutable and evidence views isolate each proof."""
from copy import deepcopy
import importlib

import pytest

from continuous.oracle import verify_query
from env.scenario import Scenario
from final_benchmark.controlled import controlled_case


def test_warming_irrelevant_queries_does_not_change_a_query():
    mod = importlib.import_module('level3.cache')
    s = controlled_case('C3').scenario
    cold = mod.SharedContinuousCache(s, refinements=(1,))
    warm = mod.SharedContinuousCache(s, refinements=(1,))
    warm.view().query('U2', [-.2, 0], [0, 0])
    a = cold.view().query('U2', [0, 0], [1, 0])
    b = warm.view().query('U2', [0, 0], [1, 0])
    assert a == b
    assert verify_query(s, a)


def test_returned_data_and_later_cache_use_cannot_mutate_an_attached_proof():
    mod = importlib.import_module('level3.cache')
    s = controlled_case('C3').scenario
    cache = mod.SharedContinuousCache(s, refinements=(1,))
    first = cache.view()
    q = first.query('U2', [0, 0], [1, 0])
    saved = deepcopy(first.cache)
    q['path'][0][0] = 999
    second = cache.view()
    second.query('U3', [0, 0], [-1, 0])
    assert first.cache == saved
    assert len(first.cache) == 1
    assert first.query('U2', [0, 0], [1, 0])['path'][0] == [0, 0]


def test_cache_rejects_a_different_original_scenario():
    mod = importlib.import_module('level3.cache')
    s = controlled_case('C3').scenario
    cache = mod.SharedContinuousCache(s, refinements=(1,))
    p = s.to_dict()
    p['benchmark_id'] = 'different-original-scenario'
    with pytest.raises(ValueError, match='scenario'):
        cache.check_scenario(Scenario(p))


def test_a_forged_seed_is_rejected_before_it_can_prune():
    mod = importlib.import_module('level3.cache')
    from continuous.oracle import ContinuousOracle
    s = controlled_case('C3').scenario
    q = ContinuousOracle(s, refinements=(1,)).query('U1', [0, 0], [1, 0])
    q['lower'] = '1000'
    with pytest.raises(ValueError, match='seed'):
        mod.SharedContinuousCache(s, refinements=(1,), initial_bounds=[q])
