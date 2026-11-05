# Final simulation benchmark — results and limits

Date: 2026-09-30. Formulation: `wind-benchmark-v2`. Main policy: **b = 1**.

The implementation now covers the six controlled outcomes, boundary experiments and a frozen randomized population. The controlled cases establish distinct operational meanings, and the boundary experiments identify conditions where local repair is insufficient. The randomized population is dominated by retention; its results must not be presented as a well-resolved distribution of higher escalation levels.

All claims are conditional on the recorded mission, horizon, execution state, commitments and slot bounds. Full-domain claims cover the manuscript's path choices under those conditions.

## 1. Controlled cases: all six outcomes are certified

Each case starts from an exactly feasible incumbent. Every finite label has an exact feasible witness and an independent physical exclusion of all smaller scopes. The infinity case has a physical exclusion of the full path domain.

| Case | Certified k_R^F and k^F | Operational meaning | Affected UAVs | Changed UAV plans | Plans preserved |
|---|---:|---|---:|---:|---:|
| C0 | 0 | Retain the incumbent despite a relevant update | 1 | 0 | 3/3 |
| C1 | 1 | Change a flight path around adverse wind | 1 | 1 | 2/3 |
| C2 | 2 | Reorder visits with task responsibility fixed | 1 | 1 | 2/3 |
| C3 | 3 | Reassign within the affected UAV plus one helper | 1 | 2 | 1/3 |
| C4 | 4 | Use both outside UAVs; every permitted one-helper patch fails | 1 | 3 | 0/3 |
| Cinf | infinity | No UAV can meet the mandatory delivery deadline | 1 | — | — |

Level 2 permits sequence, path and **loading/delivery quantity** changes. Task responsibility changes first become available at Level 3. Changed-plan counts describe the returned witness, not a separate minimum-cardinality optimization.

The 36 supplementary controlled runs vary b over 0, 1 and 2 and ground-operation duration over 0 and 0.01. C3 changes from Level 4 at b=0 to Level 3 at b=1. C4 changes from Level 4 at b=1 to Level 3 at b=2. Thus b=1 is a declared benchmark policy, chosen as the smallest positive helper allowance; it is not an intrinsic property of the hierarchy. The nonzero-operation companions preserve these outcomes.

These are constructed certification examples with supplied witnesses. Their acquisition times are not a blind-search performance comparison.

## 2. Boundary experiments: local sufficiency is measurable

The study contains **231 evaluated observations**: 207 initial points and 24 adaptive additions. Wind severity, disturbance duration, deadline slack and battery slack vary against fixed template references and path libraries. Unknown points remain visible; no interpolated region is claimed.

| Evidence domain | 0 | 1 | 2 | 3 | 4 | infinity | Unresolved minimum |
|---|---:|---:|---:|---:|---:|---:|---:|
| Represented k_R^F | 82 | 15 | 28 | 30 | 6 | 29 | 41 |
| Full path domain k^F | 82 | 12 | 14 | 20 | 6 | 29 | 68 |

Minimum-scope uncertainty does not always prevent a recoverability classification. The exact bounds give the following membership evidence for D_{<=2}, the region where Levels 0–2 suffice:

| Domain | Inside D_{<=2} | Outside D_{<=2} | Unresolved membership |
|---|---:|---:|---:|
| Represented | 125 | 106 | 0 |
| Full path domain | 125 | 70 | 36 |

These are counts of the chosen deterministic observations, not estimates of a population probability or geometric region area. An exact witness proves membership. An exclusion covering Level 2 proves nonmembership. An unresolved minimum alone proves neither.

For example, on C3 with deadline multiplier 1, battery slack 1 and duration 2 reference times, full-domain minima are 0 at zero severity, 3 at severities 16/65 and 8/17, and 4 at 48/73 and 4/5. These evaluated points establish a transition from local retention to helper coordination and then full release. They do not locate an exact continuous boundary.

