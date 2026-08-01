"""Pure tests for the locked fixed-versus-unguided benchmark decision."""

from __future__ import annotations

import pytest

from scripts.run_locked_guidance_benchmark import (
    paired_bootstrap_interval,
    promotion_decision,
)


def _rows(reductions, *, fixed_fill=0.20, fixed_violations=0):
    rows = []
    for seed, reduction in enumerate(reductions, 1):
        unguided = 100.0
        rows.append(
            {
                "seed": seed,
                "unguided_J_dep_true": unguided,
                "fixed_J_dep_true": unguided - reduction,
                "unguided_fill_rate": 0.20,
                "fixed_fill_rate": fixed_fill,
                "unguided_feasibility_violations": 0,
                "fixed_feasibility_violations": fixed_violations,
            }
        )
    return rows


def test_paired_bootstrap_is_deterministic_and_paired():
    first = paired_bootstrap_interval(
        [4.0, 5.0, 6.0],
        confidence=0.95,
        samples=1000,
        seed=7,
    )
    second = paired_bootstrap_interval(
        [4.0, 5.0, 6.0],
        confidence=0.95,
        samples=1000,
        seed=7,
    )
    assert first == second
    assert first["mean"] == pytest.approx(5.0)
    assert first["ci_low"] > 0.0


def test_fixed_is_promoted_only_when_every_rule_passes():
    decision = promotion_decision(_rows([8.0] * 40))
    assert decision["decision"] == "PROMOTE_FIXED_GUIDANCE"
    assert all(decision["checks"].values())
    assert decision["production_policy"]["production_gate"] == 0.5
    assert decision["adaptive_guidance"]["evaluated"] is False


@pytest.mark.parametrize(
    "rows,failed_check",
    [
        (
            _rows([4.0] * 40),
            "mean_deprivation_reduction_at_least_5_percent",
        ),
        (
            _rows([8.0] * 40, fixed_fill=0.19),
            "fill_rate_not_worse",
        ),
        (
            _rows([8.0] * 40, fixed_violations=1),
            "no_additional_feasibility_violations",
        ),
        (
            _rows([80.0, 80.0] + [-1.0] * 38),
            "improvement_seen_on_at_least_60_percent_of_seeds",
        ),
    ],
)
def test_failed_guardrail_retains_unguided(rows, failed_check):
    decision = promotion_decision(rows)
    assert decision["decision"] == "RETAIN_UNGUIDED_GRAPH_MAPPO"
    assert decision["checks"][failed_check] is False
    assert decision["production_policy"]["production_gate"] == 0.0
