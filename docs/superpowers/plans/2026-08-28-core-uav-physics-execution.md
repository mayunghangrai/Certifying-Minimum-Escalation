# Core UAV Physics and Fixed-Plan Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strengthen the existing packet-aware UAV runtime with one authoritative, piecewise physical evaluator, hard feasibility invariants, structured run logs, and deterministic fixed-plan execution.

**Architecture:** Keep `src/env/energy.py` as the sole source of leg direction, wind, speed, power, energy, partial-motion, and reserve calculations. Extend the existing pure route evaluator and event-driven simulator in place, and add only a thin `fixed_plan.py` adapter that drives the simulator without selecting routes.

**Tech Stack:** Python 3.10-compatible dataclasses, NumPy, Shapely, PyYAML, and pytest.

**Spec:** `docs/superpowers/specs/2026-08-28-core-uav-physics-execution-design.md`

## Global Constraints

- Preserve canonical units: kilometres, hours, km/h, kilograms, and Wh.
- Preserve fixed-Wh reserve semantics and use `commodities.w_k` as the sole payload-mass conversion.
- `evaluate_leg(edge, departure_time_h, payload_mass_kg, uav_parameters, environmental_packet)` is authoritative.
- Do not silently clamp invalid square-root arguments or negative battery state.
- Hard constraints are feasibility results/reasons, never objective penalties.
- Preserve the existing command-driven simulator; do not rewrite it or add route optimization.
- Packet updates settle active flight under the old packet before installing the new packet.
- Do not expose future packets or latent truth through runtime state.
- Preserve unrelated dirty checkout changes; stage only files explicitly changed for this plan if checkpoints are committed.
- Run tests with `PYTHONDONTWRITEBYTECODE=1` and `pytest -p no:cacheprovider`.

## Shared test fixtures

The new test modules use these concrete helpers so every analytical assertion
has a reproducible edge, UAV, and packet rather than an implicit fixture:

```python
def make_uav(speed=60.0):
    return UAVParameters(
        id="UAV-00", nominal_airspeed_kmh=speed, empty_mass_kg=4.0,
        max_payload_kg=5.0, battery_capacity_wh=230.0,
        reserve_requirement_wh=23.0,
        energy_coefficient_wh_per_km_kg=3.125, service_energy_wh=2.5,
    )


def make_packet(vectors, times):
    return EnvironmentalPacket(
        packet_id="TEST-ENV",
        issued_at_h=float(times[0]),
        valid_from_h=float(times[0]),
        valid_until_h=float(times[-1]),
        wind=tuple(WindForecastPoint(t, vector[0], vector[1])
                   for t, vector in zip(times, vectors)),
    )
```

The fixed-plan tests define a two-node scenario with depot `(0, 0)`, node A
`(1, 0)`, node B `(2, 0)`, a single commodity with unit mass `1.0 kg`, and
explicit plan deliveries `[2.0]` and `[3.0]`. The packet covers the complete
mission interval and contains no polygons unless a test specifically adds
one.

---

### Task 1: Add analytical contracts for units, reason codes, and leg results

**Files:**
- Modify: `src/env/params.py`
- Modify: `src/env/energy.py`
- Modify: `src/env/network.py`
- Test: `tests/test_core_uav_physics.py`

**Interfaces:**
- Produces `InfeasibilityReason`, shared tolerance constants, explicit
  `seconds_to_wh(power_w, duration_s)`, public direction helpers, and the
  extended immutable `LegEvaluation` returned by `evaluate_leg`.
- Preserves `PhysicsParams`, `NetworkEdge`, old `LegEvaluation` aliases, and
  old reason comparisons through compatibility mappings.

- [ ] **Step 1: Write failing analytical tests.**

