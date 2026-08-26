# Information-Aware Routing Repository Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce the repository to the active information-aware routing framework and working baselines, remove the legacy polygon generator and obsolete research branches, and regenerate a clearer but operationally identical seed-42 scenario.

**Architecture:** Preserve the current environment, trajectory, ALNS, online-replanning, and rule-based baseline surfaces. Remove source and artifacts that have no retained import path, make the robust information-aware generator the sole owner of polygons, add explicit scenario provenance, and clarify forecast issue time versus valid time in the self-contained HTML.

**Tech Stack:** Python 3.10, NumPy, PyYAML, Shapely, pytest, self-contained HTML/JavaScript.

**Spec:** `docs/superpowers/specs/2026-08-26-repository-cleanup-design.md`

## Global Constraints

- Preserve all unrelated pre-existing user modifications.
- Never run `git reset --hard`, `git checkout --`, or a broad recursive delete.
- Resolve and verify every recursive deletion target under `D:/Post-disaster Logistics/code` before removal.
- Preserve `results/alns_headroom_development/`, `scenarios/information_aware/seed_42.json`, and `outputs/information_aware_seed_42.html`.
- The seed-42 operational projection hash must remain `6a1194039a6cb752ca70ed1a4e7a817b7de939f7624f54b39c8f321bebd81ade` after excluding `content_hash`, `generation_metadata`, and `params.map.generate_polygon_airspace`.
- Run tests with `PYTHONDONTWRITEBYTECODE=1` and pytest's cache provider disabled so cleanup does not recreate caches.

---

### Task 1: Lock the cleanup and scenario contracts

**Files:**
- Create: `tests/test_repository_cleanup.py`
- Modify: `tests/test_robust_scenario_generator.py`
- Modify: `tests/test_information_aware_scenario_artifacts.py`

**Interfaces:**
- Consumes: `Scenario.to_dict()`, `generate_information_aware_scenario()`, and the two scenario CLI scripts.
- Produces: regression contracts for removed legacy configuration, scenario provenance, operational projection stability, and clarified HTML labels.

- [ ] **Step 1: Add the failing provenance contract and characterize base generation**

```python
def test_base_generator_does_not_inject_route_information_polygons():
    scenario = generate_scenario(42, EnvParams())
    assert scenario.no_fly_zones == []
    assert scenario.hazard_regions == []
    assert scenario.airspace_updates == []


def test_information_aware_generation_metadata(scenario):
    assert scenario.generation_metadata == {
        "schema": "information-aware-routing-v1",
        "scenario_type": "known_tasks_dynamic_routes",
        "generator": "env.robust_scenario_generator.generate_information_aware_scenario",
        "route_information": {
            "mode": "mixed",
            "weather_episodes": 2,
            "airspace_episodes": 2,
            "wind_forecast_update_interval_h": 0.5,
            "wind_forecast_horizon_h": 1.5,
            "wind_forecast_step_h": 0.5,
        },
    }
```

- [ ] **Step 2: Add operational-projection and HTML assertions**

```python
def operational_projection(payload):
    value = copy.deepcopy(payload)
    value.pop("content_hash", None)
    value.pop("generation_metadata", None)
    value.get("params", {}).get("map", {}).pop(
        "generate_polygon_airspace", None
    )
    return value


def test_seed_42_operational_projection_is_locked():
    payload = json.loads(CANONICAL_SCENARIO.read_text(encoding="utf-8"))
    canonical = json.dumps(
        operational_projection(payload),
        sort_keys=True,
        separators=(",", ":"),
    )
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == (
        "6a1194039a6cb752ca70ed1a4e7a817b7de939f7624f54b39c8f321bebd81ade"
    )
```

Extend the artifact test to require these exact strings:

```python
assert "Latest received forecast at current valid time" in html
assert "Current-valid-time forecast" in html
assert "valid interval" in html
```

