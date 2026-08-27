# Method-Neutral Information-Aware Routing Core Design

## Status and decision

This specification replaces the legacy UA-MTVRP-IU/ALNS simulator with a
small, method-neutral execution core for known-demand multi-UAV routing. The
research method is intentionally undecided. This milestone provides only the
scenario, information boundary, physical execution, feasibility evaluation,
and outcome accounting needed to evaluate a method chosen later.

The project-specific `src/env/robust_scenario_generator.py` remains the sole
scenario generator. It becomes standalone and no longer calls the old generic
`src/env/scenario_generator.py`, which is deleted.

## Goals

- Keep every delivery task known exactly at mission time zero.
- Preserve deterministic generation of 20-node scenarios with weather
  polygons, temporary no-fly polygons, and rolling online wind forecasts.
- Provide a simulator that executes externally supplied loading, routing, and
  delivery commands without deciding allocation, sequence, route, or replan.
- Keep controller-visible information separate from latent wind truth and
  unreleased forecast packets.
- Validate user-supplied polylines for airspace, forecast coverage, travel
  time, directional energy, battery reserve, and hazard exposure.
- Account for residual demand, deprivation, deliveries, energy, route
  violations, and completion without a solver-specific objective.
- Remove all ALNS, MAPPO, belief-state, P1/P2/P3/P4, learned-observation, and
  solver-diagnostic code and artifacts.

## Non-goals

This milestone does not implement or select:

- task allocation;
- visit sequencing;
- route search, shortest paths, A*, or waypoint generation;
- automatic replanning or repair;
- a comparison baseline;
- demand sensing, discovery, mutation, or estimation;
- delayed weather/airspace reports;
- a spatial or three-dimensional wind field.

The executor accepts decisions from tests or a future research method. It does
not provide a fallback heuristic when no decision is supplied.

## Why the two current generators are consolidated

The current project-specific generator calls the old generic generator to
obtain depot, node, demand, and inventory data. It then forces every node to be
known, deletes the old report and mutation schedules, replaces the legacy wind
field, and adds the new route disruptions. That wrapper relationship retains
belief and event parameters solely to turn them off.

The standalone generator will directly own:

1. clustered, feasibility-aware node placement;
2. exact demand and vulnerability generation;
3. depot inventory generation;
4. weather polygons and their updates;
5. temporary no-fly polygons and their updates;
6. latent two-dimensional wind truth;
7. rolling forecast packets; and
8. generation provenance and content hashing.

There will be one generator implementation and one generator CLI.

## Retained architecture

### Scenario generation and serialization

`robust_scenario_generator.py` remains the canonical generator. Its public
entry points remain:

```python
def load_information_aware_config(
    path: str | pathlib.Path,
) -> tuple[EnvParams, RouteDisruptionConfig]: ...

def generate_information_aware_scenario(
    seed: int,
    params: EnvParams | None = None,
    config: RouteDisruptionConfig | None = None,
) -> Scenario: ...
```

The generator uses separate deterministic random streams for known tasks,
weather, airspace, wind truth, and forecast error. Removing one environmental
family must not alter the other families. Version-2 outputs are deterministic
for a seed and configuration, but they are not required to be byte-identical
to the legacy version-1 scenario because the old task random stream consumed
unused belief/report draws.

The seed-42 artifact retains the agreed semantics: 20 exact known tasks, three
UAVs, a 12-hour mission, two weather episodes, two no-fly episodes, and rolling
wind forecasts issued every 0.5 hour with a 1.5-hour valid horizon.

### Lean scenario schema

`scenario.py` contains data and serialization only. The executable schema is:

```python
@dataclass(frozen=True)
class ScenarioNode:
    idx: int
    x: float
    y: float
    vulnerability: float
    demand: list[float]

@dataclass
class Scenario:
    seed: int
    params: dict
    depot: list[float]
    nodes: list[ScenarioNode]
    initial_inventory: list[float]
    no_fly_zones: list[NoFlyZone]
    hazard_regions: list[HazardRegion]
    airspace_updates: list[AirspaceUpdateEvent]
    wind_spec: dict
    generation_metadata: dict[str, object]
```

All demand exists and is visible at `t=0`. The schema has no onset, reveal,
reported demand, uncertainty, confidence, P1 reports, P3 mutations, edge
availability flips, replenishments, hazard bumps, or P4 random seed.

Airspace state has one timeline. `AirspaceUpdateEvent` contains one `time_h`
and no separate physical, report, or receive time. Weather and no-fly changes
become physically active and controller-visible at that timestamp. Wind keeps
separate packet issue and point-valid times because rolling forecast revision
is the intended online-information mechanism.

`Scenario` retains `to_dict()`, `from_dict()`, `to_json()`, `from_json()`,
`content_hash()`, `node_positions()`, `env_params()`, `airspace_timeline()`,
and `wind_forecast_timeline()`. It does not construct simulator entities or
belief state.

