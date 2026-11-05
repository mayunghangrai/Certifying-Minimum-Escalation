# Packet-Disturbance Dependency Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved packet-disturbance dependency graph and its structural and material supports, expose affected legs and tasks to the intervention-scope layer, and align the active IEEE manuscript with the implemented contract.

**Architecture:** Packet comparison first returns a support-complete finite cover of coverage, interpolated-wind, weather, and airspace changes. The existing fixed-suffix diagnostic then evaluates the old and received packets, constructs an immutable typed directed acyclic graph, computes reachability without tolerance pruning, and filters the reachable vertices by type-specific materiality tolerances. The manuscript states this diagnostic separately from the later optimization over nested intervention spaces.

**Tech Stack:** Python 3, frozen dataclasses, NumPy, Shapely, pytest, IEEEtran LaTeX, MiKTeX `latexmk`.

**Spec:** `docs/superpowers/specs/2026-08-31-packet-disturbance-dependency-closure.md`

## Global Constraints

- Use only the previous packet and the newly received packet at the decision epoch; never read future packets or latent truth.
- Evaluate the same fixed remaining suffix in both projections.
- Keep direct contact and propagated pre-state change independent; a leg may have both labels.
- Compute structural reachability before applying reporting tolerances.
- Distinguish `feasible`, `infeasible`, and `undetermined` projection status.
- Do not construct routes, reorder tasks, reassign tasks, or infer a minimum escalation level from the graph.
- Preserve every unrelated change in the existing dirty checkout.
- Keep manuscript prose academic, direct, and simple; do not introduce results or superiority claims.

---

### Task 1: Support-Complete Packet Differences

**Files:**
- Modify: `src/env/environment.py`
- Test: `tests/test_environment_packets.py`

**Interfaces:**
- Consumes: `EnvironmentalPacket`, `_wind_at`, and the existing region signatures.
- Produces: `compare_environmental_packets(previous, current) -> EnvironmentalTransition` with finite `coverage` records and interval-valued `wind` records that cover the difference between the two interpolated functions.

- [ ] **Step 1: Write failing wind-support test**

Add a test in `tests/test_environment_packets.py` that compares two packets sharing the interval `[0,1]`, where the old wind is zero at both endpoints and the new wind is zero at `0` and nonzero at `1`. Assert that a revised wind record covers a positive-length interval containing `0.5`, rather than only the changed endpoint.

```python
def test_packet_comparison_covers_interpolated_wind_difference_between_samples():
    environment = _environment_module()
    previous = environment.EnvironmentalPacket(
        packet_id="old",
        issued_at_h=0.0,
        valid_from_h=0.0,
        valid_until_h=1.0,
        wind=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
    )
    current = environment.EnvironmentalPacket(
        packet_id="new",
        issued_at_h=0.0,
        valid_from_h=0.0,
        valid_until_h=1.0,
        wind=((0.0, 0.0, 0.0), (1.0, 2.0, 0.0)),
    )

    transition = environment.compare_environmental_packets(previous, current)

    wind_changes = [change for change in transition.revised if change.domain == "wind"]
    assert any(left <= 0.5 <= right and right > left for left, right in (
        change.interval for change in wind_changes
    ))
```

- [ ] **Step 2: Write failing coverage-support test**

Add a test asserting that withdrawal of the interval `(1,2]` is represented by a `coverage` record with `before=True` and `after=False`.

```python
def test_packet_comparison_reports_withdrawn_coverage():
    environment = _environment_module()
    previous = environment.EnvironmentalPacket(
        packet_id="old",
        issued_at_h=0.0,
        valid_from_h=0.0,
        valid_until_h=2.0,
        wind=((0.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
    )
    current = environment.EnvironmentalPacket(
        packet_id="new",
        issued_at_h=0.5,
        valid_from_h=0.5,
        valid_until_h=1.0,
        wind=((0.5, 0.0, 0.0), (1.0, 0.0, 0.0)),
    )

    transition = environment.compare_environmental_packets(previous, current)

    assert any(
        change.domain == "coverage"
        and change.before is True
        and change.after is False
        and change.interval[0] <= 1.5 <= change.interval[1]
        for change in transition.revised
    )
```

- [ ] **Step 3: Run the two tests and verify RED**

Run:

```powershell
python -m pytest tests/test_environment_packets.py -q
```

Expected: the new wind-support assertion fails because the old comparison emits point records, and the coverage assertion fails because no coverage records exist.

- [ ] **Step 4: Implement finite support-cover helpers**

