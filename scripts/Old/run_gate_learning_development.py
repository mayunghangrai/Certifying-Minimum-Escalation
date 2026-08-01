"""Run the controlled three-branch adaptive-gate development experiment."""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sys
import time
from typing import Dict, Iterable, Mapping, Sequence

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import numpy as np
import torch
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agents.mappo_agent import MAPPOAgent  # noqa: E402
from env.events import Event, EventType  # noqa: E402
from env.params import EnvParams  # noqa: E402
from env.scenario_generator import generate_scenario  # noqa: E402
from env.uav_env import UAMTVRPIUEnv  # noqa: E402
from methods.adaptive_gate_diagnostics import counterfactual_policy  # noqa: E402
from methods.belief_graph import (  # noqa: E402
    NORMALIZATION_REFERENCES,
    PLAN_FEATURE_NAMES,
)
from methods.gate_learning_development import (  # noqa: E402
    REGIME_FIXTURE_VERSION,
    REGIMES,
    TRAINING_SEEDS,
    VALIDATION_SEEDS,
    assert_regime_coverage,
    build_regime_intervention,
    classify_operational_regime,
    development_seed_split,
    episode_assignments,
    file_sha256,
    regime_intervention_manifest,
    regime_intervention_time,
    validation_assignments,
)
from scripts.train_mappo import (  # noqa: E402
    DEFAULT_AGENT_CONFIG,
    load_agent_config,
)


MODES = (
    "graph_mappo",
    "graph_mappo_fixed_alns",
    "graph_mappo_adaptive_alns",
)

DECISION_FIELDS = (
    "branch",
    "phase",
    "checkpoint_episode",
    "episode",
    "scenario_seed",
    "target_regime",
    "regime_fixture_version",
    "environment_step",
    "decision_index",
    "decision_time_h",
    "uav_id",
    "selected_action",
    "recommended_action",
    "recommended_action_feasible",
    "recommended_action_masked",
    "prior_nonzero",
    "prior_nonzero_count",
    "gate_production",
    "gate_adaptive",
    "gate_fixed",
    "gate_logit",
    "abs_gate_minus_fixed",
    "followed_alns",
    "regime",
    "regime_label_in_policy_input",
    *PLAN_FEATURE_NAMES,
)

TRAINING_FIELDS = (
    "branch",
    "episode",
    "scenario_seed",
    "target_regime",
    "reward",
    "J_dep_true",
    "J_dep_belief",
    "J_energy",
    "J_risk",
    "fill_rate",
    "n_resolves",
    "termination",
    "environment_decisions",
    "prior_bearing_decisions",
    "prior_coverage",
    "guided_mask_rate",
    "follow_rate",
    "gate_mean",
    "gate_standard_deviation",
    "gate_minimum",
    "gate_maximum",
    "gate_below_005_fraction",
    "gate_above_095_fraction",
    "mean_abs_gate_minus_fixed",
    "actor_loss",
    "critic_loss",
    "feasibility_violations",
    "episode_duration_h",
    "computational_time_s",
)

EVALUATION_FIELDS = (
    "branch",
    "checkpoint_episode",
    "guidance_beta",
    "fixed_gate",
    "validation_seed_count",
    "environment_decisions",
    "prior_bearing_decisions",
    "production_gate_mean",
    "effective_guidance_scale_mean",
    "gate_mean",
    "gate_standard_deviation",
    "gate_minimum",
    "gate_maximum",
    "gate_below_005_fraction",
    "gate_above_095_fraction",
    "mean_abs_gate_minus_fixed",
    "gate_gradient_norm",
    "gate_parameter_update_norm",
    "prior_coverage",
    "guided_mask_rate",
    "adaptive_fixed_kl",
    "adaptive_fixed_tv",
    "adaptive_fixed_argmax_difference_rate",
    "adaptive_unguided_argmax_difference_rate",
    "counterfactual_unguided_alns_follow_rate",
    "counterfactual_fixed_alns_follow_rate",
    "counterfactual_adaptive_alns_follow_rate",
    "alns_follow_rate",
    "cumulative_reward",
    "mean_true_deprivation_cost",
    "feasibility_violations",
    "mean_fill_rate",
    "mean_episode_duration_h",
    "computational_time_s",
)


class _UpdateCollector:
    def __init__(self):
        self.rows = []

    def record_update(self, row):
        self.rows.append(dict(row))


def _canonical_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_yaml(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=True),
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]], fields) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _append_csv(path: Path, rows: Iterable[Mapping[str, object]], fields) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def _state_hash(value) -> str:
    digest = hashlib.sha256()

    def update(item):
        if torch.is_tensor(item):
            array = item.detach().cpu().contiguous().numpy()
            digest.update(b"tensor")
            digest.update(str(array.dtype).encode())
            digest.update(str(array.shape).encode())
            digest.update(array.tobytes())
        elif isinstance(item, np.ndarray):
            digest.update(b"ndarray")
            digest.update(str(item.dtype).encode())
            digest.update(str(item.shape).encode())
            digest.update(np.ascontiguousarray(item).tobytes())
        elif isinstance(item, Mapping):
            digest.update(b"mapping")
            for key in sorted(item, key=lambda current: str(current)):
                update(str(key))
                update(item[key])
        elif isinstance(item, (list, tuple)):
            digest.update(b"sequence")
            for child in item:
                update(child)
        else:
            digest.update(repr(item).encode("utf-8"))

    update(value)
    return digest.hexdigest()


