# Decision-Epoch Disturbance Diagnostic Design

## Status and decision

This design adds a method-neutral diagnostic boundary for a received
environmental-packet update. It evaluates the caller's incumbent plan under
the previously received packet and the newly received packet, identifies the
remaining legs touched by the packet transition, and propagates forecast
effects through the declared plan suffix.

The diagnostic is an observation/evaluation utility. It does not select a
route, construct a replacement geometry, repair a leg, reassign a task,
choose a delivery, or infer a controller action. It consumes only static
scenario data that is known at mission start, the supplied decision-epoch
snapshot, and the two explicit packets supplied by the caller. It never reads
the scenario's unrevealed packet timeline or any latent wind representation.

## Goals

- Provide one pure API for diagnosing an environmental packet revision at a
  decision epoch.
- Preserve the existing fixed-plan mapping as the incumbent-plan input shape:
  each UAV entry declares an ordered `route`, optional `load`, and optional
  `deliveries`.
- Identify only the uncompleted suffix of each declared route.
- Distinguish directly packet-affected legs from downstream legs whose timing
  or battery state changes only through propagation.
- Propagate controller-visible travel time, ETA, flight energy, battery, fixed
  reserve, service time/energy, and optional node deadline effects.
- Return an immutable, JSON-serializable closure with packet-transition,
  per-leg, and summary records.
- Make the most recent packet interruption's committed remainder visible in
  simulator snapshots so a post-update diagnostic can inspect it without
  reading simulator internals.
- Show a deterministic controlled packet revision and its closure in the
  existing self-contained scenario HTML.

## Non-goals and hard boundaries

The feature does not implement or expose:

- route construction, waypoint generation, graph search, or alternate paths;
- repair, escalation, replanning, optimization, ALNS, MILP, or learning;
- task allocation, task reassignment, or delivery selection;
- packet prediction, forecast extrapolation, or access to future packets;
- latent truth wind, forecast error, uncertainty beliefs, or hidden state;
- changes to the canonical scenario JSON schema.

The diagnostic may use an existing canonical network edge or an explicitly
declared incumbent geometry. A missing alternative is a diagnostic input
error; it is never repaired by the environment.

## Public interface

Create `src/env/diagnostics.py` with these public records and function:

```python
def diagnose_environmental_packet_update(
    scenario: Scenario,
    incumbent_plan: Mapping[Any, Mapping[str, Any]],
    epoch: EnvironmentSnapshot,
    previous_packet: EnvironmentalPacket,
    received_packet: EnvironmentalPacket,
    deadlines_h: Mapping[Any, float] | None = None,
) -> DisturbanceImpactClosure: ...
```

Expose the shorter alias `diagnose_packet_update` and re-export the public
function and `DisturbanceImpactClosure` from `env.__init__`.

The API validates that both packet issue times are no later than
`epoch.time_h`, the received packet is later than the previous packet, and an
already-populated `epoch.environment_packet` (when present) has the received
packet ID. These checks enforce that the caller cannot diagnose an unrevealed
packet by mistake.

The function may read `scenario.nodes`, `scenario.depot`, `scenario.network`,
`scenario.fleet`, and `scenario.env_params()` because those are static,
mission-time-known data. It must not read `scenario.environment_packets`,
`scenario.wind_spec`, forecast truth helpers, or any event queue. The explicit
packet arguments are the complete environmental input.

## Closure data model

The module returns frozen dataclasses with tuple-based collections:

```python
@dataclass(frozen=True)
class LegProjection:
    feasible: bool
    reason: str | None
    reason_codes: tuple[str, ...]
    departure_time_h: float | None
    arrival_time_h: float | None
    travel_time_h: float | None
    energy_wh: float | None
    battery_before_wh: float | None
    battery_after_flight_wh: float | None
    service_energy_wh: float
    battery_after_service_wh: float | None
    reserve_margin_wh: float | None
    deadline_h: float | None
    deadline_slack_h: float | None
    deadline_met: bool | None

@dataclass(frozen=True)
class LegImpact:
    leg_id: str
    uav_id: str
    uav_idx: int
    route_index: int
    origin: str
    destination: str
    geometry: tuple[tuple[float, float], ...]
    payload_mass_kg: float
    directly_affected: bool
    direct_changes: tuple[EnvironmentalChange, ...]
    propagated: bool
    baseline: LegProjection
    revised: LegProjection
    delta_arrival_time_h: float | None
    delta_travel_time_h: float | None
    delta_energy_wh: float | None
    delta_deadline_slack_h: float | None

@dataclass(frozen=True)
class DisturbanceImpactClosure:
    epoch_time_h: float
    previous_packet_id: str
    received_packet_id: str
    transition: EnvironmentalTransition
    legs: tuple[LegImpact, ...]
    summary: Mapping[str, Any]
    non_anticipative: bool = True
```

`DisturbanceImpactClosure.to_dict()` serializes all fields, including
`transition`, `legs`, and `summary`; no NumPy arrays or Enum objects remain in
the result. `leg_id` is deterministic as
`<uav_id>:leg-<route_index zero-padded to three digits>`.

## Remaining-leg extraction

For each plan entry, the diagnostic maps the plan key to a canonical fleet
UAV ID and validates the existing fixed-plan shape. It uses the epoch UAV
state to select the uncompleted suffix:

- at `DEPOT` or `AT_NODE`, the next declared route edge begins at the current
  route label;
- while `FLYING`, `epoch.uavs[*].committed_route` is the active geometry to
  `epoch.uavs[*].committed_destination`, followed by the declared route suffix;
- after a packet interruption, `committed_route` is the stored physical
  remainder and `committed_destination` is the original destination;
- a UAV with no declared remaining edge contributes no leg record.

