# Adaptive Causal-Mix ALNS: predeclared evaluation protocol

## Objective

The locked soft-boundary evaluation showed a real compute saving but a 3.10%
deprivation penalty versus 18-call periodic full replanning.  Development also
favored the weaker causal bias, which indicates that the fixed destroy bias
suppressed useful global exploration.  This cycle tests a different search
mechanism: causal and unbiased global destroy operators compete inside every
ALNS repair call, and their probabilities adapt to realized search progress.

## Method fixed before development

Each incumbent visit receives a profile keyed by its complete decision
identity `(UAV, sortie, visit)`.  The four initial causal tiers retain the
weights used in the preceding cycle:

```text
causal decision             1
affected-UAV route          decay
shared-resource route       decay^2
remaining fleet visit       decay^3
```

The visit identity, tier, and weight travel with a removed demand packet when
it is reinserted.  The ALNS call contains two destroy operators:

1. **causal destroy**, sampling visits with the attached causal weights;
2. **global destroy**, sampling all visits uniformly.

Both operators use the same greedy repair and acceptance rule.  Their initial
weights are equal.  After each use, an exponential update rewards a new global
best with 1, a diversification acceptance with 0.1, and rejection with 0.
The reaction factor is 0.20.  A predeclared minimum selection probability
prevents either operator from disappearing.  Actual operator selections,
removed causal tiers, accepted moves, and final weights are logged.

The repair trigger remains the operational-belief proxy with threshold 0.03,
linear pacing, 18 repair transactions, and 60 ALNS iterations.  The incumbent
is not causally pre-destroyed before the adaptive portfolio runs.  Hard
infeasibility continues to bypass the economic screen.

## Data separation

- Historical diagnosis only: seeds 500--739.
- Engineering smoke only: seeds 797--799; these verify packaging and are not
  eligible for parameter selection or claims.
- Original development screening: seeds 800--809, standard and mixed
  families.
- Development confirmation: seeds 810--829, all four families.
- Reserved defect fallback: seeds 830--839, used only after a reproducible
  implementation defect.
- Untouched final evaluation: seeds 900--939, all four families, run once
  after source and selected configuration are frozen.

No result from seeds 900--939 may change the algorithm, configuration, or
primary interpretation rule.

## Development grid and selection

The only candidate choices are:

- causal decay in {0.35, 0.65};
- minimum probability for each destroy operator in {0.20, 0.35}.

Candidates with any feasibility violation are ineligible.  The selected
candidate minimizes the family-balanced, paired relative deprivation delta
versus 18-call periodic full replanning.  A 0.25 percentage-point tie band is
resolved first by lower composite cost, then by lower repair wall time.  One
global setting is used for every scenario family.

## Confirmation and final comparators

1. selected Adaptive Causal-Mix ALNS;
2. fixed causal-bias Soft-Boundary ALNS with the same trigger rule;
3. uniform full-replan ALNS with the same trigger rule;
4. adaptive causal-mix with exogenous-event gating;
5. uniform full replan with exogenous-event gating;
6. 18-call periodic full replanning with 60 iterations per call;
7. 18-call periodic full replanning with 40 iterations per call, predeclared
   from the historical 0.66 soft/periodic repair-time ratio as the approximate
   wall-clock-matched comparator;
8. 2-hour periodic full replanning.

"Same trigger rule" does not imply identical realized trigger timestamps,
because installed plans can change later endogenous feasibility events.  The
exogenous-gated pair excludes fleet-service economic triggers but retains
hard-infeasibility repairs for safety.

## Endpoints and interpretation

The primary endpoint is true deprivation.  Secondary endpoints are composite
cost charged by actual solver calls, fill rate, solver calls, repair and
episode wall time, feasibility, operator selection, and removed-tier shares.

- Superiority requires a negative paired deprivation delta whose 95% CI
  excludes zero.
- Non-inferiority to 18-call/60-iteration periodic uses the same predeclared
  +1% relative-deprivation margin on the four-family per-seed blocked average.
- A compute-quality claim requires non-inferiority plus lower measured repair
  time against the full-budget comparator.
- The 40-iteration periodic comparator is accepted as wall-clock matched only
  if its mean repair time is within 15% of the adaptive method; otherwise it is
  reported as an approximate budget point, not an equal-time claim.
- Added causal structure must improve either the same-trigger-rule uniform
  search or the fixed causal-bias predecessor; beating only static or sparse
  periodic baselines is insufficient.

Confirmation is diagnostic, not a second tuning phase.  Unless a concrete
software defect is found, the selected method is frozen and the final block is
run once even if confirmation is negative.

## Defect amendment before valid screening

The standard-family 800--809 package exposed a lineage-propagation defect:
visits freshly created during a uniform-global iteration received weight 1.0
instead of the fleet-global `decay^3` floor.  Mixed 800--809 was stopped before
completion, and the entire 800--809 block is invalid for selection or claims.
The defect was fixed and regression-tested before any replacement data were
generated.  The predeclared reserve 830--839 is therefore consumed as the
replacement screening block with the original grid and selection rule.
Confirmation remains the untouched 810--829 block and final evaluation remains
900--939.
