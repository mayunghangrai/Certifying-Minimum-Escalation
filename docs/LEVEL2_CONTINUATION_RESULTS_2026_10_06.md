# Level-2 continuation — October 6, 2026

Both previously unresolved 24-task cases now certify **minimum Level 2**. The frozen continuous evidence excludes Levels 0 and 1, and each new complete mission witness proves feasibility within the original Level-2 assignment-preserving release mask.

| Case | Minimum | Proposal | Search | Tree replay | Proposal candidates |
|---|---:|---:|---:|---:|---:|
| `CB_24_6_uniform_61002_below` | **2** | 1.666 s | 3.520 s | 1.473 s | 5 |
| `CB_24_6_clustered_61002_below` | **2** | 1.536 s | 2.961 s | 1.282 s | 5 |

These are warm continuation timings: the October 5 searches already generated the path/bound evidence used here. Seed validation is included in proposal/search time; full historical evidence audits, source hashing and standalone replay are additional costs. This is not a cold-start or scaling comparison.

## Search diagnosis and changes

The original 60-second searches spent 54.785 s and 46.842 s in numerical path generation, respectively. They evaluated quantities only at complete six-UAV skeletons, so infeasible routes could be combined repeatedly with unrelated routes. The existing direct-depot deadline bounds did not exclude either mission. Stronger exclusion bounds are unnecessary once exact feasible witnesses are obtained.

`level2.proposals.propose_routes` tries task permutations and optional depot returns per mutable UAV, using the saved paths or direct chords. A numerical LP drops inventory and constraints involving other UAVs to suggest a route. This pass is explicitly a heuristic: a failed proposal excludes nothing, and a successful proposal establishes no feasibility claim. Candidate and time caps bound its work. It does not enumerate the complete repeated-visit domain.

The new optional `preferred_prefix` in `search_level2` validates a complete structurally permitted skeleton and tries its choices first. Every raw inactive/depot/task child remains recorded. The full optimistic lower-duration check and conservative exact upper-duration quantity check still adjudicate the complete candidate. Invalid or infeasible proposals cannot certify a mission or change the domain.

All continuous leg seeds are independently verified before reuse. Both reruns made **zero new conic path solves or potential proposals**. Each visited 67 tree nodes, stored 232 nodes and found a witness on its first complete skeleton. The 165 alternative open leaves remain explicit: these are witness proofs, not exhaustive exclusions. Full tree coverage is unnecessary to certify existence.

## Witness details

The uniform mission uses these mutable routes (inactive suffixes omitted):

- U1: T10 → T14 → T22 → T9 → depot.
- U5: T15 → depot → T16 → T20 → T6 → depot.
- U6: T11 → depot → T12 → T13 → T19 → depot.

The clustered mission uses:

- U2: T1 → T10 → T24 → T4 → depot.
- U4: T14 → T19 → depot → T21 → T7 → depot.
- U6: T22 → T12 → T16 → T9 → depot.

Other routes retain their original fixed coordinates. Assignments and commitments are checked against the original scenario. The exact witnesses include all paths, reserve paths, rational transfer values and their floating projections. Conservative delivery completion is approximately 0.820371 h for uniform T15 (deadline 3.464939 h, delivery 1 unit), and 0.530108 h for clustered T22 (deadline 1.210130 h, delivery 1.5 units).

## Reproduction and evidence

The full project suite passed **546 tests**, including the three new proposal/order tests. Both complete new records and all historical baseline evidence also pass replay with numerical LP/conic solvers and the Level-2 search/quantity producers patched to raise. Fresh standalone replay and full-run auditing both passed.

Run from `code/` with the project Python environment:

```powershell
.venv/Scripts/python.exe scripts/continue_level2.py
.venv/Scripts/python.exe scripts/continue_level2.py --verify
.venv/Scripts/python.exe scripts/replay_level2.py results/level2_continuation_2026_10_06/v1/records/CB_24_6_uniform_61002_below.json results/level2_continuation_2026_10_06/v1/records/CB_24_6_clustered_61002_below.json
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.venv/Scripts/python.exe -m pytest -q
```

The runner refuses an existing output manifest. Use `--output` with a fresh directory for another run. `--verify` checks the archived source, hashes of prior inputs, full historical evidence, exact witnesses, independent tree replay and all 385 preserved prior evidence files.

Pytest plugin autoload is disabled because the environment's unrelated Dash plugin fails during collection with a missing `typing_extensions` dependency; no project runtime dependency was changed.

- [Summary](../results/level2_continuation_2026_10_06/v1/summary.json)
- [Uniform proof record](../results/level2_continuation_2026_10_06/v1/records/CB_24_6_uniform_61002_below.json)
- [Clustered proof record](../results/level2_continuation_2026_10_06/v1/records/CB_24_6_clustered_61002_below.json)
- [Source and input manifest](../results/level2_continuation_2026_10_06/v1/manifest.json)
- [Run log](../results/level2_continuation_2026_10_06_run.log)
- [Standalone replay](../results/level2_continuation_2026_10_06_standalone.log)
- [Optimizer-free full-record audit](../results/level2_continuation_2026_10_06_optimizer_free.log)
- [Full audit](../results/level2_continuation_2026_10_06_audit.log)
- [Regression log](../results/level2_continuation_2026_10_06_tests.log)

The frozen October 5 results remain unchanged. With this follow-up, the thirteen original Level-2 targets comprise three minimum-2 witnesses and ten Level-2 exclusions, with no remaining Level-2 unresolved cases. Higher-scope conclusions for excluded targets remain in their separate Level-3/Level-4 records.
