# Level-4 Certified Global Reoptimization v1: six frozen targets

All six cases previously certified to exclude Levels 0–3 now also exclude Level 4. Each final global proof has complete coverage and independently replays as EMPTY. Therefore **`k^F = infinity` for all six modeled continuation problems**. No target remains unresolved, and no minimum-4 witness was found or needed.

Infinity applies to the specified remaining-mission model: its original snapshot, commitments, permitted assignments, route-slot limits, horizon, resources and stationary covered wind physics. It is not a claim about continuations outside that model.

## Final results

The unchanged six Level-3 records were selected by pinned manifest and record byte hashes. Every case used one original global release mask and a shared soft budget of 60 seconds and 100,000 processed assignment/sequence nodes. Continuous refinements were `[2,4]`, precision was 18 digits, and rational limits were 100,000 operations and 10,000 rows. Canonical prior continuous bounds seeded the scenario-bound cache.

| Frozen case | Level-4 result | Combined minimum | Critical task | Optimistic completion | Deadline | Search (s) | Replay (s) |
|---|---|---|---|---:|---:|---:|---:|
| CB_12_4_uniform_61004_below | EMPTY | infinity | T7 | 0.483193796 | 0.482201774 | 1.201 | 0.157 |
| CB_3_3_clustered_61001_below | EMPTY | infinity | T3 | 0.456291267 | 0.447182427 | 0.669 | 0.098 |
| CB_3_3_clustered_61004_below | EMPTY | infinity | T1 | 0.566797816 | 0.559825976 | 1.113 | 0.142 |
| CB_3_3_uniform_61001_below | EMPTY | infinity | T2 | 0.913863584 | 0.901666931 | 0.848 | 0.142 |
| CB_3_3_uniform_61002_below | EMPTY | infinity | T2 | 0.800133803 | 0.796876216 | 0.497 | 0.087 |
| CB_3_3_uniform_61003_below | EMPTY | infinity | T1 | 0.762912624 | 0.760931514 | 1.077 | 0.123 |

Completion and deadline values are mission time coordinates in the scenario's hours; decimals are presentation only. The saved certificates and checker use exact rational comparisons. Optimistic completion is the minimum over every permitted fleet owner, with each owner's payload capacity and both directional continuous travel bounds taken into account.

Every final proof contains one processed global root and one certified assignment exclusion, with no assignment children or attached sequence proofs needed. Together they contain six root exclusions. Search totalled **5.406 seconds** and separately measured new-proof replay totalled **0.749 seconds**. Recursive baseline audits, source and byte verification add overhead. These timings describe the targeted run on the shared workstation, not a controlled scaling benchmark.

## Why the whole global domain is excluded

For a task with positive residual mandatory quantity `R`, an owner with commodity capacity `Q` requires at least `n = ceil(R/Q)` delivering sorties. Original ownership is exclusive, and replenishment occurs at the depot. For the supported idle-at-depot snapshot, the last required delivery cannot precede

`epoch + n * (preparation + service + lower(depot, task)) + (n - 1) * lower(task, depot)`.

This necessary bound ignores the final return, other tasks, resource coupling and energy restrictions, so it is optimistic. It allows repeated visits and depot replenishment. At each root, every permitted owner exceeds the critical task's deadline strictly. Leaving the task unassigned also fails its positive mandatory requirement. Consequently no assignment and no permitted full-slot route skeleton can complete the mission; the exclusion does not rely on failed path or sequence proposals.

The exact sortie counts for the critical tasks, in canonical owner order, are:

| Case | Owner sortie counts |
|---|---|
| CB_12_4_uniform_61004_below | U1: 1; U2: 1; U3: 1; U4: 1 |
| CB_3_3_clustered_61001_below | U1: 1; U2: 1; U3: 2 |
| CB_3_3_clustered_61004_below | U1: 2; U2: 1; U3: 2 |
| CB_3_3_uniform_61001_below | U1: 1; U2: 2; U3: 2 |
| CB_3_3_uniform_61002_below | U1: 1; U2: 1; U3: 1 |
| CB_3_3_uniform_61003_below | U1: 2; U2: 1; U3: 2 |

