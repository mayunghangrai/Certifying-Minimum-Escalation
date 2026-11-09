# Wind-only simulation benchmark

## Escalation study and in-flight updates: October 8

A paired design (P1) certifies how the minimum intervention level changes with deadline slack, wind strength and tasks per UAV; comparators, a runtime profile and in-flight updates (E1) reuse it. Read the [guide](docs/ESCALATION_STUDY.md), the [pilot results](docs/ESCALATION_PILOT_RESULTS_2026_10_08.md) and the [primary results](docs/ESCALATION_PRIMARY_RESULTS_2026_10_09.md).

```powershell
.venv\Scripts\python.exe scripts/run_escalation_study.py p1 --config configs/escalation_study/p1_primary.json --out results/escalation_study_primary --workers 6
.venv\Scripts\python.exe scripts/run_escalation_study.py p1 --config configs/escalation_study/p1_primary.json --out results/escalation_study_primary --workers 6 --phase pass2
.venv\Scripts\python.exe scripts/run_escalation_study.py audit --out results/escalation_study_primary --workers 6
.venv\Scripts\python.exe scripts/run_escalation_study.py report --out results/escalation_study_primary
```

## Continuous-path extension: October 5

The new runner generates arbitrary-angle flight paths and verifies global travel-time bounds over the continuous region. The completed primary runs certify all ten controls, 127/128 paired minima and 50/62 fresh-cohort minima when stored admission evidence is included. Continuous witnesses prove a library penalty in 39 paired cases. Read the [results](docs/CONTINUOUS_PATH_RESULTS_2026_10_05.md) and [implementation guide](docs/CONTINUOUS_PATH_EXPERIMENTS.md). The current implementation supports stationary wind and uncoupled depot preparations; exhausted numerical proposals retain unresolved conclusions.

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-continuous.txt
.venv\Scripts\python.exe scripts/run_continuous_benchmark.py paired --config configs/continuous_benchmark/paired_primary.json --out results/continuous_reproduction/paired
.venv\Scripts\python.exe scripts/run_continuous_benchmark.py audit --out results/continuous_reproduction/paired
.venv\Scripts\python.exe scripts/run_continuous_benchmark.py report --out results/continuous_reproduction/paired
```

## Study 3 refinement: near-boundary missions

The October 1 extension generates paired missions just above and below two declared deadline boundaries: retaining the incumbent and repairing its paths with sequence and quantities fixed. Read the [results and interpretation](docs/STUDY3_NEAR_BOUNDARY_RESULTS_2026_10_01.md) and the [frozen protocol](docs/STUDY3_NEAR_BOUNDARY_PROTOCOL.md). Results are conditional on a local adverse wind update; they remain separate from the original randomized population. Both represented and full-domain labels retain unresolved cases.

```powershell
.venv\Scripts\python.exe scripts/final_benchmark.py near --config configs/final_benchmark/near_boundary_primary.json --output results/near_boundary_reproduction
.venv\Scripts\python.exe scripts/final_benchmark.py audit --output results/near_boundary_reproduction
.venv\Scripts\python.exe scripts/report_near_boundary.py --run results/near_boundary_reproduction --output results/near_boundary_reproduction/analysis
```

The main configuration requests 64 base pairs (up to 128 cases) after two development pilots. A generation failure remains in the sampling ledger; it is not replaced. The runner uses one process, exact stationary path screens, bounded generic repair proposals, and replayable represented/physical exclusions. The five-second cap applies to proposals; setup, exact screens, proof construction, generation, and replay are additional measured work.

## Current manuscript: 2026-09-30 final benchmark

The versioned final benchmark implements the revised local hierarchy, exact evidence replay, six controlled cases, boundary experiments, and seeded scaled missions. Read [the results and their limits](docs/FINAL_BENCHMARK_RESULTS_2026_09_30.md) and [the implementation and reproduction guide](docs/FINAL_BENCHMARK_IMPLEMENTATION.md). Its v2 records distinguish represented minima, unrestricted path-domain claims, and unresolved outcomes.

```powershell
.venv\Scripts\python.exe scripts/final_benchmark.py controlled --output results/final_benchmark_reproduction/controlled
.venv\Scripts\python.exe scripts/final_benchmark.py boundary --config configs/final_benchmark/boundary_primary.json --output results/final_benchmark_reproduction/boundary
.venv\Scripts\python.exe scripts/final_benchmark.py random --config configs/final_benchmark/random_primary.json --output results/final_benchmark_reproduction/random
```

Use a fresh output directory for changed source or configuration. The archived September 30 records remain under `results/final_benchmark_2026_09_30/` and can be replay-audited without rerunning search.

## Legacy v1 benchmark

This code implements paired wind diagnosis, recovery-plan validation, and a deterministic small-instance recovery solver for the finalized **2026-09-17 formulation**. The solver enumerates routing choices in a declared finite path library and solves continuous transfer feasibility across the five intervention scopes. No policy or learning method is included.

The authoritative source snapshots are in `docs/formulation/2026-09-17/`; their original locations and SHA-256 hashes are recorded in `sources.json`. The later manuscript's four-UAV Cases A/B are in `scenarios/worked/`, with their source material and hashes in `docs/formulation/`. Reference search reproduces their feasible counts and certifies minimum Level 3 within the saved path representations.

## Run

Create the Conda environment from `environment.yml`, or use a local Python environment:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q
.venv\Scripts\python.exe scripts/run_simulation_benchmark.py --output docs/benchmark_results.json
```

