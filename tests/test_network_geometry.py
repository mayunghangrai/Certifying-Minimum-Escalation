"""Contracts for directed network geometry records."""

from __future__ import annotations

import importlib
import math

import pytest


def _network_module():
    module = importlib.import_module("env.network")
    for name in ("Network", "NetworkEdge", "NetworkNode"):
        assert hasattr(module, name), f"env.network must define {name}"
    return module


def test_edge_derives_length_and_bearing_from_directed_geometry():
    network = _network_module()
    edge = network.NetworkEdge(
        id="DEPOT->A",
        origin="DEPOT",
        destination="A",
        geometry=[(0.0, 0.0), (3.0, 4.0)],
    )

    assert edge.length_km == pytest.approx(5.0)
    assert edge.bearing_rad == pytest.approx(math.atan2(4.0, 3.0))
    assert edge.direction_xy == pytest.approx((0.6, 0.8))


def test_network_preserves_separate_reverse_edges_and_round_trips():
    network = _network_module()
    graph = network.Network(
        nodes=(
            network.NetworkNode(id="DEPOT", position=(0.0, 0.0)),
            network.NetworkNode(id="A", position=(3.0, 4.0)),
        ),
        edges=(
            network.NetworkEdge(
                id="DEPOT->A", origin="DEPOT", destination="A",
                geometry=[(0.0, 0.0), (3.0, 4.0)],
            ),
            network.NetworkEdge(
                id="A->DEPOT", origin="A", destination="DEPOT",
                geometry=[(3.0, 4.0), (0.0, 0.0)],
            ),
        ),
    )

    restored = network.Network.from_dict(graph.to_dict())

    assert restored == graph
    assert restored.edge("DEPOT->A").origin == "DEPOT"
    assert restored.edge("A->DEPOT").destination == "DEPOT"
    assert restored.edge("DEPOT->A").geometry != restored.edge("A->DEPOT").geometry

