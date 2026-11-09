# Wind recovery experiment viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Dash application that replays the frozen wind-recovery experiments with linked map, timeline, dependency graph, task closure, and search-evidence views.

**Architecture:** A small `src/visualization/` package loads the allowlisted scenario and result JSON relative to `code/`, cross-checks report hashes, and adapts the existing simulator/search records for display. Plotly builds spatial and time views, Dash Cytoscape displays the inspectable typed DAG and task/constraint graph, and a single Dash app keeps the case, time, projection, task, and search selection synchronized.

**Tech Stack:** Python 3.10+, Dash, Plotly, Dash Cytoscape, the existing Scenario, wind-diagnostic, plan-evaluation, candidate-validation, and recovery-search APIs; PNG/SVG export from the displayed plots and graph.

**Spec:** `docs/superpowers/specs/2026-09-25-wind-recovery-dashboard-design.md`

## Global Constraints

- The viewer is read-only: it reads frozen scenarios and result artifacts, does not change simulator behavior, and does not launch a new search.
- The first release is a local desktop browser tool; no server deployment, collaboration, authentication, or scenario editing is required.
- Keep the feature inside `code/`.
- Check schema/version, scenario hash, candidate hash and embedded case ID when a view combines artifacts.
- Bound file loading to the bundled experiment data; the first release has no arbitrary path upload or write action.
- Resolve scenario and result paths relative to the script, never the caller's current working directory.
- Bind by default to `127.0.0.1`; print the local address and selected data root. Do not open a public listener or upload data.
- Plotly builds maps, schedules, comparisons, and evidence charts. Dash Cytoscape provides selectable graph nodes and edges; selection updates the related detail views.
- Use the existing Python 3.10 floor. Use major-version dependency ranges checked against Python 3.10 and the current Cytoscape component API.
- Search states remain distinct: structural pruning, verified exclusion, feasible witness, unresolved arithmetic/budget, and incomplete enumeration.
- A feasible witness is not described as installed or executed. Exact minimum claims retain their fixed finite path-representation qualification.

## File Map

- Create `src/visualization/__init__.py` to expose the small public loader and a lazy app factory, keeping Dash optional when users load scenario data or figures.
- Create `src/visualization/data.py` to resolve allowlisted fixture/result paths, load immutable scenarios and saved JSON records, check IDs/hashes, and provide typed experiment bundles.
- Create `src/visualization/replay.py` to reconstruct a selected deterministic branch from its pinned path manifest and produce display evidence without running a new recovery search.
- Create `src/visualization/figures.py` to build Plotly scenario maps, wind comparisons, and UAV timelines from a bundle and explicit selection.
- Create `src/visualization/graphs.py` to adapt the source DAG and task-support sets into compact/expanded Cytoscape elements and styles.
- Create `src/visualization/app.py` to assemble the Dash layout, register selection callbacks, error states, and current-view export controls.
- Create `scripts/visualize_experiments.py` as the path-independent, loopback-only entry point.
- Create `tests/test_visualization_data.py`, `tests/test_visualization_replay.py`, `tests/test_visualization_figures.py`, `tests/test_visualization_graphs.py`, and `tests/test_visualization_app.py` for independently checked behavior.
- Modify `requirements.txt` and `environment.yml` to add the viewer runtime and verified export dependencies without removing or changing simulator constraints.
- Modify `README.md` to document installation, launching from any working directory, supported saved examples, and export behavior.

## Review Focus

- A missing, corrupt, or stale scenario/report pair must show an actionable view error and never mix data across case IDs or hashes; pin loader tests for each condition in Task 1.
- Missing, undefined, or late simulation values must remain absent/unavailable instead of appearing as zero or a completed route; pin partial-state rendering in Task 4.
- Tasks at identical coordinates must remain distinct selectable nodes without visual offsets being mistaken for simulated geometry; pin coordinate preservation in Task 4.
- A branch certificate multiplier index must resolve to the original named row and pass `verify_exclusion` before it is labeled as an exact exclusion; pin Case A's T1 deadline branch in Task 3.
- Budget exhaustion and unresolved arithmetic must never be displayed as proof of an empty intervention level; pin this distinction in Task 3.

