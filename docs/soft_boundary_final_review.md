# Soft-Boundary Event-Causal ALNS: locked final review

## Final verdict

The selected soft-boundary method is technically valid but empirically
unsuccessful as the primary algorithm.  On the untouched seeds 700--739 it is
3.10% worse in true deprivation than 18-call periodic full replanning (paired
95% CI +1.22% to +4.98%, `p = 0.0019`).  The upper confidence limit is far
above the predeclared +1% non-inferiority margin.  Therefore the lower repair
time cannot support a compute-quality claim.

The result is consistent with development confirmation (+3.22%, 95% CI
+1.09% to +5.35%).  More tuning of the decay or trigger on these final seeds
would be post-hoc and is not justified.

## Locked protocol and integrity

- Algorithm/configuration frozen before the final run at commit `7552d93`.
- Final seeds: 700--739; four scenario families; six declared methods.
- Each family contains exactly 240 episode rows (40 seeds times 6 methods).
- All 960 episodes have zero recorded feasibility violations.
- All four provenance records report a clean Git tree and commit `7552d93`.
- Every artifact hash in every run manifest was recomputed successfully.
- Development reserve seeds 630--639 were not used because no concrete defect
  was found.
- Realized disruption exposure is material: the corridor and mixed families
  average 5.35 and 4.28 closures per episode, respectively, both within the
  predeclared 3--6 calibration band.

The result packages are under
`results/soft_boundary_cycle_final_700_739/{standard,info_obsolescence,corridor_disruption,mixed_info_disruption}`.

## Primary and secondary effects

Effects are computed by taking the paired relative difference within each
family and seed, averaging the four families within seed, and performing
inference across the 40 seed blocks.  Negative deprivation favors the soft
method.  Secondary comparisons are exploratory and are not multiplicity
adjusted.

| Comparator | Relative deprivation delta | 95% CI | Solver-call delta | Repair-time delta | Interpretation |
|---|---:|---:|---:|---:|---|
| Hard-freeze event-causal ALNS | -0.30% | -1.98% to +1.39% | -4.24 | -1.91 s | No demonstrated quality improvement |
| Same-trigger-rule full replan ALNS | +1.52% | -0.03% to +3.07% | +0.03 | -2.96 s | Faster, but likely worse quality |
| 18-call periodic full replan ALNS | +3.10% | +1.22% to +4.98% | -0.73 | -3.79 s | Significantly worse; fails non-inferiority |
| 2-hour periodic full replan ALNS | -2.83% | -5.02% to -0.64% | +12.28 | +4.48 s | Better quality only by spending much more compute |
| Initial plan only | -38.54% | -40.71% to -36.37% | +17.28 | +7.41 s | Strong improvement over a weak static baseline |

The soft method's family-wise relative deprivation penalties versus 18-call
periodic replanning are +2.67% (standard), +2.08% (information obsolescence),
+4.55% (corridor disruption), and +3.09% (mixed).  The conclusion is not
driven by one family.

| Method | Mean deprivation | Mean solver calls | Mean repair time | Mean fill rate |
|---|---:|---:|---:|---:|
| 18-call periodic full replan | 29,508.2 | 18.00 | 11.20 s | 0.4585 |
| Same-trigger-rule full replan | 29,934.9 | 17.24 | 10.37 s | 0.4495 |
| Soft-boundary event-causal | 30,348.8 | 17.28 | 7.41 s | 0.4416 |
| Hard-freeze event-causal | 30,475.5 | 21.51 | 9.32 s | 0.4431 |
| 2-hour periodic full replan | 31,306.2 | 4.99 | 2.93 s | 0.4336 |
| Initial plan only | 49,023.8 | 0.00 | 0.00 s | 0.2640 |

## Code and diagnostic review

The favorable runtime is genuine rather than an accounting artifact.

- All future visits remain destroy-eligible because the four removal weights
  are strictly positive.  At the selected decay 0.65, the weights are 1.0,
  0.65, 0.4225, and 0.274625 from causal to global decisions.
- The soft method makes one ALNS call per attempted repair.  Across the final
  suite, 2,764 attempted repair transactions produced exactly 2,764 solver
  calls.
