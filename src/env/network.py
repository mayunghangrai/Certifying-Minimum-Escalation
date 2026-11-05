"""Directed network records used by the method-neutral routing core."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence, Tuple


Point2D = Tuple[float, float]


def _point(value: Sequence[float], name: str = "point") -> Point2D:
    if len(value) != 2:
        raise ValueError(f"{name} must contain two coordinates")
    point = (float(value[0]), float(value[1]))
    if not all(math.isfinite(component) for component in point):
        raise ValueError(f"{name} must contain finite coordinates")
    return point


def _geometry(values: Sequence[Sequence[float]]) -> Tuple[Point2D, ...]:
    points = tuple(_point(value, "edge geometry point") for value in values)
    if len(points) < 2:
        raise ValueError("edge geometry must contain at least two points")
    if any(left == right for left, right in zip(points[:-1], points[1:])):
        raise ValueError("edge geometry cannot contain consecutive duplicate points")
    return points


@dataclass(frozen=True)
class NetworkNode:
    """One graph vertex in the local Cartesian mission map."""

    id: str
    position: Point2D

    def __post_init__(self) -> None:
        node_id = str(self.id)
        if not node_id:
            raise ValueError("network node id must be nonempty")
        object.__setattr__(self, "id", node_id)
        object.__setattr__(self, "position", _point(self.position, "node position"))

    def to_dict(self) -> dict:
        return {"id": self.id, "position": list(self.position)}

    @classmethod
    def from_dict(cls, payload: Mapping) -> "NetworkNode":
        return cls(id=payload["id"], position=payload["position"])


@dataclass(frozen=True)
class NetworkEdge:
    """A directed corridor with geometry shared by all physical evaluators."""

    id: str
    origin: str
    destination: str
    geometry: Tuple[Point2D, ...]
    length_km: Optional[float] = None
    bearing_rad: Optional[float] = None

    def __post_init__(self) -> None:
        edge_id = str(self.id)
        origin = str(self.origin)
        destination = str(self.destination)
        if not edge_id or not origin or not destination:
            raise ValueError("network edge id, origin, and destination must be nonempty")
        if origin == destination:
            raise ValueError("network edge origin and destination must differ")
        points = _geometry(self.geometry)
        length = sum(
            math.hypot(right[0] - left[0], right[1] - left[1])
            for left, right in zip(points[:-1], points[1:])
        )
        if length <= 0.0:
            raise ValueError("network edge length must be positive")
        direction = (points[-1][0] - points[0][0], points[-1][1] - points[0][1])
        direction_length = math.hypot(*direction)
        if direction_length <= 0.0:
            raise ValueError("network edge endpoints must differ")
        derived_bearing = math.atan2(direction[1], direction[0])
        if self.length_km is not None:
            supplied_length = float(self.length_km)
            if not math.isfinite(supplied_length) or supplied_length <= 0.0:
                raise ValueError("network edge length_km must be positive and finite")
            if not math.isclose(supplied_length, length, rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError("network edge length_km does not match its geometry")
        if self.bearing_rad is not None:
            supplied_bearing = float(self.bearing_rad)
            if not math.isfinite(supplied_bearing):
                raise ValueError("network edge bearing_rad must be finite")
        object.__setattr__(self, "id", edge_id)
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "destination", destination)
        object.__setattr__(self, "geometry", points)
        object.__setattr__(self, "length_km", float(length))
        object.__setattr__(self, "bearing_rad", float(derived_bearing))

    @property
    def length(self) -> float:
        """Compatibility alias for the canonical kilometre length."""
        return self.length_km

    @property
    def bearing(self) -> float:
        """Compatibility alias for the canonical radian bearing."""
        return self.bearing_rad

    @property
    def direction_xy(self) -> Point2D:
        return (math.cos(self.bearing_rad), math.sin(self.bearing_rad))

    @property
    def perpendicular_direction_xy(self) -> Point2D:
        """Counter-clockwise unit normal of this directed corridor."""
        direction = self.direction_xy
        return (-direction[1], direction[0])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "origin": self.origin,
            "destination": self.destination,
            "length_km": float(self.length_km),
            "bearing_rad": float(self.bearing_rad),
            "geometry": [list(point) for point in self.geometry],
        }

    @classmethod
    def from_dict(cls, payload: Mapping) -> "NetworkEdge":
        return cls(
            id=payload["id"],
            origin=payload["origin"],
            destination=payload["destination"],
            geometry=payload["geometry"],
            length_km=payload.get("length_km"),
            bearing_rad=payload.get("bearing_rad"),
        )


@dataclass(frozen=True)
class Network:
    """Validated graph container; edge direction is part of its identity."""

    nodes: Tuple[NetworkNode, ...]
    edges: Tuple[NetworkEdge, ...]

    def __post_init__(self) -> None:
        nodes = tuple(
            node if isinstance(node, NetworkNode) else NetworkNode.from_dict(node)
            for node in self.nodes
        )
        edges = tuple(
            edge if isinstance(edge, NetworkEdge) else NetworkEdge.from_dict(edge)
            for edge in self.edges
        )
        node_ids = [node.id for node in nodes]
        edge_ids = [edge.id for edge in edges]
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("network node ids must be unique")
        if len(set(edge_ids)) != len(edge_ids):
            raise ValueError("network edge ids must be unique")
        known = set(node_ids)
        if any(edge.origin not in known or edge.destination not in known for edge in edges):
            raise ValueError("network edge endpoint is not a known node")
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "edges", edges)

    def edge(self, edge_id: str) -> NetworkEdge:
        for edge in self.edges:
            if edge.id == edge_id:
                return edge
        raise KeyError(edge_id)

    def edges_between(self, origin: str, destination: str) -> Tuple[NetworkEdge, ...]:
        return tuple(
            edge for edge in self.edges
            if edge.origin == str(origin) and edge.destination == str(destination)
        )

    def to_dict(self) -> dict:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }

    @classmethod
    def from_dict(cls, payload: Mapping) -> "Network":
        return cls(
            nodes=tuple(NetworkNode.from_dict(node) for node in payload.get("nodes", [])),
            edges=tuple(NetworkEdge.from_dict(edge) for edge in payload.get("edges", [])),
        )