---

### Task 1: Load and cross-check bundled experiment data

**Files:**
- Create: `src/visualization/__init__.py`
- Create: `src/visualization/data.py`
- Create: `tests/test_visualization_data.py`

**Interfaces:**
- `source_root() -> Path` returns the `code/` root from `Path(__file__).resolve()`.
- `load_case(case_id: str) -> ExperimentBundle` accepts only `four_uav_case_a` or `four_uav_case_b`; it loads the scenario, saved diagnostic/validation/search reports and paired incumbent evaluations.
- `load_diagnostic(fixture_id: str) -> DiagnosticBundle` accepts only IDs in the bundled diagnostic index and loads that fixture's scenario and saved trace without opening a search report that does not belong to it.
- `DIAGNOSTIC_IDS` contains `irrelevant_wind`, `unchanged_speed`, `downstream`, `shifted_bins`, `reserve_only`, and `late_undefined`. `BENCHMARK_IDS` contains `benign_update`, `local_delay`, and `horizon_late`.
- `ExperimentBundle` and `DiagnosticBundle` are frozen dataclasses; exposed report payloads are mappings, with scenario identity and source paths included for later figure captions.
- Reuse `env.scenario.Scenario.from_json`, `Scenario.content_hash`, and `env.fixed_plan.evaluate_pair`. Do not reimplement the wind integrator or schema checks.

- [ ] **Step 1: Write failing fixture-index and provenance checks**

```python
def test_loads_both_worked_cases_with_matching_report_hashes():
    for case_id in ("four_uav_case_a", "four_uav_case_b"):
        bundle = load_case(case_id)
        digest = bundle.scenario.content_hash()
        assert bundle.validation["scenario_hash"] == digest
        assert bundle.search["scenario_hash"] == digest


def test_loads_each_named_diagnostic_fixture():
    for fixture_id in (*DIAGNOSTIC_IDS, *BENCHMARK_IDS):
        bundle = load_diagnostic(fixture_id)
        assert bundle.diagnostic["input_hash"] == bundle.scenario.content_hash()
```

- [ ] **Step 2: Run focused loader checks and verify the two assertions fail before the loader exists**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/test_visualization_data.py`

Expected: collection/import failure for `visualization.data`.

- [ ] **Step 3: Implement path-rooted loader dataclasses and allowlists**

Map Case A/B to their files in `scenarios/worked/` and `docs/recovery_results/`. Map `BENCHMARK_IDS` to their scenario files and matching `cases[]` records in `docs/benchmark_results.json`. Map `DIAGNOSTIC_IDS` to their scenario files and matching `cases[]` records in `docs/recovery_results/diagnostic_examples.json`. Reject unknown IDs. Validate the loaded `Scenario` with the existing loader and compare report IDs, schema versions, and content hashes before returning a bundle. Obtain paired projections with `previous, received = evaluate_pair(scenario)` and retain `previous.to_dict()` and `received.to_dict()`; preserve `None` and partial state values unchanged. Cache parsed read-only artifact inputs per process so callbacks do not repeatedly parse the 1.8 MB diagnostic report.

```python
CODE_ROOT = Path(__file__).resolve().parents[2]

@lru_cache(maxsize=8)
def read_report(relative_path: str) -> Mapping[str, object]:
    path = (CODE_ROOT / relative_path).resolve()
    if CODE_ROOT not in path.parents:
        raise ValueError("report path escapes repository")
    return MappingProxyType(json.loads(path.read_text(encoding="utf-8")))
