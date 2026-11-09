# Ongoing-mission wind-update experiments

Date: 7 October 2026. Status: proposed design for review; implementation has not started.

## Purpose and success criterion

The user requests an experiment extension that supports the paper's ongoing-mission framing rather than retreating to a depot-start contribution. The extension must apply a local wind update after part of a feasible mission has actually been executed, retain irreversible actions, and certify the smallest sufficient intervention whenever the evidence closes the relevant scopes.

Keep the existing five-level hierarchy, continuous admissible-path domain, exact resource checking and independent replay. A finite-library or witness-only demonstration would leave the minimum-intervention claim unsupported for airborne cases.

Success consists of an implemented and tested observed-state certification profile, independently checked execution-history snapshots, decisive constructed airborne controls, a frozen fresh cohort, and a report that states witnessed levels, exclusions and unresolved outcomes accurately. Existing depot-origin studies remain historical evidence, not new samples.

This design supports one local update during mission execution under stationary, fully covered, admissible supplied wind and uncoupled depot preparation. The present paper does not claim repeated-update control, a real-time response guarantee, forecast-error robustness or field deployment; those are not additional deliverables.

All work and outputs stay inside `D:/Post-disaster Logistics/code/`. The final report will provide proposed manuscript insertions there. This experiment request does not authorize edits outside that folder.

## Selected approach

Three approaches were considered:

1. **Committed leading route slot, with observed-state continuous certification — selected.** Retain the unflown part of the current leg as the first S/P slot. The existing evaluator and exact transfer compiler already propagate its wind-dependent arrival time, energy and payload. Update the origin assumptions in proposals, bounds and replay.
2. **Extract next-node pseudo-origins.** Add per-UAV ready-time state and rebase every consumer. This requires additional interfaces and risks losing endpoint service, reserve checks and slot/commitment identity. It is unnecessary for this extension.
3. **Only add generic finite-path examples.** This is less work, but would demonstrate represented feasibility rather than the paper's continuous minimum-intervention contribution.

The selected approach does not treat the next node as a depot. It cannot provide fresh supplies or recharge unless it is the physical depot and the prescribed preparation operation completes.

## 1. Execution contract and compatibility

Add an optional v2 scenario field:

    execution_policy: "finish_current_leg"

The field governs nominal replanning. Absence retains existing input semantics; do not insert a default into stored scenarios. The legacy v1 schema and all existing scenario bytes, hashes, reports and proof versions remain unchanged.

Under the new profile:

- An airborne UAV has a nonempty first remaining path from its observed position to its existing next stop. The path is the unflown geometry, not the complete original leg. Its first S/P coordinates are committed at every level.
- A task at that fixed first stop remains owned by the visiting UAV. Require the corresponding A commitment explicitly. This also makes the existing structural ownership restriction visible in the input contract.
- Delivery quantities remain mutable according to the hierarchy unless a delivery itself is committed. A committed destination does not imply a committed positive delivery.
- Observed payload is the existing fungible divisible commodity. Do not infer package destinations or additional task locks from its scalar quantity. Existing explicitly supplied assignment commitments remain fixed throughout the query.
- Keep residual service/preparation semantics. An unfinished task service retains a leading constant incoming path, residual duration/energy/delivery and its required S/P/L commitments. A pending physical-depot preparation retains its residual origin load and duration, with its existing L commitment.
- Initial loading and recharge depend on the actual ground execution role. An airborne UAV at depot coordinates gains neither privilege.
- Every candidate is checked over the full fleet, including all outsiders. Every active route ends at the original physical depot.

The new certified origin guard admits structurally valid observed origins under this explicit policy, including the existing idle, airborne, servicing and preparing modes. It retains the current stationary-wind, full-coverage/admissibility and uncoupled-preparation conditions. Non-profile airborne inputs remain outside the new certification domain. Invalid physical state/commitment combinations are rejected as inputs, not classified as infeasible missions.

