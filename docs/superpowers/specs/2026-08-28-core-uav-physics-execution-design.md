# Core UAV Physics and Fixed-Plan Execution Design

## Status

The in-chat incremental design was approved on 2026-08-28. This document
records the implementation contract for the shared physical and operational
layer. It deliberately stops before selective escalation, repair levels, or
controller benchmarking.

## Goal and scope

Make one physically authoritative implementation answer
`(UAV, directed edge, departure time, payload, current environmental packet)`
with feasibility, travel time, energy, battery consequence, and diagnostics.
Add a deterministic executor for externally supplied fixed missions so that
loading, flight, service, delivery, battery use, inventory, demand, and event
history can be audited independently of any route-planning method.

Included:

- canonical km, h, km/h, kg, and Wh units;
- directed corridor geometry and wind decomposition;
- constant-airspeed ground-speed feasibility;
- payload-dependent nominal power and explicit Wh conversion;
- piecewise traversal across wind/packet-validity breakpoints;
- polygon-derived weather and airspace feasibility;
- hard horizon, battery, payload, inventory, demand, and reserve checks;
- fixed-Wh reserve semantics;
- packet-update state settling without rollback or teleportation;
- structured flight and delivery logs;
- deterministic fixed-plan execution and conservation audits;
- analytical, unit, integration, transition, and generated-seed tests.

Excluded:

- route construction or optimization;
- selective escalation and disturbance dependency graphs;
- N0--N4 repair logic;
- operational acceptability, regret, classifiers, ALNS tuning, or oracle
  controller experiments;
- writing runtime physics or controller outputs into canonical scenario JSON.

## Existing architecture and targeted changes

The retained Python package already has typed packets and network records,
`src/env/energy.py` as the intended physics home, a pure supplied-route
evaluator, and an event-driven `RoutingSimulator`. The baseline suite contains
106 passing tests. The checkout is intentionally dirty from prior repository
cleanup and environment-foundation work; unrelated changes remain untouched.

The implementation map is:

| Path | Classification | Responsibility after this change |
| --- | --- | --- |
| `src/env/params.py` | MODIFY | Document canonical units and shared numerical tolerances. |
| `src/env/entities.py` | MODIFY | Preserve commodity vectors and enforce runtime battery/cargo invariants. |
| `src/env/environment.py` | KEEP/MODIFY | Preserve typed packet/region contracts and interval semantics. |
| `src/env/network.py` | KEEP/MODIFY | Preserve directed edge geometry and expose tested direction helpers. |
| `src/env/wind.py` | KEEP | Keep packet interpolation and online visibility boundary. |
| `src/env/airspace.py` | KEEP/MODIFY | Keep polygon geometry helpers; route packet checks through the shared evaluator. |
| `src/env/energy.py` | MODIFY/CENTRALIZE | Own all leg direction, wind, speed, power, energy, partial-state, and reserve calculations. |
| `src/env/route_evaluator.py` | MODIFY | Aggregate route results only by calling `evaluate_leg`; enforce horizon and hard reasons. |
| `src/env/simulator.py` | MODIFY | Keep the command API; add hard state guards, precise packet transitions, and structured logs. |
| `src/env/metrics.py` | MODIFY | Store auditable flight/delivery events and per-UAV energy totals. |
| `src/env/fixed_plan.py` | CREATE | Execute deterministic externally supplied routes and delivery quantities. |
| `tests/test_core_uav_physics.py` | CREATE | Analytical physics, units, reasons, reserve, geometry, and piecewise traversal tests. |
| `tests/test_fixed_plan_execution.py` | CREATE | Fixed mission, conservation, event ordering, packet transition, and seed exercise tests. |

No duplicate live formula may remain in route or execution code. Compatibility
helpers may remain only when they delegate to the shared functions.

## Canonical units and tolerances

The existing scenario coordinate system is local Cartesian kilometres. It is
retained because it is internally consistent and already serialized by the
canonical scenario. The unit contract is:

| Quantity | Canonical unit | Rule |
| --- | --- | --- |
| distance and coordinates | km | Polyline segment lengths are summed in km. |
| time | h | Mission, packet, forecast, departure, and arrival values are hours. |
| speed and wind | km/h | Wind vectors point in the direction of air movement. |
| mass and payload | kg | Commodity quantities are converted with `commodities.w_k`. |
| power | W | `Wh/(km·kg) × kg × km/h` is numerically W. |
| energy and battery | Wh | `E_Wh = P_W × dt_h`; the equivalent seconds conversion is explicit as `P_W × dt_s / 3600`. |

