# Level-3 Certified Reassignment v1: frozen targeted results

The eight frozen higher-minimum gaps were run once with the new certified outer assignment search and full route-slot sequence kernel. One case now has certified minimum intervention **3**; six exclude Level 3 and therefore have lower bound **4**; one remains unresolved with lower bound **3**. No Level-4 feasibility claim follows from an exclusion.

## Results

Each case had one shared soft limit of 60 seconds and 100,000 processed outer/inner nodes. Continuous potential refinements were `[2, 4]`, interval precision was 18 digits, and the rational solver limits were 100,000 operations and 10,000 rows. The original continuous evidence seeded a scenario-scoped cache. No inputs or prior records were changed.

| Frozen case | Level-3 result | Combined conclusion | Helper patches | Sequence proofs | Search (s) | Replay (s) |
|---|---|---|---:|---:|---:|---:|
| CB_12_4_uniform_61004_below | EMPTY | minimum at least 4; feasibility unknown | 3 | 0 | 1.316 | 0.225 |
| CB_3_3_clustered_61001_below | EMPTY | minimum at least 4; feasibility unknown | 2 | 0 | 0.590 | 0.058 |
| CB_3_3_clustered_61002_below | UNRESOLVED | minimum at least 3; feasibility unknown | 2 | 4 | 60.003 | 13.088 |
| CB_3_3_clustered_61004_below | EMPTY | minimum at least 4; feasibility unknown | 2 | 2 | 43.864 | 9.622 |
| CB_3_3_uniform_61001_below | EMPTY | minimum at least 4; feasibility unknown | 2 | 0 | 0.585 | 0.105 |
| CB_3_3_uniform_61002_below | EMPTY | minimum at least 4; feasibility unknown | 2 | 0 | 0.508 | 0.087 |
| CB_3_3_uniform_61003_below | EMPTY | minimum at least 4; feasibility unknown | 2 | 2 | 40.539 | 8.072 |
| CB_3_3_uniform_61004_below | WITNESS | minimum = 3 | 2 | 1 | 4.942 | 0.351 |

Search totalled 152.347 seconds; the separately measured new outer/inner replay totalled 31.608 seconds. Baseline audits and final full-run verification add overhead. These are observed times from a targeted diagnostic run on the shared workstation, not a controlled scaling benchmark.

Four exclusions close entirely through certified assignment pruning. The other two exclusions require full sequence-tree coverage for both surviving assignments. Across the eight cases, the report accounts for all 17 canonical maximal helper patches, 604 processed assignment nodes, 388 assignment exclusions and nine attached sequence proofs. It processes 27,231 sequence nodes. Saved trees also contain explicit unprocessed frontier nodes; processed-node counts do not count those as completed work.

## The minimum-3 witness

`CB_3_3_uniform_61004_below` originally assigns T1 to U1, T2 to U3 and T3 to U2. The original affected set is `{U3}`. The permitted helper patch `{U1, U3}` reassigns T2 to U1 while preserving the original commitments and release mask. The resulting assignment is `{T1: U1, T2: U1, T3: U2}`.

The checked U1 route is `T2 -> T2 -> DEPOT -> T1 -> DEPOT`. It delivers 0 and 1 at its two T2 visits, reloads 3/2 at the intermediate depot and delivers 3/2 at T1. U2 retains its T3 delivery; U3 delivers nothing. The quantity witness stores exact rational values, and its flight and reserve paths have independently verified continuous intervals. This actual witness includes both a repeated task visit and depot replenishment, so the sequence kernel is exercised beyond customer permutations. These structures are permitted; the result does not establish that the repeated visit is necessary.

Prior certificates exclude Levels 0, 1 and 2 for this unchanged case. The new Level-3 witness therefore certifies `k^F = 3`. Search stops on that existential witness, with other assignment/sequence regions explicitly open; exclusion coverage is unnecessary for that conclusion.

## The remaining uncertainty