Ground residual modes are part of this milestone because a common update time can find different UAVs in different phases. They must receive the same mode-aware producer and independent-replay treatment as airborne starts; do not admit them by merely relaxing a guard.

## 2. Preserve the existing auxiliary reserve model

Keep the current initial and post-service return obligations and pre-recharge depot-arrival reserve checks. Do not add a pre-service landing reserve obligation by calling the landing state a pseudo-depot.

For a non-ground-depot origin, an initial auxiliary return witness starts at the actual observed position, at the update epoch, carrying the current observed payload and battery. An active idle/preparing physical-depot origin instead retains its existing initial check after full/residual preparation, loading and battery reset. Preserve these mode-aware rules. A return witness is not a nominal A/S/P/L plan coordinate. The `finish_current_leg` policy prevents nominal repair from changing the current leg; the separate return witness represents the existing emergency-return possibility. This distinction must be explicit in documentation and the proposed manuscript text.

A return witness is not required to follow the nominal residual leg. Requiring it to do so with the full current payload and no delivery would strengthen the present model and can reject a feasible mission that unloads at its next task. That stronger reserve policy is not introduced here.

A failed supplied curve proves no return-domain exclusion. It remains unresolved until another curve is validated or a sound all-path energy/time bound rules out every admissible return. No nominal commitment override is available inside Levels 0–4.

## 3. Generate reachable states by executing the old mission

Introduce an execution-history layer and an independently checked snapshot record. Do not populate airborne positions or remaining resources manually in the scientific cohort.

For each parent mission:

1. Generate and freeze its original observation, incumbent, commitments, operation protocol and previous wind.
2. Certify its old full-mission continuation and relevant return witnesses.
3. Select a nominal flight leg by a rule fixed before updated-wind recovery is run.
4. Execute the entire fleet under the old wind to one common update epoch within that leg.
5. Extract the physical state and remaining plan, then independently verify the extraction and its previous-wind feasibility.
6. Attach the received local wind update to that same snapshot. Both wind projections share the identical epoch state, remaining plan, commitments, deadlines and stock.

The history record contains completed flights and operations, delivered quantities, consumed depot stock, battery resets, current phase, original route slots, the cut current-leg geometry and the old-to-new remaining-coordinate map. It must bind the parent input and snapshot by hash.

### Exact history arithmetic

Use rational axis-aligned parent paths, zero old wind, speeds drawn from `{1, 2, 4}`, integer/dyadic coordinates, terminating-decimal quantities and operation durations. The continuous recovery paths after the update may have arbitrary angles; only the physical history construction is chosen for exact provenance.

Before accepting a snapshot, JSON round-trip every epoch, position, battery, load, stock, cumulative delivery and residual-operation scalar. Require the current `Fraction(str(value))` interpretation to equal the exact history value. Store exact rational strings in the provenance certificate. A nonrepresentable value is recorded as `serialization_unrepresentable`, not silently rounded into a supposedly exact state.

The verifier reconstructs exact history from the original mission. Comparing two floating evaluator records is insufficient provenance.

### Ground events and cut ownership

Use one documented right-continuous event convention. At flight arrival the vehicle enters the actual endpoint operation; delivery, loading and battery reset are credited at their prescribed completion event. Executed operations are never replayed.

The primary bank uses positive dyadic service/preparation durations and zero service energy. This makes genuine mixed ground states possible without introducing a new continuous ground-power model. Nonzero residual service energy is exercised through separate contract tests using the existing declared operation accounting.

For an in-flight cut, split the old nominal polyline at the exact reached point. Remove the flown prefix only; retain every unflown vertex and the original endpoint. At a servicing cut, retain the pending service once as a leading constant-path slot. At a preparation cut, map the pending depot load to remaining-origin L and retain only its residual duration.

### Remaining coordinates and slot capacity

Rebase completed coordinates only when constructing the new update snapshot, with a frozen mapping. Once a query starts, its coordinate labels, incumbent, commitments and release masks remain immutable throughout all levels and candidates.