The fixed refinement budget added nine C1 points and fifteen C2 points; C3 retained its initial grid because proposals were ordered deterministically. Consequently the maps do not support a claim of uniformly fine transition resolution. The separate controlled threshold tests check equality and both sides of the analytic C3 thresholds.

Figures: [deadline multiplier 1, battery slack 1](../results/final_benchmark_2026_09_30/figures/boundary_D1_B1.png), [deadline/battery plane](../results/final_benchmark_2026_09_30/figures/boundary_deadline_battery.png). PDF/SVG versions are beside the PNGs. [Per-observation recoverability membership](../results/final_benchmark_2026_09_30/figures/recoverability_membership.csv) retains both domains and all unknowns.

## 3. Randomized study: four main answers

The primary sample contains **48 base missions and 96 counterfactual updates**, with task/UAV sizes 3/3, 6/3, 12/4 and 24/6, two spatial families and six frozen seeds. A/B updates share a base mission; statistical summaries resample whole base missions. Every incumbent passed exact previous-forecast feasibility. The generator was not retuned after primary results were seen.

### How often is each level required?

At the primary five-second search cap, **84/96 updates (87.5%) are certified Level 0** in both domains. The other 12 minima remain unresolved. There are no certified nonzero minima in this primary run; that is a statement about available evidence, not proof that nonzero levels never occur.

Three updates independently exclude Level 0 in the full path domain. Retention is provably impossible there; whether a repair exists, and its minimum scope, remain unresolved.

For represented Level 0, exact evidence gives a frequency identification interval of **87.5%–95.8%**; in the full path domain it is **87.5%–96.9%**. The base-cluster bootstrap interval for the frequency of *certified Level-0 observations* is 81.25%–93.75%. These answer different questions: the bootstrap addresses sampling variability; the identification interval addresses unresolved labels in the realized sample.

### How different is propagation from intervention?

The mean |U0|/M is **0.445**, with median 1/3. Twenty-nine updates have empty U0; 22 reach the full fleet. Among the 67 exposed updates, the mean affected fraction is 0.638.

**Fifty-five updates affect at least one UAV but still permit exact retention.** Among the 87 exact witnesses, 84 change no UAV plan and three change one, two and three UAV plans. Directed propagation therefore often overstates the intervention needed to retain feasibility. The structural dependency closure has median 59 nodes (range 0–881); these graph-node counts are kept separate from UAV and changed-coordinate counts.

### How much does locality preserve?

Of the three nonzero returned witnesses, two hold outside plans fixed: one changes 1/3 UAVs and preserves two plans, and another changes 2/4 and preserves two plans. The third changes all three UAV plans. Their primary-run minimum scopes remain unresolved.

The mean preserved fraction among all 87 witnesses is 0.979, largely because 84 are retention cases. It must not be reported as a general percentage improvement caused by locality. The evidence for preservation during nontrivial randomized recovery is small.

In 31/96 updates, a Level-3 patch releases exactly the Level-4 coordinates. This is a certified sufficient condition for scope equality. The remaining 65 cases are not certified equal by this check; they are not asserted to be unequal. This diagnostic also shows why |U0|/M must accompany the locality results.

### What does certification cost?

| Tasks/UAVs | Updates | Certified Level 0 | Unresolved | Median setup + search (s) | Median replay audit (s) |
|---|---:|---:|---:|---:|---:|
| 3/3 | 24 | 21 | 3 | 0.223 | 0.220 |
| 6/3 | 24 | 21 | 3 | 0.307 | 0.304 |
| 12/4 | 24 | 22 | 2 | 0.521 | 0.491 |
| 24/6 | 24 | 20 | 4 | 1.003 | 0.924 |

Across all primary updates, setup plus search has median 0.466 s and maximum 5.971 s. The five-second limit applies to search and is checked between operations; setup and replay auditing are additional. Median time to a represented certificate is 0.436 s among 84 completed certificates, all Level 0. Unresolved runs remain censored; they are not assigned an artificial certificate time.

