# Authoritative Environment Foundation Design

## Status and decision

This design updates the existing known-demand routing core to the revised
authoritative-environment model. The current checkout already contains a
method-neutral executor, polygonal route state, and a rolling wind forecast,
but its canonical data still uses `truth_keyframes`, forecast-error draws,
separate airspace events, and implicit fleet/network data.

The implementation will introduce typed canonical environmental packets,
explicit fleet and network records, and one shared leg-physics evaluator. New
scenarios will contain only packet information; they will not generate or
serialize a latent wind truth or forecast-error stream. Older scenario JSON
that contains those fields remains readable through an explicit compatibility
adapter and is never used as the shape of newly generated scenarios.

## Scope

Included:

- known depot, commodity, relief-node, fleet, and network data;
- a 12-hour configurable mission with 0.5-hour environmental updates and a
  1.5-hour configurable packet horizon by default;
- global time-varying two-dimensional wind packets;
- packet overlap, genuine revision, and newly revealed-horizon comparison;
- polygonal soft/hard weather and hard airspace restrictions;
- geometry-derived corridor states;
- a single directional leg evaluator with payload-dependent energy;
- temporal integration over packet wind intervals;
- battery and reserve quantities exposed to later controller work;
- schema/version/config/scenario hashes, descriptors, and reproducible output;
- regression tests and regeneration of the seed-42 JSON and HTML inspection
  page.

Excluded:

- incumbent-plan impact detection;
- repair/escalation levels N0--N4;
- task reassignment, reoptimization, ALNS, MILP, learning, or baselines;
- hidden demand, demand discovery, probabilistic weather beliefs, forecast
  reliability distributions, or spatial wind fields.

## Current implementation map

- `src/env/robust_scenario_generator.py` is the only active generator. It
  creates known clustered tasks, polygon disruptions, and rolling packets, but
  currently emits legacy `wind_spec.truth_keyframes` and adds random forecast
  error.
- `src/env/scenario.py` serializes the lean v2 fields
  (`seed`, `params`, `nodes`, regions, updates, and `wind_spec`) and has no
  explicit fleet, network, packet, descriptor, or metadata hash fields.
- `src/env/wind.py` owns packet interpolation and online latest-packet state,
  while also exposing a truth-only helper.
- `src/env/airspace.py` already derives hard/soft geometry intersections, but
  represents regions as legacy objects and receives separate update events.
- `src/env/energy.py` contains the useful constant-airspeed equations, but
  exposes several overlapping route/energy helpers and the simulator still
  uses a truth-based execution path.
- `src/env/route_evaluator.py` evaluates caller polylines but repeats route
  chaining/coverage decisions outside a typed leg result.
- `src/env/simulator.py` creates homogeneous UAVs from global parameters,
  queues separate wind/airspace events, and settles flights against latent
  truth.
- `scripts/render_information_aware_scenario.py` embeds the legacy schema and
  displays forecast error and latent truth. It will be updated to show packet
  revisions and packet-authoritative conditions without implying a controller
  route.

The existing checkout is intentionally dirty from the preceding repository
cleanup. Only the retained environment modules, tests, configuration,
canonical scenario, HTML renderer/output, and this documentation will be
touched. No unrelated deletions will be staged or reverted.

## Canonical data model

The new `Scenario.to_dict()` emits exactly this top-level shape:

```json
{
  "schema_version": "information-aware-routing-v3",
  "metadata": {
    "seed": 1042,
    "generator_version": "authoritative-packets-v1",
    "config_hash": "<sha256>",
    "scenario_hash": "<sha256>"
  },
  "mission": {
    "horizon_h": 12.0,
    "environment_update_interval_h": 0.5,
    "forecast_horizon_h": 1.5
  },
  "depot": {
    "id": "DEPOT",
    "position": [6.0, 6.0],
    "initial_inventory": [1.0, 2.0, 3.0, 0.5]
  },
  "commodities": [
    {"id": "medical", "unit_mass_kg": 0.25}
  ],
  "relief_nodes": [
    {
      "id": "NODE-000",
      "position": [7.0, 6.0],
      "priority": 1.0,
      "vulnerability": 1.0,
      "demand": [1.0, 0.0, 0.0, 0.0]
    }
  ],
  "fleet": [
    {
      "id": "UAV-00",
      "nominal_airspeed_kmh": 60.0,
      "empty_mass_kg": 4.0,
      "max_payload_kg": 2.5,
      "battery_capacity_wh": 230.0,
      "reserve_requirement_wh": 23.0,
      "energy_coefficient_wh_per_km_kg": 3.125,
      "service_energy_wh": 2.5
    }
  ],
  "network": {
    "nodes": [{"id": "DEPOT", "position": [6.0, 6.0]}],
    "edges": [
      {
        "id": "DEPOT->NODE-000",
        "origin": "DEPOT",
        "destination": "NODE-000",
        "length_km": 1.0,
        "bearing_rad": 0.0,
        "geometry": [[6.0, 6.0], [7.0, 6.0]]
      }
    ]
  },
  "environment_packets": [
    {
      "packet_id": "ENV-000",
      "issued_at_h": 0.0,
      "valid_from_h": 0.0,
      "valid_until_h": 1.5,
      "wind": {
        "model": "global_2d",
        "vector_convention": "towards",
        "units": {"time": "h", "speed": "km/h"},
        "points": [
          {"valid_time_h": 0.0, "u_kmh": 0.0, "v_kmh": 0.0},
          {"valid_time_h": 1.5, "u_kmh": 0.0, "v_kmh": 0.0}
        ]
      },
      "weather": [],
      "airspace": []
    }
  ],
  "scenario_descriptors": {
    "number_of_relief_nodes": 1,
    "number_of_uavs": 1,
    "number_of_graph_edges": 1,
    "number_of_environment_packets": 1,
    "number_of_weather_regions": 0,
    "number_of_airspace_announcements": 0,
    "mean_wind_magnitude_kmh": 0.0,
    "maximum_wind_magnitude_kmh": 0.0,
    "packet_revision_count": 0
  }
}
```

