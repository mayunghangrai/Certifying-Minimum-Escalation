"""Offline analysis utilities for the adaptive-gate development experiment.

Regime names in this module are analysis metadata only.  They are never added
to observations, belief graphs, action masks, or model inputs.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence

import numpy as np

from env.scenario import P1Report, Replenishment, Scenario
from methods.adaptive_gate_diagnostics import (
    FEATURE_SCHEMA,
    counterfactual_policy,
)
from methods.belief_graph import PLAN_FEATURE_NAMES


TRAINING_SEEDS = tuple(range(18440, 18480))
VALIDATION_SEEDS = tuple(range(18480, 18490))
QUALITATIVE_AUDIT_SEED = 18427
REGIME_FIXTURE_VERSION = "operational-regime-fixtures-v1"

REGIMES = (
    "FRESH_AND_STABLE",
    "DEMAND_UPDATED_BUT_FEASIBLE",
    "NEW_NODE_REVEALED",
    "INVENTORY_CHANGED",
    "EXECUTION_DEVIATION",
    "PARTIALLY_INVALID_PLAN",
    "MIXED_OPERATIONAL_CHANGE",
)

PRIMARY_FEATURES = (
    "plan_age",
    "operational_demand_change",
    "operational_inventory_change",
    "newly_known_fraction",
    "invalid_planned_corridor_fraction",
    "execution_deviation",
    "next_action_operationally_feasible",
)

VERDICTS = (
    "KEEP_EXISTING_ADAPTIVE_GATE",
    "GATE_LEARNED_POLICY_INERT",
    "MORE_TRAINING_REQUIRED",
    "WRONG_DIRECTION_GATE",
    "ACTOR_GATE_IDENTIFIABILITY_PROBLEM",
    "FIXED_GUIDANCE_SUFFICIENT",
    "TRAINING_OR_IMPLEMENTATION_FAILURE",
)


def development_seed_split() -> Dict[str, object]:
    """Return the canonical, immutable development split."""
    split = {
        "training_seeds": list(TRAINING_SEEDS),
        "validation_seeds": list(VALIDATION_SEEDS),
        "qualitative_audit_seed": QUALITATIVE_AUDIT_SEED,
        "reserved_seed_policy": (
            "All other future benchmark seeds remain unused by this "
            "development experiment."
        ),
    }
    assert not set(TRAINING_SEEDS) & set(VALIDATION_SEEDS)
    assert QUALITATIVE_AUDIT_SEED not in TRAINING_SEEDS
    assert QUALITATIVE_AUDIT_SEED not in VALIDATION_SEEDS
    return split


def episode_assignments(episodes: int) -> List[Dict[str, object]]:
    """Balanced deterministic episode/seed/regime assignments."""
    if episodes < 1:
        raise ValueError("episodes must be positive")
    rows = []
    for index in range(episodes):
        rows.append(
            {
                "episode": index + 1,
                "scenario_seed": TRAINING_SEEDS[index % len(TRAINING_SEEDS)],
                "target_regime": REGIMES[index % len(REGIMES)],
                "scenario_repeat": index // len(TRAINING_SEEDS),
            }
        )
    if episodes >= 70:
        counts = Counter(row["target_regime"] for row in rows)
        for regime in REGIMES[1:]:
            if counts[regime] / episodes < 0.10:
                raise AssertionError(
                    f"Non-stable regime {regime} below 10%: "
                    f"{counts[regime]}/{episodes}"
                )
    return rows


def validation_assignments(
    repeats_per_seed: int = 1,
    all_regimes: bool = False,
) -> List[Dict[str, object]]:
    """Deterministic validation assignment table.

    The final validation pass can cross every validation seed with every
    offline regime target.  This extends sampling without introducing new
    benchmark seeds.
    """
    if repeats_per_seed < 1:
        raise ValueError("repeats_per_seed must be positive")
    rows = []
    index = 0
    regimes = REGIMES if all_regimes else (None,)
    for repeat in range(repeats_per_seed):
        for seed_index, seed in enumerate(VALIDATION_SEEDS):
            for regime in regimes:
                rows.append(
                    {
                        "validation_episode": index + 1,
                        "scenario_seed": seed,
                        "target_regime": (
                            regime
                            if regime is not None
                            else REGIMES[seed_index % len(REGIMES)]
                        ),
                        "repeat": repeat,
                    }
                )
                index += 1
    return rows


def regime_intervention_time(params) -> float:
    """Time of the controlled observable change, after initial loading."""
    t = float(params.mission.T_load) + 0.005
    if not 0.0 < t < float(params.mission.T):
        raise ValueError(
            "Regime fixture requires T_load + 0.005 strictly inside the horizon"
        )
    return t


def _controlled_report(scenario: Scenario, t: float, *, scale: float) -> P1Report:
    known = sorted(
        (node for node in scenario.nodes if node.reveal_time <= 0.0),
        key=lambda node: node.idx,
    )
    if not known:
        raise AssertionError("Regime fixture requires an initially known node")
    node = known[0]
    true = np.asarray(node.d0, dtype=float)
    assessed = np.asarray(node.mu0, dtype=float)
    delta = scale * np.maximum(assessed, 1.0)
    # At fixture construction this fully specifies the report mark. The
    # environment still forms y=d(t)+eps at reception, exactly as for P1.
    eps = assessed + delta - true
    return P1Report(
        t=float(t),
        node=int(node.idx),
        eps=[float(value) for value in eps],
        gamma=0.9,
    )


def build_regime_intervention(
    scenario: Scenario,
    target_regime: str,
    params,
) -> Scenario:
    """Create a deterministic operational fixture before episode replay.

    The fixture changes the scenario/event state, never a gate feature or
    regime label in the policy input. All intervention marks are constructed
    before ``env.reset`` and contain no runtime random sampling.
    """
    if target_regime not in REGIMES:
        return scenario
    fixture = copy.deepcopy(scenario)
    t = regime_intervention_time(params)
    beyond_horizon = float(params.mission.T) + 1.0

    hidden = sorted(
        (node for node in fixture.nodes if float(node.reveal_time) > 0.0),
        key=lambda node: node.idx,
    )
    for node in hidden:
        node.reveal_time = beyond_horizon

    fixture.p1_reports = []
    fixture.avail_changes = []
    fixture.replenishments = []

    if target_regime in {
        "DEMAND_UPDATED_BUT_FEASIBLE",
        "EXECUTION_DEVIATION",
        "MIXED_OPERATIONAL_CHANGE",
    }:
        fixture.p1_reports.append(
            _controlled_report(fixture, t, scale=0.25)
        )
    if target_regime == "EXECUTION_DEVIATION":
        fixture.p1_reports.append(
            _controlled_report(fixture, t + 0.002, scale=0.40)
        )
    if target_regime in {"NEW_NODE_REVEALED", "MIXED_OPERATIONAL_CHANGE"}:
        if not hidden:
            raise AssertionError("P2 fixture requires a hidden scenario node")
        hidden[0].reveal_time = t
    if target_regime in {"INVENTORY_CHANGED", "MIXED_OPERATIONAL_CHANGE"}:
        stock = np.asarray(fixture.S0_init, dtype=float)
        addition = np.maximum(np.ceil(0.10 * stock), 1.0)
        fixture.replenishments.append(
            Replenishment(t=t, R=[float(value) for value in addition])
        )

    fixture.p1_reports.sort(key=lambda event: event.t)
    fixture.replenishments.sort(key=lambda event: event.t)
    return fixture


def regime_intervention_manifest(
    scenario: Scenario,
    params,
) -> Dict[str, Dict[str, object]]:
    """Return hashes and explicit actions for every deterministic fixture."""
    actions = {
        "FRESH_AND_STABLE": ["suppress observable exogenous changes"],
        "DEMAND_UPDATED_BUT_FEASIBLE": ["controlled pre-sampled P1 reception"],
        "NEW_NODE_REVEALED": ["controlled pre-sampled P2 reception"],
        "INVENTORY_CHANGED": ["controlled pre-sampled replenishment"],
        "EXECUTION_DEVIATION": [
            "two controlled P1 receptions while execution is under way"
        ],
        "PARTIALLY_INVALID_PLAN": [
            "close a deterministic later incumbent-plan leg"
        ],
        "MIXED_OPERATIONAL_CHANGE": [
            "controlled P1, P2, replenishment, and later-leg closure"
        ],
    }
    return {
        regime: {
            "fixture_version": REGIME_FIXTURE_VERSION,
            "intervention_time_h": regime_intervention_time(params),
            "actions": actions[regime],
            "content_hash": build_regime_intervention(
                scenario, regime, params
            ).content_hash(),
            "randomness_sampled_after_reset": False,
        }
        for regime in REGIMES
    }


def prior_feasible_regime_counts(
    rows: Sequence[Mapping[str, object]],
) -> Dict[str, int]:
    """Count usable gate decisions by their actual operational regime."""
    counts = Counter(
        str(row["regime"])
        for row in rows
        if int(row["prior_nonzero"])
        and int(row["recommended_action_feasible"])
    )
    return {regime: int(counts.get(regime, 0)) for regime in REGIMES}


def assert_regime_coverage(
    rows: Sequence[Mapping[str, object]],
    required: Mapping[str, int],
    *,
    phase: str,
) -> Dict[str, int]:
    """Fail loudly when an actual usable regime cohort is undersampled."""
    counts = prior_feasible_regime_counts(rows)
    failures = [
        f"{regime}={counts.get(regime, 0)}<{int(minimum)}"
        for regime, minimum in required.items()
        if counts.get(regime, 0) < int(minimum)
    ]
    if failures:
        raise AssertionError(
            f"{phase} prior-bearing feasible regime coverage failed: "
            + ", ".join(failures)
        )
    return counts


def _feature(row: Mapping[str, object], name: str) -> float:
    for key in (name, f"{name}__normalized"):
        if key in row:
            return float(row[key])
    return 0.0


def classify_operational_regime(
    row: Mapping[str, object],
    target_regime: str | None = None,
) -> str:
    """Classify a decision from operational gate inputs only."""
    demand = _feature(row, "operational_demand_change")
    inventory = _feature(row, "operational_inventory_change")
    new_nodes = _feature(row, "newly_known_fraction")
    invalid = _feature(row, "invalid_planned_corridor_fraction")
    deviation = _feature(row, "execution_deviation")
    changed = sum(
        value > 1e-8
        for value in (demand, inventory, new_nodes, invalid, deviation)
    )
    # A balanced offline target may disaggregate simultaneous observable
    # changes.  It is accepted only when that regime's real operational
    # condition is present; otherwise classification falls back below.
    target_supported = {
        "FRESH_AND_STABLE": changed == 0,
        "DEMAND_UPDATED_BUT_FEASIBLE": (
            demand > 1e-8
            and _feature(row, "next_action_operationally_feasible") > 0.5
        ),
        "NEW_NODE_REVEALED": new_nodes > 1e-8,
        "INVENTORY_CHANGED": inventory > 1e-8,
        "EXECUTION_DEVIATION": deviation > 1e-8,
        "PARTIALLY_INVALID_PLAN": (
            invalid > 1e-8
            and _feature(row, "next_action_operationally_feasible") > 0.5
        ),
        "MIXED_OPERATIONAL_CHANGE": changed >= 2,
    }
    if (
        target_regime in target_supported
        and target_supported[str(target_regime)]
    ):
        return str(target_regime)
    if changed >= 2:
        return "MIXED_OPERATIONAL_CHANGE"
    if invalid > 1e-8:
        return "PARTIALLY_INVALID_PLAN"
    if deviation > 1e-8:
        return "EXECUTION_DEVIATION"
    if new_nodes > 1e-8:
        return "NEW_NODE_REVEALED"
    if inventory > 1e-8:
        return "INVENTORY_CHANGED"
    if demand > 1e-8:
        return "DEMAND_UPDATED_BUT_FEASIBLE"
    return "FRESH_AND_STABLE"


def bootstrap_mean_interval(
    values: Sequence[float],
    *,
    seed: int = 18427,
    samples: int = 2000,
    confidence: float = 0.95,
) -> Dict[str, float]:
    array = np.asarray(values, dtype=float)
    if not len(array):
        return {"mean": math.nan, "ci_low": math.nan, "ci_high": math.nan}
    rng = np.random.default_rng(seed)
    draws = rng.choice(array, size=(samples, len(array)), replace=True).mean(axis=1)
    tail = (1.0 - confidence) / 2.0
    return {
        "mean": float(array.mean()),
        "ci_low": float(np.quantile(draws, tail)),
        "ci_high": float(np.quantile(draws, 1.0 - tail)),
    }


def _summary(values: np.ndarray) -> Dict[str, float]:
    if not len(values):
        return {
            key: math.nan
            for key in (
                "mean",
                "median",
                "standard_deviation",
                "p05",
                "p25",
                "p75",
                "p95",
                "ci_low",
                "ci_high",
            )
        }
    ci = bootstrap_mean_interval(values)
    return {
        "mean": float(values.mean()),
        "median": float(np.median(values)),
        "standard_deviation": float(values.std()),
        "p05": float(np.quantile(values, 0.05)),
        "p25": float(np.quantile(values, 0.25)),
        "p75": float(np.quantile(values, 0.75)),
        "p95": float(np.quantile(values, 0.95)),
        "ci_low": ci["ci_low"],
        "ci_high": ci["ci_high"],
    }


def regime_gate_summary(
    rows: Sequence[Mapping[str, object]],
) -> List[Dict[str, object]]:
    output = []
    for regime in REGIMES:
        subset = [
            row
            for row in rows
            if row["regime"] == regime
            and int(row.get("prior_nonzero", 0))
            and int(row.get("recommended_action_feasible", 0))
        ]
        values = np.asarray([float(row["gate_adaptive"]) for row in subset])
        output.append(
            {
                "regime": regime,
                "decision_count": len(subset),
                **_summary(values),
            }
        )
    return output


def _rank(values: np.ndarray) -> np.ndarray:
    """Average ranks with deterministic tie handling."""
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = 0.5 * (start + end - 1)
        start = end
    return ranks


def spearman_correlation(x: Sequence[float], y: Sequence[float]) -> float:
    left = np.asarray(x, dtype=float)
    right = np.asarray(y, dtype=float)
    if len(left) < 2 or left.std() <= 1e-15 or right.std() <= 1e-15:
        return math.nan
    return float(np.corrcoef(_rank(left), _rank(right))[0, 1])


def feature_relationship_rows(
    decision_rows: Sequence[Mapping[str, object]],
) -> List[Dict[str, object]]:
    output = []
    gates = np.asarray([float(row["gate_adaptive"]) for row in decision_rows])
    for feature in PRIMARY_FEATURES:
        values = np.asarray([_feature(row, feature) for row in decision_rows])
        correlation = spearman_correlation(values, gates)
        if len(values):
            edges = np.unique(np.quantile(values, [0.0, 0.25, 0.5, 0.75, 1.0]))
        else:
            edges = np.asarray([])
        if len(edges) < 2:
            output.append(
                {
                    "feature": feature,
                    "spearman": correlation,
                    "bin": 0,
                    "bin_low": float(values[0]) if len(values) else math.nan,
                    "bin_high": float(values[0]) if len(values) else math.nan,
                    "count": len(values),
                    "mean_gate": float(gates.mean()) if len(gates) else math.nan,
                }
            )
            continue
        for index, (low, high) in enumerate(zip(edges[:-1], edges[1:])):
            keep = (values >= low) & (
                values <= high if index == len(edges) - 2 else values < high
            )
            output.append(
                {
                    "feature": feature,
                    "spearman": correlation,
                    "bin": index,
                    "bin_low": float(low),
                    "bin_high": float(high),
                    "count": int(keep.sum()),
                    "mean_gate": (
                        float(gates[keep].mean()) if keep.any() else math.nan
                    ),
                }
            )
    return output


def matched_feature_profiles(
    original: Sequence[float],
) -> Dict[str, np.ndarray]:
    """Construct paired operational plan-status variants only."""
    base = np.asarray(original, dtype=float).copy()
    if base.shape != (len(PLAN_FEATURE_NAMES),):
        raise ValueError("plan-feature vector has wrong shape")
    indices = {name: index for index, name in enumerate(PLAN_FEATURE_NAMES)}
    fresh = base.copy()
    for name in (
        "plan_age",
        "operational_demand_change",
        "operational_inventory_change",
        "newly_known_fraction",
        "invalid_planned_corridor_fraction",
        "completed_planned_service_fraction",
        "execution_deviation",
        "solver_active",
        "solver_request_age",
    ):
        fresh[indices[name]] = 0.0
    fresh[indices["next_action_operationally_feasible"]] = 1.0

    def variant(**changes):
        values = fresh.copy()
        for name, value in changes.items():
            values[indices[name]] = float(value)
        return values

    return {
        "fresh_valid_plan": fresh,
        "old_valid_plan": variant(plan_age=1.0),
        "demand_changed_plan": variant(operational_demand_change=1.0),
        "inventory_changed_plan": variant(operational_inventory_change=1.0),
        "newly_revealed_node": variant(newly_known_fraction=1.0),
        "high_execution_deviation": variant(execution_deviation=1.0),
        "later_corridor_invalid_current_feasible": variant(
            invalid_planned_corridor_fraction=1.0,
            next_action_operationally_feasible=1.0,
        ),
        "combined_stale_deviated": variant(
            plan_age=1.0,
            operational_demand_change=1.0,
            operational_inventory_change=1.0,
            newly_known_fraction=1.0,
            invalid_planned_corridor_fraction=1.0,
            execution_deviation=1.0,
            next_action_operationally_feasible=1.0,
        ),
    }


def evaluate_matched_states(
    actor,
    vector_rows: Sequence[Mapping[str, object]],
    *,
    max_states: int | None = None,
) -> tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """Evaluate plan-feature variants without advancing the environment."""
    import torch

    rows: List[Dict[str, object]] = []
    vectors: List[Dict[str, object]] = []
    eligible = [
        row
        for row in vector_rows
        if np.any(np.asarray(row["alns_prior"], dtype=float) > 0)
        and bool(np.asarray(row["action_mask"], dtype=bool)[
            int(row["recommended_action"])
        ])
    ]
    if max_states is not None:
        eligible = eligible[:max_states]
    device = next(actor.parameters()).device
    with torch.no_grad():
        for row in eligible:
            profiles = matched_feature_profiles(row["plan_features"])
            base_logits = np.asarray(row["base_logits"], dtype=float)
            prior = np.asarray(row["alns_prior"], dtype=float)
            mask = np.asarray(row["action_mask"], dtype=bool)
            recommendation = int(row["recommended_action"])
            for profile, features in profiles.items():
                tensor = torch.as_tensor(
                    features[None], dtype=torch.float32, device=device
                )
                gate_logit = float(actor.guidance_gate.logits(tensor)[0, 0])
                gate = float(torch.sigmoid(
                    actor.guidance_gate.logits(tensor)
                )[0, 0])
                policy = counterfactual_policy(
                    base_logits,
                    prior,
                    mask,
                    gate,
                    float(actor.fixed_gate),
                    float(actor.beta),
                )
                rows.append(
                    {
                        "decision_index": int(row["decision_index"]),
                        "scenario_seed": int(row["scenario_seed"]),
                        "profile": profile,
                        "gate_logit": gate_logit,
                        "gate_adaptive": gate,
                        "alns_action_probability": float(
                            policy["adaptive_probabilities"][recommendation]
                        ),
                        "kl_adaptive_fixed": policy["kl_adaptive_fixed"],
                        "tv_adaptive_fixed": policy["tv_adaptive_fixed"],
                        "tv_adaptive_unguided": policy[
                            "tv_adaptive_unguided"
                        ],
                        "adaptive_argmax": policy["adaptive_argmax"],
                        "fixed_argmax": policy["fixed_argmax"],
                        "unguided_argmax": policy["unguided_argmax"],
                        "adaptive_follows_alns": int(
                            policy["adaptive_argmax"] == recommendation
                        ),
                        "fixed_follows_alns": int(
                            policy["fixed_argmax"] == recommendation
                        ),
                        "unguided_follows_alns": int(
                            policy["unguided_argmax"] == recommendation
                        ),
                    }
                )
                vectors.append(
                    {
                        "decision_index": int(row["decision_index"]),
                        "profile": profile,
                        "plan_features": features.tolist(),
                        "base_logits": base_logits.tolist(),
                        "alns_prior": prior.tolist(),
                        "action_mask": mask.astype(int).tolist(),
                        "adaptive_probabilities": np.asarray(
                            policy["adaptive_probabilities"]
                        ).tolist(),
                    }
                )
    return rows, vectors


def paired_fresh_stale_effect(
    matched_rows: Sequence[Mapping[str, object]],
) -> Dict[str, object]:
    by_decision: Dict[int, Dict[str, float]] = {}
    for row in matched_rows:
        by_decision.setdefault(int(row["decision_index"]), {})[
            str(row["profile"])
        ] = float(row["gate_adaptive"])
    effects = []
    for profiles in by_decision.values():
        if (
            "fresh_valid_plan" in profiles
            and "combined_stale_deviated" in profiles
        ):
            effects.append(
                profiles["fresh_valid_plan"]
                - profiles["combined_stale_deviated"]
            )
    if not effects:
        raise AssertionError("No matched fresh/stale gate contrast was produced")
    unique_effects = sorted(set(float(value) for value in effects))
    if len(unique_effects) != 1:
        raise AssertionError(
            "The plan-feature-only gate produced non-identical effects for "
            "identical matched feature profiles"
        )
    effect = unique_effects[0]
    return {
        "pair_count": 1,
        "source_state_count": len(effects),
        "fresh_minus_stale_mean": effect,
        "ci_low": effect,
        "ci_high": effect,
        "uncertainty_method": "deterministic_exact_no_sampling_interval",
        "expected_direction": "positive",
    }


def select_gate_learning_verdict(
    metrics: Mapping[str, object],
) -> Dict[str, object]:
    """Return exactly one evidence-based development verdict."""
    failures = list(metrics.get("invalid_conditions", []))
    gradients_ok = bool(metrics.get("gate_gradients_finite_nonzero", False))
    if not gradients_ok:
        failures.append("gate_gradients_missing_nonfinite_or_zero")
    if failures:
        verdict = "TRAINING_OR_IMPLEMENTATION_FAILURE"
        rationale = (
            "One or more development-run validity checks failed: "
            + ", ".join(sorted(set(failures)))
            + "."
        )
    else:
        prior = float(metrics.get("prior_coverage", 0.0))
        prior_count = int(metrics.get("prior_bearing_decisions", 0))
        gate_std = float(metrics.get("gate_standard_deviation", 0.0))
        gate_diff = float(metrics.get("mean_abs_gate_minus_fixed", 0.0))
        pair_effect = float(metrics.get("paired_effect", 0.0))
        pair_low = float(metrics.get("paired_ci_low", -math.inf))
        pair_high = float(metrics.get("paired_ci_high", math.inf))
        lower_medians = int(metrics.get("stale_regimes_below_fresh", 0))
        median_tv = float(metrics.get("prior_median_adaptive_fixed_tv", 0.0))
        argmax = float(metrics.get("prior_adaptive_fixed_argmax_rate", 0.0))
        logistics_competitive = bool(
            metrics.get("logistics_competitive_with_fixed", False)
        )
        completed = int(metrics.get("episodes_completed", 0))
        planned = int(metrics.get("planned_episodes", 1000))
        direction_learned = all(
            (
                prior >= 0.30,
                prior_count >= 1000,
                gate_std >= 0.03 or gate_diff >= 0.03,
                pair_effect >= 0.05 and pair_low > 0.0,
                lower_medians >= 3,
                gradients_ok,
            )
        )
        learned = all(
            (
                direction_learned,
                median_tv >= 0.003 or argmax >= 0.01,
            )
        )
        if learned and logistics_competitive:
            verdict = "KEEP_EXISTING_ADAPTIVE_GATE"
            rationale = (
                "Gate-validity targets are supported and adaptive logistics "
                "performance is competitive with fixed guidance."
            )
        elif learned:
            verdict = "FIXED_GUIDANCE_SUFFICIENT"
            rationale = (
                "The adaptive gate passes its diagnostic targets but does not "
                "match the fixed branch on true deprivation, fill rate, and "
                "reward; retain fixed guidance as the guided baseline."
            )
        else:
            trend = float(metrics.get("gate_separation_trend", 0.0))
            matched_weak = pair_effect < 0.05 or pair_low <= 0.0
            gate_near_constant = gate_std < 0.03 and gate_diff < 0.03
            actor_absorption = bool(metrics.get("actor_absorbs_follow", False))
            policy_indistinguishable = median_tv < 0.003 and argmax < 0.01
            if completed >= 200 and pair_effect < 0.0 and pair_high < 0.0:
                verdict = "WRONG_DIRECTION_GATE"
                rationale = (
                    "The exact matched contrast is significantly opposite to "
                    "the required fresh-above-stale gate relationship."
                )
            elif (
                direction_learned
                and policy_indistinguishable
                and completed >= planned
            ):
                verdict = "GATE_LEARNED_POLICY_INERT"
                rationale = (
                    "The adaptive gate learned the required fresh-above-stale "
                    "relationship, but its logit intervention is too weak to "
                    "produce a measurable policy difference at the configured "
                    "guidance strength."
                )
            elif (
                gradients_ok
                and completed < planned
                and trend > 1e-4
                and pair_effect >= 0.0
            ):
                verdict = "MORE_TRAINING_REQUIRED"
                rationale = (
                    "Correct-direction gate separation is still increasing and "
                    "the maximum development duration has not been reached."
                )
            elif (
                gradients_ok
                and completed >= 200
                and gate_near_constant
                and matched_weak
                and actor_absorption
            ):
                verdict = "ACTOR_GATE_IDENTIFIABILITY_PROBLEM"
                rationale = (
                    "The actor absorbs ALNS-follow preference while matched "
                    "plan-status changes weakly affect the trained gate."
                )
            elif gate_near_constant and policy_indistinguishable:
                verdict = "FIXED_GUIDANCE_SUFFICIENT"
                rationale = (
                    "Adaptive guidance remains effectively indistinguishable "
                    "from the simpler fixed branch."
                )
            else:
                verdict = "MORE_TRAINING_REQUIRED"
                rationale = (
                    "Learning is valid but evidence is not yet sufficient for "
                    "retention or redesign."
                )
    if verdict not in VERDICTS:
        raise AssertionError(f"Unsupported verdict: {verdict}")
    return {
        "verdict": verdict,
        "rationale": rationale,
        "performance_claim": "development evidence only; no superiority claim",
    }


def canonical_json_hash(payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


assert tuple(item["name"] for item in FEATURE_SCHEMA) == PLAN_FEATURE_NAMES
