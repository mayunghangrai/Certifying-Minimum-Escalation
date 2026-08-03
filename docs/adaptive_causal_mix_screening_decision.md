# Adaptive Causal-Mix ALNS: replacement screening decision

## Integrity

The original 800--809 screen is invalid because of the documented global-
operator lineage defect.  After the fix, the predeclared reserve 830--839 was
used once as replacement screening.  Both valid families contain 50 rows (10
seeds times 5 methods), zero feasibility violations, clean commit `36a3b5c`,
and valid artifact hashes.

## Selection

The table reports the family-balanced paired relative deprivation delta versus
18-call periodic full replanning.  Negative values favor adaptive repair.

| Decay | Minimum operator probability | Relative deprivation | 95% CI | Call delta | Repair-time delta |
|---:|---:|---:|---:|---:|---:|
| 0.35 | 0.20 | +16.41% | +7.26% to +25.56% | -0.25 | +0.08 s |
| **0.35** | **0.35** | **+13.88%** | **+3.02% to +24.74%** | **-0.70** | **-0.40 s** |
| 0.65 | 0.20 | +17.11% | -0.42% to +34.63% | -0.85 | +0.52 s |
| 0.65 | 0.35 | +17.65% | +0.33% to +34.96% | -0.70 | +0.41 s |

The predeclared rule therefore selects decay 0.35 and minimum probability
0.35.  The setting is globally frozen; no family-specific choice is allowed.

## Mechanism check

Across the selected candidate's 346 attempted transactions, each attempt used
one solver call and only three attempts had an empty incumbent profile.  The
causal operator removed causal-tier visits in 61.2% of removals, compared with
41.5% for the uniform operator.  Both operators were active (10,322 causal and
10,438 global selections), but their new-best counts were similar (300 versus
330), leaving the mean final causal probability near 0.50.

The implementation therefore realizes the intended operator distinction, but
the screen gives no efficacy evidence.  Following the protocol, the selected
setting is frozen and proceeds to the untouched 810--829 confirmation block;
confirmation is diagnostic and cannot retune the method.