The current route geometry is taken from `committed_route` when available,
otherwise from the matching directed `NetworkEdge` in `scenario.network`.
The diagnostic never searches for a route. A declared route edge absent from
the network must provide an explicit per-leg geometry in the incumbent plan;
otherwise the input is rejected.

If a declared route revisits the observed stop, the plan entry must include
`current_route_index` (the zero-based index of the observed stop), except for
the conventional initial/terminal depot pair when the snapshot is interpreted
as the initial depot state. Without that cursor the diagnostic rejects an
ambiguous repeated occurrence instead of guessing which completed stop should
be removed from the suffix.

The first leg starts at `epoch.time_h`. The current snapshot payload and
battery are authoritative for the first leg. For a not-yet-loaded UAV at the
depot, the declared plan `load` supplies its starting payload. After each
declared delivery at a visited node, the next leg carries the reduced payload
and incurs the configured service time and service energy. Invalid negative or
over-capacity payload transitions are reported as input errors, not repaired.

Deadlines are optional and are keyed by node ID, node index, or the exact
route label. An unspecified destination deadline is the mission horizon. A
deadline applies to arrival at the destination before service; deadline slack
is `deadline_h - arrival_time_h`.

## Packet comparison and direct impact

The implementation calls the existing
`compare_environmental_packets(previous_packet, received_packet)` and stores
its overlap, revised changes, and newly revealed changes in the closure.

A remaining leg is directly affected when at least one transition change
touches both:

1. the leg's declared geometry (wind changes are global; weather/airspace
   changes require polygon intersection); and
2. the leg's baseline or revised controller-visible traversal interval.

Point-valued wind changes are considered touching when their timestamp lies on
the interval boundary. Region changes use the before/after region geometry and
the change interval. A region outside the leg geometry does not mark the leg
directly affected, even if it is in the same packet. A later leg whose own
geometry/time is untouched but whose departure/arrival or battery changes
because an earlier leg changed is marked `propagated=True` and
`directly_affected=False`.

The direct-change records preserve the original `EnvironmentalChange` values
and are not converted into an action recommendation.

## Baseline/revised propagation

Both projections use the shared `evaluate_leg` implementation with the same
declared geometry, payload, and starting decision-epoch state:

- baseline uses only `previous_packet`;
- revised uses only `received_packet`.

Each UAV's legs are evaluated in route order. A feasible leg advances time by
its packet-aware travel time and battery by its packet-aware flight energy;
declared service then advances time by `service_time_h` and battery by the
UAV's `service_energy_wh`. Per-leg reserve margin is battery after the leg's
service minus the UAV reserve requirement. ETA and deadline deltas are
computed only when both corresponding values are known.

If a projection becomes infeasible or environmentally uncovered, that
projection records its canonical reason code and all later legs in that
projection are returned as unprojected with an upstream-propagation reason.
The other packet projection continues independently, so the closure can show
the observable difference without inventing a repair. No forecast value is
extrapolated beyond a packet's valid interval.

The summary includes total remaining legs, directly affected count,
propagated count, baseline/revised infeasible counts, baseline/revised
deadline-miss counts, total known flight-energy delta, and maximum known
arrival-time delta.

## Simulator snapshot integration

Extend `UAVSnapshot` with optional read-only fields:

```python
committed_route: np.ndarray | None
committed_destination: int | None
```

During ordinary flight, these mirror the active route and destination. After
an environmental packet interruption, they expose the pending physical
remainder and its original destination. They contain no future environmental
packet data.

`RoutingSimulator` stores the immediately preceding authoritative packet
when applying a packet update and provides:

```python
def diagnose_packet_update(
    self,
    incumbent_plan: Mapping[Any, Mapping[str, Any]],
    deadlines_h: Mapping[Any, float] | None = None,
) -> DisturbanceImpactClosure: ...
```

This convenience method is valid only after a packet-update decision epoch
and delegates to the pure function with the current snapshot, previous
packet, and current packet. It does not alter simulator state or choose a
follow-up command. The diagnostic window closes as soon as a controller
command mutates or attempts to mutate simulator state; callers must diagnose
before `prepare`, `dispatch`, `resume_current_leg`, `deliver`, or direct
battery-consumption commands.

## Visualization

The renderer continues to serialize the canonical scenario only. At render
time it constructs an explicit, deterministic demonstration input outside the
scenario payload:

- a declared depot→first-node→depot incumbent;
- a previous packet and a later packet cloned from the first packet with a
  controlled wind revision in their overlap;
- a node deadline selected from the demonstration's projected values.

The HTML embeds the resulting closure under a dedicated
`data-role="impact-closure"` section titled “Controlled packet-revision
disturbance-impact closure”. It displays packet IDs, direct versus propagated
leg counts, ETA/energy/deadline deltas, and per-leg status. The page remains
self-contained and does not add `fetch(` or expose future packets/truth.

## Testing and acceptance

Add `tests/test_decision_epoch_diagnostics.py` covering:

1. a received packet is rejected before its issue time and a future timeline
   packet cannot affect a closure;
2. an active/committed remainder is selected after an interruption;
3. a changed wind or intersecting region marks only the directly affected
   remaining leg(s);
4. downstream ETA, energy, reserve, and deadline slack propagate in order;
5. infeasible/unknown packet coverage yields canonical reasons and does not
   construct or repair a replacement route;
6. closure serialization contains only JSON-compatible structured values.

Extend the artifact tests to assert that the rendered HTML embeds the closure
section and its controlled revision labels. Run the full retained suite with:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest -p no:cacheprovider tests -q
```

Also run `python -m compileall -q src scripts`, `git diff --check`, and the
canonical scenario/HTML generation commands. Existing tests and the canonical
scenario hash must remain unchanged except for the regenerated HTML's added
demonstration section.