```python
def test_leg_result_exposes_complete_physical_record():
    result = evaluate_leg(edge, 0.25, 1.0, uav, calm_packet)
    assert result.departure_time_h == pytest.approx(0.25)
    assert result.arrival_time_h == pytest.approx(0.25 + 1.0 / 60.0)
    assert result.airspeed_kmh == pytest.approx(60.0)
    assert result.payload_mass_kg == pytest.approx(1.0)
    assert result.power_w == pytest.approx(3.125 * 5.0 * 60.0)
    assert result.packet_id == calm_packet.packet_id
    assert result.diagnostics["direction_xy"] == pytest.approx((1.0, 0.0))


def test_seconds_to_wh_is_explicit():
    assert seconds_to_wh(10.0, 360.0) == pytest.approx(1.0)


def test_directed_edge_direction_reverses():
    forward = NetworkEdge("ab", "A", "B", ((0.0, 0.0), (3.0, 4.0)))
    reverse = NetworkEdge("ba", "B", "A", ((3.0, 4.0), (0.0, 0.0)))
    assert edge_direction_xy(forward) == pytest.approx((-edge_direction_xy(reverse)[0], -edge_direction_xy(reverse)[1]))
```

- [ ] **Step 2: Run the focused tests and confirm the new API fields fail.**

Run: `python -m pytest -p no:cacheprovider tests/test_core_uav_physics.py -q`

Expected: FAIL because the extended result fields and helpers do not yet
exist; existing tests remain the comparison baseline.

- [ ] **Step 3: Add named tolerances, canonical reason values, and explicit conversion helpers.**

```python
class InfeasibilityReason(str, Enum):
    CROSSWIND_EXCEEDS_AIRSPEED = "CROSSWIND_EXCEEDS_AIRSPEED"
    NONPOSITIVE_GROUND_PROGRESS = "NONPOSITIVE_GROUND_PROGRESS"
    HARD_WEATHER_BLOCK = "HARD_WEATHER_BLOCK"
    AIRSPACE_BLOCK = "AIRSPACE_BLOCK"
    INSUFFICIENT_BATTERY = "INSUFFICIENT_BATTERY"
    SAFE_RETURN_RESERVE_VIOLATION = "SAFE_RETURN_RESERVE_VIOLATION"
    PAYLOAD_CAPACITY_EXCEEDED = "PAYLOAD_CAPACITY_EXCEEDED"
    INSUFFICIENT_DEPOT_INVENTORY = "INSUFFICIENT_DEPOT_INVENTORY"
    INVALID_COMMODITY_LOAD = "INVALID_COMMODITY_LOAD"
    MISSION_HORIZON_EXCEEDED = "MISSION_HORIZON_EXCEEDED"
    INVALID_EDGE = "INVALID_EDGE"
    INVALID_ENVIRONMENTAL_COVERAGE = "INVALID_ENVIRONMENTAL_COVERAGE"


def seconds_to_wh(power_w: float, duration_s: float) -> float:
    return float(power_w) * float(duration_s) / 3600.0
```

Keep legacy spellings only in an explicit adapter mapping so existing callers
can compare old values while new serialized diagnostics use canonical values.

- [ ] **Step 4: Extend `LegEvaluation` and route all construction through one failure/result factory.**

Add departure/arrival, airspeed, wind vector, payload, power, packet ID,
diagnostics, and canonical reason fields while retaining existing aliases.
Expose `edge_direction_xy(edge)` and `perpendicular_direction_xy(edge)` from
the same geometry validation used by `evaluate_leg`.

- [ ] **Step 5: Run the focused tests and the retained physics tests.**

Run: `python -m pytest -p no:cacheprovider tests/test_core_uav_physics.py tests/test_authoritative_leg_physics.py tests/test_energy.py tests/test_network_geometry.py -q`

Expected: PASS with the new analytical checks and the existing baseline.

- [ ] **Step 6: Checkpoint only the task files.**

Run: `git diff --check -- src/env/params.py src/env/energy.py src/env/network.py tests/test_core_uav_physics.py`

If committing, stage exactly those paths and use commit message
`feat: expose canonical UAV physics contracts`; never stage existing dirty
files.

### Task 2: Replace implicit speed handling with exact piecewise traversal

**Files:**
- Modify: `src/env/energy.py`
- Test: `tests/test_core_uav_physics.py`

**Interfaces:**
- Consumes the Task 1 `LegEvaluation` and packet/network contracts.
- Produces piecewise `evaluate_leg` diagnostics and an accurate
  `route_state_at` partial-motion result.

- [ ] **Step 1: Write failing tests for all wind regimes and breakpoint state.**