The CLI resolves the three frozen fixtures relative to its own location. It can also evaluate a caller-supplied fixture with `--scenario path.json` (repeat for multiple scenarios). Inputs must have a validated feasible incumbent under the previous wind table; the updated table may retain or lose feasibility. Output contains both induced traces, input hashes, the typed dependency DAG, affected tasks, the reassignment neighborhood, and five-level release counts. It does not infer a minimum repair level.

Validate an externally supplied plan using a JSON request containing exactly `level`, `plan` (the same A/S/P/L structure as `incumbent`), and `reserve_paths`:

```powershell
.venv\Scripts\python.exe scripts/validate_recovery_plan.py --scenario scenarios/worked/four_uav_case_a.json --candidate examples/recovery/case_a_east_exchange.json --output docs/recovery_results/case_a_validation.json
```

The combined report separates structural validity, commitments, scope membership at each level, mission feasibility, and reserve checks. Missing or unsuccessful reserve witnesses remain unresolved; malformed witnesses are rejected while the mission is still checked. Exit codes are 0 for a validated witness, 1 for a rejected/unresolved candidate, and 2 for invalid command/request/scenario input. Omitting `--output` prints the full JSON report. A successful candidate provides `feasible_level_upper_bound`; `minimum_certified` remains false. The bound may be tighter than the requested level when this same candidate belongs to a smaller space.

## Search

Search a small instance:

```powershell
.venv\Scripts\python.exe scripts/search_recovery.py --scenario scenarios/worked/four_uav_case_a.json --exhaustive --output docs/recovery_results/search_case_a.json
.venv\Scripts\python.exe scripts/search_recovery.py --scenario scenarios/worked/four_uav_case_b.json --exhaustive --output docs/recovery_results/search_case_b.json
```

Omit `--exhaustive` to stop at the first validated witness. `--manifest paths.json` accepts a saved `representation` object from a report. Search defaults to 100,000 enumeration events and 2,000 branches per distinct level, 500,000 events overall, and bounded exact elimination. `--exact-only` disables numerical proposals. Exit 0 means a report was produced, including unresolved or empty results; invalid inputs exit 2. The report embeds the path manifest, budgets, input hashes, witnesses, exact exclusions, and intervention bounds. See [RECOVERY_SEARCH.md](docs/RECOVERY_SEARCH.md) for arithmetic guarantees, API examples, live continuation, and representation limits.

## Controlled experiments

The [2026-09-28 controlled benchmark report](docs/CONTROLLED_BENCHMARK_2026_09_28.md) compares ascending scopes and immediate Level 4 across wind, deadline, battery and nested path-library sweeps. Each strategy receives the same shared node/branch ceilings and exact LP limits. Run into a **new** directory; existing runs are protected from overwrite:

```powershell
.venv\Scripts\python.exe scripts/run_controlled_benchmark.py --output results/my_controlled_run
.venv\Scripts\python.exe scripts/run_controlled_benchmark.py --output results/my_controlled_run --verify
.venv\Scripts\python.exe -m pip install -r requirements-experiments.txt
.venv\Scripts\python.exe scripts/plot_controlled_benchmark.py results/my_controlled_run
```

`instances.json`, `protocol.json`, `provenance.json`, `source_snapshot.zip`, JSONL reports/measurements and integrity locks preserve the study. Timing repeats are not additional scientific samples. `NO_CONTINUATION_R` is restricted to the saved finite representation; incomplete searches remain unresolved.

## Contract

