# Formulation-aligned simulation benchmark implementation plan

> Execution: inline, with test-first contract checks and a final independent review.

**Goal:** Make the 2026-09-17 one-commodity, wind-only formulation executable on deterministic supplied plans, without implementing a solver or policy.

**Spec:** The finalized `sections_system_model.tex.before` and `sections_technical_details.tex.before` snapshots immediately before the 2026-09-18 recovery-method work. Copy these into `docs/formulation/2026-09-17/` and pin their hashes. The later recovery algorithm is excluded.

**Architecture:** Strict versioned JSON with one shared mission/state/plan/commitment object and two full-horizon cell-time wind tables. A pure flight integrator and fixed-plan evaluator consume immutable validated inputs. Coordinate projections enforce the five nested scopes, with task closure before commitment filtering. Frozen JSON cases and a field-to-assumption manifest establish provenance.

**Tech stack:** Python, Shapely for polygonal geometry, JSON Schema for the closed input contract, pytest.

## Constraints and decisions

- Work only inside `code/`; manuscript files are read-only sources.
- Preserve the substantial existing uncommitted work. Before replacing the incompatible runtime, archive its exact files, tests, scripts, configuration, and frozen scenario with per-file SHA-256 hashes. Historical documents and unrelated artifacts stay intact.
- The active schema rejects old versions and unknown fields recursively. Scalar commodity quantities have no type axis or conversion adapter.
- Use km, h, kg, Wh and commodity units. Wind is piecewise constant, bounded strictly below all airspeeds, and changes only on a declared proper support.
- Preserve one common operating region, cell partition, time knots, observed state, history summary, incumbent, operation protocol and commitment mask.
- All plans and reserve paths are supplied. Validation failures never establish emptiness of a scope.
- No optimizer, policy, learning method, route construction, humanitarian objective, or automatic queue/wait action.
- Use this dirty checkout directly: a new checkout would omit the authoritative uncommitted code. No automatic commit of unrelated user work.

## Tasks

- [x] **1. Schema and fixtures.** Add failing round-trip/scalar/closed-schema/full-coverage/support/state tests. Replace `src/env/scenario.py`; add `schemas/wind-benchmark-v1.schema.json`, deterministic fixtures, source snapshots, and field provenance. Validate partition, wind, units, history summaries, resource data and fixed plan structure. Run `python -m pytest -p no:cacheprovider tests/test_benchmark_contract.py -q`.
- [x] **2. Flight and supplied-plan execution.** Add analytical tests for directed wind, cell and time crossings, exact horizon, mass-dependent energy, zero-length paths and late/undefined records. Implement `wind.py`, `energy.py`, `route_evaluator.py` and `fixed_plan.py`. Check service completion deadlines, stock, payload, reserve witnesses, bay conflicts, residual operations, terminal safety and previous-wind incumbent feasibility. Run physics and execution tests.
- [x] **3. Scope contract.** Add release and candidate-membership tests for A/S/P/L, repeated partial visits, fixed slots, canonical paths, commitments, bridge closure and adjacent equalities. Implement `intervention_scope.py` and conservative task supports. Run scope tests.
- [x] **4. Readiness evidence.** Add a reproducible benchmark CLI and exhaustive fixture-field trace tests plus adversarial rejection of legacy inputs and active API/import audits. Run the entire active suite and CLI, review against the pinned formulation, fix substantive findings, and write `docs/SIMULATION_READINESS.md` with verified numbers and precise limits.

## Review focus

1. Boundary-aligned paths and simultaneous cell/time transitions must have unique ownership and no temporal sampling error.
2. Scalar payload conservation must survive repeated visits, intermediate depot trips and partial history without replaying completed transfers.
3. A late flight/operation must leave downstream quantities unavailable; a rejected reserve path must remain unresolved, not certify nonexistence.
4. Level 3 closure must keep committed bridge tasks and release quantities at Level 2; unrestricted release must still preserve commitments.
5. Unknown nested fields, incomplete wind coverage, nonlocal changes, invalid polygons, and schema mutations must fail closed.

## Evidence ledger

- Baseline: existing suite passed, **170 tests**. It exercises the older model and is not evidence for the new formulation.
- Scope decision: retire incompatible active APIs rather than silently translate multi-commodity or flight-exclusion inputs. Preserve exact pre-migration contents in a non-executable archive for recovery.
- Source decision: use the pre-2026-09-18 snapshots, not current files whose hashes differ, to honor the requested formulation date.
- Continuation audit: the interrupted preceding turn made progress (schema, fixtures, execution and scope implementation; 90 passing tests). Current source was re-inspected before continuing.
- Schema/physics/scope evidence: 48 initial schema/domain tests, 15 analytical flight tests, then 90 full-suite tests before artifact work. Final expanded suite: 141 passing tests.
- Provenance: 61 field rules cover every leaf of all three frozen fixtures; source anchors, referenced tests, snapshot hashes and fixture hashes are checked. CLI traces are byte-identical across repeated runs from an unrelated directory.
- Review fixes: oblique boundary ownership, unfinished ground/airborne origins sharing depot coordinates, and JSON integral slot bounds were reproduced as failing tests and fixed; the expanded full suite passed.
- Ruling: segment ownership uses polygon-intersection parameter intervals rather than rounded midpoint membership, because the latter violates declared ownership on slanted edges. Affects general-polygon time/energy results; regression verifies the supplied counterexample.
- Ruling: servicing/airborne virtual origins cannot load/recharge merely because their XY coordinates equal the depot. Observed execution mode controls origin operations; an explicit subsequent depot visit can prepare. Regression verifies both modes and residual transfers.
- Ruling: accepted JSON integer-valued slot bounds normalize to Python integers. This preserves the mathematical integer domain and avoids scope-construction crashes.
- Reviewer boundaries resolved: solver/search completeness and minimum-level certification are explicitly excluded by the user; automatic full-DAG diagnosis is outside this supplied-plan benchmark; externally supplied custom task supports remain a declared conservative-support contract. Built-in supports are conservative over all structural-domain branches. These limits are stated in the readiness report.
- No user source/history was committed or restored from Git. The exact pre-migration active files remain recoverable in the hash-verified archive; unrelated pre-existing deletions and artifacts were left untouched.

- Completion audit passed: full suite 141/141; CLI generated all three paired traces; both pinned source snapshots equal their original files byte-for-byte; all 708 fixture leaves have one formulation trace; active-code legacy import/schema audits pass; readiness report delivered.
