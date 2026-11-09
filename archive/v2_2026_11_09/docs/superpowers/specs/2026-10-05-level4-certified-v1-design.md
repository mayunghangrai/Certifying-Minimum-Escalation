# Level-4 Certified Global Reoptimization v1

The user requests one global certified continuation search on only the six frozen Level-3 EMPTY cases. Their prior proofs exclude Levels 0–3. A verified Level-4 witness certifies minimum 4, a complete global exclusion certifies modeled infeasibility (`minimum: "infinity"`), and an unfinished search preserves lower bound 4 without a feasible upper bound.

## Design

Reuse the Level-3 assignment B&B implementation through an internal scope-level parameter. Level 3 retains its helper-family report and public interface. Level 4 obtains exactly `scope_family(original_scenario, 4, original_affected)[0]`, containing every fleet UAV and all uncommitted remaining A/S/P/L coordinates. It produces one `tree`, with no artificial helper union. Commitments are still fixed.

Every released task branches over `None` and the full fleet. Every fixed assignment has its original sole owner. Certified mandatory, fixed-route, commitment, slot and optimistic all-path deadline relaxations are reused. Each surviving assignment invokes `search_sequence(original_scenario, assignment, original_global_patch, scope_level=4, ...)`. The full slot alphabet retains depot revisits, repeated task visits and inactive slots. Exact quantities and continuous path/bound primitives are reused.

Explicit sequence proofs bind their scope level. Default Level-3 calls and saved reports retain their old schema. Independent replay authorizes the exact requested original mask, independently reconstructs the global assignment partition and every attached sequence proof, and propagates open evidence. Search/cache code is not imported by replay.

The shared continuous cache retains canonical request evidence, scenario/configuration binding, copies on return, and separate per-call consumed evidence. Warming can change progress under a wall cap but cannot change the mathematical evidence of a completed query.

## Six frozen targets

- CB_12_4_uniform_61004_below
- CB_3_3_clustered_61001_below
- CB_3_3_clustered_61004_below
- CB_3_3_uniform_61001_below
- CB_3_3_uniform_61002_below
- CB_3_3_uniform_61003_below

Selection requires prior Level-3 EMPTY, complete prior exclusions 0–3, lower bound 4, unknown minimum and no upper bound. Prior record/input/run hashes, source archives and mathematical proofs are checked. The exact original Level-3 manifest and six record byte hashes are pinned. All files in the frozen primary continuous, Level-2 and Level-3 directories are byte-hashed before/after execution and during audit. The initial diagnostic records remain at `results/level4_certified_2026_10_05/v1/`; changed code requires the separate final directory `results/level4_certified_2026_10_05/v1_completion_bounds/`. Initial Level-4 files are also covered by the final byte audit. No scaling study or additional case is run.

The initial run revealed that the assignment tree could reach its node limit before using a mandatory deadline whose all-owner bounds already established impossibility. The final source adds an optimistic completion relaxation: residual mandatory quantity R, payload capacity Q, exact required sorties n=ceil(R/Q), and earliest last delivery epoch+n*(preparation+service+all-path depot-to-task lower)+(n-1)*all-path task-to-depot lower. Minimum over every permitted owner must exceed the deadline strictly before pruning an undecided task; a selected task uses its sole chosen owner. This allows repeated visits/replenishment, ignores final return and all other resource coupling, and is independently reconstructed by replay. Original Level-3 behavior remains unchanged.

## Budget and verification

Retain the v1 diagnostic budget: one total soft 60-second/100,000-node budget per case, refinements `[2,4]`, interval precision 18, rational limits 100,000 operations and 10,000 rows. Setup and cache work are included. Unprocessed children are explicit frontier nodes. Unsupported physics remains unresolved; current support is stationary covered wind, idle depot origins and uncoupled preparations.

Behavioral and adversarial tests cover global release independent of helper policy, fixed commitments, raw child coverage, original-context binding, every attached proof, unfinished inner propagation, semantic cold/warm equivalence, infinity/minimum/budget semantics and frozen target provenance. Run the complete suite, fresh-process replay for all six records, and a full provenance/byte audit. Report observed times as diagnostic rather than scaling evidence. Work stays under `code/`; preserve pre-existing changes and make no automatic commit.
