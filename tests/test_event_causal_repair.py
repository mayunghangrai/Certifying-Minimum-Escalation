"""Contracts for dependency-aware, belief-consistent ALNS repair."""

from pathlib import Path

import numpy as np

from env.events import EventType
from env.params import EnvParams
from env.scenario_generator import generate_scenario
from env.uav_env import UAMTVRPIUEnv
from methods.event_causal_repair import (
    EventCausalRepairController,
    OperationalChanges,
    OperationalSnapshot,
    PlanBeliefDependencyGraph,
    corridor_resource,
    trace_impacts,
)


def small_env(seed=42):
    params = EnvParams()
    params.map.n_nodes = 8
    params.map.n_hidden = 2
    params.mission.T = 2.0
    params.mission.n_replenish = 1
    params.hybrid.K_max = 4
    params.hybrid.alns_iterations = 2
    env = UAMTVRPIUEnv(params)
    obs, info = env.reset(scenario=generate_scenario(seed, params))
    return env, obs, info


def first_decision(graph):
    assert graph.decisions
    return graph.decisions[sorted(graph.decisions)[0]]


def test_operational_snapshot_excludes_silent_truth_mutation():
    env, _, _ = small_env()
    before = OperationalSnapshot.capture(env)
    hidden_truth_node = env.nodes[0]
    hidden_truth_node.add_cohort(0, 7.0, env.t)
    after = OperationalSnapshot.capture(env)
    assert before == after


def test_dependency_graph_links_route_to_operational_resources():
    env, _, _ = small_env()
    graph = PlanBeliefDependencyGraph.build(env)
    decision = first_decision(graph)
    assert f"demand:{decision.node}" in decision.resources
    assert f"uav:{decision.key.uav}:energy" in decision.resources
    assert corridor_resource(
        decision.predecessor_node, decision.node) in decision.resources
    # Inventory dependencies are handled via reservation/slack logic, not
    # via a global commodity broadcast to every visit.
    assert not any(
        resource.startswith("inventory:")
        for resource in decision.resources)


def test_corridor_closure_traces_direct_decision_and_route_consequences():
    env, _, _ = small_env()
    before = OperationalSnapshot.capture(env)
    graph = PlanBeliefDependencyGraph.build(env)
    decision = first_decision(graph)
    env.graph.set_available(
        decision.predecessor_node, decision.node, False)
    after = OperationalSnapshot.capture(env)
    changes = OperationalChanges.between(before, after)
    trace = trace_impacts(
        env, graph, changes, EventType.AVAIL_CHANGE)
    assert decision.key in trace.direct
    assert decision.key in trace.hard
    assert decision.key in trace.mutable
    assert trace.mutable.isdisjoint(trace.frozen)


def test_bound_screen_can_certify_continuation_without_solving():
    env, obs, info = small_env()
    controller = EventCausalRepairController(solve_cost=1e12)
    controller.act(env, obs, info["masks"], info["deciders"])
    node = sorted(env.belief.known)[0]
    env.belief.entries[node].mu += np.array([0.1, 0.0, 0.0, 0.0])
    env.last_decision_event_type = EventType.P1_REPORT
    budget_before = env.K_rem
    controller.act(env, obs, info["masks"], info["deciders"])
    assert controller.diagnostics[-1]["outcome"] == "certified_continue"
    assert env.K_rem == budget_before
    assert env.metrics.n_resolves == 0


def test_calibrated_proxy_threshold_blocks_small_soft_event():
    env, obs, info = small_env()
    controller = EventCausalRepairController(
        proxy_threshold_fraction=1.0)
    controller.act(env, obs, info["masks"], info["deciders"])
    node = sorted(env.belief.known)[0]
    env.belief.entries[node].mu += np.array([0.1, 0.0, 0.0, 0.0])
    env.last_decision_event_type = EventType.P1_REPORT
    budget_before = env.K_rem
    controller.act(env, obs, info["masks"], info["deciders"])
    record = controller.diagnostics[-1]
    assert record["outcome"] == "continue_event_impact_below_threshold"
    assert (
        record["proxy_activation_threshold"]
        >= record["event_impact_value_proxy"]
    )
    assert env.K_rem == budget_before
    assert env.metrics.n_resolves == 0


def test_hard_infeasibility_automatically_attempts_selective_repair():
    env, obs, info = small_env(seed=7)
    controller = EventCausalRepairController()
    controller.act(env, obs, info["masks"], info["deciders"])
    graph = PlanBeliefDependencyGraph.build(env)
    decision = first_decision(graph)
    env.graph.set_available(
        decision.predecessor_node, decision.node, False)
    env.last_decision_event_type = EventType.AVAIL_CHANGE
    budget_before = env.K_rem
    controller.act(env, obs, info["masks"], info["deciders"])
    record = controller.diagnostics[-1]
    assert record["attempted"] == 1
    assert record["installed"] == 1
    assert record["repair_solver_calls"] >= 1
    assert record["repair_wall_time_s"] > 0.0
    assert controller.repair_solver_calls == record["repair_solver_calls"]
    assert controller.repair_wall_time_s == record["repair_wall_time_s"]
    assert env.K_rem == budget_before - 1
    assert env.metrics.n_resolves == 1
    repaired = PlanBeliefDependencyGraph.build(env)
    for plan_decision in repaired.decisions.values():
        assert env.graph.A(
            plan_decision.predecessor_node, plan_decision.node)


def test_hard_family_makes_static_scaffold_obsolete_after_revelations():
    config = (
        Path(__file__).parents[1]
        / "configs" / "env" / "event_causal_hard.yaml"
    )
    params = EnvParams.from_yaml(str(config))
    scenario = generate_scenario(12, params)
    hidden = {
        node.idx for node in scenario.nodes if node.reveal_time > 0.0
    }
    assert len(hidden) == params.map.n_hidden
    assert all(
        sum(scenario.nodes[node].d0) > 0.0 for node in hidden)
    env = UAMTVRPIUEnv(params)
    env.reset(scenario=scenario)
    initially_planned = {
        visit.node
        for sorties in env.scaffold.plans.values()
        for sortie in sorties
        for visit in sortie.visits
    }
    assert hidden.isdisjoint(initially_planned)