- [ ] **Step 3: Run the new contracts and verify failure**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
C:\Users\mayun\anaconda3\python.exe -m pytest -p no:cacheprovider tests/test_repository_cleanup.py tests/test_robust_scenario_generator.py tests/test_information_aware_scenario_artifacts.py -q
```

Expected: the base-generator characterization passes; failures report missing
`generation_metadata` and old HTML wording. Removal of the obsolete field is
verified by the repository-wide forbidden-reference check rather than a
source-shape unit test.

- [ ] **Step 4: Commit the contract tests**

```powershell
git add -- tests/test_repository_cleanup.py tests/test_robust_scenario_generator.py tests/test_information_aware_scenario_artifacts.py
git commit -m "test: lock focused repository contracts"
```

### Task 2: Remove legacy polygon generation and add provenance

**Files:**
- Modify: `src/env/params.py`
- Modify: `src/env/scenario_generator.py`
- Modify: `src/env/robust_scenario_generator.py`
- Modify: `src/env/scenario.py`

**Interfaces:**
- Consumes: `RouteDisruptionConfig`, `WindForecastConfig`, and the existing robust disruption generators.
- Produces: `Scenario.generation_metadata: Dict[str, object]`; robust generation remains the sole polygon owner.

- [ ] **Step 1: Remove the legacy switch and helper**

Delete `MapParams.generate_polygon_airspace`, `_oriented_rectangle()` and
`_polygon_airspace()` from `scenario_generator.py`, the conditional call in
`generate_scenario()`, and now-unused `HazardRegion`/`NoFlyZone` imports. The
base generator must always initialize these lists explicitly:

```python
no_fly_zones=[]
hazard_regions=[]
airspace_updates=[]
```

- [ ] **Step 2: Add backward-compatible scenario provenance**

Add this final dataclass field to `Scenario`:

```python
generation_metadata: Dict[str, object] = field(default_factory=dict)
```

No migration branch is needed: older JSON omits the field and receives the
default, while current JSON passes it through `Scenario.from_dict()`.

- [ ] **Step 3: Populate provenance in the robust generator**

Remove `known.map.generate_polygon_airspace = False`. Before returning the
scenario, set:

```python
scenario.generation_metadata = {
    "schema": "information-aware-routing-v1",
    "scenario_type": "known_tasks_dynamic_routes",
    "generator": (
        "env.robust_scenario_generator.generate_information_aware_scenario"
    ),
    "route_information": {
        "mode": config.mode,
        "weather_episodes": config.weather_episodes,
        "airspace_episodes": config.airspace_episodes,
        "wind_forecast_update_interval_h": (
            config.wind.forecast_update_interval_h
        ),
        "wind_forecast_horizon_h": config.wind.forecast_horizon_h,
        "wind_forecast_step_h": config.wind.forecast_step_h,
    },
}
```

- [ ] **Step 4: Run focused generator tests**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
C:\Users\mayun\anaconda3\python.exe -m pytest -p no:cacheprovider tests/test_repository_cleanup.py tests/test_robust_scenario_generator.py tests/test_scenario.py -q
```

Expected: all selected tests pass except artifact-label assertions that belong
to Task 4.

- [ ] **Step 5: Commit the generator cleanup**

```powershell
git add -- src/env/params.py src/env/scenario_generator.py src/env/robust_scenario_generator.py src/env/scenario.py tests/test_repository_cleanup.py tests/test_robust_scenario_generator.py
git commit -m "refactor: make robust generator own route polygons"
```

### Task 3: Prune rejected source, tests, configurations, and artifacts

**Files:**
- Modify: `src/agents/__init__.py`
- Modify: `tests/test_online_replanning.py`
- Rename: `configs/env/manuscript.yaml` to `configs/env/alns_headroom_environment.yaml`
- Modify: `scripts/run_alns_headroom_test.py`
- Modify: `environment.yml`
- Delete: exact paths listed below

**Interfaces:**
- Consumes: the retained imports rooted at the three scripts and retained tests.
- Produces: a repository with ALNS, online replanning, trajectories, wind,
  airspace, robust scenario generation, and rule-based baselines only.

- [ ] **Step 1: Remove source branches with no retained dependency**

Delete these exact source paths:

```text
src/agents/mappo_agent.py
src/agents/networks.py
src/methods/
src/env/audit_artifacts.py
src/env/audit_generator.py
src/env/audit_geometry.py
src/env/audit_model.py
src/env/audit_replay.py
src/env/audit_validation.py
src/env/audit_visualization.py
src/env/controlled_profiles.py
src/env/mechanism_stress.py
src/env/scenario_characterization.py
src/env/scenario_curation.py
src/env/units.py
```

