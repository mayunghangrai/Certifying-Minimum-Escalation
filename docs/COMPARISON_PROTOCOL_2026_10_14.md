# Equal-resource comparison: protocol

Date: 14 October 2026. Status: **implemented** (`src/final_study`, `src/certify_v2`),
**amended on 15 October** after a review (Section 12), with reporting clarifications on
**19 October** (Section 13). It answers supervisor comment 4 on
the experiments.

Builds on: `CERTIFICATION_METHOD_PLAN_2026_10_09.md` (method v2),
`ROOT_CAUSE_AND_REDESIGN_PLAN_2026_10_10.md` (amendments to v2), and
`SCENARIO_DESIGN_2026_10_14.md` (instance sets FS and LS, answering comment 3). This protocol
replaces the comparator and ablation studies of the 9 and 10 October plans (C1-C3, M2, M3).

## Summary

1. Every method runs on the same laptop and gets the same CPU-time budget per
   instance, the same stopping rule and the same input. All methods are scored against
   the same reference labels.
2. Four methods are compared:
   - global replanning (GR);
   - local greedy repair (LR);
   - progressive hierarchical search (PH);
   - the certified minimum-intervention method (CMI).

   GR, LR and PH are built from CMI's own parts, so differences come from the strategy,
   not from implementation quality.
3. Three ablations of CMI remove, in turn:
   - affected-fleet identification;
   - exclusion proofs (this arm is PH);
   - evidence reuse.

   Reuse across instances is measured in a separate study, never in the head-to-head.
4. Results are organized around the supervisor's three questions. Each question has one
   primary endpoint, fixed before the runs.
5. The runs cover the factorial study (FS) and the level suite (LS) of the scenario
   design, at 10 s and 60 s per instance, plus scaling at 60 s and 300 s. The worst
   case is about 20 h on the laptop.

## 1. The comment and what it concerns

The supervisor's comment, in short: the comparison between global-first and gradual
search used different time budgets and different amounts of reused evidence. All
methods should get the same hardware, budget, stopping criteria and input. The
comparison should cover global replanning, local/greedy repair, progressive
hierarchical search and the proposed method, with ablations that remove affected-fleet
identification, exclusion proofs or evidence reuse. It should answer three questions:

- Does the method change fewer decisions?
- Can it certify that the intervention is minimal?
- What does the certificate cost?

The comment is accurate for the 9 October comparison:

| Arm (9 Oct) | Budget per variant | Evidence it reused |
|---|---|---|
| P1 ladder (our method) | up to 30 s, then up to 120 s for open variants | flight-time bounds from looser deadline variants, exclusions transferred along the deadline chain, plans propagated back, and pass 2 started from pass-1 bounds |
| C1 finite path library | 10 s | none |
| C2 global first | 10 s of proposals, then 20 s of global search | none |
| C3 time-sliced ladder | 2 s per level | none |

There were two more differences:

- **Wall-clock budgets under contention.** All budgets were wall-clock time with six
  workers running at once, which inflates times by about 1.6x.
- **C2 was not true global replanning.** It searched around the incumbent's assignment.

The 9 October comparator table is therefore exploratory and will not be used for a
performance claim.

| The comment asks for | Where this protocol answers it |
|---|---|
| Same hardware | F1 |
| Same computation budget | F2 |
| Same stopping criteria | F3 |
| Same input information | F4 |
| Global replanning, local/greedy repair, progressive search, the proposed method | Section 3 |
| Ablations: affected fleet, exclusion proofs, evidence reuse | Section 4 |
| Three questions | Section 6 |

## 2. Fairness rules

- **F1 Hardware and software.**
  - One machine: the laptop (Ryzen 7 5800H, Windows 11, Python 3.13.3) and one
    environment.
  - One thread per process (`OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS` and
    `MKL_NUM_THREADS` set to 1) and six worker processes.
  - Each worker takes one instance and runs every arm on it back to back, in a random
    order. Background load and contention therefore fall on all arms alike.
  - A one-worker subset of 30 instances measures the contention factor.
- **F2 Budget.**
  - One CPU-time budget B per instance, the same for every arm: B = 10 s and B = 60 s,
    in separate runs.
  - All work counts against B: setup, flight-time bounds, paths, proofs and exact
    checks.
  - The budget is checked between operations, as now, but on CPU time (`process_time`)
    instead of wall time. An overrun by the last operation is logged and reported.
    Reporting clarification (19 October): arena outcome tables and anytime curves count
    only accepted plan/proof events whose CPU timestamp is at most B; runtime includes
    overrun work. Raw events remain available for reference pooling and integrity checks.