def _rng_state() -> dict:
    return {
        "python": random.getstate(),
        "numpy": np.random.get_state(),
        "torch": torch.random.get_rng_state(),
        "cuda": (
            torch.cuda.get_rng_state_all() if torch.cuda.is_available() else []
        ),
    }


def _restore_rng(payload: Mapping[str, object]) -> None:
    random.setstate(payload["python"])
    np.random.set_state(payload["numpy"])
    torch.random.set_rng_state(payload["torch"])
    if torch.cuda.is_available() and payload.get("cuda"):
        torch.cuda.set_rng_state_all(payload["cuda"])


def _save_progress(
    agent: MAPPOAgent,
    directory: Path,
    episode: int,
    stopping_reason: str = "in_progress",
) -> None:
    checkpoint = directory / "checkpoints" / "latest.pt"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    agent.save(checkpoint)
    torch.save(_rng_state(), directory / "checkpoints" / "rng_state.pt")
    _canonical_write_json(
        directory / "progress.json",
        {
            "episode_completed": episode,
            "stopping_reason": stopping_reason,
            "checkpoint": "checkpoints/latest.pt",
        },
    )


def _make_agent(env, config: Mapping[str, object], mode: str) -> MAPPOAgent:
    return MAPPOAgent(
        env.M,
        env.obs_dims,
        env.n_actions,
        {**config, "method_mode": mode},
    )


def _copy_initialization(source: MAPPOAgent, target: MAPPOAgent) -> None:
    target.actor.load_state_dict(copy.deepcopy(source.actor.state_dict()))
    target.critic.load_state_dict(copy.deepcopy(source.critic.state_dict()))
    target.actor_optimizer.load_state_dict(
        copy.deepcopy(source.actor_optimizer.state_dict())
    )
    target.critic_optimizer.load_state_dict(
        copy.deepcopy(source.critic_optimizer.state_dict())
    )


def _component_hashes(agent: MAPPOAgent) -> Dict[str, str]:
    return {
        "actor": _state_hash(agent.actor.state_dict()),
        "actor_graph_encoder": _state_hash(
            agent.actor.graph_encoder.state_dict()
        ),
        "critic": _state_hash(agent.critic.state_dict()),
        "critic_graph_encoder": _state_hash(
            agent.critic.graph_encoder.state_dict()
        ),
        "actor_optimizer": _state_hash(agent.actor_optimizer.state_dict()),
        "critic_optimizer": _state_hash(agent.critic_optimizer.state_dict()),
        "normalization": _state_hash(NORMALIZATION_REFERENCES),
    }


def _decision_row(
    *,
    branch: str,
    phase: str,
    checkpoint_episode: int,
    episode: int,
    scenario_seed: int,
    target_regime: str,
    step: int,
    decision_index: int,
    env,
    uav_id: int,
    action: int,
    mask,
    detail,
) -> Dict[str, object]:
    features = np.asarray(detail["plan_features"], dtype=float)
    prior = np.asarray(detail["alns_prior"], dtype=float)
    recommended = int(detail["recommended_action"])
    feasible = 0 <= recommended < len(mask) and bool(mask[recommended])
    row = {
        "branch": branch,
        "phase": phase,
        "checkpoint_episode": checkpoint_episode,
        "episode": episode,
        "scenario_seed": scenario_seed,
        "target_regime": target_regime,
        "regime_fixture_version": (
            REGIME_FIXTURE_VERSION if target_regime in REGIMES else ""
        ),
        "environment_step": step,
        "decision_index": decision_index,
        "decision_time_h": float(env.t),
        "uav_id": uav_id,
        "selected_action": action,
        "recommended_action": recommended,
        "recommended_action_feasible": int(feasible),
        "recommended_action_masked": int(recommended >= 0 and not feasible),
        "prior_nonzero": int(np.any(prior > 0)),
        "prior_nonzero_count": int(np.count_nonzero(prior)),
        "gate_production": float(detail["gate"]),
        "gate_adaptive": float(detail["gate_adaptive"]),
        "gate_fixed": float(detail["gate_fixed"]),
        "gate_logit": float(detail["gate_logit"]),
        "abs_gate_minus_fixed": abs(
            float(detail["gate_adaptive"]) - float(detail["gate_fixed"])
        ),
        "followed_alns": int(recommended >= 0 and action == recommended),
        "regime_label_in_policy_input": 0,
        **{
            name: float(features[index])
            for index, name in enumerate(PLAN_FEATURE_NAMES)
        },
    }
    row["regime"] = classify_operational_regime(row, target_regime)
    return row


def _rebuild_current_decision(env, obs, info):
    """Rebuild observations/masks after a policy-independent fixture refresh."""
    deciders = sorted(obs)
    rebuilt_obs = {u: env._build_obs(u) for u in deciders}
    masks = {u: env._action_mask(u) for u in deciders}
    env._action_mask_cache = masks
    return rebuilt_obs, {
        **info,
        "masks": masks,
        "deciders": deciders,
        "t": env.t,
    }


