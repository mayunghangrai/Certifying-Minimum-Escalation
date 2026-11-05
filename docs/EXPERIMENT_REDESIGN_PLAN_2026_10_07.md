# Experiment redesign and in-flight extension: plan

Date: 7 October 2026. Status: **proposal, not frozen**. Nothing described here has been run. This plan accompanies `AIRBORNE_START_REVISION_PLAN_2026_10_07.md`, which remains unchanged; where the two differ (Section 5.2, D1 and D2), this plan says so.

## Summary

1. Keep the frozen evidence: 10 controls, the analytic cascade, 128 paired cases and the 62-case cohort. Present the tight/loose cohort as a stress test, not as primary evidence.
2. New primary study **P1** at t = 0: a fixed fleet of four UAVs, 1–3 tasks per UAV, deadlines on every task set before the update, and pre-update slack crossed with wind strength inside each mission. It estimates when and how often each level is required, with confidence intervals, and brackets each mission's escalation thresholds.
3. Comparators **C1–C3** and a runtime profile **R1** reuse the P1 variants; no new missions.
4. Update-time extension **E1**: the same mission and update, arriving at τ/4 and τ/2 during execution. It starts only after the continuous verifier accepts in-flight starts. No closed-loop multi-update simulation in this paper.
5. P1, comparators and R1 fit in one overnight run on six worker processes even if every run hits its cap; E1 needs a second night.

Decisions to confirm before implementation: in-flight leg geometry (D1), initial reserve witness (D2), handling of ground operations at the snapshot time (D3), whether energy may bind (Section 2.7), and the pilot thresholds in Section 7.

## 1. Why the current cohort cannot be the primary evidence

Recomputed on 7 October 2026 from the frozen records under `results/continuous_paths_2026_10_05/primary/` and the follow-up reports of 5–6 October:

- All 200 certified cases have `epoch_h = 0`, zero cumulative deliveries and every UAV idle at the depot. Every tested update arrives before take-off; `continuous/physics.py::stationary_guard` rejects any other start.
- Every paired and cohort case uses wind speed 3/5 along a coordinate axis. Wind strength was never varied outside the controls, and no certified record uses a diagonal wind.
- `continuous_benchmark/cases.py::boundary_pair` places the tight deadline below the certified Level-1 bound, so "all 31 tight cases exclude Levels 0–1" holds by construction.
- In the cohort only the critical task has a deadline, so serving it earlier costs nothing elsewhere.
- In the 3-task/3-UAV class each UAV owns exactly one task (round-robin assignment in `final_benchmark/generators.py::random_pair`). There is nothing to resequence, and Level 2 fails at the root.

| Final tight-case outcome | Level 2 | Level 3 | Infeasible | Unresolved |
|---|---:|---:|---:|---:|
| 3 tasks / 3 UAVs (8 cases) | 0 | 2 | 5 | 1 |
| 6, 12 or 24 tasks (23 cases) | 22 | 0 | 1 | 0 |

- In 4 of the 6 infeasible cases, the UAV owning the late task was already the fastest in the fleet. Both Level-3 cases had a faster helper.
- |U0| = 1 in 50/62 cohort cases and 96/128 paired cases, so Level 3 versus Level 4 is rarely exercised.
- Battery capacity comes from `final_benchmark/near_boundary.py::_resource_reference(q, before, after, [.05, .2, .5][seed % 3])`. The slack is tied to the seed (61001 and 61004 both receive 0.5), and `after` evaluates the post-update Level-1 reference plan, so resources are conditioned on the update.
- The size ladder (3,3), (6,3), (12,4), (24,6) changes task count, fleet size and tasks per UAV together.

Consequence: the counts describe the generator. They cannot say when or how often escalation is required, which matches the manuscript's own statement that the counts are descriptive.

## 2. Primary study P1: paired dose–response at t = 0

### 2.1 Questions

- **Q1.** How does the certified minimum level depend on pre-update deadline slack, wind strength and tasks per UAV?
- **Q2.** How much deadline tightening does each level absorb, and how often is there a band in which only Level 4 suffices?
- **Q3.** How often does a stronger wind need *less* intervention?

### 2.2 Base missions

