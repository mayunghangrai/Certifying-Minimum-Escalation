# Level-2 Exhaustive Search v1 Implementation Plan

> **For agentic workers:** Use test-driven development. Independent generator, quantity and replay modules are delegated; root owns integration, safe bounds and targeted execution.

**Goal:** Certify sequence sufficiency over the full Level-2 route-slot domain.

**Architecture:** Explicit prefix tree with full next-symbol coverage, optimistic rational resource/quantity exclusions, and conservative continuous-path witnesses. A separate replay program checks coverage and evidence without invoking search or optimizers.

**Tech Stack:** Existing Python environment, Fraction arithmetic, continuous oracle, rational transfer compiler and SciPy proposals.

**Spec:** `docs/superpowers/specs/2026-10-05-level2-exhaustive-v1-design.md`

## Global Constraints

- Work only under `code/`; preserve frozen experiment files and unrelated checkout changes.
- Preserve assignment, all fixed coordinates, repeats, depot revisits and inactive suffixes.
- Numerical failure and budget exhaustion remain unresolved.
- Run only the 13 frozen unresolved targets; no case generation or scaling study.

## Review Focus

- A zero-delivery late visit cannot invalidate every quantity choice.
- An assigned optional task still requires a structural visit.
- Shared endpoints do not imply that a fixed path is shortest.
- Removing a branch, changing an assignment or forging a bound must invalidate replay.
- Exact primal values must be bound to their float projection and the stored scenario.

## Tasks

1. Generator: `src/level2/skeletons.py`, tests for literal brute-force domain equivalence, commitments, repeats, revisits and padding.
2. Quantities: `src/level2/quantities.py`, tests for exact fractions, zero late delivery, forged primals/Farkas evidence and solver limits.
3. Bounds/search: `src/level2/bounds.py`, `src/level2/search.py`, tests for safe prefix pruning, full small-instance exclusion, witness and explicit frontier under limits.
4. Independent replay: `src/level2/replay.py`, `scripts/replay_level2.py`, tests for omitted/duplicated branches and altered terminal evidence.
5. Targeted runner: `scripts/run_level2_targets.py`, source/input bindings, immutable records and results report. Execute 13 inputs, replay every proof, run the complete project test suite and review the four modules.

Each implementation task writes and observes a failing behavioral test before implementation, then runs its focused tests. Root performs integration and final whole-project verification. No automatic commits: the current checkout contains substantial pre-existing changes and untracked active source.

## Completion ledger

- [x] Generator: 14 tests and independent brute-force domain comparisons.
- [x] Quantities: 17 tests and independently replayed rational primals/Farkas evidence.
- [x] Bounds/search: six tests, recharge audit correction and explicit budget frontiers.
- [x] Replay: thirteen tests, fresh-process CLI tampering check and optimizer poison check.
- [x] Target runner: four tests, prior-run binding correction, exactly 13 immutable records.
- [x] Final read-only mathematical/provenance review completed; no remaining material issue identified.
- [x] Target run and both full-run/standalone replay completed. Outcomes: one Level-2 witness, ten exclusions, two unresolved.
- [x] Final full suite: 441 passed in 81.88 seconds; results and limitations documented separately from frozen experiments.
