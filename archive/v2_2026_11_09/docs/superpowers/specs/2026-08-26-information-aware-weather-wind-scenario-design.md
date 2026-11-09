# Information-Aware Weather and Wind Scenario Design

**Date:** 2026-08-26

## Objective

Extend the existing known-demand route-disruption generator into a reproducible
benchmark in which 20 fixed relief tasks are routed by three UAVs while weather,
temporary airspace restrictions, and rolling wind forecasts change the route
and battery-feasibility information available online.

## Scope boundary

All task data are exact at time zero: locations, four-commodity demands,
vulnerability, demand onset, depot stock, and fleet parameters. No node is
hidden and no sensing, victim-discovery, demand-reporting, or endogenous
information-acquisition action exists. The only information process added in
this milestone is exogenous environmental information.

## Scenario data and random streams

The existing `Scenario.wind_spec` remains the serialized wind container for
backward compatibility. It will hold a versioned `global_2d` model, latent truth
keyframes, and serialized rolling forecast packets while retaining neutral
legacy scalar-wind fields (`base_keyframes` and `gusts`). Existing weather and
airspace random streams remain the first two children of their current seed
sequence; wind truth and forecast error use two new independent children. Thus,
changing wind settings cannot alter tasks or polygon disruptions.

Wind truth is a seeded, smooth, piecewise-linear global vector in km/h over the
12-hour mission. Keyframes store `[time_h, eastward_u_kmh, northward_v_kmh]`.
The configured speed stays below the UAV nominal airspeed.

Forecast packets are issued at 0.5-hour intervals. Each packet contains vector
estimates on a 0.5-hour grid from its issue time through at most 1.5 hours ahead,
clipped at the mission horizon. Forecast error increases with lead time and is
newly sampled at each issue, so overlapping valid times are genuinely revised.
The direction convention is “towards”: `(u, v)` is the direction in which the
air mass moves.

## Truth and controller separation

`WindForecastPacket` is an immutable value object. `OnlineWindForecast` accepts
only packets whose `issued_at` is no later than the current time, retains the
latest received packet, interpolates only within its declared validity range,
and returns no vector beyond that range. The simulator can separately evaluate
latent truth through an explicitly named oracle helper.

The environment queues one `WIND_FORECAST_UPDATE` information event per packet.
Future packets remain in the event queue and do not enter operational state.
The new event is a decision-information type, but this milestone does not add a
new replanning policy. Existing observation-vector dimensions remain frozen;
future route-planning methods consume the typed operational forecast interface.

## Weather compatibility

Existing moving weather polygons and temporary airspace polygons are generated
and applied exactly as before. They determine geometric route state and risk.
The wind model does not change polygon timing, severity, geometry, or event
classes. Weather/mixed modes receive dynamic wind; static and airspace-only
modes retain a neutral wind specification.

## Directional energy

Legacy `flight_energy` remains unchanged. A new function computes the energy of
a directed segment using nominal ground velocity along the segment,
`v_air = v_ground - v_wind`, and multiplier
`(||v_air|| / v_uav)^2`. A safe-return helper applies the same calculation to
the outbound and return headings and adds service energy and the existing
battery reserve. Zero wind is exactly backward-compatible.

A forecast route-energy helper will reject certification if any planned segment
time falls outside the latest packet rather than extrapolating beyond the
visible forecast horizon.

## Deliverables

1. Validated wind configuration and deterministic generation.
2. Typed online forecast state with no-future-leakage behavior.
3. Environment forecast-update events.
4. Backward-compatible directional energy and safe-return primitives.
5. A canonical replayable `seed_42.json` containing exactly 20 known tasks.
6. A self-contained interactive HTML showing route availability, weather and
   airspace polygons, wind truth versus currently received forecast, forecast
   horizon, and directional battery estimates.

## Verification

Tests must demonstrate deterministic truth/forecasts, independent RNG streams,
forecast revision, horizon clipping, no early packet access, serialization/hash
round trips, zero-wind compatibility, head/tail/crosswind behavior, event-queue
revelation, exact known demand, and the 20-node canonical output. The focused
suite and relevant existing regression tests must pass before handoff.