The shared tolerances are named and documented: `DISTANCE_TOL_KM`,
`TIME_TOL_H`, `ENERGY_TOL_WH`, and `STATE_TOL`. They are used only for
floating-point boundary comparisons; they must never turn a physically
invalid square-root argument into a valid traversal.

## Canonical physics API

`src/env/energy.py` remains the only live implementation of the following
operations:

```python
evaluate_leg(
    edge,
    departure_time_h,
    payload_mass_kg,
    uav_parameters,
    environmental_packet,
) -> LegEvaluation

nominal_power(payload_mass_kg, uav_parameters) -> float

route_state_at(
    points_xy,
    departure_time_h,
    at_time_h,
    payload_mass_kg,
    uav_parameters,
    environmental_packet,
) -> tuple[np.ndarray, float, float, float]
```

`LegEvaluation` is immutable and contains at least:

```python
feasible: bool
reason: str | None
departure_time_h: float
arrival_time_h: float | None
travel_time_h: float | None
distance_km: float
airspeed_kmh: float
ground_speed_kmh: float | None
wind_vector_kmh: tuple[float, float] | None
along_track_wind_kmh: float | None
cross_track_wind_kmh: float | None
payload_mass_kg: float
power_w: float | None
energy_wh: float | None
weather_state: str
airspace_state: str
packet_id: str | None
diagnostics: dict
```

The `diagnostics` mapping includes the packet ID, direction and perpendicular
unit vectors, temporal segment records, and any safe-return margin supplied by
the caller. Existing field/property names such as `travel_time`, `energy`,
`distance_km`, and `ground_speed_kmh` remain usable.

For a directed edge from `i` to `j`, the evaluator derives

```text
d_ij       = (x_j - x_i, y_j - y_i)
e_ij       = d_ij / ||d_ij||
e_perp_ij  = (-e_ij[1], e_ij[0])
w_parallel = dot(w, e_ij)
w_perp     = dot(w, e_perp_ij)
s          = w_parallel + sqrt(v_uav^2 - w_perp^2)
P          = e_c * (m0 + payload_mass_kg) * v_uav
E_Wh       = P * delta_t_h
```

The perpendicular sign is positive for wind projected onto the
counter-clockwise normal. Reverse geometry reverses both direction vectors;
therefore `w_parallel_ji == -w_parallel_ij` and reverse traversal may have a
different speed, duration, and energy.

Course maintenance is infeasible when `abs(w_perp) >= v_uav`. The evaluator
returns a structured failure and never calls `sqrt` on that invalid argument.
It is also infeasible when `s <= 0`. The full canonical reason is
`NONPOSITIVE_GROUND_PROGRESS`.

Each leg is divided at packet validity boundaries, wind keyframe boundaries,
and region validity boundaries. Each covered interval uses the packet wind
defined for that interval and accumulates distance, time, and energy until the
edge length is exhausted. If the packet cannot cover the traversal, the
result is infeasible with `INVALID_ENVIRONMENTAL_COVERAGE` and no claimed ETA
or energy.

## Standardized hard reason codes

The common enum/string values are:

```text
CROSSWIND_EXCEEDS_AIRSPEED
NONPOSITIVE_GROUND_PROGRESS
HARD_WEATHER_BLOCK
AIRSPACE_BLOCK
INSUFFICIENT_BATTERY
SAFE_RETURN_RESERVE_VIOLATION
PAYLOAD_CAPACITY_EXCEEDED
INSUFFICIENT_DEPOT_INVENTORY
INVALID_COMMODITY_LOAD
MISSION_HORIZON_EXCEEDED
INVALID_EDGE
INVALID_ENVIRONMENTAL_COVERAGE
```

Old public reason spellings remain compatibility aliases at the adapter
boundary (`NONPOSITIVE_GROUND_SPEED`, `PAYLOAD_EXCEEDS_CAPACITY`, and
`ENVIRONMENT_COVERAGE_UNKNOWN`) but are not emitted by new canonical APIs or
new logs.

## Weather and airspace semantics

Packet weather is classified geometrically for the currently evaluated edge:
no intersection is `CLEAR`, a soft/degraded intersection is `DEGRADED` (the
existing `SOFT` field alias remains readable), and a hard intersection is
`BLOCKED` with `HARD_WEATHER_BLOCK`. Soft weather remains traversable and has
no arbitrary energy multiplier; its classification and exposure are
diagnostic only until a later model explicitly defines a physical consequence.

An active packet airspace polygon intersecting the edge is hard-infeasible with
`AIRSPACE_BLOCK`. Activation and expiration are interval properties of the
packet, not permanent mutation of network edges.