Internal coordinates remain kilometres, time remains hours, speed remains
km/h, mass remains kg, and energy remains Wh. These are already consistent in
the existing tested model; conversions are explicit at the geometry/battery
boundaries. The canonical schema names all units where ambiguity would be
likely.

The Python `Scenario` class keeps read-only legacy aliases (`seed`, `params`,
`nodes`, `initial_inventory`, `wind_spec`, and old region collections) so the
previous executor and old JSON can be migrated deliberately. Those aliases
are not emitted by the canonical serializer.

## Packet semantics

An `EnvironmentalPacket` is an authoritative information object issued at
`issued_at_h`. It describes conditions from `valid_from_h` through
`valid_until_h`, with the upper bound truncated to the mission horizon. Its
wind is a global east/north vector timeline; weather and airspace are polygon
records whose validity intervals are interpreted geometrically at traversal
time.

At time `t_n`, only packets with `issued_at_h <= t_n` are controller-visible.
The latest received packet is authoritative for its interval until a later
packet supersedes it. A later packet may revise wind values, polygon geometry,
severity, or validity inside the overlap. The generator creates packets from
a smooth reproducible packet process with a configurable revision magnitude,
not from a truth-plus-error model.

`compare_environmental_packets(previous, current)` returns an
`EnvironmentalTransition` with:

- `overlap`: the common valid interval;
- `revised`: changes whose timestamp/validity lies in the overlap; and
- `newly_revealed`: conditions in the portion of the current horizon outside
  the previous horizon.

No repair level is inferred or stored.

## Geometry and network

`NetworkEdge` stores directed origin/destination identifiers, physical length,
bearing, and a polyline geometry. The generator emits a separate reverse edge
for each depot/task corridor with reversed geometry. Even when two edges share
the same physical corridor, wind decomposition is performed from the edge's
directed endpoints, so travel time and energy need not be symmetric.

`WeatherRegion` supports `DEGRADED` and `BLOCKED`; `AirspaceRestriction` is
always hard. A corridor state is derived by intersecting its polyline with
regions that are valid at the traversal time. No `CORRIDOR_BLOCKED`,
`CORRIDOR_REOPENED`, or controller-impact event is serialized.

## Shared flight physics

`src/env/energy.py` will expose the single authoritative
`evaluate_leg(edge, departure_time_h, payload_mass_kg, uav_parameters,
environmental_packet)` implementation and a frozen `LegEvaluation` result.
All route, safe-return, and execution helpers delegate to it.

For directed unit vector `e` and global wind `w`:

```text
w_parallel = dot(w, e)
w_perp     = dot(w, [-e_y, e_x])
s          = w_parallel + sqrt(v_uav^2 - w_perp^2)
P          = e_c * (m0 + payload_mass) * v_uav
energy     = P * travel_time
```

The leg is infeasible with explicit reason `CROSSWIND_EXCEEDS_AIRSPEED` when
`abs(w_perp) >= v_uav`, or `NONPOSITIVE_GROUND_SPEED` when `s <= 0`. Hard
weather and airspace produce `HARD_WEATHER_BLOCK` and `AIRSPACE_BLOCK`.
Missing packet coverage produces `ENVIRONMENT_COVERAGE_UNKNOWN`. Feasible
travel time is the time integral of the directed speed over packet time
segments; energy is the corresponding power-time integral.

The evaluator returns along/crosswind components, weather and airspace states,
ground speed, travel time, and energy. A route with per-leg payload masses
delegates each leg separately, allowing delivery payload to decrease between
legs. Battery capacity and reserve remain hard feasibility quantities; reserve
shortfalls are reported explicitly and never converted to an objective
penalty.

## Runtime transition

The simulator will queue one environment-packet event per `issued_at_h`. On a
packet event, it first settles active flights under the prior packet, replaces
the authoritative packet, and interrupts active flights into
`AWAITING_ROUTE`. It never constructs a replacement route. Dispatch evaluates
the caller-supplied polyline against the current packet and current geometry;
execution thereafter uses the same packet-aware leg integration. Snapshots
expose current tasks, fleet state, inventory, current packet, and active
regions, but no future packets or compatibility truth data.

Legacy scenarios are adapted at reset time: old forecast packets become
packet wind data and old truth data is used only as a deprecated fallback for
old replay files. New generated scenarios never exercise that fallback.

## Verification and visualization

Tests will cover deterministic hashes, different-seed variation, horizon
truncation, overlap/revision/new-horizon comparison, zero/head/tail/crosswind,
directional asymmetry, payload-dependent energy, multi-leg payload changes,
polygon intersection, airspace validity, reserve checks, and old-schema
migration. The seed-42 JSON will be regenerated only after those tests pass.

`outputs/information_aware_seed_42.html` will be regenerated from the new
canonical JSON. It will visualize known nodes, directed network corridors,
packet valid horizons, packet revisions, geometry-derived route states, and
the current authoritative wind. It will not label values as forecast error or
show latent truth from new scenarios.

