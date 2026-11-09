# Final simulation benchmark implementation

**Goal:** implement the approved three-study protocol on a laptop, with independently checked evidence and explicit unresolved outcomes.

**Spec:** [Approved design](../specs/2026-09-30-final-simulation-benchmark-design.md).

**Architecture:** version the revised scenario contract; retain the v1 evaluator and reports; reuse the exact fixed-skeleton linear backend. Represent Level 3 as a union of participant patches. Store exact represented evidence separately from optional independently checked physical exclusions. A resumable experiment runner writes one immutable record per instance and derives tables from those records.

**Stack:** Python 3.13, pytest, JSON Schema, Shapely, SciPy, rational arithmetic, standard-library records and manifests.

## Global constraints

- Work inside `code/`; preserve the manuscript and prior fixtures/results.
- Primary `b=1` is a benchmark policy; scope depends on directed incumbent evaluation reachability.
- Level 2 changes quantities, paths, and sequences; responsibility changes start at Level 3.
- Library exhaustion establishes only represented exclusions. Unknown, unsupported arithmetic, interrupted search, and missing forecast coverage remain unresolved.
- Evidence quality takes priority over grid density and benchmark size. Freeze generator settings only after a development pilot.
- Main Study 3 has four outputs: level frequency, propagation/change, preservation, and certification effort. H/G is supplementary evidence-cost analysis.
- Preserve the dirty starting checkout with a source archive. Do not commit pre-existing user work.

## Task 1 — Scope contract

**Produces:** v2 schema, directed `U0` with traces, participant patch family, scope membership and changed-coordinate metrics.

Write failing tests for v2 validation, helper budget, frozen outsiders, fixed assignments at Level 2, and shared-resource independence. Implement and run these plus the existing domain/scope tests.

**Expected:** all tests pass; legacy behavior is unchanged.

## Task 2 — Evidence machinery

**Consumes:** scope patches. **Produces:** exact per-patch witnesses/exclusions, independent replay, explicit domain bounds, admissibility/coverage guards and rational wind input.

Test patch coverage, witness membership, tampered certificates, incomplete searches, missing/retained forecast tail, and finite-library versus full-domain claims. Add budgeted union search and a separate evidence assembler. Keep full-domain physical certificates explicit and independently checkable.

**Expected:** unknowns never become exclusions; all claimed certificates replay.

## Task 3 — Six controlled cases

**Consumes:** v2 evidence. **Produces:** C0, C1, C2, C3, C4, Cinf scenarios, expected witnesses and physical exclusions.

Build the six analytic cases in the spec. Test exact witness feasibility, lower-scope exclusions, non-nearest helper success, and collapse diagnostics. Exercise nonzero operation times separately.

**Expected:** six distinct certified full-domain outcomes with auditable assumptions.

## Task 4 — Reproducible records

**Consumes:** scenarios, libraries, evidence. **Produces:** CLI, source/config manifests, atomic per-case records, replay audit, durable case-level resume, analysis.

Test hash validation, interruption/resume, unsupported-domain plotting labels, unknown retention, and deterministic generation. Separate timing from deterministic scientific evidence. Document that interrupted individual searches restart, while completed cases are reused.

**Expected:** reruns reproduce scientific records; corrupt/stale records cannot be silently reused.

## Task 5 — Development pilot

**Consumes:** generators and runner. **Produces:** pilot report, calibration log, frozen primary settings.

Run a small development-only sample. Inspect prior feasibility, update exposure, `|U0|/M`, representation/exact-arithmetic coverage, level distribution and measured search cost. Adjust only documented generator defects or pathological distributions before freezing.

**Expected:** explicit go/no-go rationale and a laptop-sized frozen primary workload.

## Task 6 — Studies 2 and 3

**Consumes:** frozen settings. **Produces:** boundary observations with conservative refinement, randomized records, four primary result summaries, supplementary scope-collapse/H-G diagnostics, reproducibility instructions.

Run the frozen workload, retain all unresolved outcomes, audit certificates, and create standalone scientific plots/tables. Run the full test suite and fresh final code review.

**Expected:** results are traceable to immutable records and correctly scoped claims.

## Review focus

Check Level-3 patch coverage under commitments; exact quantity membership after materialization; query support and `U0` inflation; admissibility and missing-data semantics; claim-domain leakage; certificate replay; result reuse after configuration/source changes; clustered randomized denominators; timing censoring; and whether plots imply classification or interpolation absent from the evidence.