```python
@pytest.mark.parametrize("wind, expected_speed", [
    ((0.0, 0.0), 60.0),
    ((12.0, 0.0), 72.0),
    ((-12.0, 0.0), 48.0),
    ((0.0, 12.0), math.sqrt(60.0**2 - 12.0**2)),
])
def test_analytical_ground_speed(wind, expected_speed):
    result = evaluate_leg(east_edge, 0.0, 0.0, uav, constant_packet(wind))
    assert result.ground_speed_kmh == pytest.approx(expected_speed)


def test_crosswind_at_airspeed_is_not_clamped():
    result = evaluate_leg(east_edge, 0.0, 0.0, uav10, constant_packet((0.0, 10.0)))
    assert result.feasible is False
    assert result.reason == InfeasibilityReason.CROSSWIND_EXCEEDS_AIRSPEED


def test_stalled_headwind_has_canonical_reason():
    result = evaluate_leg(east_edge, 0.0, 0.0, uav10, constant_packet((-10.0, 0.0)))
    assert result.feasible is False
    assert result.reason == InfeasibilityReason.NONPOSITIVE_GROUND_PROGRESS


def test_partial_state_uses_segment_distance_not_elapsed_time_fraction():
    edge = NetworkEdge("AB", "A", "B", ((0.0, 0.0), (100.0, 0.0)))
    uav = make_uav()
    packet = make_packet(((0.0, 0.0), (0.0, 0.0), (20.0, 0.0)),
                         (0.0, 0.5, 1.0))
    position, distance, energy, now = route_state_at(
        ((0.0, 0.0), (100.0, 0.0)), 0.0, 0.75, 0.0, uav, packet,
    )
    assert distance == pytest.approx(46.25, abs=DISTANCE_TOL_KM)
    assert position[0] == pytest.approx(distance)
    assert energy == pytest.approx(nominal_power(0.0, uav) * 0.75)
    assert now == pytest.approx(0.75)
```

- [ ] **Step 2: Run the tests and verify the exact-crosswind and nonlinear partial-state failures.**

Run: `python -m pytest -p no:cacheprovider tests/test_core_uav_physics.py -q`

Expected: FAIL because the current evaluator uses a tolerance clamp and
`route_state_at` interpolates position by total-leg time fraction.

- [ ] **Step 3: Implement a shared internal piecewise integrator.**

Split at packet validity, wind-point, and region-validity boundaries. For each
interval, use the midpoint packet wind, compute
`w_parallel + sqrt(v_uav**2 - w_perp**2)` only after checking
`abs(w_perp) < v_uav`, and reject `speed <= 0` without clamping. Accumulate
distance, time, and `power_w * duration_h`; store immutable-equivalent segment
records in `diagnostics["segments"]`.

- [ ] **Step 4: Make `route_state_at` consume the same segment records.**

For a requested time inside a segment, advance only the segment's proportional
distance and energy. For a completed segment, use its full distance. Never
recompute a prior segment with a later packet or interpolate position from the
whole-leg duration.

- [ ] **Step 5: Run the focused suite and retained route tests.**

Run: `python -m pytest -p no:cacheprovider tests/test_core_uav_physics.py tests/test_authoritative_leg_physics.py tests/test_energy.py tests/test_route_evaluator.py -q`

Expected: PASS, including zero/tail/head/crosswind, reverse asymmetry,
piecewise traversal, explicit coverage failure, and payload energy scaling.

### Task 3: Centralize route-level feasibility, horizon, and reserve margins

**Files:**
- Modify: `src/env/energy.py`
- Modify: `src/env/route_evaluator.py`
- Test: `tests/test_core_uav_physics.py`
- Test: `tests/test_route_evaluator.py`

**Interfaces:**
- Produces `safe_return_margin_wh(...)`, `evaluate_safe_return(...)`, and an
  extended `RouteEvaluation` with `feasible`, `failure_reason`, per-leg
  evaluations, and `reserve_margin_wh`.
- `evaluate_route` remains pure and keeps old fields/reason text as adapters.

The new reserve signatures are:

