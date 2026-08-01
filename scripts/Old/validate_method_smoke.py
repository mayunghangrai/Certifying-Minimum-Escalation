"""Fail-loud validation of belief-graph method smoke artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


LAYOUT = {
    "vanilla_mappo": "vanilla",
    "graph_mappo": "graph",
    "graph_mappo_fixed_alns": "fixed",
    "graph_mappo_adaptive_alns": "adaptive",
}


def _rows(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise AssertionError(f"No rows in {path}")
    return rows


def validate(root: Path) -> dict:
    results = {}
    for mode, folder in LAYOUT.items():
        base = root / folder
        train_path = base / "logs" / f"{mode}_train_log.csv"
        diagnostic_path = base / "logs" / f"{mode}_decision_diagnostics.csv"
        checkpoint = base / "models" / f"{mode}.pt"
        train = _rows(train_path)
        diagnostics = _rows(diagnostic_path)
        for row in train:
            for field in ("actor_loss", "critic_loss", "reward"):
                if not math.isfinite(float(row[field])):
                    raise AssertionError(f"{mode}: non-finite {field}")
        followed = deviated = 0
        gate_values = []
        for row in diagnostics:
            selected = int(row["selected_action"])
            mask = json.loads(row["operational_action_mask"])
            if selected < 0 or selected >= len(mask) or mask[selected] != 1:
                raise AssertionError(f"{mode}: selected masked action {selected}")
            recommended = int(row["alns_recommended_action"])
            if recommended >= 0 and mask[recommended] != 1:
                raise AssertionError(
                    f"{mode}: ALNS recommendation is operationally masked"
                )
            gate = float(row["gate"])
            if not 0.0 <= gate <= 1.0:
                raise AssertionError(f"{mode}: gate outside [0,1]")
            gate_values.append(gate)
            followed += int(row["followed_alns"])
            deviated += int(row["deviated_from_alns"])
        if mode in {"vanilla_mappo", "graph_mappo"} and any(gate_values):
            raise AssertionError(f"{mode}: no-guidance gate is nonzero")
        if mode == "graph_mappo_fixed_alns" and any(
            abs(value - 0.5) > 1e-7 for value in gate_values
        ):
            raise AssertionError("Fixed guidance did not use g=0.5")
        if not checkpoint.exists() or checkpoint.stat().st_size == 0:
            raise AssertionError(f"{mode}: checkpoint missing")
        results[mode] = {
            "passed": True,
            "decision_count": len(diagnostics),
            "finite_losses": True,
            "all_selected_actions_operationally_valid": True,
            "gate_min": min(gate_values),
            "gate_max": max(gate_values),
            "followed_alns_count": followed,
            "deviated_from_alns_count": deviated,
            "checkpoint": str(checkpoint),
        }
    return {"passed": True, "modes": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path("results/method_smoke")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/method_smoke/smoke_validation.json"),
    )
    args = parser.parse_args()
    result = validate(args.root)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"validation -> {args.output}")


if __name__ == "__main__":
    main()
