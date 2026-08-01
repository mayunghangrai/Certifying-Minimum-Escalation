"""Regression tests for non-invasive shadow ALNS auditing."""

from __future__ import annotations

import pickle
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from env.params import EnvParams  # noqa: E402
from env.uav_env import UAMTVRPIUEnv  # noqa: E402
from env.events import EventType  # noqa: E402
from methods.event_causal_repair import (  # noqa: E402
    EventCausalRepairController,
    OperationalChanges,
    PlanBeliefDependencyGraph,
    trace_impacts,
)

def _small_params() -> EnvParams:
    params = EnvParams()

    params.mission.T = 2.0
    params.mission.M = 3

    params.map.n_nodes = 8
    params.map.n_hidden = 0

    params.hybrid.K_max = 6
    params.hybrid.alns_iterations = 1
    params.hybrid.route_depth = 3

    return params


def _serialized_state(value) -> bytes:
    return pickle.dumps(
        value,
        protocol=pickle.HIGHEST_PROTOCOL,
    )


def test_shadow_solve_does_not_change_operational_state() -> None:
    env = UAMTVRPIUEnv(_small_params())
    env.reset(seed=300)

    scaffold_before = env.scaffold
    scaffold_state_before = _serialized_state(
        env.scaffold
    )

    operational_rng_before = _serialized_state(
        env._rng_alns.bit_generator.state
    )

    k_rem_before = int(env.K_rem)
    resolves_before = int(env.metrics.n_resolves)

    operational_calls_before = int(
        env.repair_solver_calls
    )
    operational_wall_before = float(
        env.repair_solver_wall_time_s
    )

    audit_calls_before = int(
        env.shadow_audit_solver_calls
    )
    audit_wall_before = float(
        env.shadow_audit_wall_time_s
    )

    interval_resolve_before = bool(
        env._interval_resolve
    )

    assert env.alns_solving is False
    assert env.alns_request_t is None

    ctx = env._plan_context()

    candidate = env.propose_shadow_scaffold_repair(
        ctx=ctx,
        warm=env.scaffold,
        frozen_nodes_by_uav=None,
    )

    # A candidate was produced, but it was not installed.
    assert candidate is not None
    assert env.scaffold is scaffold_before

    # The incumbent scaffold itself was not modified.
    assert _serialized_state(
        env.scaffold
    ) == scaffold_state_before

    # Repair budget and transaction accounting are unchanged.
    assert env.K_rem == k_rem_before
    assert env.metrics.n_resolves == resolves_before
    assert env._interval_resolve == interval_resolve_before

    # Operational solver accounting is unchanged.
    assert (
        env.repair_solver_calls
        == operational_calls_before
    )
    assert (
        env.repair_solver_wall_time_s
        == operational_wall_before
    )

    # The operational ALNS RNG was not advanced.
    assert _serialized_state(
        env._rng_alns.bit_generator.state
    ) == operational_rng_before

    # Only audit-specific counters changed.
    assert (
        env.shadow_audit_solver_calls
        == audit_calls_before + 1
    )
    assert (
        env.shadow_audit_wall_time_s
        >= audit_wall_before
    )

    # Shadow optimization is not an operational solve state.
    assert env.alns_solving is False
    assert env.alns_request_t is None

def test_controller_shadow_audit_produces_two_candidates() -> None:
    env = UAMTVRPIUEnv(_small_params())
    env.reset(seed=301)

    controller = EventCausalRepairController(
        shadow_audit_screened_events=True,
    )

    known_nodes = sorted(
        int(node)
        for node in env.belief.known
    )

    assert known_nodes, (
        "Test scenario contains no known demand node"
    )

    node = known_nodes[0]

    dependency_graph = (
        PlanBeliefDependencyGraph.build(env)
    )

    changes = OperationalChanges(
        demand_nodes={node},
        demand_commodities={(node, 0)},
    )

    trace = trace_impacts(
        env=env,
        dependency_graph=dependency_graph,
        changes=changes,
        event_type=EventType.P1_REPORT,
    )

    assert not trace.hard

    ctx = env._plan_context()

    current_value = (
        env.planner.evaluate_belief_value(
            env.scaffold,
            ctx,
        )
    )

    operational_calls_before = int(
        env.repair_solver_calls
    )

    operational_wall_before = float(
        env.repair_solver_wall_time_s
    )

    audit_calls_before = int(
        env.shadow_audit_solver_calls
    )

    k_rem_before = int(env.K_rem)

    operational_record = {
        "time_h": float(env.t),
        "event_kind": "demand_correction",
        "event_type": "P1_REPORT",
        "changed_resources": (
            f"demand:{node}|cohort:{node}:0"
        ),
        "hard_impact_count": 0,
        "optimistic_value_upper_bound": (
            100.0
        ),
        "potential_gain_bound": 50.0,
        "event_impact_value_proxy": 1.0,
        "proxy_activation_threshold": 5.0,
        "proxy_threshold_fraction": 0.3,
    }

    audit = controller._run_screen_shadow_audit(
        env=env,
        dependency_graph=dependency_graph,
        trace=trace,
        ctx=ctx,
        current_value=current_value,
        solve_cost=5.0,
        operational_record=operational_record,
    )

    assert audit[
        "shadow_audit_solver_calls"
    ] == 2

    assert (
        env.shadow_audit_solver_calls
        == audit_calls_before + 2
    )

    # No operational solve or budget consumption occurred.
    assert (
        env.repair_solver_calls
        == operational_calls_before
    )

    assert (
        env.repair_solver_wall_time_s
        == operational_wall_before
    )

    assert env.K_rem == k_rem_before
    assert env.metrics.n_resolves == 0

    # Both counterfactual alternatives were evaluated.
    assert "shadow_level1_value" in audit
    assert "shadow_full_value" in audit

    assert (
        audit["shadow_level1_feasible"]
        in (0, 1)
    )

    assert (
        audit["shadow_full_feasible"]
        in (0, 1)
    )

    assert (
        audit["screen_false_negative"]
        in (0, 1)
    )

    assert (
        audit["expansion_was_needed"]
        in (0, 1)
    )

    assert (
        audit[
            "expansion_net_benefit_needed"
        ]
        in (0, 1)
    )