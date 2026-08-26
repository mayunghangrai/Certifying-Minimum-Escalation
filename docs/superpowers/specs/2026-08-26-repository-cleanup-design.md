# Information-Aware Routing Repository Cleanup Design

## Objective

Turn the repository into a focused research codebase for online
information-aware multi-UAV routing under weather, airspace, and wind
uncertainty. Preserve working allocation and routing baselines, the current
simulation stack, the canonical seed-42 scenario, and reproducible evidence
that is directly relevant to this project. Remove archived, rejected,
duplicate, generated, and legacy material that does not support that scope.

## Scope boundary

The cleanup is dependency-driven and behavior-preserving. It will not redesign
the event-driven simulator or remove generic state required by the retained
ALNS, trajectory, and online-replanning baselines. A deeper simplification of
the simulator's historical partial-observability model is a separate research
refactor because it could change numerical behavior and baseline comparability.

Existing user edits outside the files listed in this design remain untouched.
The cleanup must never use a broad Git reset or checkout.

## Retained project surface

The cleaned repository retains:

- Environment primitives required by scenario generation, replay, route
  availability, wind forecasts, battery energy, waypoint trajectories,
  deprivation accounting, ALNS, and online replanning.
- `src/agents/baselines.py` as the rule-based comparison surface.
- `scripts/generate_information_aware_scenario.py`,
  `scripts/render_information_aware_scenario.py`, and
  `scripts/run_alns_headroom_test.py`.
- `configs/env/information_aware_routes.yaml`, the environment profile used by
  the ALNS headroom runner, and `configs/method/alns_headroom_test.yaml`.
- `scenarios/information_aware/seed_42.json` and
  `outputs/information_aware_seed_42.html`.
- The non-smoke ALNS headroom development result because it records the
  predeclared negative headroom finding that motivated the current direction.
- Tests that exercise retained modules and current scientific contracts.
- `PROJECT_CONTEXT.md`, the current scenario design and implementation plan,
  and a new concise repository `README.md`.

## Removed project surface

The cleanup removes these categories after verifying that no retained entry
point imports them:

1. Archives and caches:
   - `scripts/Old/`
   - `src/methods/Old/`
   - `.tmp_baseline_verification/`
   - `.pytest_cache/`
   - every `__pycache__/` directory

2. Rejected algorithm branches:
   - MAPPO network and agent implementations that have no retained runner
   - belief-graph guidance, adaptive-gate, gate-learning, and event-causal
     repair method modules
   - their agent/method configurations and tests

3. Superseded scenario and audit branches:
   - audit-scenario generation, replay, validation, and visualization modules
   - controlled/mechanism-stress generation, characterization, and curation
     modules
   - their configurations, frozen scenarios, tests, and noncanonical outputs

4. Generated or historical artifacts:
   - smoke headroom output
   - trajectory-debug output
   - runtime profiler files
   - the superseded `outputs/scenario_verification_seed42/` demonstrator

5. Duplicate documentation and dependencies:
   - duplicate `Agent.md` while retaining `CLAUDE.md`
   - dependencies used only by removed MAPPO, plotting, audit, or stress code,
     including PyTorch, Stable-Baselines3, notebook tooling, and CUDA packages

## Legacy polygon generation removal

`MapParams.generate_polygon_airspace` and the base generator's
`_polygon_airspace()` path are removed. The information-aware generator will
no longer disable a legacy switch. It will remain the only component that
constructs route-information polygons:

- `_weather_disruptions()` owns weather hazard polygons.
- `_airspace_disruptions()` owns temporary no-fly polygons.
- `RouteDisruptionConfig.mode`, `weather_episodes`, and `airspace_episodes`
  are the authoritative generation controls.

Any guards or configuration keys whose only purpose was to prevent the legacy
generator from running are removed with it.

## Canonical scenario clarity

The seed-42 JSON receives explicit, serialized generation provenance:

- schema identifier
- scenario type (`known_tasks_dynamic_routes`)
- generator identifier
- route-information mode
- weather and airspace episode counts
- wind forecast issue interval, valid horizon, and valid-time step

The provenance is descriptive; the explicit nodes, regions, update events,
wind truth, and forecast packets remain the executable scenario state.

Regeneration uses seed `42` and
`configs/env/information_aware_routes.yaml`. The new scenario must preserve the
old operational projection exactly: depot, nodes, inventory, UAV and mission
parameters, weather/no-fly geometry, update timeline, wind truth, and forecast
packet values. The expected differences are removal of the legacy parameter,
addition of provenance, and the resulting content-hash change.

## Visualization clarity

The regenerated HTML will distinguish packet receipt from forecast valid time:

- `Latest received forecast at current valid time` replaces `Received wind`.
- The arrow label states that it is the current-valid-time slice of the latest
  issued packet.
- The horizon label shows packet issue time and valid interval.
- Weather hazards and temporary no-fly restrictions retain distinct labels.
- Scenario type, seed, content hash, and region counts appear in the metadata.

The renderer remains a self-contained HTML generator with no network fetches.

## Dependency and documentation cleanup

`environment.yml` will contain only packages imported by retained source,
scripts, and tests. A top-level `README.md` will describe:

- the research question and exclusions
- the retained directory layout
- how to generate seed 42
- how to render the HTML
- how to run the ALNS headroom baseline
- how to run the retained test suite
- which component owns weather, airspace, and wind generation

## Verification contract

Cleanup is complete only when all of the following hold:

1. A repository-wide search finds no reference to
   `generate_polygon_airspace`, `_polygon_airspace`, `scripts/Old`, or
   `src/methods/Old` in retained project files.
2. Every retained Python module imports successfully.
3. The retained tests pass under the documented environment.
4. Seed 42 regenerates twice to byte-identical JSON with one content hash.
5. The pre-cleanup and post-cleanup operational projections are equal after
   excluding the intentionally changed provenance, removed legacy parameter,
   and content hash.
6. The regenerated HTML is self-contained, embeds the new scenario hash, and
   contains the clarified forecast labels.
7. No unrelated pre-existing user modification is included in cleanup edits.

## Deletion safety

Before recursive deletion, each target is resolved to an absolute path and
verified to be inside `D:/Post-disaster Logistics/code`. Only the exact paths
listed in the implementation plan may be deleted. Tracked material remains
recoverable through Git; current canonical scenario and relevant headroom
evidence are preserved explicitly.
