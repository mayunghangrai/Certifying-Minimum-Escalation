# Level-3 Certified Reassignment v1 Implementation Plan

> **For agentic workers:** Use test-driven development. Sequence-interface and independent replay tasks are delegated; root integrates certified outer search, cache, target provenance and execution.

**Goal:** A certified Level-3 escalation test on the eight frozen unresolved higher-minimum targets.

**Architecture:** Original helper-patch coverage and assignment B&B wrap a parameterized full-slot sequence kernel. Immutable scenario-bound cache views carry independently checked continuous evidence; a separate checker verifies both tree layers.

**Tech Stack:** Existing Python/Fraction, potential bounds, continuous oracle, rational transfer compiler and replay primitives.

**Spec:** `docs/superpowers/specs/2026-10-05-level3-certified-v1-design.md`

## Global Constraints

- Preserve original scenario identity, commitments and release masks; no incumbent rebasing.
- Explicitly list every helper patch and every raw assignment child.
- Prune only with independently verifiable necessary conditions.
- Propagate unfinished geometry, quantity and budget regions as unresolved.
- Freeze all previously produced experiment bytes; run exactly eight new target records.

## Review Focus

- Helpers may repair quantities/routes even when assignment values stay unchanged.
- Released assignment values outside a patch need explicit structural accounting.
- Optional tasks may stay unassigned; mandatory residual delivery cannot.
- Shared-cache order and returned-object mutation cannot alter proof snapshots.
- A failed or unfinished inner search cannot exclude an outer assignment region.

## Tasks and verification

1. Sequence API: extend `level2/skeletons.py` and `search.py` with explicit assignment/patch inputs; test original commitments, helper participation and legacy compatibility before implementation.
2. Independent replay: extend `level2/replay.py` for explicit sequence proofs; add `level3/replay.py`, standalone CLI and adversarial tests for both tree layers.
3. Cache: add `level3/cache.py`; test immutable scenario-scoped cold/warm queries and isolated evidence views.
4. Assignment search: add `level3/search.py`; test complete patch/child accounting, certified deadline/structural pruning, existential witnesses and unresolved propagation.
5. Target run: add `level3/targets.py` and runner; test exact eight-input selection and provenance substitutions; freeze source, run eight, independently audit every proof and verify prior byte hashes.
6. Run focused tests and the complete suite; document results, uncertainty and trusted-core boundaries. No automatic commits because the checkout contains pre-existing changes and untracked active source.

Each implementation task starts with a behavioral RED test and ends with a GREEN check. Root retains a completion ledger here.

## Completion ledger

- Sequence API complete: explicit assignment and original authorized patch, original scenario identity, commitment preservation, legacy compatibility and fixed-slot ownership checks; 17 new sequence-interface tests.
- Independent replay complete: outer helper/assignment tree and every attached sequence proof, fresh-process CLI and adversarial checks; 14 new replay tests.
- Shared cache complete: canonical verified bounds/paths, scenario/configuration binding, copied snapshots and per-call evidence views; four new cache tests.
- Assignment B&B complete: all raw owner children, five certified necessary pruning rules, existential witnesses and actual inner UNRESOLVED propagation; seven new search tests.
- Frozen target runner complete: exact eight-case selection, archive/input/run/record provenance, immutable output and before/after prior-byte checking; three new target tests.
- Integrated verification complete: 486 tests pass, all eight new records pass full audit and standalone replay, and all nine attached sequence proofs pass. All 274 prior experiment files remain unchanged.
- Target results: one WITNESS with certified minimum 3, six EMPTY with lower bound 4 and no feasible upper bound, one UNRESOLVED with lower bound 3. Detailed findings and limits are in `docs/LEVEL3_CERTIFIED_RESULTS_2026_10_05.md`.
- Source frozen at `7ea08005678c1b11482065c8c16b6282ac6372c174bc20229c1d63791ac03419`; new records are in `results/level3_certified_2026_10_05/v1/`. No scaling/Level-4 run or automatic commit was performed.
