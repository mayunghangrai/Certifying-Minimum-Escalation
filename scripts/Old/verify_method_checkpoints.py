"""Reload smoke checkpoints twice and verify deterministic fixed-seed outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agents.mappo_agent import MAPPOAgent  # noqa: E402
from env.params import EnvParams  # noqa: E402
from env.scenario_generator import generate_scenario  # noqa: E402
from env.uav_env import UAMTVRPIUEnv  # noqa: E402
from scripts.train_mappo import DEFAULT_AGENT_CONFIG  # noqa: E402


RELATIVE = {
    "vanilla_mappo": "vanilla/models/vanilla_mappo.pt",
    "graph_mappo": "graph/models/graph_mappo.pt",
    "graph_mappo_fixed_alns": (
        "fixed/models/graph_mappo_fixed_alns.pt"
    ),
    "graph_mappo_adaptive_alns": (
        "adaptive/models/graph_mappo_adaptive_alns.pt"
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(root: Path) -> dict:
    params = EnvParams()
    params.mission.T = 1.0
    params.hybrid.alns_iterations = 10
    env = UAMTVRPIUEnv(params)
    obs, info = env.reset(scenario=generate_scenario(18428, params))
    global_state = env.get_global_state()
    graph = env.get_operational_belief_graph()
    results = {}
    for mode, relative in RELATIVE.items():
        path = root / relative
        if not path.exists():
            raise FileNotFoundError(path)
        config = {
            **DEFAULT_AGENT_CONFIG,
            "gamma_hour": params.mission.gamma_hour,
            "device": "cpu",
            "method_mode": mode,
        }
        agents = [
            MAPPOAgent(env.M, env.obs_dims, env.n_actions, config)
            for _ in range(2)
        ]
        outputs = []
        for agent in agents:
            agent.load(path)
            agent.set_eval()
            outputs.append(
                agent.select_actions(
                    obs,
                    info["masks"],
                    global_state,
                    deterministic=True,
                    graph=(graph if mode != "vanilla_mappo" else None),
                )
            )
        if outputs[0][0] != outputs[1][0]:
            raise AssertionError(f"{mode}: deterministic actions differ")
        if not np.isclose(outputs[0][2], outputs[1][2], atol=1e-8, rtol=0):
            raise AssertionError(f"{mode}: deterministic values differ")
        for uav in outputs[0][1]:
            if not np.isclose(
                outputs[0][1][uav], outputs[1][1][uav], atol=1e-8, rtol=0
            ):
                raise AssertionError(f"{mode}: deterministic log-probs differ")
        try:
            payload = torch.load(path, map_location="cpu", weights_only=False)
        except TypeError:
            payload = torch.load(path, map_location="cpu")
        results[mode] = {
            "passed": True,
            "checkpoint": str(path),
            "checkpoint_sha256": _sha256(path),
            "model_version": payload.get("model_version", 1),
            "saved_mode": payload.get("method_mode", "vanilla_mappo"),
            "actions": outputs[0][0],
            "value": outputs[0][2],
        }
    return {"passed": True, "fixed_scenario_seed": 18428, "modes": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path("results/method_smoke")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "results/method_smoke/checkpoint_reload_verification.json"
        ),
    )
    args = parser.parse_args()
    result = verify(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"verification -> {args.output}")


if __name__ == "__main__":
    main()
