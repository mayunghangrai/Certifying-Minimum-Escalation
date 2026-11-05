# Information-Aware Weather and Wind Scenario Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one replayable 20-node scenario with known relief tasks, weather/airspace route disruptions, rolling online wind forecasts, and direction-aware battery calculations.

**Architecture:** Keep the existing scenario and polygon-weather pipeline intact. Add a focused wind-information module used by the generator, scenario container, event queue, and energy helpers; serialize all exogenous data in the canonical scenario JSON while exposing only received packets through operational state.

**Tech Stack:** Python 3.12, NumPy, Shapely, PyYAML, pytest, self-contained HTML/SVG/JavaScript.

**Spec:** `docs/superpowers/specs/2026-08-26-information-aware-weather-wind-scenario-design.md`

## Global Constraints

- All relief-task information is exact at time zero; do not add sensing or unknown demand.
- Preserve existing weather polygon geometry, timing, and semantics.
- Use km/h for wind vectors, with positive `u` east and positive `v` north.
- Forecast issue interval is 0.5 h and visible horizon is 1.5 h in the canonical profile.
- Never extrapolate battery certification beyond the latest received forecast horizon.
- Preserve legacy calm-air behavior exactly when wind is zero.
- Do not modify, stage, commit, or remove unrelated user changes in the dirty checkout.

---

### Task 1: Wind information value objects and operational state

**Files:**
- Create: `src/env/wind.py`
- Test: `tests/test_wind_information.py`

**Interfaces:**
- Produces: `WindForecastPoint`, `WindForecastPacket`, `OnlineWindForecast`, `interpolate_wind_vector`, and `truth_wind_vector`.
- `OnlineWindForecast.receive(packet, now_h)` rejects early receipt; `vector_at(valid_time_h)` returns `None` outside the latest packet.

- [ ] Write literal-value tests for interpolation, packet round trip, forecast replacement/revision, early-receipt rejection, and horizon refusal.
- [ ] Run `conda run -n base python -m pytest tests/test_wind_information.py -q` and confirm failure because `env.wind` does not exist.
- [ ] Implement immutable packet/point dataclasses and the minimal operational state.
- [ ] Re-run the test file and confirm all tests pass.

### Task 2: Directional energy and forecast certification

**Files:**
- Modify: `src/env/energy.py`
- Modify: `tests/test_energy.py`

**Interfaces:**
- Produces: `directional_flight_energy(start_xy, end_xy, payload_mass, wind_vector_kmh, p)`.
- Produces: `directional_safe_return_energy(current_xy, node_xy, depot_xy, payload_mass, payload_mass_after, outbound_wind_kmh, return_wind_kmh, p)`.
- Produces: `forecast_route_energy(points_xy, segment_start_times_h, payload_masses, forecast, p)` returning `None` when coverage is incomplete.

- [ ] Add hand-computed zero-wind, 12 km/h headwind/tailwind, crosswind, reverse-edge, safe-return, and uncovered-horizon tests.
- [ ] Run the named energy tests and confirm missing-function failures.
- [ ] Implement the relative-air-velocity multiplier without changing `flight_energy`.
- [ ] Re-run `tests/test_energy.py` and `tests/test_wind_information.py`.

### Task 3: Seeded wind truth and rolling forecast generation

**Files:**
- Modify: `src/env/robust_scenario_generator.py`
- Modify: `configs/env/information_aware_routes.yaml`
- Modify: `tests/test_robust_scenario_generator.py`

**Interfaces:**
- Produces: nested `WindForecastConfig` parsed by `RouteDisruptionConfig.from_dict`.
- Produces: `wind_spec` with `model`, `units`, `truth_keyframes`, and `forecast_packets`.

- [ ] Add tests for configuration validation, determinism, different-seed variation, forecast revision, horizon clipping, speed bounds, and weather/airspace RNG independence.
- [ ] Run the focused generator tests and confirm expected failures against the neutral-wind generator.
- [ ] Add two new seed-sequence children and generate smooth truth plus lead-dependent noisy packets only in weather/mixed modes.
- [ ] Re-run generator and serialization tests.

### Task 4: Online event revelation without observation leakage

**Files:**
- Modify: `src/env/events.py`
- Modify: `src/env/scenario.py`
- Modify: `src/env/uav_env.py`
- Modify: `tests/test_robust_scenario_generator.py`

**Interfaces:**
- Produces: `EventType.WIND_FORECAST_UPDATE` in `INFO_DECISION_TYPES`.
- Produces: `Scenario.wind_forecast_timeline()`.
- Produces: `env.operational_wind`, updated only when a queued packet is received.

- [ ] Add an environment test proving future packets stay queued and operational coverage stops at the latest received horizon.
- [ ] Run the test and confirm the event type/state is missing.
- [ ] Queue packets at issue time, apply them to `OnlineWindForecast`, and expose only the operational state.
- [ ] Re-run focused environment and event-order tests.

### Task 5: Canonical seed and interactive inspection artifact

**Files:**
- Modify: `scripts/generate_information_aware_scenario.py`
- Create: `scripts/render_information_aware_scenario.py`
- Create: `scenarios/information_aware/seed_42.json`
- Create: `outputs/information_aware_seed_42.html`
- Test: `tests/test_information_aware_scenario_artifacts.py`

**Interfaces:**
- The existing generation CLI writes one content-hashed JSON.
- The render CLI consumes that JSON and writes one self-contained HTML file.

- [ ] Add a CLI/artifact test asserting 20 exact-known nodes, 3 UAVs, 12 h, mixed disruptions, forecast packets, and embedded visual data.
- [ ] Run it and confirm failure because the render CLI/artifacts do not exist.
- [ ] Implement the renderer with a time slider, polygon states, wind truth/current forecast vectors, visible forecast horizon, and head/tail/crosswind energy labels.
- [ ] Generate seed 42 and its HTML, reload JSON, and verify its content hash.
- [ ] Inspect the HTML at 1,024 px, 736 px, and 360 px in light/dark themes and fix runtime or layout defects.

### Task 6: Regression and requirement audit

**Files:**
- Verify all files listed above; do not alter unrelated files.

- [ ] Run the focused scenario, wind, energy, trajectory, scenario serialization, and environment tests.
- [ ] Run the full test suite when feasible and record any pre-existing failures separately.
- [ ] Inspect `git diff --` for every touched tracked file and `git status --short` for scope.
- [ ] Re-read the spec and map every requirement to either a test or a generated artifact before reporting completion.
