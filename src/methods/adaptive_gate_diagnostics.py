"""Deterministic, truth-excluding diagnostics for the adaptive ALNS gate.

The subsystem only consumes detached operational tensors already used by the
policy.  It never samples actions, advances the environment, or calls backward.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np
import yaml

from .belief_graph import PLAN_FEATURE_NAMES


FEATURE_SCHEMA = (
    {
        "name": "plan_age",
        "definition": "Elapsed time since incumbent creation divided by mission horizon.",
        "source_state": "Scaffold.created_t and operational decision time",
        "units": "mission-horizon ratio",
        "normalization_rule": "(t - created_t) / T",
        "clipping_rule": "clip to [0,1]",
        "missing_value_rule": "never missing while an incumbent Scaffold exists",
    },
    {
        "name": "operational_demand_change",
        "definition": "L1 change in received belief means since incumbent creation.",
        "source_state": "BeliefState and Scaffold.mu_snapshot",
        "units": "dimensionless L1 ratio",
        "normalization_rule": "sum(abs(mu-current - mu-plan)) / max(sum(abs(mu-plan)),1)",
        "clipping_rule": "clip to [0,1]",
        "missing_value_rule": "default zero when the incumbent demand snapshot is empty",
    },
    {
        "name": "operational_inventory_change",
        "definition": "L1 depot-inventory change since incumbent creation.",
        "source_state": "DepotInventory and Scaffold.inventory_snapshot",
        "units": "dimensionless L1 ratio",
        "normalization_rule": "sum(abs(S-current - S-plan)) / max(sum(abs(S-plan)),1)",
        "clipping_rule": "clip to [0,1]",
        "missing_value_rule": "default zero only for a missing/empty legacy snapshot",
    },
    {
        "name": "newly_known_fraction",
        "definition": "Fraction of affected nodes revealed since incumbent creation.",
        "source_state": "BeliefState.known and Scaffold.known_snapshot",
        "units": "node fraction",
        "normalization_rule": "new known node count / configured node capacity",
        "clipping_rule": "clip to [0,1]",
        "missing_value_rule": "default zero when the known-node snapshot is empty",
    },
    {
        "name": "invalid_planned_corridor_fraction",
        "definition": "Fraction of incumbent legs now believed unavailable.",
        "source_state": "Scaffold visits and operational ReliefGraph availability",
        "units": "planned-leg fraction",
        "normalization_rule": "believed-invalid legs / max(planned legs,1)",
        "clipping_rule": "clip to [0,1]",
        "missing_value_rule": "default zero when the plan contains no legs",
    },
    {
        "name": "completed_planned_service_fraction",
        "definition": "Fraction of initially planned visits removed/completed.",
        "source_state": "Scaffold.planned_service_count and remaining visits",
        "units": "planned-service fraction",
        "normalization_rule": "max(initial - remaining,0) / max(initial,1)",
        "clipping_rule": "clip to [0,1]",
        "missing_value_rule": "default zero when the incumbent had no services",
    },
    {
        "name": "execution_deviation",
        "definition": "Whether a committed UAV destination differs from incumbent next visit.",
        "source_state": "Observable UAV mode/destination and Scaffold.peek_next",
        "units": "binary",
        "normalization_rule": "already in {0,1}",
        "clipping_rule": "clip to [0,1]",
        "missing_value_rule": "zero when no committed flight comparison is applicable",
    },
    {
        "name": "solver_active",
        "definition": "Whether the repository's ALNS solve is currently executing.",
        "source_state": "UAMTVRPIUEnv.alns_solving",
        "units": "binary",
        "normalization_rule": "already in {0,1}",
        "clipping_rule": "clip to [0,1]",
        "missing_value_rule": "never fabricated; normally zero for synchronous ALNS",
    },
    {
        "name": "solver_request_age",
        "definition": "Age of an outstanding ALNS request divided by mission horizon.",
        "source_state": "UAMTVRPIUEnv.alns_request_t and operational time",
        "units": "mission-horizon ratio",
        "normalization_rule": "(t - request_t) / T",
        "clipping_rule": "clip to [0,1]",
        "missing_value_rule": "default zero when no synchronous request is outstanding",
    },
    {
        "name": "next_action_operationally_feasible",
        "definition": "Whether the incumbent next visit passes current operational leg checks.",
        "source_state": "Scaffold.peek_next and operational C1/C2/C5 checks",
        "units": "binary",
        "normalization_rule": "already in {0,1}",
        "clipping_rule": "clip to [0,1]",
        "missing_value_rule": "default zero when no next incumbent visit exists",
    },
)

for _index, _entry in enumerate(FEATURE_SCHEMA):
    _entry["index"] = _index
    _entry["operational_information_guarantee"] = (
        "Uses received belief/controller, observable fleet/depot state, "
        "operational corridor belief, and incumbent snapshots only."
    )

if tuple(entry["name"] for entry in FEATURE_SCHEMA) != PLAN_FEATURE_NAMES:
    raise RuntimeError("Adaptive-gate feature schema does not match gate input order")


DEFAULT_DIAGNOSTIC_CONFIG = {
    "constant_std_epsilon": 1e-8,
    "near_constant_range": 1e-3,
    "missing_dominated_fraction": 0.8,
    "clipped_dominated_fraction": 0.8,
    "prior_coverage_minimum": 0.2,
    "mostly_masked_fraction": 0.5,
    "gate_close_to_fixed_abs_difference": 0.05,
    "saturation_fraction": 0.8,
    "negligible_logit_shift": 0.05,
    "measurable_policy_kl": 1e-6,
    "near_zero_argmax_change_rate": 0.01,
    "gate_gradient_epsilon": 1e-8,
    "gate_relative_update_epsilon": 1e-6,
    "minimum_prior_bearing_decisions": 50,
    "minimum_ppo_updates": 10,
    "unique_value_tolerance_decimals": 8,
}


FORBIDDEN_DIAGNOSTIC_KEYS = {
    "true_demand",
    "true_vulnerability",
    "physical_corridor_conditions",
    "active_hazard_ids",
    "active_temporary_nfz_ids",
    "unreceived_events",
    "future_events",
    "hidden_p3",
}


def _softmax_masked(logits: np.ndarray, mask: np.ndarray) -> np.ndarray:
    values = np.asarray(logits, dtype=np.float64).copy()
    valid = np.asarray(mask, dtype=bool)
    values[~valid] = -np.inf
    out = np.zeros_like(values)
    if not valid.any():
        return out
    maximum = np.max(values[valid])
    exp = np.exp(values[valid] - maximum)
    out[valid] = exp / exp.sum()
    return out


def _entropy(probabilities: np.ndarray) -> float:
    keep = probabilities > 0
    return float(-np.sum(probabilities[keep] * np.log(probabilities[keep])))


def _kl(left: np.ndarray, right: np.ndarray) -> float:
    keep = left > 0
    safe_right = np.maximum(right[keep], np.finfo(np.float64).tiny)
    return float(np.sum(left[keep] * (np.log(left[keep]) - np.log(safe_right))))


def _tv(left: np.ndarray, right: np.ndarray) -> float:
    return float(0.5 * np.abs(left - right).sum())


def counterfactual_policy(
    base_logits: np.ndarray,
    prior: np.ndarray,
    mask: np.ndarray,
    adaptive_gate: float,
    fixed_gate: float,
    beta: float,
) -> Dict[str, object]:
    """Isolate only the gate value while reusing exact detached policy inputs."""
    base = np.asarray(base_logits, dtype=np.float64)
    prior = np.asarray(prior, dtype=np.float64)
    mask = np.asarray(mask, dtype=bool)
    unguided = base.copy()
    fixed = base + float(beta) * float(fixed_gate) * prior
    adaptive = base + float(beta) * float(adaptive_gate) * prior
    masked_unguided = np.where(mask, unguided, -1e8)
    masked_fixed = np.where(mask, fixed, -1e8)
    masked_adaptive = np.where(mask, adaptive, -1e8)
    p0 = _softmax_masked(unguided, mask)
    pf = _softmax_masked(fixed, mask)
    pa = _softmax_masked(adaptive, mask)
    return {
        "unguided_logits": unguided,
        "fixed_guided_logits": fixed,
        "adaptive_guided_logits": adaptive,
        "masked_unguided_logits": masked_unguided,
        "masked_fixed_logits": masked_fixed,
        "masked_adaptive_logits": masked_adaptive,
        "unguided_probabilities": p0,
        "fixed_probabilities": pf,
        "adaptive_probabilities": pa,
        "unguided_argmax": int(np.argmax(p0)),
        "fixed_argmax": int(np.argmax(pf)),
        "adaptive_argmax": int(np.argmax(pa)),
        "kl_adaptive_unguided": _kl(pa, p0),
        "kl_adaptive_fixed": _kl(pa, pf),
        "tv_adaptive_unguided": _tv(pa, p0),
        "tv_adaptive_fixed": _tv(pa, pf),
        "entropy_unguided": _entropy(p0),
        "entropy_fixed": _entropy(pf),
        "entropy_adaptive": _entropy(pa),
    }


def operational_mask_reason(env, uav_id: int, action: int) -> str:
    """Explain an operational mask without consulting latent physical state."""
    mask = env._action_mask(uav_id)
    if 0 <= action < len(mask) and bool(mask[action]):
        return "FEASIBLE"
    if action < 0 or action >= len(mask):
        return "ACTION_NOT_APPLICABLE"
    kind, node, other = env.decode_action(uav_id, action)
    if kind == "REQUEST_RESOLVE":
        return "ACTION_NOT_APPLICABLE"
    if kind in {"FOLLOW", "RETURN"}:
        return "ACTION_NOT_APPLICABLE"
    if node is None or not env.belief.is_known(node):
        return "ACTION_NOT_APPLICABLE"
    demand = env.belief.d_tilde(node)
    if demand.sum() <= 1e-9:
        return "DEMAND_SATISFIED"
    if kind == "INSERT":
        uav = env.uavs[uav_id]
        if env._in_turnaround[uav_id]:
            return "UAV_COMMITTED"
        if not env.graph.A(env._anchor_node(uav_id), node):
            return "BELIEVED_CORRIDOR_CLOSED"
        resources = (
            env.inventory.S0 if uav.ell.sum() <= 1e-9 else uav.ell
        )
        if not np.any((resources > 1e-9) & (demand > 1e-9)):
            return "INVENTORY_UNAVAILABLE"
        if not env._c5_ok(uav_id, node):
            return "INSUFFICIENT_ENERGY"
    if kind in {"SKIP", "SWAP"} and node not in set(
        env.scaffold.planned_nodes(uav_id)
    ):
        return "ACTION_NOT_APPLICABLE"
    if kind == "SWAP" and other is not None:
        if not env.graph.A(env._anchor_node(other), node):
            return "BELIEVED_CORRIDOR_CLOSED"
    return "OTHER"


def _action_identifier(env, uav_id: int, action: int) -> str:
    if action < 0:
        return "NONE"
    kind, node, other = env.decode_action(uav_id, action)
    suffix = "" if node is None else f":N{node}"
    if other is not None:
        suffix += f":UAV{other}"
    return kind + suffix


def build_decision_diagnostic(
    *,
    detail: Mapping[str, object],
    graph,
    env,
    uav_id: int,
    context: Mapping[str, object],
) -> tuple[Dict[str, object], Dict[str, object], Dict[str, object]]:
    """Build one summary row plus full vectors from detached exact tensors."""
    base = np.asarray(detail["base_logits"], dtype=np.float64)
    prior = np.asarray(detail["alns_prior"], dtype=np.float64)
    mask = np.asarray(detail["action_mask"], dtype=bool)
    selected = int(detail["selected_action"])
    adaptive_gate = float(detail["gate_adaptive"])
    fixed_gate = float(detail["gate_fixed"])
    beta = float(detail["beta"])
    counter = counterfactual_policy(
        base, prior, mask, adaptive_gate, fixed_gate, beta
    )
    recommended = int(detail["recommended_action"])
    prior_positive = prior > 0
    recommended_feasible = (
        recommended >= 0 and recommended < len(mask) and bool(mask[recommended])
    )
    selected_base = float(base[selected])
    selected_guided = float(
        counter["adaptive_guided_logits"][selected]
    )
    recommended_in_action_space = 0 <= recommended < len(base)
    alns_index = recommended if recommended_in_action_space else None
    destination = None
    edge = None
    mapping_success = False
    if (
        alns_index is not None
        and alns_index < graph.action_to_destination.shape[1]
    ):
        slot = int(graph.action_to_destination[uav_id, alns_index])
        edge_index = int(graph.action_to_edge[uav_id, alns_index])
        destination = graph.slot_to_entity_id.get(slot)
        edge = None if edge_index < 0 else f"operational_edge:{edge_index}"
        mapping_success = slot >= 0
    zero_prior_reason = (
        graph.zero_prior_reasons[uav_id]
        if graph.zero_prior_reasons
        else ""
    )
    if not prior_positive.any():
        if recommended >= 0 and not recommended_in_action_space:
            zero_prior_reason = "RECOMMENDED_ACTION_NOT_IN_CURRENT_ACTION_SET"
        elif recommended_in_action_space and not mapping_success:
            zero_prior_reason = "ACTION_MAPPING_FAILED"
        elif not zero_prior_reason:
            zero_prior_reason = "OTHER"

    row: Dict[str, object] = {
        **dict(context),
        "uav_id": int(uav_id),
        "gate_logit": float(detail["gate_logit"]),
        "gate_adaptive": adaptive_gate,
        "gate_fixed": fixed_gate,
        "gate_minus_fixed": adaptive_gate - fixed_gate,
        "abs_gate_minus_fixed": abs(adaptive_gate - fixed_gate),
        "beta": beta,
        "effective_scale": beta * adaptive_gate,
        "fixed_effective_scale": beta * fixed_gate,
        "incumbent_plan_exists": int(getattr(env, "scaffold", None) is not None),
        "uav_has_recommendation": int(recommended >= 0),
        "recommended_action": recommended,
        "recommended_action_identifier": (
            _action_identifier(env, uav_id, recommended)
            if recommended_in_action_space
            else ("NONE" if recommended < 0 else f"UNMAPPED:{recommended}")
        ),
        "recommended_destination": destination or "",
        "recommended_corridor": edge or "",
        "recommended_load_component": "NOT_FACTORIZED",
        "recommended_service_component": "NOT_FACTORIZED",
        "recommendation_maps_successfully": int(mapping_success),
        "prior_nonzero_count": int(np.count_nonzero(prior)),
        "prior_l1_norm": float(np.abs(prior).sum()),
        "prior_l2_norm": float(np.linalg.norm(prior)),
        "prior_maximum": float(prior.max(initial=0.0)),
        "positive_prior_action_count": int(prior_positive.sum()),
        "prior_is_zero": int(not prior_positive.any()),
        "zero_prior_reason": zero_prior_reason if not prior_positive.any() else "",
        "total_action_count": int(len(mask)),
        "feasible_action_count": int(mask.sum()),
        "infeasible_action_count": int((~mask).sum()),
        "recommended_action_feasible": int(recommended_feasible),
        "recommended_action_masked": int(
            recommended >= 0 and not recommended_feasible
        ),
        "recommended_action_mask_reason": (
            operational_mask_reason(env, uav_id, recommended)
            if recommended >= 0
            else "NO_RECOMMENDATION"
        ),
        "any_positive_prior_action_masked": int(
            bool((prior_positive & ~mask).any())
        ),
        "positive_prior_actions_surviving_mask": int(
            (prior_positive & mask).sum()
        ),
        "selected_action": selected,
        "selected_action_identifier": _action_identifier(env, uav_id, selected),
        "selected_action_base_logit": selected_base,
        "selected_action_adaptive_guided_logit": selected_guided,
        "alns_action_base_logit": (
            float(base[alns_index]) if alns_index is not None else math.nan
        ),
        "alns_action_adaptive_guided_logit": (
            float(counter["adaptive_guided_logits"][alns_index])
            if alns_index is not None else math.nan
        ),
        "alns_action_fixed_guided_logit": (
            float(counter["fixed_guided_logits"][alns_index])
            if alns_index is not None else math.nan
        ),
        "alns_action_base_probability": (
            float(counter["unguided_probabilities"][alns_index])
            if alns_index is not None else math.nan
        ),
        "alns_action_adaptive_probability": (
            float(counter["adaptive_probabilities"][alns_index])
            if alns_index is not None else math.nan
        ),
        "alns_action_fixed_probability": (
            float(counter["fixed_probabilities"][alns_index])
            if alns_index is not None else math.nan
        ),
        "maximum_absolute_logit_shift": float(
            np.max(np.abs(
                counter["adaptive_guided_logits"] - base
            ))
        ),
        "mean_absolute_logit_shift": float(
            np.mean(np.abs(counter["adaptive_guided_logits"] - base))
        ),
        "maximum_absolute_probability_shift": float(
            np.max(np.abs(
                counter["adaptive_probabilities"]
                - counter["unguided_probabilities"]
            ))
        ),
        "kl_adaptive_unguided": counter["kl_adaptive_unguided"],
        "kl_adaptive_fixed": counter["kl_adaptive_fixed"],
        "tv_adaptive_unguided": counter["tv_adaptive_unguided"],
        "tv_adaptive_fixed": counter["tv_adaptive_fixed"],
        "entropy_unguided": counter["entropy_unguided"],
        "entropy_adaptive": counter["entropy_adaptive"],
        "entropy_fixed": counter["entropy_fixed"],
        "stochastic_selected_action": selected,
        "unguided_argmax_action": counter["unguided_argmax"],
        "fixed_argmax_action": counter["fixed_argmax"],
        "adaptive_argmax_action": counter["adaptive_argmax"],
        "stochastic_selected_follows_alns": int(selected == recommended),
        "adaptive_argmax_follows_alns": int(
            counter["adaptive_argmax"] == recommended
        ),
        "fixed_argmax_follows_alns": int(
            counter["fixed_argmax"] == recommended
        ),
        "adaptive_fixed_argmax_differ": int(
            counter["adaptive_argmax"] != counter["fixed_argmax"]
        ),
        "adaptive_unguided_argmax_differ": int(
            counter["adaptive_argmax"] != counter["unguided_argmax"]
        ),
        "probabilities_changed_argmax_unchanged": int(
            counter["tv_adaptive_unguided"] > 1e-12
            and counter["adaptive_argmax"] == counter["unguided_argmax"]
        ),
        "categorical_random_value": "",
        "sampling_backend": (
            "torch.distributions.Categorical.sample"
            if context.get("selection_mode") == "stochastic"
            else "deterministic_argmax"
        ),
    }
    raw = np.asarray(graph.plan_feature_raw[uav_id], dtype=float)
    normalized = np.asarray(graph.plan_features[uav_id], dtype=float)
    clipped = np.asarray(graph.plan_feature_clipped[uav_id], dtype=bool)
    defaulted = np.asarray(graph.plan_feature_defaulted[uav_id], dtype=bool)
    for schema in FEATURE_SCHEMA:
        index = schema["index"]
        prefix = schema["name"]
        row[f"{prefix}__raw"] = float(raw[index])
        row[f"{prefix}__normalized"] = float(normalized[index])
        row[f"{prefix}__missing"] = 0
        row[f"{prefix}__defaulted"] = int(defaulted[index])
        row[f"{prefix}__clipped"] = int(clipped[index])
        row[f"{prefix}__normalization_reference"] = schema[
            "normalization_rule"
        ]
        row[f"{prefix}__feature_index"] = index

    vectors = {
        "decision_index": row["decision_index"],
        "run_id": row["run_id"],
        "mode": row["mode"],
        "uav_id": uav_id,
        "base_logits": base.tolist(),
        "production_masked_logits": np.asarray(
            detail["masked_logits"], dtype=float
        ).tolist(),
        "production_probabilities": np.asarray(
            detail["probabilities"], dtype=float
        ).tolist(),
        "action_mask": mask.astype(int).tolist(),
        "alns_prior": prior.tolist(),
        **{
            key: np.asarray(counter[key], dtype=float).tolist()
            for key in (
                "unguided_logits",
                "fixed_guided_logits",
                "adaptive_guided_logits",
                "masked_unguided_logits",
                "masked_fixed_logits",
                "masked_adaptive_logits",
                "unguided_probabilities",
                "fixed_probabilities",
                "adaptive_probabilities",
            )
        },
    }
    counter_row = {
        key: row[key]
        for key in (
            "run_id",
            "mode",
            "episode",
            "phase",
            "decision_index",
            "decision_time",
            "uav_id",
            "recommended_action",
            "gate_adaptive",
            "gate_fixed",
            "beta",
            "alns_action_base_probability",
            "alns_action_fixed_probability",
            "alns_action_adaptive_probability",
            "unguided_argmax_action",
            "fixed_argmax_action",
            "adaptive_argmax_action",
            "kl_adaptive_unguided",
            "kl_adaptive_fixed",
            "tv_adaptive_unguided",
            "tv_adaptive_fixed",
            "adaptive_fixed_argmax_differ",
            "adaptive_unguided_argmax_differ",
        )
    }
    return row, counter_row, vectors


def _stats(values: np.ndarray) -> Dict[str, float]:
    return {
        "minimum": float(np.min(values)),
        "maximum": float(np.max(values)),
        "mean": float(np.mean(values)),
        "standard_deviation": float(np.std(values)),
        "median": float(np.median(values)),
        "p05": float(np.percentile(values, 5)),
        "p25": float(np.percentile(values, 25)),
        "p75": float(np.percentile(values, 75)),
        "p95": float(np.percentile(values, 95)),
    }


def feature_variation_summary(
    decision_rows: Sequence[Mapping[str, object]],
    config: Mapping[str, float],
) -> List[Dict[str, object]]:
    if not decision_rows:
        return []
    groups: List[tuple[str, str, List[Mapping[str, object]]]] = [
        ("all", "all", list(decision_rows))
    ]
    for column in ("mode", "episode", "uav_id"):
        values = sorted({str(row[column]) for row in decision_rows})
        for value in values:
            groups.append(
                (
                    column,
                    value,
                    [row for row in decision_rows if str(row[column]) == value],
                )
            )
    groups.extend(
        [
            (
                "condition",
                "prior_nonzero",
                [row for row in decision_rows if not row["prior_is_zero"]],
            ),
            (
                "condition",
                "recommendation_feasible",
                [
                    row for row in decision_rows
                    if row["recommended_action_feasible"]
                ],
            ),
            (
                "condition",
                "after_operational_change",
                [
                    row for row in decision_rows
                    if any(
                        float(row[f"{name}__normalized"]) > 1e-12
                        for name in (
                            "operational_demand_change",
                            "operational_inventory_change",
                            "newly_known_fraction",
                            "invalid_planned_corridor_fraction",
                        )
                    )
                ],
            ),
        ]
    )
    output = []
    decimals = int(config["unique_value_tolerance_decimals"])
    for scope, scope_value, rows in groups:
        if not rows:
            continue
        gates = np.asarray([float(row["gate_adaptive"]) for row in rows])
        for schema in FEATURE_SCHEMA:
            name = schema["name"]
            values = np.asarray(
                [float(row[f"{name}__normalized"]) for row in rows]
            )
            missing = np.asarray(
                [int(row[f"{name}__missing"]) for row in rows]
            )
            defaulted = np.asarray(
                [int(row[f"{name}__defaulted"]) for row in rows]
            )
            clipped = np.asarray(
                [int(row[f"{name}__clipped"]) for row in rows]
            )
            stats = _stats(values)
            if stats["standard_deviation"] < config["constant_std_epsilon"]:
                status = "CONSTANT"
            elif (
                stats["maximum"] - stats["minimum"]
                < config["near_constant_range"]
            ):
                status = "NEAR_CONSTANT"
            elif max(missing.mean(), defaulted.mean()) > config[
                "missing_dominated_fraction"
            ]:
                status = "MISSING_DOMINATED"
            elif clipped.mean() > config["clipped_dominated_fraction"]:
                status = "CLIPPED_DOMINATED"
            else:
                status = "VARIABLE"
            correlation = (
                float(np.corrcoef(values, gates)[0, 1])
                if np.std(values) > 0 and np.std(gates) > 0
                else None
            )
            per_episode_constant = []
            for episode in sorted({row["episode"] for row in rows}):
                episode_values = [
                    float(row[f"{name}__normalized"])
                    for row in rows if row["episode"] == episode
                ]
                per_episode_constant.append(
                    np.std(episode_values) < config["constant_std_epsilon"]
                )
            output.append(
                {
                    "scope": scope,
                    "scope_value": scope_value,
                    "feature": name,
                    "feature_index": schema["index"],
                    "count": len(rows),
                    "missing_count": int(missing.sum()),
                    "default_count": int(defaulted.sum()),
                    **stats,
                    "unique_value_count": int(
                        len(np.unique(np.round(values, decimals)))
                    ),
                    "fraction_clipped": float(clipped.mean()),
                    "fraction_defaulted": float(defaulted.mean()),
                    "fraction_constant_within_episode": float(
                        np.mean(per_episode_constant)
                    ),
                    "correlation_with_gate": correlation,
                    "status": status,
                }
            )
    return output


def controlled_probe_profiles() -> Dict[str, np.ndarray]:
    base = np.zeros(len(PLAN_FEATURE_NAMES), dtype=np.float32)
    base[-1] = 1.0
    profiles = {"fresh_valid_plan": base}
    for name, index in (
        ("old_valid_plan", 0),
        ("large_operational_demand_change", 1),
        ("large_inventory_change", 2),
        ("newly_revealed_nodes", 3),
        ("believed_invalid_corridors", 4),
        ("many_completed_services", 5),
        ("high_execution_deviation", 6),
        ("solver_active", 7),
    ):
        profile = base.copy()
        profile[index] = 1.0
        profiles[name] = profile
    combined = base.copy()
    combined[[0, 1, 3, 4, 6]] = 1.0
    combined[-1] = 0.0
    profiles["combined_stale_invalid"] = combined
    return profiles


def evaluate_controlled_probes(actor, checkpoint_label: str) -> List[Dict]:
    import torch

    rows = []
    with torch.no_grad():
        for name, features in controlled_probe_profiles().items():
            tensor = torch.as_tensor(
                features[None],
                dtype=torch.float32,
                device=next(actor.parameters()).device,
            )
            logit = actor.guidance_gate.logits(tensor)
            gate = torch.sigmoid(logit)
            row = {
                "checkpoint": checkpoint_label,
                "profile": name,
                "gate_logit": float(logit[0, 0].cpu()),
                "gate_value": float(gate[0, 0].cpu()),
            }
            for index, feature_name in enumerate(PLAN_FEATURE_NAMES):
                row[f"{feature_name}__raw"] = float(features[index])
                row[f"{feature_name}__normalized"] = float(features[index])
            rows.append(row)
    baseline = next(row for row in rows if row["profile"] == "fresh_valid_plan")
    for row in rows:
        row["gate_minus_fresh"] = row["gate_value"] - baseline["gate_value"]
    return rows


def classify_root_causes(
    metrics: Mapping[str, object],
    config: Optional[Mapping[str, float]] = None,
) -> List[Dict[str, object]]:
    cfg = {**DEFAULT_DIAGNOSTIC_CONFIG, **(config or {})}
    evidence = []

    def add(name, severity, metric, threshold, value, artifact, column, text):
        evidence.append(
            {
                "classification": name,
                "severity": severity,
                "supporting_metric": metric,
                "threshold": threshold,
                "measured_value": value,
                "supporting_artifact": artifact,
                "supporting_column": column,
                "interpretation": text,
            }
        )

    prior = float(metrics.get("prior_coverage_rate", 0.0))
    if prior < cfg["prior_coverage_minimum"]:
        add(
            "NO_PRIOR_COVERAGE", "HIGH", "prior_coverage_rate",
            cfg["prior_coverage_minimum"], prior,
            "adaptive_gate_decisions.csv", "prior_is_zero",
            "The ALNS prior is available for too few decisions.",
        )
    masked = float(metrics.get("prior_masked_rate", 0.0))
    if masked > cfg["mostly_masked_fraction"]:
        add(
            "PRIOR_MOSTLY_MASKED", "HIGH", "prior_masked_rate",
            cfg["mostly_masked_fraction"], masked,
            "adaptive_gate_decisions.csv", "any_positive_prior_action_masked",
            "Operational masks remove most positively guided actions.",
        )
    gate_diff = float(metrics.get("mean_abs_gate_minus_fixed", math.inf))
    if gate_diff < cfg["gate_close_to_fixed_abs_difference"]:
        add(
            "GATE_CLOSE_TO_FIXED", "MEDIUM", "mean_abs_gate_minus_fixed",
            cfg["gate_close_to_fixed_abs_difference"], gate_diff,
            "adaptive_gate_decisions.csv", "abs_gate_minus_fixed",
            "Adaptive gates remain numerically close to the fixed ablation.",
        )
    for name, key, text in (
        ("GATE_SATURATED_LOW", "gate_below_005_fraction", "Gates saturate near zero."),
        ("GATE_SATURATED_HIGH", "gate_above_095_fraction", "Gates saturate near one."),
    ):
        value = float(metrics.get(key, 0.0))
        if value > cfg["saturation_fraction"]:
            add(
                name, "HIGH", key, cfg["saturation_fraction"], value,
                "adaptive_gate_decisions.csv", "gate_adaptive", text,
            )
    shift = float(metrics.get("mean_max_logit_shift", 0.0))
    if shift < cfg["negligible_logit_shift"]:
        add(
            "GUIDANCE_LOGIT_EFFECT_NEGLIGIBLE", "MEDIUM",
            "mean_max_logit_shift", cfg["negligible_logit_shift"], shift,
            "adaptive_gate_decisions.csv", "maximum_absolute_logit_shift",
            "Guidance adds little relative displacement to the policy logits.",
        )
    kl = float(metrics.get("mean_kl_adaptive_unguided", 0.0))
    argmax_rate = float(metrics.get("adaptive_unguided_argmax_change_rate", 0.0))
    if (
        kl > cfg["measurable_policy_kl"]
        and argmax_rate <= cfg["near_zero_argmax_change_rate"]
    ):
        add(
            "PROBABILITIES_CHANGE_BUT_ACTIONS_DO_NOT", "MEDIUM",
            "mean_KL_and_argmax_change_rate",
            {
                "kl_min": cfg["measurable_policy_kl"],
                "argmax_max": cfg["near_zero_argmax_change_rate"],
            },
            {"kl": kl, "argmax_rate": argmax_rate},
            "adaptive_gate_counterfactual_decisions.csv",
            "kl_adaptive_unguided,adaptive_unguided_argmax_differ",
            "Guidance changes probabilities without changing deterministic actions.",
        )
    feature_statuses = list(metrics.get("feature_statuses", []))
    degenerate = sum(status != "VARIABLE" for status in feature_statuses)
    if feature_statuses and degenerate == len(feature_statuses):
        add(
            "PLAN_FEATURES_CONSTANT", "HIGH", "degenerate_feature_count",
            len(feature_statuses), degenerate,
            "adaptive_gate_feature_summary.csv", "status",
            "All plan-confidence features are degenerate.",
        )
    elif degenerate:
        add(
            "PLAN_FEATURES_PARTIALLY_DEGENERATE", "MEDIUM",
            "degenerate_feature_count", 1, degenerate,
            "adaptive_gate_feature_summary.csv", "status",
            "One or more plan-confidence inputs are constant/default/clipped dominated.",
        )
    grad = float(metrics.get("median_gate_gradient_norm", 0.0))
    if grad < cfg["gate_gradient_epsilon"]:
        add(
            "GATE_GRADIENT_ABSENT", "HIGH", "median_gate_gradient_norm",
            cfg["gate_gradient_epsilon"], grad,
            "adaptive_gate_update_diagnostics.csv", "gate_gradient_l2_norm",
            "The policy objective supplies no measurable gate gradient.",
        )
    relative_update = float(metrics.get("median_relative_gate_update", 0.0))
    if grad >= cfg["gate_gradient_epsilon"] and relative_update < cfg[
        "gate_relative_update_epsilon"
    ]:
        add(
            "GATE_UPDATE_NEGLIGIBLE", "MEDIUM",
            "median_relative_gate_update",
            cfg["gate_relative_update_epsilon"], relative_update,
            "adaptive_gate_update_diagnostics.csv",
            "gate_relative_parameter_update",
            "Gradients exist but barely move gate parameters.",
        )
    if bool(metrics.get("fixed_adaptive_paths_identical", False)):
        add(
            "FIXED_AND_ADAPTIVE_PATHS_IDENTICAL", "CRITICAL",
            "unexpected_exact_path_identity", False, True,
            "adaptive_gate_counterfactual_decisions.csv",
            "gate_adaptive,gate_fixed",
            "Fixed and adaptive branches unexpectedly use the same gate value.",
        )
    if (
        int(metrics.get("prior_bearing_decisions", 0))
        < cfg["minimum_prior_bearing_decisions"]
        or int(metrics.get("ppo_updates", 0)) < cfg["minimum_ppo_updates"]
    ):
        add(
            "SMOKE_RUN_TOO_SHORT", "MEDIUM",
            "prior_bearing_decisions_and_updates",
            {
                "prior_min": cfg["minimum_prior_bearing_decisions"],
                "updates_min": cfg["minimum_ppo_updates"],
            },
            {
                "prior": int(metrics.get("prior_bearing_decisions", 0)),
                "updates": int(metrics.get("ppo_updates", 0)),
            },
            "metadata.json", "decision_count,ppo_update_count",
            "The run offers limited prior-bearing or optimization evidence.",
        )
    if bool(metrics.get("stochastic_action_coincidence", False)):
        add(
            "STOCHASTIC_ACTION_COINCIDENCE", "LOW",
            "distribution_difference_with_same_samples", True, True,
            "adaptive_gate_decisions.csv", "stochastic_selected_action",
            "Short stochastic rollouts can match despite different probabilities.",
        )
    if bool(metrics.get("synchronous_solver_features_constant", False)):
        add(
            "SYNCHRONOUS_ALNS_FEATURE_LIMITATION", "EXPECTED",
            "solver_feature_variation", "variable only for asynchronous solver",
            "constant",
            "adaptive_gate_feature_summary.csv", "solver_active,solver_request_age",
            "The real synchronous ALNS makes solver-state inputs degenerate.",
        )
    if not evidence:
        add(
            "NO_DIAGNOSTIC_PROBLEM_DETECTED", "INFO",
            "combined_evidence", "no trigger", "no trigger",
            "adaptive_gate_diagnosis.json", "",
            "Variation, gradients, prior coverage, and policy influence are measurable.",
        )
    elif len(evidence) > 1:
        add(
            "NO_SINGLE_DOMINANT_CAUSE", "INFO", "classification_count", 1,
            len(evidence), "adaptive_gate_diagnosis.json", "classification",
            "Several measured mechanisms contribute to the identical smoke outcome.",
        )
    return evidence


class AdaptiveGateDiagnostics:
    """In-memory deterministic collector with canonical artifact writers."""

    def __init__(self, config: Optional[Mapping[str, object]] = None):
        self.config = {**DEFAULT_DIAGNOSTIC_CONFIG, **(config or {})}
        self.decision_rows: List[Dict] = []
        self.counterfactual_rows: List[Dict] = []
        self.vector_rows: List[Dict] = []
        self.update_rows: List[Dict] = []
        self.probe_rows: List[Dict] = []

    def record_decision(self, row, counterfactual, vectors) -> None:
        self.decision_rows.append(dict(row))
        self.counterfactual_rows.append(dict(counterfactual))
        self.vector_rows.append(dict(vectors))

    def record_update(self, row: Mapping[str, object]) -> None:
        self.update_rows.append(dict(row))

    def record_probes(self, rows: Iterable[Mapping[str, object]]) -> None:
        self.probe_rows.extend(dict(row) for row in rows)

    @staticmethod
    def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
        if not rows:
            path.write_text("", encoding="utf-8", newline="\n")
            return
        fields = list(rows[0].keys())
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def _write_json(path: Path, payload) -> None:
        path.write_text(
            json.dumps(
                payload, sort_keys=True, indent=2, allow_nan=False
            ) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    @staticmethod
    def _write_jsonl_gz(path: Path, rows: Sequence[Mapping]) -> None:
        with path.open("wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as zipped:
                with io.TextIOWrapper(zipped, encoding="utf-8", newline="\n") as text:
                    for row in rows:
                        text.write(
                            json.dumps(
                                row, sort_keys=True, separators=(",", ":"),
                                allow_nan=False,
                            )
                            + "\n"
                        )

    def aggregate_metrics(self, feature_summary: Sequence[Mapping]) -> Dict:
        rows = self.decision_rows
        updates = self.update_rows
        gates = np.asarray([row["gate_adaptive"] for row in rows], dtype=float)
        prior = np.asarray([not row["prior_is_zero"] for row in rows], dtype=bool)
        prior_masked = np.asarray(
            [row["any_positive_prior_action_masked"] for row in rows], dtype=bool
        )
        all_features = [
            row for row in feature_summary
            if row["scope"] == "all" and row["scope_value"] == "all"
        ]
        gradients = np.asarray(
            [row["gate_gradient_l2_norm"] for row in updates], dtype=float
        )
        relative_updates = np.asarray(
            [row["gate_relative_parameter_update"] for row in updates],
            dtype=float,
        )
        return {
            "decision_count": len(rows),
            "prior_bearing_decisions": int(prior.sum()),
            "ppo_updates": len(updates),
            "gate_mean": float(gates.mean()),
            "gate_std": float(gates.std()),
            "gate_min": float(gates.min()),
            "gate_max": float(gates.max()),
            "gate_below_005_fraction": float((gates < 0.05).mean()),
            "gate_above_095_fraction": float((gates > 0.95).mean()),
            "mean_abs_gate_minus_fixed": float(
                np.mean([row["abs_gate_minus_fixed"] for row in rows])
            ),
            "median_abs_gate_minus_fixed": float(
                np.median([row["abs_gate_minus_fixed"] for row in rows])
            ),
            "prior_coverage_rate": float(prior.mean()),
            "prior_masked_rate": float(
                prior_masked[prior].mean() if prior.any() else 0.0
            ),
            "mean_max_logit_shift": float(
                np.mean([row["maximum_absolute_logit_shift"] for row in rows])
            ),
            "mean_max_probability_shift": float(
                np.mean([
                    row["maximum_absolute_probability_shift"] for row in rows
                ])
            ),
            "mean_kl_adaptive_unguided": float(
                np.mean([row["kl_adaptive_unguided"] for row in rows])
            ),
            "mean_kl_adaptive_fixed": float(
                np.mean([row["kl_adaptive_fixed"] for row in rows])
            ),
            "mean_tv_adaptive_unguided": float(
                np.mean([row["tv_adaptive_unguided"] for row in rows])
            ),
            "mean_tv_adaptive_fixed": float(
                np.mean([row["tv_adaptive_fixed"] for row in rows])
            ),
            "adaptive_unguided_argmax_change_rate": float(
                np.mean([
                    row["adaptive_unguided_argmax_differ"] for row in rows
                ])
            ),
            "adaptive_fixed_argmax_change_rate": float(
                np.mean([row["adaptive_fixed_argmax_differ"] for row in rows])
            ),
            "feature_statuses": [row["status"] for row in all_features],
            "median_gate_gradient_norm": float(
                np.median(gradients) if len(gradients) else 0.0
            ),
            "median_relative_gate_update": float(
                np.median(relative_updates) if len(relative_updates) else 0.0
            ),
            "fixed_adaptive_paths_identical": bool(
                all(row["abs_gate_minus_fixed"] < 1e-12 for row in rows)
            ),
            "stochastic_action_coincidence": bool(
                np.mean([row["kl_adaptive_fixed"] for row in rows]) > 1e-6
                and not any(row["adaptive_fixed_argmax_differ"] for row in rows)
            ),
            "synchronous_solver_features_constant": bool(
                all(
                    row["status"] == "CONSTANT"
                    for row in all_features
                    if row["feature"] in {"solver_active", "solver_request_age"}
                )
            ),
        }

    def write(
        self,
        output_dir: Path,
        metadata: Mapping[str, object],
        save_full_vectors: bool = True,
    ) -> Dict[str, object]:
        output_dir.mkdir(parents=True, exist_ok=True)
        feature_summary = feature_variation_summary(
            self.decision_rows, self.config
        )
        metrics = self.aggregate_metrics(feature_summary)
        diagnosis = classify_root_causes(metrics, self.config)
        self._write_json(output_dir / "metadata.json", dict(metadata))
        (output_dir / "diagnostic_config.yaml").write_text(
            yaml.safe_dump(self.config, sort_keys=True),
            encoding="utf-8",
            newline="\n",
        )
        self._write_json(
            output_dir / "adaptive_gate_feature_schema.json",
            list(FEATURE_SCHEMA),
        )
        self._write_csv(
            output_dir / "adaptive_gate_decisions.csv", self.decision_rows
        )
        self._write_csv(
            output_dir / "adaptive_gate_update_diagnostics.csv",
            self.update_rows,
        )
        self._write_csv(
            output_dir / "adaptive_gate_feature_summary.csv", feature_summary
        )
        self._write_json(
            output_dir / "adaptive_gate_feature_summary.json", feature_summary
        )
        self._write_csv(
            output_dir / "adaptive_gate_counterfactual_decisions.csv",
            self.counterfactual_rows,
        )
        self._write_csv(
            output_dir / "adaptive_gate_controlled_probes.csv",
            self.probe_rows,
        )
        if save_full_vectors:
            self._write_jsonl_gz(
                output_dir / "adaptive_gate_vectors.jsonl.gz",
                self.vector_rows,
            )
            self._write_jsonl_gz(
                output_dir / "adaptive_gate_counterfactual_vectors.jsonl.gz",
                self.vector_rows,
            )
        diagnosis_payload = {
            "metrics": metrics,
            "classifications": diagnosis,
            "performance_claim": (
                "None. Diagnostics isolate gate mechanics and are not "
                "performance evidence."
            ),
        }
        self._write_json(
            output_dir / "adaptive_gate_diagnosis.json", diagnosis_payload
        )
        lines = [
            "# Adaptive-gate diagnosis",
            "",
            "This report diagnoses gate mechanics only; it makes no performance claim.",
            "",
        ]
        for item in diagnosis:
            lines.extend(
                [
                    f"## {item['classification']} ({item['severity']})",
                    "",
                    item["interpretation"],
                    "",
                    f"Measured `{item['supporting_metric']}`: "
                    f"`{item['measured_value']}`; threshold: "
                    f"`{item['threshold']}`.",
                    "",
                ]
            )
        (output_dir / "adaptive_gate_diagnosis.md").write_text(
            "\n".join(lines), encoding="utf-8", newline="\n"
        )
        canonical_files = sorted(
            path for path in output_dir.iterdir()
            if path.is_file() and path.name != "reproducibility_report.json"
        )
        hashes = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in canonical_files
        }
        self._write_json(
            output_dir / "reproducibility_report.json",
            {"files": hashes},
        )
        return diagnosis_payload


def assert_truth_exclusion(payload: Mapping[str, object]) -> None:
    encoded = json.dumps(payload, sort_keys=True).lower()
    leaked = [key for key in FORBIDDEN_DIAGNOSTIC_KEYS if key in encoded]
    if leaked:
        raise AssertionError(
            f"Diagnostic artifact contains forbidden truth keys: {leaked}"
        )