The main [four-panel figure](../results/final_benchmark_2026_09_30/figures/random_primary.png) and [observation table](../results/final_benchmark_2026_09_30/figures/random_observations.csv) report these primary results.

## 4. Supplementary evidence and interpretation

The prespecified H/G comparison contains 32 updates from the tight-margin subset. H finds exact witnesses in 24 cases and G in 23; 23 have witnesses from both. Median witness times on those common successes are 0.462 s and 0.467 s. H obtains 22 minimum-scope certificates; a stronger certificate was not requested from G. These observations do not establish general algorithm superiority. [Paired evidence-cost table](../results/final_benchmark_2026_09_30/figures/supplement_H_G_evidence_cost.csv).

The separate **post-run budget sensitivity** applies 60 seconds uniformly to the same 96 updates. It yields 85 certified Level-0 cases, one certified represented Level-1 case and ten unresolved represented minima. In the full path domain, it yields 85 Level-0 cases and eleven unresolved minima. These repeated checks add evidence on the original population; they do not add independent missions or replace the primary results.

Two cases explain the change:

- `R_3_3_clustered_21003_B`: an exact path repair and complete represented Level-0 exclusion certify k_R^F=1. Full-domain k^F remains unresolved between 0 and 1; the finite reserve library cannot exclude other continuous returns.
- `R_6_3_uniform_21001_B`: the primary run found a Level-1 repair changing all three UAV plans. More search finds a different auxiliary reserve-return witness while retaining every plan coordinate, certifying k_R^F=k^F=0. A feasible repair's scope need not be necessary.

The represented Level-0 identification interval narrows to 88.5%–92.7%. Summed per-case setup plus search increases from 95.2 s to 592.5 s; separately recorded replay auditing totals 47.9 s and 49.9 s. The extra computation resolves two additional represented minima and leaves the higher escalation distribution largely open. This sensitivity was selected after the primary run and must be labeled accordingly. [Case-by-case budget comparison](../results/final_benchmark_2026_09_30/analysis/budget_comparison.csv).

## 5. What the paper can claim

- Every hierarchy outcome has a distinct, exactly certified controlled example.
- Certified boundary observations show when Levels 0–2 cease to suffice, including cases where full release is necessary under b=1.
- In the frozen randomized population, propagation often occurs without any required plan change.
- The randomized sample provides limited evidence on nontrivial recovery and higher-level frequencies. Unresolved cases and the dominance of retention must remain visible.

A claim that higher escalation levels are well characterized across random missions, or that locality usually produces large savings during necessary recovery, would exceed the present evidence. This limitation should shape the paper's wording rather than trigger tuning of the frozen population.

## Reproduction and verification

See the [implementation guide](FINAL_BENCHMARK_IMPLEMENTATION.md), [frozen randomized configuration](../configs/final_benchmark/random_primary.json), and [boundary configuration](../configs/final_benchmark/boundary_primary.json). Each run stores immutable records, source/config hashes, source archive, runtime versions and replayable evidence. Report tables are generated by `scripts/report_final_benchmark.py`; figure inputs and outputs are bound by `figures/figure_manifest.json`.

Published tables use the archived records. Exact evidence is replayable; a fresh run with wall-time caps can stop at a different enumeration point and produce different unresolved labels. The [machine-readable report data](../results/final_benchmark_2026_09_30/analysis/report_data.json) and its manifest bind the reported statistics to specific records.

The latest full suite reports **333 tests passed**. All **497 study records** passed the final hash, source-archive, run-binding and certificate replay audit. All six figure layouts were visually inspected; the figure manifest verifies 365 input records and 26 exported artifacts. The fresh code review found no critical mathematical defect; provenance, timestamp and preservation findings were corrected with failing-then-passing regressions. The manuscript's four formulation-source hashes match their pre-implementation values, and pre-existing user edits were preserved.
