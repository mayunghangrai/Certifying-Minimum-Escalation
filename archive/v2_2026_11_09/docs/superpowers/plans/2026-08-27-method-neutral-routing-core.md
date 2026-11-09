# Method-Neutral Information-Aware Routing Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy belief/ALNS environment with one standalone known-task scenario generator, a supplied-route evaluator, and a method-neutral execution simulator.

**Architecture:** `robust_scenario_generator.py` becomes the only generator and emits a lean version-2 schema. A pure `route_evaluator.py` evaluates but never constructs polylines; `simulator.py` executes caller-supplied load, flight, and delivery commands while revealing environmental information online. Every solver, baseline, belief update, learned observation, and automatic route search/replan is removed.

**Tech Stack:** Python 3.10, NumPy, PyYAML, Shapely, pytest, self-contained HTML/JavaScript.

**Spec:** `docs/superpowers/specs/2026-08-27-method-neutral-routing-core-design.md`

## Global Constraints

- Retain `src/env/robust_scenario_generator.py` as the only scenario generator.
- Do not implement allocation, sequencing, route search, waypoint generation, replanning, repair, or any comparison method.
- Every task is exactly known at `t=0`; no demand uncertainty or sensing field may remain.
- Weather/no-fly updates are visible at their physical update time; wind packets retain online issue/valid-time semantics.
- A dispatch must be hard-airspace-safe, completely covered by the latest received forecast, and battery-reserve feasible.
- Do not reset, checkout, stage, or commit unrelated user changes in the shared dirty working tree.
- Use `PYTHONDONTWRITEBYTECODE=1` and `pytest -p no:cacheprovider` for every test run.
- Do not create implementation commits from overlapping dirty files. The plan document is the final isolated documentation commit; implementation remains in the verified working tree.

---

### Task 1: Lock the version-2 scenario and configuration contracts

**Files:**
- Create: `tests/test_method_neutral_scenario.py`
- Modify: `tests/test_robust_scenario_generator.py`
- Modify: `tests/test_information_aware_scenario_artifacts.py`

**Interfaces:**
- Consumes: current `load_information_aware_config()` and `generate_information_aware_scenario()`.
- Produces: failing contracts for the lean `EnvParams`, exact `Scenario` schema, standalone generator, deterministic stream isolation, and renderer compatibility.

- [ ] **Step 1: Add strict configuration tests**

```python
def test_environment_configuration_rejects_legacy_sections():
    with pytest.raises(ValueError, match="unknown environment keys"):
        EnvParams.from_dict({"belief": {"sigma0_frac": 0.0}})
    with pytest.raises(ValueError, match="unknown environment keys"):
        EnvParams.from_dict({"hybrid": {"alns_iterations": 10}})


def test_information_aware_config_has_only_method_neutral_sections():
    params, route_information = load_information_aware_config(CONFIG)
    assert set(params.to_dict()) == {
        "physics", "commodities", "map", "route_validation", "mission"
    }
    assert route_information.mode == "mixed"
```

- [ ] **Step 2: Add the exact scenario-schema contract**

```python
def test_generated_scenario_uses_known_task_v2_schema():
    params, route_information = load_information_aware_config(CONFIG)
    scenario = generate_information_aware_scenario(42, params, route_information)
    payload = scenario.to_dict()
    assert set(payload) == {
        "seed", "params", "depot", "nodes", "initial_inventory",
        "no_fly_zones", "hazard_regions", "airspace_updates",
        "wind_spec", "generation_metadata",
    }
    assert set(payload["nodes"][0]) == {
        "idx", "x", "y", "vulnerability", "demand"
    }
    assert payload["generation_metadata"]["schema"] == (
        "information-aware-routing-v2"
    )
    assert len(payload["nodes"]) == 20
    assert all(sum(node["demand"]) > 0.0 for node in payload["nodes"])
```

- [ ] **Step 3: Prove the new generator is standalone and stream-isolated**

```python
def test_generator_has_no_legacy_base_generator_dependency():
    source = (ROOT / "src" / "env" / "robust_scenario_generator.py").read_text()
    forbidden = "from .scenario_" + "generator import"
    assert forbidden not in source


def test_disabling_weather_does_not_change_tasks_airspace_or_wind():
    params, mixed = load_information_aware_config(CONFIG)
    without_weather = dataclasses.replace(mixed, mode="airspace")
    a = generate_information_aware_scenario(42, params, mixed)
    b = generate_information_aware_scenario(42, params, without_weather)
    assert a.nodes == b.nodes
    assert a.no_fly_zones == b.no_fly_zones
    assert a.wind_spec == b.wind_spec
```

