"""Unit tests for deterministic expanding event-causal neighborhoods."""

from __future__ import annotations

from methods.event_causal_repair import (
    DecisionKey,
    ImpactTrace,
    PlanBeliefDependencyGraph,
    PlanDecision,
    expanding_repair_neighborhoods,
)


def _add_decision(
    graph: PlanBeliefDependencyGraph,
    key: DecisionKey,
    node: int,
    resources: set[str],
) -> None:
    decision = PlanDecision(
        key=key,
        node=node,
        predecessor_node=-1,
        resources=frozenset(resources),
    )
    graph.decisions[key] = decision

    for resource in decision.resources:
        graph.resource_to_decisions.setdefault(
            resource,
            set(),
        ).add(key)


def _synthetic_graph() -> tuple[
    PlanBeliefDependencyGraph,
    DecisionKey,
    DecisionKey,
    DecisionKey,
    DecisionKey,
]:
    graph = PlanBeliefDependencyGraph()

    u0_first = DecisionKey(0, 0, 0)
    u0_second = DecisionKey(0, 0, 1)
    u1_first = DecisionKey(1, 0, 0)
    u2_first = DecisionKey(2, 0, 0)

    _add_decision(
        graph,
        u0_first,
        node=0,
        resources={
            "inventory:0",
            "corridor:-1:0",
        },
    )
    _add_decision(
        graph,
        u0_second,
        node=1,
        resources={
            "inventory:2",
            "corridor:0:1",
        },
    )
    _add_decision(
        graph,
        u1_first,
        node=2,
        resources={
            "inventory:0",
            "corridor:-1:2",
        },
    )
    _add_decision(
        graph,
        u2_first,
        node=3,
        resources={
            "inventory:1",
            "corridor:-1:3",
        },
    )

    return (
        graph,
        u0_first,
        u0_second,
        u1_first,
        u2_first,
    )


def test_expanding_neighborhood_hierarchy() -> None:
    (
        graph,
        u0_first,
        u0_second,
        u1_first,
        u2_first,
    ) = _synthetic_graph()

    trace = ImpactTrace(
        event_kind="demand_correction",
        locality_class="information",
        changed_resources={"demand:0"},
        hard=set(),
        direct={u0_first},
        opportunity_seeds=set(),
        mutable={u0_first},
        frozen={u0_second, u1_first, u2_first},
    )

    levels = expanding_repair_neighborhoods(
        graph,
        trace,
        selective_repair=True,
    )

    assert [level.hierarchy_level for level in levels] == [
        1,
        2,
        3,
        4,
    ]
    assert [level.name for level in levels] == [
        "causal_decisions",
        "affected_uav_routes",
        "shared_resource_uavs",
        "full_fleet",
    ]

    assert set(levels[0].mutable) == {
        u0_first,
    }
    assert set(levels[1].mutable) == {
        u0_first,
        u0_second,
    }
    assert set(levels[2].mutable) == {
        u0_first,
        u0_second,
        u1_first,
    }
    assert set(levels[3].mutable) == {
        u0_first,
        u0_second,
        u1_first,
        u2_first,
    }


def test_full_replan_baseline_has_one_level() -> None:
    graph, u0_first, u0_second, u1_first, u2_first = (
        _synthetic_graph()
    )

    trace = ImpactTrace(
        event_kind="demand_correction",
        locality_class="information",
        changed_resources={"demand:0"},
        hard=set(),
        direct={u0_first},
        opportunity_seeds=set(),
        mutable={u0_first},
        frozen={u0_second, u1_first, u2_first},
    )

    levels = expanding_repair_neighborhoods(
        graph,
        trace,
        selective_repair=False,
    )

    assert len(levels) == 1
    assert levels[0].hierarchy_level == 4
    assert levels[0].name == "full_fleet"
    assert set(levels[0].mutable) == set(
        graph.decisions
    )


def test_duplicate_neighborhoods_are_removed() -> None:
    graph = PlanBeliefDependencyGraph()
    only = DecisionKey(0, 0, 0)

    _add_decision(
        graph,
        only,
        node=0,
        resources={
            "inventory:0",
            "corridor:-1:0",
        },
    )

    trace = ImpactTrace(
        event_kind="demand_correction",
        locality_class="information",
        changed_resources={"demand:0"},
        hard=set(),
        direct={only},
        opportunity_seeds=set(),
        mutable={only},
        frozen=set(),
    )

    levels = expanding_repair_neighborhoods(
        graph,
        trace,
        selective_repair=True,
    )

    assert len(levels) == 1
    assert levels[0].hierarchy_level == 1
    assert levels[0].name == "causal_decisions"
    assert set(levels[0].mutable) == {only}
