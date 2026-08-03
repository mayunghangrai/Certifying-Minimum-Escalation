# Adaptive Causal-Mix ALNS: confirmation review (seeds 810--829)

## Integrity

All four scenario families contain exactly 160 rows (20 seeds times 8
methods), zero feasibility violations, clean commit `656cac5`, and valid
artifact hashes.  The corridor and mixed families average 4.85 and 5.25
realized closures per episode, both inside the predeclared 3--6 target band.
No implementation defect was detected.

## Blocked paired effects

Each family is averaged within seed before inference.  Negative deprivation
favors Adaptive Causal-Mix ALNS.

| Comparator | Relative deprivation | 95% CI | Call delta | Repair-time delta |
|---|---:|---:|---:|---:|
| Fixed causal-bias soft boundary | +12.33% | +6.45% to +18.21% | -0.19 | +3.38 s |
| Same-trigger-rule uniform full replan | +15.94% | +10.66% to +21.22% | -0.16 | +0.55 s |
| Exogenous-gated adaptive mix | -2.28% | -6.24% to +1.68% | +3.80 | +3.24 s |
| Exogenous-gated uniform full replan | +10.53% | +4.21% to +16.84% | +4.78 | +4.75 s |
| 18-call/60-iteration periodic | +16.26% | +9.67% to +22.84% | -0.83 | -0.29 s |
| 18-call/40-iteration periodic | +16.07% | +9.97% to +22.18% | -0.83 | +2.99 s |
| 2-hour periodic | +11.32% | +5.48% to +17.16% | +12.18 | +8.09 s |

The family-wise penalties against full-budget periodic are +17.93% (standard),
+21.67% (information obsolescence), +10.41% (corridor disruption), and
+15.03% (mixed).  The upper confidence limit is far outside the predeclared
+1% non-inferiority margin.

The adaptive method averages 10.998 seconds of repair time, while the
full-budget periodic baseline averages 11.291 seconds.  This negligible time
difference cannot offset the quality loss.  The 40-iteration periodic point
averages 8.011 seconds, 27% below adaptive time, and therefore fails the
predeclared +/-15% wall-match criterion; it is only an approximate lower-compute
point.

## Mechanism audit

The implementation is active rather than silently reverting to uniform ALNS.
Across 1,374 attempted adaptive transactions:

- exactly 1,374 solver calls were charged and 1,017 candidates were installed;
- causal and global operators were selected 41,123 and 41,317 times;
- their new-best rates were nearly identical, 3.51% and 3.42%;
- the mean final causal probability was 0.497;
- causal destroy removed causal-tier visits 59.1% of the time, compared with
  38.2% for uniform global destroy;
- only 12 attempts had an empty incumbent profile.

Thus visit-exact causal bias changes executed removals, but those changes do
not produce better search outcomes.  The learner correctly finds almost equal
operator rewards.  Preserving the incumbent while mixing 30% destroy moves is
substantially weaker than either the fixed causal pre-destroy or a full global
reconstruction in this simulator.

## Claim--evidence status

- **Exact visit lineage and executed-removal logging:** supported technically.
- **Adaptive use of causal versus global destroy:** supported technically;
  both operators are active and probabilities respond to rewards.
- **Improvement over fixed causal bias:** contradicted by +12.33% deprivation.
- **Improvement over same-trigger-rule uniform search:** contradicted by
  +15.94% deprivation.
- **Non-inferior quality at lower compute:** contradicted; quality is much
  worse and repair time is effectively the same as full-budget periodic.
- **Benefit under disruption:** contradicted; losses persist with calibrated
  corridor closures.

## Decision

Freeze the selected implementation without modification and run the untouched
900--939 final block once, as predeclared.  Confirmation is decisively negative
but exposes no software defect.  The final run is for an unbiased locked
estimate, not another opportunity to tune the method.
