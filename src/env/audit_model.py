"""Typed scenario-v2 containers used by deterministic generation and audit."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


SCHEMA_VERSION = "2.0"
GENERATOR_VERSION = "2.0.0"


class CorridorCondition(str, Enum):
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class Corridor:
    corridor_id: str
    origin: str
    destination: str
    waypoints_m: List[List[float]]
    nominal_length_m: float
    accumulated_climb_m: float
    accumulated_descent_m: float
    cruise_altitude_m: float
    nominal_travel_time_s: float
    nominal_energy_wh: float
    integrated_geographical_risk: float
    minimum_obstacle_clearance_m: float
    static_feasible: bool
    generation_seed_stream: str
    version: str = GENERATOR_VERSION
    fixture_role: Optional[str] = None


@dataclass(frozen=True)
class ExogenousEvent:
    event_id: str
    event_type: str
    physical_occurrence_time_s: float
    report_generation_time_s: Optional[float]
    report_reception_time_s: Optional[float]
    affected_entity: str
    commodity: Optional[str]
    magnitude_or_mark: Dict[str, Any]
    visible_to_controller: bool
    report_lost: bool
    source_seed_stream: str


@dataclass(frozen=True)
class P4Potential:
    node_id: str
    service_visit_index: int
    will_generate: bool
    report_delay_s: float
    report_lost: bool
    confidence: float
    noise_by_commodity: List[float]
    source_seed_stream: str


@dataclass
class AuditScenario:
    metadata: Dict[str, Any]
    config: Dict[str, Any]
    geography: Dict[str, Any]
    nodes: List[Dict[str, Any]]
    true_initial_cohorts: List[Dict[str, Any]]
    operational_initial_cohorts: List[Dict[str, Any]]
    corridors: List[Corridor]
    fleet: Dict[str, Any]
    depot: Dict[str, Any]
    exogenous_events: List[ExogenousEvent]
    p4_potential_outcomes: List[P4Potential]

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def to_json(self, path: str | Path) -> Path:
        path = Path(path)
        payload = self.to_dict()
        payload["content_hash"] = self.content_hash()
        text = json.dumps(
            payload,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        path.write_text(text + "\n", encoding="utf-8", newline="\n")
        return path

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "AuditScenario":
        data = dict(payload)
        expected_hash = data.pop("content_hash", None)
        obj = cls(
            metadata=data["metadata"],
            config=data["config"],
            geography=data["geography"],
            nodes=data["nodes"],
            true_initial_cohorts=data["true_initial_cohorts"],
            operational_initial_cohorts=data["operational_initial_cohorts"],
            corridors=[Corridor(**item) for item in data["corridors"]],
            fleet=data["fleet"],
            depot=data["depot"],
            exogenous_events=[
                ExogenousEvent(**item) for item in data["exogenous_events"]
            ],
            p4_potential_outcomes=[
                P4Potential(**item) for item in data["p4_potential_outcomes"]
            ],
        )
        if expected_hash is not None and expected_hash != obj.content_hash():
            raise ValueError(
                "Scenario content hash mismatch: file is not a canonical "
                "or unmodified scenario-v2 artifact"
            )
        return obj

    @classmethod
    def from_json(cls, path: str | Path) -> "AuditScenario":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


@dataclass
class PhysicalState:
    time_s: float
    node_cohorts: Dict[str, List[Dict[str, Any]]]
    true_vulnerability: Dict[str, float]
    active_temporary_nfz_ids: List[str]
    active_hazard_ids: List[str]
    corridor_conditions: Dict[str, str]
    depot_inventory: List[float]

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class ControllerState:
    time_s: float
    known_nodes: List[str]
    operational_cohorts: Dict[str, List[Dict[str, Any]]]
    reported_vulnerability: Dict[str, float]
    received_zone_notices: List[str]
    believed_corridor_conditions: Dict[str, str]
    depot_inventory: List[float]
    received_event_ids: List[str] = field(default_factory=list)
    node_report_generation_time_s: Dict[str, float] = field(default_factory=dict)
    node_report_confidence: Dict[str, float] = field(default_factory=dict)
    corridor_report_generation_time_s: Dict[str, float] = field(
        default_factory=dict
    )

    def to_dict(self) -> Dict[str, Any]:
        payload = dataclasses.asdict(self)
        forbidden = {
            "true_vulnerability",
            "true_demand",
            "latent_demand",
            "physical_corridor_conditions",
            "unreceived_events",
        }
        leaked = forbidden.intersection(payload)
        if leaked:
            raise AssertionError(f"Controller export contains latent truth: {sorted(leaked)}")
        return payload