| Item | Specification |
|---|---|
| Fleet | m = 4. Airspeeds from the existing set {1, 1.275, 1.56}, shuffled and cycled as in `boundary_pair`; record each UAV's speed rank |
| Tasks | n ∈ {4, 8, 12}, i.e. 1, 2 or 3 tasks per UAV. Uniform and clustered layouts, demands, payload capacities, stock and slot bound 2⌈n/m⌉+3 as in `random_pair` |
| Incumbent | Round-robin and nearest-neighbour sequences; straight zero-wind legs (`make_plan`); zero previous wind; one stationary time bin; non-binding horizon |
| Deadlines | Every task with a positive incumbent delivery: `d_i(s) = _decimal(u_i + s·τ, True)`, where `u_i` is the certified upper previous delivery time (intervals from `stationary_duration`, as in `cases._deliveries`) and `τ = max_i u_i` |
| Battery | Set from the previous forecast only (as `final_benchmark/generators.py::_capacity_reference`). One declared slack for all missions, chosen in the pilot so that energy is non-binding at Levels 0–1 (reason in Section 2.7) |
| Count | 20 missions per (n, family), 120 base missions. Pilot seeds 71001–71002 and primary seeds 72001–72020 per cell; no overlap with earlier studies |

### 2.3 Wind update, shared by every variant of a mission

- **Cell:** uniform over the cells of the 4×4 grid queried by the incumbent's nominal legs under the previous evaluation. This conditions only on pre-update exposure.
- **Direction:** uniform over 12 rational unit vectors: (±1, 0), (0, ±1), (±3/5, ±4/5), (±4/5, ±3/5). Rational components keep the potential and interval checks exact.
- **Strength:** r ∈ {1/5, 2/5, 3/5} and w = r · v_min · direction, so |w| ≤ 3/5, below every airspeed (`speed_bound_kmh` = 0.6).
- **Admission:** the previous premise is certified for every variant, and 1 ≤ |U0| ≤ m/2. U0 is structural; assert that it is identical across the 15 variants. Allow at most 24 draws, with new geometry every 12 as in `boundary_pair`. Log every attempt. Keep failed slots and do not replace them. Never use a recovery label.
- Diagonal winds are new to the certified runs. First add one analytic control with uniform diagonal wind, checked against `(sqrt((w·d)^2 + A·|d|^2) - w·d) / A` with `A = v^2 - |w|^2`.

### 2.4 Variants and certification ladder

Within each mission, cross slack s ∈ {2/5, 1/5, 1/10, 1/20, 1/50} with the three strengths: 15 variants per mission, 1,800 in total. Each variant runs the ladder until its minimum is certified or the caps are reached:

1. `continuous.search.recover_continuous`: Level 0–1 screens and deadline exclusions, bounded Level 2–4 proposals and physical certificates.
2. `level2.search.search_level2`, if Level 2 is neither excluded nor witnessed.
3. `level3.search.search_level3`, if Level 2 is excluded and no witness at Level 3 or below exists.
4. `level4.search.search_level4`, if Level 3 is excluded and no witness exists.

Reuse evidence along the slack axis only, where the wind tables are identical:

- **Path seeds.** Pass the verified queries of earlier variants (`result['paths']` and Level-2 `leg_bounds`) as `initial_bounds`.
  - Pre-filter them with `continuous.oracle.verify_query`, because `level3/cache.py` raises on an invalid seed.
  - `recover_continuous` needs a small `initial_bounds` argument that verifies seeds and preloads `ContinuousOracle.cache`.
  - Do not share seeds across strengths. Potential certificates are verified over the whole mesh, including the changed cell.
- **Monotone transfer.** Tightening deadlines removes plans and leaves U0 and the release spaces unchanged (nested degradation; U0 is asserted per variant). An exclusion at slack s therefore holds at every tighter slack, and a witness at s is feasible at every looser slack.
  - Witnesses: re-validate with `continuous.validation.certify_witness` on the looser variant.
  - Exclusions: store a `monotone_transfer_v1` item. It binds the source record hash and checks four conditions. First, the scenarios must be identical once `benchmark_id` and task `deadline_h` are cleared, as `continuous_benchmark/cli.py::_audit_sampling` normalizes them. Second, every target deadline must be at most its source deadline. Third, U0 must be identical. Fourth, the source exclusion must replay. Add this check to the replay audit.
- **Order.** Within each strength, process slacks from loosest to tightest and carry exclusions forward. Re-validate any later witness on looser variants that are still unresolved.
- **Assertion.** Within a mission and strength, the certified level must not increase as slack increases. A violation is a defect to investigate, not a finding.