- Exactly one divisible commodity: demand, mandatory service, stock, loads, deliveries and onboard quantities are scalar commodity units; a positive unit mass converts them to kg.
- One immutable mission, history summary, observed fleet state, incumbent, operation protocol, and commitment mask are shared by both wind projections. The fixtures share these values across all three cases as well.
- Both cell-time wind tables cover the whole remaining horizon. A declared proper local support contains every changed entry, and every wind magnitude is strictly below every UAV's airspeed. Cells index wind; every direction is traversable.
- Supplied polylines are split at cell boundaries and integrated exactly within each constant-wind time bin. Lowest cell ID owns shared boundaries; temporal bins are right-open except at the final horizon endpoint. Power is `gamma * (empty_mass + unit_mass * onboard) * airspeed`.
- Fixed-slot A/S/P/L plans allow repeated partial visits by one responsible UAV, intermediate depot preparation, residual committed operations, and canonical inactive padding. Scope 0 retains; 1 releases paths; 2 also releases sequence and transfers; 3 also releases assignments in the task-constraint closure; 4 releases all mutable coordinates. Commitments survive every level.
- Feasibility checks mandatory quantities, deadlines at service completion, payload/stock/battery, pre-recharge reserves, terminal return, bay overlaps and supplied reserve witnesses. Ground operations follow fixed rules; there is no implicit queue or waiting decision. A failed supplied reserve path is unresolved, not proof of nonexistence.
- Wind diagnosis uses the union of nominal and reserve queries from both evaluations. Each deterministic path-integration node includes time-bin selection and horizon guards. An unavailable evaluation conservatively includes every time bin along its fixed geometry. Structural reachability precedes unit-specific numerical reporting tolerances; direct contact can remain reportable even when physical values do not change.
- Affected tasks are incident to reportable legs, including propagation to unchanged cells and initial reserve contact attributed to the first leg. Their task-constraint closure includes committed task vertices; commitment filtering occurs only afterward. Committed path endpoints can restrict potential task participation. Shared stock, bays, or unrestricted participation can legitimately make Levels 3 and 4 equal.

`Scenario.from_json(...)` validates the closed JSON schema and semantic invariants. `evaluate_pair(scenario)` checks the previous-wind premise and evaluates the fixed incumbent twice. `evaluate_plan(scenario, candidate, projection=..., reserve_paths=...)` evaluates a structurally valid caller-supplied candidate with its supplied witnesses. `check_scope(...)` checks only permission, independently of feasibility.

```python
import json
from pathlib import Path
import sys
sys.path.insert(0, "src")  # Run from code/.

from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update
from env.recovery_validation import validate_recovery_plan

scenario = Scenario.from_json("scenarios/worked/four_uav_case_a.json")
diagnostic = diagnose_wind_update(scenario)
# diagnostic.graph, .affected_tasks, .task_closure, .neighborhood
request = json.loads(Path("examples/recovery/case_a_east_exchange.json").read_text())
report = validate_recovery_plan(scenario, request["plan"], request["level"],
                                reserve_paths=request["reserve_paths"])
payload = report.to_dict()
```

The low-level `release_sets`/`check_scope` APIs still accept explicit `affected_tasks` and optional conservative supports. The benchmark CLI and recovery validator obtain those tasks automatically from `diagnose_wind_update`; no illustrative seed is inserted. The combined validator evaluates physical behavior even when commitments or scope fail, and never promotes that physical result into a successful recovery witness. Reporting tolerances are configurable through `diagnose_wind_update(..., tolerances={"time_h": ..., "energy_wh": ...})`; they never alter graph edges or the evaluator's feasibility tolerance.

The JSON schema is `schemas/wind-benchmark-v1.schema.json`. `scenarios/benchmark/manifest.lock` pins fixture bytes and content hashes; `docs/formulation/fixture_traceability.json` maps every fixture leaf to the formulation and tests. `docs/SIMULATION_READINESS.md` summarizes measured readiness and boundaries.

Six diagnostic fixtures in `scenarios/diagnostics/` cover irrelevant wind, unchanged speed despite changed wind, downstream effects, shifted bins, reserve-only impact, and late/undefined states. `docs/formulation/recovery_fixture_provenance.json` pins those examples, the two worked scenarios, supplied recovery requests, and imported manuscript sources. Saved combined reports and diagnostic traces are in `docs/recovery_results/`.

## Migration

This is a deliberate schema/API break. Prior versions, commodity vectors, flight-exclusion fields, rolling forecast coverage and unknown nested fields are rejected; no legacy migration adapter remains. The exact predecessor runtime and tests are preserved as historical data in `archive/pre_2026_09_17/runtime.zip` with a verified manifest. They are outside active imports and test discovery. Historical research documents and presentation artifacts are not benchmark evidence.
