# Airborne starts: assessment and revision plan

Date: 7 October 2026. Scope: assessment of issue 1 and the associated claim–evidence gap. No implementation or manuscript revision is included in this pass.

Audit profile: RA-L letter, English, robotics/optimization; starting-state condition tests, reproducibility and overclaimed operational scope; primary-source citation verification.

## Recommendation

Narrow the paper's operational claims immediately. A committed-current-leg extension is a defensible next step, but it is a modest extension to the evaluator and a larger extension to the current continuous minimum-level certification system. Treat those as separate deliverables.

The smallest implementation should retain the remaining current leg as a committed leading route slot. Its next-node state is a **virtual continuation origin**, not a replenishment depot. This implements the proposed abstraction while preserving the original observation epoch, route coordinates, commitments and wind-dependency graph.

The generic finite-path search can support small airborne witness demonstrations before every continuous pruning rule is generalized. Such evidence supports feasibility within a declared representation; it does not establish unrestricted-path minimum intervention. If airborne minimum certification is a central paper claim, the proof and independent replay work below is required.

## 1. What the current project actually establishes

The canonical paper is `manuscript/root.tex`. Its title already says “Certifying Minimum Intervention”; the reference search is explicitly described as verification. Nevertheless, the introduction opens with an ongoing relief mission and a mission-controller decision, whereas the continuous certified verifier and the current manuscript computational cohorts use idle depot origins. The generic evaluator already supports other observed states, including the servicing state in older benchmark fixtures.

| Claim or capability | Current evidence | Revision needed |
|---|---|---|
| Minimum intervention under the declared model | Continuous bounds, exact transfer witnesses and independent replay; the final table distinguishes minima, infeasibility and unresolved cases | Preserve this as the central claim |
| Arbitrary observed mission states in the formulation | General positions, battery, payload and execution modes are described | Distinguish formulation from implemented certification scope near the first contribution |
| Recovery from a committed in-flight leg | The schema accepts `airborne`, but no rule requires its current destination/path to remain fixed | Add explicit residual-leg semantics and constructed controls |
| Certified continuous airborne minima | `stationary_guard` rejects non-idle/non-depot origins; producer and replay pruning assume depot starts | Extend or disable the affected rules before admitting airborne certificates |
| Live mission use | Current studies are frozen forecast-conditioned problems; their timing is not an end-to-end online latency study | Keep application motivation; avoid a validated live-controller claim |

Useful anchors, relative to `D:/Post-disaster Logistics/`:

- `manuscript/sections/introduction.tex:4`: ongoing-mission framing; `:60`: reference search is verification.
- `manuscript/sections/recovery_method.tex:19`: stationary, depot-origin, uncoupled-preparation verifier; `:65`: depot-only completion bound.
- `manuscript/sections/discussion.tex:18`: airborne recovery is explicitly outside current validation.
- `manuscript/sections/mechanism_evidence.tex:6`: current protocol; `:45`: final evidence table.
- `code/src/env/fixed_plan.py:148`: all UAVs begin at the common observed epoch, with their own observed battery and payload.
- `code/src/continuous/physics.py:37`: origin support guard.
- `code/PROJECT_CONTEXT.md`: latest evidence and the distinction between generic finite search and continuous certification.

The current final table reports 128 paired missions as 45 Level 0, 82 Level 1 and one Level 3; the 31 tight controls as 22 Level 2, two Level 3, six infeasible and one unresolved. These are existing manuscript/frozen-evidence claims, not results of this assessment or airborne results.

## 2. Correct the proposed starting-state semantics

### Keep one common observed snapshot

For an airborne UAV observed at epoch t with position x, battery b and onboard quantity q, supply the remaining geometry of its current leg and its fixed next node v. Evaluate that same remaining leg under each wind projection. Its arrival state under projection omega is:

    ready time = t + residual flight duration under omega
    battery    = b - residual flight energy under omega
    payload    = q
    position   = v

Only the unflown geometry is evaluated. Executed travel, energy and deliveries are not replayed. Different UAVs can have different arrival times; do not synchronize them at the latest arrival or create a replacement global epoch.