### 2.5 Budgets and measurements

- **Stopping rules.** Deterministic limits bind: 120 proposals, 100,000 nodes per level search, and the existing limits on rational operations and rows. Wall time is a backstop: 30 s per variant across the ladder in pass 1, with fixed per-stage caps. A pre-declared pass 2 gives 120 s to variants still unresolved. Record which limit stopped each stage.
- **Measurements.** Record CPU time (`time.process_time`) and wall time per stage. Also record work counters: oracle queries, conic paths, potential fields, nodes, and primal and Farkas proofs.
- **Event log.** Write one entry at every bound change: stage, level, witness or exclusion, wall and CPU timestamps, and node count. Touchpoints are `accept()` and `exclude()` in `continuous/search.py`, plus the result points of the Level 2–4 searches.

### 2.6 Analysis

- **Per-variant record:**
  - the certified level, or [lower, upper];
  - the evidence source of each bound: search, transfer or admission;
  - |U0| and the headwind component on exposed legs;
  - the speed rank of each affected UAV;
  - witness changes from `env.local_scope.change_metrics`;
  - timings and work counters.
- **Figure:** share of missions at each certified level against slack, in panels by strength and tasks per UAV, with unresolved cases as their own band.
- **Inference:** base missions are the unit.
  - Use the cluster bootstrap already in `final_benchmark/analysis.py::summarize`, which resamples whole missions; draw 2,000 resamples.
  - Report identification intervals for unresolved labels, as in the 30 September report.
  - At one (s, r), expected precision is about ±15 percentage points per tasks-per-UAV level (40 missions) and ±9 pooled (120).
  - Pool families unless the pilot shows a large difference.
- **Escalation bands (Q2):** the grid brackets each mission's thresholds s_k* between adjacent slack values.
  - Report the slack absorbed by each level, in units of τ.
  - Report the share of missions with a non-empty band where only Level 4 suffices.
  - A witness's own minimum deadline margin tightens the upper bracket at no cost. Optionally, run two bisection steps between grid points on a 30-mission subset.
- **Q3:** count mission and slack pairs whose certified level falls as strength rises.

### 2.7 Energy as a driver (optional)

At Levels 0–1, continuous exclusions cover only deadline and horizon (`deadline_certificate`), so energy-limited variants would stay unresolved there. That is why P1 keeps the battery non-binding.

To add energy, extend `deadline_certificate` and its verifier with an energy/reserve rule:

- Quantities are fixed at Levels 0–1, so each leg's payload is known and γ(m⁰ + m·q)·v·τ_lower is an exact optimistic energy.
- Mirror the battery and reserve rules of `level2/bounds.py::prefix_exclusion`.
- Then add battery slack as a two-level factor.

## 3. Comparators C1–C3

Run the comparators on P1 variants whose certified lower bound is at least 1, under the same caps. No new missions are needed.

| Policy | Implementation | Status |
|---|---|---|
| C1 finite axis library | `recovery.local_search.recover_local` with `final_benchmark.generators.axis_library` | Existing |
| C2 global first | Level-4 proposals and `search_level4`, without the lower levels | Needs a level argument in the proposal loop of `recover_continuous` |
| C3 time-sliced escalation | Proposals only, 2 s per level, moving up after a failed slice, no exclusions | Heuristic baseline |

For each policy, report:

- the permitted level and the witness's membership level (returned by `certify_witness`), compared with the certified k^F;
- the over-intervention rate;
- changed UAVs and assignment changes (`change_metrics`);
- time to the first feasible plan;
- whether minimality is certified.

## 4. Runtime profile R1

- **Time to certificate.** Use the pass-1 event logs to plot the empirical distribution of time to certificate (CPU and wall) by tasks per UAV, censored at the caps, and the fraction certified at every smaller budget. This holds because search order does not depend on the time cap, provided the per-stage caps are fixed. Confirm it by rerunning 20 variants with a smaller cap. Report pass-2 outcomes separately, because pass 2 is seeded with pass-1 evidence.
- **Uncontended timings.** Run 20 variants on a single worker so the wall-time reference is not affected by other workers.
- **Larger missions.** Use n ∈ {24, 48} and m ∈ {6, 8}, 10 missions each, at one slack and strength with a 60 s cap. Run diagnosis, Levels 0–1 and Level-2 witness search only, and claim only witnesses and their times.

