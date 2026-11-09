# Level-4 Certified Global Reoptimization v1 Implementation Plan

> **For agentic workers:** Use test-driven development and parallel agents for the independent sequence-context and replay tasks. Root integrates the shared assignment engine, frozen runner and verification.

**Goal:** Certify Level-4 feasibility or global exclusion on exactly the six frozen cases with exclusions through Level 3.

**Architecture:** One global scope mask and assignment tree reuse the existing assignment/slot/continuous/quantity machinery. Independent replay checks the same global domain through separate code and preserves default Level-3 proof compatibility.

**Tech Stack:** Existing Python, Fraction, continuous potentials/intervals, rational transfer and Farkas checking, immutable JSON/source archives.

**Spec:** `docs/superpowers/specs/2026-10-05-level4-certified-v1-design.md`

## Global constraints

- Original scenarios and commitments remain authoritative.
- Exactly one global tree; every raw assignment child represented.
- Only certified necessary relaxations prune; all unfinished evidence propagates.
- Saved Level-2/3 proof formats remain replayable.
- Exactly six frozen targets, fresh output directory, prior bytes unchanged.
- WITNESS => minimum 4; EMPTY => infinity for the modeled continuation; UNRESOLVED => lower bound 4 only.

## Review focus

- A localized mask must not masquerade as global coverage.
- Global release must still subtract every original commitment.
- Proofs must retain candidate assignment and explicit original scope level.
- Every attached proof must be checked, including after an existential witness.
- Cache warming and altered source/provenance must not invalidate evidence silently.

## Tasks

1. **Sequence context** — modify `src/level2/search.py`/`skeletons.py`; add `tests/test_level4_sequence.py`. Interface: `search_sequence(..., scope_level=3)`; level 4 records the level explicitly. RED mask/commitment/global tests, implement exact authorization, then focused GREEN regression.
2. **Independent checker** — extend `src/level2/replay.py` and `src/level3/replay.py`; add `src/level4/replay.py`, `scripts/replay_level4.py`, `tests/test_level4_replay.py`. Interface: default3 `replay_sequence`, shared internal assignment checker, public Level4 `replay_tree/verify_tree`. RED adversarial tests, implement global single-tree verification, then GREEN.
3. **Shared assignment engine** — minimally parameterize `src/level3/search.py`; add `src/level4/search.py` and `tests/test_level4_search.py`. Interface: `search_level4(scenario, **same_budget_and_cache_options)`. RED global-domain, witness, EMPTY, actual inner UNRESOLVED and cold/warm tests; reuse existing bounds and budgeting, then GREEN.
4. **Frozen targets** — add `src/level4/targets.py`, `scripts/run_level4_targets.py`, `tests/test_level4_targets.py`. RED exact-six selection, three-valued/infinity combination and substitution tests. Implement original provenance/audits, immutable records, prior-byte checking and report; GREEN.
5. **Execution** — run focused and complete tests, freeze source and run only six at 60 seconds/100,000 nodes. Independently replay all six and audit every prior byte. Document actual conclusions and uncertainty in `docs/LEVEL4_CERTIFIED_RESULTS_2026_10_05.md`; update context after verification.

## Completion ledger

All five tasks are complete. The shared assignment engine now accepts one original global Level-4 mask; sequence search and independent replay require explicit scope level 4. Adversarial tests cover child accounting, commitments, context, inner uncertainty, cache evidence and exact frozen provenance.

The initial six-case run is preserved at `results/level4_certified_2026_10_05/v1/` (three EMPTY, three UNRESOLVED). Its bounds exposed a missing whole-region deadline relaxation. A reviewed exact-capacity completion bound was added, with independent replay and tests for both undecided and selected owners. The same six unchanged targets were rerun in `results/level4_certified_2026_10_05/v1_completion_bounds/`; all six certify EMPTY and minimum `"infinity"` for the modeled continuation.

Final verification: 543 tests passed; all six fresh standalone replays passed; the full audit passed with 296 prior files byte-for-byte unchanged, including the initial Level-4 run. Results and precise scope qualifications are recorded in `docs/LEVEL4_CERTIFIED_RESULTS_2026_10_05.md`. No automatic commit, additional target or scaling experiment was performed.
