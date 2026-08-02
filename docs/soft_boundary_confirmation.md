# Soft-boundary confirmation review (seeds 610--629)

## Outline

- Verify the four-family confirmation packages and frozen provenance.
- Test whether soft boundaries improve hard freezing.
- Test quality against identical-trigger and periodic full replanning.
- Check the predeclared +1% non-inferiority margin and compute trade-off.
- Decide whether a defect justifies using reserved seeds 630--639.

## Evidence

All four families contain exactly 120 rows (20 seeds times 6 methods), zero
feasibility violations, clean commit `457137d`, and valid manifest hashes.
Every attempted soft-boundary transaction used one solver call and recorded
decay 0.65.  No implementation or accounting defect was detected, so reserved
development seeds 630--639 remain unused.

Blocked paired effects average each family within seed before inference.
Negative deprivation differences favor the soft method.

| Comparator | Relative deprivation delta | 95% CI | Mean solver-call delta | Mean repair-time delta | Interpretation |
|---|---:|---:|---:|---:|---|
| Hard freezing | +0.33% | -1.48% to +2.13% | -3.58 | -1.44 s | No demonstrated improvement |
| Identical-trigger full replan | +3.19% | +0.40% to +5.98% | +0.07 | -3.13 s | Significantly worse quality |
| 18-call periodic full replan | +3.22% | +1.09% to +5.35% | -0.78 | -3.96 s | Significantly worse quality |
| 2-hour periodic full replan | -2.77% | -4.94% to -0.60% | +12.22 | +4.28 s | Better quality at much higher compute |

The upper confidence limit against equal-budget periodic is +5.35%, so the
selected method fails the predeclared +1% non-inferiority margin.  It reduces
repair wall time relative to the two strong full-replan comparators, but the
quality loss prevents a compute-quality claim.

## Claim-evidence map

- Claim: Soft boundaries remove the hard-freeze solver restriction. |
  Evidence: every nonempty incumbent receives positive weighted-node support,
  and each transaction uses one globally eligible weighted ALNS call. |
  Status: **supported technically**.
- Claim: Soft boundaries improve hard freezing. | Evidence: +0.33% blocked
  relative deprivation with a confidence interval spanning meaningful benefit
  and harm. | Status: **not supported**.
- Claim: Soft boundaries preserve full-replan quality at lower time. |
  Evidence: 3.19% worse deprivation despite 3.13 seconds lower repair time. |
  Status: **contradicted in confirmation**.
- Claim: Soft boundaries improve on a low-frequency periodic policy. |
  Evidence: 2.77% lower deprivation but 12.22 more solver calls. | Status:
  **supported only as a quality/compute trade-off, not dominance**.

## Adversarial self-review

- Contribution: needs revision; weighted causal destroy is implemented but has
  no confirmed advantage over hard freezing.
- Clarity: pass; the trigger is labeled heuristic and the boundary weights are
  explicit.
- Experimental strength: pass for development; comparisons are paired and use
  the strongest earlier baselines.
- Evaluation completeness: final untouched seeds remain required by protocol.
- Method soundness: technically pass, empirically weak; added structure does
  not yet yield positive net value.

## Decision

Freeze the selected implementation without modification and run the final
700--739 suite once.  Confirmation is negative, but there is no software defect
that would justify consuming the reserved development block or changing the
method before final evaluation.

