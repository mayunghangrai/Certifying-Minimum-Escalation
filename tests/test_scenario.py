"""Scenario generation: seeding, feasibility, serialization round-trip."""

import os
import tempfile

import numpy as np
import pytest

from env.energy import max_service_radius
from env.params import EnvParams
from env.scenario import Scenario
from env.scenario_generator import generate_scenario


@pytest.fixture(scope="module")
def scn():
    return generate_scenario(42, EnvParams())


def test_same_seed_identical_hash(scn):
    other = generate_scenario(42, EnvParams())
    assert scn.content_hash() == other.content_hash()


def test_different_seed_different_hash(scn):
    other = generate_scenario(43, EnvParams())
    assert scn.content_hash() != other.content_hash()


def test_all_nodes_within_feasible_radius(scn):
    p = EnvParams()
    r_max = max_service_radius(p.physics, conservative=True)
    depot = np.array(scn.depot)
    for n in scn.nodes:
        assert np.linalg.norm(np.array([n.x, n.y]) - depot) <= r_max + 1e-9
    assert scn.r_feasible == pytest.approx(r_max)


def test_hidden_nodes_have_reveal_after_onset(scn):
    p = EnvParams()
    hidden = [n for n in scn.nodes if n.reveal_time > 0]
    assert len(hidden) == p.map.n_hidden
    for n in hidden:
        # P2: demand-onset time recorded separately, onset <= reveal
        assert 0.0 <= n.onset_time <= n.reveal_time <= p.mission.T


def test_p3_mutations_nonnegative_after_onset(scn):
    for m in scn.p3_mutations:
        assert all(v >= 0 for v in m.delta_d)          # eq:p3_mutation
        assert sum(m.delta_d) > 0
        assert m.t >= scn.nodes[m.node].onset_time


def test_p1_reports_within_horizon_after_reveal(scn):
    p = EnvParams()
    for r in scn.p1_reports:
        assert scn.nodes[r.node].reveal_time <= r.t < p.mission.T


def test_json_round_trip(scn):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "s.json")
        scn.to_json(path)
        loaded = Scenario.from_json(path)
        assert loaded.content_hash() == scn.content_hash()
        assert len(loaded.nodes) == len(scn.nodes)
        assert loaded.seed == 42


def test_passive_truth_grows_with_p3(scn):
    early = scn.passive_truth_at(0.0)
    late = scn.passive_truth_at(EnvParams().mission.T)
    total_early = sum(n.demand_vector().sum() for n in early)
    total_late = sum(n.demand_vector().sum() for n in late)
    assert total_late > total_early


def test_passive_belief_known_set_grows(scn):
    p = EnvParams()
    known0 = scn.passive_belief_at(0.0).known
    knownT = scn.passive_belief_at(p.mission.T).known
    assert known0 < knownT
    assert len(knownT) == p.map.n_nodes


def test_stock_positive(scn):
    assert all(v > 0 for v in scn.S0_init)
