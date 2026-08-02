"""Run the locked four-family event-causal experiment suite sequentially.

Sequential execution avoids cross-process CPU contention in solver-time
comparisons. Each family writes its own resolved configuration, provenance,
diagnostics, paired metrics, and figures through the canonical runner.
"""

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
    parser.add_argument("--seed-start", type=int, default=500)
    parser.add_argument("--n-seeds", type=int, default=40)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("results/event_causal_repair_locked_500_539"),
    )
    parser.add_argument(
        "--families",
        nargs="*",
        choices=tuple(FAMILIES),
        default=list(FAMILIES),
    )
    parser.add_argument(
        "--matched-periodic-target-count", type=int, default=18,
    )
    args = parser.parse_args()

    args.output_root.mkdir(parents=True, exist_ok=True)
    for index, family in enumerate(args.families, start=1):
        output_dir = args.output_root / family
        command = [
            sys.executable,
            "-u",
            "scripts/run_event_causal_repair_experiment.py",
            "--config",
            FAMILIES[family],
            "--method-config",
            "configs/method/event_causal_repair.yaml",
            "--seed-start",
            str(args.seed_start),
            "--n-seeds",
            str(args.n_seeds),
            "--output-dir",
            str(output_dir),
            "--matched-periodic-target-count",
            str(args.matched_periodic_target_count),
            "--include-trigger-ablations",
            "--skip-threshold-sensitivity",
            "--plot",
        ]
        print(
            f"\n=== family {index}/{len(args.families)}: {family} ===",
            flush=True,
        )
        print(" ".join(command), flush=True)
        subprocess.run(command, check=True)

    print("\nLocked event-causal suite complete.", flush=True)


if __name__ == "__main__":
    main()