In `src/env/environment.py`, add private helpers that partition the union of packet validity endpoints and wind knots into finite cells. Emit a revised wind change for each common-coverage cell on which the two endpoint pairs are not identical. Emit a coverage change for each cell on which packet coverage differs, classifying gained coverage as newly revealed and lost coverage as revised. Retain the existing weather and airspace comparison.

- [ ] **Step 5: Run packet tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_environment_packets.py tests/test_authoritative_generator.py -q
```

Expected: all tests pass, including the zero-revision-magnitude generator contract.

---

### Task 2: Typed Dependency Graph and Closure

**Files:**
- Modify: `src/env/diagnostics.py`
- Modify: `src/env/__init__.py`
- Test: `tests/test_decision_epoch_diagnostics.py`

**Interfaces:**
- Produces: `ProjectionStatus`, `DependencyVertex`, `DependencyEdge`, and `DisturbanceDependencyGraph` as immutable public records.
- Extends: `DisturbanceImpactClosure.dependency_graph`, `.affected_leg_ids`, and `.affected_task_ids`.
- Preserves: existing `LegProjection.feasible`, `LegImpact.directly_affected`, serialization, and aliases.

- [ ] **Step 1: Write failing three-valued-status test**

Extend the existing short-coverage test to assert:

```python
assert closure.legs[0].revised.status.value == "undetermined"
assert closure.legs[1].revised.status.value == "undetermined"
assert closure.legs[0].directly_affected is True
assert any(change.domain == "coverage" for change in closure.legs[0].direct_changes)
```

- [ ] **Step 2: Write failing graph-closure test**

For the standard wind-update fixture, assert that the returned graph has packet, environmental, evaluator, state, quantity, and status vertex types; that every seed belongs to the structural closure; that material vertices belong to the structural closure; and that the reportable set equals the union of seeds and material vertices.

```python
graph = closure.dependency_graph
assert {vertex.kind for vertex in graph.vertices} >= {
    "packet_change", "environment", "state", "evaluator", "quantity", "status"
}
assert set(graph.seed_vertex_ids) <= set(graph.structural_closure_vertex_ids)
assert set(graph.material_vertex_ids) <= set(graph.structural_closure_vertex_ids)
assert set(graph.reportable_vertex_ids) == (
    set(graph.seed_vertex_ids) | set(graph.material_vertex_ids)
)
```

- [ ] **Step 3: Write failing mixed-influence and affected-task test**

Use a wind revision whose support overlaps both legs. Assert that the second leg is both directly affected and propagated, and that `NODE-000` is returned as an affected task while `DEPOT` is excluded.

```python
second = closure.legs[1]
assert second.directly_affected is True
assert second.propagated is True
assert closure.affected_task_ids == ("NODE-000",)
```

- [ ] **Step 4: Run diagnostic tests and verify RED**

Run:

```powershell
python -m pytest tests/test_decision_epoch_diagnostics.py -q
```

Expected: failures identify the absent status property, graph records, affected-task projection, and independent propagated flag.

- [ ] **Step 5: Add immutable graph records and typed materiality**

In `src/env/diagnostics.py`:

1. Add `ProjectionStatus(str, Enum)` with `FEASIBLE`, `INFEASIBLE`, and `UNDETERMINED`.
2. Add `LegProjection.status`, mapping environmental-coverage and upstream-unknown reasons to `UNDETERMINED` while preserving `feasible` for compatibility.
3. Add frozen vertex, edge, and graph dataclasses with JSON-safe `to_dict()` methods.
4. Compare time values with `TIME_TOL_H`, energy/battery/reserve values with `ENERGY_TOL_WH`, state values with `STATE_TOL`, and categorical values exactly.

- [ ] **Step 6: Build the graph and compute supports**

Construct stable vertex identifiers for packet records and each remaining leg. Add syntactic dependency edges for entering state, composite evaluation, timing, energy, battery, reserve, deadline, aggregate status, and successor state. Add packet-contact edges for each direct change. Compute:

```python
structural = reachable_from(seed_ids, edges)
material = {
    vertex.vertex_id
    for vertex in vertices
    if vertex.vertex_id in structural
    and vertex.kind != "packet_change"
    and vertex.materially_changed
}
reportable = set(seed_ids) | material
```

Do not filter vertices during reachability.

- [ ] **Step 7: Make propagated influence independent of direct contact**

Before evaluating each leg, compare the old and revised entering departure time, battery, and payload mass with their typed tolerances. Set `propagated=True` when a noninitial leg has a material entering-state difference, regardless of whether that leg also has direct packet contact.

- [ ] **Step 8: Expose affected legs and tasks**

Derive affected legs from reportable leg-indexed vertices. Derive task identifiers from their non-depot origins and destinations. Export the four new public record types from `env.__init__`.

- [ ] **Step 9: Run diagnostic and intervention tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_decision_epoch_diagnostics.py tests/test_intervention_scope.py -q
```

