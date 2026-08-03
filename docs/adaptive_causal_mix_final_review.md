# Adaptive Causal-Mix ALNS: locked final review (seeds 900--939)

## Outline

- Verify the once-only four-family final packages and provenance.
- Test the predeclared +1% non-inferiority claim against K=18 periodic.
- Compare adaptive search with fixed causal bias and uniform full replanning.
- Audit exact visit lineage, executed removals, operator learning, and compute.
- Identify the defensible manuscript conclusion and next research direction.

## Final verdict

Adaptive Causal-Mix ALNS is implemented correctly but fails as an optimization
method.  On the untouched final block it is 17.88% worse in true deprivation
than 18-call/60-iteration periodic full replanning (paired 95% CI +11.67% to
+24.09%, `p < 10^-6`).  It also takes effectively the same repair time: 11.464
seconds versus 11.315 seconds.  The method therefore fails both superiority
and the predeclared +1% non-inferiority criterion, and it cannot support a
compute--quality claim.

The final result agrees with four-family confirmation (+16.26%, 95% CI +9.67%
to +22.84%).  More tuning on final seeds is prohibited and scientifically
unjustified.

## Protocol and integrity

- Initial implementation: commit `7a6db20`.
- A concrete visit-lineage defect invalidated the partial 800--809 screen.
- The defect was fixed and regression-tested at commit `36a3b5c`.
- The predeclared reserve 830--839 was used once for replacement screening.
- Selected decay 0.35 and minimum operator probability 0.35 were frozen at
  commit `656cac5`.
- Confirmation used untouched seeds 810--829; final used untouched seeds
  900--939 once.
- Each final family contains 320 rows (40 seeds times 8 methods), for 1,280
  final episodes in total.
- All final episodes have zero recorded feasibility violations.
- Every provenance record reports clean commit `bd13809`; every manifest hash
  was recomputed successfully.
- Corridor and mixed scenarios average 4.22 and 4.88 realized closures per
  episode, both inside the predeclared 3--6 calibration band.

Final packages are under
`results/adaptive_causal_mix_cycle_final_900_939/{standard,info_obsolescence,corridor_disruption,mixed_info_disruption}`.

## Final paired effects

Effects average the four families within each seed before inference.  Negative
deprivation favors Adaptive Causal-Mix ALNS.  Secondary comparisons are
exploratory and are not multiplicity adjusted.

| Comparator | Relative deprivation | 95% CI | Call delta | Repair-time delta | Result |
|---|---:|---:|---:|---:|---|
| Fixed causal-bias soft boundary | +13.50% | +7.19% to +19.81% | -0.15 | +4.04 s | Significantly worse |
| Same-trigger-rule uniform full replan | +17.77% | +11.43% to +24.11% | -0.11 | +0.93 s | Significantly worse |
| Exogenous-gated adaptive mix | +1.40% | -3.55% to +6.34% | +4.75 | +3.86 s | No quality benefit for extra compute |
| Exogenous-gated uniform full replan | +14.51% | +8.23% to +20.79% | +4.41 | +5.17 s | Significantly worse |
| 18-call/60-iteration periodic | +17.88% | +11.67% to +24.09% | -0.91 | +0.15 s | Fails non-inferiority and compute claim |
| 18-call/40-iteration periodic | +18.17% | +11.73% to +24.62% | -0.90 | +3.50 s | Significantly worse |
| 2-hour periodic | +13.71% | +6.61% to +20.80% | +12.09 | +8.56 s | Worse despite much more compute |

The adaptive penalty versus full-budget periodic is positive in every family:
+19.80% (standard), +10.77% (information obsolescence), +26.67% (corridor
disruption), and +14.29% (mixed).  Only one of 40 blocked seed comparisons
favors adaptive repair.

| Method | Mean deprivation | Mean calls | Mean repair time | Mean fill rate |
|---|---:|---:|---:|---:|
| Same-trigger-rule uniform full replan | 31,369.6 | 17.19 | 10.54 s | 0.4447 |
| K=18 periodic, 60 iterations | 31,429.0 | 18.00 | 11.31 s | 0.4504 |
| K=18 periodic, 40 iterations | 31,439.2 | 17.99 | 7.96 s | 0.4523 |
| Exogenous-gated uniform full replan | 32,268.2 | 12.68 | 6.29 s | 0.4396 |
| Fixed causal-bias soft boundary | 32,402.4 | 17.24 | 7.42 s | 0.4320 |
| 2-hour periodic full replan | 32,546.6 | 5.00 | 2.91 s | 0.4336 |
| Adaptive causal mix | 36,778.8 | 17.09 | 11.46 s | 0.3784 |
| Exogenous-gated adaptive mix | 37,052.2 | 12.34 | 7.61 s | 0.3839 |