```

- [ ] **Step 4: Run focused checks for success, path independence, and artifact failure**

Add checks that every fixture ID maps to one scenario; missing, malformed, wrong-ID, and mismatched-hash artifacts raise a typed `DataLoadError` with the affected artifact named. Verify that changing the process working directory does not change `source_root()` or loaded hashes. Verify that loaded source JSON is never rewritten. Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/test_visualization_data.py`.

Expected: all cases load with their matching source identity; corrupt or mismatched pairs raise a displayable domain error, not a traceback.

### Task 2: Reconstruct evidence for a selected deterministic search branch

**Files:**
- Create: `src/visualization/replay.py`
- Create: `tests/test_visualization_replay.py`

**Interfaces:**
- `replay_branch(bundle: ExperimentBundle, level: int, branch_index: int) -> BranchReplay` returns the matching structural plan, reserve paths, stored status, named evidence, and reconstructed feasibility/witness detail.
- `BranchReplay` holds the branch hash/status, released coordinates, plan and reserve paths, named failed rows with certificate multipliers (if excluded), validated transfer plan (if feasible), and exact/unresolved qualifications.
- Reuse `release_sets`, `PathLibrary.from_dict`, `enumeration.enumerate_events`, `transfers.build_transfer_problem`, `linear.solve_linear`, `linear.verify_exclusion`, `recovery.verify_witness`, and `env.recovery_validation.validate_recovery_plan`. Never call `recover` or `search_level` from the viewer.
- Match an enumerated event to saved evidence with the search format's deterministic hash: `hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()`.

- [ ] **Step 1: Write failing branch matching and exact proof checks**

```python
def test_case_a_level3_original_assignment_names_deadline_exclusion():
    replay = replay_branch(load_case("four_uav_case_a"), 3, 0)
    assert replay.status == "EMPTY"
    assert replay.exact
    assert replay.certificate_valid
    assert "deadline:U1:1:T1" in {row.label for row in replay.exclusions}


def test_case_a_level3_exchange_replays_as_exact_witness():
    replay = replay_branch(load_case("four_uav_case_a"), 3, 1)
    assert replay.status == "WITNESS"
    assert replay.witness_validation["accepted"]
    assert replay.witness_validation["exact"]
```

- [ ] **Step 2: Run the replay checks and confirm the missing API fails before implementation**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/test_visualization_replay.py`

Expected: import failure for `visualization.replay`.

- [ ] **Step 3: Reconstruct only the selected saved branch**

Rebuild the release set for its reported level and diagnostic task set, restore the exact `PathLibrary` manifest from the search report, enumerate non-`None` structural events in report order, and verify the selected event's branch hash. For an exact `EMPTY` record, rebuild its named transfer rows and run `verify_exclusion` on the stored certificate before exposing its row labels. For a `WITNESS` record, use the level's stored witness when its path hash matches; otherwise solve only the selected exact branch and pass the result through `verify_witness` and the existing combined validator. Keep `REJECTED`, `UNRESOLVED`, and budget-limited records in their saved categories; never upgrade saved evidence.

```python
event = event_at_index(events, branch.index)
if branch_hash(event) != branch.branch_hash:
    raise ArtifactMismatch("saved branch hash does not match reconstructed event")
problem = build_transfer_problem(scenario, event, reserves)
verify_exclusion(problem.rows, branch.certificate)
```

- [ ] **Step 4: Pin ambiguity, invalid-proof, and scope-status behavior**

Check that a tampered branch hash, out-of-range index, invalid certificate, mismatched path manifest, and missing selected witness produce typed unavailable/error detail. Check that `UNRESOLVED` remains unresolved even when no feasible witness is stored. Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/test_visualization_replay.py`.

Expected: the exact Case A exclusion exposes its real deadline row, the swapped assignment remains a validated witness, and invalid/uncertain evidence is never called proven.

### Task 3: Build map, wind, and mission-time Plotly views

**Files:**
- Create: `src/visualization/figures.py`
- Create: `tests/test_visualization_figures.py`
- Modify: `requirements.txt`
- Modify: `environment.yml`