Wind generation remains enabled independently of polygon mode. This corrects
the current coupling that generates wind only when weather polygons are on.

- [ ] **Step 4: Update artifact assertions for lean fields**

The generated JSON must contain `"initial_inventory"`, `"vulnerability"`,
and `"demand"`, and must not contain the separately concatenated strings
`"mu" + "0"`, `"sigma" + "0"`, `"p1" + "_reports"`, or
`"p3" + "_mutations"`. The HTML must retain the forecast labels, embed the
scenario hash, and contain no `fetch(`.

- [ ] **Step 5: Run the focused tests and record RED**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
C:\Users\mayun\anaconda3\python.exe -m pytest -p no:cacheprovider tests/test_method_neutral_scenario.py tests/test_robust_scenario_generator.py tests/test_information_aware_scenario_artifacts.py -q
```

Expected: failures identify permissive legacy configuration, old schema
fields, and the dependency on `env.scenario_generator`.

---

### Task 2: Make the project-specific generator standalone

**Files:**
- Rewrite: `src/env/params.py`
- Rewrite: `src/env/scenario.py`
- Modify: `src/env/airspace.py`
- Modify: `src/env/robust_scenario_generator.py`
- Modify: `configs/env/information_aware_routes.yaml`
- Modify: `scripts/generate_information_aware_scenario.py`
- Modify: `scripts/render_information_aware_scenario.py`
- Test: `tests/test_method_neutral_scenario.py`
- Test: `tests/test_robust_scenario_generator.py`
- Test: `tests/test_information_aware_scenario_artifacts.py`

**Interfaces:**
- Consumes: Shapely polygon primitives and wind packet classes.
- Produces: `EnvParams`, lean `Scenario`, single-time airspace updates, and standalone `generate_information_aware_scenario()`.

- [ ] **Step 1: Replace the parameter model**

Implement exactly these parameter groups:

```python
@dataclass
class RouteValidationParams:
    safe_corridor_margin_m: float = 20.0


@dataclass
class MissionParams:
    T: float = 12.0
    M: int = 3
    load_time_h: float = 0.15
    charge_time_h: float = 0.5
    service_time_h: float = 0.02
    n_depot_bays: int = 2


@dataclass
class EnvParams:
    physics: PhysicsParams = field(default_factory=PhysicsParams)
    commodities: CommodityParams = field(default_factory=CommodityParams)
    map: MapParams = field(default_factory=MapParams)
    route_validation: RouteValidationParams = field(
        default_factory=RouteValidationParams
    )
    mission: MissionParams = field(default_factory=MissionParams)
```

Retain only the physics, commodity, and map fields named in the specification.
`EnvParams.from_dict()` must reject unknown top-level and nested keys rather
than filtering them.

- [ ] **Step 2: Replace the scenario model**

Implement the exact `ScenarioNode` and `Scenario` fields from the specification.
`Scenario.from_dict()` validates an exact top-level key set after removing an
optional `content_hash`; it reconstructs nodes and airspace events, while
`content_hash()` hashes only `to_dict()`.

- [ ] **Step 3: Give airspace updates one timestamp**

Change `AirspaceUpdateEvent(event_time, receive_time, ...)` to:

```python
@dataclass
class AirspaceUpdateEvent:
    time_h: float
    region_id: str
    region_type: str
    update_type: str
    new_polygon: Optional[PolygonPoints] = None
    new_severity: Optional[float] = None
    version: int = 1
    safety_buffer_m: Optional[float] = None
    hard_threshold: Optional[float] = None
```

Remove `report_time` from `NoFlyZone` and `HazardRegion`. Update activation,
deactivation, sorting, registration, and application to use `time_h`.

- [ ] **Step 4: Move known-task generation into the retained generator**

Copy and simplify clustered placement from the old generator. Use five child
streams from `SeedSequence([seed, 49157])`:

```python
task_seq, weather_seq, airspace_seq, wind_seq, forecast_seq = root.spawn(5)
```

`_known_task_scenario()` uses only `task_seq`, generates exact demand and
vulnerability, sets inventory to the exact summed demand, and returns empty
environmental lists plus neutral wind. Remove `_known_demand_params()`, every
legacy field overwrite, and the import of the old generator.

- [ ] **Step 5: Preserve route-information generation with v2 provenance**

Adapt weather/no-fly update construction to `time_h`; sort by
`(time_h, region_id, version)`. Generate wind whenever `config.wind.enabled`
is true, independent of polygon mode. Set metadata schema to
`information-aware-routing-v2`.

- [ ] **Step 6: Adapt the CLI, renderer, and YAML**

The generator CLI reads `scenario.params["mission"]` through
`scenario.env_params()`. The YAML replaces `trajectory:` with:

```yaml
route_validation:
  safe_corridor_margin_m: 20.0
