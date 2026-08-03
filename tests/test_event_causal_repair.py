"""Contracts for dependency-aware, belief-consistent ALNS repair."""

from pathlib import Path

import numpy as np

from env.alns_scaffold import RemovalProfile, Scaffold
from env.events import EventType
from env.params import EnvParams
from env.scenario_generator import generate_scenario
from env.uav_env import UAMTVRPIUEnv
from methods.event_causal_repair import (
    AdaptiveCausalMixRepairController,
    EventCausalRepairController,
    OperationalChanges,
    OperationalSnapshot,
    PlanBeliefDependencyGraph,
    PeriodicFullReplanController,
    SoftBoundaryEventCausalRepairController,
    adaptive_removal_profiles,
    corridor_resource,
    soft_boundary_removal_weights,
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
    assert "corridor_leg_closed" in trace.hard_reasons[decision.key.label()]


def test_soft_boundary_keeps_every_visit_removable_with_causal_bias():
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
    weights = soft_boundary_removal_weights(graph, trace, decay=0.5)
    assert weights
    assert all(weight > 0.0 for weight in weights.values())
    assert weights[(decision.key.uav, decision.node)] == 1.0
    noncausal = [
        graph.decisions[key]
        for key in trace.frozen
        if (key.uav, graph.decisions[key].node) in weights
    ]
    if noncausal:
        assert any(
            weights[(item.key.uav, item.node)] < 1.0
            for item in noncausal
        )


def test_adaptive_profiles_preserve_exact_decision_identity():
    env, _, _ = small_env()
    before = OperationalSnapshot.capture(env)
    graph = PlanBeliefDependencyGraph.build(env)
    decision = first_decision(graph)
    env.graph.set_available(
        decision.predecessor_node, decision.node, False)
    after = OperationalSnapshot.capture(env)
    trace = trace_impacts(
        env,
        graph,
        OperationalChanges.between(before, after),
        EventType.AVAIL_CHANGE,
    )
    profiles = adaptive_removal_profiles(graph, trace, decay=0.5)
    assert len(profiles) == len(graph.decisions)
    assert set(profiles) == {
        (key.uav, key.sortie, key.visit)
        for key in graph.decisions
    }
    direct = profiles[(
        decision.key.uav,
        decision.key.sortie,
        decision.key.visit,
    )]
    assert direct.visit_id == decision.key.label()
    assert direct.tier == "causal_decisions"
    assert direct.weight == 1.0


def test_adaptive_causal_mix_logs_executed_operator_removals():
    env, obs, info = small_env(seed=29)
    env.p.hybrid.alns_iterations = 12
    controller = AdaptiveCausalMixRepairController(
        proxy_threshold_fraction=0.0,
        causal_decay=0.5,
        adaptive_min_probability=0.35,
        budget_pacing=False,
    )
    controller.act(env, obs, info["masks"], info["deciders"])
    node = sorted(env.belief.known)[0]
    env.belief.entries[node].mu += np.array([10.0, 0.0, 0.0, 0.0])
    env.last_decision_event_type = EventType.P1_REPORT
    controller.act(env, obs, info["masks"], info["deciders"])
    record = controller.diagnostics[-1]
    assert record["attempted"] == 1
    assert record["repair_policy"] == "adaptive_causal_mix"
    assert record["repair_solver_calls"] == 1
    assert record["adaptive_profile_count"] > 0
    assert (
        record["adaptive_causal_selections"]
        + record["adaptive_global_selections"]
        == 12
    )
    removed = sum(
        record[f"adaptive_removed_{tier}"]
        for tier in (
            "causal_decisions",
            "affected_uav_routes",
            "shared_resource_uavs",
            "global_fleet",
        )
    )
    assert removed > 0
    assert 0.35 <= record["adaptive_causal_final_probability"] <= 0.65
    assert 0.35 <= record["adaptive_global_final_probability"] <= 0.65


def test_new_adaptive_visits_use_global_floor_weight():
    env, _, _ = small_env(seed=31)
    profile = RemovalProfile(
        visit_id="u0/s0/v0",
        tier="global_fleet",
        weight=0.125,
    )
    scaffold = env.planner.solve(
        env._plan_context(),
        np.random.default_rng(9),
        warm=Scaffold(plans={u.idx: [] for u in env.uavs}),
        removal_profiles_by_decision={(0, 0, 0): profile},
        adaptive_causal_mix=True,
        iterations_override=0,
    )
    visits = [
        visit
        for sorties in scaffold.plans.values()
        for sortie in sorties
        for visit in sortie.visits
    ]
    assert visits
    assert all(visit.removal_tier == "global_fleet" for visit in visits)
    assert all(visit.removal_weight == 0.125 for visit in visits)


def test_soft_boundary_repair_uses_one_solver_call():
    env, obs, info = small_env(seed=19)
    captured_weights = []
    propose = env.propose_scaffold_repair

    def capture_proposal(warm, frozen, removal_weights=None):
        captured_weights.append(removal_weights)
        return propose(warm, frozen, removal_weights)

    env.propose_scaffold_repair = capture_proposal
    controller = SoftBoundaryEventCausalRepairController(
        proxy_threshold_fraction=0.0,
        boundary_decay=0.5,
        budget_pacing=False,
    )
    controller.act(env, obs, info["masks"], info["deciders"])
    node = sorted(env.belief.known)[0]
    env.belief.entries[node].mu += np.array([10.0, 0.0, 0.0, 0.0])
    env.last_decision_event_type = EventType.P1_REPORT
    controller.act(env, obs, info["masks"], info["deciders"])
    record = controller.diagnostics[-1]
    assert record["attempted"] == 1
    assert record["repair_policy"] == "soft_boundary"
    assert record["neighborhood_levels_attempted"] == "soft_boundary"
    assert record["repair_solver_calls"] == 1
    assert record["soft_weighted_node_count"] > 0
    assert record["causal_scope_fraction"] <= 1.0
    assert len(captured_weights) == 1
    assert captured_weights[0]
    assert min(captured_weights[0].values()) > 0.0


def test_routine_service_consumption_is_not_an_exogenous_change():
    before = OperationalSnapshot(
        t=1.0,
        known=frozenset({0}),
        demand={0: (5.0, 0.0, 0.0, 0.0)},
        inventory=(10.0, 10.0, 10.0, 10.0),
        corridors={},
        uav_battery=(200.0,),
        uav_payload=((3.0, 0.0, 0.0, 0.0),),
    )
    after = OperationalSnapshot(
        t=1.02,
        known=frozenset({0}),
        demand={0: (4.0, 0.0, 0.0, 0.0)},
        inventory=before.inventory,
        corridors={},
        uav_battery=(197.5,),
        uav_payload=((2.0, 0.0, 0.0, 0.0),),
    )
    changes = OperationalChanges.between(
        before, after, event_type=EventType.SERVICE_COMPLETE,
    )
    assert changes.service_consumption_nodes == {0}
    assert not changes.has_relevant_change


def test_service_shortfall_remains_relevant_information():
    before = OperationalSnapshot(
        t=1.0,
        known=frozenset({0}),
        demand={0: (5.0, 0.0, 0.0, 0.0)},
        inventory=(10.0, 10.0, 10.0, 10.0),
        corridors={},
        uav_battery=(200.0,),
        uav_payload=((3.0, 0.0, 0.0, 0.0),),
    )
    after = OperationalSnapshot(
        t=1.02,
        known=frozenset({0}),
        demand={0: (0.0, 0.0, 0.0, 0.0)},
        inventory=before.inventory,
        corridors={},
        uav_battery=(197.5,),
        uav_payload=((2.0, 0.0, 0.0, 0.0),),
    )
    changes = OperationalChanges.between(
        before, after, event_type=EventType.SERVICE_COMPLETE,
    )
    assert changes.demand_nodes == {0}
    assert changes.has_relevant_change


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


def test_linear_budget_pacing_reserves_early_soft_repairs():
    env, _, _ = small_env()
    env.t = 0.1
    assert not EventCausalRepairController._pacing_allows(env)
    env.t = env.T / 2.0
    assert EventCausalRepairController._pacing_allows(env)


def test_target_count_periodic_baseline_uses_every_interior_slot():
    env, obs, info = small_env(seed=17)
    controller = PeriodicFullReplanController(target_count=2)
    steps = 0
    while not env.done and steps < 2000:
        actions = controller.act(
            env, obs, info["masks"], info["deciders"],
        )
        obs, _, _, info = env.step(actions)
        steps += 1
    assert env.done
    assert env.metrics.n_resolves == 2


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