## 5. Update-time extension E1

### 5.1 Scope

E1 covers a single update arriving at time t while the incumbent is being executed. It excludes repeated updates, forecast error and closed-loop control. Certificates hold only for the supplied forecast, so a closed-loop study tests a controller and belongs in a follow-up paper.

### 5.2 In-flight rules (decisions to confirm)

- **D1, current leg.** An airborne UAV keeps its destination.
  - Commit `S {u}:1` and, for a task destination, that task's `A` coordinate. The structural contract already requires the visiting UAV to own the task, so no level can reassign it.
  - Do not commit `P {u}:1`. At Level 1, an affected UAV may then re-route the rest of its leg to the same destination.
  - This differs from today's airborne plan, which freezes the geometry. Freezing is simpler, but it can turn an update on the leg being flown into an unrepairable failure by assumption.
  - Commit the destination's delivery quantity only if it is operationally committed.
- **D2, initial reserve witness.** Keep the manuscript and evaluator definition: a return path from the observed position carrying the current payload. `env/fixed_plan.py` already requires an `initial` witness for non-depot origins. Today's airborne plan proposes a stricter witness (destination first, then return). Choosing it changes the reserve definition, and the paper must say so.
- **D3, ground operations.** If any UAV is mid-service or mid-preparation at the target time, use the earliest later time at which none is, and record the shift. This keeps residual-operation origins out of the verifier.
- **New outcome class: committed-part failure.** An all-path certificate shows that the committed part cannot be completed within battery, reserve or the destination task's deadline. That means reaching the committed destination and serving it, since its owner is fixed. No level can repair such a failure, so report it separately from infeasibility of the remaining plan. Without an energy lower bound from the actual origin, these cases stay unresolved.

### 5.3 Snapshot generation

- **Target times.** For each P1 mission at the middle strength, target t ∈ {τ/4, τ/2}. Execute the incumbent under the previous (zero) wind from 0 to t using the evaluator records.
- **Mission state at t.**
  - Completed deliveries and loads go into `cumulative_delivered` and depot stock.
  - Fully served tasks leave the remaining mission.
  - The remaining plan is re-indexed from the current destination.
  - The remaining slot bound is the original bound minus the completed slots.
- **Airborne positions.** Under zero wind, legs are straight and ground speed is constant, but leg lengths and times are generally irrational, and the verifier is exact.
  - Round position to a 10⁻⁹ grid and battery down to 10⁻⁹ Wh, and keep payload exact.
  - Re-check the previous premise at the snapshot, and reject and log any snapshot that rounding makes infeasible.
- **Wind tables.** They must start at the snapshot epoch: `env/scenario.py` requires `time_knots_h[0] == epoch_h`. Use one stationary bin [t, T].
  - Use the same cell, direction and strength as the t = 0 variant, and leave deadlines unchanged.
  - If the remaining plan no longer uses the cell, U0 is empty and Level 0 follows. This is part of the measured effect, not a new admission.

### 5.4 Verifier changes

- **Origin guard.** In `continuous/physics.py::stationary_guard` (line 43), admit `airborne` origins and idle depot origins. Keep rejecting `servicing` and `preparing` (see D3).
- **Depot-start assumptions to generalize, or disable for non-depot origins:**
  - `continuous/search.py`: the deadline certificate and its verifier start at epoch plus preparation (lines 83, 91 and 133), and the screens create `'initial': [depot]` reserve stubs (lines 52 and 228).
  - `level2/bounds.py::prefix_exclusion`: it starts at the depot with full battery (lines 36–42) and adds preparation for unvisited deadlines (lines 76–77).
  - The origin flags in `level2/replay.py` (line 92) and `recovery/transfers.py`.
  - The guards in `recovery/physical_proofs.py` (line 122) and `recovery/static_paths.py` (line 19).
  - The manuscript's mandatory-completion bound.
  - Section 3 of today's airborne plan lists the Level-3 references.
- **Generalization rule.** Generalize a bound only together with its replay checker. Otherwise disable it for non-depot origins: that stays sound and only adds unresolved cases. Potential-based all-path bounds need no change, because the field is global and valid from any start point.
- **Tests:**
  - A zero-time snapshot reproduces the t = 0 conclusions.
  - Deliveries before t are counted once, and stock is conserved.
  - The destination commitment holds at every level.
  - Replay rejects altered origins, batteries and commitments.
  - Depot-origin results are unchanged.