The previous and received projections must share the original observed snapshot. Their derived arrival states may differ because of wind. Constructing two unrelated post-arrival scenarios would obscure the wind-to-time/battery dependency and invalidate the current paired diagnostic premise.

### Retain the committed first slot

Use the incumbent's first remaining path as the residual current leg and fix its S/P coordinates at every level. Preserve its slot label and count it under the original route-slot limit. A fixed task stop already forces that task's owner to remain the visiting UAV under the structural contract, even if its delivery quantity is zero; record the corresponding A commitment explicitly for clarity. Landing at that location without retaining task responsibility would need a distinct arrival-node representation. Fix delivery quantities only when they are actually committed; landing alone does not commit a particular service quantity.

The virtual origin is initially an **arrival** state. If the next node is a task, its service duration, service energy and delivery still occur exactly once. If it is the physical depot, recharge/loading occur only through the declared preparation operation. Every route still terminates at the original physical depot.

This avoids a subtle failure in a naive pseudo-depot conversion: origin delivery is zero in the current plan contract, so extracting the next task into slot 0 would otherwise skip its service and delivery.

An idle UAV at the physical depot is the zero-residual-leg case, with ready time t. Full battery is available only if already observed or after preparation; it is not a general property of an idle depot state.

### Report committed-prefix failures separately

Check residual flight admissibility, coverage, horizon and energy before tail recovery. A verified violation of an immutable prefix cannot be repaired by Levels 1–4 under that prefix policy. Report it as an immutable-prefix failure, distinct from a search failure or a tail-level exclusion. Keep the failed UAV's state/resources in the mission report.

At a non-depot endpoint, arriving above the battery reserve floor is necessary but not sufficient: a return path carrying the remaining payload must also fit the energy and horizon constraints. A failed supplied return path remains unresolved unless an all-path exclusion proves nonexistence. For an interval energy calculation, certify a below-reserve failure only when the entire possible arrival-battery interval is below the required threshold.

The initial return-witness policy also needs an explicit decision. For this limited extension, require an airborne initial witness to include the committed residual geometry followed by a return from the next node, without service or recharge. This preserves the no-diversion policy and avoids certifying safety using an immediate diversion that the nominal policy forbids. It restricts the existing auxiliary reserve domain and must be declared explicitly. Check post-service reserve separately; identify any additional pre-service landing check as a model change.

### Do not infer cargo task labels from a scalar load

The current model carries one divisible, fungible commodity. `onboard` is a scalar; it does not identify packages destined for particular tasks. Physical payload remains with its UAV, but that fact alone does not lock specific task assignments.

For the small extension, encode any operational task locks explicitly in existing commitments and retain them throughout the present certificate. Reconsider them at a later landing/update epoch. “Unlock after landing inside the same remaining plan” would require time-dependent ownership or a proved prefix/suffix rebasing convention, because the present A coordinate assigns one owner to each remaining task.

If task-labelled cargo is essential, introduce a manifest and conservation/transfer rules as a separate model extension. Landing at a relief point does not currently permit transshipment, and returned depot payload currently remains onboard. Do not assume that any landing automatically enables transfer to another UAV.

## 3. Proof and implementation work, in order

