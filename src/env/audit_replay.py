"""Deterministic replay with strictly separated physical and controller state."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import yaml

from .audit_geometry import condition_at, intersects_zone
from .audit_model import AuditScenario, ControllerState, PhysicalState


def load_audit_actions(path: str | Path) -> Dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict) or "actions" not in payload:
        raise ValueError(f"Invalid audit-policy action file: {path}")
    return payload


def _copy_cohort(row: Dict) -> Dict:
    return {
        "node_id": row["node_id"],
        "commodity_index": int(row["commodity_index"]),
        "commodity": row["commodity"],
        "cohort_id": row["cohort_id"],
        "onset_time_s": float(
            row.get("onset_time_s", row.get("reported_onset_time_s", 0.0))
        ),
        "quantity": float(row["quantity"]),
    }


def _group(rows: Iterable[Dict]) -> Dict[str, List[Dict]]:
    grouped: Dict[str, List[Dict]] = {}
    for row in rows:
        grouped.setdefault(row["node_id"], []).append(_copy_cohort(row))
    for cohorts in grouped.values():
        cohorts.sort(
            key=lambda item: (
                item["commodity_index"],
                item["onset_time_s"],
                item["cohort_id"],
            )
        )
    return grouped


def _replace_operational_node(
    grouped: Dict[str, List[Dict]],
    node_id: str,
    reported_cohorts: Sequence[Dict],
    commodity_names: Sequence[str],
) -> None:
    grouped[node_id] = []
    for index, row in enumerate(reported_cohorts):
        commodity_index = int(row["commodity_index"])
        grouped[node_id].append(
            {
                "node_id": node_id,
                "commodity_index": commodity_index,
                "commodity": commodity_names[commodity_index],
                "cohort_id": f"{node_id}_report_{index}",
                "onset_time_s": float(row["onset_time_s"]),
                "quantity": float(row["quantity"]),
            }
        )


def _replace_operational_aggregate(
    grouped: Dict[str, List[Dict]],
    node_id: str,
    demand: Sequence[float],
    commodity_names: Sequence[str],
    onset_time_s: float,
) -> None:
    grouped[node_id] = []
    for index, quantity in enumerate(demand):
        if quantity <= 0:
            continue
        grouped[node_id].append(
            {
                "node_id": node_id,
                "commodity_index": index,
                "commodity": commodity_names[index],
                "cohort_id": f"{node_id}_aggregate_report_{index}",
                "onset_time_s": float(onset_time_s),
                "quantity": float(quantity),
            }
        )


def reduce_fofs(
    grouped: Dict[str, List[Dict]], node_id: str, quantities: Sequence[float]
) -> List[float]:
    """Apply first-onset-first-served reduction and return accepted amounts."""
    accepted = [0.0] * len(quantities)
    cohorts = grouped.setdefault(node_id, [])
    for commodity_index, requested in enumerate(quantities):
        remaining = max(float(requested), 0.0)
        candidates = sorted(
            (
                item
                for item in cohorts
                if item["commodity_index"] == commodity_index
                and item["quantity"] > 1e-12
            ),
            key=lambda item: (item["onset_time_s"], item["cohort_id"]),
        )
        for cohort in candidates:
            take = min(cohort["quantity"], remaining)
            cohort["quantity"] -= take
            remaining -= take
            accepted[commodity_index] += take
            if remaining <= 1e-12:
                break
    grouped[node_id] = [item for item in cohorts if item["quantity"] > 1e-12]
    return accepted


class ScenarioReplay:
    """Policy-free deterministic replay; construction consumes no random source."""

    def __init__(
        self, scenario: AuditScenario, audit_actions: Optional[Dict] = None
    ) -> None:
        self.scenario = scenario
        self.audit_actions = audit_actions or {"actions": []}
        if "audit_actions" in scenario.to_dict():
            raise ValueError("Scenario JSON must not contain audit-policy actions")
        if not scenario.p4_potential_outcomes:
            raise ValueError(
                "Deterministic scenario-v2 replay requires pre-sampled "
                "P4 potential outcomes; legacy p4_seed is not sampled online"
            )

    def snapshot(self, time_s: float) -> Tuple[PhysicalState, ControllerState]:
        if time_s < 0:
            raise ValueError("Replay time must be nonnegative")
        commodity_names = self.scenario.metadata["commodity_names"]
        nodes_by_id = {item["node_id"]: item for item in self.scenario.nodes}
        true_rows = [
            row
            for row in self.scenario.true_initial_cohorts
            if row["onset_time_s"] <= time_s
        ]
        true_grouped = _group(true_rows)
        operational_grouped = _group(self.scenario.operational_initial_cohorts)
        known = {
            item["node_id"] for item in self.scenario.nodes if item["initially_known"]
        }
        reported_vulnerability = {
            item["node_id"]: item["reported_vulnerability"]
            for item in self.scenario.nodes
            if item["initially_known"]
        }
        node_report_generation = {
            item["node_id"]: 0.0
            for item in self.scenario.nodes
            if item["initially_known"]
        }
        node_report_confidence = {
            item["node_id"]: 1.0
            for item in self.scenario.nodes
            if item["initially_known"]
        }
        received_zone_generation: Dict[str, float] = {}
        received_corridor_generation: Dict[str, float] = {}
        received_events: List[str] = []
        received_notices: List[str] = []
        inventory_true = [
            float(v) for v in self.scenario.depot["initial_inventory"]
        ]
        inventory_oper = list(inventory_true)

        for event in self.scenario.exogenous_events:
            if event.physical_occurrence_time_s <= time_s:
                mark = event.magnitude_or_mark
                if event.event_type == "P3_MUTATION":
                    delta = mark["delta"]
                    node_id = event.affected_entity
                    for index, quantity in enumerate(delta):
                        if quantity <= 0:
                            continue
                        true_grouped.setdefault(node_id, []).append(
                            {
                                "node_id": node_id,
                                "commodity_index": index,
                                "commodity": commodity_names[index],
                                "cohort_id": f"{event.event_id}_{index}",
                                "onset_time_s": event.physical_occurrence_time_s,
                                "quantity": float(quantity),
                            }
                        )
                if event.event_type == "DEPOT_REPLENISHMENT":
                    inventory_true = [
                        left + right
                        for left, right in zip(inventory_true, mark["quantity"])
                    ]
            received = (
                not event.report_lost
                and event.report_reception_time_s is not None
                and event.report_reception_time_s <= time_s
            )
            if not received:
                continue
            received_events.append(event.event_id)
            if event.event_type in {
                "TEMP_NFZ_ACTIVATE",
                "TEMP_NFZ_EXPIRE",
                "HAZARD_ACTIVATE",
                "HAZARD_DEACTIVATE",
            }:
                received_notices.append(event.affected_entity)
                received_zone_generation[event.affected_entity] = float(
                    event.report_generation_time_s
                    if event.report_generation_time_s is not None
                    else event.report_reception_time_s
                )
            elif event.event_type == "P2_NODE_REVEAL":
                node_id = event.affected_entity
                known.add(node_id)
                _replace_operational_aggregate(
                    operational_grouped,
                    node_id,
                    event.magnitude_or_mark["reported_demand"],
                    commodity_names,
                    nodes_by_id[node_id]["onset_time_s"],
                )
                reported_vulnerability[node_id] = float(
                    event.magnitude_or_mark["reported_vulnerability"]
                )
                node_report_generation[node_id] = float(
                    event.report_generation_time_s
                    if event.report_generation_time_s is not None
                    else event.report_reception_time_s
                )
                node_report_confidence[node_id] = float(
                    event.magnitude_or_mark.get("confidence", 1.0)
                )
            elif event.event_type == "P1_REPORT":
                node_id = event.affected_entity
                if "reported_cohorts" in event.magnitude_or_mark:
                    _replace_operational_node(
                        operational_grouped,
                        node_id,
                        event.magnitude_or_mark["reported_cohorts"],
                        commodity_names,
                    )
                elif "reported_demand" in event.magnitude_or_mark:
                    _replace_operational_aggregate(
                        operational_grouped,
                        node_id,
                        event.magnitude_or_mark["reported_demand"],
                        commodity_names,
                        nodes_by_id[node_id]["onset_time_s"],
                    )
                if "reported_vulnerability" in event.magnitude_or_mark:
                    reported_vulnerability[node_id] = float(
                        event.magnitude_or_mark["reported_vulnerability"]
                    )
                node_report_generation[node_id] = float(
                    event.report_generation_time_s
                    if event.report_generation_time_s is not None
                    else event.report_reception_time_s
                )
                node_report_confidence[node_id] = float(
                    event.magnitude_or_mark.get("confidence", 1.0)
                )
            elif event.event_type == "CORRIDOR_CONDITION_REPORT":
                received_corridor_generation[event.affected_entity] = float(
                    event.report_generation_time_s
                    if event.report_generation_time_s is not None
                    else event.report_reception_time_s
                )
            elif event.event_type == "DEPOT_REPLENISHMENT":
                inventory_oper = [
                    left + right
                    for left, right in zip(
                        inventory_oper, event.magnitude_or_mark["quantity"]
                    )
                ]

        activated_visits: List[Tuple[str, int, float]] = []
        for action in sorted(
            self.audit_actions.get("actions", []),
            key=lambda item: (item["time_s"], item["action_id"]),
        ):
            if action["time_s"] > time_s:
                continue
            if action["action_type"] != "delivery":
                raise ValueError(f"Unsupported audit action: {action['action_type']}")
            reduce_fofs(
                true_grouped, action["node_id"], action["quantities"]
            )
            reduce_fofs(
                operational_grouped, action["node_id"], action["quantities"]
            )
            activated_visits.append(
                (
                    action["node_id"],
                    int(action["service_visit_index"]),
                    float(action["time_s"]),
                )
            )

        for node_id, visit_index, service_time in activated_visits:
            candidates = [
                outcome
                for outcome in self.scenario.p4_potential_outcomes
                if outcome.node_id == node_id
                and outcome.service_visit_index == visit_index
            ]
            if len(candidates) != 1:
                raise ValueError(
                    f"Expected one P4 potential for {node_id} visit {visit_index}"
                )
            potential = candidates[0]
            reception = service_time + potential.report_delay_s
            if (
                potential.will_generate
                and not potential.report_lost
                and reception <= time_s
            ):
                operational_grouped[node_id] = copy.deepcopy(
                    true_grouped.get(node_id, [])
                )
                received_events.append(f"P4_{node_id}_{visit_index}")
                node_report_generation[node_id] = float(service_time)
                node_report_confidence[node_id] = float(potential.confidence)

        scenario_dict = self.scenario.to_dict()
        physical_conditions = {
            corridor.corridor_id: condition_at(
                corridor, scenario_dict, time_s, operational=False
            ).value
            for corridor in self.scenario.corridors
        }
        operational_conditions = {
            corridor.corridor_id: condition_at(
                corridor, scenario_dict, time_s, operational=True
            ).value
            for corridor in self.scenario.corridors
            if (corridor.origin == "DEPOT" or corridor.origin in known)
            and (corridor.destination == "DEPOT" or corridor.destination in known)
        }
        zone_by_id = {
            zone["zone_id"]: zone
            for zone in self.scenario.geography["dynamic_zones"]
        }
        corridor_report_generation: Dict[str, float] = {}
        for corridor in self.scenario.corridors:
            if corridor.corridor_id not in operational_conditions:
                continue
            latest = received_corridor_generation.get(corridor.corridor_id, 0.0)
            for zone_id, generation_time in received_zone_generation.items():
                if intersects_zone(corridor, zone_by_id[zone_id]):
                    latest = max(latest, generation_time)
            corridor_report_generation[corridor.corridor_id] = latest
        active_temp = [
            zone["zone_id"]
            for zone in self.scenario.geography["dynamic_zones"]
            if zone["zone_type"] == "temporary_nfz"
            and zone["active_from_s"] <= time_s < zone["active_to_s"]
        ]
        active_hazard = [
            zone["zone_id"]
            for zone in self.scenario.geography["dynamic_zones"]
            if zone["zone_type"] == "hazard"
            and zone["active_from_s"] <= time_s < zone["active_to_s"]
        ]
        physical = PhysicalState(
            time_s=float(time_s),
            node_cohorts=true_grouped,
            true_vulnerability={
                item["node_id"]: item["true_vulnerability"]
                for item in self.scenario.nodes
                if item["onset_time_s"] <= time_s
            },
            active_temporary_nfz_ids=active_temp,
            active_hazard_ids=active_hazard,
            corridor_conditions=physical_conditions,
            depot_inventory=inventory_true,
        )
        controller = ControllerState(
            time_s=float(time_s),
            known_nodes=sorted(known),
            operational_cohorts={
                node_id: operational_grouped.get(node_id, [])
                for node_id in sorted(known)
            },
            reported_vulnerability={
                node_id: reported_vulnerability[node_id]
                for node_id in sorted(known)
            },
            received_zone_notices=sorted(set(received_notices)),
            believed_corridor_conditions=operational_conditions,
            depot_inventory=inventory_oper,
            received_event_ids=sorted(received_events),
            node_report_generation_time_s={
                node_id: node_report_generation[node_id]
                for node_id in sorted(known)
            },
            node_report_confidence={
                node_id: node_report_confidence[node_id]
                for node_id in sorted(known)
            },
            corridor_report_generation_time_s=corridor_report_generation,
        )
        controller.to_dict()
        return physical, controller

    def urgency_rankings(self, time_s: float) -> Dict[str, List[str]]:
        physical, controller = self.snapshot(time_s)
        commodity = self.scenario.config["commodities"]
        true_scores = {
            node_id: urgency_score(
                cohorts,
                physical.true_vulnerability[node_id],
                time_s,
                commodity,
            )
            for node_id, cohorts in physical.node_cohorts.items()
            if node_id in physical.true_vulnerability
        }
        operational_scores = {
            node_id: urgency_score(
                controller.operational_cohorts.get(node_id, []),
                controller.reported_vulnerability[node_id],
                time_s,
                commodity,
            )
            for node_id in controller.known_nodes
        }
        return {
            "true": sorted(true_scores, key=lambda key: (-true_scores[key], key)),
            "operational": sorted(
                operational_scores, key=lambda key: (-operational_scores[key], key)
            ),
            "true_scores": true_scores,
            "operational_scores": operational_scores,
        }


def urgency_score(
    cohorts: Sequence[Dict], vulnerability: float, time_s: float, commodity: Dict
) -> float:
    total = 0.0
    for cohort in cohorts:
        index = int(cohort["commodity_index"])
        age_h = max((time_s - float(cohort["onset_time_s"])) / 3600.0, 0.0)
        rate = (
            commodity["waiting_scale"][index]
            * commodity["waiting_growth_per_hour"][index]
            * math_exp(commodity["waiting_growth_per_hour"][index] * age_h)
        )
        total += (
            commodity["criticality"][index]
            * float(cohort["quantity"])
            * rate
        )
    return float(vulnerability) * total


def math_exp(value: float) -> float:
    # Isolated for straightforward monkeypatching in tests; it is deterministic.
    return float(np.exp(value))
