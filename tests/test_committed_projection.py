"""Regression tests for committed-operation ALNS projection."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Tuple

import numpy as np
import pytest


# Allow imports from src/ when pytest is launched from the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from env.energy import service_energy  # noqa: E402
from env.entities import Mode  # noqa: E402
from env.params import EnvParams  # noqa: E402
from env.uav_env import EPS, SERVICE_DWELL, UAMTVRPIUEnv  # noqa: E402


def _small_test_params() -> EnvParams:
    """Create a small deterministic environment for fast unit tests."""

    params = EnvParams()

    params.mission.T = 2.0
    params.mission.M = 3
    params.mission.n_replenish = 0

    params.map.n_nodes = 8
    params.map.n_hidden = 0

    params.events.avail_closure_rate = 0.0

    params.hybrid.K_max = 3
    params.hybrid.alns_iterations = 1
    params.hybrid.route_depth = 3

    return params


def _find_active_delivery() -> Tuple[UAMTVRPIUEnv, int]:
    """Advance until one UAV has a committed flight to a demand node."""

    # Several deterministic seeds are tried so the test is not dependent on
    # one particular randomly generated initial route.
    for seed in (100, 101, 102, 103):
        env = UAMTVRPIUEnv(_small_test_params())
        obs, info = env.reset(seed=seed)

        for _ in range(250):
            candidates = [
                u
                for u, uav in enumerate(env.uavs)
                if (
                    env._arrival_seq[u] is not None
                    and uav.mode == Mode.FLYING
                    and uav.dest_node is not None
                    and int(uav.dest_node) >= 0
                )
            ]

            if candidates:
                return env, candidates[0]

            actions = {
                u: env.A_FOLLOW
                for u in info["deciders"]
            }

            obs, _, done, info = env.step(actions)

            if done:
                break

    raise AssertionError(
        "Could not create an active committed demand-node flight "
        "using deterministic test seeds."
    )


def _force_partial_committed_delivery(
    env: UAMTVRPIUEnv,
    u: int,
) -> Tuple[int, np.ndarray, np.ndarray, np.ndarray]:
    """Give the active UAV a deterministic partial-delivery state.

    The test uses a planned cap of one unit while the UAV carries two units.
    This guarantees that payload remains after the committed delivery, so the
    projected mutable suffix should begin at the destination node.
    """

    uav = env.uavs[u]
    target = int(uav.dest_node)

    believed_demand = np.asarray(
        env.belief.d_tilde(target),
        dtype=float,
    ).copy()

    assert believed_demand.sum() > EPS, (
        "Active target has no positive belief demand."
    )

    # Prefer one of the first three commodities so two units remain within
    # the benchmark payload-mass scale.
    first_three = believed_demand[:3]

    if first_three.sum() > EPS:
        commodity = int(np.argmax(first_three))
    else:
        commodity = int(np.argmax(believed_demand))

    payload = np.zeros_like(believed_demand)
    payload[commodity] = 2.0

    committed_cap = np.zeros_like(believed_demand)
    committed_cap[commodity] = 1.0

    uav.ell = payload.copy()
    env._committed_x_plan[u] = committed_cap.copy()

    return target, believed_demand, payload, committed_cap


def test_committed_delivery_projection_and_demand_reduction() -> None:
    """The mutable suffix starts after the immutable committed delivery."""

    env, u = _find_active_delivery()

    target, believed_demand, payload, committed_cap = (
        _force_partial_committed_delivery(env, u)
    )

    uav = env.uavs[u]

    battery_before_projection = float(uav.b)
    remaining_leg_energy = env._remaining_committed_leg_energy(u)

    projected_demand = {
        target: believed_demand.copy()
    }

    start = env._project_committed_plan_start(
        u=u,
        projected_demand=projected_demand,
    )

    expected_delivery = np.minimum(
        payload,
        believed_demand,
    )
    expected_delivery = np.minimum(
        expected_delivery,
        committed_cap,
    )
    expected_delivery = np.maximum(
        expected_delivery,
        0.0,
    )

    expected_remaining_demand = np.maximum(
        believed_demand - expected_delivery,
        0.0,
    )

    expected_payload_after = np.maximum(
        payload - expected_delivery,
        0.0,
    )

    expected_battery_after = max(
        battery_before_projection
        - remaining_leg_energy
        - service_energy(env.p.physics),
        0.0,
    )

    # The mutable suffix starts at the committed destination.
    assert np.allclose(
        start.pos,
        env.nodes[target].pos,
    )

    # The suffix cannot begin until flight and service are complete.
    assert start.ready_time == pytest.approx(
        float(uav.arrive_time) + SERVICE_DWELL
    )

    assert start.anchor == target
    assert start.at_depot is False
    assert start.payload_committed is True
    assert start.uses_onboard_payload is True

    # The committed service reduces both projected demand and payload.
    assert np.allclose(
        projected_demand[target],
        expected_remaining_demand,
    )

    assert np.allclose(
        start.ell,
        expected_payload_after,
    )

    # Remaining flight energy and service energy must be deducted.
    assert start.b == pytest.approx(
        expected_battery_after
    )

    # Basic conservation checks.
    assert np.all(
        expected_delivery <= payload + EPS
    )
    assert np.all(
        expected_delivery <= believed_demand + EPS
    )
    assert np.all(
        projected_demand[target] <= believed_demand + EPS
    )


def test_plan_context_uses_projected_committed_start() -> None:
    """_plan_context must use the projected destination state."""

    env, u = _find_active_delivery()

    target, _, _, _ = _force_partial_committed_delivery(
        env,
        u,
    )

    uav = env.uavs[u]

    ctx = env._plan_context()

    start = next(
        item
        for item in ctx.uav_starts
        if item.uav == u
    )

    assert np.allclose(
        start.pos,
        env.nodes[target].pos,
    )

    assert start.ready_time == pytest.approx(
        float(uav.arrive_time) + SERVICE_DWELL
    )

    assert start.anchor == target
    assert start.payload_committed is True
    assert start.uses_onboard_payload is True

    # This distinguishes the projected destination from the old incorrect
    # behavior that started ALNS at the UAV's current mid-flight position.
    current_midflight_position = uav.position_at(env.t)

    assert not np.allclose(
        start.pos,
        current_midflight_position,
    )


def test_replanning_does_not_cancel_active_arrival() -> None:
    """A replan may change only the suffix, not the active flight leg."""

    env, u = _find_active_delivery()

    uav = env.uavs[u]

    arrival_sequence_before = env._arrival_seq[u]
    destination_before = int(uav.dest_node)
    arrival_time_before = float(uav.arrive_time)
    origin_before = np.asarray(uav.origin).copy()

    assert arrival_sequence_before is not None

    # resolved=True previously allowed global replanning to divert the UAV.
    # The corrected contract must preserve the active leg regardless.
    env._apply_movement(
        u=u,
        kind="FOLLOW",
        node=None,
        resolved=True,
    )

    assert env._arrival_seq[u] == arrival_sequence_before
    assert int(env.uavs[u].dest_node) == destination_before

    assert env.uavs[u].arrive_time == pytest.approx(
        arrival_time_before
    )

    assert np.allclose(
        env.uavs[u].origin,
        origin_before,
    )

    assert env.uavs[u].mode == Mode.FLYING