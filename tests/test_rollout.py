"""End-to-end rollouts: multiple seeds, invariants, ALNS scaffold sanity."""

import numpy as np
import pytest

from env.params import EnvParams
from env.scenario_generator import generate_scenario
from env.uav_env import UAMTVRPIUEnv


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_random_rollout_invariants(seed):
    p = EnvParams()
    env = UAMTVRPIUEnv(p)
    obs, info = env.reset(scenario=generate_scenario(seed, p))
    rng = np.random.default_rng(seed)
    steps = 0
    while not env.done and steps < 5000:
        actions = {u: int(rng.choice(np.flatnonzero(info["masks"][u])))
                   for u in info["deciders"]}
        obs, r, done, info = env.step(actions)
        steps += 1
        assert np.isfinite(r)
        # battery must respect the safety reserve while airborne (C5 gives
        # at least beta_safe margin at leg commitment; never below zero)
        for uav in env.uavs:
            assert uav.b >= -1e-6
        # payload capacity C4
        w_k = np.asarray(p.commodities.w_k)
        for uav in env.uavs:
            assert uav.payload_mass(w_k) <= p.physics.W_max + 1e-6
        # inventory never negative (C6)
        assert np.all(env.inventory.S0 >= -1e-9)
    assert env.done
    m = env.metrics.summary()
    assert m["J_dep_true"] >= 0
    assert m["J_energy"] > 0
    assert 0 <= m["fill_rate"] <= 1.0 + 1e-9


def test_follow_policy_delivers_something():
    p = EnvParams()
    env = UAMTVRPIUEnv(p)
    obs, info = env.reset(scenario=generate_scenario(42, p))
    steps = 0
    while not env.done and steps < 5000:
        actions = {u: env.A_FOLLOW for u in info["deciders"]}
        obs, r, done, info = env.step(actions)
        steps += 1
    assert env.metrics.delivered_units.sum() > 0, \
        "pure scaffold-following must deliver aid"
    assert env.metrics.fill_rate() > 0.1


def test_scaffold_respects_stock_and_capacity():
    p = EnvParams()
    env = UAMTVRPIUEnv(p)
    env.reset(scenario=generate_scenario(42, p))
    w_k = np.asarray(p.commodities.w_k)
    total_planned = np.zeros(4)
    for u, sorties in env.scaffold.plans.items():
        for s in sorties:
            if s.y.sum() > 0:
                assert float(np.dot(w_k, s.y)) <= p.physics.W_max + 1e-6  # C4
                np.testing.assert_allclose(
                    s.y, np.sum([v.x_plan for v in s.visits], axis=0))
            total_planned += s.y
    assert np.all(total_planned <= np.array(env.scenario.S0_init) + 1e-6)  # C6


def test_p3_increases_truth_but_not_belief():
    p = EnvParams()
    env = UAMTVRPIUEnv(p)
    env.reset(scenario=generate_scenario(42, p))
    muts = [m for m in env.scenario.p3_mutations
            if env.scenario.nodes[m.node].reveal_time == 0.0]
    assert muts, "seed 42 should mutate an initially-known node"
    m0 = muts[0]
    node = m0.node
    d_before = env.nodes[node].demand_vector().copy()
    mu_before = env.belief.entries[node].mu.copy()
    from env.events import Event, EventType
    env._apply_event(Event(m0.t, EventType.P3_MUTATION,
                           {"node": node, "delta": np.array(m0.delta_d)}))
    np.testing.assert_allclose(env.nodes[node].demand_vector(),
                               d_before + np.array(m0.delta_d))
    np.testing.assert_allclose(env.belief.entries[node].mu, mu_before)
