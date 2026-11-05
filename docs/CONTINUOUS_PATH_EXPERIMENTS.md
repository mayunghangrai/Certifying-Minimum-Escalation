# Continuous-path experiments

The October 5 extension generates admissible polylines anywhere in the flight region. `PathLibrary` is absent from its feasibility and exclusion checks. The original Study 3 records are preserved, and new experiments use separate directories.

## Evidence and its limits

The first implementation covers stationary, fully covered admissible wind, idle depot origins, the revised five-level scope contract, and uncoupled depot preparations. Time-dependent wind and coupled depot bays return an explicit unresolved result.

The path generator proposes straight flights, incumbent curves and detour itineraries. It continuously optimizes wind-cell crossing coordinates with Clarabel. Every returned curve is independently split at cell boundaries and integrated using rational outward bounds. An interface follows the scenario's lowest-cell-ID ownership rule. Numerical solver status never establishes feasibility or infeasibility.

Feasibility-only queries can retain a zero-wind straight chord without exploring detours. Global-bound queries continue to propose detours and potential fields. Deadline proofs prioritize relevant prefixes. Higher-level proposals first check direct candidates and skip fixed-quantity candidates that fail even when all flight costs are set to zero. These shortcuts reduce numerical work while retaining explicit uncertainty.

For a displacement `d` in wind `w` at airspeed `v`, let `A = v² - ||w||²`. Flight duration is

```
(sqrt((w·d)² + A ||d||²) - w·d) / A.
```

The independent checker encloses the square root with rational numbers. Upper durations conservatively delay delivery and increase flight energy. Under the stated stationary, uncoupled assumptions, an exact feasible transfer problem using these upper durations proves mission feasibility. Equality involving irrational durations may remain unresolved. Increasing arithmetic precision narrows this uncertainty.

A continuous piecewise-affine potential supplies a global lower travel-time bound. On every triangle in a complete rectangular mesh aligned with the wind partition, the independent checker verifies

```
w·grad(phi) + v ||grad(phi)|| <= 1.
```

It checks the equivalent rational squared inequality after confirming the right-hand side is nonnegative. Shared vertex values make the potential continuous. Integrating its derivative along a flight proves that `phi(goal)-phi(start)` bounds every admissible path, including paths absent from the numerical proposals. The mesh parameterizes the potential; it does not discretize the admissible path domain. Spatially uniform wind uses the analytical displacement bound directly.

Level 0 holds every nominal A/S/P/L coordinate fixed and allows new auxiliary reserve witnesses. Level 1 releases only eligible nominal paths of the affected UAVs. Levels 2–4 use the existing sequence/transfer/assignment masks and helper unions. Fixed commitments survive all levels. Candidate quantities are independently checked; the higher-level proposal routine does not exhaust continuous quantities or all route skeletons.

Global prefix bounds can exclude Levels 0 and 1 when every allowed path misses a fixed positive delivery deadline or horizon. Existing independent physical deadline relaxations may exclude larger scopes. Energy or reserve failure of a candidate, exhausted itineraries, and timeouts leave uncertainty. This implementation does not provide a complete continuous-domain infeasibility solver for every constraint combination.

## Three stages

1. **Controlled validation:** ten cases cover Levels 0–4, global deadline infeasibility, an arbitrary-angle repair absent from the old axis library, analytical diagonal and constant-wind bounds, a wind detour without a stored bypass, and reserve-only Level 0 repair. Altered fields, interface ownership and commitments have regression tests.
2. **Paired Study 3 migration:** all 128 frozen October 1 scenarios are used without altering missions, incumbents, affected-set rules, quantities or helper budgets. Every archived record and source archive is bound to the new run. The comparison reports library conclusions, archived unrestricted conclusions, and new continuous evidence. Historical baseline timings use a different clock definition; they do not establish a speed ranking.
3. **Fresh continuous boundary cohort:** new seeds produce continuous zero-wind incumbents. A local adverse update must affect at most half the fleet and cause a material positive delay certified by a global lower bound. The tight deadline is placed below that lower bound; the loose deadline is placed above a validated fixed-sequence path time. Both retain certified previous feasibility. Only the selected critical task has a deadline, and resource headroom is declared in the sampling record. Capped failures are retained; admission never uses a recovery-level quota.

The cohort boundary is an interval containing the infimum of fixed-sequence delivery times over allowed paths. Its width is reported. A certified tight case demonstrates that continuous path repair is insufficient within Level 1. It does not itself establish which higher level is feasible.

The completed primary runs and their unresolved cases are documented in [the October 5 results](CONTINUOUS_PATH_RESULTS_2026_10_05.md). A separate derived table combines bounded-search evidence with independently verified witnesses retained during cohort construction. This table preserves the frozen search records and their measured costs.

## Reproduction

Use the existing project Python environment or install the additional proposal backend:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-continuous.txt
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Each experiment command takes a frozen configuration and a fresh output directory:

```powershell
.venv\Scripts\python.exe scripts/run_continuous_benchmark.py controlled --config configs/continuous_benchmark/controlled_primary.json --out results/continuous_reproduction/controlled
.venv\Scripts\python.exe scripts/run_continuous_benchmark.py paired --config configs/continuous_benchmark/paired_primary.json --out results/continuous_reproduction/paired
.venv\Scripts\python.exe scripts/run_continuous_benchmark.py cohort --config configs/continuous_benchmark/cohort_primary.json --out results/continuous_reproduction/cohort
.venv\Scripts\python.exe scripts/run_continuous_benchmark.py audit --out results/continuous_reproduction/paired
.venv\Scripts\python.exe scripts/run_continuous_benchmark.py report --out results/continuous_reproduction/paired
```

`audit` independently checks existing evidence without calling the numerical path or potential optimizer. It also checks the source archive, input bank and sampling ledgers. `report` writes case observations, path bounds, transition tables, conservative witness margins and a descriptive Markdown report under `analysis/`.

After generating all three stage reports, combine search and cohort admission evidence with:

```powershell
.venv\Scripts\python.exe scripts/summarize_continuous_results.py --root results/continuous_reproduction
```

This aggregation replays the stored evidence and publishes `analysis/cohort_combined_evidence.csv`, `summary.json` and its own reporting-source manifest. It requires the current experiment source to match all three frozen runs.

The new solver uses a total soft wall limit checked between numerical/proof operations, plus a proposal cap. A single operation can overrun the soft limit. Generation, controlled bound observations and independent replay are measured separately. Screen/proof components are nested measurements; they must not be added to obtain total cost.

`manifest.json`, `source.zip`, `records/*.json` and `sampling/*.json` are immutable publications. Completed cases are reused only after request binding and proof replay. A change to source, configuration or the input bank requires a new run directory. Reports are reproducible derived files and can be regenerated.

## APIs

```python
from continuous.oracle import ContinuousOracle, verify_query
from continuous.search import recover_continuous, verify_continuous_evidence

oracle = ContinuousOracle(scenario, refinements=(1, 2))
query = oracle.query("U1", start, goal)
assert verify_query(scenario, query)

result = recover_continuous(scenario, max_seconds=10, max_proposals=120)
assert verify_continuous_evidence(scenario, result)
print(result["full_domain"])
```

`full_domain` contains the lower and upper intervention bounds, certified minimum when they agree, and excluded levels. A validated path can tighten the upper bound. Only independently replayed all-path evidence can raise the lower bound. All unknown conclusions remain in the case tables.