Generation metadata uses schema identifier
`information-aware-routing-v2` and scenario type
`known_tasks_dynamic_routes`.

### Parameters

`params.py` retains only:

- `PhysicsParams`: payload mass, empty mass, battery capacity, propulsion
  coefficient, service energy, reserve, and cruise speed;
- `CommodityParams`: unit mass and deprivation coefficients;
- `MapParams`: region size, node/cluster counts, placement controls,
  vulnerability range, and demand means;
- `RouteValidationParams`: safe-corridor margin;
- `MissionParams`: horizon, fleet size, loading time, charging time, service
  time, and depot-bay count; and
- `EnvParams`: the five groups above.

Belief, information-event, hybrid, solver, reward-weight, path-search, and
discount parameters are removed. Configuration loading rejects unknown legacy
keys instead of silently ignoring them.

### Route evaluator

A new `route_evaluator.py` evaluates a supplied polyline and never creates or
modifies one:

```python
@dataclass(frozen=True)
class RouteEvaluation:
    distance_km: float
    duration_h: float
    hard_blocked: bool
    hazard_exposure: float
    forecast_covered: bool
    forecast_energy_wh: float | None
    battery_feasible: bool | None
    reasons: tuple[str, ...]

def evaluate_route(
    points_xy: Sequence[Sequence[float]],
    departure_time_h: float,
    payload_mass_kg: float,
    battery_wh: float,
    airspace: AirspaceMap,
    forecast: OnlineWindForecast,
    params: EnvParams,
) -> RouteEvaluation: ...
```

The evaluator validates finite two-dimensional points, at least two points,
map bounds, hard-region intersections, and the battery reserve. Travel time is
polyline length divided by cruise speed. Directional energy uses the latest
received forecast evaluated at each segment midpoint. If any segment lies
outside the received forecast packet's valid interval, energy and battery
feasibility are `None`; wind is never extrapolated. Soft-hazard intersection
length is reported as exposure without selecting an alternative path.

The evaluator may return an uncertified result so a prospective method can
diagnose why a route is unusable. The executor is stricter: `dispatch` requires
`forecast_covered=True` and `battery_feasible=True` in addition to no hard
block. It therefore never launches a route whose reserve cannot be certified
from information currently available to the controller.

An internal realized-route calculation uses latent wind truth for simulation
accounting. It is not included in controller snapshots.

### Method-neutral executor

A new `simulator.py` replaces `uav_env.py`. It owns physical state and event
time but contains no policy. Its public interface is command-based:

```python
class RoutingSimulator:
    def reset(self, scenario: Scenario) -> EnvironmentSnapshot: ...
    def prepare(self, uav_id: int, quantities: Sequence[float]) -> None: ...
    def dispatch(
        self,
        uav_id: int,
        destination: int,
        waypoints_xy: Sequence[Sequence[float]],
    ) -> None: ...
    def deliver(self, uav_id: int, quantities: Sequence[float]) -> None: ...
    def advance(self) -> DecisionEpoch: ...
```

`destination=-1` denotes the depot. `prepare` is legal only at the depot and
reserves available inventory subject to payload capacity. It schedules loading
and full charging using the finite depot-bay queue. `dispatch` is legal only
for a ready UAV, requires the supplied path to begin at its current position
and end at the destination, and rejects a currently blocked or known
battery-infeasible route. `deliver` is legal only at the specified demand node
and cannot exceed onboard quantities or residual demand.

`advance` processes the next event in deterministic timestamp order, accrues
deprivation over the elapsed interval, settles realized energy and movement,
applies environmental information, and returns an immutable snapshot. The
caller decides what to do next. The simulator never chooses a node, delivery
quantity, waypoint, sequence, or replacement route.

If an airspace or forecast update arrives during flight, the executor settles
the UAV to its interpolated position at that time and returns a decision epoch.
It cancels the pending waypoint event and places the UAV in
`AWAITING_ROUTE` at that position. The outstanding route is not automatically
continued or repaired. The caller may submit its remaining geometry as a new
polyline, divert elsewhere, return, or wait.

### Information boundary

`EnvironmentSnapshot` contains only:

- current mission time;
- all known task locations, vulnerability, and residual demand;
- current inventory and UAV physical states;
- currently received weather/no-fly state;
- the latest received wind forecast packet; and
- the event type that opened the decision epoch.

It never contains future polygon updates, unreleased forecast packets, or
latent wind truth. Snapshot values are copies so callers cannot mutate the
simulator. Oracle helpers used by tests and evaluation are explicitly named
with an `oracle_` prefix and are not members of `EnvironmentSnapshot`.

Weather/no-fly physical onset and controller visibility remain simultaneous,
matching the approved scenario configuration. Wind packets remain rolling and
online: only packets with `issued_at_h <= current_time` are visible.

### Physical state and events

`entities.py` is reduced to exact, observable state:

- `DemandNodeState`: position, vulnerability, initial demand, and residual
  demand;
