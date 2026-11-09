# Deterministic small-instance recovery search

The solver searches the five existing intervention scopes using a fixed finite library of nominal and return paths. Assignments, visit sequences, nominal curves and reserve choices are discrete; loading and delivery amounts remain continuous. A zero-objective linear feasibility problem finds quantities for each route skeleton. The outer search minimizes the original intervention label; it does not optimize energy, duration or humanitarian utility within a level.

## Run and reuse

From `code/`, after installing `requirements.txt`:

```powershell
.venv\Scripts\python.exe scripts/search_recovery.py --scenario scenarios/worked/four_uav_case_a.json --exhaustive --output docs/recovery_results/search_case_a.json
.venv\Scripts\python.exe scripts/search_recovery.py --scenario scenarios/worked/four_uav_case_b.json --exhaustive --output docs/recovery_results/search_case_b.json
```

The CLI works from any directory when given absolute scenario/output paths. Without `--output`, it prints JSON. Without `--exhaustive`, it stops after finding a validated witness; an unresolved lower level does not prevent looking for a higher-level witness. Exit 0 indicates a produced report, not necessarily a successful recovery. Exit 2 identifies invalid input. An output path cannot overwrite a scenario or manifest input.

Python API (with `code/src` on `sys.path`):

```python
from env.scenario import Scenario
from recovery import PathLibrary, recover, search_level, verify_level_evidence

scenario = Scenario.from_json("scenarios/worked/four_uav_case_a.json")
library = PathLibrary.build(scenario)
result = recover(scenario, library)

partial = search_level(scenario, library, 3, max_nodes=10, exhaustive=True)
continued = search_level(scenario, library, 3, cursor=partial.cursor,
                         max_nodes=100_000, exhaustive=True)
assert partial.to_dict()["nodes"] == 10  # Prior reports remain snapshots.
```

Continuation retries unresolved branches when LP budgets or numerical settings change, then resumes enumeration. It skips identical unsuccessful LP attempts so unresolved arithmetic cannot starve unexamined branches. Retries consume node/branch allowances but do not change branch indices or enumeration evidence. The live cursor is in-process state, not an authenticated checkpoint. Saved cursor counters identify replay positions; restarting a process requires deterministic replay. Original scenario and library hashes must match.

## Representation and enumeration

`PathLibrary.build` includes admissible straight paths between task/depot/observed-origin coordinates, constant paths, every incumbent curve, and every supplied previous return witness. Extra `nominal_paths` and `return_paths` are optional explicit polylines. `direct=False` restricts construction to supplied/incumbent paths and depot padding. Nonconvex regions may prevent straight paths; the solver does not silently generate detours. Supply those curves explicitly if needed.

The manifest records canonical curves, slot bounds, schema version and scenario hash. Curve identity removes redundant forward-collinear vertices, preserving turns and backtracking. Its canonical hash identifies the representation. Save the report's `representation` object as a standalone JSON file and pass `--manifest` to reuse it. `PathLibrary.from_dict` checks membership of incumbent and previous witness paths, scenario identity, endpoints, geometry and padding. A single manifest is held fixed across all compared levels.

Enumeration is lazy and deterministic. It considers active-prefix stop sequences ending at depot, null padding, repeated visits, optional unassigned tasks, compatible committed coordinates, single-UAV ownership per visited task, every represented nominal curve and every required return-path combination. It never grids quantities. Partial expansions count toward budgets, including work before a complete skeleton appears. The default straight-path representation is finite and intentionally small; it is not all possible continuous geometry.

## Timing and continuous constraints

For a chosen skeleton, constant ground durations and wind-aware path integration fix the schedule independently of the quantities. The compiler then enforces nonnegative transfers; delivery availability; mandatory and maximum service; shared stock; payload before/after transfers; affine flight energy; battery at arrivals and after service; pre-recharge depot reserve; post-service and initial return reserve; terminal safety; fixed transfers; and zero delivery for a visit completing after its deadline. Intermediate depot visits retain carried payload and reset battery. Residual ground operations use their committed remaining duration, energy and quantity. Depot bays have half-open occupancy intervals and no queue.

Horizon and bay failures can exclude a fully selected skeleton without an LP. A failed selected reserve path excludes that choice only. Exhaustion of a return library proves only represented failure. Every proposed plan is checked through the original combined recovery validator, plus representation membership and a fresh exact primal check when supported. Simulator feasibility uses its existing `1e-9` tolerance.

## Exact and numerical evidence