def _later_available_plan_leg(env):
    immediate = set()
    candidates = []
    for u in range(env.M):
        anchor = env._anchor_node(u)
        nxt = env.scaffold.peek_next(u)
        if nxt is not None:
            immediate.add((anchor, nxt.node))
        previous = anchor
        for sortie in env.scaffold.plans.get(u, []):
            for visit in sortie.visits:
                candidates.append((previous, visit.node))
                previous = visit.node
            if sortie.visits:
                candidates.append((previous, -1))
            previous = -1
    return next(
        (
            leg
            for leg in candidates
            if leg not in immediate
            and leg[0] != leg[1]
            and env.graph.A(*leg)
        ),
        None,
    )


def _refresh_regime_fixture(env, obs, info, target_regime, closure_seq):
    env.scaffold = env._solve_scaffold(initial=True)
    obs, info = _rebuild_current_decision(env, obs, info)
    if target_regime in {
        "PARTIALLY_INVALID_PLAN",
        "MIXED_OPERATIONAL_CHANGE",
    }:
        if closure_seq is not None:
            env.queue.cancel(closure_seq)
        leg = _later_available_plan_leg(env)
        if leg is not None:
            closure_seq = env.queue.push(
                Event(
                    regime_intervention_time(env.p),
                    EventType.AVAIL_CHANGE,
                    {"i": leg[0], "j": leg[1], "available": False},
                )
            )
    return obs, info, closure_seq


def _run_episode(
    *,
    env,
    scenario,
    agent,
    branch: str,
    phase: str,
    episode: int,
    checkpoint_episode: int,
    target_regime: str,
    train: bool,
    deterministic: bool,
    collect_vectors: bool = False,
    decision_start: int = 0,
):
    started = time.perf_counter()
    scenario = build_regime_intervention(scenario, target_regime, env.p)
    obs, info = env.reset(scenario=scenario)
    if train:
        agent.begin_episode()
    total_reward = 0.0
    rows = []
    vectors = []
    step = 0
    invalid_actions = 0
    closure_seq = None
    fixture_refreshed = False
    while not env.done and step < 6000:
        refresh_fixture = (
            target_regime == "FRESH_AND_STABLE"
            or (target_regime in REGIMES and not fixture_refreshed)
        )
        if refresh_fixture:
            obs, info, closure_seq = _refresh_regime_fixture(
                env, obs, info, target_regime, closure_seq
            )
            fixture_refreshed = True
        graph = env.get_operational_belief_graph()
        gstate = env.get_global_state()
        actions, log_probs, value = agent.select_actions(
            obs,
            info["masks"],
            gstate,
            deterministic=deterministic,
            graph=graph,
            diagnostics_enabled=collect_vectors,
        )
        for uav_id in sorted(obs):
            row = _decision_row(
                branch=branch,
                phase=phase,
                checkpoint_episode=checkpoint_episode,
                episode=episode,
                scenario_seed=scenario.seed,
                target_regime=target_regime,
                step=step,
                decision_index=decision_start + len(rows),
                env=env,
                uav_id=uav_id,
                action=actions[uav_id],
                mask=info["masks"][uav_id],
                detail=agent.last_diagnostics[uav_id],
            )
            rows.append(row)
            if not bool(info["masks"][uav_id][actions[uav_id]]):
                invalid_actions += 1
            if collect_vectors:
                detail = agent.last_diagnostics[uav_id]
                vectors.append(
                    {
                        "decision_index": row["decision_index"],
                        "scenario_seed": scenario.seed,
                        "target_regime": target_regime,
                        "regime": row["regime"],
                        "uav_id": uav_id,
                        "recommended_action": row["recommended_action"],
                        "plan_features": np.asarray(
                            detail["plan_features"], dtype=float
                        ).tolist(),
                        "base_logits": np.asarray(
                            detail["base_logits"], dtype=float
                        ).tolist(),
                        "alns_prior": np.asarray(
                            detail["alns_prior"], dtype=float
                        ).tolist(),
                        "action_mask": np.asarray(
                            detail["action_mask"], dtype=int
                        ).tolist(),
                    }
                )
        if train:
            agent.record_decisions(
                env.t,
                obs,
                info["masks"],
                gstate,
                actions,
                log_probs,
                value,
                graph=graph,
            )
        interval_start = env.t
        obs, reward, _, info = env.step(actions)
        if train:
            agent.record_reward(reward, interval_start)
        total_reward += reward
        step += 1
    if train:
        agent.end_episode(env.t)
    metrics = env.metrics.summary()
    metrics.update(
        {
            "reward": float(total_reward),
            "steps": step,
            "feasibility_violations": invalid_actions,
            "episode_duration_h": float(env.t),
            "computational_time_s": time.perf_counter() - started,
        }
    )
    return metrics, rows, vectors