Capacity matters in particular for the clustered 61004 and uniform 61003 cases: owners whose first arrival is optimistic enough still require a second delivery sortie. Checking arrival alone leaves such branches alive; checking the mandatory completion closes them safely.

The initial diagnostic run under `results/level4_certified_2026_10_05/v1/` remains frozen. It produced three EMPTY and three UNRESOLVED results. The 12-task case exhausted its assignment-node cap; the clustered 61004 and uniform 61003 cases exhausted their shared time caps with an inner sequence frontier. Inspection of that saved evidence motivated the certified completion relaxation. After independent mathematical review and adversarial testing, only the same six targets were rerun in the separate final directory. The improved result cannot be attributed to modifying any scenario, earlier record or budget.

## Implementation and independent verification

Level 4 calls the same assignment kernel as Level 3, with one global original release mask instead of the helper-patch union. Candidate assignment and original scope level 4 are explicit inputs to the complete route-slot engine. Original commitments remain fixed. Released slots retain inactivity, depot visits and repeated task visits, as well as assigned task choices. The three-valued WITNESS/EMPTY/UNRESOLVED contract is unchanged, and unfinished inner evidence propagates outward.

The independent checker reconstructs the global mask, raw owner domain, every explored assignment child, all certified relaxations and every attached sequence proof. It independently reconstructs completion bounds from rational residual quantities, exact ceilings and verified directional potentials. It imports no producer or shared cache and runs no numerical optimizer. Common trusted primitives are scenario/scope definitions, rational arithmetic, continuous interval/potential verification and exact transfer/Farkas checking.

All **543 tests passed** in 84.29 seconds, including 57 new Level-4 tests. Fixtures exercise witnesses, complete slot structures, commitment and owner contexts, child omissions, certified pruning, explicit inner uncertainty, cache isolation, adversarial replay and frozen input/budget substitutions. These fixtures exercise deeper solver paths; the six final empirical targets themselves need only root pruning.

A fresh standalone process accepted all six saved global certificates with `valid=true`, `covered=true`, `status=EMPTY` and no attached sequence proofs. The complete target-run audit also passed with `valid=True`, `records=6`, `prior_files_unchanged=296` and status counts `{WITNESS: 0, EMPTY: 6, UNRESOLVED: 0}`. The audit recursively verifies their original Level-3, Level-2 and continuous premises, exact target identity, source archive and budget binding. All **296 prior files** in the primary continuous, Level-2, Level-3 and initial Level-4 directories remain byte-for-byte unchanged.

This cohort establishes global infeasibility through strong deadline and capacity relaxations. It does not establish performance for deep global assignment or route-slot enumeration. No additional target or scaling study was run.

## Frozen artifacts

- Contract: [LEVEL4_CERTIFIED_V1.md](LEVEL4_CERTIFIED_V1.md).
- Final records, manifest and source archive: `results/level4_certified_2026_10_05/v1_completion_bounds/`.
- Machine-readable results: `results/level4_certified_2026_10_05/v1_completion_bounds/analysis/cases.csv`.
- Standalone replay log: `results/level4_completion_standalone_replay_2026_10_05.log`.
- Full provenance audit: `results/level4_completion_targets_audit_2026_10_05.log`.
- Full test log: `results/level4_completion_final_suite_2026_10_05.log`.
- Preserved initial results and source: `results/level4_certified_2026_10_05/v1/`.

Final source hash: `cfc8b504dce398a945e55b7276a834343d5034167e4ed8d36eb845669fa00906`.

Final run hash: `cdfe6ac97089833237331d8c47875db3f09f9aabc70c194d1c6236d784ec6c53`.

The study retains its 2026-10-05 artifact names. The final manifest was created on 2026-10-06 UTC. Source, input or budget changes require a new run directory.
