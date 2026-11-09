# Authoritative Environment Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the forecast-error-centric scenario foundation with a reproducible authoritative-packet scenario, explicit fleet/network data, and one packet-aware UAV leg-physics implementation, without adding the hierarchical repair controller.

**Architecture:** Keep the retained `env` package boundaries, add typed packet and network models, and make the existing energy module the only source of directional leg physics. `Scenario` serializes one canonical v3 shape and adapts legacy v2 JSON only at the boundary; the simulator and renderer consume the canonical packet timeline.

**Tech Stack:** Python 3.10-compatible dataclasses, NumPy, PyYAML, Shapely, pytest, and the existing self-contained HTML/JavaScript renderer.

**Spec:** `docs/superpowers/specs/2026-08-27-authoritative-environment-foundation-design.md`

## Global Constraints

- Mission defaults remain `T = 12 h`, environment updates every `0.5 h`, and packet look-ahead `H = 1.5 h`, all configurable.
- New scenarios use a global time-varying 2D wind vector and deterministic packet revisions; no forecast-error probability model is generated or serialized.
- Weather and airspace effects are derived from polygon intersection and validity intervals; no redundant corridor-state events are stored.
- New canonical scenario JSON contains no controller routes, repair labels, escalation levels, or controller-dependent descriptors.
- Directed traversal uses `s = w_parallel + sqrt(v_uav^2 - w_perp^2)` and `P = e_c (m0 + payload) v_uav` in km/h, km, h, kg, and Wh.
- Hard physical infeasibility is explicit; battery reserve is a hard constraint.
- Preserve the existing dirty checkout; do not reset, checkout, stage, or commit unrelated user changes.
- Use `PYTHONDONTWRITEBYTECODE=1` and `pytest -p no:cacheprovider` for test runs.

### Task 1: Establish typed packet and network contracts with failing tests

**Files:**
- Create: `src/env/environment.py`
- Create: `src/env/network.py`
- Modify: `src/env/airspace.py`
- Modify: `src/env/wind.py`
- Test: `tests/test_environment_packets.py`
- Test: `tests/test_network_geometry.py`

**Interfaces:**
- Produces `EnvironmentalPacket`, `EnvironmentalTransition`,
  `compare_environmental_packets`, `WeatherRegion`, `AirspaceRestriction`,
  `NetworkNode`, `NetworkEdge`, and `Network`.
- Keeps `WindForecastPoint`, `WindForecastPacket`, and `OnlineWindForecast`
  as compatibility adapters over packet wind timelines.

- [x] **Step 1: Write tests for packet validation and round trips.** Assert
  packet issue/validity fields, mission-end truncation, strict wind point
  order, SOFT/HARD weather normalization, and full `to_dict`/`from_dict`
  equality.
- [x] **Step 2: Run the new tests and observe the expected missing-symbol
  failures.**

  Run: `python -m pytest -p no:cacheprovider tests/test_environment_packets.py tests/test_network_geometry.py -q`

- [x] **Step 3: Implement the packet, region, and network dataclasses.** Make
  geometry immutable-by-copy, validate finite coordinates and intervals, and
  expose `NetworkEdge.direction_xy`, `length_km`, and `bearing_rad`.
- [x] **Step 4: Implement packet comparison.** Compare common wind sample
  times and region IDs/geometry/severity/validity; return separate `revised`
  and `newly_revealed` collections and mapping-style aliases.
- [x] **Step 5: Run both contract files and refactor only while green.**

  Run: `python -m pytest -p no:cacheprovider tests/test_environment_packets.py tests/test_network_geometry.py -q`

### Task 2: Define the canonical versioned scenario and fleet projection

**Files:**
- Modify: `src/env/params.py`
- Modify: `src/env/entities.py`
- Modify: `src/env/scenario.py`
- Modify: `src/env/__init__.py`
- Test: `tests/test_scenario_schema.py`
- Modify: `tests/test_scenario.py`

**Interfaces:**
- `Scenario.to_dict()` emits the v3 top-level shape in the spec.
- `Scenario.from_dict()` accepts v3 and explicitly adapts v2 legacy fields.
- `Scenario.env_params()` continues to serve the simulator; `Scenario.fleet`
  and `Scenario.network` provide typed canonical records.

- [x] **Step 1: Write schema tests first.** Assert exact canonical top-level
  keys, metadata hash keys, mission defaults, fleet fields, bidirectional
  network records, absence of `truth_keyframes` and forecast-error fields in
  generated output, and legacy v2 loadability.