Deduct retired route stops from the parent slot allowance. An unfinished current-leg/task-service slot still consumes one remaining slot. At an intermediate DEPOT arrival with preparation still pending, retire its old S/P slot at arrival and map the pending load to the new origin L:0:y; residual preparation does not occupy another visit slot. Remove commitments for already executed coordinates and record them as executed history; remap every unexecuted commitment, including transfers, to its remaining coordinate.

If the true remaining allowance is zero, the schema's minimum one storage slot is only canonical inactive padding. Commit all its S/P/L coordinates and prohibit any active restart. The history checker must reconstruct this parked representation. It must not create a fresh sortie allowance for an exhausted vehicle.

Tasks and deadlines retain their original identity and absolute mission times. Update cumulative delivery and residual stock exactly once. Remove every executed visit from the remaining route; remove an assignment entry only when its task's remaining demand is zero. Do not silently remove an unexecuted or committed future visit to such a completed task. The first parent/history contract forbids that case, and the extractor records an unsupported admission if it occurs. There is no cargo refund and no fresh full battery at the cut.

## 4. Certification changes

The existing exact transfer compiler already initializes each vehicle from its observed battery and payload, and time from the shared observation epoch. Keep that model and the whole-fleet inventory constraints. The current first leg naturally creates UAV-specific arrival states; no new global arrival epoch is needed.

### Witnesses and actual-origin proposals

Replace depot-initialized path and return proposals in `continuous/search.py`, `level2/search.py` and `level2/proposals.py` with observed-origin queries. An initial return query uses the actual observed position. Retain the committed nominal first path; only released tail paths may be optimized.

For the conservative witness model, stationary flight durations are independent of entry time. Upper duration enclosures delay operations and increase nonnegative flight energy. Fixed/residual ground durations and transfers retain their declared semantics; physical-depot resets occur only at the correct operation. Uncoupled preparations avoid schedule conflicts caused by interval shifts. Formalize this argument for every admitted origin mode, rather than relying on the depot-only proof.

### Levels 0–1

Start deadline/horizon bounds at the observed epoch. Add initial preparation only at an available depot origin, using the residual duration for preparing mode. Apply residual service duration/energy at the leading servicing slot. Fixed nominal paths use their interval lower bounds; released paths use independently verified all-path potential bounds.

The separate checker reconstructs the same mode-aware arithmetic and verifies endpoint, path release and commitment identity. It does not import the search producer or a numerical optimizer.

### Level 2

Initialize sequence-prefix resource bounds at the actual observed position and battery. Replace the blanket first-leg preparation/full-recharge assumption with the actual role and operation predicate. Use correct residual leading service/preparation and later physical-depot operations in both producer and replay.

Empty-mass flight energy remains a safe optimistic relaxation. Released geometric legs use endpoint all-path bounds, with zero as the safe unsupported-query fallback. A finite list of candidate curves does not define the admissible path domain.

The lower-duration quantity relaxation must include observed onboard stock and actual initial battery, and omit no full-fleet requirement. An exact Farkas contradiction excludes a complete skeleton; a feasible lower model alone is not a mission witness. Upper-duration constraints with exact quantities certify selected full-fleet paths.

### Levels 3–4

Preserve complete helper-patch, assignment and route-slot coverage. Disable depot-only assignment deadline and multi-sortie completion pruning unless every fleet member is idle at the physical depot. Preparing-at-depot also violates the legacy full-preparation assumption. In the first new profile, disable those two physical pruning kinds for the entire mission whenever this exact legacy origin condition fails, while retaining structural pruning and correctly generalized sequence/quantity exclusions.

This can produce more unresolved cases; it preserves sound continuous-domain certification. Introduce a new state-aware pruning rule only after proving it an optimistic relaxation and implementing its independent checker. Do not require a replacement multi-sortie bound to finish this milestone.

Keep the existing applicability guards on legacy represented/static/physical certificates. They cannot exclude airborne domains merely because another verifier now accepts airborne witnesses.

### Immutable nominal-prefix outcomes