```python
safe_return_margin_wh(
    remaining_battery_wh: float,
    predicted_return_energy_wh: float,
    reserve_requirement_wh: float,
) -> float

evaluate_safe_return(
    current_xy,
    safe_endpoint_xy,
    departure_time_h: float,
    payload_mass_kg: float,
    remaining_battery_wh: float,
    uav_parameters,
    environmental_packet,
    *,
    service_energy_wh: float = 0.0,
) -> SafeReturnEvaluation
```

- [ ] **Step 1: Write failing route feasibility tests.**

```python
def test_route_rejects_horizon_overrun_with_explicit_reason(params):
    params.mission.T = 0.05
    result = evaluate_route(route, 0.0, 0.0, 230.0, None, forecast, params,
                            environmental_packet=packet)
    assert result.feasible is False
    assert InfeasibilityReason.MISSION_HORIZON_EXCEEDED in result.reason_codes


def test_safe_return_margin_distinguishes_reserve_violation():
    margin = safe_return_margin_wh(40.0, 20.0, 23.0)
    assert margin == pytest.approx(-3.0)
    result = evaluate_safe_return(
        current, depot, 0.0, 0.0, 40.0, uav, packet,
        service_energy_wh=0.0,
    )
    assert result.feasible is False
    assert result.reason == InfeasibilityReason.SAFE_RETURN_RESERVE_VIOLATION
```

- [ ] **Step 2: Run the route tests and observe missing fields/helpers.**

Run: `python -m pytest -p no:cacheprovider tests/test_core_uav_physics.py tests/test_route_evaluator.py -q`

Expected: FAIL because route-level horizon and reserve-result fields are not
yet exposed.

- [ ] **Step 3: Implement reserve helpers using the existing fixed-Wh semantics.**

Evaluate the current-position-to-safe-endpoint edge with `evaluate_leg`, add
service energy when requested, compute
`remaining_battery - predicted_energy - reserve`, and return an explicit
reserve failure when the margin is negative. Preserve `safe_return_energy`
and `is_safe_return_feasible` as analytical compatibility helpers.

- [ ] **Step 4: Update `evaluate_route` to aggregate only shared leg results.**

Create one directed `NetworkEdge` per supplied segment, preserve per-leg
payload masses, collect standardized codes, retain legacy reason aliases, and
mark `feasible=False` for any hard leg failure, missing coverage, battery
shortfall, or arrival beyond `params.mission.T`.

- [ ] **Step 5: Run route, energy, and retained simulator tests.**

Run: `python -m pytest -p no:cacheprovider tests/test_core_uav_physics.py tests/test_route_evaluator.py tests/test_energy.py tests/test_simulator.py -q`

Expected: PASS with explicit hard feasibility while current command behavior
remains compatible.

### Task 4: Enforce runtime battery, payload, inventory, demand, and log invariants

**Files:**
- Modify: `src/env/entities.py`
- Modify: `src/env/metrics.py`
- Modify: `src/env/simulator.py`
- Test: `tests/test_fixed_plan_execution.py`
- Test: `tests/test_simulator.py`

**Interfaces:**
- Produces runtime `UAVState` capacity/status aliases, structured
  `flight_log`/`event_log`, per-UAV energy totals, and
  `RoutingSimulator.conservation_audit()`.
- `RoutingSimulator.consume_battery(uav_id: int, energy_wh: float) -> None`
  performs an atomic, capacity-aware battery decrement for tests and runtime
  event application.
- Preserves existing `prepare`, `dispatch`, `deliver`, `advance`, snapshots,
  and metrics summary fields.

- [ ] **Step 1: Write failing invariant and structured-log tests.**

```python
def test_negative_battery_is_rejected_instead_of_clamped(sim):
    sim.uavs[0].battery = 0.01
    with pytest.raises(ValueError, match="INSUFFICIENT_BATTERY"):
        sim.consume_battery(0, 0.02)
    assert sim.uavs[0].battery == pytest.approx(0.01)


def test_delivery_and_flight_logs_have_required_fields(fixed_result):
    flight = fixed_result.event_log["flights"][0]
    assert {"uav", "origin", "destination", "departure_time_h",
            "arrival_time_h", "payload_before", "payload_after",
            "battery_before", "battery_after", "packet_id", "energy_wh",
            "weather_state", "airspace_state", "feasible", "reason"} <= set(flight)
```

- [ ] **Step 2: Run the tests to verify the missing guard/log failures.**

