"""Canonical writers for scenario-v2 audit artifacts."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, Iterable, List

import numpy as np
import yaml

from .audit_geometry import normalized_risk_layers
from .audit_model import AuditScenario


MANDATORY_FIGURES = [
    "truth_map_t4_2.png",
    "controller_map_t4_2.png",
    "truth_vs_controller.png",
    "event_timeline.png",
    "corridor_status_timeline.png",
    "selected_node_truth_vs_reported_demand.png",
    "urgency_evolution.png",
]

DATA_ARTIFACTS = [
    "metadata.json",
    "config_snapshot.yaml",
    "nodes.csv",
    "true_initial_cohorts.csv",
    "operational_initial_cohorts.csv",
    "obstacles.geojson",
    "permanent_nfz.geojson",
    "dynamic_zones.geojson",
    "population_risk.npy",
    "infrastructure_risk.npy",
    "terrain_difficulty.npy",
    "base_composite_risk.npy",
    "risk_layers_metadata.json",
    "corridors.json",
    "exogenous_events.csv",
    "p4_potential_reports.csv",
    "seed_18427.json",
    "audit_actions.json",
    "validation_report.json",
    "README.md",
]


def _write_json(path: Path, payload) -> None:
    path.write_text(
        json.dumps(
            payload,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_csv(path: Path, rows: List[Dict], columns: List[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=columns,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _feature_collection(features: List[Dict]) -> Dict:
    return {"type": "FeatureCollection", "features": features}


def write_data_artifacts(
    scenario: AuditScenario,
    output_dir: str | Path,
    audit_actions: Dict,
) -> Path:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "metadata.json", scenario.metadata)
    (output / "config_snapshot.yaml").write_text(
        yaml.safe_dump(
            scenario.config,
            sort_keys=True,
            allow_unicode=True,
            default_flow_style=False,
        ),
        encoding="utf-8",
        newline="\n",
    )
    _write_csv(
        output / "nodes.csv",
        sorted(scenario.nodes, key=lambda item: item["node_id"]),
        [
            "node_id",
            "x_m",
            "y_m",
            "true_vulnerability",
            "reported_vulnerability",
            "onset_time_s",
            "initially_known",
        ],
    )
    _write_csv(
        output / "true_initial_cohorts.csv",
        sorted(
            scenario.true_initial_cohorts,
            key=lambda item: (
                item["node_id"],
                item["commodity_index"],
                item["onset_time_s"],
            ),
        ),
        [
            "node_id",
            "commodity_index",
            "commodity",
            "cohort_id",
            "onset_time_s",
            "quantity",
        ],
    )
    _write_csv(
        output / "operational_initial_cohorts.csv",
        sorted(
            scenario.operational_initial_cohorts,
            key=lambda item: (
                item["node_id"],
                item["commodity_index"],
                item["reported_onset_time_s"],
            ),
        ),
        [
            "node_id",
            "commodity_index",
            "commodity",
            "cohort_id",
            "reported_onset_time_s",
            "quantity",
        ],
    )

    obstacle_features = []
    for obstacle in scenario.geography["obstacles"]:
        x0, x1 = obstacle["min_x_m"], obstacle["max_x_m"]
        y0, y1 = obstacle["min_y_m"], obstacle["max_y_m"]
        obstacle_features.append(
            {
                "type": "Feature",
                "id": obstacle["obstacle_id"],
                "properties": {
                    "obstacle_id": obstacle["obstacle_id"],
                    "height_m": obstacle["height_m"],
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
                    ],
                },
            }
        )
    _write_json(output / "obstacles.geojson", _feature_collection(obstacle_features))

    permanent_features = []
    for zone in scenario.geography["permanent_nfz"]:
        permanent_features.append(
            {
                "type": "Feature",
                "id": zone["zone_id"],
                "properties": dict(zone),
                "geometry": {
                    "type": "Point",
                    "coordinates": [zone["center_x_m"], zone["center_y_m"]],
                },
            }
        )
    _write_json(
        output / "permanent_nfz.geojson",
        _feature_collection(permanent_features),
    )
    dynamic_features = []
    for zone in scenario.geography["dynamic_zones"]:
        dynamic_features.append(
            {
                "type": "Feature",
                "id": zone["zone_id"],
                "properties": dict(zone),
                "geometry": {
                    "type": "Point",
                    "coordinates": [zone["center_x_m"], zone["center_y_m"]],
                },
            }
        )
    _write_json(
        output / "dynamic_zones.geojson",
        _feature_collection(dynamic_features),
    )

    coarse_grid = scenario.geography["coarse_grid"]
    x_m = np.asarray(coarse_grid["x_m"], dtype=np.float64)
    y_m = np.asarray(coarse_grid["y_m"], dtype=np.float64)
    grid_x, grid_y = np.meshgrid(x_m, y_m, indexing="xy")
    normalized_layers = normalized_risk_layers(
        grid_x, grid_y, scenario.geography, hazard_intensity=0.0
    )
    risk_arrays = {
        "population_risk.npy": normalized_layers["population"],
        "infrastructure_risk.npy": normalized_layers["infrastructure"],
        "terrain_difficulty.npy": normalized_layers["terrain_obstacle"],
        "base_composite_risk.npy": np.asarray(
            coarse_grid["base_composite_risk"], dtype=np.float64
        ),
    }
    for filename, values in risk_arrays.items():
        np.save(
            output / filename,
            np.asarray(values, dtype="<f4"),
            allow_pickle=False,
        )
    _write_json(
        output / "risk_layers_metadata.json",
        {
            "grid": {
                "coordinate_reference": "synthetic_local_metric",
                "origin_m": [float(x_m[0]), float(y_m[0])],
                "cell_size_m": scenario.geography["coarse_cell_m"],
                "shape_yx": [int(len(y_m)), int(len(x_m))],
                "x_coordinates_m": x_m.tolist(),
                "y_coordinates_m": y_m.tolist(),
            },
            "arrays": {
                filename: {
                    "dtype": "float32_little_endian",
                    "normalization": "fixed_configurable_reference_range",
                    "range": [0.0, 1.0],
                }
                for filename in risk_arrays
            },
            "reference_ranges": scenario.geography["risk_reference_ranges"],
            "composite_weights": scenario.geography["risk_weights"],
            "dynamic_hazard_included": False,
        },
    )
    _write_json(
        output / "corridors.json",
        {
            "schema_version": scenario.metadata["schema_version"],
            "directed": True,
            "corridors": [
                {
                    **corridor.__dict__,
                }
                for corridor in sorted(
                    scenario.corridors, key=lambda item: item.corridor_id
                )
            ],
        },
    )
    event_rows = []
    for event in scenario.exogenous_events:
        event_rows.append(
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "physical_occurrence_time_s": event.physical_occurrence_time_s,
                "report_generation_time_s": (
                    "" if event.report_generation_time_s is None else event.report_generation_time_s
                ),
                "report_reception_time_s": (
                    "" if event.report_reception_time_s is None else event.report_reception_time_s
                ),
                "affected_entity": event.affected_entity,
                "commodity": event.commodity or "",
                "magnitude_or_mark": json.dumps(
                    event.magnitude_or_mark,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ),
                "visible_to_controller": event.visible_to_controller,
                "report_lost": event.report_lost,
                "source_seed_stream": event.source_seed_stream,
            }
        )
    _write_csv(
        output / "exogenous_events.csv",
        event_rows,
        [
            "event_id",
            "event_type",
            "physical_occurrence_time_s",
            "report_generation_time_s",
            "report_reception_time_s",
            "affected_entity",
            "commodity",
            "magnitude_or_mark",
            "visible_to_controller",
            "report_lost",
            "source_seed_stream",
        ],
    )
    p4_rows = [
        {
            "node_id": item.node_id,
            "service_visit_index": item.service_visit_index,
            "will_generate": item.will_generate,
            "report_delay_s": item.report_delay_s,
            "report_lost": item.report_lost,
            "confidence": item.confidence,
            "noise_by_commodity": json.dumps(
                item.noise_by_commodity, separators=(",", ":")
            ),
            "source_seed_stream": item.source_seed_stream,
        }
        for item in scenario.p4_potential_outcomes
    ]
    _write_csv(
        output / "p4_potential_reports.csv",
        p4_rows,
        [
            "node_id",
            "service_visit_index",
            "will_generate",
            "report_delay_s",
            "report_lost",
            "confidence",
            "noise_by_commodity",
            "source_seed_stream",
        ],
    )
    scenario.to_json(output / f"seed_{scenario.metadata['master_seed']}.json")
    _write_json(output / "audit_actions.json", audit_actions)
    (output / "README.md").write_text(
        f"""# Seed {scenario.metadata['master_seed']} audit package

