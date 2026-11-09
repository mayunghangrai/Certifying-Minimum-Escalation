# Decision-Epoch Disturbance Diagnostic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a non-anticipative, method-neutral diagnostic closure for received environmental-packet updates and render a controlled revision example.

**Architecture:** Add a pure `env.diagnostics` evaluator that consumes static scenario data, an immutable decision-epoch snapshot, and exactly two explicit packets. Extend snapshots with the committed route remainder, retain all route/repair/allocation decisions outside the environment, and expose a simulator convenience method that delegates to the pure evaluator. The renderer embeds a demonstration closure separately from the canonical scenario payload.

**Tech Stack:** Python 3.10-compatible dataclasses, NumPy, Shapely, the existing packet-aware `evaluate_leg` implementation, pytest, and the self-contained HTML/JavaScript renderer.

**Spec:** `docs/superpowers/specs/2026-08-30-decision-epoch-disturbance-diagnostic-design.md`

## Global Constraints

- The diagnostic consumes only static known scenario data, the supplied decision-epoch snapshot, and the two explicit packets; it never reads `scenario.environment_packets`, `scenario.wind_spec`, truth helpers, or an event queue.
- No route construction, waypoint generation, alternate path, repair, escalation, replanning, optimization, task allocation, task reassignment, or delivery selection is added.
- Baseline uses only `previous_packet`; revised uses only `received_packet`; no forecast value is extrapolated beyond a packet’s valid interval.
- Mission defaults remain `T = 12 h`, environment updates every `0.5 h`, and packet look-ahead `H = 1.5 h`.
- Directed traversal continues to use the shared `evaluate_leg` implementation and canonical units kilometres, hours, km/h, kilograms, and Wh.
- Preserve the existing dirty checkout; do not reset, checkout, stage, or commit unrelated user changes.
- Use `PYTHONDONTWRITEBYTECODE=1` and `pytest -p no:cacheprovider` for test runs.

---

### Task 1: Define the diagnostic closure records and packet visibility contract

**Files:**
- Create: `src/env/diagnostics.py`
- Create: `tests/test_decision_epoch_diagnostics.py`

**Interfaces:**
- Produces `LegProjection`, `LegImpact`, `DisturbanceImpactClosure`, `diagnose_environmental_packet_update`, and alias `diagnose_packet_update`.
- Consumes `Scenario`, `EnvironmentSnapshot`, `EnvironmentalPacket`, `EnvironmentalTransition`, and `evaluate_leg`.

- [ ] **Step 1: Write the failing visibility and serialization tests**

```python
def test_packet_update_requires_both_packets_to_be_visible_at_the_epoch():
    scenario, epoch, previous, received = make_fixture()
    future = replace_packet(received, issued_at_h=epoch.time_h + 0.1)

    with pytest.raises(ValueError, match="visible"):
        diagnose_environmental_packet_update(
            scenario, PLAN, epoch, previous, future
        )


def test_closure_serializes_to_json_compatible_values_without_future_timeline_data():
    scenario, epoch, previous, received = make_fixture()
    closure = diagnose_environmental_packet_update(
        scenario, PLAN, epoch, previous, received
    )

    payload = closure.to_dict()
    json.dumps(payload, allow_nan=False)
    assert payload["non_anticipative"] is True
    assert payload["previous_packet_id"] == previous.packet_id
    assert payload["received_packet_id"] == received.packet_id
    assert "environment_packets" not in json.dumps(payload)
    assert "truth_keyframes" not in json.dumps(payload)
```

- [ ] **Step 2: Run the focused tests and verify the feature is absent**

Run: `$env:PYTHONDONTWRITEBYTECODE='1'; python -m pytest -p no:cacheprovider tests/test_decision_epoch_diagnostics.py -q`

Expected: collection or assertion failure because `env.diagnostics` and its public API do not yet exist.

- [ ] **Step 3: Implement immutable projection and closure dataclasses**

Define `LegProjection`, `LegImpact`, and `DisturbanceImpactClosure` with the fields in the spec. Implement `to_dict()` with a recursive converter for dataclasses, tuples, NumPy scalars/arrays, mappings, and Enum values so `json.dumps(closure.to_dict(), allow_nan=False)` succeeds.

- [ ] **Step 4: Implement packet visibility validation and the empty/validated closure path**