```

The renderer reads the lean fields and sorts airspace updates by `time_h`.
It remains a self-contained visualization, not a route solver.

- [ ] **Step 7: Run Task 1 tests and the retained wind/energy tests**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
C:\Users\mayun\anaconda3\python.exe -m pytest -p no:cacheprovider tests/test_method_neutral_scenario.py tests/test_robust_scenario_generator.py tests/test_information_aware_scenario_artifacts.py tests/test_energy.py tests/test_wind_information.py -q
```

Expected: PASS.

---

### Task 3: Add the supplied-route evaluator

**Files:**
- Create: `src/env/route_evaluator.py`
- Create: `tests/test_route_evaluator.py`
- Modify: `src/env/energy.py`
- Modify: `tests/test_energy.py`

**Interfaces:**
- Consumes: `AirspaceMap`, `OnlineWindForecast`, `EnvParams`, and caller-supplied polylines.
- Produces: immutable `RouteEvaluation` and an oracle-only realized energy helper for the simulator.

- [ ] **Step 1: Write failing validation and no-search tests**

```python
def test_evaluator_rejects_malformed_polyline():
    with pytest.raises(ValueError, match="at least two"):
        evaluate_route([[1.0, 1.0]], 0.0, 0.0, 230.0, airspace, forecast, params)


def test_evaluator_preserves_the_supplied_waypoints():
    points = [[1.0, 1.0], [2.0, 3.0], [4.0, 4.0]]
    original = copy.deepcopy(points)
    result = evaluate_route(points, 0.0, 0.0, 230.0, airspace, forecast, params)
    assert points == original
    assert result.distance_km == pytest.approx(
        math.sqrt(5.0) + math.sqrt(5.0)
    )
```

- [ ] **Step 2: Write failing environmental and forecast tests**

Cover hard polygon intersection, positive soft-hazard exposure, no forecast
packet, partial forecast coverage, and complete coverage. Assert uncovered
routes have `forecast_energy_wh is None` and `battery_feasible is None`.

- [ ] **Step 3: Write failing directional-energy tests**

For an eastbound segment, assert westward headwind consumes more than calm and
eastward tailwind consumes less. Assert the reverse segment swaps those
relationships.

- [ ] **Step 4: Implement the pure evaluator**

`evaluate_route()` converts input to a new NumPy array, validates shape and map
bounds, computes segment lengths/times, calls `AirspaceMap.hard_intersects()`
and `path_hazard_risk()`, and accumulates forecast energy without modifying
the input. `battery_feasible` compares energy plus `beta_safe` to `battery_wh`.

Add:

```python
def oracle_realized_route_energy(
    points_xy: Sequence[Sequence[float]],
    departure_time_h: float,
    payload_mass_kg: float,
    wind_spec: Mapping,
    physics: PhysicsParams,
) -> float: ...
```

It uses latent truth only and remains absent from controller snapshots.

- [ ] **Step 5: Run route, energy, and wind tests**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
C:\Users\mayun\anaconda3\python.exe -m pytest -p no:cacheprovider tests/test_route_evaluator.py tests/test_energy.py tests/test_wind_information.py -q
```

Expected: PASS.

---

### Task 4: Add the method-neutral execution simulator

**Files:**
- Rewrite: `src/env/entities.py`
- Rewrite: `src/env/events.py`
- Rewrite: `src/env/deprivation.py`
- Rewrite: `src/env/metrics.py`
- Create: `src/env/simulator.py`
- Create: `tests/test_simulator.py`
- Modify: `tests/test_deprivation.py`

**Interfaces:**
- Consumes: lean `Scenario`, `RouteEvaluation`, oracle realized energy, and explicit caller commands.
- Produces: `RoutingSimulator`, immutable snapshots, deterministic decision epochs, and method-neutral metrics.

- [ ] **Step 1: Write failing state and information-boundary tests**

```python
def test_reset_exposes_all_tasks_but_no_future_information(scenario):
    snapshot = RoutingSimulator().reset(scenario)
    assert len(snapshot.nodes) == 20
    assert all(np.sum(node.remaining_demand) > 0.0 for node in snapshot.nodes)
    assert not hasattr(snapshot, "future_airspace_updates")
    assert not hasattr(snapshot, "wind_truth")
    assert snapshot.wind_forecast is not None
    assert snapshot.wind_forecast.issued_at_h == pytest.approx(0.0)