**Interfaces:**
- `make_map_figure(bundle, projection: str, mission_time_h: float, selected_uav: str | None = None) -> plotly.graph_objects.Figure` uses only scenario geometry and the selected paired evaluation.
- `make_schedule_figure(bundle, projection: str, selected_uav: str | None = None) -> plotly.graph_objects.Figure` plots the saved evaluation's known flight/service/return intervals and deadlines.
- `make_wind_figure(bundle, mission_time_h: float) -> plotly.graph_objects.Figure` plots previous/received wind vectors over their actual cells and active time bin.
- Projection values are exactly `previous` or `received`; invalid projections and out-of-horizon time fail with a readable figure-selection error.

- [ ] **Step 1: Write failing source-value and coordinate checks**

```python
def test_case_a_received_plot_uses_actual_cell_and_task_positions():
    bundle = load_case("four_uav_case_a")
    figure = make_map_figure(bundle, "received", 0.5)
    points = figure.to_dict()["data"]
    assert any("east" in str(trace.get("name", "")) for trace in points)
    assert figure.layout.xaxis.range[0] <= -1
    assert figure.layout.xaxis.range[1] >= 1


def test_unknown_arrival_is_not_plotted_as_a_zero_time_arrival():
    bundle = load_diagnostic("late_undefined")
    figure = make_schedule_figure(bundle, "received")
    assert figure.layout.meta["unavailable_values"] > 0
```

- [ ] **Step 2: Run focused figure checks and confirm the named builders are absent**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/test_visualization_figures.py`

Expected: import failure for `visualization.figures`.

- [ ] **Step 3: Add Plotly and implement consistently scaled local-coordinate and time figures**

Add a compatible Plotly 6 major-version range to `requirements.txt` and `environment.yml`, preserving the Python 3.10 floor. Draw cell polygons, depot, individually labeled tasks, selected routes, and reserves from the scenario. Do not jitter coincident tasks; make their task labels/selection distinct. Derive active-bin arrows from the scenario wind field and mission-time selection. Derive schedule marks from paired-evaluation records, preserve unknown/late records as annotations, and use separate line/style meaning for previous and received runs. Include units, legend, case ID, and evidence state in the figure metadata.

```python
fig = go.Figure()
for cell in scenario.cells:
    fig.add_trace(cell_polygon_trace(cell))
fig.update_yaxes(scaleanchor="x", scaleratio=1, title="Northing (km)")
fig.update_xaxes(title="Easting (km)")
```

- [ ] **Step 4: Verify Case A, Case B, diagnostic undefined state, and plot bounds**

Check Case A's T1 service value/deadline and west/east cell ranges against `evaluate_pair`; check Case B's four distinct task IDs remain individually accessible at shared coordinates; check wind values use the active bin; check unknown/late events remain unplotted with a labelled undefined count. Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/test_visualization_figures.py`.

Expected: coordinates and values match the simulation and stored diagnostics at all supported map selections.

### Task 4: Adapt dependency DAG and task-support graphs

**Files:**
- Create: `src/visualization/graphs.py`
- Create: `tests/test_visualization_graphs.py`

**Interfaces:**
- `dependency_elements(bundle, focus_key: str | None = None, expanded_legs: frozenset[str] = frozenset()) -> tuple[list[dict], list[dict]]` returns real Cytoscape node and edge records plus display-only aggregate nodes keyed to all underlying source IDs.
- `task_elements(bundle, selected_task: str | None = None) -> tuple[list[dict], list[dict]]` returns task nodes (`data.kind="task"`, `data.task_id`, `data.committed`) and shared-constraint nodes derived from `diagnostic.task_supports`, labelled with affected, closure, neighborhood, and commitment state.
- `node_detail(bundle, node_key: str) -> dict` returns the original node's kind, name, role, units, parents, and previous/received values without converting undefined values to zero.

- [ ] **Step 1: Write failing provenance and closure checks**