Implement `diagnose_environmental_packet_update(...)` with the exact signature from the spec. Accept only `EnvironmentalPacket` values, validate `previous_packet.issued_at_h <= epoch.time_h`, `received_packet.issued_at_h <= epoch.time_h`, and strictly increasing issue times. When `epoch.environment_packet` is not `None`, require its ID to equal `received_packet.packet_id`. Call `compare_environmental_packets(previous_packet, received_packet)` and return a closure with deterministic IDs and summary fields.

- [ ] **Step 5: Run the focused tests and keep the first green checkpoint**

Run: `$env:PYTHONDONTWRITEBYTECODE='1'; python -m pytest -p no:cacheprovider tests/test_decision_epoch_diagnostics.py -q`

Expected: the visibility and JSON-serialization tests pass.

### Task 2: Extract remaining incumbent legs and propagate baseline/revised effects

**Files:**
- Modify: `src/env/diagnostics.py`
- Modify: `tests/test_decision_epoch_diagnostics.py`

**Interfaces:**
- Consumes the public records from Task 1 and existing scenario network/fleet/snapshot fields.
- Produces per-UAV remaining leg extraction, direct-change attribution, sequential `evaluate_leg` projections, deadline slack, reserve margins, and summary counts.

- [ ] **Step 1: Add failing tests for active remainder and direct-versus-propagated legs**

```python
def test_diagnostic_uses_committed_active_remainder_and_declared_suffix():
    scenario, epoch, previous, received = make_in_flight_fixture()

    closure = diagnose_environmental_packet_update(
        scenario, MULTI_LEG_PLAN, epoch, previous, received
    )

    assert [leg.destination for leg in closure.legs] == [
        "NODE-001", "NODE-002", "DEPOT"
    ]
    assert closure.legs[0].geometry[0] == pytest.approx(tuple(epoch.uavs[0].position))


def test_packet_revision_marks_direct_leg_and_propagates_eta_energy_deadline_effects():
    scenario, epoch, previous, received = make_three_leg_fixture()
    closure = diagnose_environmental_packet_update(
        scenario,
        MULTI_LEG_PLAN,
        epoch,
        previous,
        received,
        deadlines_h={"NODE-002": 0.25},
    )

    direct = [leg for leg in closure.legs if leg.directly_affected]
    propagated = [leg for leg in closure.legs if leg.propagated]
    assert direct
    assert propagated
    assert all(not leg.directly_affected for leg in propagated)
    assert closure.summary["directly_affected_leg_count"] == len(direct)
    assert closure.legs[-1].delta_arrival_time_h is not None
    assert closure.legs[-1].delta_energy_wh is not None
    assert closure.legs[-1].revised.deadline_slack_h == pytest.approx(
        0.25 - closure.legs[-1].revised.arrival_time_h
    )
```

- [ ] **Step 2: Run the new extraction tests and verify they fail**

Run: `$env:PYTHONDONTWRITEBYTECODE='1'; python -m pytest -p no:cacheprovider tests/test_decision_epoch_diagnostics.py -q`

Expected: failure because the closure has no remaining-leg records or projections yet.

- [ ] **Step 3: Implement plan normalization and remaining suffix extraction**

Normalize UAV keys against `scenario.fleet`, validate each declared route starts/ends at `DEPOT`, and resolve node labels without consulting environmental timelines. For a `FLYING` or interrupted UAV, use `epoch.uavs[index].committed_route` and `committed_destination` for the first remaining geometry, then use the declared route suffix and matching directed network edges. Require explicit plan geometry for a declared edge absent from the network; never synthesize an alternative route.

- [ ] **Step 4: Implement sequential packet projections**

For each UAV and each suffix leg, call `evaluate_leg` once with `previous_packet` and once with `received_packet`, using the same epoch battery/payload start. Advance each projection independently by travel time and flight energy. Apply declared service time and service energy after node arrivals, reduce payload using the declared delivery vector, compute reserve margin after service, and stop only the failed projection with an `UPSTREAM_PROPAGATION_UNKNOWN` record for later legs.

- [ ] **Step 5: Implement direct-change attribution and deltas**

Use the existing transition changes. Wind changes are global and touch a leg when their timestamp lies in its baseline or revised traversal interval. Weather/airspace changes additionally require Shapely intersection with the before/after region signature geometry and interval overlap. Set `directly_affected` from these records; set `propagated` only when the leg is not direct and a prior projection changed its timing, energy, or feasibility. Compute known ETA, travel-time, energy, and deadline-slack deltas only when both sides are known.

- [ ] **Step 6: Implement deadlines and deterministic summary fields**

