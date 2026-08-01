import numpy as np

from scripts.calibrate_guidance_strength import (
    _boosted_probability,
    evaluate_beta,
)
from scripts.check_guidance_pilot_acceptance import evaluate_acceptance


def test_one_hot_boost_probability_matches_full_softmax():
    logits = np.asarray([0.2, -0.4, 1.1], dtype=float)
    base = np.exp(logits - logits.max())
    base /= base.sum()
    boost = 1.7
    boosted = logits.copy()
    boosted[1] += boost
    expected = np.exp(boosted - boosted.max())
    expected /= expected.sum()
    actual = _boosted_probability(
        np.asarray([base[1]]),
        np.asarray([boost]),
    )
    np.testing.assert_allclose(
        actual[0], expected[1], rtol=0.0, atol=1e-12
    )


def test_calibrated_beta_requires_measurable_controlled_fresh_effect():
    states = {
        "profile": np.asarray(
            ["fresh_valid_plan", "combined_stale_deviated"], dtype=object
        ),
        "gate": np.asarray([0.8, 0.2]),
        "base_probability": np.asarray(
            [1.0 / (1.0 + np.exp(2.0))] * 2
        ),
        "base_follows": np.asarray([False, False]),
        "logit_gap": np.asarray([2.0, 2.0]),
    }
    result = evaluate_beta(
        states,
        2.6,
        minimum_tv=0.003,
        minimum_argmax_change=0.01,
        maximum_argmax_change=0.75,
        minimum_fresh_stale_gap=0.05,
        maximum_saturation=0.05,
    )
    assert result["eligible"] == 1
    assert result["fresh_adaptive_follow_rate"] == 1.0
    assert result["combined_stale_adaptive_follow_rate"] == 0.0
    assert result["adaptive_unguided_argmax_change_rate"] == 0.5


def test_pilot_acceptance_reports_each_predeclared_criterion():
    metrics = {
        "invalid_conditions": [],
        "gate_gradients_finite_nonzero": True,
        "paired_effect": 0.20,
        "paired_ci_low": 0.20,
        "stale_regimes_below_fresh": 4,
        "matched_profile_median_adaptive_fixed_tv": 0.01,
        "matched_profile_adaptive_fixed_argmax_rate": 0.02,
        "matched_profile_adaptive_unguided_argmax_rate": 0.04,
        "matched_fresh_minus_stale_follow_rate": 0.20,
        "matched_recommended_probability_saturation_rate": 0.0,
        "development_stability_ok": True,
        "adaptive_true_deprivation": 90.0,
        "fixed_true_deprivation": 100.0,
        "adaptive_fill_rate": 0.30,
        "fixed_fill_rate": 0.25,
        "adaptive_reward": -900.0,
        "fixed_reward": -1000.0,
    }
    audit = evaluate_acceptance(metrics)
    assert audit["status"] == "PILOT_ACCEPTED"
    assert all(audit["checks"].values())

    metrics["matched_profile_adaptive_unguided_argmax_rate"] = 0.50
    rejected = evaluate_acceptance(metrics)
    assert rejected["status"] == "PILOT_REJECTED"
    assert "controlled_adaptive_unguided_argmax_change" in rejected[
        "failed_checks"
    ]

    metrics["matched_profile_adaptive_unguided_argmax_rate"] = 0.04
    metrics["adaptive_true_deprivation"] = 110.0
    rejected = evaluate_acceptance(metrics)
    assert "logistics_competitive_with_fixed_guidance" in rejected[
        "failed_checks"
    ]
