# Level-3 Certified Reassignment v1

This milestone wraps the full route-slot sequence engine in certified helper-patch and assignment search. Every commitment and release mask refers to the unchanged original scenario. Candidate assignments are explicit inputs; the original incumbent is never replaced to accommodate a candidate.

## Eight acceptance criteria

1. **Helper coverage:** the report lists the complete canonical maximal Level-3 helper family. These patches cover smaller permitted participant sets by inclusion. Each patch has an assignment tree, including an explicit open root when it was not reached.
2. **Assignment coverage:** tasks are represented in canonical order. A fixed A coordinate has its sole original owner; a released coordinate branches over `None` and every fleet UAV. Each branch lists all children. A fixed-route certificate closes incompatible outside-patch ownership; it is not silently omitted.
3. **Explicit inner context:** `search_sequence(original_scenario, assignment, patch, ...)` receives the chosen assignment and original permitted release mask. Its proof stores both, and its scenario hash remains the original hash. The legacy `search_level2` wrapper and proof schema remain supported.
4. **Certified pruning only:** positive residual mandatory delivery cannot be unassigned; a completely fixed route cannot acquire an unvisited task; a fixed task stop cannot contradict ownership; distinct assigned tasks need at least one slot each plus the terminal depot; and an all-path optimistic delivery bound can rule out a mandatory deadline. Every rule is independently reconstructed. Depot replenishment, repeated visits, optional zero delivery and every permitted slot structure remain available.
5. **Uncertainty propagation:** an inner unfinished sequence/geometry/quantity proof makes its outer assignment region unresolved. Only complete exclusion of all assignment regions in every helper patch excludes Level 3. A valid witness can stop search while other regions remain explicitly open.
6. **Independent replay:** `level3/replay.py` imports no outer producer or cache. It checks the patch family, raw owner partitions, every assignment exclusion, and every attached full-slot proof via the independently implemented sequence checker. No numerical optimizer is required. Original scope, arithmetic, potential and transfer/Farkas checks are the trusted common primitives.
7. **Cache isolation:** the shared cache is bound to the original scenario, vehicle/endpoints, refinement configuration and interval precision. Lower bounds and selected paths are generated separately from canonical original inputs. Cache entries are copied on return; every inner call gets a new view containing only its own consumed query snapshots. The outer tree stores its consumed lower certificates separately. Warming irrelevant entries, changing query order or mutating returned objects cannot change stored mathematical evidence. Cold/warm semantic equivalence is tested with sufficient time and fixed node limits. Cache speed can affect how much work fits inside a wall limit; unfinished work retains its actual explicit frontier.
8. **Frozen targets and records:** select exactly the eight prior Level-2 exclusions with unknown higher minima. Validate prior source archives and original record/run bindings. Hash every file in the primary continuous and Level-2 experiment directories before and after the run and during audit. Produce new immutable records under a new directory.

## Modules and evidence

- `src/level2/skeletons.py` and `search.py`: parameterized assignment-preserving full-slot kernel; legacy Level-2 entry point retained.
- `src/level2/replay.py`: independent explicit-assignment sequence replay; original commitments and release-mask authorization retained.
- `src/level3/cache.py`: immutable scenario-scoped global lower certificates and local continuous-query evidence views.
- `src/level3/search.py`: full helper family, assignment B&B and a single total per-case time/node budget shared with all sequence calls.
- `src/level3/replay.py`: independent outer and inner coverage/conclusion verification.
- `src/level3/targets.py`: exact eight-target selection, source/input/record provenance, combined hierarchy bounds and prior-byte auditing.

Outer `WITNESS`, combined with prior exclusion of Levels 0–2, certifies minimum 3. `EMPTY` raises the lower bound to 4 without claiming Level-4 feasibility. `UNRESOLVED` preserves the prior lower bound of 3. Attached quantity witnesses carry exact rational strings; their float plans are projections.

Physics support remains stationary, fully covered admissible wind, idle depot origins and uncoupled preparations. Other modes stay unresolved. Potential/curve generation and rational solver limits can leave inner regions open. Time caps are soft and checked between operations, so an individual optimization can exceed the cap.

## Commands

```powershell
.venv\Scripts\python.exe scripts/run_level3_targets.py --output results/level3_certified_2026_10_05/v1
.venv\Scripts\python.exe scripts/run_level3_targets.py --output results/level3_certified_2026_10_05/v1 --verify
.venv\Scripts\python.exe scripts/replay_level3.py results/level3_certified_2026_10_05/v1/records/CB_3_3_uniform_61001_below.json
```

The default budget is 60 seconds and 100,000 processed outer/inner nodes per case. It is shared across helper patches and sequence calls. Prior verified continuous evidence seeds each scenario's cache. Search timing includes setup and cache work; new proof replay is measured separately. Baseline audits, full-run audits and tests add overhead. Source or configuration changes require a new output directory.

Prior source archives remain authoritative for reproducing older runs. The live code has evolved, so older source-equality checks should use their frozen runtime rather than requiring the new implementation to equal an old snapshot. Mathematical legacy proofs remain replayable against the unchanged original scenarios.

## Verification

Tests cover reassignment under original commitments, helper participation with unchanged assignment, partial assignment child coverage, all five pruning rules, missing/reordered helper patches, every attached proof, explicit unresolved propagation, corrupted masks, committed task ownership conflicts, cold/warm cache equivalence, alias isolation, substituted input runs and fresh-process CLI rejection of altered evidence.

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.venv\Scripts\python.exe -m pytest -q
```