Resolve deadline keys by exact label, canonical node ID, or node index; use `scenario.env_params().mission.T` for unspecified destinations. Add baseline/revised infeasible and deadline-miss counts, remaining/direct/propagated counts, total known flight-energy delta, and maximum known arrival-time delta to the closure summary.

- [ ] **Step 7: Run diagnostic tests and refactor only while green**

Run: `$env:PYTHONDONTWRITEBYTECODE='1'; python -m pytest -p no:cacheprovider tests/test_decision_epoch_diagnostics.py -q`

Expected: all diagnostic behavior tests pass, including direct-region filtering, packet coverage failures, propagation, deadlines, and JSON serialization.

### Task 3: Expose committed remainders and simulator packet-update diagnostics

**Files:**
- Modify: `src/env/simulator.py`
- Modify: `tests/test_decision_epoch_diagnostics.py`
- Modify: `tests/test_packet_route_execution.py`

**Interfaces:**
- Extends `UAVSnapshot` with `committed_route` and `committed_destination`.
- Produces `RoutingSimulator.diagnose_packet_update(incumbent_plan, deadlines_h=None)`.

- [ ] **Step 1: Write the failing snapshot and convenience-method tests**

```python
def test_packet_epoch_snapshot_exposes_only_the_committed_remainder():
    simulator, plan = interrupted_simulator_and_plan()
    epoch = simulator.advance()

    assert epoch.uavs[0].committed_route is not None
    assert epoch.uavs[0].committed_destination == 0
    assert not hasattr(epoch, "future_packets")
    assert not hasattr(epoch, "wind_truth")


def test_simulator_diagnose_packet_update_delegates_without_mutating_state():
    simulator, plan = interrupted_simulator_and_plan()
    simulator.advance()
    before = simulator.snapshot()

    closure = simulator.diagnose_packet_update(plan)

    after = simulator.snapshot()
    assert closure.received_packet_id == after.environment_packet.packet_id
    assert before.time_h == after.time_h
    assert before.uavs[0].battery == pytest.approx(after.uavs[0].battery)
```

- [ ] **Step 2: Run the simulator-focused tests and verify the missing fields fail**

Run: `$env:PYTHONDONTWRITEBYTECODE='1'; python -m pytest -p no:cacheprovider tests/test_decision_epoch_diagnostics.py tests/test_packet_route_execution.py -q`

Expected: failure because snapshots do not expose the committed remainder and the simulator has no diagnostic convenience method.

- [ ] **Step 3: Store the immediately preceding authoritative packet**

Initialize `_previous_environment_packet` to `None` in `RoutingSimulator.__init__` and `reset()`. In the authoritative packet branch of `_apply_event`, save the current packet before interruption/replacement, then publish the received packet. Do not retain or expose the future queue as part of the diagnostic input.

- [ ] **Step 4: Add read-only committed route fields to snapshots**

Add optional `committed_route` and `committed_destination` fields to `UAVSnapshot`. During `_snapshot`, mirror `active_route`/`destination` during flight and `pending_route`/`pending_destination` after interruption using `_readonly` copies.

- [ ] **Step 5: Add the simulator convenience method**

Implement `RoutingSimulator.diagnose_packet_update(...)` as a lazy import/delegation to `env.diagnostics.diagnose_environmental_packet_update`. Require a reset simulator, an immediately preceding packet, a current packet, and `_last_event_type is EventType.ENVIRONMENT_PACKET_UPDATE`; do not modify simulator state or issue a command.

- [ ] **Step 6: Run simulator and diagnostic tests**

Run: `$env:PYTHONDONTWRITEBYTECODE='1'; python -m pytest -p no:cacheprovider tests/test_decision_epoch_diagnostics.py tests/test_packet_route_execution.py tests/test_simulator.py -q`

Expected: all existing packet-interruption behavior remains green and the new snapshot/convenience contracts pass.

### Task 4: Render a controlled packet-revision closure

**Files:**
- Modify: `scripts/render_information_aware_scenario.py`
- Modify: `tests/test_canonical_visualization.py`
- Modify: `tests/test_information_aware_scenario_artifacts.py`
- Regenerate: `outputs/information_aware_seed_42.html`

**Interfaces:**
- Consumes the pure diagnostic API with an explicit demonstration plan and packet pair.
- Produces an HTML `data-role="impact-closure"` section titled “Controlled packet-revision disturbance-impact closure”.

- [ ] **Step 1: Write the failing artifact assertions**

```python
assert 'data-role="impact-closure"' in html
assert "Controlled packet-revision disturbance-impact closure" in html
assert "Directly affected legs" in html
assert "Propagated legs" in html
assert "ETA delta" in html
assert "Energy delta" in html
assert "Deadline slack" in html
```