This directory is a deterministic scenario-v2 package. Canonical internal
units are metres, seconds, watt-hours, kilograms, and standardized demand
units. Medical and water are active; food and shelter slots are retained at
zero for compatibility.

Generate and audit from the `code` directory:

```text
python -m scripts.generate_seed --seed {scenario.metadata['master_seed']} --config configs/prototype_seed.yaml --output outputs/seed_{scenario.metadata['master_seed']}
python -m scripts.audit_seed --scenario outputs/seed_{scenario.metadata['master_seed']}/seed_{scenario.metadata['master_seed']}.json --audit-actions outputs/seed_{scenario.metadata['master_seed']}/audit_actions.json --time-hours 4.2
```

`seed_{scenario.metadata['master_seed']}.json` contains the exogenous scenario
only. `audit_actions.json` is a separate scripted audit policy and is never
part of the exogenous event schedule. The four `.npy` files expose the
normalized population, infrastructure, terrain-difficulty, and base composite
risk rasters on the coarse grid. See `risk_layers_metadata.json` for
coordinates, fixed normalization references, dtype, and composite weights.
""",
        encoding="utf-8",
        newline="\n",
    )
    return output


def write_validation_report(output_dir: str | Path, report: Dict) -> Path:
    path = Path(output_dir) / "validation_report.json"
    _write_json(path, report)
    return path