```python
def test_case_a_compact_graph_can_expand_real_wind_to_deadline_lineage():
    bundle = load_case("four_uav_case_a")
    compact_nodes, compact_edges = dependency_elements(bundle)
    full_nodes, full_edges = dependency_elements(bundle, expanded_legs=frozenset({"U1:1"}))
    assert len(full_nodes) > len(compact_nodes)
    edges = {(edge["data"]["source"], edge["data"]["target"]) for edge in full_edges}
    nodes = {node["data"]["id"] for node in full_nodes}
    assert ("change:east:0", "U1:1:nominal:wind:east:0") in edges
    assert "U1:1:deadline" in nodes


def test_committed_bridge_stays_visible_in_task_closure():
    bundle = load_diagnostic("downstream")
    nodes, _ = task_elements(bundle)
    task_ids = {node["data"]["task_id"] for node in nodes if node["data"].get("kind") == "task"}
    committed = {node["data"]["task_id"] for node in nodes
                 if node["data"].get("kind") == "task" and node["data"]["committed"]}
    assert task_ids >= set(bundle.diagnostic["task_closure"])
    assert committed
```

- [ ] **Step 2: Confirm graph checks fail before graph adapters exist**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/test_visualization_graphs.py`

Expected: import failure for `visualization.graphs`.

- [ ] **Step 3: Build source-preserving Cytoscape elements and safe summary projection**

Convert every stored graph node and parent relation without changing keys. For initial compact view, group nodes by source UAV/leg, retaining full member IDs on each aggregate. Expanding a leg reveals its actual source nodes and directed edges; node detail uses the untouched report record. Build task/constraint bipartite edges solely from nonempty stored task supports; style initial affected tasks and final closure/neighborhood separately and expose committed tasks. Do not draw inferred causal edges between tasks.

```python
elements = [
    {"data": {"id": node["key"], "label": node["label"], "kind": node["kind"]}}
    for node in report_nodes
]
elements += [
    {"data": {"source": edge["parent"], "target": edge["child"]}}
    for edge in report_edges
]
```

- [ ] **Step 4: Check all named fixtures, edge lineage, and shared coordinates**

Verify the Case A selected lineage preserves all original node IDs; the `downstream` fixture highlights propagated legs in unchanged cells; `shifted_bins` includes the active wind-bin parent; `reserve_only` marks reserve-role nodes without advancing nominal states; and `late_undefined` retains nulls. Verify task co-location does not merge node IDs. Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/test_visualization_graphs.py`.

Expected: every displayed source node and edge points to an existing diagnostic record and supported task.

### Task 5: Assemble a synchronized, local Dash application

**Files:**
- Create: `src/visualization/app.py`
- Create: `tests/test_visualization_app.py`
- Modify: `requirements.txt`
- Modify: `environment.yml`

**Interfaces:**
- `create_app() -> dash.Dash` builds the multi-view application using the fixture allowlist only.
- `selection_payload(case_id, diagnostic_id, projection, mission_time_h, selected_task, selected_leg, level, branch_index) -> dict` validates and normalizes one shared view-selection object.
- Keep public callback functions small; use direct component IDs named `case-select`, `diagnostic-select`, `projection-select`, `mission-time`, `uav-select`, `dependency-graph`, `task-graph`, `level-select`, `branch-select`, `evidence-detail`, `map-graph`, `schedule-graph`, `wind-graph`, and `export-current`.

- [ ] **Step 1: Write failing app-layout and selection-state checks**

```python
def test_layout_contains_each_linked_view_and_distinct_time_controls():
    app = create_app()
    def component_ids(component):
        if isinstance(component, list):
            return {item for child in component for item in component_ids(child)}
        if component is None or not hasattr(component, "to_plotly_json"):
            return set()
        props = component.to_plotly_json()["props"]
        found = {props["id"]} if "id" in props else set()
        return found | component_ids(props.get("children"))

    ids = component_ids(app.layout)
    assert {"map-graph", "schedule-graph", "dependency-graph", "task-graph", "evidence-detail"} <= ids
    assert {"mission-time", "level-select", "branch-select"} <= ids


def test_selection_rejects_unknown_fixture_and_preserves_case_id():
    with pytest.raises(SelectionError):
        selection_payload("../../secret", None, "received", 0, None, None, 3, 0)
```