```

Mutating arrays returned in one snapshot must not alter a later snapshot.

- [ ] **Step 2: Write failing command lifecycle tests**

Use a small deterministic scenario and assert this caller-driven sequence:

```python
sim.prepare(0, [1.0, 0.0, 0.0, 0.0])
load_epoch = sim.advance()
node_position = [scenario.nodes[0].x, scenario.nodes[0].y]
sim.dispatch(0, 0, [sim.uavs[0].position, node_position])
arrival_epoch = sim.advance()
sim.deliver(0, [1.0, 0.0, 0.0, 0.0])
service_epoch = sim.advance()
sim.dispatch(0, -1, [sim.uavs[0].position, scenario.depot])
return_epoch = sim.advance()
```

Assert state transitions, inventory decrement, residual-demand decrement,
payload decrement, positive energy, positive deprivation, and depot return.

- [ ] **Step 3: Write failing fail-closed tests**

Cover overweight load, insufficient inventory, wrong command mode, invalid
destination, mismatched route endpoints, hard block, missing forecast
coverage, insufficient battery, excessive delivery, and non-monotone events.
All command errors are `ValueError` and leave state unchanged.

- [ ] **Step 4: Write the mid-flight update test**

Create a route whose arrival lies after a forecast or airspace update. Assert
`advance()` stops at the update time, interpolates a position strictly between
route endpoints, cancels the waypoint event, sets `AWAITING_ROUTE`, exposes
only the newly received state, and does not create replacement waypoints.

- [ ] **Step 5: Implement lean entities and events**

Use modes `DEPOT`, `PREPARING`, `READY`, `FLYING`, `AT_NODE`,
`SERVICING`, and `AWAITING_ROUTE`. `EventQueue` orders the six event types from
the specification by `(time_h, priority, insertion_sequence)` and supports
lazy cancellation.

- [ ] **Step 6: Implement exact known-demand deprivation and metrics**

Expose:

```python
def deprivation_integral(
    vulnerability: float,
    residual_demand: np.ndarray,
    start_time_h: float,
    duration_h: float,
    lambda_k: np.ndarray,
    alpha_k: np.ndarray,
    kappa_k: np.ndarray,
) -> float: ...
```

Remove cohort, belief, assignment-value, and expected-improvement functions.
Metrics contain only fields listed in the specification.

- [ ] **Step 7: Implement `RoutingSimulator`**

At reset, create exact node/UAV/inventory state, queue every environmental
event and horizon, and synchronously apply all time-zero updates. `prepare`
reserves stock and a bay; `dispatch` records a copied caller path and schedules
arrival; `deliver` schedules service; `advance` integrates deprivation and
physical motion before applying the next event. Environment updates interrupt
every flying UAV and invalidate only its pending waypoint event.

- [ ] **Step 8: Run simulator, deprivation, route, generator, and artifact tests**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
C:\Users\mayun\anaconda3\python.exe -m pytest -p no:cacheprovider tests/test_simulator.py tests/test_deprivation.py tests/test_route_evaluator.py tests/test_method_neutral_scenario.py tests/test_robust_scenario_generator.py tests/test_information_aware_scenario_artifacts.py -q
```

Expected: PASS.

---

### Task 5: Delete every solver and legacy information branch

**Files:**
- Modify: `src/env/__init__.py`
- Delete: `src/agents/`
- Delete: `src/env/alns_scaffold.py`
- Delete: `src/env/belief.py`
- Delete: `src/env/graph.py`
- Delete: `src/env/observation_contract.py`
- Delete: `src/env/online_replanning.py`
- Delete: `src/env/scenario_generator.py`
- Delete: `src/env/trajectory.py`
- Delete: `src/env/uav_env.py`
- Delete: `scripts/run_alns_headroom_test.py`
- Delete: `configs/env/alns_headroom_environment.yaml`
- Delete: `configs/method/`
- Delete: `results/alns_headroom_development/`
- Delete: legacy tests listed below

**Interfaces:**
- Consumes: the passing version-2 generator/evaluator/simulator tests.
- Produces: a repository containing no algorithm or legacy demand-information implementation.

