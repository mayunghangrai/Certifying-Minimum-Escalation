"""Strict seed-18427 audit for the optional operational belief graph."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from env.audit_model import AuditScenario  # noqa: E402
from env.audit_replay import ScenarioReplay, load_audit_actions  # noqa: E402
from methods.belief_graph import (  # noqa: E402
    NODE_FEATURE_NAMES,
    OperationalBeliefGraphBuilder,
)


CHECKPOINT_HOURS = (3.7, 4.2, 4.8, 5.0, 5.1)
NFZ_CORRIDOR = "corridor_depot_n3_south_outbound"
NFZ_ALTERNATIVE = "corridor_depot_n3_north_alternative"
HAZARD_CORRIDOR = "corridor_n1_n5_hazard_outbound"


def _total(cohorts, node_id: str, commodity_index: int) -> float:
    return float(
        sum(
            row["quantity"]
            for row in cohorts.get(node_id, [])
            if row["commodity_index"] == commodity_index
        )
    )


def _graph_hash(graph) -> str:
    digest = hashlib.sha256()
    for array in (
        graph.node_features,
        graph.node_type_ids,
        graph.edge_index,
        graph.edge_features,
        graph.node_mask,
        graph.edge_mask,
    ):
        digest.update(np.ascontiguousarray(array).tobytes())
    digest.update(
        json.dumps(
            graph.entity_id_to_slot, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )
    return digest.hexdigest()


def audit(scenario_path: Path, actions_path: Path) -> dict:
    scenario = AuditScenario.from_json(scenario_path)
    actions = load_audit_actions(actions_path)
    replay = ScenarioReplay(scenario, actions)
    builder = OperationalBeliefGraphBuilder(max_known_nodes=len(scenario.nodes))
    water = scenario.metadata["commodity_names"].index("water")
    if scenario.metadata["active_commodity_mask"] != [1, 0, 1, 0]:
        raise AssertionError("Canonical medical/water mask is not [1, 0, 1, 0]")

    records = {}
    graphs = {}
    states = {}
    for hours in CHECKPOINT_HOURS:
        physical, controller = replay.snapshot(hours * 3600.0)
        graph = builder.build_from_controller(scenario, controller)
        key = f"{hours:.1f}"
        graphs[key] = graph
        states[key] = (physical, controller)
        records[key] = {
            "known_nodes": sorted(controller.known_nodes),
            "n3_true_water": _total(physical.node_cohorts, "N3", water),
            "n3_operational_water": _total(
                controller.operational_cohorts, "N3", water
            ),
            "n3_graph_water": (
                float(
                    graph.node_features[
                        graph.entity_id_to_slot["N3"],
                        NODE_FEATURE_NAMES.index("commodity_2"),
                    ]
                    * 10.0
                )
                if "N3" in graph.entity_id_to_slot
                else None
            ),
            "nfz_corridor_belief": controller.believed_corridor_conditions.get(
                NFZ_CORRIDOR
            ),
            "hazard_corridor_belief": (
                controller.believed_corridor_conditions.get(HAZARD_CORRIDOR)
            ),
            "nfz_corridor_available": graph.operational_corridor_mask.get(
                NFZ_CORRIDOR
            ),
            "alternative_available": graph.operational_corridor_mask.get(
                NFZ_ALTERNATIVE
            ),
            "graph_hash": _graph_hash(graph),
        }

    physical_37, _ = states["3.7"]
    if not (
        records["3.7"]["n3_true_water"] == 16.0
        and records["3.7"]["n3_operational_water"] == 6.0
        and np.isclose(records["3.7"]["n3_graph_water"], 6.0)
    ):
        raise AssertionError("3.7 h hidden-P3 truth exclusion failed")

    physical_42, controller_42 = states["4.2"]
    if "N6" in graphs["4.2"].entity_id_to_slot:
        raise AssertionError("N6 entered the graph before P2 reception")
    if not (
        "TNFZ1" in physical_42.active_temporary_nfz_ids
        and "TNFZ1" not in controller_42.received_zone_notices
        and "HAZ1" in physical_42.active_hazard_ids
        and "HAZ1" not in controller_42.received_zone_notices
    ):
        raise AssertionError("4.2 h hidden zone-information mismatch failed")
    if not (
        physical_42.corridor_conditions[NFZ_CORRIDOR] == "CLOSED"
        and controller_42.believed_corridor_conditions[NFZ_CORRIDOR] == "NORMAL"
        and physical_42.corridor_conditions[HAZARD_CORRIDOR] == "DEGRADED"
        and controller_42.believed_corridor_conditions[HAZARD_CORRIDOR]
        == "NORMAL"
    ):
        raise AssertionError("4.2 h named-corridor truth exclusion failed")

    if records["4.8"]["nfz_corridor_belief"] != "CLOSED":
        raise AssertionError("NFZ corridor was not closed at notice reception")
    if records["4.8"]["nfz_corridor_available"] is not False:
        raise AssertionError("Received closure did not mask the named corridor")
    if records["4.8"]["alternative_available"] is not True:
        raise AssertionError("Operational NFZ alternative is unavailable")
    if "N6" not in graphs["5.0"].entity_id_to_slot:
        raise AssertionError("N6 did not enter graph at P2 reception")
    if not (
        records["5.1"]["n3_operational_water"] == 16.0
        and np.isclose(records["5.1"]["n3_graph_water"], 16.0)
    ):
        raise AssertionError("N3 graph did not update at P1 reception")
    n3_slot_50 = graphs["5.0"].entity_id_to_slot["N3"]
    n3_slot_51 = graphs["5.1"].entity_id_to_slot["N3"]
    urgency_index = NODE_FEATURE_NAMES.index("operational_urgency")
    if not (
        graphs["5.1"].node_features[n3_slot_51, urgency_index]
        > graphs["5.0"].node_features[n3_slot_50, urgency_index]
    ):
        raise AssertionError("N3 operational urgency did not increase after P1")

    return {
        "passed": True,
        "scenario_hash": scenario.content_hash(),
        "commodity_mapping": {
            "names": scenario.metadata["commodity_names"],
            "active_mask": scenario.metadata["active_commodity_mask"],
        },
        "checkpoints": records,
        "limitations": [
            "Scenario-v2 audit replay has no live ALNS incumbent; plan-confidence "
            "features are validated in active-environment tests and smoke runs."
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        type=Path,
        default=Path("outputs/seed_18427/seed_18427.json"),
    )
    parser.add_argument(
        "--audit-actions",
        type=Path,
        default=Path("outputs/seed_18427/audit_actions.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/seed_18427/belief_graph_audit.json"),
    )
    args = parser.parse_args()
    result = audit(args.scenario, args.audit_actions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"audit -> {args.output}")


if __name__ == "__main__":
    main()