def _aggregate_training_row(
    branch,
    episode,
    assignment,
    metrics,
    decisions,
    actor_loss,
    critic_loss,
):
    gates = np.asarray([row["gate_adaptive"] for row in decisions], dtype=float)
    prior = np.asarray([row["prior_nonzero"] for row in decisions], dtype=bool)
    masked = np.asarray(
        [row["recommended_action_masked"] for row in decisions], dtype=bool
    )
    followed = np.asarray([row["followed_alns"] for row in decisions], dtype=bool)
    return {
        "branch": branch,
        "episode": episode,
        "scenario_seed": assignment["scenario_seed"],
        "target_regime": assignment["target_regime"],
        "reward": metrics["reward"],
        "J_dep_true": metrics["J_dep_true"],
        "J_dep_belief": metrics["J_dep_belief"],
        "J_energy": metrics["J_energy"],
        "J_risk": metrics["J_risk"],
        "fill_rate": metrics["fill_rate"],
        "n_resolves": metrics["n_resolves"],
        "termination": metrics["termination_reason"],
        "environment_decisions": len(decisions),
        "prior_bearing_decisions": int(prior.sum()),
        "prior_coverage": float(prior.mean()) if len(prior) else 0.0,
        "guided_mask_rate": (
            float(masked[prior].mean()) if prior.any() else 0.0
        ),
        "follow_rate": (
            float(followed[prior].mean()) if prior.any() else 0.0
        ),
        "gate_mean": float(gates.mean()) if len(gates) else math.nan,
        "gate_standard_deviation": (
            float(gates.std()) if len(gates) else math.nan
        ),
        "gate_minimum": float(gates.min()) if len(gates) else math.nan,
        "gate_maximum": float(gates.max()) if len(gates) else math.nan,
        "gate_below_005_fraction": (
            float((gates < 0.05).mean()) if len(gates) else 0.0
        ),
        "gate_above_095_fraction": (
            float((gates > 0.95).mean()) if len(gates) else 0.0
        ),
        "mean_abs_gate_minus_fixed": (
            float(np.abs(gates - 0.5).mean()) if len(gates) else math.nan
        ),
        "actor_loss": actor_loss,
        "critic_loss": critic_loss,
        "feasibility_violations": metrics["feasibility_violations"],
        "episode_duration_h": metrics["episode_duration_h"],
        "computational_time_s": metrics["computational_time_s"],
    }


def _aggregate_evaluation(
    branch,
    checkpoint_episode,
    episode_metrics,
    decisions,
    vectors,
    last_updates,
    elapsed,
    *,
    guidance_beta,
    fixed_gate,
):
    gates = np.asarray([row["gate_adaptive"] for row in decisions], dtype=float)
    production_gates = np.asarray(
        [row["gate_production"] for row in decisions], dtype=float
    )
    prior = np.asarray([row["prior_nonzero"] for row in decisions], dtype=bool)
    masked = np.asarray(
        [row["recommended_action_masked"] for row in decisions], dtype=bool
    )
    followed = np.asarray([row["followed_alns"] for row in decisions], dtype=bool)
    fixed_kl = []
    fixed_tv = []
    fixed_argmax = []
    unguided_argmax = []
    counterfactual_unguided_follow = []
    counterfactual_fixed_follow = []
    counterfactual_adaptive_follow = []
    for row, vector in zip(decisions, vectors):
        result = counterfactual_policy(
            np.asarray(vector["base_logits"], dtype=float),
            np.asarray(vector["alns_prior"], dtype=float),
            np.asarray(vector["action_mask"], dtype=bool),
            float(row["gate_adaptive"]),
            float(fixed_gate),
            float(guidance_beta),
        )
        fixed_kl.append(result["kl_adaptive_fixed"])
        fixed_tv.append(result["tv_adaptive_fixed"])
        fixed_argmax.append(result["adaptive_argmax"] != result["fixed_argmax"])
        unguided_argmax.append(
            result["adaptive_argmax"] != result["unguided_argmax"]
        )
        if int(row["prior_nonzero"]) and int(
            row["recommended_action_feasible"]
        ):
            recommended = int(row["recommended_action"])
            counterfactual_unguided_follow.append(
                result["unguided_argmax"] == recommended
            )
            counterfactual_fixed_follow.append(
                result["fixed_argmax"] == recommended
            )
            counterfactual_adaptive_follow.append(
                result["adaptive_argmax"] == recommended
            )
    update = last_updates[-1] if last_updates else {}
    return {
        "branch": branch,
        "checkpoint_episode": checkpoint_episode,
        "guidance_beta": float(guidance_beta),
        "fixed_gate": float(fixed_gate),
        "validation_seed_count": len(VALIDATION_SEEDS),
        "environment_decisions": len(decisions),
        "prior_bearing_decisions": int(prior.sum()),
        "production_gate_mean": float(production_gates.mean()),
        "effective_guidance_scale_mean": float(
            guidance_beta * production_gates.mean()
        ),
        "gate_mean": float(gates.mean()),
        "gate_standard_deviation": float(gates.std()),
        "gate_minimum": float(gates.min()),
        "gate_maximum": float(gates.max()),
        "gate_below_005_fraction": float((gates < 0.05).mean()),
        "gate_above_095_fraction": float((gates > 0.95).mean()),
        "mean_abs_gate_minus_fixed": float(np.abs(gates - 0.5).mean()),
        "gate_gradient_norm": float(
            update.get("gate_gradient_l2_norm", 0.0)
        ),
        "gate_parameter_update_norm": float(
            update.get("gate_parameter_update_l2_distance", 0.0)
        ),
        "prior_coverage": float(prior.mean()),
        "guided_mask_rate": (
            float(masked[prior].mean()) if prior.any() else 0.0
        ),
        "adaptive_fixed_kl": float(np.mean(fixed_kl)),
        "adaptive_fixed_tv": float(np.mean(fixed_tv)),
        "adaptive_fixed_argmax_difference_rate": float(np.mean(fixed_argmax)),
        "adaptive_unguided_argmax_difference_rate": float(
            np.mean(unguided_argmax)
        ),
        "counterfactual_unguided_alns_follow_rate": (
            float(np.mean(counterfactual_unguided_follow))
            if counterfactual_unguided_follow
            else 0.0
        ),
        "counterfactual_fixed_alns_follow_rate": (
            float(np.mean(counterfactual_fixed_follow))
            if counterfactual_fixed_follow
            else 0.0
        ),
        "counterfactual_adaptive_alns_follow_rate": (
            float(np.mean(counterfactual_adaptive_follow))
            if counterfactual_adaptive_follow
            else 0.0
        ),
        "alns_follow_rate": (
            float(followed[prior].mean()) if prior.any() else 0.0
        ),
        "cumulative_reward": float(
            sum(item["reward"] for item in episode_metrics)
        ),
        "mean_true_deprivation_cost": float(
            np.mean([item["J_dep_true"] for item in episode_metrics])
        ),
        "feasibility_violations": int(
            sum(item["feasibility_violations"] for item in episode_metrics)
        ),
        "mean_fill_rate": float(
            np.mean([item["fill_rate"] for item in episode_metrics])
        ),
        "mean_episode_duration_h": float(
            np.mean([item["episode_duration_h"] for item in episode_metrics])
        ),
        "computational_time_s": elapsed,
    }