The 40-iteration periodic point is 30.5% faster than adaptive repair and thus
falls outside the predeclared +/-15% wall-match band.  It must be reported as a
lower-compute point, not as an equal-time comparison.

## Mechanism and code audit

The negative result is not caused by a disabled adaptive operator or favorable
accounting shortcut.

- All 2,734 attempted adaptive transactions used exactly one solver call.
- Causal and global operators were selected 82,067 and 81,973 times.
- Their new-best rates were 3.48% and 3.17%; the mean final causal probability
  remained 0.500.
- Causal destroy removed causal-tier visits in 60.8% of removals, versus 38.3%
  for uniform global destroy.
- Exact `(UAV, sortie, visit)` profiles are attached before search and lineage
  is preserved through both destroy operators and greedy reinsertion.
- Only 22 attempted transactions had an empty incumbent profile.
- Infeasible candidates are rejected before installation; final episode
  violations are zero.
- A fresh targeted regression run passes 16/16 tests.  The complete non-Torch
  simulator/planner suite previously passed 110/110 after the final source
  fix.  Full collection remains unavailable because the local Torch import
  aborts before pytest collection, an unrelated pre-existing environment
  failure.

The mechanism works, but its internal search rewards do not translate into
mission quality.  The causal and global operators receive almost equal
new-best rates, while retaining an incumbent and applying repeated 30% destroy
moves is substantially weaker than rebuilding the full scaffold.  The loss is
largest under corridor disruption, contradicting the intended benefit of
event-causal localization.

## Claim--evidence map

- **Claim:** removal profiles use exact visit identities and survive repair. |
  **Evidence:** code path, regression tests, and nonzero executed-tier logs. |
  **Status:** supported technically.
- **Claim:** adaptive learning uses both causal and uniform global operators. |
  **Evidence:** nearly equal final selections and measured operator-specific
  removal distributions. | **Status:** supported technically.
- **Claim:** adaptive mixing improves fixed causal bias. | **Evidence:**
  +13.50% deprivation and +4.04 seconds. | **Status:** contradicted.
- **Claim:** adaptive mixing improves uniform full replanning. | **Evidence:**
  +17.77% deprivation and +0.93 seconds. | **Status:** contradicted.
- **Claim:** adaptive repair preserves K=18 quality at lower compute. |
  **Evidence:** +17.88% deprivation and essentially equal repair time. |
  **Status:** contradicted.
- **Claim:** causal localization is especially useful under disruption. |
  **Evidence:** +26.67% versus K=18 in corridor disruption with calibrated
  closures. | **Status:** strongly contradicted.

## Adversarial self-review

- **Contribution:** the visit-exact adaptive portfolio is reproducible, but it
  contributes a negative finding rather than a competitive method.
- **Writing clarity:** pass if the manuscript distinguishes same trigger rule
  from identical trigger timestamps and reports the invalidated screen.
- **Experimental strength:** pass for the negative conclusion; screening,
  confirmation, and final data are separated, strong baselines are included,
  and final effects are paired.
- **Evaluation completeness:** pass for the tested architecture; both trigger
  and search ablations, equal-call and lower-compute periodic points, four
  scenario families, feasibility, and mechanism logs are present.
- **Method soundness:** technically pass but empirically fail; added causal
  structure increases time and severely reduces quality.

## Recommended manuscript and research decision

Do not present Adaptive Causal-Mix ALNS, fixed causal freezing, or soft
boundaries as the manuscript's winning algorithm.  Do not run another decay,
probability, or threshold sweep on any used seed block.  The defensible result
is that localized incumbent repair is inferior to global reconstruction for
this simulator and lightweight ALNS.

The only event-triggered direction close to the strong baseline is
same-trigger-rule uniform full replanning: it is +0.40% versus K=18 periodic
(95% CI -1.11% to +1.92%) while saving 0.81 calls and 0.78 seconds.  It still
misses the strict +1% non-inferiority criterion, so this is a promising lead,
not a positive claim.

For the current manuscript, either:

1. frame the causal variants as preregistered negative ablations and make the
   empirical lesson---global reconstruction dominates causal localization---
   explicit; or
2. return the headline method to proxy-triggered global full replanning and
   run a new, separately preregistered trigger-design cycle on new seeds.

Further work should focus on trigger calibration for global replanning or on a
stronger global optimizer.  Another repair-boundary redesign is not supported
by the accumulated hard-freeze, soft-boundary, and adaptive-mix evidence.
