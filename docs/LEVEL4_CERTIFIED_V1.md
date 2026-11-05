# Level-4 Certified Global Reoptimization v1

Level 4 reuses the certified Level-3 assignment engine, complete route-slot sequence kernel, continuous lower bounds/paths and exact quantity machinery. Its domain is one original global release mask, not a union of helper neighborhoods. All uncommitted remaining A/S/P/L coordinates are released; every original commitment stays fixed.

## Search and evidence

`search_level4(original_scenario, **budget_options)` invokes the shared assignment kernel with level 4. Its report has version `level4_certified_v1`, explicit `scope_level: 4`, and one `tree` containing the original global `patch`, task order, root and nodes. It has no helper `patches` array. Every released task branches over `None` and all fleet owners; a committed assignment retains its original sole owner. Assignment branches list every child before exploration, including explicit open frontier nodes.

The kernel reuses five necessary assignment pruning rules: positive residual mandatory delivery cannot be unassigned; a completely fixed route cannot acquire an unvisited task; fixed task stops cannot contradict ownership; distinct assigned tasks require slots plus the terminal depot; and an all-path optimistic depot-to-task delivery bound can exclude a mandatory deadline. Level 4 also checks an optimistic completion bound before an ownership decision, allowing whole assignment regions to close. These are relaxations, not heuristic failure tests. Replenishment and repeated visits remain available in the sequence domain.

For residual mandatory quantity `R > 0` and vehicle capacity `Q` in commodity units, let `n = ceil(R/Q)` using exact rational arithmetic. Exclusive ownership and depot-only replenishment require at least `n` task-delivering sorties. Their last mandatory delivery cannot occur before

`epoch + n * (preparation + service + lower(depot, task)) + (n - 1) * lower(task, depot)`.

This bound permits replenishment and ignores the final return, all other tasks, stock coupling and energy constraints, so it is optimistic. Directional bounds are certified separately. Before ownership is selected, the minimum over every permitted owner must exceed the deadline strictly; after selection, the same condition applies to that sole chosen owner. The unassigned choice is impossible when residual mandatory quantity is positive. The proof lists the permitted owner context, exact sortie counts and earliest-time bounds; replay independently reconstructs them. Tasks with no residual mandatory quantity do not trigger this rule. An unassigned owner is left to the existing ownership check.

Each surviving assignment calls `search_sequence(original_scenario, assignment, original_global_patch, scope_level=4, ...)`. The proof stores its candidate assignment, original scenario hash, authorized mask and explicit level. Every mutable slot branches over inactivity, depot and every assigned task. Depot revisits, repeated task visits and inactive suffixes are retained. Default Level-3 sequence calls and saved Level-2/3 proof schemas remain supported.

Continuous potential certificates bound the full admissible path domain. Generated paths supply only independently checked witnesses; proposal exhaustion cannot exclude a region. Quantity exclusions use optimistic lower-duration rational relaxations and independently verified infeasibility/Farkas evidence. Witness checking uses conservative upper-duration enclosures and exact rational primal values. Infeasibility of those witness constraints alone leaves the skeleton unresolved. Unfinished geometry, quantity or enumeration regions remain open.

## Three-valued conclusions

For the six targets, prior independently verified certificates exclude Levels 0–3:

| Level-4 result | Required evidence | Combined conclusion |
|---|---|---|
| WITNESS | One checked exact quantity/path/commitment witness | minimum 4 |
| EMPTY | Complete exclusion of the global assignment tree and every surviving sequence domain | minimum `"infinity"`; modeled continuation infeasible |
| UNRESOLVED | Any unfinished region, with no verified witness | lower bound 4; no feasible upper bound |

`"infinity"` is a JSON string, not an infinite floating-point value. It applies to the specified remaining-mission model, including its route-slot limits, commitments, horizon, resources and physics. A valid existential witness may stop search with other regions open. Complete coverage is required for EMPTY. Neither node counts nor heuristic failure establish exclusion.

## Independent replay and cache isolation