- [ ] **Step 2: Run the renderer tests and verify the closure is absent**

Run: `$env:PYTHONDONTWRITEBYTECODE='1'; python -m pytest -p no:cacheprovider tests/test_canonical_visualization.py tests/test_information_aware_scenario_artifacts.py -q`

Expected: failure on the new closure markers while the existing canonical renderer assertions remain green.

- [ ] **Step 3: Build the explicit controlled demonstration in Python**

Add a renderer helper that selects the first canonical `DEPOT->NODE-000` edge, declares a `DEPOT -> NODE-000 -> DEPOT` incumbent with a bounded load, clones a packet pair with issue time `0.5 h`, applies a deterministic wind revision along that directed edge, and calls the pure diagnostic at `0.5 h`. Keep the demonstration closure outside `scenario.to_dict()` and do not read later scenario packets.

- [ ] **Step 4: Embed and display the closure**

Serialize the closure with `json.dumps`, add a dedicated sidebar section, and render packet IDs, transition counts, direct/propagated counts, ETA/energy/deadline deltas, and per-leg rows. Keep the page self-contained, accessible, and free of `fetch(`, truth, and forecast-error UI.

- [ ] **Step 5: Regenerate and run artifact tests**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python scripts/render_information_aware_scenario.py --input scenarios/information_aware/seed_42.json --output outputs/information_aware_seed_42.html
python -m pytest -p no:cacheprovider tests/test_canonical_visualization.py tests/test_information_aware_scenario_artifacts.py -q
```

Expected: the generated HTML contains the controlled closure and retains the canonical scenario hash and no-future-leakage checks.

### Task 5: Export the API, document the boundary, and complete verification

**Files:**
- Modify: `src/env/__init__.py`
- Modify: `README.md`
- Modify: `PROJECT_CONTEXT.md`
- Modify: `tests/test_repository_cleanup.py`
- Modify: `tests/test_method_neutral_scenario.py`

**Interfaces:**
- Public package exports include `DisturbanceImpactClosure`, `LegImpact`, `LegProjection`, `diagnose_environmental_packet_update`, and `diagnose_packet_update`.

- [ ] **Step 1: Add failing public-export and forbidden-scope assertions**

```python
def test_diagnostic_api_is_public_and_method_neutral():
    import env

    assert callable(env.diagnose_environmental_packet_update)
    assert callable(env.diagnose_packet_update)
    assert hasattr(env, "DisturbanceImpactClosure")
    source = (ROOT / "src" / "env" / "diagnostics.py").read_text(encoding="utf-8")
    assert "environment_packets" not in source
    assert "truth_keyframes" not in source
    assert "ALNS" not in source
    assert "replan" not in source.lower()
```

- [ ] **Step 2: Run export tests and observe missing exports**

Run: `$env:PYTHONDONTWRITEBYTECODE='1'; python -m pytest -p no:cacheprovider tests/test_repository_cleanup.py tests/test_method_neutral_scenario.py -q`

Expected: failure until the new module is exported and the method-neutral assertions are satisfied.

- [ ] **Step 3: Add package exports and concise boundary documentation**

Update `env.__init__`, `README.md`, and `PROJECT_CONTEXT.md` to describe the diagnostic as a read-only comparison of an incumbent suffix against two received packets, with no route decision or future packet access. Keep canonical scenario JSON unchanged.

- [ ] **Step 4: Run the complete retained test suite**

Run: `$env:PYTHONDONTWRITEBYTECODE='1'; python -m pytest -p no:cacheprovider tests -q`

Expected: zero failures with the exact collected/passed count recorded for the final report.

- [ ] **Step 5: Run static, import, artifact, and diff verification**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m compileall -q src scripts
git diff --check
python scripts/generate_information_aware_scenario.py --seed 42 --config configs/env/information_aware_routes.yaml --output scenarios/information_aware/seed_42.json
python scripts/render_information_aware_scenario.py --input scenarios/information_aware/seed_42.json --output outputs/information_aware_seed_42.html
```

Inspect the diff and confirm the canonical scenario hash is unchanged, the HTML contains the closure, no future packet/truth field is exposed, and no unrelated dirty file is staged or modified by the implementation.

- [ ] **Step 6: Re-read the spec and report requirement coverage**

Check each spec requirement against the implementation and test output before making completion claims. Report changed files, API signatures, direct/propagated semantics, full test count, and any remaining limitation honestly.
