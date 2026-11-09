# Level-2 Exhaustive Search v1 results — October 5, 2026

The four modules are implemented, and the run contains exactly the thirteen frozen unresolved targets. Independent tree replay and full prior-evidence replay passed for all thirteen. No new missions were generated and the original continuous experiment records remain unchanged.

## Certified conclusions

| Conclusion | Cases |
|---|---:|
| Level 2 feasible, minimum certified as 2 | 1 |
| Level 2 excluded, stored Level-3 witness certifies minimum 3 | 2 |
| Level 2 excluded, higher minimum still unknown | 8 |
| Level 2 still unresolved at the search limit | 2 |

Both previously reported `[2, 3]` gaps are closed:

- `CB_3_3_clustered_61003_below`: **minimum 3**.
- `NB_3_3_uniform_41002_fixed_sequence_below`: **minimum 3**.

`CB_6_3_uniform_61002_below` now has a conservative continuous-path witness with exactly checked rational quantities, certifying **minimum 2** when combined with the frozen exclusion of Levels 0 and 1.

The eight other exclusions raise the known lower bound from 2 to 3; they do not establish Level-3 feasibility. They include `CB_12_4_uniform_61004_below` and the seven other three-task cohort targets.

The two 24-task targets remain unresolved: `CB_24_6_clustered_61002_below` and `CB_24_6_uniform_61002_below`. They preserve respectively 123 and 125 open tree leaves after the 60-second soft cap. Replay validates their partial coverage without promoting it to exclusion.

## Coverage and computational observations

The search branches over the complete declared fixed-slot alphabet, including task repetitions, depot revisits and inactive suffixes. Exact assignments, fixed paths and transfers, and commitments survive every branch. Every branch explicitly records all next-slot choices, even when search stops after finding a witness.

All ten complete Level-2 exclusions were established by a depot-to-unvisited-mandatory-task lower bound at the root. This bound excludes every sequence, including repeated/depot visits; those visits cannot make the first positive delivery arrive before the all-path bound. A single verified root pruning proof therefore covers the entire route domain without enumerating its descendants.

The new feasible six-task case used 51 stored tree nodes, two complete skeleton evaluations, one exact quantity exclusion and one exact rational mission witness. The clustered 24-task search checked 33 complete skeletons and closed them with rational quantity contradictions. The uniform 24-task search reached two complete skeletons, closing one before the other was interrupted. Neither exhausted its route domain.

Measured total search was **131.005 s**, and new tree replay was **6.873 s**. The follow-up reuses independently verified prior oracle evidence. Initial/secondary baseline audits, full-run auditing and the full test suite are additional costs.

The large cases spent approximately 46.842 s and 54.785 s in numerical path generation, versus 2.560 s and 2.670 s in bound construction. These counters identify the present implementation's bottleneck; they are not a scaling result. A future optimization should avoid generating path witnesses for every pair when only a lower bound is needed. No scaling study was run here.

## Verification and provenance

The full suite passed **441 tests**, including **54 Level-2 tests**. New tests cover independent brute-force slot-domain comparisons, repeats/revisits/padding, commitments, exact quantities, late zero deliveries, recharge, forged bounds/Farkas/primal proofs, omitted branches, cycles, unreachable nodes, substituted input runs and standalone replay. Replay also passes with producer methods and numerical optimizers patched to raise.

- [Implementation and commands](LEVEL2_EXHAUSTIVE_V1.md)
- [Case table](../results/level2_exhaustive_2026_10_05/v1/analysis/cases.csv)
- [Run report](../results/level2_exhaustive_2026_10_05/v1/analysis/REPORT.md)
- [Frozen run manifest](../results/level2_exhaustive_2026_10_05/v1/manifest.json)
- [Full-run audit log](../results/level2_targets_audit_2026_10_05.log)
- [Standalone tree replay log](../results/level2_standalone_replay_2026_10_05.log)
- [Final full-suite log](../results/level2_full_suite_final_2026_10_05.log)

Frozen source hash: `583438a02b37ca862c30f1042920426ba51336ecdaa11b9b3b4aa0f3dc05b95d`. The source archive and immutable case records bind all prior scenarios, record hashes, file hashes, stage manifests and per-case budgets. Replay is independent of the new search and quantity orchestration, sharing only the declared trusted environment/physics/constraint-checking primitives.
