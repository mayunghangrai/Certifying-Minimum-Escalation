# Soft-boundary screening decision (seeds 600--609)

The screening stage used the standard and mixed-information/disruption
families.  All four candidates completed 20 paired family-seed blocks with
zero feasibility violations and clean provenance at commit `3875657`.

| Candidate | Family-balanced relative deprivation vs 18-call periodic | 95% CI | Mean solver-call delta | Mean repair-time delta |
|---|---:|---:|---:|---:|
| decay 0.35, gate off | +5.84% | +3.02% to +8.67% | -0.45 | -3.52 s |
| decay 0.35, gate on | +11.18% | +3.99% to +18.37% | -6.25 | -6.63 s |
| **decay 0.65, gate off** | **+4.79%** | **+1.38% to +8.20%** | **-0.35** | **-3.60 s** |
| decay 0.65, gate on | +9.34% | +2.96% to +15.72% | -6.10 | -7.01 s |

Under the predeclared rule, decay 0.65 with the fleet-service gate off is
selected because it has the lowest family-balanced relative deprivation.
Its advantage over the next candidate exceeds the 0.25 percentage-point tie
band, so composite-cost and repair-time tie-breakers are not invoked.

The selected candidate remains worse than the periodic reference during
screening.  Confirmation therefore tests whether it improves materially over
hard freezing and whether its quality/time tradeoff approaches the
identical-trigger full-replan ablation; screening alone does not support a
positive performance claim.