Change `src/agents/__init__.py` to:

```python
"""Rule-based allocation and routing baselines."""
```

- [ ] **Step 2: Remove obsolete tests and the controlled-profile assertion**

Delete these exact tests:

```text
tests/test_adaptive_gate_diagnostics.py
tests/test_audit_scenario.py
tests/test_belief_graph_method.py
tests/test_certified_local_development_comparison.py
tests/test_certified_local_locked_benchmark.py
tests/test_critical_consistency_fixes.py
tests/test_event_causal_repair.py
tests/test_expanding_neighborhoods.py
tests/test_gate_learning_development.py
tests/test_guidance_strength_calibration.py
tests/test_guided_mappo.py
tests/test_locked_guidance_benchmark.py
tests/test_mechanism_stress_pipeline.py
tests/test_mechanism_stress_postfreeze.py
tests/test_online_replanning_benchmark.py
tests/test_seed_scene_comparison.py
tests/test_shadow_audit.py
```

Remove the `env.controlled_profiles` import and
`test_controlled_profiles_reproduce_exactly_without_seed_search()` from
`tests/test_online_replanning.py`.

- [ ] **Step 3: Remove obsolete configurations and rename the retained ALNS environment**

Delete:

```text
configs/agent/
configs/scenario/
configs/audit_policy_seed_18427.yaml
configs/prototype_seed.yaml
configs/env/corridor_disruption.yaml
configs/env/event_causal_hard.yaml
configs/env/info_obsolescence.yaml
configs/env/logistics_scenario.yaml
configs/env/mixed_info_disruption.yaml
configs/env/standard.yaml
configs/method/adaptive_causal_mix_development.yaml
configs/method/adaptive_causal_mix_selected.yaml
configs/method/certified_local_periodic_global_development.yaml
configs/method/certified_local_periodic_global_locked.yaml
configs/method/certified_local_periodic_global.yaml
configs/method/event_causal_repair.yaml
configs/method/impact_aware_anytime_development.yaml
configs/method/mechanism_stress_v2_postfreeze.yaml
configs/method/online_replanning_policy_locked.yaml
configs/method/soft_boundary_development.yaml
configs/method/soft_boundary_selected.yaml
```

Rename `configs/env/manuscript.yaml` to
`configs/env/alns_headroom_environment.yaml` without changing its values, and
update the default in `run_alns_headroom_test.py`.

- [ ] **Step 4: Remove archives and generated clutter after absolute-path validation**

Resolve each target and assert that it starts with
`D:\Post-disaster Logistics\code\` before recursive removal:

```text
scripts/Old/
.tmp_baseline_verification/
.pytest_cache/
scenarios/mechanism_validation/
outputs/scenario_verification_seed42/
results/alns_headroom_smoke/
results/debug_trajectory_seed_28/
results/certified_local_runtime_cprofile_after.prof
results/certified_local_runtime_cprofile_before.prof
all __pycache__/ directories under src/, scripts/, and tests/
Agent.md
```

Tracked deletions are recoverable from Git. The ignored debug, smoke, cache,
and profiler artifacts are intentionally removed and are not retained.

- [ ] **Step 5: Minimize dependencies**

Replace `environment.yml` with:

```yaml
name: information_aware_routing
channels:
  - conda-forge
dependencies:
  - python=3.10
  - numpy
  - pyyaml
  - shapely
  - pytest
```

- [ ] **Step 6: Verify imports and retained tests**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
C:\Users\mayun\anaconda3\python.exe -m pytest -p no:cacheprovider tests -q
rg -n -S "generate_polygon_airspace|_polygon_airspace|scripts/Old|src/methods/Old|from methods|from agents.mappo_agent" src scripts tests configs
```

Expected: retained suite passes and `rg` produces no matches.

- [ ] **Step 7: Commit the dependency-driven prune**

Stage only the exact source, test, config, environment, and deletion paths from
this task, then commit:

```powershell
git commit -m "chore: remove obsolete research branches"
```

### Task 4: Clarify the renderer and repository documentation

**Files:**
- Modify: `scripts/render_information_aware_scenario.py`
- Create: `README.md`
- Modify: `PROJECT_CONTEXT.md`
- Test: `tests/test_information_aware_scenario_artifacts.py`