- [ ] **Step 1: Remove obsolete tests**

Delete:

```text
tests/test_alns_demand_onset_corrections.py
tests/test_alns_headroom.py
tests/test_belief.py
tests/test_certified_local_periodic_global.py
tests/test_cohorts.py
tests/test_committed_projection.py
tests/test_env.py
tests/test_online_replanning.py
tests/test_plan_obsolescence.py
tests/test_rollout.py
tests/test_trajectory_replanning.py
```

Rewrite `tests/test_scenario.py` and `tests/test_repository_cleanup.py` around
the v2 schema and exact retained/deleted path lists.

- [ ] **Step 2: Delete source, runner, configs, and results**

Use `apply_patch` for text files. For ignored result artifacts, enumerate each
resolved file under the exact approved result directory, delete files
individually, then remove empty directories without recursive deletion.

- [ ] **Step 3: Rewrite the package description**

`src/env/__init__.py` describes the known-task scenario, online environmental
information, supplied-route evaluator, and method-neutral simulator. It must
not describe a manuscript, SMDP, policy action, solver, or learning system.

- [ ] **Step 4: Run the retained tests**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
C:\Users\mayun\anaconda3\python.exe -m pytest -p no:cacheprovider tests -q
```

Expected: all retained tests pass and collection imports no deleted module.

- [ ] **Step 5: Run the source-boundary scan**

Construct forbidden search terms in PowerShell fragments so the cleanup tests
and command itself do not leave literal matches. Search `src`, `scripts`,
`tests`, `configs`, `README.md`, and `PROJECT_CONTEXT.md` for solver names,
legacy information-event names, deleted module names, path-search terms, and
old schema fields. Expected: no matches.

---

### Task 6: Regenerate artifacts and document the method-neutral repository

**Files:**
- Modify: `README.md`
- Modify: `PROJECT_CONTEXT.md`
- Modify: `environment.yml`
- Regenerate: `scenarios/information_aware/seed_42.json`
- Regenerate: `outputs/information_aware_seed_42.html`
- Modify: `tests/test_information_aware_scenario_artifacts.py`
- Modify: `tests/test_repository_cleanup.py`

**Interfaces:**
- Consumes: final version-2 generator, renderer, evaluator, and simulator.
- Produces: reproducible canonical artifacts and a clean research-project handoff.

- [ ] **Step 1: Rewrite documentation around the undecided method**

Document only:

- known tasks and environmental information uncertainty;
- the single robust generator;
- supplied-route evaluation;
- the method-neutral command executor;
- scenario generation, rendering, and tests; and
- explicit deferral of algorithm selection.

Remove every solver, rejected-method, headroom-result, belief, sensing, and
learned-policy instruction.

- [ ] **Step 2: Keep only runtime/test dependencies**

`environment.yml` remains Python 3.10, NumPy, PyYAML, Shapely, and pytest.

- [ ] **Step 3: Generate two seed-42 copies**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$python='C:\Users\mayun\anaconda3\python.exe'
& $python scripts/generate_information_aware_scenario.py --seed 42 --config configs/env/information_aware_routes.yaml --output scenarios/information_aware/seed_42.json
& $python scripts/generate_information_aware_scenario.py --seed 42 --config configs/env/information_aware_routes.yaml --output scenarios/information_aware/seed_42.v2-check.json
```

Assert byte equality, schema v2, 20 nodes, 3 UAVs, 2 weather regions, 2 no-fly
regions, no legacy fields, and a matching recomputed content hash. Then delete
only the temporary comparison file.

- [ ] **Step 4: Render and validate the canonical HTML**

```powershell
& $python scripts/render_information_aware_scenario.py --input scenarios/information_aware/seed_42.json --output outputs/information_aware_seed_42.html
```

Assert the renderer's printed hash equals the JSON hash, the embedded payload
has that hash, clarified forecast labels remain, and `fetch(` is absent.

- [ ] **Step 5: Run complete final verification**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
C:\Users\mayun\anaconda3\python.exe -m pytest -p no:cacheprovider tests -q
git diff --check
```

Also import every retained source/script module, run the forbidden-reference
scan, verify no `__pycache__`, `.pytest_cache`, solver config/result, or deleted
source path exists, and verify the canonical JSON and HTML remain present.

- [ ] **Step 6: Report the working-tree handoff**

Report exact passing test count, final content hash, retained files, deleted
categories, and the fact that no research method was selected. Do not stage or
commit the overlapping implementation changes from the dirty shared tree.
