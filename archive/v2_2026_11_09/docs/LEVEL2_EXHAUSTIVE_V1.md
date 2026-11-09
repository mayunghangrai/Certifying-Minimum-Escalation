# Level-2 Exhaustive Search v1

This implementation decides whether a fixed-assignment recovery can be certified over the existing finite route-slot domain. It preserves the model's permitted task repetitions, depot stops/revisits, inactive suffixes, fixed coordinates and commitments. Its domain is not restricted to customer permutations or a path library.

## Four modules

- `src/level2/skeletons.py`: raw next-slot alphabet and necessary structural exclusions. Every mutable stop branches over `None`, `DEPOT` and every remaining task assigned to that UAV. Fixed stops retain their original value. Assignment requires every assigned task to occur, including optional tasks. Fixed paths constrain endpoints and padding; fixed quantities constrain transfer eligibility.
- `src/level2/bounds.py` and `search.py`: explicit branch tree, full child partitions, global continuous lower bounds and optimistic empty-payload time/energy/reserve checks. Initial and intermediate depot preparations recharge before departure. Deadline pruning refers only to an unvisited task that requires positive residual mandatory delivery. A previously visited task may be served later or receive zero at a late visit.
- `src/level2/quantities.py`: exact rational primal and Farkas checks for the existing affine mission-resource model. Numerical LP solutions and dual rays are proposals and are checked or repaired with rational arithmetic. Bounded rational elimination is the fallback. Missing global lower bounds are safely zero. Lower-duration infeasibility excludes the skeleton; upper-duration feasibility certifies selected continuous paths. Failure of the upper-duration model does not exclude the continuous domain.
- `src/level2/replay.py` and `scripts/replay_level2.py`: separate coverage implementation. It reconstructs the slot domain and verifies every branch and terminal proof without importing the Level-2 producer, bounds or quantity orchestration modules or calling an optimizer. It shares the trusted environment scope rules, continuous arithmetic/potential checks, affine transfer compiler and rational Farkas checker.

## Conclusions and limits

`WITNESS` supplies an exact rational quantity point and conservative path-duration intervals. The float plan is its display projection; the rational strings are authoritative. Open siblings can remain because feasibility is existential.

`EMPTY` requires every raw route-slot region to be closed by a verified structural, resource or rational quantity contradiction. It certifies that sequence/quantity repair within Level 2 is insufficient over all admissible continuous polylines. Establishing minimum Level 3 additionally needs Level-3 feasibility evidence.

`UNRESOLVED` retains all unfinished frontier regions, geometry gaps and rational solver limits. Exhaustive means that the algorithm branches over the complete declared finite slot domain; finite search budgets do not guarantee exhaustive completion or exact continuous path optimization. The oracle's selected itineraries never define the exclusion domain.

Supported physics: revised v2 scope, idle depot origins, stationary fully covered admissible wind, and uncoupled depot preparation. Other modes remain unresolved. Continuous potential construction can fail or leave gaps; a proposal failure retains a zero bound or an open leaf.

## Thirteen-case follow-up

The runner selects exactly the twelve unresolved tight cohort inputs and the separate unresolved paired input from `results/continuous_paths_2026_10_05/primary/`. It checks case identity, scenario/request hashes, prior run binding and frozen source archives. It does not generate cases. Existing continuous certificates are independently checked and reused; reported timings therefore concern follow-up work with warm prior evidence.

```powershell
.venv\Scripts\python.exe scripts/run_level2_targets.py --output results/level2_exhaustive_2026_10_05/v1
.venv\Scripts\python.exe scripts/run_level2_targets.py --output results/level2_exhaustive_2026_10_05/v1 --verify
.venv\Scripts\python.exe scripts/replay_level2.py results/level2_exhaustive_2026_10_05/v1/records/CB_3_3_clustered_61003_below.json
```

The default per-case limits are 60 seconds and 100,000 processed prefix nodes; the total clock is soft and checked between operations. Setup, oracle queries and LP operations are included. New tree replay is measured separately. Baseline evidence replay and final complete-run auditing add overhead. A source/budget change requires a new output directory.

Every new run freezes source and input bindings and stores immutable case records. Mathematical replay includes both prior continuous evidence and the new Level-2 tree before deriving a combined minimum interval. The previous benchmark records remain untouched.

## Verification

Tests compare full small domains against independent brute-force validation and cover repeats, depot revisits, padding, partial commitments, late zero-delivery visits, fractional quantities, Farkas tampering, recharge, missing branches, cycles, unreachable nodes, forged witnesses and optimizer-free replay. The standalone command is checked in a fresh process against valid and altered coverage.

In the current bundled environment, disable unrelated third-party pytest plugin autoload:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.venv\Scripts\python.exe -m pytest -q
```