For `CB_3_3_clustered_61002_below`, the `{U1, U2}` helper patch is fully excluded. The `{U1, U3}` patch has an unfinished sequence proof for assignment `{T1: U2, T2: U3, T3: U1}`. That proof retains 16 inner nodes with reason `search budget`, and the outer assignment tree retains three nodes with reason `shared search budget`. The other three attached sequence proofs are EMPTY. The unfinished inner proof propagates to its patch and to the overall UNRESOLVED result.

No visited sequence reports a continuous geometry gap in this run. The unresolved conclusion is due to the time-limited combinatorial frontier; unevaluated branches may still contain geometric or quantity difficulties. It remains `k^F >= 3`, with no feasible upper bound. No Level-4 solver or new scaling experiment was run.

## Acceptance and independent verification

All eight requested implementation criteria are met:

1. The report and checker reconstruct the complete canonical maximal helper family, which covers smaller permitted patches by inclusion. Even unreached patches retain an explicit root.
2. Every released assignment coordinate branches over `None` and the entire fleet. Fixed coordinates retain their sole original owner. Every raw child is represented; incompatible outside-patch choices have an explicit fixed-route exclusion.
3. The original scenario, candidate assignment and original authorized release mask are explicit inputs to the sequence engine and are bound into its proof.
4. Only independently checked necessary assignment conditions, continuous all-path/resource bounds and rational quantity exclusions prune. Proposal failure cannot exclude a region.
5. Open inner and outer regions remain UNRESOLVED unless an independently checked witness supplies an existential conclusion.
6. The separate replay program verified all eight outer trees and all nine attached full-slot sequence proofs. The six EMPTY results have complete coverage. The WITNESS and UNRESOLVED results correctly retain open regions.
7. Scenario/configuration-bound caches return copies, separate canonical lower evidence from path generation, and attach only locally consumed immutable snapshots. Cold/warm semantic equivalence and mutation isolation tests pass. Cache speed can change the frontier reached under a wall limit, without changing the evidence for a completed query.
8. Exactly the eight frozen targets were run. All **274 files** in the prior primary continuous and Level-2 run directories have unchanged byte hashes. Their manifests, source archives and original record bindings were checked; older proofs were mathematically replayed against unchanged scenarios.

The complete suite passes **486 tests** (83.11 seconds), including 45 new Level-3 tests. Focused and adversarial tests exercise child/patch omissions, original-context substitutions, commitment conflicts, altered certificates, explicit inner uncertainty, cache isolation and target provenance. A fresh process ran the standalone replay CLI on every saved record and accepted all eight. The full target-run audit also passed with `valid=True`, `records=8`, and `prior_files_unchanged=274`.

The checker shares trusted scenario/scope definitions, rational arithmetic, interval/potential verification and exact transfer/Farkas primitives. It does not invoke the outer search, shared cache or a numerical optimizer. Physics support remains stationary covered wind, idle depot origins and uncoupled preparations. Unsupported modes and exhausted numerical/rational limits remain unresolved.

## Frozen artifacts

- Implementation contract: `docs/LEVEL3_CERTIFIED_V1.md`.
- New records, manifest and source archive: `results/level3_certified_2026_10_05/v1/`.
- Machine-readable table: `results/level3_certified_2026_10_05/v1/analysis/cases.csv`.
- Standalone replay log: `results/level3_standalone_replay_2026_10_05.log`.
- Full provenance/byte audit: `results/level3_targets_audit_2026_10_05.log`.
- Full test output: `results/level3_full_suite_2026_10_05.log`.

Run hash: `4e588709f612ba5d78bd04f8f60e5212037ddc745d150f71017da3ec3625a732`.

Source hash: `7ea08005678c1b11482065c8c16b6282ac6372c174bc20229c1d63791ac03419`.

The new run is separate from the frozen Level-2 and continuous experiments. Source or budget changes require a new output directory. The scaling study remains a separate future experiment.