- **F3 Stopping.**
  - A run ends when the arm returns its final answer or B is spent, whichever comes
    first.
  - Each arm gets one pass, with no restart and no second pass.
  - Every arm logs every plan it finds (CPU time, level, decisions changed). CMI arms
    also log every proof. Results can therefore also be read at any smaller budget.
- **F4 Input.**
  - Each instance is solved cold, from its own scenario file only. That file holds the
    incumbent, the update, deadlines, commitments and fleet state.
  - An arm may compute anything from the file within its budget, including the
    affected-fleet diagnosis. It sees nothing from other instances or earlier runs: no
    seeded bounds, no transferred exclusions, no propagated plans and no earlier-pass
    bounds.
  - All arms use the same flight-time model, path optimizer and exact checker.
  - Randomized arms use fixed seeds; three seeds on a subset measure their variance.
- **F5 Acceptance.** A plan counts only if the shared exact checker accepts it
  (`certify_witness` or the exact quantity witness). Its level is the smallest original
  level mask that contains it, computed the same way for every arm.
- **F6 Scoring.** Every arm is scored against the reference labels (Section 5), never
  against its own output.
- **F7 Freezing.** The pilot runs on its own seeds. Code, arms, budgets, metrics and
  thresholds are then frozen, and the source hash is recorded before the primary runs.

## 3. Methods

| Method | Strategy | Starts from | Proves anything | Ends when |
|---|---|---|---|---|
| **GR** global replanning | Rebuilds every route from scratch: regret insertion of all tasks, then local moves (relocate, swap, reverse a segment, insert a depot visit). It first removes lateness, then reduces total flight time. Keeps commitments. | nothing: ignores the incumbent | no | local optimum or B; returns its best plan and logs its first feasible one |
| **LR** local greedy repair | Takes late deliveries in deadline order. For each, it tries in turn: re-route the late leg, move the task earlier in its UAV's route, move it to the cheapest position in any other UAV's route. It keeps the first change that fixes the delivery without making another one late, and never undoes a change. Then (amended 15 October) UAVs whose estimated energy falls short of the battery or the return reserve, one at a time: re-route their legs, add a depot stop, or move one of their tasks to the cheapest position in another route; it keeps the first change that clears the shortfall without a late delivery or a new shortfall, and leaves a shortfall it cannot clear to the exact checker. | the incumbent | no | first feasible plan, failure when no move helps, or B |
| **PH** progressive hierarchical search | Levels 0 to 4 in order. At each level, the CMI plan finder runs inside that level's mask with achievable flight times only. Each level gets a fixed share of B, set in the pilot, and the search escalates when the share ends without a plan. | the incumbent | no | first plan, or B |
| **CMI** certified minimum intervention | Method v2: affected-fleet identification, lower-bound proofs, the same plan finder and the alternating ladder. | the incumbent | yes | certified answer (minimum with its proof, or no continuation), or B with a bracket and its best plan |

All four share the flight-time table code, the path optimizer (`continuous/`) and the
exact checker (`continuous/validation.py`, `level2/quantities.py`). PH also shares CMI's
plan finder. A difference in results therefore reflects strategy, not the quality of
one arm's code.

## 4. Ablations