- [x] **Step 2: Run the schema tests to verify they fail against the v2 model.**
- [x] **Step 3: Add mission aliases and fleet parameter validation.** Keep
  `.T`/`.M` compatibility while exposing `horizon_h` and `fleet_size`; add a
  typed UAV parameter record with capacity and reserve validation.
- [x] **Step 4: Implement canonical scenario projection and migration.** Use
  a hash payload that excludes only `metadata.scenario_hash`, calculate a
  deterministic `config_hash`, and keep old attributes as non-serialized
  aliases.
- [x] **Step 5: Run schema and existing scenario tests; fix compatibility
  issues without restoring old serialized fields.**

  Run: `python -m pytest -p no:cacheprovider tests/test_scenario_schema.py tests/test_scenario.py -q`

### Task 3: Generate deterministic authoritative packets, weather, airspace,
and network descriptors

**Files:**
- Modify: `src/env/robust_scenario_generator.py`
- Modify: `configs/env/information_aware_routes.yaml`
- Modify: `src/env/scenario.py`
- Test: `tests/test_authoritative_generator.py`
- Modify: `tests/test_robust_scenario_generator.py`

**Interfaces:**
- `generate_information_aware_scenario(seed, params, route_information)`
  returns a controller-independent canonical `Scenario`.
- `RouteDisruptionConfig` supports packet revision magnitude and serializable
  canonical config values while mapping deprecated v2 config names explicitly.

- [x] **Step 1: Write failing generator tests.** Cover same-seed canonical
  equality/hash stability, different-seed variation, packet issue/validity
  truncation, overlapping packet horizons, nonzero revisions in overlap,
  newly revealed intervals, no error stream metadata, static known demand,
  fleet/network/descriptors, and packet weather/airspace regions.
- [x] **Step 2: Run the generator tests and record the expected v2/schema or
  missing-field failures.**
- [x] **Step 3: Update config dataclasses and YAML defaults.** Replace
  forecast-error names in active config with `update_interval_h`,
  `lookahead_h`, `time_step_h`, and `revision_magnitude_kmh`; retain explicit
  deprecated-input mapping only in the loader.
- [x] **Step 4: Replace `_wind_truth`/`_wind_forecasts` generation with one
  smooth packet process.** Use independent deterministic task, weather,
  airspace, and packet-revision streams; store only packet wind points.
- [x] **Step 5: Generate the star network with a directed outbound and
  reverse edge for every relief node; derive length and bearing from geometry.**
- [x] **Step 6: Generate packet-scoped weather and airspace polygon records,
  including at least one overlap revision and a late horizon truncation, then
  calculate controller-independent descriptors.
- [x] **Step 7: Run the generator tests and refactor with all assertions green.**

  Run: `python -m pytest -p no:cacheprovider tests/test_authoritative_generator.py tests/test_robust_scenario_generator.py -q`

### Task 4: Centralize packet-aware leg physics and route evaluation

**Files:**
- Modify: `src/env/energy.py`
- Modify: `src/env/route_evaluator.py`
- Modify: `src/env/airspace.py`
- Test: `tests/test_leg_physics.py`
- Modify: `tests/test_energy.py`
- Modify: `tests/test_route_evaluator.py`

**Interfaces:**
- `evaluate_leg(edge, departure_time_h, payload_mass_kg, uav_parameters, environmental_packet) -> LegEvaluation` is authoritative.
- `evaluate_route(...)` delegates each segment to `evaluate_leg`, accepts a
  scalar or one payload mass per segment, and reports explicit reasons.

- [x] **Step 1: Write failing tests for `LegEvaluation`.** Pin zero-wind
  speed/time, signed along/cross wind, tail/head asymmetry, crosswind and
  stalled-progress reasons, hard polygon states, packet coverage, and
  payload-dependent power/energy.
- [x] **Step 2: Run the physics tests and verify failure before implementation.**
- [x] **Step 3: Implement `LegEvaluation`, packet time-segment integration,
  geometry-derived condition checks, and one nominal-power function.** Make
  the `PhysicsParams` adapter and canonical fleet record follow the same path.
- [x] **Step 4: Redirect calm/directional/safe-return helpers to the shared
  evaluator; remove duplicate wind-speed formulas from route/evaluation code.
- [x] **Step 5: Add per-segment payload propagation to route evaluation and
  update legacy result aliases.**
- [x] **Step 6: Run physics, energy, and route tests; fix only implementation
  defects revealed by real failures.**

  Run: `python -m pytest -p no:cacheprovider tests/test_leg_physics.py tests/test_energy.py tests/test_route_evaluator.py -q`