Expected: all tests pass and existing APIs remain compatible.

---

### Task 3: Align the Approved Specification

**Files:**
- Modify: `docs/superpowers/specs/2026-08-31-packet-disturbance-dependency-closure.md`

**Interfaces:**
- Consumes: implemented public field names and status semantics from Task 2.
- Produces: a design record whose mathematical names and implementation correspondence match the code exactly.

- [ ] **Step 1: Update the implementation correspondence**

Record the implemented graph records, exact-before-tolerance reachability, three-valued status, independent direct/propagated flags, and affected-task projection. Keep continuous traversal and the discrete midpoint evaluator explicitly distinct.

- [ ] **Step 2: Correct the operational-change reporting definition**

Define operational material change over state, evaluator-output, quantity, and aggregate-status vertices, excluding packet and environmental-contact vertices. This preserves the distinction between a contacted soft condition and a downstream operational change.

- [ ] **Step 3: Validate mathematical formatting**

Check sequential equation tags, balanced display delimiters, balanced `aligned`/`cases` environments, and whitespace with:

```powershell
git diff --check -- docs/superpowers/specs/2026-08-31-packet-disturbance-dependency-closure.md
```

---

### Task 4: Update the Active IEEE Manuscript

**Files:**
- Modify: `D:/Post-disaster Logistics/manuscript/main.tex`
- Modify: `D:/Post-disaster Logistics/manuscript/sections/abstract.tex`
- Modify: `D:/Post-disaster Logistics/manuscript/sections/system_model.tex`

**Interfaces:**
- Consumes: the approved specification and implemented field names.
- Produces: a concise IEEE journal formulation of hierarchical disturbance propagation and the boundary to minimum-sufficient escalation.

- [ ] **Step 1: Revise title, keywords, and abstract**

Use the title `Hierarchical Disturbance Propagation for Minimum-Intervention Multi-UAV Relief Routing Under Environmental Updates`. Add `dependency closure` to the keywords. Rewrite the abstract using problem, limitation, mechanism, current evidence boundary, and implication. Do not claim numerical improvement.

- [ ] **Step 2: Replace the packet-impact diagnostic subsection**

Present, in this order: fixed suffix and two packet projections; typed graph; direct contact; exact structural seed support; reflexive-transitive closure; material and reportable supports; affected legs and tasks; and standard finite-DAG properties. Use short sentences and define every symbol before use.

- [ ] **Step 3: Correct the escalation subsection**

Define the feasibility-required level as

```latex
k_n^{F}=\min\{k:\mathcal{X}_k\cap\mathcal{F}_{n+1}\neq\varnothing\}.
```

State that the implemented checker evaluates supplied candidates and therefore returns a candidate-certified upper bound when feasible; failure of one supplied candidate does not prove that its whole intervention space is infeasible. State explicitly that the dependency closure alone does not determine `k_n^F`.

- [ ] **Step 4: Compile and inspect the active manuscript**

Run from `D:/Post-disaster Logistics/manuscript`:

```powershell
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
```

Check `main.log` for undefined control sequences, undefined references, duplicate labels, and overfull boxes. Inspect the generated PDF page count and text extraction or rendered pages before accepting the revision.

---

### Task 5: Full Verification

**Files:**
- Verify only; do not broaden the change set.

**Interfaces:**
- Consumes: all earlier tasks.
- Produces: evidence that code, mathematical contract, and active manuscript agree.

- [ ] **Step 1: Run the complete Python suite**

```powershell
python -m pytest -q
```

Expected: all collected tests pass with no errors.

- [ ] **Step 2: Run scoped whitespace and status checks**

```powershell
git diff --check -- src/env/environment.py src/env/diagnostics.py src/env/__init__.py tests/test_environment_packets.py tests/test_decision_epoch_diagnostics.py docs/superpowers/specs/2026-08-31-packet-disturbance-dependency-closure.md docs/superpowers/plans/2026-08-31-dependency-closure-implementation.md
git status --short
```

Confirm that no unrelated dirty file was modified by this work.

- [ ] **Step 3: Reconcile terminology**

Confirm that code, specification, abstract, and system model use the same terms: `packet change`, `direct contact`, `propagated pre-state`, `structural closure`, `material support`, `reportable support`, `affected task`, and `feasibility-required escalation`.