| Step | Concrete work | Main touchpoints | Acceptance condition |
|---|---|---|---|
| A. Define the residual-flight contract | Require a valid remaining path from the observed position to the fixed next stop; enforce prefix commitments; retain stock and slot accounting | `env/scenario.py`, both scenario schemas, `env/plan.py`, `env/local_scope.py` | No level changes the residual destination/geometry; onboard cargo is not charged to depot stock again |
| B. Validate the full mission | Evaluate the fixed residual leg and endpoint service under both projections; add separate immutable-prefix outcomes; enforce prefix-compatible initial reserve witnesses | `env/fixed_plan.py`, `env/wind_dependency.py`, `env/recovery_validation.py`, `recovery/transfers.py` | One observation hash; wind-dependent arrival states remain in the DAG; no skipped service, recharge or terminal return |
| C. Demonstrate small airborne repairs | Use the generic enumeration/transfer search with a declared finite path library; validate every full-fleet candidate | `recovery/enumeration.py`, `recovery/local_search.py`, `recovery/search.py`, small fixtures | Witness/exclusion scope is labelled accurately; unsupported arithmetic and failed proposals remain unresolved |
| D. Extend continuous certification if required | Add actual-origin queries and interval prefix states; generalize or conservatively disable depot-only pruning in producer and replay | `continuous/physics.py`, `continuous/search.py`, `continuous/validation.py`, `level2/search.py`, `level2/proposals.py`, `level2/bounds.py`, `level2/quantities.py`, `level2/replay.py`, `level3/search.py`, `level3/replay.py`, `level4/search.py` | No unsupported state can produce an exclusion; new witnesses and exclusions pass independent replay |
| E. Freeze new evidence and revise the paper | Save new cases, budgets, source hashes, proof versions and replay output separately; update claims only after verification | New experiment directory; active included manuscript sections | Existing experiment artifacts remain unchanged; airborne cases are reported as a separate constructed cohort |

The most important mathematical obligation is fixed-prefix equivalence: evaluating the original committed prefix plus a tail must agree with evaluating the tail from the correctly derived UAV state, while preserving endpoint operations, delivery accounting, reserve obligations and all original coordinate restrictions. This is a proof obligation, not a result established in this assessment.

The hierarchy's nesting survives if every level shares the same immutable-prefix/cargo commitments and feasible domain. The continuous-potential inequality and Farkas contradiction remain valid mathematical tools. Their start/end queries and the resource model's initial conditions must reflect the new states.

Several current concrete bounds do **not** carry over unchanged:

- `level2/bounds.py:32–43` begins at the depot and adds preparation/full recharge on the first leg. `level2/replay.py:119` reconstructs the same assumptions.
- `level2/search.py:113` generates an initial depot-only reserve and `:124` starts path queries at the depot; `level2/proposals.py:48` repeats those assumptions. Continuous witness validation also retains the origin guard. These paths need actual-origin/prefix handling, not just changes to exclusion formulas.
- `level3/search.py:107` and `:132`, with `level3/replay.py:72` and `:115`, use epoch-plus-depot travel/preparation in assignment/deadline bounds.
- The mandatory-completion bound in `recovery_method.tex:65–82` charges depot preparation and outbound travel for each delivering sortie. Already-carried supply and a nearby non-depot origin can invalidate it.
- `recovery/static_paths.py`, `recovery/represented_proofs.py` and `recovery/physical_proofs.py` also contain depot-origin assumptions. Keep their guards until their domains are separately justified.

For a first small airborne certificate implementation, disable unsupported pruning rather than silently removing its guard. Any replacement completion bound must allow delivery from initial onboard stock and replenishment from the physical depot. Use favorable time/energy interval directions for exclusions and conservative unfavorable directions for witnesses. Version the proof semantics and update independent checkers together; do not reinterpret frozen historical proofs.

## 4. Smallest useful experimental package

Keep stationary, fully covered wind and uncoupled depot preparations. This isolates the starting-state extension. Construct analytically checkable small cases rather than launching a large new benchmark.

| Package | Controlled conditions | Evidence to report | Claim it supports |
|---|---|---|---|
| Mixed-start recovery | One idle depot UAV and one or more airborne UAVs with different residual-flight lengths, batteries and positive onboard loads; one common old/new snapshot | Prefix arrival/time/energy, complete repair witness, scope and commitments; exact minimum only where smaller full domains are excluded | Recovery can be evaluated from heterogeneous committed starting states |
| Ownership restriction pair | Identical mission with an explicitly declared task commitment present/absent; retain scalar commodity semantics | Feasible scope or unresolved/infeasible outcome in each case; show whether a proposed reassignment violates the lock | Commitments constrain reassignment even when a geometric repair is attractive |
| Immutable-prefix failure | An update affects only the remaining current leg; choose a case with a provable energy/reserve or admissibility violation | Independently checked prefix violation, with no repair-level success claim | The method distinguishes unrepairable committed execution from tail replanning |