Run: `python -m pytest -p no:cacheprovider tests/test_fixed_plan_execution.py tests/test_simulator.py -q`

Expected: FAIL because battery consumption currently clamps and no complete
flight log or conservation audit exists.

- [ ] **Step 3: Add capacity-aware UAV state and atomic consumption helpers.**

Validate initial battery against capacity at reset and update battery only when
the requested amount is finite, nonnegative, and no greater than the current
state. Raise `ValueError` containing `INSUFFICIENT_BATTERY` before mutation.
Validate payload mass at load and delivery boundaries and retain commodity
vectors unchanged.

- [ ] **Step 4: Make simulator dispatch, service, and loading failures explicit.**

Use canonical reason codes in command errors, reject load completion beyond the
mission horizon, reject inventory/capacity violations atomically, and enforce
safe-return margin after accounting for service and post-delivery payload.
Do not clip negative residual demand, inventory, or payload except to remove a
nonnegative floating-point tolerance after a validated subtraction.

- [ ] **Step 5: Add structured flight/delivery records and conservation audit.**

Record one dictionary per flight segment and delivery with numeric snapshots,
packet ID, actual event time, and reason. Keep these records in run metrics and
never write them into `Scenario.to_dict()`. Return a dictionary containing
inventory, demand, battery, payload, and distance residuals plus boolean
within-tolerance flags.

- [ ] **Step 6: Run the retained simulator/deprivation suite.**

Run: `python -m pytest -p no:cacheprovider tests/test_simulator.py tests/test_deprivation.py tests/test_route_evaluator.py -q`

Expected: PASS with no negative runtime state and preserved snapshot behavior.

### Task 5: Make packet-update motion physically continuous and resumable

**Files:**
- Modify: `src/env/entities.py`
- Modify: `src/env/simulator.py`
- Test: `tests/test_fixed_plan_execution.py`
- Modify: `tests/test_packet_route_execution.py`

**Interfaces:**
- Produces `RoutingSimulator.resume_current_leg(uav_id) -> None` for the
  already committed remaining geometry; it does not construct a replacement
  route.
- Keeps active-flight updates in `AWAITING_ROUTE` for ordinary callers and
  preserves the existing snapshot contract.

- [ ] **Step 1: Write failing packet-transition tests.**

```python
def test_packet_update_settles_old_packet_and_resume_uses_new_packet():
    sim = make_midflight_simulator()
    old_position = sim.uavs[0].position.copy()
    update = sim.advance()
    assert update.uavs[0].mode is Mode.AWAITING_ROUTE
    assert old_position[0] < update.uavs[0].position[0] < target_x
    battery_at_update = update.uavs[0].battery
    sim.resume_current_leg(0)
    assert sim.uavs[0].mode is Mode.FLYING
    assert sim.uavs[0].position[0] == pytest.approx(update.uavs[0].position[0])
    sim.advance()
    assert sim.metrics.energy_consumed_wh > 0.0
    assert sim.uavs[0].battery < battery_at_update
```

- [ ] **Step 2: Run the transition tests and capture the inaccurate partial position/resume failures.**

Run: `python -m pytest -p no:cacheprovider tests/test_fixed_plan_execution.py tests/test_packet_route_execution.py tests/test_simulator.py -q`

Expected: FAIL because the current partial position uses whole-leg time
fraction and discards the committed remainder.

- [ ] **Step 3: Store committed remainder and settle under the prior packet.**

When an environment event arrives, call the shared `route_state_at` before
replacing `environment_packet`, log the partial segment, cancel only the old
arrival event, and store the remaining polyline/destination internally. Keep
`active_route=None` and `AWAITING_ROUTE` in snapshots.

- [ ] **Step 4: Implement explicit continuation without route construction.**

`resume_current_leg` dispatches exactly the stored remainder using the new
authoritative packet. It rejects missing remainder, wrong mode, coverage,
weather, airspace, battery, reserve, or horizon with canonical errors.

- [ ] **Step 5: Run focused transition and full retained tests.**

Run: `python -m pytest -p no:cacheprovider tests/test_packet_route_execution.py tests/test_simulator.py tests/test_core_uav_physics.py -q`