- [ ] **Step 2: Run the focused app checks and verify the Dash dependency/API has not yet been added**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/test_visualization_app.py`

Expected: import failure for `visualization.app`.

- [ ] **Step 3: Add Dash and Dash Cytoscape, then implement layout, callbacks, and actionable load states**

Add supported Dash and Dash Cytoscape major-version ranges to `requirements.txt` and add their pip installation declarations to `environment.yml`; retain Python 3.10 and verify the component API before pinning. Create a case/fixture picker above the shared map and schedule, with a second row for the paired wind view, expandable Cytoscape DAG, task/constraint graph, five-level scope ledger, and branch detail. Wire task/node/edge selections to route highlights and evidence detail. Keep mission time and search branch as separate native controls. Display exact/witness qualifiers and missing/unresolved state in visible text. Show a component-level error when one artifact cannot load and keep unrelated fixture selection functional. Keep file readers inside Python callbacks; never expose an arbitrary user path or file-write action.

```python
@app.callback(
    Output("map-figure", "figure"),
    Output("branch-detail", "children"),
    Input("fixture-picker", "value"),
    Input("mission-time", "value"),
    Input("branch-picker", "value"),
)
def update_view(fixture_id, mission_time, branch_id):
    bundle = load_fixture(fixture_id)
    return build_map(bundle, mission_time), describe_branch(bundle, branch_id)
```

- [ ] **Step 4: Check synchronized selections, independent time controls, and readable failures**

Use Dash's layout/callback validation to confirm IDs and callback inputs/outputs exist and are unique. Exercise selecting `T1`, `U1:1`, a wind node, and Case A's two Level 3 branches; assert the same selected IDs appear in the map, schedule, graph detail, and decision pane as applicable. Check corrupt JSON produces the small labelled load error. Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/test_visualization_app.py`.

Expected: selecting a node or branch changes all connected views in that case without changing the mission-time or search-step meaning.

### Task 6: Add export controls and a path-independent loopback launcher

**Files:**
- Create: `scripts/visualize_experiments.py`
- Modify: `src/visualization/app.py`
- Modify: `requirements.txt`
- Modify: `environment.yml`
- Create: `tests/test_visualization_export.py`

**Interfaces:**
- `main(argv: list[str] | None = None) -> int` accepts an optional `--port`, binds only to `127.0.0.1`, and does not accept a file-system scenario path.
- `figure_export(figure, case_id: str, projection: str, evidence_status: str, format: str) -> bytes` exports only `png` or `svg`, embedding the current case and evidence caption.
- Cytoscape export uses its supported PNG image-generation API; Plotly export uses the pinned Kaleido renderer and does not make a network request at runtime.

- [ ] **Step 1: Write failing caption, format, and loopback-argument checks**

```python
from plotly.graph_objects import Figure, Scatter

def fig():
    return Figure(Scatter(x=[0, 1], y=[0, 1]))


def test_figure_export_caption_names_case_projection_and_proof_status():
    image = figure_export(fig(), "four_uav_case_a", "received", "exact witness", "svg")
    assert b"four_uav_case_a" in image
    assert b"received" in image
    assert b"exact witness" in image


def test_launcher_uses_only_the_loopback_host_and_rejects_unknown_arguments():
    args = parse_args([])
    assert args.port == 8050
    assert DEFAULT_HOST == "127.0.0.1"
```

