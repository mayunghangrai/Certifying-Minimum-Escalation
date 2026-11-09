# Continuous Path Experiments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement and run the approved three-stage continuous-region recovery experiment.

**Architecture:** Add an independent continuous recovery package with rational interval physics, continuously optimized candidate geometry and verified spatial potential bounds. Reuse the existing scope and transfer constraints through a narrow duration-provider hook, and add a versioned experiment runner that preserves earlier artifacts.

**Tech Stack:** Existing Python 3.13 environment, NumPy/SciPy/Shapely, Clarabel for numerical conic proposals, rational `Fraction` arithmetic for proof replay.

**Spec:** `docs/superpowers/specs/2026-10-05-continuous-path-experiments-design.md`

## Global Constraints

- Work only inside `code/`; preserve all pre-existing changes and frozen results. No commit or repository cleanup is part of this request.
- Continuous polylines are the modeled domain. Initialization meshes and candidate itineraries cannot certify exhaustion.
- First target: stationary complete admissible wind, idle depot origins, and no depot-bay coupling. Other inputs remain explicit unresolved.
- Preserve A/S/P/L commitments, fixed quantities at Levels 0/1, auxiliary reserve witnesses and the helper policy.
- Optimizers propose; rational independent checks certify. Failed proposals and timeouts never imply infeasibility.
- Pilot with disjoint seeds; freeze source/configuration before primary runs. Keep unresolved cases and generation failures.

## Review Focus

- Incorrect wind-cell ownership on paths that follow an interface: test a boundary-aligned flight against an analytic time.
- Unsupported time-varying wind or depot coupling: test unresolved behavior without global emptiness claims.
- Newly generated reserve paths at Level 0: test that nominal coordinates remain identical and the minimum can be zero.
- False continuous-domain exclusions from a finite seed set or malformed potential: test rejected altered evidence and unresolved search exhaustion.
- Paired denominators and provenance: test complete record-bank binding and retention of failed cohort slots.

### Task 1: Rational interval path physics

Files: create `src/continuous/physics.py`, `src/continuous/__init__.py`, `tests/test_continuous_physics.py`; modify `src/recovery/transfers.py` with an optional duration provider.

Interfaces: `sqrt_bounds(value, digits)`, `stationary_duration(scenario, uid, path, digits=18) -> (Fraction, Fraction)`, `stationary_guard(scenario) -> reason|None`; `build_transfer_problem(..., duration_provider=None)` retains existing behavior by default.

- [x] Write and run failing tests for the irrational diagonal, rational constant-wind flight, exact splitting, boundary ownership and unsupported inputs.
- [x] Implement outward square-root bounds and rational cell splitting; add the duration hook.
- [x] Run the physics tests and existing transfer/physics regression tests.

### Task 2: Continuous geometry and global travel-time bounds

Files: create `src/continuous/oracle.py`, `src/continuous/potential.py`, `tests/test_continuous_oracle.py`, `requirements-continuous.txt`.

Interfaces: `ContinuousOracle(scenario, refinements=(2,4), digits=18).query(uid,start,goal,warm_paths=()) -> dict`; `verify_potential(scenario,uid,certificate) -> bool`; certificates contain rational mesh values and a lower bound, separate from candidate paths.

- [x] Write and run failing tests for an analytic diagonal, a detour absent from the library, a constant-wind global bound and tampered fields/partition coverage.
- [x] Implement conic proposals with continuous cell crossing positions and verified piecewise-affine potentials; retain the best independently integrated path.
- [x] Run oracle and proof-replay tests with the installed proposal backend.

### Task 3: Scoped interval witnesses and continuous exclusions

Files: create `src/continuous/validation.py`, `src/continuous/search.py`, `tests/test_continuous_recovery.py`.

Interfaces: `certify_witness(scenario,plan,reserves,level,digits=18) -> dict`, `recover_continuous(scenario,...)->dict`, `verify_continuous_evidence(scenario,result)->bool`.

- [x] Write and run failing tests for new nominal geometry, reserve-only Level 0, fixed commitments, certified Level-1 deadline exclusion, unsupported guards and unresolved exhausted proposals.
- [x] Implement conservative upper-time feasibility, global lower-time deadline proofs, and bounded sequence/assignment proposals using the existing scope masks.
- [x] Run recovery tests and the existing local-scope/evidence tests.

### Task 4: Versioned three-stage experiments

Files: create `src/continuous_benchmark/`, `scripts/run_continuous_benchmark.py`, `tests/test_continuous_benchmark.py`, `configs/continuous_benchmark/`.

Interfaces: CLI commands `controlled`, `paired`, `cohort`, `audit`, `report`; immutable records bind scenarios, inputs, source, budgets and replayable evidence. Cohort generation returns cases plus a complete attempt ledger.

- [x] Write and run failing tests for record replay/tampering, fixed paired inputs, continuous boundary placement, previous feasibility, deterministic seeds and failed sampling slots.
- [x] Implement analytic cases, 128-case input-bank loading, fresh-seed continuous pairing, source capture, restart integrity and descriptive reporting.
- [x] Run a development pilot, inspect admissions and evidence gaps, and freeze primary configurations.

### Task 5: Run, audit and document

Files: new result directories under `results/continuous_paths_2026_10_05/`; add `docs/CONTINUOUS_PATH_EXPERIMENTS.md` and update the current README/context.

- [x] Run the full current test suite and fix introduced failures.
- [x] Run controlled validation, all 128 paired cases, and the frozen continuous boundary cohort.
- [x] Independently audit all new evidence, source archives and sampling ledgers.
- [x] Generate case tables and a report with all unresolved cases and separate cost components.
- [x] Review numerical/physical proof assumptions, correct any findings, and report tested outcomes and remaining limitations.

Completion: 387 tests passed. Primary replay passed for 10 controls, 128 paired cases and 62 cohort cases, with all 32 cohort sampling slots retained. The paired run certifies 127 minima and 39 library penalties. Cohort search certifies 49 minima; adding independently replayed admission evidence certifies 50. Results and provenance are in `docs/CONTINUOUS_PATH_RESULTS_2026_10_05.md`.

Execution follows the user's explicit instruction to implement the selected direction. The plan is retained as a work record and does not require a new authorization step.