Normalized scenario JSON decimals are interpreted as rational numbers. An independent rational path integrator computes polygon-edge intersections, boundary ownership, time-bin crossings and wind speeds. Exact mode supports rational lengths and rational square roots of the wind expressions. Irrational expressions or unavailable arithmetic fall back to numerical proposals, unless `--exact-only` is selected.

Bounded Fourier–Motzkin elimination returns either a rational point checked against every original inequality, a nonnegative combination of original rows yielding `0 <= negative`, or unresolved. `verify_exclusion` independently checks that combination. `verify_level_evidence` reconstructs enumeration and every branch constraint/exclusion; it does not trust an LP's infeasibility status. Numerical [SciPy/HiGHS](https://docs.scipy.org/doc/scipy/reference/optimize.linprog-highs.html) solves the continuous zero-objective LP as a proposal backend. Its status alone never certifies emptiness. Rational reconstruction of a numerical proposal is accepted as exact only if every original rational inequality passes.

Exact witness quantities are stored in `exact_transfers`; `plan` contains float projections for the existing simulator. Exact scope membership compares the fractions against incumbent decimal rationals. Thus an exact `1/3` is distinguished from a stored `0.3333333333333333`, even if their float projections coincide.

Input diagnosis requires a simulator-feasible previous incumbent. `previous_premise.exact_feasible` separately reports `true`, `false`, or `null` (unsupported arithmetic) for exact-decimal previous feasibility. An exact minimum over the received-wind feasible sets remains meaningful when this flag is false, but that input does not qualify as an exact feasible-before-update benchmark. Both published worked examples have this flag true. Diagnostic supports/neighborhoods remain the existing conservative, tolerance-reporting construction; they are frozen during search.

| Outcome | Evidence |
|---|---|
| `MINIMUM_CERTIFIED_R` | An exact witness and matching exact lower/upper intervention bounds. |
| `WITNESS_WITH_GAP_R` | An exact witness; a smaller level remains unresolved. |
| `NUMERICAL_WITNESS_R` | Simulator-validated recovery without an exact primal certificate; separate `numerical_upper_bound`. |
| `NO_CONTINUATION_R` | Every branch of represented Level 4 soundly excluded. |
| `UNRESOLVED_R` | No verified witness and no complete represented exclusion. |

An empty level excludes smaller nested levels. Identical release masks share one search and retain their original labels. Timeouts, failed numerical construction and incomplete enumeration never imply emptiness. JSON `null` for `upper_bound` means no certified finite upper bound; `lower_bound=null` occurs only for certified represented no-continuation. `feasible_branches` counts discrete skeleton/return selections admitting at least one transfer solution, not the number of continuous plans.

## Budgets and measured evidence

Defaults are 100,000 generator events and 2,000 branch attempts per distinct level, 500,000 generator events overall, 10,000 exact elimination pair operations and 2,000 rows per LP, plus 10,000 numerical simplex iterations. CLI flags expose each limit. Input validation, diagnostic construction and proof replay are outside enumeration budgets; these are work counters, not wall-clock guarantees. Exhaustive mode still respects all limits.

`strategy='level4'` (CLI `--strategy level4`) searches Level 4 immediately. It reports the smallest scope containing its witness, but generally retains lower bound 0 because smaller scopes have not been excluded. The default is `strategy='ascending'`. `total_branches=N` (CLI `--total-branches N`) adds a shared branch-attempt ceiling across scopes, alongside `total_nodes`. Existing `max_branches` remains a per-scope ceiling. Reports include `strategy`, `branches_used` and `total_branch_budget`; equivalent masks consume work once. Controlled comparisons must set both shared ceilings and identical per-LP limits.

The controlled 2026-09-28 pilot is documented in [CONTROLLED_BENCHMARK_2026_09_28.md](CONTROLLED_BENCHMARK_2026_09_28.md), with frozen inputs, budgets, source snapshots, repeated measurements and independent proof audits.

Saved exhaustive reports in `docs/recovery_results/` reproduce:

| Case | Structural branches at Levels 0–4 | Feasible branches | Certified minimum |
|---|---|---|---|
| A | 1, 1, 1, 2, 4 | 0, 0, 0, 1, 2 | 3 |
| B | 1, 1, 1, 24, 24 | 0, 0, 0, 6, 6 | 3; Levels 3/4 share a search |

Tests also exercise recoveries at Levels 0/1/2, fractional quantities, residual operations, returned payload/recharge, alternate reserve witnesses, shared boundaries, horizon/bin crossings, exhausted budgets and resumed LP work, proof tampering, wrong-scope/path rejection, and deterministic CLI replay. General algebraic certification, persistent resumable checkpoints, scalable optimization, policies and learning remain outside this implementation. No timing advantage or real-time capability is claimed.
