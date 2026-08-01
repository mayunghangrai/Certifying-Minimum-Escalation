"""Replay and re-audit a serialized deterministic scenario-v2 package."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.env.audit_artifacts import MANDATORY_FIGURES, write_validation_report
from src.env.audit_model import AuditScenario
from src.env.audit_replay import ScenarioReplay, load_audit_actions
from src.env.audit_validation import validate_scenario
from src.env.audit_visualization import generate_audit_figures


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay, validate, and regenerate scenario-v2 audit figures."
    )
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument(
        "--audit-actions",
        type=Path,
        help="Defaults to audit_actions.json beside the scenario.",
    )
    parser.add_argument("--time-hours", type=float, default=4.2)
    return parser


def main() -> int:
    args = _parser().parse_args()
    scenario = AuditScenario.from_json(args.scenario)
    actions_path = args.audit_actions or args.scenario.with_name("audit_actions.json")
    actions = load_audit_actions(actions_path)
    if int(actions.get("scenario_seed", -1)) != scenario.metadata["master_seed"]:
        raise ValueError("Audit-policy actions do not belong to this scenario seed")
    replay = ScenarioReplay(scenario, actions)
    report = validate_scenario(scenario, actions)
    figures = generate_audit_figures(
        scenario, replay, args.scenario.parent, args.time_hours * 3600.0
    )
    missing = [str(path) for path in figures if not path.is_file()]
    if missing:
        raise RuntimeError(f"Mandatory figures were not generated: {missing}")
    report = validate_scenario(
        scenario, actions, required_figure_names=MANDATORY_FIGURES
    )
    write_validation_report(args.scenario.parent, report)
    print(f"scenario_hash={scenario.content_hash()}")
    print(f"audit_output={args.scenario.parent.resolve()}")
    print(f"figures={len(figures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