Expected: PASS, including no rollback/teleportation and no early future-packet
visibility.

### Task 6: Add deterministic fixed-plan execution

**Files:**
- Create: `src/env/fixed_plan.py`
- Modify: `src/env/simulator.py`
- Modify: `src/env/__init__.py`
- Test: `tests/test_fixed_plan_execution.py`

**Interfaces:**
- Produces:

```python
execute_fixed_plan(scenario, plan, objective_params=None) -> FixedPlanResult
RoutingSimulator.execute_fixed_plan(plan) -> FixedPlanResult
```

- Consumes plan entries shaped as:

```python
{
    "UAV-00": {
        "route": ["DEPOT", "NODE-000", "NODE-001", "DEPOT"],
        "load": [5.0, 0.0, 0.0, 0.0],
        "deliveries": {
            "NODE-000": [2.0, 0.0, 0.0, 0.0],
            "NODE-001": [3.0, 0.0, 0.0, 0.0],
        },
    }
}
```

- [ ] **Step 1: Write failing fixed-plan integration tests.**

```python
def test_fixed_plan_executes_payload_drop_and_return():
    result = execute_fixed_plan(scenario, plan)
    assert result.completed is True
    assert result.simulator.uavs[0].mode is Mode.DEPOT
    assert result.metrics.completed_services == 2
    assert result.metrics.delivery_log[0][2] < result.metrics.delivery_log[1][2]
    assert result.conservation["all_within_tolerance"] is True
    assert [event["payload_before_mass_kg"] for event in result.flight_events] == pytest.approx([5.0, 3.0, 0.0])
```

- [ ] **Step 2: Run the integration test and confirm the fixed-plan API is absent.**

Run: `python -m pytest -p no:cacheprovider tests/test_fixed_plan_execution.py -q`

Expected: FAIL with an import or missing-method failure.

- [ ] **Step 3: Implement plan normalization and edge lookup.**

Accept fleet IDs or integer keys, validate route starts/ends at `DEPOT`, map
node IDs to typed scenario nodes, select exact directed network edges when
present, and use a direct geometry edge only for a route pair without a stored
edge. Reject malformed plans before any simulator mutation.

- [ ] **Step 4: Implement the deterministic event-driving loop.**

Prepare all requested UAV loads, advance queued events chronologically, dispatch
the next exact route edge, issue only declared delivery vectors at demand-node
arrivals, resume stored committed remainders after packet updates, and stop at
the horizon or first hard plan failure. Never invent a route or delivery.

- [ ] **Step 5: Return `FixedPlanResult` with trace and audit.**

Expose the simulator, metrics, `event_log`, per-flight event list, completion
flag, termination reason, and conservation audit. Ensure actual arrival times
are used for delivery records and that final depot payload/inventory is
conserved.

- [ ] **Step 6: Run fixed-plan tests plus all retained tests.**

Run: `python -m pytest -p no:cacheprovider tests/test_fixed_plan_execution.py tests/test_simulator.py tests/test_packet_route_execution.py tests/test_route_evaluator.py -q`

Expected: PASS with deterministic multi-leg payload and delivery accounting.

### Task 7: Add generated-seed and controlled-disturbance verification artifacts

**Files:**
- Modify: `tests/test_fixed_plan_execution.py`
- Create: `scripts/verify_core_uav_physics.py`
- Modify: `README.md`

**Interfaces:**
- Produces a repeatable verification command that loads generated seed 42,
  runs a manually supplied valid fixed mission, and prints a JSON report with
  legs, deliveries, times, energies, battery/payload trajectories, packets,
  weather/airspace states, reserve, and completion time.

The test module defines `SEED_42` as
`Path(__file__).parents[1] / "scenarios" / "information_aware" / "seed_42.json"`
and builds its seed plan from the first generated relief node:

```python
def seed_42_plan(scenario):
    node = scenario.nodes[0]
    quantity = [0.0] * 4
    quantity[0] = min(1.0, node.demand[0])
    return {
        "UAV-00": {
            "route": ["DEPOT", f"NODE-{node.idx:03d}", "DEPOT"],
            "load": quantity,
            "deliveries": {f"NODE-{node.idx:03d}": quantity},
        }
    }
```

