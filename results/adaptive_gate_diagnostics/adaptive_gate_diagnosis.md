# Adaptive-gate diagnosis

This report diagnoses gate mechanics only; it makes no performance claim.

## GATE_CLOSE_TO_FIXED (MEDIUM)

Adaptive gates remain numerically close to the fixed ablation.

Measured `mean_abs_gate_minus_fixed`: `0.011860361224726626`; threshold: `0.05`.

## PLAN_FEATURES_PARTIALLY_DEGENERATE (MEDIUM)

One or more plan-confidence inputs are constant/default/clipped dominated.

Measured `degenerate_feature_count`: `2`; threshold: `1`.

## SYNCHRONOUS_ALNS_FEATURE_LIMITATION (EXPECTED)

The real synchronous ALNS makes solver-state inputs degenerate.

Measured `solver_feature_variation`: `constant`; threshold: `variable only for asynchronous solver`.

## NO_SINGLE_DOMINANT_CAUSE (INFO)

Several measured mechanisms contribute to the identical smoke outcome.

Measured `classification_count`: `3`; threshold: `1`.