Before tail search, independently assess the fixed residual first flight and any unavoidable leading ground operation under both projections. Record wind-dependent time/energy intervals and distinguish a verified irreversible failure from an unresolved evaluation or repair-search timeout.

Sound all-level failures include a lower arrival time beyond the horizon, a most favorable arrival battery below zero, or battery below the reserve floor when that necessarily prevents the existing depot/post-service reserve requirement. An interval crossing a threshold remains unresolved.

A first-task deadline failure excludes every level only if a positive delivery is fixed there or the locked owner must complete positive mandatory remaining demand and no later visit can precede the already-late first completion. Do not promote an optional mutable first-slot delivery failure to global infeasibility.

For a prefix failure, retain a separately labelled proof and reason even if the resulting minimum-level interval is reported as infinity. Never drop the UAV or its payload/resources from the mission.

## 5. Independent replay and proof versions

Preserve v1 report and proof interpretations, with their original origin guard and arithmetic. New origin-aware witness, prefix, sequence and assignment records receive new versions and bind the execution policy. Keep existing spatial-potential/path certificates unchanged where their semantics remain unchanged.

Add an optimizer-free `continuous/replay.py` for new Level-0/1 records. It may share trusted scope, rational physics and transfer primitives, but not producer/proposal/bound orchestration. Level-2/3/4 replay independently reconstructs new origin/operation rules and rejects legacy depot-completion proofs applied to non-depot domains.

The new history checker similarly reconstructs the exact cut, stock/delivery accounting, residual geometry, remaining slots and commitments. It must not trust a supplied ready time, battery or mapping merely because the outer record hash was recomputed.

## 6. Experiment protocol

### Constructed validation controls

Build eight physically sourced controls: certified outcomes spanning Levels 0–4, an unavoidable committed-prefix failure, a failed-but-replaceable auxiliary return proposal, and heterogeneous arrival states. Controls should exercise loaded direct service and a tempting commitment violation. Independently derive their expected conclusions; do not use an expected label as certificate evidence.

Use additional tests for mixed residual service/preparation, no free recharge at depot coordinates, full-fleet stock conflicts, zero-change old/suffix execution equivalence, threshold-overlapping intervals and deliberately exhausted budgets. Altered evidence rejection is a test, not a new scientific sample.

### Fresh primary cohort

Use the existing study's four size classes `(tasks, UAVs) = (3,3), (6,3), (12,4), (24,6)`, two layouts (uniform and clustered), and two fresh seeds per class/layout. This gives **16 independent parent missions**.

Each parent nominates a still-loaded flight leg after at least one completed positive delivery. Prefer an outbound/inter-task leg; do not mix return-only cuts into this cohort. Set that rule and a generation-attempt cap before inspecting received-wind recovery outcomes.

Cut the nominated leg at **25%, 50% and 75%** of its old flight duration. For each of the **48 snapshots**, attempt two local updates with wind magnitude **0.2 and 0.6 times the minimum fleet airspeed**. Freeze the adverse direction/cell choice by a deterministic geometry rule before solving recovery. The intended bank therefore contains **96 attempted update cases**, with all unsuccessful generation/admission slots retained.

Parent deadlines, quantities, resource margins and commitments are fixed using the previous-feasible history before applying the new wind. Do not derive cohort deadlines from new recovery results or select cases for a desired minimum level. A certified absence of effect is a valid retention case.

Admission requires an independently certified parent/history and previous-feasible snapshot, a genuine nominated airborne state with remaining supply/demand, exactly represented state, and the declared local/full-coverage wind contract. Record every capped generation attempt, invalid/unrepresentable cut and unverified prior premise. A failed admission is not a replacement opportunity outside the frozen cap.

Pilot controls and one small history before freezing the primary configuration. The primary runner uses a shared per-case 60-second soft repair/proof-construction budget and 100,000 processed tree-node ceiling across Levels 0–4. Use 18-digit outward flight intervals and the existing oracle refinements `(2,4)`. Replay has its own measured cost. Record budget overruns from atomic solver calls and distinguish them from a hard real-time guarantee.

