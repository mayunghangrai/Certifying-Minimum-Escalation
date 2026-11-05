# Wind diagnosis and recovery validation implementation plan

**Goal:** Implement the four requested dependency, neighborhood, validation and fixture deliverables.

**Specification:** The user's goal and `docs/formulation/2026-09-17/technical_details.tex`, equations wind_atoms through affected_tasks, task_closure_iteration, and supplied-witness bounds. Import the explicitly requested four-UAV Cases A/B from the manuscript recovery supplement as examples, without implementing its search method.

**Architecture:** Keep one physical evaluator. Expose entering states and complete reserve evaluation records from it; build a paired typed DAG from those records with union query supports. Compute structural reachability first and numerical materiality second. Feed reportable affected tasks into the existing constraint closure. A separate validator combines structural, commitment, scope, physical and reserve results for caller-supplied plans.

**Constraints:** One scalar commodity; full-horizon paired wind; fixed slot coordinates and operation rules; no optimizer or path search. Null is an unavailable value. Failed reserve geometries do not prove nonexistence. A successful candidate provides only an upper bound, never an exclusion certificate. Preserve all existing user changes and frozen benchmark inputs; write only inside `code/`.

## Tasks and verification

- [x] 1. Add diagnostic regressions and richer evaluator records. Tests exercise unqueried wind, equal-speed wind changes, downstream propagation, union time-bin queries, reserve-only contact, and unavailable suffixes. API: `diagnose_wind_update(scenario, *, tolerances=None)` returns graph, structural/material/reportable supports, per-leg flags, affected tasks and automatically computed neighborhood.
- [x] 2. Derive conservative slot/task participation from commitments and path endpoints. Inventory support uses mutable loads, service supports retain possible selectors and transfers, and route predicates retain transitive mutable dependencies. Test fixed-path local Case A, unrestricted Case B and committed bridge closure.
- [x] 3. Add `validate_recovery_plan(scenario, candidate, level, *, reserve_paths)` and a JSON CLI. Report structure, commitments, all scope memberships, mission feasibility, reserve witnesses, errors and upper bound together. Test malformed input, valid-but-infeasible plans, unresolved/invalid witnesses, forbidden changes and feasible witnesses.
- [x] 4. Freeze diagnostic examples and imported four-UAV Cases A/B with source hashes and exact expected records. Check the 4/24 represented structural cases and feasible counts `(0,0,0,1,2)` / `(0,0,0,6,6)` as fixture-specific evidence, without promoting enumeration to unrestricted minimum claims. Integrate automatic diagnosis into the benchmark CLI and update usage/readiness docs.
- [x] 5. Run the complete active suite, deterministic CLIs from another directory, and a focused independent review; address substantive findings with regressions.

## Review focus

- Both old-only and new-only queries must contribute contact; unavailable states need conservative possible queries and explicit nulls.
- A direct wind change with unchanged speed retains structural dependence without inventing numerical changes; tolerances cannot prune graph arcs.
- Initial reserve contact belongs to the first leg; reserve evaluation never advances nominal states.
- Committed task vertices remain in closure; genuine shared stock/bay or route participation may make Levels 3 and 4 equal.
- Candidate failure cannot certify an empty scope, and invalid witness input must not conceal mission failures or generate an upper bound.

## Evidence and decisions

- Existing checkout contains the uncommitted runtime migration and extensive unrelated changes. Work in place without restoring or committing that history; a HEAD-only worktree would omit the active runtime.
- Baseline system `python` lacks jsonschema; use the existing `.venv/Scripts/python.exe` environment.
- DAG nodes summarize deterministic path integration and its bin/horizon guards. Query inputs are the union needed by both evaluations; absent entering states conservatively use every bin along the fixed path. These are dependency supersets, not claims of minimal causal influence.

- Baseline: 141 tests passed in the project virtual environment. New diagnostic tests failed before the DAG existed; worked locality/count tests failed before support tightening; recovery/CLI tests failed before their implementations.
- Final review: a read-only independent reviewer checked the named implementation and formulation. It found external numeric overflow; reproduced with huge integers and overflowing finite totals, then fixed with rejection/explicit numerical unavailability. No additional actionable DAG/support/claim issue was found. Unrelated pre-existing migration changes and unrestricted minimum proofs were outside this task and review.
- Additional review regression: a completed arrival followed by late ground service must retain known arrival checks, mark service checks unavailable, and mark relief-site depot checks inactive. Reproduced and fixed.
- Verification checkpoint: 193 tests pass. Both imported east-exchange candidates produce witness reports with upper bound 3 and minimum_certified=false. All 11 scenario CLI runs preserve feasible previous projections; irrelevant wind yields an empty neighborhood, Case A yields two tasks, and Case B yields all four.
- Saved artifacts: docs/benchmark_results.json and docs/recovery_results/{diagnostic_examples,case_a_validation,case_b_validation}.json. Imported sources and fixture hashes are verified by executable provenance tests.
- No source-history commit, branch switch, restore, merge or push was performed. Existing unrelated changes remain in place.


## Completion audit

1. Dependency graph: typed paired graph, atom-to-query edges, integration/bin/horizon guards, downstream nominal states, local resource/deadline statuses and complete diagnostic reserve traces are implemented. The 15 dependency regressions pass, including cancellation, outside-closure invariance, both query-union directions, initial reserve isolation and late flight/ground definedness.
2. Automatic scope: reportable incident-task seeds feed the full task closure before committed assignments are removed. Bridge tests and fixed-path/global worked cases pass; no artificial local split is imposed on stock, bays or unrestricted route participation.
3. External validation: API and CLI return one report separating structure, commitments, membership, mission and reserve outcomes. Malformed, infeasible, unresolved and numerical-overflow inputs have regressions. Only a fully validated candidate yields an upper bound; minimum_certified is always false.
4. Fixtures and manuscript import: six frozen diagnostic fixtures, Cases A/B, two supplied candidates and imported source snapshots are hash-verified. Exact worked records and represented permutation counts are reproduced.

Final verification: 193/193 tests passed. All three original and eight additional saved scenario reports match current evaluations after normalizing native Windows line endings; both combined candidate reports also match. Repeated CLI executions are byte-identical in the suite. The README Python example executes successfully. Named-path git whitespace checks passed. No required work remains.
