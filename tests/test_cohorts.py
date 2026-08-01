"""Cohort dynamics: FOFS service, aggregation, [.]^+ transition (sec: demand_model)."""

import numpy as np
import pytest

from env.entities import Cohort, DepotInventory, NodeTruth


@pytest.fixture
def node():
    n = NodeTruth(idx=0, pos=np.zeros(2), nu=1.0)
    n.add_cohort(0, 3.0, tau_arr=0.0)
    n.add_cohort(0, 2.0, tau_arr=5.0)
    return n


def test_aggregation(node):
    # eq:cohort_aggregation: d = sum_c q
    assert node.d(0) == 5.0
    np.testing.assert_allclose(node.demand_vector(), [5.0, 0, 0, 0])


def test_cohort_age(node):
    # eq:cohort_age: a = t - tau_arr
    assert node.cohorts[0][0].age(7.0) == 7.0
    assert node.cohorts[0][1].age(7.0) == 2.0
    assert node.oldest_age(0, 7.0) == 7.0


def test_fofs_service_oldest_first(node):
    served = node.serve_fofs(0, 4.0)
    assert served == 4.0
    # oldest cohort (q=3, tau=0) fully consumed, second partially
    assert len(node.cohorts[0]) == 1
    assert node.cohorts[0][0].tau_arr == 5.0
    assert node.cohorts[0][0].q == pytest.approx(1.0)


def test_service_clips_at_demand(node):
    # eq:delivery_amount / eq:true_demand_transition [.]^+ : cannot overserve
    served = node.serve_fofs(0, 99.0)
    assert served == 5.0
    assert node.d(0) == 0.0


def test_mutation_creates_new_cohort(node):
    # eq:p3_mutation: new cohort at mutation time
    node.add_cohort(0, 4.0, tau_arr=6.0)
    assert len(node.cohorts[0]) == 3
    assert node.d(0) == 9.0


def test_zero_mutation_ignored(node):
    node.add_cohort(1, 0.0, tau_arr=6.0)
    assert node.cohorts[1] == []


def test_depot_inventory_c6():
    inv = DepotInventory(S0=np.array([5.0, 2.0, 0.0, 1.0]))
    # eq:inventory_constraint: request clipped to stock
    got = inv.load(np.array([3.0, 5.0, 2.0, 0.0]))
    np.testing.assert_allclose(got, [3.0, 2.0, 0.0, 0.0])
    np.testing.assert_allclose(inv.S0, [2.0, 0.0, 0.0, 1.0])
    # eq:inventory_transition with replenishment
    inv.replenish(np.array([1.0, 1.0, 1.0, 1.0]))
    np.testing.assert_allclose(inv.S0, [3.0, 1.0, 1.0, 2.0])