def _evaluate_checkpoint(
    env,
    agent,
    branch,
    checkpoint_episode,
    params,
    deterministic,
    last_updates,
):
    started = time.perf_counter()
    all_metrics = []
    all_rows = []
    all_vectors = []
    index = 0
    agent.set_eval()
    for assignment in validation_assignments():
        scenario = generate_scenario(assignment["scenario_seed"], params)
        metrics, rows, vectors = _run_episode(
            env=env,
            scenario=scenario,
            agent=agent,
            branch=branch,
            phase="checkpoint_validation",
            episode=assignment["validation_episode"],
            checkpoint_episode=checkpoint_episode,
            target_regime=assignment["target_regime"],
            train=False,
            deterministic=deterministic,
            collect_vectors=True,
            decision_start=index,
        )
        index += len(rows)
        all_metrics.append(metrics)
        all_rows.extend(rows)
        all_vectors.extend(vectors)
    return _aggregate_evaluation(
        branch,
        checkpoint_episode,
        all_metrics,
        all_rows,
        all_vectors,
        last_updates,
        time.perf_counter() - started,
        guidance_beta=float(agent.actor.beta),
        fixed_gate=float(agent.actor.fixed_gate),
    )


def _materialize_imported_baseline(
    *,
    directory: Path,
    agent: MAPPOAgent,
    env,
    params,
    deterministic_evaluation: bool,
) -> Path:
    """Persist and evaluate an imported unguided baseline without retraining."""
    directory.mkdir(parents=True, exist_ok=True)
    _save_progress(
        agent,
        directory,
        0,
        "imported_shared_initialization_no_retraining",
    )
    final_path = directory / "checkpoints" / "final.pt"
    agent.save(final_path)
    evaluation = _evaluate_checkpoint(
        env,
        agent,
        "graph_mappo",
        0,
        params,
        deterministic_evaluation,
        [],
    )
    _write_csv(
        directory / "evaluation_log.csv",
        [evaluation],
        EVALUATION_FIELDS,
    )
    return final_path


