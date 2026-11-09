# Wind recovery experiment viewer

## Purpose

Build a local, read-only Dash application that lets a researcher replay the existing deterministic wind-recovery examples and understand how a wind update affects a plan, creates dependency reachability, expands the affected-task set, and leads to a validated recovery witness or search exclusion. It reads frozen scenarios and result artifacts; it does not change simulator behavior or launch a new search.

**Audience and assumption:** researchers inspecting examples for technical understanding and preparing presentation or paper figures. The first release is a local desktop browser tool; no server deployment, collaboration, authentication, or scenario editing is required.

## Scope and case order

1. Open the saved Case A scenario, validation report, and exhaustive reference-search report from `scenarios/worked/` and `docs/recovery_results/`.
2. Add Case B from the corresponding saved artifacts.
3. Expose the diagnostic records in `docs/recovery_results/diagnostic_examples.json`: all six diagnostic fixtures, with particular walkthroughs for downstream propagation, shifted time bins, and reserve-only impact. Keep the three original benchmark examples available as well.

The viewer displays source values and stored outcomes; it never substitutes a hand-authored example for a result. It visibly identifies unresolved or missing evidence. Case labels link to their scenario and saved report by ID and SHA-256 where available.

## User experience

Use one shared selection for case, wind projection, mission time, selected UAV/leg/task, intervention level, and search branch. Keep mission time separate from the search-step selector: the former advances physical execution and wind-bin selection; the latter moves through deterministic plan enumeration and proof evidence.

The page has a scenario map and UAV schedule, plus linked diagnostic and search views:

- The map plots the actual operational region, cells, depot, tasks, selected route and reserve geometry. Previous and received routes share the same scale. Wind arrows and strength encode the active cell and time bin.
- The schedule places flight, service, return, deadline, and battery/energy observations on mission time. Values come from the stored paired evaluations.
- The dependency view uses Cytoscape for a collapsed overview by vehicle and route leg. Expanding a leg shows its actual typed DAG nodes and edges. Selecting a node highlights related path and constraint evidence; its detail displays previous/received values, units, node kind, and parents. Graph aggregation is presentation-only and links back to source node keys.
- The affected-task view projects stored task-to-constraint supports into a bipartite graph. It distinguishes the initially affected tasks, transitive constraint closure, reassignment neighborhood, and assignments kept fixed by commitments.
- The search view lists levels 0–4 with released coordinate counts, structural branches, feasible branches, search status, and exactness. Selecting a branch shows its plan changes, return choices, checks, and original evidence. An exact infeasible branch is marked excluded with its named constraint and verifiable certificate; a structurally pruned branch, unresolved branch, failed candidate validation, feasible witness, and complete empty level have distinct labels.
- The witness view shows the original and recovered assignments, route and transfer diffs, reserve checks, mission checks, exact/numerical evidence, and the intervention-level bound. A feasible witness is not described as installed or executed.

Offer export of the selected map, timeline, graph, or decision view as a labelled figure. Include its case ID, projection, and evidence status in the export caption. Export must represent the currently selected data and preserve readable labels and units.

Use a guided case sequence as an entry point, not as a substitute for direct selection and graph inspection. All details essential to a decision must also appear without hover. Encode status with labels and marks as well as color.

## Data and application structure

Keep the feature inside `code/`. Add a small `src/visualization/` package for read-only artifact loading, figure construction, and Dash app creation, plus `scripts/visualize_experiments.py` as the project-rooted entry point. Use the existing `Scenario` loader and JSON schema for scenarios. Read the existing JSON reports rather than duplicate wind evaluation, DAG construction, scope logic, or search. Make existing evaluator/validator functions the source of any derived value that an artifact does not contain.

Check schema/version, scenario hash, candidate hash and embedded case ID when a view combines artifacts. Show a local, actionable error for missing, malformed, or mismatched files and disable only the affected view. Bound file loading to the bundled experiment data; the first release has no arbitrary path upload or write action. Importing the viewer must not import Dash from core simulator modules or change the existing command-line interfaces.

Use Plotly for maps, schedules, comparisons, and evidence charts. Use Dash Cytoscape for selectable graph nodes and edges and callbacks to synchronize the detail views. Bind app state to a small, explicit selection object. Keep diagnosis and search pure Python and reuse their current package APIs and report semantics.

## Dependencies and launch

Add Dash and Dash Cytoscape to the active `requirements.txt` and `environment.yml`; keep the existing Python 3.10 floor. Pin only compatible major ranges that have been checked against Python 3.10 and the current Cytoscape component API. Add the export dependency only if its supported rendering path is documented and succeeds in both a clean project environment and this workspace. Installation and environment changes belong to implementation, after written-spec review.

Launch using the code-rooted command `python scripts/visualize_experiments.py`. Resolve scenario and result paths relative to the script, never the caller's current directory. Bind by default to `127.0.0.1`; print the local address and selected data root. Do not open a public listener or upload data.

## Acceptance criteria

- Case A and B load from frozen inputs, and their selected validation/search reports are tied to the matching scenario hash.
- Scenario coordinates, paths, wind values, physical time, deadlines, DAG values, task supports, branch outcomes, release counts, and feasibility status match their source artifacts or existing Python APIs.
- Selecting a task, node, edge, UAV, or branch updates the related view and detail in the same case. The DAG starts compact and exposes actual provenance when expanded.
- The Case A narrative shows the changed wind delaying T1 beyond its deadline, the original assignment being excluded, and the exact Level 3 exchange being validated. Levels 0–2 exclusion evidence and the selected witness preserve the representation and proof qualifiers in the saved report.
- Case B preserves its wider reassignment neighborhood and labels the identical Level 3/4 release spaces as shared evidence.
- The six diagnostic fixtures visibly distinguish irrelevant changes, unchanged physical values, downstream propagation, shifted bins, reserve-only effects, and late/undefined checks. No unavailable value is plotted as zero.
- Each search state distinguishes structural pruning, verified exclusion, witness, unresolved arithmetic/budget, and incomplete enumeration. Failed candidate checks do not imply an empty level.
- Selected figure exports contain their source case and evidence status. Invalid or absent artifacts are reported without a traceback in the browser.
- Running the viewer from outside `code/` still locates the same pinned data. Existing simulation CLIs and outputs remain unchanged.

## Verification plan

Check loaders against the cases and all diagnostic records; compare rendered figure sources to selected saved source keys. Check that graph aggregation preserves source IDs and reachability, and that clicking real nodes/edges changes all linked selections. Check browser layout at desktop and narrow widths, light and dark themes, launch from an unrelated working directory, hash mismatch/error presentation, and selected-figure export. Run focused visualization checks and the existing simulation suite.

## Excluded from this release

Editing or generating scenarios, regenerating the frozen benchmark/search reports, starting a new solver run from the UI, installing recovery plans into a live simulator, adding learning/policy comparisons, paper statistical aggregate plots, multi-user hosting, and changes to physical/search contracts.