## Battery, reserve, and payload invariants

`UAVParameters.reserve_requirement_wh` is the canonical fixed-Wh reserve.
Initialization and every state transition enforce

```text
0 <= battery_wh <= battery_capacity_wh
payload_mass_kg <= max_payload_kg
```

Before dispatch, required flight energy plus the fixed reserve must fit the
available battery. At a delivery, service energy, predicted allowed return
energy with the post-delivery payload, and reserve must fit the current
battery. The reusable reserve margin is

```text
reserve_margin_wh = remaining_battery_wh
                    - predicted_return_energy_wh
                    - reserve_requirement_wh
```

Negative margin is a hard `SAFE_RETURN_RESERVE_VIOLATION`, even when the
battery is not yet zero. Battery consumption raises an explicit hard failure
instead of silently clamping negative state. No charging occurs outside the
existing explicit depot loading/charging operation.

Commodity vectors are preserved through loading, flight, delivery, residual
demand, and returned unused payload. `commodities.w_k` is the sole conversion
from commodity quantities to physical payload mass.

## Route aggregation and fixed-plan execution

`evaluate_route` remains a pure evaluator of a caller-supplied polyline. It
creates directed edge records for each segment and calls `evaluate_leg` for
each one, preserving per-leg payload masses. It returns aggregate duration,
energy, hard feasibility, standardized reasons, mission-horizon status, and a
reserve margin without mixing feasibility with humanitarian objective values.

`src/env/fixed_plan.py` exposes a small deterministic adapter around the
existing `RoutingSimulator`:

```python
plan = {
    "UAV-00": {
        "route": ["DEPOT", "NODE-000", "NODE-001", "DEPOT"],
        "load": [5.0, 0.0, 0.0, 0.0],
        "deliveries": {
            "NODE-000": [2.0, 0.0, 0.0, 0.0],
            "NODE-001": [3.0, 0.0, 0.0, 0.0],
        },
    }
}

execute_fixed_plan(scenario, plan) -> FixedPlanResult
```

The result contains the simulator, metrics, event log, completion status, and
conservation audit. It schedules loading, advances to load completion,
dispatches each supplied edge, services explicitly requested deliveries, and
returns to the depot. It never chooses a route or invents delivery quantities.
If a packet update interrupts a committed active leg, the simulator first
settles the physical state under the old packet. The executor may resume the
same remaining geometry under the new packet without constructing a new route;
ordinary callers may instead inspect the `AWAITING_ROUTE` state and issue an
explicit command.

## Packet updates and partial state

At an environment packet event during flight:

1. settle elapsed motion under the previously authoritative packet;
2. record exact partial position, travelled distance, energy, and battery;
3. cancel only the stale arrival event and retain the committed remainder for
   optional fixed-plan continuation;
4. install the newly issued packet and expose it in the snapshot;
5. never recalculate already flown distance, roll back, or teleport.

Partial position is computed by the same piecewise traversal integrator as
normal evaluation, not by a time fraction multiplied by total edge distance.
No future packet is accessed before its issue event.

## Structured run artifacts and conservation

Runtime results stay separate from `Scenario.to_dict()`. Every completed or
rejected leg records a structured event containing UAV, origin, destination,
edge geometry, departure/arrival, packet ID, payload and battery before/after,
wind components, ground speed, travel time, energy, weather/airspace state,
feasibility, and reason. Delivery records contain node, commodity, quantity,
actual completion time, and residual demand.

The simulator exposes a conservation audit for:

```text
initial inventory = depot inventory + loaded payload + delivered quantities
initial demand[node, commodity] = residual demand + delivered quantities
initial battery[uav] - final battery[uav] = executed flight + service energy
sum event distances = executed travelled distance
```

All equalities use named tolerances. Negative inventory, residual demand,
payload, or battery is rejected before state mutation.

## Verification contract

New tests must compare analytical values independently of the implementation
for zero wind, pure tailwind, pure headwind, known crosswind, payload-power
scaling, and W·s-to-Wh conversion. They must also cover reverse direction,
exact and excessive crosswind, stalled progress, horizon, packet coverage,
piecewise breakpoint traversal, packet transition, weather and airspace
validity, battery/reserve distinctions, commodity and payload propagation,
multiple-UAV independence, chronological event order, and all conservation
audits. Existing tests remain passing except where the revised standardized
reason spelling is intentionally exposed through a compatibility alias.

One deterministic generated seed (seed 42) is exercised with a manually
constructed valid mission. A controlled packet revision is demonstrated by
measuring a changed travel time, energy, and reserve margin without invoking
replanning or escalation logic.