- [ ] **Step 2: Confirm the new export and launcher contracts fail**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/test_visualization_export.py`

Expected: import failure for `visualization.app` or `visualize_experiments`.

- [ ] **Step 3: Add verified runtime dependencies and static-current-view export**

Add a supported Kaleido major-version range to `requirements.txt` and `environment.yml` only after its documented renderer API succeeds with the selected Plotly version in both a clean Python 3.10 environment and this workspace. Implement the export callback with the selected plot data and visible case/projection/evidence caption; offer Plotly views as PNG/SVG and Cytoscape graphs as PNG through its documented image-generation API. Put the current case ID, projection, and evidence status in the Plotly figure's visible export annotation before rendering. Reject unsupported formats and empty data with a friendly status. Confirm PNG renderer startup does not add a runtime network request before retaining Kaleido.

```python
caption = f"{case_id} | {projection} | {evidence_status}"
fig.add_annotation(text=caption, xref="paper", yref="paper", x=0, y=1.08, showarrow=False)
image_bytes = pio.to_image(fig, format=selected_format)
```

- [ ] **Step 4: Implement and exercise the command-line launcher and exported files**

Resolve all data through `source_root()`, pass only the parsed port to Dash, bind to the fixed loopback host, and return a clear dependency or start-up error rather than importing Dash from core simulator modules. Export the active Case A map, schedule, and exact proof detail as PNG/SVG, and the DAG as PNG; verify file signatures, source captions, selected data, and rejection of unknown formats. Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/test_visualization_export.py`.

Expected: launch and export produce no mutation to any scenario or frozen result artifact.

### Task 7: Document usage and verify the complete viewer against the saved experiments

**Files:**
- Modify: `README.md`
- Modify: `tests/test_visualization_app.py`
- Modify: `tests/test_visualization_data.py`

**Interfaces:**
- Documented launch from `code/`: `python .\scripts\visualize_experiments.py`. From another directory, invoke the absolute script path with appropriate shell quoting; the script derives bundled input paths from its own location.
- Record the view's supported evidence boundary: stored cases are read-only; exact search bounds concern the fixed saved path representation.

- [ ] **Step 1: Add one integration check for Case A, Case B, and all saved diagnostics**

```python
def test_all_saved_cases_keep_their_reported_scope_and_outcome_labels():
    for case_id in ("four_uav_case_a", "four_uav_case_b"):
        b = load_case(case_id)
        assert [x["level"] for x in b.search["levels"]] == [0, 1, 2, 3, 4]
        assert b.validation["status"] == "witness"
    for fixture_id in (*DIAGNOSTIC_IDS, *BENCHMARK_IDS):
        b = load_diagnostic(fixture_id)
        assert b.diagnostic["input_hash"] == b.scenario.content_hash()
```

- [ ] **Step 2: Verify saved search evidence without running the search**

Use `verify_level_evidence` for complete empty levels and `verify_witness` for each displayed exact witness. Assert Case A and B retain their saved 0/1/2 empty-level evidence, Level 3 witness, and minimum 3 scoped to the saved representation. Assert Case B labels equal Level 3/4 release spaces with their saved `equivalent_to` marker. Check that diagnostic-only fixtures do not show a search panel as if a solver report existed.

- [ ] **Step 3: Add installation, launch, cases, and figure-export documentation**

Add a focused README section with the existing environment setup, loopback address, both launch commands, fixture list, view semantics, source-hash error state, and PNG/SVG export controls. Do not change the simulator or search command examples.

```powershell
conda env update -f environment.yml
conda activate post-disaster-logistics
python .\scripts\visualize_experiments.py
```

- [ ] **Step 4: Run complete dashboard checks and existing simulation suite from a clean environment**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q`

Expected: existing simulator and recovery checks plus visualization checks pass. Start the app from a different working directory; open Case A, switch Case B, select each diagnostic fixture, expand a graph leg, step the search ledger, and export each view. Verify no browser console errors, no horizontal clipping at narrow viewport, no newly written result files, and no mismatch between the dashboard values and the saved source reports.