| Arm | What is removed | What it measures |
|---|---|---|
| **noAF** | Affected-fleet identification. U0 becomes the whole fleet, so Levels 1-2 release every UAV, and Level 3 coincides with Level 4 because no outside helper is left. Plans are still scored with the original masks. | What identifying U0 buys in decisions changed (Q1), in certification (Q2: noAF certifies in original terms only when its plan's level is one above a level it excluded) and in cost (Q3). |
| **noEP** = PH | Exclusion proofs. With no lower bounds and no exclusions, a level can be left only when its time share runs out. | What proofs buy: certificates (Q2), time spent at impossible levels (Q3), and escalations past a level that had a plan (Q1). |
| **noER** | Evidence reuse inside an instance. There is no shared flight-time table, and no proof is cited across levels; each level computes its own bounds and paths, as v1 did. | What reuse inside one instance buys in cost (Q3). |
| **XR** (separate study) | Nothing; it *adds* reuse across instances, as in P1. The five deadline variants of each P1 mission and strength are solved in sequence, sharing flight-time bounds, transferring exclusions and propagating plans back. | What reuse buys when consecutive updates hit the same mission, at the same per-variant budget as CMI solving them independently. It is reported apart from the head-to-head, because no baseline can use such information. It runs on P1 because only P1's variants share a wind. |

## 5. Instances and reference labels

Both instance sets come from `SCENARIO_DESIGN_2026_10_14.md`.

- **Population, for the primary endpoints.** FS has 1,458 variants: 162 missions x 3
  strengths x 3 update times. No method's outcome on a variant decides whether it is
  drawn, with one exception: a mission is admitted only when Level 0 is certified
  infeasible at its reference variant (3/5, t = 0). FS is therefore the population of
  disrupted missions, and every admitted variant stays in it, unresolved ones included.
  General performance claims come from FS only.
  - At 10 s: all of them.
  - At 60 s: every variant of a random third of the missions (54 missions, 486
    variants).
- **Per level.** LS has 300 instances balanced over Levels 1-4 and no continuation, plus
  30 hard instances, run at 10 s and 60 s. Because LS is built from certified labels, it
  holds instances v2 certifies at the reference budget; it gives results level by level,
  within that selection, and is never used for overall rates.
- **Secondary.** The 700 P1 variants with lower bound at least 1, at 10 s. They keep
  continuity with the current results. All 1,800 P1 variants serve the XR study.
- **Scaling.** The 40 larger missions (24-48 tasks, 6-8 UAVs), at 60 s and 300 s,
  reported for all 40, for the 27 that R1 left disrupted and for the 24 that R1 left
  unresolved.
- **Reference labels.** The labels are the scenario design's reference runs: CMI with
  600 s per instance, one pass and no reuse, audited by the independent replay checker.
  - A plan from any arm, combined with a reference proof one level below it, also
    certifies the minimum: the evidence is pooled. For constructed LS Level-4 draws, the
    construction's exact-checked witness is pooled the same way when the label is made
    (amended 16 October; scenario design, Section 4).
  - Instances the reference leaves undecided keep their bracket, and scoring uses only
    what the bracket allows.
- **Cross-check.** Every plan from every arm must lie at or above the reference's proven
  lower bound. A violation would expose a defect in a proof. The target is zero.

## 6. The three questions

### Q1. Does the method change fewer decisions?

Measured on every accepted plan:

- the intervention level, and how many levels it lies above the reference minimum;
- UAVs whose plan changed, and how many of them lie outside the affected fleet;
- tasks reassigned to another UAV;
- tasks with a new predecessor on the same UAV. This counts sequence edits. The present
  count compares slot by slot, so one insertion counts every later slot as changed.
- legs flown on a new path, and deliveries with changed quantities;
- coverage: the share of instances with any plan, and the share with a plan at the
  reference minimum.

Comparisons are paired, because every arm sees the same instances. The analysis reports
the differences (CMI minus each arm), with 95% intervals from a bootstrap over missions,
for FS overall and by update time, and for LS level by level.

CMI certifies the minimum *level*, not the minimum number of changes within that level.
Change counts are measured, not certified. Decision 5 offers an optional certified
count.

### Q2. Can it certify that the intervention is minimal?

- **CMI arms:**
  - the share of instances with a certified answer within 10 s and 60 s (a minimum with
    its proof, or no continuation);
  - the bracket width when undecided;
  - the share of certificates that replay (target 100%);
  - cross-check violations (target 0).
- **Baselines:** an accepted Level-0 plan establishes the minimum without an exclusion
  proof. Report these certificates for every arm; only CMI arms can certify positive
  intervention minima or no continuation. Report plans above the reference minimum and
  missing plans although the reference has one. The baselines do not claim optimality.

### Q3. What does the certificate cost?

- **Times:**
  - CPU time to the first plan and to the final answer, for every arm;
  - CPU time to the certificate, for CMI arms;
  - additional delay after the certified-level plan: certificate time minus the time to
    the first plan at the certified level. This is the same statistic originally called
    "proof overhead"; the label was clarified on 19 October. It excludes proof work
    performed before the plan and does not measure the total or incremental cost of proofs.
- **Anytime curves.** Two curves against CPU time from 0 to B: the share of instances
  with a plan at the minimum, and the share certified.
- **Breakdown.** CMI's time split into bounds, route checks, assignment search, paths and
  exact checks, plus the audit time for an independent replay.
- **Groupings and wall time.** All of the above by fleet size, tasks per UAV and
  certified level. Wall time and the contention factor are reported alongside.

### Primary endpoints, fixed in advance

- **Q1:** the share of FS variants with a plan at the reference minimum, at 10 s, each
  arm against CMI.
  The denominator is all FS variants, including unrecoverable and unresolved ones. A
  separately labelled secondary rate conditions on a known finite reference minimum
  (Levels 0-4), with its denominator shown. An unresolved minimum is not a verified
  success; this does not establish that its plan is nonminimal.
- **Q2:** the share of FS variants certified within 10 s, and, on the random third,
  within 60 s.
- **Q3:** the median and 90th-percentile CPU time to certificate on FS, and its ratio to
  PH's time to its first plan on the same variants: both medians are taken over the
  variants where CMI certified and PH found a plan, with a bootstrap interval over
  missions, and the variants CMI did not certify and PH did not solve are reported
  alongside.

Everything else is secondary.

## 7. Hypotheses

The directions are fixed now; the thresholds are set after the pilot, before the
primary runs.

- **H1.** GR changes more decisions than CMI (UAVs changed, tasks reassigned). LR and PH
  return a plan at the minimum less often than CMI at the same budget.
- **H2.** CMI certifies most instances within the budget. Every certificate replays, and
  no arm's plan contradicts a proof. Amended 15 October: the report states two things
  separately. "Target met" means the observed rate reaches the threshold. "Supported"
  means the lower end of the 95% interval lies above it, so that the underlying rate
  exceeds it.
- **H3.** A certificate costs at most a small multiple of a heuristic's time to its first
  plan (Q3, paired on the same variants; supported when the upper end of the 95% interval
  lies within the multiple). noAF and noER cost more than CMI. noEP (PH) can certify only
  Level 0 and spends time at impossible levels.

## 8. What must be built

These steps come after method v2 itself, following the 9 and 10 October plans.

1. **Run harness.**
   - One instance per worker; all arms run back to back in a random order.
   - The CPU-time budget, the event log, cold starts and an input hash per instance.
   - New module `src/escalation_study/arena.py`, a config file and a CLI command.
2. **Arms:**
   - GR and LR are new.
   - PH is the v2 ladder with bounds and proofs switched off and fixed time shares.
   - noAF is v2 with U0 set to the fleet. `scope_family` already takes U0 as an
     argument.
   - noER is v2 without the shared table and without proof citations.
   - XR is v2 with the existing chain logic.
3. **Metrics.** A new function counts predecessor changes and re-routed legs. The
   existing `change_metrics` stays unchanged.
4. **Tests:**
   - every arm returns only plans the checker accepts;
   - budgets hold in CPU time;
   - starts are cold: an instance gives the same answers whatever ran before it on the
     worker;
   - all arms see identical inputs, checked by hash.
5. **Pilot.** On the scenario design's pilot seeds: set PH's and CMI's time shares, fix
   the thresholds, then freeze.

## 9. Cost on the laptop

Worst case, every run hitting its budget, on six workers:

| Block | Runs | Budget | Wall |
|---|---|---|---:|
| Head-to-head on FS and LS | 4 arms x (1,788 instances at 10 s + 816 at 60 s) | 10 s, 60 s | 12.4 h |
| Ablations noAF and noER | 2 x 1,788 | 10 s | 1.7 h |
| Head-to-head on P1 (secondary) | 4 x 700 | 10 s | 1.3 h |
| XR study on P1 | 2 x 1,800 | 10 s | 1.7 h |
| Scaling | 4 x 40 x 2 budgets | 60 s, 300 s | 2.7 h |

The worst case is about 20 h. With the reference labels of the scenario design (about
5 h), the total is about three nights. Typical runs should take far less: LR, PH and CMI
usually stop within seconds.

## 10. Decisions

1. **Methods.** Approve the four methods as defined in Section 3, in particular GR as
   replanning from scratch and PH as CMI without proofs.
2. **Budgets.** 10 s and 60 s of CPU time per instance, and 600 s for the reference
   labels.
3. **Extra baseline (recommended).** GR-c: global search started from the incumbent,
   minimizing lateness first and then the number of decisions changed. It answers the
   likely reviewer question "why not simply penalize changes in a global planner?" and
   adds about 2.4 h in the worst case.
4. **Instance sets.** FS for the overall endpoints and LS for results level by level,
   both from the scenario design; P1 as the secondary set.
5. **Optional.** Certify a finer minimum inside the level, such as the fewest reassigned
   tasks at Levels 3-4. Q1 could then be answered with a certificate as well. It costs
   extra search; decide after the pilot.

## 11. Draft reply to the supervisor

> We agree that the 9 October comparison cannot support a performance claim. The
> comparators had roughly 6-30 s per variant. Our method had up to 150 s and reused bounds,
> exclusions and plans across the five deadline variants of each mission. We will replace
> that comparison with one protocol:
>
> - all methods run on the same laptop with the same CPU-time budget per instance (10 s
>   and 60 s), in one pass with the same stopping rule;
> - each instance is solved from its own input only, with nothing from other instances;
> - a plan counts only if the same exact checker accepts it.
>
> We compare global replanning, local greedy repair, progressive hierarchical search and
> the certified method. Ablations remove affected-fleet identification, exclusion proofs
> and evidence reuse; reuse across instances is reported separately. Results are
> organized by your three questions:
>
> - decisions changed: the level above the certified minimum, UAVs changed, tasks
>   reassigned and sequence edits;
> - certification: the share certified within the budget, with every certificate
>   replayed independently;
> - cost: CPU time to the first plan and to the certificate, and the overhead of the
>   proof.

## Verification of this plan

The 9 October budgets and reuse were read in `configs/escalation_study/comparators.json`,
`src/escalation_study/comparators.py` (C2 starts from the incumbent's assignment, and
every arm uses wall-clock caps) and `src/escalation_study/ladder.py`. The contention factor
of about 1.6 comes from the R1 runtime profile. The existing decision counts were read in
`env/local_scope.change_metrics`. The FS and LS sizes come from
`SCENARIO_DESIGN_2026_10_14.md`. (When this was proposed on 14 October, no other file had
been changed.)

## 12. Amendments of 15 October (review)

1. **Certificates kept.** Every arena result and label keeps its evidence and records in
   a proof file the record cites by digest; the report's replay can be repeated from disk.
2. **LR** repairs energy and reserve shortfalls (Section 3), so the comparison on battery
   scenarios measures strategy, not missing functionality.
3. **Population** wording (Section 5): FS is the disrupted population; LS is selected on
   certification.
4. **Statistics.** Recoverable means a verified finite upper bound (a plan at Level 4 or
   below replays). H2 separates "target met" from "supported"; H3 is paired (Q3). The
   ordinal regression adds the mission-factor x strength and x update-time interactions,
   each tested jointly (clustered Wald test), next to the main-effects model.
5. **Scaling** is reported by R1 stratum.

## 13. Reporting clarifications of 19 October (after the final run)

These changes correct reporting from the stored records. They do not change the frozen
methods, budgets, thresholds, scenario selection or solver outputs.

1. **Denominators.** Restore the all-FS denominator specified for Q1, consistently in
   tables and anytime curves. Preserve the known-finite-minimum conditional rate as a
   secondary metric, with both denominators shown. The earlier table used the latter
   rate as Q1; the archived reports retain that presentation.
2. **Budget events.** Score arena plan outcomes from the plan each arm returned, the only
   plan that is stored and independently replayed: it counts if it replays and was
   returned at `cpu_s <= budget_s`; a plan returned later counts as no plan. Proofs count
   when logged at `cpu_s <= budget_s`. Plans logged during the search but not returned,
   such as a lower-level plan a baseline later replaced, are not credited; their runs are
   counted separately. Edit counts describe the returned plan. Report operation overrun
   frequencies/maxima, late events and unreturned plans separately, retaining all raw
   data for integrity checks. (A first version of this clarification, also of 19 October,
   credited the lowest plan level logged by the cutoff. It was replaced the same day
   because those plans have no stored or replayed witness; it changed only GR and GR-c.)
3. **Pairing.** Compare short- and long-budget CMI certification on the same instances
   in the long-budget subset. Add a paired CMI-minus-PH interval at 60 s, resampling
   missions as in the existing analysis. This additional comparison is exploratory,
   not a replacement for the prespecified short-budget H1 test.
4. **Level 0 and optimality wording.** Include Level-0 certificates for all arms and
   distinguish them from certificates of positive minima or no continuation. A baseline
   plan above the minimum is not described as making a false claim of optimality.
5. **Cost terminology.** Rename the existing timing difference to "additional delay after
   the certified-level plan." Its formula is unchanged. Use the matched PH comparison,
   coverage and CPU breakdown to discuss the cost of certification.