**Interfaces:**
- Consumes: `Scenario.generation_metadata`, forecast packets, weather regions,
  and no-fly regions.
- Produces: clearer self-contained HTML and a concise repository entry point.

- [ ] **Step 1: Clarify forecast and metadata labels**

Use these exact user-facing strings:

```javascript
`packet issued ${packet.issued_at_h.toFixed(1)} h · valid interval ${first.toFixed(1)}–${last.toFixed(1)} h`
```

```javascript
drawArrow(
  forecast, 88, 'forecast', 'forecast-arrow',
  'Current-valid-time forecast'
);
```

```javascript
'Latest received forecast at current valid time': forecast
  ? `${speed(forecast).toFixed(1)} km/h`
  : 'none'
```

Add scenario type and separate weather/no-fly counts to the metadata chips.

- [ ] **Step 2: Add the repository README**

Document these exact commands:

```powershell
python scripts/generate_information_aware_scenario.py --seed 42 --config configs/env/information_aware_routes.yaml --output scenarios/information_aware/seed_42.json
python scripts/render_information_aware_scenario.py --input scenarios/information_aware/seed_42.json --output outputs/information_aware_seed_42.html
python scripts/run_alns_headroom_test.py --config configs/env/alns_headroom_environment.yaml --protocol configs/method/alns_headroom_test.yaml --output-dir results/alns_headroom_development
python -m pytest -p no:cacheprovider tests -q
```

The README must also state that robust generation owns all weather/no-fly
polygons and that a packet's issue time differs from its points' valid times.

- [ ] **Step 3: Add a repository-layout section to project context**

List `src/env`, `src/agents/baselines.py`, `scripts`, `configs`, `scenarios`,
`outputs`, `results/alns_headroom_development`, and `tests`, with one sentence
per entry.

- [ ] **Step 4: Run artifact tests**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
C:\Users\mayun\anaconda3\python.exe -m pytest -p no:cacheprovider tests/test_information_aware_scenario_artifacts.py tests/test_repository_cleanup.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit documentation and rendering clarity**

```powershell
git add -- README.md PROJECT_CONTEXT.md scripts/render_information_aware_scenario.py tests/test_information_aware_scenario_artifacts.py
git commit -m "docs: clarify information-aware scenario workflow"
```

### Task 5: Regenerate and verify canonical seed 42

**Files:**
- Modify: `scenarios/information_aware/seed_42.json`
- Modify: `outputs/information_aware_seed_42.html`

**Interfaces:**
- Consumes: the retained configuration, generator, scenario schema, and renderer.
- Produces: canonical JSON/HTML with one matching content hash and locked
  operational projection.

- [ ] **Step 1: Generate two independent copies**

Generate the canonical file and a temporary comparison copy with the same
seed/config, using `C:\Users\mayun\anaconda3\python.exe`.

- [ ] **Step 2: Verify byte determinism and operational projection**

Assert that both generated JSON files are byte-identical. Remove
`content_hash` and `generation_metadata`, canonicalize the remaining JSON, and
assert SHA-256 equals:

```text
6a1194039a6cb752ca70ed1a4e7a817b7de939f7624f54b39c8f321bebd81ade
```

- [ ] **Step 3: Render the canonical HTML**

Run the renderer against the regenerated JSON and verify that its printed hash
equals the JSON's `content_hash`.

- [ ] **Step 4: Run the complete retained verification suite**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
C:\Users\mayun\anaconda3\python.exe -m pytest -p no:cacheprovider tests -q
rg -n -S "generate_polygon_airspace|_polygon_airspace|scripts/Old|src/methods/Old|from methods|from agents.mappo_agent" src scripts tests configs scenarios PROJECT_CONTEXT.md README.md
git diff --check
```

Expected: tests pass, the forbidden-reference search has no matches, and Git
reports no whitespace errors.

- [ ] **Step 5: Remove temporary generation copies and caches**

Delete only the temporary comparison JSON and any cache directory recreated by
external tooling. Verify the canonical JSON, HTML, and ALNS development result
still exist.

- [ ] **Step 6: Commit canonical artifacts**

```powershell
git add -f -- scenarios/information_aware/seed_42.json outputs/information_aware_seed_42.html
git commit -m "build: regenerate canonical information-aware scenario"
```