Add regression controls for zero residual flight/depot equivalence, a task endpoint's service occurring exactly once, no free recharge at a virtual origin, stock conservation, and a failed return proposal remaining unresolved. For continuous certificate support, include a loaded near-task origin that would defeat the old depot-completion bound, plus altered-prefix/ready-state/lock proofs that replay must reject.

Use the same path domains, commitments, helper allowance and solver budgets for any paired comparison. Do not target a desired measured minimum by screening out unresolved cases. If ground-truth controls are deliberately constructed for certain levels, label them as controls and prove the expected conclusion independently.

Report case identities, complete starting states, update support, finite versus continuous path domain, previous-feasibility admission, witnessed levels, excluded levels, unresolved outcomes and replay status. Keep verification controls separate from scientific sample counts. No runtime superiority or field-readiness claim follows from this package.

## 5. Manuscript revision sequence

1. **Introduction and abstract:** retain relief missions as motivation; make the tested object a forecast-conditioned certification problem. State stationary wind, depot-origin states and uncoupled preparations before presenting current experimental conclusions. The title can remain. A suitable bridging sentence is: “We study forecast-conditioned certificates for the smallest permitted intervention; the computational study uses stationary wind, idle depot origins, and uncoupled depot preparations.”
2. **Problem formulation:** distinguish a general observed state from the implemented state domain. If the extension is completed, define the fixed residual leg and arrival/service boundary, and explicitly declared ownership commitments. Remove any implication of task-labelled cargo unless that model is added.
3. **Method:** retain the three-valued outcome rule. Add the prefix-failure branch and the fixed-prefix equivalence argument. Generalize or explicitly restrict the completion bound. Widen the implementation-scope statement only to the modes actually verified.
4. **Experiments:** add a compact separate airborne-control table after verifying the new records. Keep existing final counts and cohorts unchanged. Distinguish candidate validation, finite-library minimum certificates and unrestricted-path certificates.
5. **Discussion and conclusion:** match the actual extension: committed-leg continuation under stationary supplied forecasts, if demonstrated. Retain limitations on forecast error, online latency and repeated updates. A few airborne controls do not establish a deployed live-mission tool.

Under the six-page target, keep the residual-state definition, decisive proof conditions and control table in the main paper; do not defer essential validity arguments to the internal supplement. When revisions are actually made, compile the canonical manuscript with BibTeX and inspect the rendered pages as required by its local instructions.

## 6. Diversion reference and verification status

Verified publisher record:

S. Ichoua, M. Gendreau, and J.-Y. Potvin, “Diversion Issues in Real-Time Vehicle Dispatching,” *Transportation Science*, vol. 34, no. 4, pp. 426–438, Nov. 2000, doi: 10.1287/trsc.34.4.426.12325.

[Publisher record](https://pubsonline.informs.org/doi/10.1287/trsc.34.4.426.12325), [author manuscript, Section 4.1](https://www.iro.umontreal.ca/~potvin/soumia.pdf), [author institutional record](https://commons.erau.edu/ww-leadership/2/).

The publisher abstract verifies that diversion was an additional dispatch strategy compared with a strategy without diversion. Indexed author-manuscript text in Section 4.1 discusses fixed current destinations in prior approaches. Direct author-PDF access was blocked during this assessment, so full-text verification was limited to the indexed passage. Use this as historical precedent for an explicit no-diversion assumption; it does not prove that every current dynamic-routing model uses it, or that fixing a destination necessarily fixes the complete remaining flight geometry.

This assessment read the active sources and current result reports; it did not rerun scientific experiments, prove the extension, or audit every frozen certificate. Nine targeted existing tests passed: the airborne-at-depot no-recharge/loading regression and all eight continuous-physics tests. Default pytest startup was blocked by an unrelated auto-loaded Dash plugin missing `typing_extensions`; the same tests passed with plugin auto-loading disabled. No dependency was installed.

Only this assessment document was created. Production code, manuscript sources and frozen scientific evidence were not edited.
