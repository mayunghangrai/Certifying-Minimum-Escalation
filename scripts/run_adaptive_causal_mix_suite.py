"""Run adaptive causal-mix development or final families sequentially."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


FAMILIES = {
    "standard": "configs/env/standard.yaml",
    "info_obsolescence": "configs/env/info_obsolescence.yaml",
    "corridor_disruption": "configs/env/corridor_disruption.yaml",
    "mixed_info_disruption": "configs/env/mixed_info_disruption.yaml",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("screen", "confirm", "final"), required=True,
    )
    parser.add_argument("--seed-start", type=int, required=True)
    parser.add_argument("--n-seeds", type=int, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--method-config",
        type=Path,
        default=Path(
            "configs/method/adaptive_causal_mix_development.yaml"
        ),
    )
    parser.add_argument(
        "--families",
        nargs="+",
        choices=tuple(FAMILIES),
        default=list(FAMILIES),
    )
    parser.add_argument("--selected-decay", type=float, default=None)
    parser.add_argument(
        "--selected-min-probability", type=float, default=None,
    )
    args = parser.parse_args()

    args.output_root.mkdir(parents=True, exist_ok=True)
    for index, family in enumerate(args.families, start=1):
        command = [
            sys.executable,
            "-u",
            "scripts/run_adaptive_causal_mix_experiment.py",
            "--config",
            FAMILIES[family],
            "--method-config",
            str(args.method_config),
            "--mode",
            args.mode,
            "--seed-start",
            str(args.seed_start),
            "--n-seeds",
            str(args.n_seeds),
            "--output-dir",
            str(args.output_root / family),
        ]
        if args.selected_decay is not None:
            command.extend(["--selected-decay", str(args.selected_decay)])
        if args.selected_min_probability is not None:
            command.extend([
                "--selected-min-probability",
                str(args.selected_min_probability),
            ])
        print(
            f"\n=== {args.mode} family {index}/{len(args.families)}: "
            f"{family} ===",
            flush=True,
        )
        print(" ".join(command), flush=True)
        subprocess.run(command, check=True)
    print(f"\nAdaptive causal-mix {args.mode} suite complete.", flush=True)


if __name__ == "__main__":
    main()
