# Simulation readiness — 2026-09-17 formulation

**Ready for deterministic wind diagnosis, external recovery validation and small-instance reference search.** The three original frozen cases use one divisible commodity, two UAVs, three tasks, five route slots per UAV, and six cell-time wind entries over `[1,8]` h. Geometry, demands, observed state, incumbent, commitments and operation rules are identical across those cases; only received wind values, declared update support and case ID vary. Every previous-wind incumbent has a validated complete feasible continuation with supplied reserve witnesses. Six diagnostic fixtures and two imported four-UAV cases extend this evidence.

| Case | Changed entries / 6 | Updated incumbent | Evidence |
|---|---:|---|---|
| `benign_update` | 1 | Feasible, complete | Retaining the incumbent suffices. |
| `local_delay` | 2 | Infeasible, complete | A's second delivery moves from 3.7000 to 4.0375 h, beyond its 3.9 h deadline. Flight energy rises from 118.4853 to 145.9803 Wh across both UAVs. |
| `horizon_late` | 3 | Infeasible, incomplete | Confirmed late flights, plus battery/deadline violations; unavailable suffix states remain null. No forecast extrapolation. |

The fixed protocol supports scalar fractional transfers, repeated visits by the responsible UAV, intermediate replenishment, retained returned payload, residual committed service/preparation, hard service deadlines, battery/payload/stock limits, bay overlaps, terminal depot return and one-sided reserve witnesses. Travel integrates cell and time-bin crossings without temporal sampling. Shared edges have explicit ownership; all cells and directions remain traversable.

The paired diagnostic automatically identifies `{A,B,C}` as affected in each original benchmark case. With C's assignment committed, the reassignment neighborhood is `{A,B}`. The five scopes release these coordinate counts:

| Level | Assignment A | Sequence S | Path P | Transfers L |
|---:|---:|---:|---:|---:|
| 0 | 0 | 0 | 0 | 0 |
| 1 | 0 | 0 | 9 | 0 |
| 2 | 0 | 8 | 9 | 23 |
| 3 | 2 | 8 | 9 | 23 |
| 4 | 2 | 8 | 9 | 23 |

Shared stock makes Levels 3 and 4 coincide here, as the formulation permits. Tests also cover empty neighborhoods, committed bridge tasks, quantity release at Level 2 and commitment preservation at Level 4. Counts describe permissions; they do not imply that every coordinate can change independently within the common structural domain.

**Diagnostic evidence:** The DAG records changed wind roots, wind inputs, entering states, deterministic path evaluations, quantities and statuses. Path evaluations include the union of both projections' queries, all selected time bins, and horizon guards. Unavailable evaluations use every bin along the fixed geometry as a conservative query support. Unit-specific reporting tolerances apply after reachability; they never remove graph edges. Nominal transitions stay within one UAV, and reserve traces do not alter them.

| Diagnostic fixture | Observed result |
|---|---|
| `irrelevant_wind` | Changed atom is isolated; no affected task or neighborhood. |
| `unchanged_speed` | Wind input changes and structural closure is nonempty, but operational support is empty. |
| `downstream` | U2's last leg uses only unchanged cell L yet has changed entering state and is affected. |
| `shifted_bins` | U1's outbound flight newly queries east bin 1; both evaluations contribute query support. |
| `reserve_only` | Nominal records are identical; the supplied diagnostic return becomes late, leaving reserve feasibility unresolved. |
| `late_undefined` | Late flights leave unavailable suffix states; conservative query supports and null values remain explicit. |

Additional regressions cover old-only queries, initial reserve attribution, ground operations that finish late, known arrival checks before late service, and committed bridge vertices.

**Imported four-UAV evidence:** `scenarios/worked/` reproduces the manuscript's exact constructed examples. The east exchange is supplied externally and validates in both cases with a feasible upper bound of 3. Case A's committed path endpoints yield neighborhood `{T1,T2}`; Case B's mutable paths yield all four tasks and equal Level-3/4 release spaces. Finite direct-path permutation checks reproduce structural counts `(1,1,1,2,4)` / `(1,1,1,24,24)` and feasible counts `(0,0,0,1,2)` / `(0,0,0,6,6)`. The recovery delivery/return/energy records match the manuscript's rational values. These fixture-specific enumerations are not a general search or minimum-level certificate.