### 5.5 Design

Use 120 missions × 2 update times × 5 slacks at strength 2/5, i.e. 1,200 variants; the t = 0 variants come from P1. Report level shares against slack by update time, and report committed-part failures separately.

## 6. Running on the laptop

- **Workers.** Run six worker processes on the Ryzen 7 5800H (8 cores), pulling missions from a shared queue. Schedule by mission rather than by variant: one worker handles all variants of a mission, so seeds and transfers stay in one process.
- **Threads.** Set `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS` and `MKL_NUM_THREADS` to 1 before imports.
- **Windows.** Windows starts worker processes with spawn, so guard the entry point with `if __name__ == "__main__":`.
- **Run store.** Create the run store and manifest in the parent process before starting the workers. Record the real worker count; `continuous_benchmark/records.py` currently writes `worker_processes=1`.
- **Records.** Keep one atomic JSON record per variant (`atomic_json`). Stored records are re-audited and reused, so an interrupted run resumes.
- **Power.** Plug the laptop in, use the best-performance power mode and disable sleep. Throttling then affects only wall times, which serve as backstops.

## 7. Protocol

1. **Build.** Implement the generator, ladder driver, transfer checker, event log and tests. Run the diagonal-wind control.
2. **Pilot.** Use seeds 71001–71002 per (n, family): 12 missions and 180 variants.
   - Choose the slack endpoints so that, at strength 2/5, the loosest slack is mostly Level 0 and the tightest mostly Level 2 or higher.
   - Set the battery slack and fix the caps.
   - If more than about a quarter of n = 12 variants remain unresolved after pass 2, drop n = 12 rather than raising caps.
3. **Freeze.** Freeze the configuration and source hash, then run primary seeds 72001–72020. Use no outcome quotas, and do not replace failed slots.
4. **Follow-on runs.** Run the comparators and R1 in separate run directories. Run E1 only after the Section 5.4 changes pass their tests.

## 8. Budget

Worst case, with every run hitting its cap, on six workers:

| Block | Units | Cap | CPU | Wall |
|---|---:|---|---:|---:|
| Pilot | 180 variants | 30 s | 1.5 h | 15 min |
| P1 pass 1 | 1,800 variants | 30 s | 15 h | 2.5 h |
| P1 pass 2 | ≤ 180 variants (10%) | 120 s | 6 h | 1 h |
| C1–C3 | ≤ 1,800 runs | 10 s | 5 h | 50 min |
| R1 larger missions | 40 missions | 60 s | 0.7 h | 7 min |
| E1 | 1,200 variants | 30 s | 10 h | 1.7 h |

Typical costs should be far lower. Measured anchors:

- **Paired cases:** median solve time 0.30–1.44 s by size class, with a 5 s cap.
- **Cohort cases:** median 2.30–7.34 s with a 10 s cap; 248.9 s of search and 286.5 s of generation in total.
- **Level-2 targets on 5 October:** the two 24-task cases spent 46.8 s and 54.8 s of their 60 s generating paths.
- **Level-2 continuation on 6 October:** both cases certified in 3.5 s and 3.0 s, with reused path evidence and route ordering.
- **Level-3 targets:** 0.5–60.0 s each.

## 9. Manuscript sequence

- **Now:** state that the computational evidence uses idle depot origins. Section 5 of today's airborne plan has a bridging sentence.
- **After P1:**
  - Add one figure of level shares against slack.
  - Add one table for the comparators, including the paired library result.
  - Cover the controls and analytic cascade in one paragraph.
  - Mention the tight/loose cohort in one sentence as a stress test.
- **After E1:** add an update-time panel and a paragraph defining D1–D3.

## 10. Out of scope for this paper

- Closed-loop simulation with repeated updates and forecast error.
- Time-varying wind and coupled depot bays.
- Exhaustive Level 3–4 scaling at large n.
- Separate budget-sensitivity reruns; read smaller budgets from the event logs instead.
- Flight tests.

## Verification of this plan

Section 1 figures were recomputed on 7 October 2026 from the frozen case records, the cohort sampling metadata and the 5–6 October follow-up reports. Code references were read in the current source. No experiment was run, and no file other than this one was created or changed.