- `UAVState`: position, battery, payload, mode, destination, and active
  supplied polyline; and
- `DepotInventory`: available quantities and bay availability.

All demand is a single `t=0` cohort, so dynamic cohort insertion and hidden
onset/reveal fields are removed.

`events.py` retains a deterministic queue and only these event families:

- `AIRSPACE_UPDATE`;
- `WIND_FORECAST_UPDATE`;
- `WAYPOINT_REACHED`;
- `LOAD_COMPLETE`;
- `SERVICE_COMPLETE`; and
- `HORIZON`.

There are no demand-information, availability-flip, strategic-review,
trajectory-tick, backup, resolve, or solver events.

### Deprivation and metrics

`deprivation.py` retains waiting-cost functions and exact true-deprivation
integrals. It accepts known residual demand and elapsed time directly. All
belief-side urgency, expected-value, and assignment-value functions are
removed.

`metrics.py` reports:

- total and per-node deprivation;
- energy consumed;
- hard-route and battery violations;
- delivered units and fill rate;
- unserved residual demand;
- completed services; and
- termination reason.

It contains no belief objective, solve count, plan divergence, policy reward,
or algorithm-specific statistic.

## File disposition

### Retain and refactor

```text
src/env/__init__.py
src/env/airspace.py
src/env/deprivation.py
src/env/energy.py
src/env/entities.py
src/env/events.py
src/env/metrics.py
src/env/params.py
src/env/robust_scenario_generator.py
src/env/scenario.py
src/env/wind.py
scripts/generate_information_aware_scenario.py
scripts/render_information_aware_scenario.py
configs/env/information_aware_routes.yaml
```

### Create

```text
src/env/route_evaluator.py
src/env/simulator.py
tests/test_route_evaluator.py
tests/test_simulator.py
```

### Delete

```text
src/agents/
src/env/alns_scaffold.py
src/env/belief.py
src/env/graph.py
src/env/observation_contract.py
src/env/online_replanning.py
src/env/scenario_generator.py
src/env/trajectory.py
src/env/uav_env.py
scripts/run_alns_headroom_test.py
configs/env/alns_headroom_environment.yaml
configs/method/
results/alns_headroom_development/
```

Tests tied to any deleted module, ALNS, belief updates, learned observations,
old trajectory search, old scenario schema, or old simulator actions are also
deleted. Tests for retained behavior are rewritten against the lean contracts.

## Canonical artifacts and documentation

Seed 42 is regenerated from
`configs/env/information_aware_routes.yaml`. The canonical JSON content hash is
updated for schema version 2. Determinism is checked by two independent
generations with byte-identical output.

The self-contained HTML renderer is updated for the lean node and parameter
field names. It continues to show route availability, current-valid-time wind,
forecast issue/valid intervals, weather/no-fly regions, and oracle wind truth
for evaluation. It does not display or imply an allocation/routing method.

`README.md` and `PROJECT_CONTEXT.md` describe the repository as a scenario and
execution testbed awaiting method selection. All ALNS instructions and result
references are removed.

## Error handling

- Configuration loaders reject unknown keys and invalid numeric ranges.
- Scenario deserialization rejects missing or legacy fields rather than
  silently accepting mixed schemas.
- Commands reject invalid UAV state, payload, destination, path endpoints,
  inventory, delivery amount, and time ordering with `ValueError`.
- A hard-blocked, forecast-uncovered, or battery-infeasible dispatch is
  rejected.
- A route outside forecast coverage is represented as uncertified, not
  fabricated by extrapolation.
- Events at the same timestamp use an explicit deterministic priority.

## Verification contract

The refactor is complete only when:

1. repository search finds no `ALNS`, `MAPPO`, belief, P1/P2/P3/P4,
   legacy `env.scenario_generator` import/path, `uav_env`, learned-observation,
   or path-search references outside historical design/plan documents;
2. only the new robust generator can create scenarios;
3. seed 42 generates twice to byte-identical version-2 JSON;
4. all tasks are exact and visible at `t=0` with no uncertainty fields;
5. future airspace updates and wind packets are absent from controller
   snapshots;
6. headwind/tailwind asymmetry and missing forecast coverage are tested;
7. the evaluator never creates waypoints or searches for a path;
8. manually supplied commands can load, fly, deliver, return, and accrue
   expected energy and deprivation;
9. mid-flight environmental updates produce a decision epoch without an
   automatic replan;
10. invalid route, payload, battery, and inventory commands fail closed;
11. the regenerated HTML embeds the JSON's exact content hash and contains no
    network fetch; and
12. the complete retained test suite, import check, forbidden-reference scan,
    and `git diff --check` pass without recreating caches.

## Implementation safety

The repository remains a dirty shared working tree. Implementation must not
reset, checkout, stage, or commit unrelated user changes. Deletion targets are
resolved explicitly under `D:/Post-disaster Logistics/code`. The canonical
scenario and HTML are regenerated only after the new schema and generator
tests pass.
