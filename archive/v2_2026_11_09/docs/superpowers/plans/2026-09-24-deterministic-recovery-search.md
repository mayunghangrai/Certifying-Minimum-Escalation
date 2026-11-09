# Deterministic recovery search implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. Track the test evidence below.

**Goal:** Search the five represented intervention spaces using finite route enumeration and continuous transfer feasibility, returning verified witnesses, sound exclusions, or unresolved search.

**Architecture:** A separate `src/recovery/` package owns immutable path manifests, lazy enumeration, affine transfer constraints, rational certificates, and bounded search. Existing `env` scenario, diagnosis, scope and candidate-validation APIs remain the physical contract. Rational geometry/wind evaluations permit exact certificates; other geometry uses numerical proposals with explicit uncertified outcomes.

**Tech stack:** Python, fractions, existing Shapely geometry validation, SciPy/HiGHS for continuous numerical proposals; exact Fourier–Motzkin elimination for tiny rational problems.

**Spec:** User-approved design in this conversation; mathematical source `docs/formulation/2026-09-17/`; search semantics in the manuscript's 2026-09-18 recovery-method specification.

## Global constraints

- One divisible commodity; no quantity grid, policy, learning, secondary mission objective or changed physical semantics.
- Freeze geometry, state, commitments, received wind and path manifest across levels.
- Include incumbent/committed nominal paths and supplied previous reserve witnesses in the library.
- Only complete, sound exclusions may imply emptiness. Arithmetic/budget uncertainty stays unresolved.
- Certificates apply to the declared finite representation and fixed operation protocol.
- Work in `code/`; preserve existing unrelated dirty changes and do not stage or commit them.

## Review focus

- Transfers that are fractional, fixed, zero at late visits, or incompatible with changed stops.
- Retained payload, intermediate recharge, residual operations and reserve-only failure.
- Budget exhaustion during structural enumeration or linear elimination; resumption cannot skip evidence.
- Numerical proposals near exact equality, irrational coefficients, overflow and certificate tampering.
- Equivalent levels, representation membership, deterministic ordering and input immutability.

## Task 1: finite representation and lazy enumeration

Create `src/recovery/representation.py`, `src/recovery/enumeration.py`, and `tests/test_recovery_search_domain.py`.
`PathLibrary.build(scenario, nominal_paths=(), return_paths=(), direct=True)` records canonical finite paths and a scenario hash. `enumerate_events(scenario, library, releases)` lazily yields counted expansion events and structurally valid plan/return branches. Transfers allowed by the level start at zero; fixed transfers retain their incumbent value.

- [x] RED: require canonical immutable library round-trip, incumbent inclusion, wrong-instance rejection, exact worked structural branch counts, and committed padding/endpoints.
- [x] GREEN: implement endpoint-indexed paths, prefix stop sequences, assignment ownership and full reserve-choice products; no quantity discretization.
- [x] Verify: `.venv/Scripts/python.exe -m pytest tests/test_recovery_search_domain.py -q`.

## Task 2: continuous transfer feasibility and exact arithmetic

Create `src/recovery/linear.py`, `src/recovery/physics.py`, `src/recovery/transfers.py`, and `tests/test_recovery_search_transfers.py`.
`build_transfer_problem(...)` produces labeled affine inequalities and timing records. `solve_linear(...)` returns a checked primal point, an exact nonnegative-combination contradiction, or unresolved. Exact path integration uses rational polygon intersections and rational square roots; unsupported radicals are explicitly numerical.

- [x] RED: analytical rational travel, cross-bin integration, boundary ownership, fractional feasible transfers, contradictory continuous constraints, invalid proof and operation-budget exhaustion.
- [x] GREEN: implement exact elimination with reconstruction and Farkas certificates; use HiGHS numerical proposals only with independent candidate checks.
- [x] Verify resource cases: deadlines, stock, capacity, retained returns, recharge, residual service/preparation, bay overlap, reserve and horizon.

## Task 3: bounded ascending search and reports

Create `src/recovery/search.py`, package exports, CLI `scripts/search_recovery.py`, and `tests/test_recovery_search.py`.
`search_level(...)` supports in-process continuation; `recover(...)` searches increasing labels, shares identical release spaces, and records per-level evidence and bounds. Reports serialize cursor positions for replay, with live cursors used for continuation; JSON is not trusted as proof state.

- [x] RED: worked feasible counts and minimum 3; equal Levels 3/4; zero/partial budgets; resume; unresolved lower level with a higher witness; numerical witness without exact certificate; no continuation only after exact complete exclusion.
- [x] GREEN: implement counters, proof records, input hashes, manifest persistence and safe deterministic CLI output.
- [x] Verify replay from another directory, both worked cases, and the full suite.

## Task 4: documentation and review

- [x] Update README, PROJECT_CONTEXT and readiness boundaries; add `docs/RECOVERY_SEARCH.md` and deterministic worked results.
- [x] Obtain a fresh read-only review under requesting-code-review; reproduce and fix substantive findings with regression tests.
- [x] Run the complete suite and CLI replay; whitespace check recorded below.

## Execution ledger

- Baseline: 193 tests passed in 11.47 s before implementation.
- Ruling: explicit user instruction to implement the presented architecture authorizes implementation; no repeated design approval gate.
- Ruling: use the current workspace because the simulator and fixtures are uncommitted prerequisites; an ordinary HEAD worktree would omit them. No unrelated Git changes will be staged, reset or committed.
- Ruling: general algebraic exact arithmetic is outside this first implementation. Exact rational branches may certify; unsupported arithmetic can provide a simulator-validated numerical witness but cannot certify emptiness or an exact minimum.
- Tasks 1–3: new-module imports first failed before implementation. Domain/transfer integration reached 20 passing tests; initial search integration reached 31; all original tests remained green.
- Regressions: missing direct=False depot padding and live-report drift each reproduced failing, then fixed. Reports are snapshots while the cursor is live.
- Review: first dispatch exhausted account usage; the user resumed on 2026-09-25. The read-only reviewer reproduced exact-fraction scope misclassification and malformed-proof crashes. Both were fixed with failing-then-passing tests. Reviewer additionally checked 1,000 generated rational LPs and found no accounting/enumeration defect.
- Ruling on continuation: unresolved LP work should be retryable when settings change. Implemented retries; follow-up review reproduced starvation under unchanged settings, then a regression proved the fix skips identical failed attempts and advances enumeration.
- Ruling on previous premise: exact received-wind minima remain meaningful for normalized-decimal feasible sets even if the incumbent is only tolerance-feasible. Reports separately expose numerical/exact previous feasibility; the documentation distinguishes a search result from exact benchmark qualification. Both worked cases verify the previous premise exactly.
- Final verification (2026-09-25): 253 tests passed in 14.20 s, including 60 search tests. Saved Case A/B reports replayed identically, all saved empty-level evidence verified, and both saved exact witnesses revalidated. Both minima are 3; Case B's Levels 3/4 share a search. Case A used 248 enumeration events, Case B 860 (these are work counters, not performance comparisons).
- Review exclusions resolved: general algebraic arithmetic/large-instance scalability remain explicit limits; unrelated checkout changes are untouched; LP retry behavior was implemented and tested rather than deferred.
- Whitespace: targeted `git diff --check` passed (only the existing CRLF conversion warning); a separate scan passed for all 18 changed implementation/test/guide/config files, including untracked additions. Changes remain in the shared working directory; no branch, staging, commit, merge or publication was requested or performed.
