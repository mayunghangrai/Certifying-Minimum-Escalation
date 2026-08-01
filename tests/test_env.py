"""Environment tests: masks (C1-C6), event ordering, budget, termination."""

import numpy as np
import pytest

from env.entities import Mode
from env.events import Event, EventQueue, EventType
from env.params import EnvParams
from env.scenario_generator import generate_scenario
from env.uav_env import UAMTVRPIUEnv


@pytest.fixture(scope="module")
def env_ready():
    p = EnvParams()
    env = UAMTVRPIUEnv(p)
    obs, info = env.reset(scenario=generate_scenario(42, p))
    return env, obs, info


def test_event_queue_deterministic_ordering():
    q = EventQueue()
    q.push(Event(1.0, EventType.UAV_ARRIVAL, {"uav": 0}))
    q.push(Event(1.0, EventType.P3_MUTATION, {"node": 1}))
    q.push(Event(0.5, EventType.P1_REPORT, {"node": 2}))
    q.push(Event(1.0, EventType.P1_REPORT, {"node": 3}))
    order = [q.pop().etype for _ in range(4)]
    # earlier time first; at equal times state updates before info before fleet
    assert order == [EventType.P1_REPORT, EventType.P3_MUTATION,
                     EventType.P1_REPORT, EventType.UAV_ARRIVAL]


def test_event_queue_cancellation():
    q = EventQueue()
    s1 = q.push(Event(1.0, EventType.UAV_ARRIVAL, {"uav": 0}))
    q.push(Event(2.0, EventType.UAV_ARRIVAL, {"uav": 1}))
    q.cancel(s1)
    ev = q.pop()
    assert ev.payload["uav"] == 1
    assert q.pop() is None


def test_reset_returns_deciders_with_masks(env_ready):
    env, obs, info = env_ready
    assert len(info["deciders"]) >= 1
    for u in info["deciders"]:
        assert obs[u].shape == (env.obs_dims["actor"],)
        m = info["masks"][u]
        assert m.shape == (env.n_actions,)
        assert m[env.A_FOLLOW] and m[env.A_RETURN]


def test_action_space_layout():
    p = EnvParams()
    env = UAMTVRPIUEnv(p)
    N, M = p.map.n_nodes, p.mission.M
    assert env.n_actions == 3 + 2 * N + N * (M - 1)
    kind, node, other = env.decode_action(1, env.encode_swap(4, 1, 2))
    assert (kind, node, other) == ("SWAP", 4, 2)
    kind, node, _ = env.decode_action(0, env.encode_insert(7))
    assert (kind, node) == ("INSERT", 7)
    kind, node, _ = env.decode_action(0, env.encode_skip(7))
    assert (kind, node) == ("SKIP", 7)


def test_mask_c1_unknown_nodes_blocked():
    p = EnvParams()
    env = UAMTVRPIUEnv(p)
    env.reset(scenario=generate_scenario(42, p))
    hidden = [n.idx for n in env.scenario.nodes if n.reveal_time > env.t]
    assert hidden, "seed 42 should have hidden nodes at t=0"
    for u in range(env.M):
        mask = env._action_mask(u)
        for i in hidden:
            assert not mask[env.encode_insert(i)]      # C1
            assert not mask[env.encode_skip(i)]


def test_mask_c2_route_availability():
    p = EnvParams()
    env = UAMTVRPIUEnv(p)
    env.reset(scenario=generate_scenario(42, p))
    # pick a known node and close its depot edge
    known = sorted(env.belief.known)
    target = known[0]
    from env.graph import DEPOT
    env.graph.set_available(DEPOT, target, False)
    # a UAV at the depot must not be allowed to INSERT toward it
    for u in range(env.M):
        if env.uavs[u].mode == Mode.DEPOT and not env._in_turnaround[u]:
            assert not env._action_mask(u)[env.encode_insert(target)]


def test_mask_resolve_budget_gate():
    p = EnvParams()
    env = UAMTVRPIUEnv(p)
    env.reset(scenario=generate_scenario(42, p))
    u = 0
    assert env._action_mask(u)[env.A_RESOLVE]
    env.K_rem = 0
    assert not env._action_mask(u)[env.A_RESOLVE]      # eq:resolve_budget


def test_resolve_decrements_budget():
    p = EnvParams()
    env = UAMTVRPIUEnv(p)
    obs, info = env.reset(scenario=generate_scenario(42, p))
    k0 = env.K_rem
    actions = {u: env.A_RESOLVE for u in info["deciders"]}
    _, _, _, info2 = env.step(actions)
    # multiple simultaneous requests dedupe to a single re-solve
    assert env.K_rem == k0 - 1
    assert env.metrics.n_resolves == 1


def test_c5_energy_mask_blocks_far_nodes():
    p = EnvParams()
    env = UAMTVRPIUEnv(p)
    env.reset(scenario=generate_scenario(42, p))
    u = 0
    uav = env.uavs[u]
    uav.mode = Mode.FLYING
    env._in_turnaround[u] = False
    uav.ell = np.array([2.0, 1.0, 0.0, 0.0])
    uav.b = 5.0                     # nearly empty battery
    known = sorted(env.belief.known)
    mask = env._action_mask(u)
    for i in known:
        assert not mask[env.encode_insert(i)]          # C5 blocks everything


def test_reward_is_negative_deprivation_dominated():
    p = EnvParams()
    env = UAMTVRPIUEnv(p)
    obs, info = env.reset(scenario=generate_scenario(42, p))
    actions = {u: env.A_FOLLOW for u in info["deciders"]}
    _, r, done, info2 = env.step(actions)
    assert np.isfinite(r)
    assert r <= 0.0
    assert info2["dt"] >= 0.0


def test_full_episode_random_policy_terminates():
    p = EnvParams()
    env = UAMTVRPIUEnv(p)
    obs, info = env.reset(scenario=generate_scenario(7, p))
    rng = np.random.default_rng(0)
    steps = 0
    while not env.done and steps < 5000:
        actions = {}
        for u in info["deciders"]:
            valid = np.flatnonzero(info["masks"][u])
            actions[u] = int(rng.choice(valid))
        obs, r, done, info = env.step(actions)
        assert np.isfinite(r)
        steps += 1
    assert env.done
    assert env.done_reason in ("horizon", "demand_satisfied",
                               "depot_exhausted", "fleet_infeasible")
    # battery physics: no UAV ever below zero
    for uav in env.uavs:
        assert uav.b >= -1e-6
    assert env.metrics.J_dep_true > 0.0


def test_seeded_episode_reproducibility():
    p = EnvParams()

    def run():
        env = UAMTVRPIUEnv(p)
        obs, info = env.reset(scenario=generate_scenario(11, p))
        total = 0.0
        steps = 0
        while not env.done and steps < 300:
            actions = {u: env.A_FOLLOW for u in info["deciders"]}
            obs, r, done, info = env.step(actions)
            total += r
            steps += 1
        return total, env.metrics.J_dep_true, env.t

    a = run()
    b = run()
    assert a == b
