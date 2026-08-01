"""Generate, validate, and visualize one deterministic scenario-v2 seed."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.env.audit_artifacts import (
    DATA_ARTIFACTS,
    MANDATORY_FIGURES,
    write_data_artifacts,
    write_validation_report,
)
from src.env.audit_generator import generate_audit_scenario
from src.env.audit_replay import ScenarioReplay, load_audit_actions
from src.env.audit_validation import validate_scenario
from src.env.audit_visualization import generate_audit_figures


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate the deterministic scenario-v2 audit package."
    )
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--audit-actions",
        type=Path,
        default=Path("configs/audit_policy_seed_18427.yaml"),
        help="Separate scripted audit-policy action fixture.",
    )
    parser.add_argument("--time-hours", type=float, default=4.2)
    return parser


def main() -> int:
    args = _parser().parse_args()
    scenario = generate_audit_scenario(args.seed, config_path=args.config)
    actions = load_audit_actions(args.audit_actions)
    if int(actions.get("scenario_seed", -1)) != args.seed:
        raise ValueError(
            f"Audit action seed {actions.get('scenario_seed')} does not match "
            f"scenario seed {args.seed}"
        )
    write_data_artifacts(scenario, args.output, actions)
    replay = ScenarioReplay(scenario, actions)
    validate_scenario(scenario, actions)
    figures = generate_audit_figures(
        scenario, replay, args.output, args.time_hours * 3600.0
    )
    missing_figures = [str(path) for path in figures if not path.is_file()]
    if missing_figures:
        raise RuntimeError(f"Mandatory figures were not generated: {missing_figures}")
    report = validate_scenario(
        scenario, actions, required_figure_names=MANDATORY_FIGURES
    )
    write_validation_report(args.output, report)
    expected = DATA_ARTIFACTS + MANDATORY_FIGURES
    missing = [name for name in expected if not (args.output / name).is_file()]
    if missing:
        raise RuntimeError(f"Audit package is incomplete: {missing}")
    print(f"scenario_hash={scenario.content_hash()}")
    print(f"output={args.output.resolve()}")
    print(f"artifacts={len(expected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
