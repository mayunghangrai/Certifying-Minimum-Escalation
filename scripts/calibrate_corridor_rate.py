"""Calibrate the corridor-closure rate for a sparse closure model (item 3).

Closures are fully determined at scenario generation, so no episodes are
simulated: for each candidate ``avail_closure_rate`` the script generates
scenarios for the requested seeds and reports the per-episode closure
count distribution plus which edges close.

Example
-------
    python scripts/calibrate_corridor_rate.py \
        --config configs/env/event_causal_hard.yaml \
        --seed-start 200 --n-seeds 10
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from env.params import EnvParams  # noqa: E402
from env.scenario_generator import generate_scenario  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=str, required=True)
    parser.add_argument("--seed-start", type=int, default=200)
    parser.add_argument("--n-seeds", type=int, default=10)
    parser.add_argument(
        "--rates",
        type=float,
        nargs="*",
        default=[0.001, 0.002, 0.003, 0.004, 0.005, 0.006],
    )
    parser.add_argument(
        "--target-lo", type=float, default=3.0,
        help="Lower bound of the target mean-closures band.",
    )
    parser.add_argument(
        "--target-hi", type=float, default=6.0,
        help="Upper bound of the target mean-closures band.",
    )
    args = parser.parse_args()

    seeds = list(range(args.seed_start, args.seed_start + args.n_seeds))
    base = EnvParams.from_yaml(args.config)

    print(
        f"Corridor-closure calibration: {len(seeds)} seeds, "
        f"target mean closures/episode in "
        f"[{args.target_lo:.1f}, {args.target_hi:.1f}]"
    )
    print(
        f"{'rate':>8} {'mean':>6} {'min':>5} {'max':>5} "
        f"{'p10':>6} {'p90':>6}  in-band?"
    )
    for rate in args.rates:
        base.events.avail_closure_rate = float(rate)
        counts = []
        edge_counter: Counter = Counter()
        for seed in seeds:
            scenario = generate_scenario(seed, base)
            closures = [
                a for a in scenario.avail_changes if not a.available
            ]
            counts.append(len(closures))
            for a in closures:
                edge_counter[(a.i, a.j)] += 1
        arr = np.asarray(counts, dtype=float)
        mean = float(arr.mean())
        in_band = args.target_lo <= mean <= args.target_hi
        print(
            f"{rate:8.4f} {mean:6.2f} {int(arr.min()):5d} "
            f"{int(arr.max()):5d} "
            f"{float(np.percentile(arr, 10)):6.2f} "
            f"{float(np.percentile(arr, 90)):6.2f}  "
            f"{'YES' if in_band else 'no'}"
        )
        if in_band and edge_counter:
            top = ", ".join(
                f"{i}-{j}:{c}" for (i, j), c in edge_counter.most_common(5)
            )
            print(f"        most-closed edges: {top}")

    print(
        "\nPick the smallest rate whose mean lies in the target band and "
        "set it as avail_closure_rate in the corridor env config."
    )


if __name__ == "__main__":
    main()