### Task 5: Move the executor to authoritative packet execution

**Files:**
- Modify: `src/env/events.py`
- Modify: `src/env/simulator.py`
- Modify: `src/env/entities.py`
- Modify: `src/env/wind.py`
- Test: `tests/test_simulator_packets.py`
- Modify: `tests/test_simulator.py`

**Interfaces:**
- `RoutingSimulator.reset()` queues packet issue events and exposes the latest
  `environment_packet` in snapshots.
- `prepare`, `dispatch`, and `deliver` remain caller-command interfaces.
- Mid-flight packet replacement settles the current route under the prior
  packet and returns the UAV in `AWAITING_ROUTE` without constructing a route.

- [x] **Step 1: Write failing simulator tests.** Assert no future packet in a
  snapshot, current packet visibility, interruption on packet revision,
  packet-aware arrival/energy, heterogeneous fleet parameters, reserve
  reporting, and delivery-driven payload changes.
- [x] **Step 2: Run the simulator tests to verify the current truth-based
  implementation fails the new contracts.**
- [x] **Step 3: Add the environment-packet event and replace separate future
  wind/airspace queueing with issue-time packet queueing.** Keep old event
  adapters only for migrated legacy scenarios.
- [x] **Step 4: Update dispatch and settlement to call `evaluate_route` and
  the shared packet-aware integrator; never read truth fields for generated
  scenarios.
- [x] **Step 5: Preserve atomic load/deliver/reserve behavior and expose fleet
  capacity/reserve data without adding controller decisions.
- [x] **Step 6: Run simulator and full retained tests; refactor only after green.**

  Run: `python -m pytest -p no:cacheprovider tests/test_simulator_packets.py tests/test_simulator.py -q`

### Task 6: Update renderer, regenerate artifacts, and audit the acceptance
criteria

**Files:**
- Modify: `scripts/generate_information_aware_scenario.py`
- Modify: `scripts/render_information_aware_scenario.py`
- Modify: `README.md`
- Modify: `PROJECT_CONTEXT.md`
- Modify: `tests/test_information_aware_scenario_artifacts.py`
- Modify: `tests/test_method_neutral_scenario.py`
- Regenerate: `scenarios/information_aware/seed_42.json`
- Regenerate: `outputs/information_aware_seed_42.html`

- [x] **Step 1: Write/update artifact tests first.** Assert the rendered HTML
  embeds the canonical scenario hash, packet horizon/revision labels,
  geometry-derived status text, no `fetch(`, and no new latent-truth or
  forecast-error UI labels.
- [x] **Step 2: Run artifact tests against the old renderer to verify the
  expected failures.**
- [x] **Step 3: Update the renderer for canonical nodes, network edges,
  packet-scoped regions, current authoritative wind, and overlap/revision
  details while keeping it self-contained and keyboard accessible.
- [x] **Step 4: Generate seed 42 JSON and HTML with the canonical scripts.**

  Run:

  ```powershell
  $env:PYTHONDONTWRITEBYTECODE='1'
  python scripts/generate_information_aware_scenario.py --seed 42 --config configs/env/information_aware_routes.yaml --output scenarios/information_aware/seed_42.json
  python scripts/render_information_aware_scenario.py --input scenarios/information_aware/seed_42.json --output outputs/information_aware_seed_42.html
  ```

- [x] **Step 5: Run the complete retained suite, import scan, forbidden-field
  scan, JSON/HTML hash checks, and `git diff --check`.**

  Run:

  ```powershell
  $env:PYTHONDONTWRITEBYTECODE='1'
  python -m pytest -p no:cacheprovider tests -q
  python -c "from env.scenario import Scenario; s=Scenario.from_json('scenarios/information_aware/seed_42.json'); print(s.content_hash()); print(len(s.environment_packets))"
  rg -n "truth_keyframes|forecast_error|wind_forecast_error|expected_escalation|GLOBAL_REOPT_REQUIRED|ALNS|MAPPO" scenarios scripts src tests configs -g '!*.pyc'
  git diff --check -- src tests scripts configs README.md PROJECT_CONTEXT.md outputs scenarios docs/superpowers/specs/2026-08-27-authoritative-environment-foundation-design.md docs/superpowers/plans/2026-08-27-authoritative-environment-foundation.md
  ```

- [x] **Step 6: Re-read this plan and the spec, report any unmet acceptance
  item honestly, and only then mark the goal complete.**
