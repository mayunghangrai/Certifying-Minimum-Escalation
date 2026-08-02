# Soft-Boundary Event-Causal ALNS: predeclared next-cycle protocol

## Objective

The previous locked evaluation showed that hard selective freezing lost
global route coordination, while the regret certificate was operationally
inactive.  This cycle tests a narrower redesign: retain causal tracing as an
ALNS destroy bias, allow every future visit to remain removable, and use the
event-impact score explicitly as a heuristic trigger rather than a claimed
certificate.

## Method fixed before development

For each repair event, the incumbent causal trace defines four nested visit
classes.  Destroy-selection weights are:

```text
causal decisions            1
other affected-UAV visits   decay
shared-resource UAV visits  decay^2
all remaining visits        decay^3
```

All weights are strictly positive, so unrelated routes are never frozen.
The causal decisions are removed from the warm start before construction,
and one weighted ALNS call performs the repair.  A candidate is installed
only if it is feasible and its belief-side improvement exceeds the charged
solve cost; genuine hard infeasibility bypasses the economic screen.

The primary method uses proxy-only triggering with threshold fraction 0.03,
linear budget pacing, 18 repair transactions, and 60 ALNS iterations.  The
regret certificate is excluded from the primary claim because the preceding
evaluation found it changed no executed outcomes.

## Data separation

- Historical diagnosis only: seeds 500--539.  These seeds cannot select or
  modify the new method.
- Development screening: seeds 600--609, standard and mixed families.
- Development confirmation: seeds 610--629, all four families.
- Reserved development fallback: seeds 630--639, used once only if a concrete
  implementation defect is found during confirmation.
- Untouched final evaluation: seeds 700--739, all four families, run once
  after the selected specification and source commit are frozen.

## Screening grid

The only tunable design choices are:

- boundary decay in {0.35, 0.65};
- soft fleet-service gate in {off, on}.

The four candidates are compared with equal-budget periodic full replanning,
2-hour periodic full replanning, the former hard-freeze method, and
identical-trigger full replanning.

## Selection rule

Candidates with any feasibility violation are ineligible.  Among eligible
candidates, select the lowest family-balanced paired relative deprivation
delta versus equal-budget periodic replanning across screening seeds.  If two
candidates differ by less than 0.25 percentage points, prefer lower composite
cost charged by actual solver calls; if still tied, prefer lower measured
repair wall time.  The rule is global: no family-specific parameter is allowed.

Confirmation is diagnostic, not a second tuning grid.  A source or protocol
change after confirmation is permitted only for a reproducible implementation
defect, must be documented, and must use the reserved 630--639 block before
the final method is frozen.

## Frozen final comparison

The final suite contains:

1. selected Soft-Boundary Event-Causal ALNS;
2. former hard-freeze event-causal ALNS with the same trigger/gate/pacing;
3. identical-trigger full-replan ALNS;
4. 18-call equal-budget periodic full replanning;
5. 2-hour periodic full replanning;
6. initial plan only.

The primary endpoint is true deprivation cost.  Secondary endpoints are
composite cost charged by actual solver calls, fill rate, actual solver calls,
repair wall time, and feasibility violations.

## Final interpretation rule

- Superiority over a comparator requires a negative paired deprivation delta
  whose 95% confidence interval excludes zero.
- Non-inferiority to equal-budget periodic uses a predeclared +1% relative
  deprivation margin on the four-family, per-seed blocked average.
- A compute-quality claim additionally requires lower measured repair time or
  fewer actual solver calls without violating the non-inferiority margin.
- Improvement over hard freezing must be demonstrated directly; performance
  against weak every-event/static baselines is not sufficient.

