"""Run the deterministic three-stage adaptive-gate diagnostic protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import sys

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
# Threaded BLAS reductions can differ by a few low-order bits across fresh
# processes.  Those differences are enough to alter a later categorical draw,
# so the diagnostic protocol deliberately uses a single deterministic CPU
# reduction order.
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import numpy as np
import torch
import yaml

torch.set_num_threads(1)
torch.set_num_interop_threads(1)
torch.use_deterministic_algorithms(True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agents.mappo_agent import MAPPOAgent  # noqa: E402
from env.params import EnvParams  # noqa: E402
from env.scenario_generator import generate_scenario  # noqa: E402
from env.uav_env import UAMTVRPIUEnv  # noqa: E402
from methods.adaptive_gate_diagnostics import (  # noqa: E402
    AdaptiveGateDiagnostics,
    assert_truth_exclusion,
    build_decision_diagnostic,
    evaluate_controlled_probes,
)
from scripts.train_mappo import DEFAULT_AGENT_CONFIG, load_agent_config  # noqa: E402


DEFAULT_PROTOCOL = {
    "short_mission_horizon_hours": 1.0,
    "short_alns_iterations": 10,
    "training_seed_count": 5,
}


def _checkpoint_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rng_snapshot():
    return {
        "python": random.getstate(),
        "numpy": np.random.get_state(),
        "torch": torch.random.get_rng_state().clone(),
    }


def _rng_restore(state):
    random.setstate(state["python"])
    np.random.set_state(state["numpy"])
    torch.random.set_rng_state(state["torch"])


def _identity_forward_audit(agent, env, obs, info, graph) -> dict:
    state = _rng_snapshot()
    first = agent.select_actions(
        obs,
        info["masks"],
        env.get_global_state(),
        deterministic=False,
        graph=graph,
        diagnostics_enabled=False,
    )
    first_detail = {
        u: {
            "gate": agent.last_diagnostics[u]["gate"],
            "gate_logit": agent.last_diagnostics[u]["gate_logit"],
            "gate_adaptive": agent.last_diagnostics[u]["gate_adaptive"],
        }
        for u in obs
    }
    _rng_restore(state)
    second = agent.select_actions(
        obs,
        info["masks"],
        env.get_global_state(),
        deterministic=False,
        graph=graph,
        diagnostics_enabled=True,
    )
    second_detail = {
        u: {
            "gate": agent.last_diagnostics[u]["gate"],
            "gate_logit": agent.last_diagnostics[u]["gate_logit"],
            "gate_adaptive": agent.last_diagnostics[u]["gate_adaptive"],
        }
        for u in obs
    }
    passed = (
        first[0] == second[0]
        and first[1] == second[1]
        and first[2] == second[2]
        and first_detail == second_detail
    )
    if not passed:
        raise AssertionError("Diagnostics-on/off forward identity failed")
    return {
        "passed": True,
        "actions_identical": True,
        "log_probabilities_identical": True,
        "values_identical": True,
        "gate_tensors_identical": True,
        "additional_rng_draws": 0,
    }


def _collect_episode(
    *,
    env,
    scenario,
    agent,
    collector,
    run_id: str,
    master_seed: int,
    training_seed: int | str,
    evaluation_seed: int | str,
    episode: int,
    phase: str,
    deterministic: bool,
    checkpoint_identifier: str,
    decision_counter: list[int],
    train: bool,
):
    obs, info = env.reset(scenario=scenario)
    if train:
        agent.begin_episode()
    step = 0
    while not env.done and step < 6000:
        graph = env.get_operational_belief_graph()
        actions, log_probs, value = agent.select_actions(
            obs,
            info["masks"],
            env.get_global_state(),
            deterministic=deterministic,
            graph=graph,
            diagnostics_enabled=True,
        )
        for uav_id in sorted(obs):
            context = {
                "run_id": run_id,
                "mode": agent.method_mode,
                "master_seed": master_seed,
                "training_seed": training_seed,
                "evaluation_seed": evaluation_seed,
                "episode": episode,
                "environment_step": step,
                "decision_index": decision_counter[0],
                "decision_time": float(env.t),
                "checkpoint_identifier": checkpoint_identifier,
                "phase": phase,
                "selection_mode": (
                    "deterministic" if deterministic else "stochastic"
                ),
            }
            row, counterfactual, vectors = build_decision_diagnostic(
                detail=agent.last_diagnostics[uav_id],
                graph=graph,
                env=env,
                uav_id=uav_id,
                context=context,
            )
            assert_truth_exclusion(row)
            collector.record_decision(row, counterfactual, vectors)
            decision_counter[0] += 1
        if train:
            agent.record_decisions(
                env.t,
                obs,
                info["masks"],
                env.get_global_state(),
                actions,
                log_probs,
                value,
                graph=graph,
            )
        interval_start = env.t
        obs, reward, _, info = env.step(actions)
        if train:
            agent.record_reward(reward, interval_start)
        step += 1
    if train:
        agent.end_episode(env.t)
    return step


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent-config",
        default="configs/agent/belief_graph_guided.yaml",
    )
    parser.add_argument("--seed", type=int, default=18427)
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/adaptive_gate_diagnostics"),
    )
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--fixed-gate", type=float)
    parser.add_argument("--beta", type=float)
    parser.add_argument("--evaluation-seeds", type=int, nargs="+", default=[100, 2026])
    parser.add_argument("--deterministic-eval", action="store_true", default=True)
    parser.add_argument("--save-full-vectors", action="store_true", default=True)
    parser.add_argument("--controlled-probes", action="store_true", default=True)
    parser.add_argument("--diagnostic-config", type=Path)
    parser.add_argument("--device", default="cpu")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.episodes < 1:
        raise ValueError("--episodes must be positive")
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    diagnostic_overrides = {}
    protocol = dict(DEFAULT_PROTOCOL)
    if args.diagnostic_config:
        payload = yaml.safe_load(
            args.diagnostic_config.read_text(encoding="utf-8")
        ) or {}
        diagnostic_overrides = payload.get("thresholds", payload)
        protocol.update(payload.get("protocol", {}))
    collector = AdaptiveGateDiagnostics(diagnostic_overrides)

    loaded_config, inferred_mode = load_agent_config(args.agent_config)
    mode = inferred_mode or "graph_mappo_adaptive_alns"
    if mode != "graph_mappo_adaptive_alns":
        raise ValueError("Diagnostic training requires adaptive guidance mode")
    if args.fixed_gate is not None:
        loaded_config["fixed_guidance_gate"] = args.fixed_gate
    if args.beta is not None:
        loaded_config["guidance_beta"] = args.beta

    params = EnvParams()
    params.mission.T = float(protocol["short_mission_horizon_hours"])
    params.hybrid.alns_iterations = int(protocol["short_alns_iterations"])
    env = UAMTVRPIUEnv(params)
    probe_scenario = generate_scenario(args.seed, params)
    probe_obs, probe_info = env.reset(scenario=probe_scenario)
    config = {
        **DEFAULT_AGENT_CONFIG,
        **loaded_config,
        "gamma_hour": params.mission.gamma_hour,
        "device": args.device,
        "method_mode": mode,
    }
    agent = MAPPOAgent(env.M, env.obs_dims, env.n_actions, config)
    initial_untrained_state = {
        key: value.detach().clone()
        for key, value in agent.actor.state_dict().items()
    }
    if args.controlled_probes:
        collector.record_probes(
            evaluate_controlled_probes(agent.actor, "initial_untrained")
        )
    if args.checkpoint:
        agent.load(args.checkpoint)
        if args.controlled_probes:
            collector.record_probes(
                evaluate_controlled_probes(agent.actor, "supplied_checkpoint")
            )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = args.output_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    initial_path = checkpoint_dir / "initial.pt"
    agent.save(initial_path)

    graph = env.get_operational_belief_graph()
    identity = _identity_forward_audit(
        agent, env, probe_obs, probe_info, graph
    )
    run_id = f"adaptive_gate_seed{args.seed}_episodes{args.episodes}"
    decision_counter = [0]
    training_seeds = [
        args.seed + 1 + index
        for index in range(int(protocol["training_seed_count"]))
    ]
    for episode in range(1, args.episodes + 1):
        scenario_seed = training_seeds[(episode - 1) % len(training_seeds)]
        scenario = generate_scenario(scenario_seed, params)
        agent.set_train()
        _collect_episode(
            env=env,
            scenario=scenario,
            agent=agent,
            collector=collector,
            run_id=run_id,
            master_seed=args.seed,
            training_seed=scenario_seed,
            evaluation_seed="",
            episode=episode,
            phase="training",
            deterministic=False,
            checkpoint_identifier=f"after_update_{episode - 1}",
            decision_counter=decision_counter,
            train=True,
        )
        agent.update(
            collector,
            {
                "run_id": run_id,
                "mode": mode,
                "episode": episode,
                "phase": "training",
            },
        )

    final_path = checkpoint_dir / "final.pt"
    agent.save(final_path)
    if args.controlled_probes:
        collector.record_probes(
            evaluate_controlled_probes(agent.actor, "final_trained")
        )

    agent.set_eval()
    for evaluation_index, evaluation_seed in enumerate(args.evaluation_seeds, 1):
        scenario = generate_scenario(evaluation_seed, params)
        _collect_episode(
            env=env,
            scenario=scenario,
            agent=agent,
            collector=collector,
            run_id=run_id,
            master_seed=args.seed,
            training_seed="",
            evaluation_seed=evaluation_seed,
            episode=evaluation_index,
            phase="evaluation",
            deterministic=bool(args.deterministic_eval),
            checkpoint_identifier="final",
            decision_counter=decision_counter,
            train=False,
        )

    metadata = {
        "run_id": run_id,
        "method": "Belief-Graph Guided MAPPO-ALNS adaptive-gate diagnostics",
        "master_seed": args.seed,
        "episodes": args.episodes,
        "training_seeds": training_seeds,
        "evaluation_seeds": args.evaluation_seeds,
        "mode": mode,
        "fixed_gate": float(agent.actor.fixed_gate),
        "beta": float(agent.actor.beta),
        "gate_hidden_dim": int(
            agent.actor.guidance_gate.network[0].out_features
        ),
        "plan_feature_count": 10,
        "protocol": protocol,
        "configuration_overrides": {
            "short_mission_horizon_hours": protocol[
                "short_mission_horizon_hours"
            ],
            "short_alns_iterations": protocol["short_alns_iterations"],
            "fixed_gate": args.fixed_gate,
            "beta": args.beta,
            "diagnostic_config": (
                str(args.diagnostic_config) if args.diagnostic_config else None
            ),
        },
        "forward_identity_audit": identity,
        "decision_count": len(collector.decision_rows),
        "ppo_update_count": len(collector.update_rows),
        "initial_checkpoint_sha256": _checkpoint_hash(initial_path),
        "final_checkpoint_sha256": _checkpoint_hash(final_path),
        "checkpoint_supplied": str(args.checkpoint) if args.checkpoint else None,
        "truth_exclusion": "operational tensors only",
        "performance_claim": "none",
    }
    assert_truth_exclusion(metadata)
    diagnosis = collector.write(
        args.output_dir,
        metadata,
        save_full_vectors=bool(args.save_full_vectors),
    )
    print(json.dumps(diagnosis, indent=2, sort_keys=True))
    print(f"diagnostics -> {args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