`level4/replay.py` invokes the shared independently implemented assignment checker with level 4. The checker reconstructs exactly `scope_family(original_scenario, 4, original_affected)[0]`, every raw assignment child, each necessary exclusion and every attached full-slot proof using `replay_sequence(..., scope_level=4)`. It checks all attached proofs even when one supplies a witness. Replaying a localized mask or implicit/default Level-3 inner proof as global evidence is rejected.

The checker imports no assignment producer or shared cache and invokes no numerical optimizer. Trusted common primitives are scenario/scope definitions, rational arithmetic, interval/potential verification and exact transfer/Farkas checking. Its `patches: 1` metadata counts the single verified domain, not a helper decomposition.

The unchanged shared cache is scenario/configuration bound, generates canonical lower and path evidence separately, returns copies and gives each inner call a fresh view containing only consumed query snapshots. Returned-object mutation, unrelated warming and request order cannot alter completed mathematical evidence. Cache speed can affect progress under a wall cap; the actual frontier remains explicit.

## Frozen six-case study

The only targets are the six prior Level-3 EMPTY records with exclusions `[0,1,2,3]`, lower bound 4 and no feasible upper bound:

- CB_12_4_uniform_61004_below
- CB_3_3_clustered_61001_below
- CB_3_3_clustered_61004_below
- CB_3_3_uniform_61001_below
- CB_3_3_uniform_61002_below
- CB_3_3_uniform_61003_below

The runner pins the exact original Level-3 manifest and six record byte hashes. Copies must preserve those bytes; merely recomputing a changed record's self-hash is insufficient. It checks the archived original source and recursively replays prior mathematical proofs. All files in the prior primary continuous, Level-2 and Level-3 experiment directories are byte-hashed before/after execution and during final audit. The audit reconstructs its expected input map from the pinned bank, requires exact embedded baseline identity, and binds outer budget/precision to the new manifest.

The initial diagnostic run is preserved under `results/level4_certified_2026_10_05/v1/`. It exposed an assignment-order bottleneck: the 12-task case exhausted 100,000 nodes although the saved bounds already ruled out every owner of its critical task. The final v1 source adds the certified completion relaxation and writes to `results/level4_certified_2026_10_05/v1_completion_bounds/`. Both runs use only the same six frozen targets. The initial run is also included in the final before/after byte audit. Source, input or budget changes require a new output directory. Older source snapshots remain authoritative for reproducing their runs; the new live code need not equal older frozen source. No extra target or scaling study is included.

## Budgets, support and commands

The diagnostic budget is 60 seconds and 100,000 processed assignment/sequence nodes per case, shared by the single global tree and all inner calls. Continuous refinements are `[2,4]`, interval precision 18, and rational limits are 100,000 operations and 10,000 rows. Setup and cache work are included. Limits are cooperative between operations; an individual solve can overrun a soft time cap. Timing is operational diagnostic evidence, not a controlled scaling comparison.

Supported physics remains stationary covered admissible wind, idle depot origins and uncoupled preparations. Unsupported modes stay unresolved. The implementation does not make a claim for arbitrary evolving wind or coupled depot scheduling.

```powershell
.venv\Scripts\python.exe scripts/run_level4_targets.py
.venv\Scripts\python.exe scripts/run_level4_targets.py --verify
.venv\Scripts\python.exe scripts/replay_level4.py results/level4_certified_2026_10_05/v1_completion_bounds/records/CB_3_3_uniform_61001_below.json
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.venv\Scripts\python.exe -m pytest -q
```

The standalone CLI also accepts multiple records, arrays, JSONL, and a bare proof with `--scenario`. It exits nonzero on invalid evidence. Tests cover global ownership and mask authorization, original commitments, complete slot structures, all assignment children, valid witnesses/exclusions, inner uncertainty, cache equivalence, adversarial replay and frozen input/budget substitutions.

The final six-case run certifies EMPTY for every target, giving minimum `"infinity"` for each modeled continuation. Each proof closes its global root with the certified completion bound. All six fresh standalone replays and the complete provenance audit pass; 296 prior files are unchanged. The full suite passes 543 tests. See [the targeted results](LEVEL4_CERTIFIED_RESULTS_2026_10_05.md) for the exact certificates and interpretation. This cohort does not measure deep assignment or sequence search scaling.