The disturbance helper uses the same two-node, one-commodity fixture from the
shared test-fixture section, replaces its packet wind points with the supplied
constant vector, and leaves all polygons empty. Its `plan` is the explicit
depot-to-A-to-depot route with one declared delivery.

- [ ] **Step 1: Write failing seed/report tests.**

```python
def test_generated_seed_42_fixed_plan_report_has_real_runtime_quantities():
    scenario = Scenario.from_json(SEED_42)
    result = execute_fixed_plan(scenario, seed_42_plan(scenario))
    assert result.completed is True
    assert len(result.flight_events) >= 2
    assert result.environment_packets_encountered
    assert result.conservation["all_within_tolerance"] is True


def test_packet_revision_changes_downstream_reserve_margin_without_escalation():
    calm = execute_fixed_plan(make_disturbance_scenario((0.0, 0.0)), plan)
    headwind = execute_fixed_plan(make_disturbance_scenario((-12.0, 0.0)), plan)
    assert headwind.total_travel_time_h > calm.total_travel_time_h
    assert headwind.total_energy_wh > calm.total_energy_wh
    assert headwind.final_reserve_margin_wh < calm.final_reserve_margin_wh
```

- [ ] **Step 2: Run the new tests and observe missing report output.**

Run: `python -m pytest -p no:cacheprovider tests/test_fixed_plan_execution.py -q`

Expected: FAIL only until the report API and script are implemented.

- [ ] **Step 3: Implement the verification script with independent summary calculations.**

Load `scenarios/information_aware/seed_42.json`, choose only corridors whose
current packet and battery checks pass, execute the fixed plan, and print
structured values from the run log. Compute analytical zero/tail/head/crosswind
comparisons in the script from the documented equations rather than comparing
one simulator helper against another.

- [ ] **Step 4: Document the command and artifact separation.**

Add a short README section showing the verification command and stating that
the generated scenario remains controller-independent while the report is a
separate run artifact.

- [ ] **Step 5: Run the script and its tests.**

Run: `$env:PYTHONDONTWRITEBYTECODE='1'; python scripts/verify_core_uav_physics.py --scenario scenarios/information_aware/seed_42.json`

Expected: exit 0 and a report containing all requested trace fields, with no
changes to the scenario JSON.

### Task 8: Final regression, duplicate-physics scan, and audit

**Files:**
- Modify: `src/env/__init__.py` if exports need completion
- Modify: `tests/test_core_uav_physics.py` if audit coverage exposes a gap
- Modify: `tests/test_fixed_plan_execution.py` if audit coverage exposes a gap

**Interfaces:**
- Verifies the complete plan against the approved specification and does not
  add escalation, repair, or optimization behavior.

- [ ] **Step 1: Run the complete retained and new test suite.**

Run: `$env:PYTHONDONTWRITEBYTECODE='1'; python -m pytest -p no:cacheprovider tests -q`

Record the exact collected/passed/failed counts.

- [ ] **Step 2: Scan for duplicate live physics formulas and forbidden scope.**

Run: `rg -n 'e_c\s*\*|nominal_power|sqrt\(|P\s*=|energy_wh|evaluate_leg|N0|N1|N2|N3|N4|escalat|ALNS|MILP' src/env scripts tests`

Manually classify every hit. Only `energy.py` may contain the live wind-speed,
power, and leg-energy equations; other hits must be imports, delegation,
tests, or explicitly out-of-scope historical text.

- [ ] **Step 3: Run static/import and formatting checks.**

Run: `python -m compileall -q src scripts`

Run: `git diff --check`

Expected: both commands exit 0 without touching unrelated dirty files.

- [ ] **Step 4: Re-run the generated-seed and controlled-disturbance commands.**

Confirm the scenario hash is unchanged, the run artifact contains no future
packet or latent-truth fields, and the disturbance changes travel time,
energy, and reserve margin without invoking escalation or replanning.

- [ ] **Step 5: Produce the final structured report.**

Report the existing architecture map, modified files, exact equations and
units, API signatures, reason codes, execution semantics, packet-transition
semantics, test counts, analytical expected/actual/error values, generated
seed trace, conservation audit, remaining physical limitations, and readiness
for the next runtime-information/commitment chunk.