Use fresh parent seeds 81001 and 81002 for each size/layout. Set exact generation/resource rules in the implementation plan before freezing. If a configuration change is needed after the pilot, create a new run version, preserving the old pilot and its failures.

The 96 variants are paired observations from 16 histories, not 96 independent missions. Report attempted slots, admitted snapshots/cases, and certified/unresolved recovery outcomes among admitted cases separately. Admission failures are not recovery-level outcomes. Report results descriptively by parent, progress and strength. No recovery-level quotas or unconditional field recovery-rate inference.

## 7. Evidence and report

Store parent inputs, history cuts, snapshot maps/scenarios, previous-premise evidence, diagnostics, returned paths/quantities, prefix proofs, search trees, independent replay results, configuration, environment and source archives with hashes in a new result directory. No existing frozen artifact is overwritten.

Report:

- Actual state composition, completed-delivery fraction and remaining battery/payload at each update.
- Old/new residual current-leg duration and energy, affected UAV count and immutable coordinates.
- Witnessed level, excluded levels, certified minimum or interval, immutable-prefix failure and unresolved reason.
- Deadline, battery/reserve and stock margins, together with whole-fleet preservation checks.
- Measured diagnosis, path generation, search/proof construction, history verification and independent replay times.

The report provides a claim–evidence table: ongoing observed-state recovery, unchanged commitments/outside plans, whole-mission acceptability and minimum intervention. An airborne minimum needs a witness plus every lower-scope exclusion; a global-reassignment control needs complete Level-3 helper-family exclusion and a Level-4 witness.

Prepare proposed paper insertions under `code/docs/`: policy/observed-state definition, the conditional prefix/state accounting and conservative-witness arguments, updated verifier support, experiment protocol/table and evidence-backed conclusions. Essential proof conditions should be suitable for inclusion in the main six-page paper.

## 8. Implementation boundaries and verification

Suggested new modules are `ongoing_mission/history.py`, `ongoing_mission/snapshot.py`, `ongoing_mission/replay.py`, and `ongoing_benchmark/` for cases/records/runner/report. These separate physical history, snapshot construction, independent provenance and scientific execution. Keep mode-aware certification changes within the existing continuous and Level-2/3/4 modules.

Implement in dependency order: explicit input policy; observed-state and history contracts; witness/Level-0/1 certificates and replay; Level-2 sequence/quantity bounds and replay; Level-3/4 coverage and pruning applicability; constructed controls; pilot; frozen primary study; source-bound report.

Meaningful verification must cover:

1. Legacy no-policy scenarios/proofs and the existing airborne-at-depot evaluator regression.
2. Required residual S/P/task-A locks, changed first paths and missing/malformed policy fields.
3. Exact cut/old-tail equivalence, stock/cargo/battery conservation, completed delivery and retired-slot accounting.
4. Mixed UAV phases at one epoch, residual ground operations and endpoint service occurring once.
5. Origin-sensitive lower bounds, a loaded near-task counterexample to the old depot-completion rule, full-fleet quantity checking and auxiliary return replacement.
6. Complete tiny assignment/sequence/helper coverage and independently certified airborne minima.
7. Prefix failures, overlapping intervals, optional deliveries, open frontiers and budget exhaustion.
8. Forged observed resources, coordinate maps, source hashes, prefix geometry, commitments, legacy proof arithmetic and omitted coverage rejected by independent replay.

Run focused tests during implementation and the complete current test suite before freezing experiments. Audit old frozen inputs/records for unchanged bytes. New-control failures require diagnosis; cohort unresolved outcomes remain scientific results and are not converted to exclusions.

## Review decision

This specification chooses a continuous-certification extension, physically executed mission histories, the finish-current-leg nominal policy, preserved auxiliary emergency-return semantics, mixed residual ground-state support, eight controls and 96 attempted cohort cases. It is ready for design review; numerical outcomes and completed implementation are not claimed.