- Candidate feasibility is checked before installation.  Infeasible
  candidates were rejected and the episode-level violation count remained
  zero.
- Causal scopes average roughly one third of the incumbent decision graph, so
  the experiment exercised nontrivial localization.
- Scenario reuse, deterministic method-order randomization, centralized
  solver-call accounting, and manifest provenance were inspected; no leakage,
  disabled repair path, or comparator-specific feasibility shortcut was
  found.
- A fresh targeted regression run passed 13/13 tests; the earlier broad
  regression run passed 115 tests after excluding pre-existing tests whose
  scripts had already been moved to `scripts/Old`.

Two limitations narrow the claim even though they do not invalidate the run.

1. Removal weights are keyed by `(UAV, node)`, not the full decision identity.
   Repeated visits by one UAV to the same node therefore share a weight.  The
   implementation is causally biased, but not visit-exact.
2. "Identical-trigger" in the result labels means the same trigger rule, not
   guaranteed identical trigger timestamps.  Different installed plans can
   change later fleet-service and feasibility events.  The manuscript should
   call this comparator **same-trigger-rule full replan** and should not present
   it as a perfectly isolated operator-only ablation.

The screening pattern is also informative: decay 0.65 outperformed the more
localized decay 0.35, while gating fleet-service triggers hurt quality.  A
weaker causal bias being preferred suggests that this ALNS benefits from
global exploration; the issue is unlikely to be solved by making the boundary
harder.

## Claim--evidence alignment

- **Implemented claim:** causal information changes destroy probabilities
  while preserving global removability.  **Supported by code and tests.**
- **Efficiency claim:** one weighted repair is faster than multi-level hard
  repair and same-trigger-rule full repair.  **Supported.**
- **Quality claim:** soft boundaries improve hard freezing.  **Not supported:**
  -0.30% with a CI spanning both benefit and harm.
- **Compute-quality claim:** soft repair preserves strong-baseline quality at
  lower time.  **Contradicted:** +3.10% deprivation and failed +1%
  non-inferiority versus equal-budget periodic replanning.
- **Original regret-certificate claim:** the certificate decides when to
  repair.  **Not supported by this cycle:** the certificate was previously
  inactive and was deliberately removed from the primary method.

## Adversarial reviewer assessment

- **Contribution:** technically clear, but the proposed structural bias has no
  demonstrated advantage over hard freezing and loses to the strongest
  equal-budget baseline.
- **Soundness:** pass for implementation and protocol integrity; qualify the
  trigger comparator and decision-weight granularity.
- **Experimental strength:** strong for a negative conclusion because the
  final seeds were untouched, comparisons are paired, disruption is realized,
  and confirmation agrees with final evaluation.
- **Claim discipline:** the method can be described as a causal-biased ALNS,
  not as regret-certified repair or as an empirically superior planner.
- **Publication risk:** high if retained as the manuscript's headline method;
  a reviewer can reasonably ask why periodic full replanning is both simpler
  and better.

## Recommended next action

Do not run another decay/threshold sweep and do not use this soft-boundary
variant as the manuscript's winning method.  The immediate manuscript action
is to report it as a negative ablation or remove the superiority claim, retain
18-call periodic full replanning as the strong benchmark, and rename the
same-trigger-rule comparator accurately.

If another algorithmic cycle is warranted, it should change the search rather
than only the boundary:

1. use an adaptive ALNS portfolio that mixes unbiased global destroy with
   causal destroy, learning operator weights from realized improvement;
2. assign weights to full visit/decision keys and log the actually removed
   causal, route-local, shared-resource, and global proportions;
3. create a fixed exogenous-trigger replay ablation to isolate repair search
   from endogenous trigger timing;
4. compare under both equal solver-call and equal wall-clock budgets;
5. predeclare new development and final seed blocks before any such redesign.

This is a fundamentally different search cycle.  It should proceed only if
the paper requires a new optimization contribution; otherwise the defensible
conclusion is that simple periodic full replanning is the best evaluated policy
for the present simulator and budget.