**Combined recovery report:** `validate_recovery_plan` returns separate structural, commitment, all-level membership, mission and reserve results, together with the automatic diagnostic. Known mission violations remain visible even for malformed reserve input. Successful candidates produce only a feasible upper bound; unsuccessful candidates exclude no level. Invalid structure explicitly leaves dependent checks unevaluated. Unrepresentable input numbers are rejected, and nonfinite computed values become null with numerical-unavailability reasons and no successful bound.

**Reference search:** `src/recovery/` now enumerates structurally permitted route/return choices in one frozen path manifest and solves continuous transfer feasibility. Exact rational primal/exclusion checks certify minimum Level 3 for both worked cases; exhaustive feasible branch counts are `(0,0,0,1,2)` and `(0,0,0,6,6)`. Saved `search_case_a.json` and `search_case_b.json` in `docs/recovery_results/` replay identically and pass independent witness/exclusion verification. Case B shares one search for Levels 3/4. Exact supported examples also recover at Levels 0/1/2. Budgets and numerical ambiguity remain unresolved; live continuation advances enumeration and retries LPs with changed settings. See [RECOVERY_SEARCH.md](RECOVERY_SEARCH.md) for commands and evidence semantics.

**Verification:** `.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q` passes **253 tests** (14.20 s, 2026-09-25). The 193 simulator/diagnostic tests remain passing. Sixty additional search tests cover finite representations, continuous fractional transfers, original mission resources, exact primal/exclusion evidence, rational scope membership, all worked counts, partial budgets/continuation, malformed proof rejection, and deterministic CLI replay. Review reproduced and fixed float-rounded scope misclassification, malformed-proof crashes, and retry starvation; padding and report-snapshot regressions also pass. Verified environment: Python 3.13.3, Shapely 2.1.2, jsonschema 4.26.0, pytest 9.0.3, SciPy 1.17.1.

**Traceability:** `docs/formulation/2026-09-17/` contains hash-pinned pre-recovery-method source snapshots. The 61 rules in `docs/formulation/fixture_traceability.json` cover all 708 serialized fixture leaves, link to an existing formulation anchor and relevant executable test, and distinguish synthetic numerical choices from manuscript assumptions. `scenarios/benchmark/manifest.lock` pins all fixtures. `docs/benchmark_results.json` stores both complete result records and input hashes; regenerate it with `python scripts/run_simulation_benchmark.py --output docs/benchmark_results.json`.

`docs/formulation/recovery_fixture_provenance.json` separately pins the eight additional scenario files, two supplied recovery requests, the copied manuscript worked-instance JSON, and its recovery supplement. `docs/recovery_results/diagnostic_examples.json` contains all eight paired diagnostic runs. `case_a_validation.json` and `case_b_validation.json` in the same directory are the combined external-candidate reports. Regenerate either with `scripts/validate_recovery_plan.py` and the matching files under `scenarios/worked/` and `examples/recovery/` as shown in the README.

**Boundaries:** Search certificates concern the declared finite path library and fixed operation protocol. General algebraic arithmetic and scalable search are not implemented; unsupported rational arithmetic can produce separately labeled numerical witnesses. The existing evaluator remains floating point with tolerance `1e-9`; exact search checks are separate. `previous_premise` distinguishes numerical from exact feasibility before the update. A minimum for received-wind feasible sets does not establish exact validity of that prior premise; both worked cases verify it exactly. No policy or learning method is included. Graph edges/task supports remain conservative supersets, and the low-level custom-support API requires caller justification. A failed supplied witness/candidate never excludes a level by itself. The energy law is a synthetic linear surrogate; history is a settled epoch summary. Late aggregates include completed nominal flights only.

**Migration:** No multi-commodity vectors, no-fly/weather exclusions, rolling-coverage semantics or legacy adapters remain in active runtime, schema, fixtures or CLI. The prior runtime and tests are preserved only in the verified non-executable `archive/pre_2026_09_17/runtime.zip`; historical documents and presentation outputs are not simulation evidence. This migration deliberately breaks the previous API.