def _train_branch(
    *,
    root,
    env,
    params,
    agent,
    branch,
    assignments,
    start_episode,
    maximum_episode,
    evaluation_interval,
    checkpoint_interval,
    deterministic_evaluation,
    minimum_fresh_prior_training_decisions,
    resume,
):
    directory = root / {
        "graph_mappo": "graph_mappo",
        "graph_mappo_fixed_alns": "fixed_guidance",
        "graph_mappo_adaptive_alns": "adaptive_guidance",
    }[branch]
    directory.mkdir(parents=True, exist_ok=True)
    training_path = directory / "training_log.csv"
    decision_path = directory / "decision_log.csv"
    update_path = directory / "gate_update_log.csv"
    evaluation_path = directory / "evaluation_log.csv"
    update_collector = _UpdateCollector()
    decision_index = len(_read_csv(decision_path))
    last_updates = []
    for episode in range(start_episode, maximum_episode + 1):
        assignment = assignments[episode - 1]
        scenario = generate_scenario(assignment["scenario_seed"], params)
        agent.set_train()
        metrics, rows, _ = _run_episode(
            env=env,
            scenario=scenario,
            agent=agent,
            branch=branch,
            phase="training",
            episode=episode,
            checkpoint_episode=episode,
            target_regime=assignment["target_regime"],
            train=True,
            deterministic=False,
            decision_start=decision_index,
        )
        decision_index += len(rows)
        previous_update_count = len(update_collector.rows)
        actor_loss, critic_loss = agent.update(
            update_collector,
            {
                "branch": branch,
                "phase": "training",
                "episode": episode,
            },
        )
        new_updates = update_collector.rows[previous_update_count:]
        last_updates = new_updates
        training_row = _aggregate_training_row(
            branch,
            episode,
            assignment,
            metrics,
            rows,
            actor_loss,
            critic_loss,
        )
        _append_csv(training_path, [training_row], TRAINING_FIELDS)
        _append_csv(decision_path, rows, DECISION_FIELDS)
        if branch == "graph_mappo_adaptive_alns":
            fields = list(new_updates[0]) if new_updates else []
            if new_updates:
                _append_csv(update_path, new_updates, fields)
        if (
            episode % checkpoint_interval == 0
            or episode == maximum_episode
        ):
            checkpoint = directory / "checkpoints" / f"episode_{episode:04d}.pt"
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            agent.save(checkpoint)
            _save_progress(agent, directory, episode)
        if (
            episode % evaluation_interval == 0
            or episode == maximum_episode
        ):
            evaluation = _evaluate_checkpoint(
                env,
                agent,
                branch,
                episode,
                params,
                deterministic_evaluation,
                last_updates,
            )
            _append_csv(evaluation_path, [evaluation], EVALUATION_FIELDS)
            print(
                f"{branch} episode {episode}: "
                f"prior={evaluation['prior_coverage']:.3f} "
                f"production_gate={evaluation['production_gate_mean']:.3f} "
                f"gate={evaluation['gate_mean']:.3f}±"
                f"{evaluation['gate_standard_deviation']:.3f} "
                f"TV(a,f)={evaluation['adaptive_fixed_tv']:.6f}",
                flush=True,
            )
        elif episode == 1 or episode % 10 == 0:
            print(
                f"{branch} episode {episode}: "
                f"reward={training_row['reward']:.1f} "
                f"prior={training_row['prior_coverage']:.3f}",
                flush=True,
            )
    _save_progress(
        agent,
        directory,
        maximum_episode,
        "planned_episode_limit_reached",
    )
    training_decisions = [
        row
        for row in _read_csv(decision_path)
        if row.get("phase") == "training"
    ]
    assigned_regimes = {
        str(row["target_regime"])
        for row in assignments[:maximum_episode]
    }
    assert_regime_coverage(
        training_decisions,
        {
            "FRESH_AND_STABLE": int(
                minimum_fresh_prior_training_decisions
            ),
            **{
                regime: 1
                for regime in REGIMES[1:]
                if regime in assigned_regimes
            },
        },
        phase=f"{branch} training",
    )
    final_path = directory / "checkpoints" / "final.pt"
    agent.save(final_path)
    return directory, final_path


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent-config",
        default="configs/agent/belief_graph_guided.yaml",
    )
    parser.add_argument(
        "--experiment-config",
        default="configs/agent/gate_learning_development.yaml",
        type=Path,
    )
    parser.add_argument(
        "--output-dir",
        default=Path("results/gate_learning_development"),
        type=Path,
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-episodes", type=int)
    parser.add_argument("--min-episodes", type=int)
    parser.add_argument("--evaluation-interval", type=int)
    parser.add_argument("--device", default="cuda")
    parser.add_argument(
        "--deterministic-evaluation",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--shared-initialization-checkpoint", type=Path)
    parser.add_argument(
        "--guided-only",
        action="store_true",
        help=(
            "Train only fixed/adaptive guided branches from an imported "
            "unguided checkpoint; requires --shared-initialization-checkpoint."
        ),
    )
    parser.add_argument(
        "--guidance-beta",
        type=float,
        help=(
            "Override alns_guidance.beta for both guided branches. The value "
            "is recorded in metadata and guided checkpoints."
        ),
    )
    parser.add_argument(
        "--regenerate-development-scenarios",
        action="store_true",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    experiment = yaml.safe_load(
        args.experiment_config.read_text(encoding="utf-8")
    )
    protocol = dict(experiment["protocol"])
    runtime = dict(experiment["development_runtime"])
    gate_training = dict(experiment["gate_training"])
    reproducibility = dict(experiment["reproducibility"])
    planned = int(args.max_episodes or protocol["planned_episodes"])
    minimum = int(args.min_episodes or protocol["minimum_episodes"])
    evaluation_interval = int(
        args.evaluation_interval or protocol["evaluation_interval"]
    )
    if args.guided_only and not args.shared_initialization_checkpoint:
        raise ValueError(
            "--guided-only requires --shared-initialization-checkpoint"
        )
    if args.guidance_beta is not None and (
        not math.isfinite(args.guidance_beta) or args.guidance_beta <= 0.0
    ):
        raise ValueError("--guidance-beta must be finite and positive")
    if planned < minimum:
        raise ValueError("max episodes cannot be below minimum episodes")
    if planned > int(protocol["absolute_maximum_episodes"]):
        raise ValueError("max episodes exceeds absolute development maximum")
    preexisting = (
        [
            path
            for path in args.output_dir.iterdir()
            if path.name not in {"run_stdout.log", "run_stderr.log"}
        ]
        if args.output_dir.exists()
        else []
    )
    if not args.resume and preexisting:
        raise FileExistsError(
            f"{args.output_dir} is not empty; use --resume or a new directory"
        )
    existing_metadata = None
    if args.resume:
        metadata_path = args.output_dir / "metadata.json"
        if not metadata_path.exists():
            raise FileNotFoundError(
                "Cannot resume corrected methodology without metadata.json"
            )
        existing_metadata = json.loads(
            metadata_path.read_text(encoding="utf-8")
        )
        if (
            existing_metadata.get("regime_fixture_version")
            != REGIME_FIXTURE_VERSION
        ):
            raise RuntimeError(
                "Existing checkpoints predate the operational-regime fixture "
                "correction; start a new output directory from shared "
                "initialization instead of resuming them"
            )
        if args.guidance_beta is not None and not math.isclose(
            float(existing_metadata.get("beta", math.nan)),
            float(args.guidance_beta),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise RuntimeError(
                "Resume guidance beta differs from metadata; start a new "
                "output directory for a different beta"
            )
    args.output_dir.mkdir(parents=True, exist_ok=True)

    master_seed = int(reproducibility["master_seed"])
    random.seed(master_seed)
    np.random.seed(master_seed)
    torch.manual_seed(master_seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(master_seed)
    if bool(reproducibility["deterministic_algorithms"]):
        torch.use_deterministic_algorithms(True)

    params = EnvParams()
    params.mission.T = float(runtime["mission_horizon_hours"])
    params.hybrid.alns_iterations = int(runtime["alns_iterations"])
    env = UAMTVRPIUEnv(params)
    probe = generate_scenario(TRAINING_SEEDS[0], params)
    env.reset(scenario=probe)
    loaded, _ = load_agent_config(args.agent_config)
    guidance_beta = float(
        args.guidance_beta
        if args.guidance_beta is not None
        else (
            existing_metadata["beta"]
            if existing_metadata is not None
            else loaded.get("guidance_beta", 1.0)
        )
    )
    if not math.isfinite(guidance_beta) or guidance_beta <= 0.0:
        raise ValueError("Resolved guidance beta must be finite and positive")
    agent_config = {
        **DEFAULT_AGENT_CONFIG,
        **loaded,
        "gamma_hour": params.mission.gamma_hour,
        "device": args.device,
        "guidance_beta": guidance_beta,
        "gate_directional_regularization_coef": float(
            gate_training["directional_regularization_coefficient"]
        ),
        "gate_directional_margin": float(
            gate_training["directional_margin"]
        ),
    }
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")

    split = development_seed_split()
    _canonical_write_json(args.output_dir / "seed_split.json", split)
    experiment = copy.deepcopy(experiment)
    experiment["gate_training"]["guidance_beta"] = guidance_beta
    _write_yaml(args.output_dir / "experiment_config.yaml", experiment)

    scenario_manifest = []
    for seed in (*TRAINING_SEEDS, *VALIDATION_SEEDS):
        scenario = generate_scenario(seed, params)
        scenario_manifest.append(
            {
                "seed": seed,
                "base_content_hash": scenario.content_hash(),
                "regime_interventions": regime_intervention_manifest(
                    scenario, params
                ),
            }
        )
    _canonical_write_json(
        args.output_dir / "development_scenario_manifest.json",
        scenario_manifest,
    )
    assignments = episode_assignments(planned)
    _write_csv(
        args.output_dir / "episode_scenario_assignments.csv",
        assignments,
        (
            "episode",
            "scenario_seed",
            "target_regime",
            "scenario_repeat",
        ),
    )

    metadata = {
        "objective": "adaptive-gate methodology-development experiment",
        "performance_claim": "none",
        "regime_fixture_version": REGIME_FIXTURE_VERSION,
        "master_seed": master_seed,
        "branch_random_seed": int(reproducibility["branch_random_seed"]),
        "agent_config": str(args.agent_config),
        "experiment_config": str(args.experiment_config),
        "device": args.device,
        "planned_episodes_per_branch": planned,
        "minimum_episodes": minimum,
        "evaluation_interval": evaluation_interval,
        "development_runtime": runtime,
        "fixed_gate": 0.5,
        "beta": guidance_beta,
        "gate_training": gate_training,
        "plan_feature_names": list(PLAN_FEATURE_NAMES),
        "training_seeds": list(TRAINING_SEEDS),
        "validation_seeds": list(VALIDATION_SEEDS),
        "qualitative_audit_seed": 18427,
        "pre_experiment_test_baseline": {
            "status": "not_executed_by_training_cli",
            "command": (
                "$env:KMP_DUPLICATE_LIB_OK='TRUE'; python -m pytest -q"
            ),
        },
        "unmodified_runtime_benchmark": {
            "mission_horizon_hours": 12.0,
            "alns_iterations": 60,
            "device": "cpu",
            "result": "one episode incomplete after 604.1 seconds",
            "terminated_benchmark_process_id": 20416,
        },
        "overrides": {
            "resume": args.resume,
            "max_episodes": args.max_episodes,
            "min_episodes": args.min_episodes,
            "evaluation_interval": args.evaluation_interval,
            "device": args.device,
            "deterministic_evaluation": args.deterministic_evaluation,
            "shared_initialization_checkpoint": (
                str(args.shared_initialization_checkpoint)
                if args.shared_initialization_checkpoint
                else None
            ),
            "guided_only": args.guided_only,
            "guidance_beta": args.guidance_beta,
            "regenerate_development_scenarios": (
                args.regenerate_development_scenarios
            ),
        },
    }
    _canonical_write_json(args.output_dir / "metadata.json", metadata)

    shared_agent = _make_agent(env, agent_config, "graph_mappo")
    graph_directory = args.output_dir / "graph_mappo"
    graph_start = 1
    if args.shared_initialization_checkpoint:
        shared_agent.load(args.shared_initialization_checkpoint)
        shared_path = args.shared_initialization_checkpoint
        _materialize_imported_baseline(
            directory=graph_directory,
            agent=shared_agent,
            env=env,
            params=params,
            deterministic_evaluation=args.deterministic_evaluation,
        )
    else:
        if args.resume and (graph_directory / "progress.json").exists():
            progress = json.loads(
                (graph_directory / "progress.json").read_text(encoding="utf-8")
            )
            graph_start = int(progress["episode_completed"]) + 1
            shared_agent.load(graph_directory / "checkpoints" / "latest.pt")
            rng_payload = torch.load(
                graph_directory / "checkpoints" / "rng_state.pt",
                weights_only=False,
            )
            _restore_rng(rng_payload)
        if graph_start <= planned:
            _, shared_path = _train_branch(
                root=args.output_dir,
                env=env,
                params=params,
                agent=shared_agent,
                branch="graph_mappo",
                assignments=assignments,
                start_episode=graph_start,
                maximum_episode=planned,
                evaluation_interval=evaluation_interval,
                checkpoint_interval=int(protocol["checkpoint_interval"]),
                deterministic_evaluation=args.deterministic_evaluation,
                minimum_fresh_prior_training_decisions=int(
                    gate_training[
                        "minimum_fresh_prior_bearing_training_decisions"
                    ]
                ),
                resume=args.resume,
            )
        else:
            shared_path = graph_directory / "checkpoints" / "final.pt"

    shared_init_dir = args.output_dir / "shared_initialization"
    shared_init_dir.mkdir(parents=True, exist_ok=True)
    shared_agent.save(shared_init_dir / "graph_mappo.pt")

    fixed = _make_agent(env, agent_config, "graph_mappo_fixed_alns")
    adaptive = _make_agent(env, agent_config, "graph_mappo_adaptive_alns")
    _copy_initialization(shared_agent, fixed)
    _copy_initialization(shared_agent, adaptive)
    shared_hashes = _component_hashes(shared_agent)
    fixed_hashes = _component_hashes(fixed)
    adaptive_hashes = _component_hashes(adaptive)
    if not (shared_hashes == fixed_hashes == adaptive_hashes):
        raise AssertionError("Shared branch initialization is not identical")
    fixed_init = args.output_dir / "fixed_guidance" / "checkpoints" / "initial.pt"
    adaptive_init = (
        args.output_dir / "adaptive_guidance" / "checkpoints" / "initial.pt"
    )
    fixed_init.parent.mkdir(parents=True, exist_ok=True)
    adaptive_init.parent.mkdir(parents=True, exist_ok=True)
    fixed.save(fixed_init)
    adaptive.save(adaptive_init)
    _canonical_write_json(
        shared_init_dir / "verification.json",
        {
            "passed": True,
            "component_hashes": shared_hashes,
            "fixed_initial_checkpoint_sha256": file_sha256(fixed_init),
            "adaptive_initial_checkpoint_sha256": file_sha256(adaptive_init),
            "source_checkpoint": str(shared_path),
        },
    )

    branch_seed = int(reproducibility["branch_random_seed"])
    for branch, agent in (
        ("graph_mappo_fixed_alns", fixed),
        ("graph_mappo_adaptive_alns", adaptive),
    ):
        directory = args.output_dir / (
            "fixed_guidance"
            if branch == "graph_mappo_fixed_alns"
            else "adaptive_guidance"
        )
        start = 1
        random.seed(branch_seed)
        np.random.seed(branch_seed)
        torch.manual_seed(branch_seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(branch_seed)
        if args.resume and (directory / "progress.json").exists():
            progress = json.loads(
                (directory / "progress.json").read_text(encoding="utf-8")
            )
            start = int(progress["episode_completed"]) + 1
            agent.load(directory / "checkpoints" / "latest.pt")
            _restore_rng(
                torch.load(
                    directory / "checkpoints" / "rng_state.pt",
                    weights_only=False,
                )
            )
        if start <= planned:
            _train_branch(
                root=args.output_dir,
                env=env,
                params=params,
                agent=agent,
                branch=branch,
                assignments=assignments,
                start_episode=start,
                maximum_episode=planned,
                evaluation_interval=evaluation_interval,
                checkpoint_interval=int(protocol["checkpoint_interval"]),
                deterministic_evaluation=args.deterministic_evaluation,
                minimum_fresh_prior_training_decisions=int(
                    gate_training[
                        "minimum_fresh_prior_bearing_training_decisions"
                    ]
                ),
                resume=args.resume,
            )

    print(f"training development outputs -> {args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
