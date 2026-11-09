# Experiment redesign for the RA-L submission

Date: 30 October 2026. Status: **proposal, nothing run or implemented.** Decisions D1-D5
(Section 7) are needed before any code is written.

Builds on: `COMPARISON_PROTOCOL_2026_10_14.md`, `SCENARIO_DESIGN_2026_10_14.md`,
`FINAL_STUDY_RESULTS_2026_10_18.md`, `FINAL_STUDY_REVIEW_2026_10_19.md`,
`SUPPORT_SENSITIVITY_RESULTS_2026_10_22.md`, and the active manuscript
(`../manuscript/sections/mechanism_evidence.tex`, read only).

Constraint: RA-L, six pages. Page 6 is full, so every addition must replace something.

## 1. What the current evidence establishes, and what it does not

All numbers are from `results/final_study_2026_10_17/analysis/REPORT.md` (FS, 10 s) unless
stated.

| Question | Established | Not established | Why a reviewer will notice |
|---|---|---|---|
| Q1 fewer decisions | CMI changes 3.46 fewer UAVs than GR and 0.44 fewer than GR-c (paired). No CMI plan lies above the reference minimum. | Any difference from PH or LR. Paired CMI minus PH: 0.00 UAVs, 0.00 tasks, -0.01 sequence edits (n = 1,126). PH reaches the minimum level more often at 10 s (81.3% vs 78.1%). | (a) "Plan at the minimum level" is the method's own criterion, and the reference labels come from CMI itself at 600 s, so scoring is partly circular. (b) GR-c is the only global competitor that penalises change, and it is a heuristic. (c) Edit counts are measured, never certified. |
| Q2 certify minimality | 81.0% certified at 10 s; 98.9% at 600 s; 20,655 / 20,655 replays; 0 cross-check violations. | That a certificate is *correct*, using evidence not produced by CMI. That the checker would *reject* a wrong certificate. What the certificate changes for the operator. | Baselines certify only Level 0 because they have no proof mechanism, so "only CMI certifies" holds by construction. A 100% replay rate shows nothing unless the checker can fail. |
| Q3 cost | Median 1.27 s, p90 6.42 s; 1.13x PH's first-plan time on 1,122 common successes. | Cost where certification is hard: at 10 s CMI certifies 54% of Level-3, 15% of Level-4 and 41% of no-continuation variants. Checking cost, certificate size and the CPU split are computed but not in the paper. | The 1.13x ratio excludes the 273 variants CMI did not certify, which are the expensive ones. |
| Scope (locality) | One-cell updates: |U0|/M = 34.5%. | Anything between local and global. S2-S5 give |U0|/M of 96-100%: Level 3 is already global release there. | The method's premise is locality. The paper shows the local end and the global end but not where the advantage ends. Table II's S-rows carry almost no information. |

Parts of the theory that have no experiment at all:

- **T1** affected-fleet closure (Section III-A): "UAVs outside U0 keep their evaluation
  exactly". noAF tests U0 = whole fleet, not dependency closure against spatial overlap.
- **T2** the characterisation F3 nonempty <=> min mu <= b (eq. 11). Every run uses b = 1.
- **T3** escalation boundaries (Section III-D): nested regions and ordered thresholds
  alpha*_k.

**Reading of the three questions.** Answering Q1-Q3 is necessary but not sufficient. The
redesign keeps them as the frame and adds three things to each: a **certified** quantity
in place of a measured one where possible, **ground truth not produced by CMI**, and a
**stratification** that shows where the effect lives rather than a pooled mean.

**What it does not try to do.** It does not try to show CMI beating PH at plan finding.
PH is CMI's plan finder without proofs, and the evidence says they tie. The defensible
claim is: *the same plans as the best proof-free hierarchical search, at about 1.1x its
cost, plus a certificate that changes the operator's decision in a stated share of cases.*

## 2. Claim -> evidence map (the design in one table)

| Claim in the paper | Primary evidence | Block | New runs? |
|---|---|---|---|
| Q1a CMI does not over-intervene | Level gap and over-escalations per arm (exists) | A1 | no |
| Q1b Savings appear where reassignment is possible | Paired decision vector stratified by reference level 1/2/3/4 | A1 | no |
| Q1c **Certified** minimum number of extra UAVs that must change, and each arm's excess over it | b-sweep: mu* per instance; per-arm excess outside-U0 UAVs | **B1** | yes |
| Q2a Certificates are correct | Planted-minimum instances, ground truth known analytically, 0 disagreements | **B2** | yes |
| Q2b The checker is not vacuous | Mutation testing of stored certificates: rejection rate | **B3** | yes (replay only) |
| Q2c The certificate changes the decision | No-continuation triage latency; over-escalations avoided; CPU PH spends at proven-infeasible levels | A2 | no |
| Q3a Cost by difficulty | CPU to certificate and paired ratio to PH, by certified level | A3 | no |
| Q3b Checking is cheaper than producing | Replay CPU vs production CPU; certificate size | A3 | no |
| Q3c Where cost goes | CPU split: bounds, paths, search, exact checks, setup | A3 | no |
| Scope: where the advantage ends | Locality sweep: Q1/Q2/Q3 against |U0|/M | **B4** | yes |
| Theory T3 (optional) | Certified staircase k^F(alpha) on a strength sweep | B5 | yes |
| Theory T1 (optional) | U0 by dependency closure vs spatial overlap; outside-U0 evaluation identity | C2 | cheap |

## 3. Tier A: re-analysis of the frozen records (no solver runs)

Read-only on `results/final_study_2026_10_17`. A new script writes a separate analysis
folder, and the existing `REPORT.md` stays unchanged.

**A1 Q1 by stratum.** For each arm, on paired returned plans, report UAVs changed, outside-U0
UAVs, tasks reassigned and sequence edits, split by the reference minimum (1, 2, 3, 4).
Expected: zero differences at Levels 1-2, where every hierarchical arm finds the same path
or reorder, and the GR/GR-c gap concentrated at Level 3. This locates the effect instead of
averaging it into 1.12 vs 1.62.

**A2 Q2 decision value.** Three counts from stored events:
1. *No-continuation triage.* On the 102 FS no-continuation variants: the share where each
   arm gives a terminal answer by B, and its CPU. CMI proves no continuation; every other
   arm returns nothing and cannot tell "infeasible" from "not found".
2. *Over-escalation.* Plans above the reference minimum (GR 868, GR-c 498, LR 24, PH 8,
   CMI 0) plus how many levels above.
3. *Search at impossible levels.* CPU that PH and LR spend at levels the reference proves
   infeasible (PH `escalate` events against reference lower bounds).

**A3 Q3 cost profile.** CPU to certificate by certified level, with the paired CMI/PH
ratio recomputed **inside each level** (Level 1, 2, 3, NC). Replay CPU vs production CPU per
certificate (median 0.81 s exists). Certificate size from `evidence_size`. CPU split by
component (bounds 20%, paths 33%, search 19%, setup 17%, exact 11% are already in the
report). LS at 60 s gives the hard-level view.

Cost: about one day of analysis code, minutes of compute.

## 4. Tier B: new experiments using existing code (no method change)

### B1 Certified minimum outside participation (Q1, theory T2)

The b-sweep turns Q1 from a measured count into a certified one. `helper_budget` is a
scenario field (`env/local_scope.scope_family` reads `data['hierarchy']['helper_budget']`),
so only the payload changes.

By eq. (11), when F4 is nonempty and Levels 0-2 are excluded,
mu* = min{ b : F3(b) nonempty } is the certified minimum number of UAVs outside U0 whose
plans must change. If k^F <= 2, then mu* = 0 trivially.

- **Population:** every FS and LS instance with certified minimum 3 or 4 at b = 1
  (FS 401 + 13; LS 60 + 60). No-continuation instances are unaffected by b.
- **Runs:** reference minimum 3: CMI at b = 0 (mu* is 0 or 1). Reference minimum 4: b = 2,
  3, ... up to M - |U0|, stopping at the first Level-3 plan. CMI, 600 s, one pass, replayed.
- **Endpoints:** the distribution of mu*; for every arm's returned plan, its excess
  `uavs_changed_outside_u0 - mu*` (from stored decisions); for GR-c, the share whose excess
  is 0. This answers "does a change-penalised global planner already change the minimum
  number of UAVs?" with a certified reference.
- **Caveat:** for b >= 2 the Level-3 patch family grows as C(M - |U0|, b), so some Level-4
  instances may stay unresolved. They are reported as brackets on mu*.
- **Cost:** about 610 runs. Worst case 610 x 600 s / 6 workers = 17 h; typical runs far
  shorter (FS Level-3 median 5 s).

### B2 Planted-minimum instances (Q2a: correctness against independent ground truth)

`final_benchmark/controlled.py` has six analytic gadgets (C0 -> 0, C1 -> 1, C2 -> 2,
C3 -> 3, C4 -> 4 with b = 1, Cinf -> no continuation) with known minima. They are tiny.

Proposal: **embed** a gadget into an FS background mission, so the ground truth is known by
construction at FS scale.
- The background UAVs serve their own tasks, are feasible at Level 0 under the update, and
  are placed so that the analytic argument extends to them: for every gadget task i and
  background UAV u, the straight-line distance over (v_u + wind bound) exceeds the time to
  the deadline. Then no background UAV can help, and the gadget's minimum holds for the
  whole mission.
- The condition is checked by the generator **and** by the existing all-path bound before an
  instance is admitted; failures are logged.
- **Endpoints:** disagreements between CMI's certified level and the planted level (target 0;
  any disagreement is a soundness defect and stops the study); recall (certified within
  10 s and 60 s) by planted level; each baseline's plan level against the planted one.
- **Size:** 6 gadgets x 3 fleet sizes x 10 backgrounds x 3 update times = 540 instances, all
  arms at 10 s. About 2 h.
- **Open point:** the Level-2 and Level-4 gadgets need checking against background helpers
  (C4 becomes 3 once b >= 2). I am not certain the reachability condition is sufficient for
  every gadget under airborne starts; Decision D3 limits B2 to t = 0 if needed.

### B3 Mutation testing of the checker (Q2b)

A 100% replay rate is informative only if the checker rejects wrong certificates.
- **Sample:** 50 stored certificates per class (Levels 1-4 and no continuation, FS and LS)
  = 250 proofs, from the proof files already saved.
- **Mutation operators** (each makes the certificate wrong): scale one Farkas multiplier;
  drop one branch from a coverage tree; lower a recorded travel-time bound by epsilon; change
  one witness quantity by epsilon so a deadline or energy limit is violated; relabel a
  witness to a lower level; perturb one scenario value bound by the hash.
- **Endpoint:** rejection rate per operator (target 100%). A mutant that is accepted is
  investigated by hand: either it is still valid (a benign mutant, reported separately) or
  it is a checker defect.
- **Cost:** 250 x about 8 operators x about 0.8 s replay, under 1 h.

### B4 Locality sweep (scope; all three questions)

This replaces S1-S5, whose |U0|/M is 34.5% or 96-100% with nothing between.
- **Factor:** target affected fraction |U0|/M in {1/8, 1/4, 3/8, 1/2, 3/4, 1}, reached by
  choosing the update support (cells, or time bins on a finer 8 x 8 grid) until the
  diagnosed U0 hits the band.
- **Population:** 60 FS-like missions (8 UAVs x 3 tasks, both layouts) x 6 bands = 360
  instances, strength 3/5, t = 0.
- **Runs:** labels (CMI 600 s) and arena GR, GR-c, LR, PH, CMI at 10 s.
- **Endpoints:** against |U0|/M: CMI-minus-GR UAVs changed (Q1), CMI certification rate (Q2),
  CPU to certificate (Q3), recovery success of CMI and GR. This gives the break-even point
  where certified local repair stops paying, which the current S2-S5 results show only as
  "the advantage reverses".
- **Code impact:** the update-support selector in the generator; an 8 x 8 grid may need a
  generator option. `env/` is unchanged if the grid is a scenario input (to verify, D4).
- **Cost:** worst case 360 x 600 s / 6 + 360 x 50 s / 6, about 11 h.

### B5 Escalation staircase (optional; theory T3)

20 FS missions x 12 strengths from 0 to 4/5 of the slowest airspeed, CMI at 600 s.
Report the share of missions whose certified k^F(alpha) is monotone, the thresholds
alpha*_k, and the non-monotone cases (Section III-D says stronger wind need not degrade
feasibility). This is a strong single figure but costs page space. Run it only if D2 keeps
it.

## 5. Tier C (only if a reviewer asks)

- **C1 Exact minimum-edit global baseline.** B1 already certifies the minimum number of
  outside UAVs, which is the edit measure the theory supports. A full minimum-edit planner
  is a new method. Not recommended for this submission.
- **C2 Dependency closure vs spatial overlap.** Count UAVs in U0 by DAG closure but not by
  nominal-path overlap. In FS, cross-UAV propagation can come only through shared stock and
  return witnesses, so the difference may be zero. Report it in one sentence if so.

## 6. Primary endpoints, fixed before the runs

| Question | Primary | Secondary |
|---|---|---|
| Q1 | Per-arm excess over certified mu* on Level-3/4 instances (B1) | Decision vector by reference level (A1); level gap |
| Q2 | Planted-level disagreements = 0 (B2) and mutation rejection = 100% (B3); certification rate at 10 s / 60 s (existing) | No-continuation triage and over-escalation (A2); recall on planted instances |
| Q3 | CPU to certificate and CMI/PH ratio by certified level (A3) | Replay vs production CPU; certificate size; CPU split; cost against |U0|/M (B4) |

## 7. Paper layout within six pages

| Element now | Proposed |
|---|---|
| Table II: FS + S1-S5 rows | FS row, planted-instance row (B2: planted vs certified), and the mu* distribution for Level 3/4 (B1). The S-rows move into the B4 figure. |
| Table III: one block of 7 arms | Same arms; columns grouped Q1 (level gap, UAVs, excess over mu*), Q2 (certified, NC decided), Q3 (CPU to certificate, ratio to PH). |
| Fig. 2: anytime curves (two panels) | (a) anytime certification (kept); (b) locality sweep: UAVs saved vs GR and certification rate against |U0|/M. |
| Text: protocol, Q1, Q2, Q3, beyond FS | Protocol trimmed about 20%. Q2 adds one sentence each for B2 and B3. "Beyond FS" becomes one scope paragraph (LS, scaling, B4). |

Risk: this is roughly page-neutral only if the S-rows, the support-sensitivity paragraph
and part of the protocol text go. Recompile and check the page count after every change.

## 8. Order and effort

| Step | Work | Compute |
|---|---|---|
| 1 | A1-A3 analysis script | minutes |
| 2 | B3 mutation harness | < 1 h |
| 3 | B1 b-sweep runner (payload change only) | 1 night |
| 4 | B2 gadget embedding generator + admission check | about 2 h |
| 5 | B4 locality selector | 1 night |
| 6 | B5 (if kept) | about 4 h |

Steps 1-3 need no generator change and give a certified answer to Q1 and a non-vacuous
answer to Q2. They should run first.

## 9. Decisions needed

- **D1** Is the reading in Section 1 right: keep Q1-Q3 as the frame, add certified,
  ground-truth and stratified evidence, and drop any attempt to show superiority over PH?
- **D2** Which blocks to run: recommended A1-A3, B1, B2, B3, B4; B5 optional.
- **D3** B2 at t = 0 only, or at all three update times (needs the airborne reachability
  argument checked first).
- **D4** B4 may add a finer wind grid to the generator.
- **D5** Manuscript edits happen in `../manuscript`, outside `code/`. They need separate
  permission when the results exist.

## 10. A2 results (30 October 2026)

Script `scripts/analyze_decision_value.py`; output `results/a2_decision_value_2026_10_30/`
(read-only on `final_study_2026_10_17`, same scoring as its report; counts match the report's
"plans above the minimum" and "no plan although the reference has one" for every arm and set).

1. **PH is not proof-free at Levels 0-1.** `Instance.search` ignores `proofs=False` there
   (`certify_v2/levels.py`, `search`), so PH leaves those levels on CMI's lower-bound exclusions:
   FS 10 s, 916 Level-0 and 469 Level-1 exits by proof against 275 and 115 by time share; at
   FS 60 s every Level-0/1 exit is by proof. The baseline is therefore stronger than a
   proof-free hierarchical replanner, and differs from the protocol's definition of PH.
2. **Getting past infeasible levels: PH is faster.** FS 10 s, reference lower bound 3: PH
   starts Level 3 at a median 1.52 s; CMI proves Levels 0-2 infeasible at 2.31 s.
3. **Escalations: PH is right in hindsight, never by proof.** FS 10 s: 98.2% of PH's positive-level
   plans are at the reference minimum, none proven; 99.5% of CMI's are proven by its own evidence.
4. **Unrecoverable missions are where the certificate changes the outcome.** PH spends a median
   9.6 s of 10 s (38.9 s of 60 s) and returns nothing. CMI proves no continuation for 42/102 (FS 10 s),
   44/47 (FS 60 s third) and 54/60 (LS 60 s), medians 5.7, 10.3 and 13.3 s. For the baselines,
   "nothing" is ambiguous: at FS 10 s, 148 of PH's 252 empty results were recoverable.

## 11. Amendment: strict PH (30 October 2026)

Finding 1 of Section 10 means PH as run is not the protocol's PH (Section 4: "a level can be left
only when its time share runs out"). A new arm, **PH-strict**, restores the definition. The
frozen PH arm is kept as run and reported as "PH (proof-assisted at Levels 0-1)".

- Code: `fixed_exclusions` setting in `certify_v2/levels.py` (default on: PH, CMI and every
  stored result unchanged). Off, Levels 0-1 run no lower-time check, no potential refinement and
  no tight-leg shortcut; each leg gets a quick and a deep path search, and the level ends open.
  `run_ph(..., arm=...)` and arm `PH-strict` in `final_study/arena.py`.
- Still shared by design with CMI (protocol: PH uses CMI's plan finder): the plan finder's
  pruning of visiting orders by optimistic lateness at Levels 2-4, and the table's first lower
  bound used to rank path improvements. PH-strict never leaves a level because of them.
- Test: `test_strict_ph_leaves_levels_without_proofs`.
- Runs: `scripts/run_strict_ph.py`, config `configs/final_study/strict_ph.json`; arms PH,
  PH-strict and CMI together on the frozen FS instances (10 s all, 60 s third), in the
  `wind_benchmark` environment (Python 3.10.21, packages as in the final-study manifest).
- Tests: 640 passed in `.venv`; 639 passed in `wind_benchmark` with
  `test_analysis_recoverable_h3_pairing_and_interaction_tests` deselected, because SciPy BFGS
  crashes that environment (exit 127 on a three-variable problem; unrelated to this change).

### Results (run of 30 October 2026, `results/strict_ph_2026_10_30/REPORT.md`)

1,440 x 3 arms at 10 s and 477 x 3 at 60 s; every result replays; no plan below a proven lower
bound; no failed unit. The rerun reproduces the frozen brackets for PH on 1,417/1,440 (10 s) and
477/477 (60 s), and for CMI on 1,397/1,440 and 476/477. CMI certifies 1,135 (78.8%) at 10 s here,
against 1,167 (81.0%) in the frozen run: run-to-run CPU variation. Comparisons below are paired
within this run.

| | 10 s | 60 s (third) |
|---|---|---|
| Plan at minimum: CMI / PH / PH-strict | 1,100 / 1,155 / 1,073 | 412 / 403 / 399 |
| CMI minus PH-strict, plan at minimum (pp) | +1.9 [+0.4, +3.5] | +2.7 [-0.4, +6.5] |
| CMI minus PH, plan at minimum (pp) | -3.8 [-5.6, -2.0] | +1.9 [-0.8, +5.5] |
| PH minus PH-strict, plan at minimum (pp) | +5.7 [+3.8, +7.7] | +0.8 [+0.0, +1.9] |
| CMI certificate / PH first plan (ratio of medians) | 1.14x [1.10, 1.18] | 0.98x [0.96, 1.22] |
| CMI certificate / PH-strict first plan | 0.82x [0.35, 0.96] | 0.22x [0.20, 0.26] |
| PH-strict minus PH, first plan (median paired) | +0.38 s [+0.27, +2.22] | +4.44 s [+3.73, +6.55] |
| Levels left after < 0.02 s (PH / PH-strict) | 421 / 813 | 106 / 84 |

Reading:
- PH's 10 s advantage over CMI came from CMI's own Level 0-1 exclusions: without them PH loses
  5.7 points and falls 1.9 points below CMI.
- Against a proof-free hierarchy, CMI's certificate arrives before the other's first plan
  (0.82x at 10 s, 0.22x at 60 s). Exclusion proofs make escalation faster, not slower.
- At Level 3 and 10 s, PH as run still reaches the minimum most often (256 of 401, against CMI
  190 and PH-strict 177).

Caveats:
- PH's time shares were calibrated in the pilot on PH as run and kept; they were not tuned for
  PH-strict. Its first-plan times include waiting out the Level 0 share (0.5 s at 10 s, 3 s at
  60 s) on every disrupted instance. A different schedule could shorten them.
- Shares are cumulative, so one overrunning operation (up to about 2 s for a deep path search)
  leaves later levels with almost no time; PH-strict does this 813 times at 10 s.
- PH-strict still shares the plan finder's optimistic-lateness pruning at Levels 2-4 with CMI.

## 12. PH-strict schedule sensitivity (31 October 2026; rule fixed before the run)

Question: does CMI's advantage over PH-strict (Section 11) survive a better time-share schedule?

Schedules (`final_study/arena.py`, `PH_SCHEDULES`; all with `fixed_exclusions=False`):

| Arm | Shares of the budget B | Why |
|---|---|---|
| PH-strict | 0.05, 0.15, 0.20, 0.30, 0.30 (cumulative) | as run on 30 October |
| PH-strict-dbl | (1, 2, 4, 8, 16)/31 (cumulative) | standard doubling, chosen without the data |
| PH-strict-fix | Levels 0-1 end at 0.5 s and 2 s; the rest 2:3:3 | removes the 60 s waiting at Level 0; equals PH-strict at 10 s, so run at 60 s only |
| PH-strict-gs | as PH-strict, and each level runs at least its own share from its start (`run_ph(guaranteed=True)`) | an overrun can no longer leave a later level no time |

Population: the 60 s third of FS (477 variants, 53 missions) at 10 s and at 60 s; CMI and
PH-strict rerun alongside in each instance's random arm order. Config
`configs/final_study/strict_ph_schedules.json`; output `results/strict_ph_schedules_2026_10_31/`.
Tests: 642 passed in `.venv`; 641 passed with the SciPy-crash test deselected in `wind_benchmark`.
The 30-instance smoke run replayed all 120 results; PH-strict-gs skipped no level.

Decision rule:
- At each budget, the best PH-strict schedule is the one with the most minimum-level plans on
  these instances, chosen after the run. This favours PH-strict.
- CMI's advantage is called **robust** if, against that best schedule, (a) the CMI-minus-schedule
  minimum-level difference is not significantly negative, and (b) the H3 ratio (CMI certificate /
  schedule first plan, ratio of medians) has an upper interval end below 1.
- A best schedule that significantly beats CMI on (a) at 10 s is rerun on all 1,440 instances
  before any manuscript claim.

### Results (`results/strict_ph_schedules_2026_10_31/REPORT.md`)

477 x 4 arms at 10 s and 477 x 5 at 60 s; every result replays; no plan below a proven lower
bound; no failed unit. Rerun CMI has the frozen bracket on 463/477 (10 s) and 476/477 (60 s).

| | 10 s | 60 s |
|---|---|---|
| Plan at minimum: CMI | 334 | 412 |
| PH-strict / -dbl / -fix / -gs | 327 / 325 / - / 324 | 401 / 397 / 400 / 398 |
| Best schedule (most minimum-level plans) | PH-strict | PH-strict |
| CMI minus best, plan at minimum (pp) | +1.5 [-1.3, +5.0] | +2.3 [-0.6, +6.1] |
| H3 ratio vs best | 0.36x [0.30, 0.96] | 0.23x [0.20, 0.27] |
| H3 ratio vs -dbl / -fix / -gs | 0.80x [0.35, 1.09] / - / 0.32x [0.30, 0.59] | 0.23x / 0.32x [0.29, 0.48] / 0.23x |
| Levels left after < 0.02 s: PH-strict / -dbl / -fix / -gs | 255 / 416 / - / 37 | 91 / 46 / 81 / 90 |

Verdict under the rule: **robust at both budgets** ((a) and (b) hold against the best
schedule). No full rerun is triggered.

Notes:
- Against doubling at 10 s, CMI's timing advantage is not established: its first plan has a
  median of 1.66 s on the matched instances against CMI's certificate at 1.33 s, and the
  ratio's interval reaches 1.09. It reaches the minimum less often (325 vs CMI 334).
- Guaranteed shares removed most skipped levels (37 against 255) without more minimum-level
  plans (324 against 327): skipping was not what limited PH-strict.
- Fixed-time low levels cut the 60 s first plan by a median 3.39 s, but CMI's certificate is
  still faster (0.32x).
- Where CMI wins is Level 3: 43 of 116 at 10 s against 32-38, and 114 against 96-100 at 60 s.
  At Level 4 (9 instances) every PH-strict schedule reaches the minimum at 60 s, CMI 6.

## 13. B1 as run (31 October 2026; rule fixed before the run)

Changes from Section 4, B1, decided before the full run:

- **Population:** FS 401 + 13 and LS 63 + 62 instances whose pooled reference minimum is 3 or 4
  (LS selected suite only), 539 in all. The frozen allowance is b = 1 in every instance.
- **Bounds:**
  - Lower: reference minimum 4 gives mu* >= 2 (Level 3 excluded at b = 1). A Level-3
    exclusion in a b-sweep label at b gives mu* >= b+1.
  - Upper: the mu of any replayed plan, from frozen labels, frozen arenas or b-sweep labels.
- **Runs:** a label at b only where the stored bracket is open, for b from the lower bound to
  (best stored mu) - 1, all in parallel and without stopping early. That is 298 labels (262 at
  b = 0, 36 at b = 2-6) instead of about 610. They are CMI labels at 600 s with the frozen
  settings, one pass, replayed.
- **Equivalence check (eq. 11):** each stored best plan with mu != 1 is re-checked under the
  scenario with b = mu, expecting Level <= 3. There are 277 such plans. The check is scope
  membership plus the exact quantity check.
  - The stored witness lists the quantity columns of its b = 1 patch, so it is rebuilt on each
    smaller patch's own columns. Dropped columns are held at incumbent values by the compiler.
    Without this rebuild, 4 of 12 smoke plans were refused on column lists alone.
  - Controls are rejected as they should be: mu = 1 plans at b = 0, a nudged helper quantity,
    and a nudged U0 quantity (the last by the exact check).
- **Endpoints:** the mu* distribution with open brackets; per arena and arm, the excess
  (plan mu - mu*) of returned plans on settled instances, the zero-excess share (no plan counts
  as a failure, 95% interval over missions), and the count of plans below mu*, which must be 0.
- **Files:** config `configs/final_study/b_sweep.json`; runner `scripts/run_b_sweep.py`;
  smoke run `results/b_sweep_smoke` (12 labels at 60 s, all replay); full run
  `results/b_sweep_2026_10_31`.
- **Known limit:** CMI certifies the minimum level, not the minimum mu within that level, so its
  plans can have positive excess. The smoke run already shows b-sweep labels finding plans with
  smaller mu than any stored plan.

### Results (`results/b_sweep_2026_10_31/REPORT.md`)

298 labels in 40 min on 6 workers. Every label replays (185 Level-3 exclusions, 108 Level-3
plans, 5 open). All 277 re-checks are accepted, and no plan anywhere has mu below a certified
mu*. No failed unit.

mu* is settled on 536 of 539 instances; 3 stay at the bracket [0, 1].

| | n | mu* = 0 | mu* = 1 | mu* = 2 | bracket |
|---|---:|---:|---:|---:|---:|
| FS, minimum 3 | 401 | 240 | 159 | 0 | 2 |
| FS, minimum 4 | 13 | 0 | 0 | 13 | 0 |
| LS, minimum 3 | 63 | 36 | 26 | 0 | 1 |
| LS, minimum 4 | 62 | 0 | 0 | 62 | 0 |

- The b-sweep found plans with fewer outside UAVs than any stored plan on 95 instances: 74
  Level-3 instances from 1 to 0, and 21 LS Level-4 instances from 3-7 to 2. Every Level-4
  instance needs exactly two outside UAVs.
- Plans with mu = mu* among returned plans (counts in the report):

| | FS 10 s | FS 60 s | LS 10 s | LS 60 s |
|---|---|---|---|---|
| CMI | 183/217 (84%) | 98/119 (82%) | 15/19 | 67/95 (71%) |
| PH (as run) | 227/272 (83%) | 96/110 (87%) | 22/29 | 45/64 (70%) |
| GR-c | 127/258 (49%) | 49/81 (60%) | 21/44 | 22/45 (49%) |
| LR | 124/169 (73%) | 31/36 | 7/11 | 7/11 |
| GR | 30/303 (10%) | 9/103 (9%) | 9/65 | 9/67 |

- Every zero-excess plan is at the minimum level. No plan above the minimum level has
  mu = mu*: GR has 244 such plans at FS 10 s, GR-c 36.
- At the minimum level CMI's excess is at most 1 on FS, and at most 4 on LS at 60 s
  (Level-4 plans). The hierarchy itself does not choose among plans within a level.
  PH behaves the same way.
- Reading for Q1: the change-penalised global planner (GR-c) brings in more outside UAVs than
  needed on about half its plans. CMI and PH do so on 13-30%. The difference comes from the
  level order, so it is not an advantage of CMI over PH.
- A lexicographic refinement (Level 3 at b = 0 before b = 1) would make CMI's plans meet mu*
  wherever it certifies Level 3. It is a method change and is not run here.
- Paired zero-excess difference, CMI minus the arm, in pp on the same instances with a 95%
  interval over missions. "Matched" means both arms returned a plan; PH is PH as run. Full
  table in the report.

| | FS 10 s | FS 60 s | LS 60 s |
|---|---|---|---|
| GR-c, all instances | +13.6 [+3.8, +23.8] | +39.5 [+23.3, +56.5] | +36.3 [+25.8, +46.0] |
| GR-c, matched | +15.1 [+2.9, +28.1], n = 126 | +17.5 [+2.4, +35.2], n = 80 | +7.9 [-10.5, +28.9], n = 38 |
| GR, matched | +70.3 [+57.6, +82.9] | +74.0 [+60.5, +87.6] | +48.1 [+30.8, +63.5] |
| PH, matched | +0.0 (183 vs 183) | -0.9 [-2.8, +0.0] | +3.2 [-3.2, +9.7] |

  On matched plans CMI beats GR-c on FS at both budgets and is level with PH. "All
  instances" adds recovery, and that is where PH leads at 10 s.

## 14. CMI-mu: fewest outside UAVs after the level certificate (1 November 2026; fixed before the run)

Motivation: B1 shows that CMI certifies the minimum level but returns plans whose mu is above
mu* on 16-29% of instances (Section 13).

Method (`run_cmi(mu_refine=True)`, arm `CMI-mu`; CMI unchanged):
- The refinement starts only once the minimum level k is certified at 3 or 4. It uses the
  remaining budget, so the level certificate and its CPU time are CMI's.
- Lower bound on mu*: 0 at k = 3; at k = 4 the scenario's allowance plus one, since Level 3
  is excluded. Upper bound: the returned plan's mu.
- For b = lower, ..., mu - 1, Level 3 is searched at allowance b (`Instance.level3(allowance=b)`,
  patches from `scope_family(..., helper_budget=b)`), with proofs:
  - a plan replaces the returned one (same level, mu <= b) and ends the step;
  - a proof (`allowance_patches_v1`) raises the lower bound to b+1;
  - an open search or the end of the budget ends the step.
- Plans in this step are checked only on the allowance-b patches (`exact(allowance=b)`), so
  the quantity solve cannot move a UAV outside the patch.
- Result fields: `mu_bounds` (lower, upper, minimum) and `mu_proofs`. Events: `mu_proof`,
  `mu_plan`, `mu_open`.
- Replay (`verify_run`) replays every allowance tree. It finds a plan's patch at its
  allowance, recomputes the bracket (proofs nest in b; the plan's mu from its exact
  quantities) and requires it to equal `mu_bounds`.

Tests:
- `test_mu_refinement_finds_and_proves_the_fewest_outside_uavs`: on two B1 instances where CMI
  changed one outside UAV, CMI-mu at 10 s returns mu = 0 and proves mu* = 1 respectively, and
  rejects two tampered results.
- Full suite: 643 passed in `.venv`; 642 passed with the SciPy-crash test deselected in
  `wind_benchmark`.

Smoke (`results/cmi_mu_smoke`; 26 instances, 38 runs):
- Every result replays.
- The level bracket matches frozen CMI on 37 of 38.
- The refinement closed the mu bracket on all 24 certified Level-3/4 runs: 14 proofs, 1
  better plan, 9 already at the lower bound.
- No contradiction with B1's mu*.

Full run (`results/cmi_mu_2026_11_01`):
- CMI-mu alone on FS 1,440 at 10 s and 477 at 60 s, and LS 330 at 10 s and at 60 s.
- Compared with frozen CMI on the same instances against B1's mu*.
- At most 66,000 CPU-s, about 3 h on 6 workers.

Endpoints:
- (a) The zero-excess share, CMI-mu minus CMI, paired, on all instances and on matched plans.
- (b) The share of certified Level-3/4 runs with a closed mu bracket.
- (c) Level brackets and plan-at-minimum counts equal to CMI's up to run-to-run variation, as a
  guard that the refinement does not cost recovery.
- (d) Zero contradictions with mu*.

### Results (`results/cmi_mu_2026_11_01/REPORT.md`)

2,577 runs in 68 min on 6 workers. Every result replays, the mu bracket included. No failed
unit, and no contradiction with B1's mu*.

| | FS 10 s | FS 60 s | LS 10 s | LS 60 s |
|---|---|---|---|---|
| Plans with mu = mu*, CMI / CMI-mu (matched plans) | 172 / 190 of 206 | 98 / **119 of 119** | 14 / 17 of 18 | 67 / **95 of 95** |
| CMI-mu minus CMI, matched (pp) | +8.7 [+3.4, +14.3] | +17.6 [+8.3, +27.0] | +16.7 [+0.0, +33.3] | +29.5 [+21.1, +38.9] |
| CMI-mu minus CMI, all instances (pp) | +2.4 [-1.0, +6.0] | +16.9 [+8.0, +26.2] | +5.6 [+1.6, +10.5] | +22.6 [+16.1, +29.8] |
| Certified Level-3/4 runs with a closed mu bracket | 187 / 209 | 118 / 120 | 22 / 24 | 90 / 95 |
| Refinement outcomes (better plan / proof / open) | 18 / 95 / 0 | 21 / 53 / 0 | 3 / 8 / 0 | 27 / 20 / 1 |
| Level bracket equal to frozen CMI | 1410 / 1440 | 476 / 477 | 313 / 330 | 330 / 330 |
| Certified, CMI / CMI-mu | 1167 / 1152 | 456 / 456 | 155 / 161 | 269 / 269 |

- At 60 s every CMI-mu plan on an instance with settled mu* uses exactly mu* outside UAVs, on
  FS and LS. The claim becomes: lowest level, then fewest outside UAVs, both certified per
  instance whenever the bracket closes.
- The guard (c) holds at 60 s, where results are identical. At 10 s certification moves by
  run-to-run timing in both directions: FS -1.0 pp [-1.8, -0.3], with 18 lost and 3 gained;
  LS +1.8 pp [+0.3, +3.3].
- The 18 FS losses are not caused by the refinement, which runs only after certification. All
  18 were certified late by frozen CMI (7.3-9.4 s of 10 s).
- At 10 s the all-instance gain is small because the refinement has little time left after
  the certificate. On matched plans it is still +8.7 pp.

## 15. B3 as run: mutation testing of the checker (1 November 2026; fixed before the run)

Runner `scripts/run_mutation.py`; no source change.

Sample (seed 76105): 50 proofs per class.
- 600 s labels with minimum 1, 2, 3, 4 or no continuation, half FS and half LS where
  possible. FS has 13 Level-4 labels, so LS fills the rest.
- CMI-mu runs with allowance proofs from `results/cmi_mu_2026_11_01`.
- 300 in all. Every unchanged proof (control) must replay.

Operators: each makes the proof claim more than it shows. Digests are recomputed where a hash
would otherwise reject the mutant first.

| Operator | Mutation | Invalid by construction |
|---|---|---|
| o1 | zero one nonzero Farkas multiplier (fixed-route exclusion) | no (a smaller combination can still certify) |
| o2 | one fixed-route leg above what is proven: a released leg 1 tick over its certified bound, a fixed path 1 tick over its recomputed time | yes |
| o3 | double a travel-time lower bound and re-key its certificate | no (the bound can have slack) |
| o4 | a route-proof matrix entry 1 tick over its certified bound | yes |
| o5 | delete a reachable node of a stop-sequence tree | yes |
| o6 | delete a non-root node of a cited assignment tree | yes |
| o7 | drop one patch from a Level-3 or allowance exclusion | yes |
| o8 | relabel the plan one level lower, with that bracket | yes |
| o9 | raise one positive delivery by 1/1000 and re-hash the plan | no (the plan can stay feasible) |
| o10 | cite the highest exclusion as one level higher | yes |

Endpoints:
- Per operator: rejection rate, with a target of 100% on the invalid-by-construction operators,
  and the check that fired.
- Every accepted mutant is inspected by hand and reported as still valid or as a checker defect.

The smoke run found a weakness in the operator, not in the checker. The first o2 (+1 tick on
any leg) left 2 of 12 mutants valid: those records cite a weaker bound than the block's final
certificate (0.71 vs 0.99 and 0.65 vs 0.73, in 10^12 ticks), which is conservative and sound.
o2 was then fixed to go above the certified bound. Smoke after the fix (`results/mutation_smoke`,
12 proofs): 12/12 controls replay and 88/88 mutants are rejected.

### Results (`results/mutation_2026_11_01/REPORT.md`)

300 proofs (50 per class) in 33 min on 6 workers; no failed unit.
- Controls: 300 of 300 replay.
- Mutants: 2,170 applied, 2,170 rejected (100%), every one by the check aimed at it. No mutant
  was accepted, so none needed inspection by hand.

| Operator | Applied | Rejected | Check that fired |
|---|---:|---:|---|
| o1 Farkas multiplier | 300 | 300 | fixed-route Farkas |
| o2 leg above proven | 300 | 300 | fixed path bound 192, leg bound 108 |
| o3 lower bound doubled | 300 | 300 | lower-bound certificate |
| o4 matrix entry | 200 | 200 | matrix entry exceeds its certified bound |
| o5 stop-sequence node | 70 | 70 | stop-sequence tree |
| o6 assignment node | 150 | 150 | missing node |
| o7 patch dropped | 150 | 150 | level-3 patches 100, allowance patches 50 |
| o8 plan relabelled | 250 | 250 | plan level |
| o9 delivery nudged | 200 | 200 | exact quantity check |
| o10 exclusion promoted | 250 | 250 | record level 100, level-2 UAV 100, level-3 patches 50 |

Coverage and limits:
- Each operator applies where its evidence occurs. o4-o7 need route proofs or trees (Levels
  3-4, no continuation, CMI-mu). o9 needs released quantities (not Level 1). o8 and o10 need a
  plan or an exclusion below Level 4.
- Stop-sequence trees occur in 70 of the 300 proofs.
- Mutants are single-point and written by the same authors as the checker.
- Scenario perturbations are not tested: exclusions are recomputed from the scenario, so a
  changed scenario asks a different question.

Reading for Q2: the 100% replay rate is informative. The checker rejected every one of 2,170
proofs made to claim more than they show, across every evidence kind the method produces.

## 16. A1 and A3 results (1 November 2026)

Script `scripts/analyze_strata.py`; output `results/a1_a3_strata_2026_11_01/REPORT.md`. This is
a read-only re-analysis of the frozen run, with PH-strict taken from `results/strict_ph_2026_10_30`
(FS only). Differences are arm minus CMI on paired returned plans, with 95% intervals over
missions.

### A1: where Q1 lives (FS 10 s; FS 60 s and LS agree)

| Arm | Ref. min 1 | Ref. min 2 | Ref. min 3 | Plans above minimum |
|---|---|---|---|---|
| PH-strict, PH, noAF, noER | 0.00-0.06 UAVs at every level (intervals touch 0) | | | 0-13 |
| LR | +0.01 | +0.16 [+0.06, +0.33] UAVs, +0.29 tasks | +0.02 | 24 |
| GR-c | **+0.72 [+0.62, +0.81]** UAVs, +1.38 tasks | **+0.59 [+0.35, +0.79]**, +1.50 tasks | +0.09 [-0.03, +0.23] UAVs, +0.21 outside U0, +0.86 tasks | 498 |
| GR | +3.67 | +3.96 | +2.29 | 868 |

- Against the hierarchical arms the difference is zero in every stratum. Section 1 already
  reads it this way: CMI's Q1 advantage is the level order, which PH shares.
- Against GR-c the gap is largest at reference Levels 1-2, where GR-c reassigns tasks that a
  path change or reorder would have kept. This is **not** at Level 3 as Section 3 expected; at
  Level 3 GR-c changes about as many UAVs, with more of them outside U0.
- The one stratum where CMI changes more is LS Level 4 at 60 s: GR-c -0.62 [-1.12, -0.12] UAVs
  (n = 8). That is the extra helpers of Section 13, which CMI-mu removes.

### A3: cost by certified level

| CMI certified level | FS 10 s certificate CPU, median / p90 | H3 vs PH-strict, FS 10 s | H3 vs PH-strict, FS 60 s | Replay / production CPU | Certificates, median |
|---|---|---|---|---|---|
| 0 | 0.48 / 0.89 s | 0.79x [0.77, 0.86] | 1.15x [1.00, 1.19] | 0.93 | 14 |
| 1 | 1.20 / 2.52 s | 0.68x [0.31, 0.82] | 0.27x [0.23, 0.30] | 0.49 | 48 |
| 2 | 3.09 / 5.42 s | 0.49x [0.44, 0.55] | 0.27x [0.17, 0.32] | 0.30 | 74 |
| 3 | 5.03 / 8.50 s | 0.73x [0.66, 0.78] | 0.78x [0.64, 1.16] | 0.27 | 130 |
| 4 | 3.02 s (n = 2) | 0.42x (n = 2) | 1.08x [1.03, 1.23] (n = 6) | 0.30 | 77 |
| none | 5.66 / 9.00 s | - | - | 0.25 | 168 |

- **Timing:** against PH-strict, CMI's certificate comes before PH-strict's first plan at every
  certified level at 10 s, and at Levels 1-2 at 60 s. At 60 s Level 0 is 1.15x, and Level 3's
  interval reaches 1.16. Against PH as run (proofs borrowed, Section 11) the ratio rises with the
  level, 1.00-1.78x at 10 s; that comparison is not fair to CMI.
- **Uncertified runs excluded from the rows:** at FS 10 s these are 186 at Level 3, 11 at
  Level 4, 60 with no continuation and 16 unresolved. They are where the cost lies.
- **Checking is cheaper than producing:** replay takes about the production time at Level 0,
  half at Level 1, and a quarter to a third at Levels 2-4.
- **Certificate size** grows with the level: median 14 bound certificates at Level 0, 130 at
  Level 3 and 168 with no continuation (FS 10 s); up to 371 at LS Level 4, 60 s.
- **CPU split:** at Levels 0-1, setup and path search dominate (paths 50% at Level 1). From
  Level 2 the lower-bound certificates grow to 41-58% at Levels 3-4 and with no continuation.
  In uncertified 60 s runs the assignment search takes about half.

### A1/A3 with CMI-mu as the method (`results/a1_a3_strata_cmi_mu_2026_11_01/REPORT.md`)

Same script with `--method results/cmi_mu_2026_11_01`. Differences are arm minus CMI-mu, and
frozen CMI is listed as an arm. The reference also pools CMI-mu's plans.

A1, outside-U0 UAVs, arm minus CMI-mu, at reference Levels 3 and 4:

| Arm | FS 10 s, L3 | FS 60 s, L3 | LS 60 s, L3 | LS 60 s, L4 |
|---|---|---|---|---|
| CMI (frozen) | +0.09 [+0.03, +0.14] | +0.18 [+0.09, +0.28] | +0.26 [+0.16, +0.39] | +0.46 [+0.23, +0.74] |
| PH-strict | +0.09 [+0.04, +0.16] | +0.13 [+0.04, +0.23] | - | - |
| GR-c | +0.29 [+0.15, +0.44] | +0.44 [+0.28, +0.65] | +0.60 [+0.40, +0.83] | +0.25 [+0.00, +0.62] |

- The LS Level-4 stratum where GR-c changed fewer UAVs than CMI (-0.62) turns around: GR-c is
  now +0.25 against CMI-mu.
- At Level 3 CMI-mu changes fewer outside UAVs than PH-strict: +0.09 and +0.13 for PH-strict,
  intervals above 0. This is the first Q1 difference from the proof-free hierarchy, and it comes
  from the allowance proofs. Levels 0-2 are unchanged (all differences about 0).

A3 with CMI-mu:
- The level certificate is the same as CMI's by construction. The CPU differs only by run-to-run
  timing: medians are within about 10% of frozen CMI's, and the FS 10 s Level-0 median is
  0.55 s against 0.48 s.
- H3 against PH-strict stays below 1 at every certified level at 10 s (0.41-0.90x). At 60 s:
  Level 0 1.00x [0.89, 1.05]; Levels 1-2 0.23-0.26x; Level 3 0.67x [0.62, 1.01]; Level 4 0.86x
  [0.82, 0.99] (n = 6).
- Replay against production CPU and certificate sizes are as for CMI (0.21-0.94; Level 3 median
  130 certificates at FS 10 s).

## 17. B2: planted-minimum instances (1 November 2026; fixed before the run)

Script `scripts/run_planted.py`, config `configs/final_study/planted.json`.

What it tests: the true minimum level is fixed by construction, not by CMI. Each arm's
certificate and plan are then compared with it.

Construction:
- Gadgets: the analytic cases of `final_benchmark.controlled`.
  - C0 -> 0, C1 -> 1, C2 -> 2, C3 -> 3.
  - C4 -> 4 at b = 1, and -> 3 at b = 2.
  - Cinf -> no continuation (level 5 in the tables).
- Background: n = 1, 2 or 3 extra UAVs, each with one task of its own, in the unchanged west cell.
  - Speed: 2-3 times the fastest gadget UAV.
  - Deadline: its own exact flight time + 0.2%.
  - N1 is near due north and N2 near due south. N3 is north, 5% farther out than N1 and
    0.13 x its distance further west.
  - Sites lie on Pythagorean triples, so flight times are rational.
  - The west edge of the region and the west cell is moved from x = -2 to x = -3. It also
    stretches north and south to reach the sites. The gadget itself is unchanged.
- Each gadget gets 3 background sizes x 10 seeds, so 7 x 30 = 210 candidates. The seed draws
  the background speed and distances.
- All UAVs start idle at the depot (t = 0 only), because the v1 relaxation needs that.

Admission: all four conditions must hold, using v1 code that does not import `certify_v2`.
1. The affected set U0 is {U1}.
2. Isolation under the v1 axis-wise bound (`travel_lower_bound`):
   - no gadget UAV reaches a background task in time;
   - no background UAV can serve a gadget task before or after its own task;
   - no background UAV can serve two background tasks.
3. The planted plan passes `verify_local_witness` at exactly the planted level. The planted
   plan is the gadget's recovery with the background unchanged.
4. `physical_certificate` proves every lower level infeasible (through planted - 1, or through 4
   for Cinf), and `verify_physical_certificate` accepts it.

Refused candidates are logged in `ledger.json`.

Pre-run checks:
- First placement, with every site north: Cinf with 3 background UAVs failed condition 4. The
  axis-wise bound cannot rule out one UAV serving two northern tasks in a row. The placement
  above was chosen to close that gap.
- With that placement, all 210 candidates pass.
- Negative control: claiming the planted level one too high or one too low is refused in all
  11 cases tried. Too high fails condition 4; too low fails condition 3.

Arms:
- 10 s: all nine.
- 60 s: CMI, CMI-mu and PH-strict.

Endpoints:
- Certified minimum different from the planted level (target 0).
- Plan below the planted level (target 0, impossible by condition 4).
- Recall: certified at the planted level, by planted level.
- CMI-mu mu* against the construction: C3 1, and C4 2 at both b.

Smoke (`results/planted_smoke`):
- Sizes 1 and 3, seed 0, so 14 instances and 28 arena units.
- About 20 s of wall time, no failures, and all records replay.
- Certified minimum different from the planted level: 0 for every arm. Plan below the planted
  level: 0.
- Recall at 10 s and 60 s:
  - CMI, CMI-mu and noER: 14/14.
  - noAF: 11/14 at 10 s; it misses one Level-3 and both Level-4 instances.
  - PH, PH-strict, LR and GR-c: 2/14 (Level 0 only).
  - GR: 0.
- CMI-mu mu*: C3 1 (x2) and C4 2 (x4), as constructed.
- GR returned plans above the planted level on 5 instances, GR-c on 1 and noAF on 1.
- Caveat: these gadgets are small (4-6 UAVs, at most 6 tasks). B2 tests whether answers are
  correct against an independent ground truth, not how the method scales.

Full run (`results/planted_2026_11_01/REPORT.md`):
- 210 of 210 candidates admitted; 420 arena units; 3.8 min of wall time on 6 workers.
- No failures, and all records replay.
- Certified minimum different from the planted level: 0 for every arm at both budgets. Plan
  below the planted level: 0.
- Recall, the same at 10 s and 60 s:

  | Arm | Certified at the planted level | Where it falls short |
  |---|---:|---|
  | CMI, CMI-mu, noER | 210/210 | - |
  | noAF | 169/210 (10 s only) | 49/60 at Level 3, 0/30 at Level 4 |
  | PH, PH-strict, LR, GR-c | 30/210 | Level 0 only |
  | GR | 0/210 | - |

- noAF stops early; it does not time out. It finds the Level-4 plan, but with U0 masked to the
  whole fleet it cannot exclude the true Level 3. It ends with bracket [3, 4].
- Plans above the planted level: GR 85, GR-c 20, noAF 11. All other arms: 0.
- CMI-mu mu*: C3 1 (x30), C4 at b = 1 2 (x30), C4 at b = 2 2 (x30), all as constructed.
- CMI CPU per instance at 10 s: median 0.30 s, p90 0.77 s, maximum 1.02 s.

## 18. B4 as run: locality sweep (1 November 2026; fixed before the run)

Script `scripts/run_locality.py`, config `configs/final_study/locality.json`.

What it tests: Q1-Q3 against the affected share |U0|/M, between the local end (FS) and the global
end (S2-S5).

Changes from Section 5 (B4), each found before the run:
- **No time bins.** `certify_v2` rejects time-dependent wind (`stationary_wind_guard`), so
  locality comes from the update support only.
- **No 8 x 8 grid (decision D4: not used).** The scenario code accepts the finer grid as plain
  data, but path construction becomes about 5 times slower.
  - Same mission, same wind, same U0 = 3 UAVs, CMI at 10 s:
    - 4 x 4 grid: Level 2 certified at about 3.8 s, with 1.2 s in paths;
    - 8 x 8 grid: nothing within 10 s, with 6.7 s in paths.
  - In the 8 x 8 smoke (`results/locality_smoke`) CMI and PH returned no plan at 10 s in any
    band. A sweep on that grid would measure grid resolution, not locality.
- **Selector.** The first selector added cells that affect no UAV, which gave supports of up to
  50 of 64 cells. The rule below adds cells only for the UAVs they bring in.

Population:
- Missions: 90 (45 uniform, 45 clustered), seeds 77001 onward.
  - FS generator with 8 UAVs x 3 tasks and medium slack and battery.
  - The generator's own admission is the mission filter.
- Grid and update: the FS 4 x 4 grid, at t = 0. The update keeps the generator's wind vector
  (strength 3/5).
- Bands: |U0| = 1, 2, 3, 4, 6 or 8 of 8.
- Supports grow nested within each mission.
  - Start: the cell affecting the fewest UAVs (at least one).
  - Next cell: the 4-neighbour adding the most new affected UAVs without passing the next band.
    If none fits, the one adding the fewest.
  - A band takes the first support whose U0 has exactly that size.
- A band is admitted if:
  - it is reached;
  - the diagnosed |U0| equals the target;
  - the previous plan is still valid;
  - Level 0 is certified infeasible (the FS 30 s screen).

  Refusals are kept in the mission records.
- Probe on the 18 stored FS 8 x 3 missions: the band is reached on 16 / 9 / 8 / 11 / 11 / 18
  of the 18 missions, with supports of 1-7 cells.

Runs:
- Labels: CMI-mu at 600 s.
- Arena at 10 s: GR, GR-c, LR, PH, PH-strict, CMI and CMI-mu.
- All runs go through `run_instance` and are replayed.

Endpoints, by band:
- Q1: UAVs changed and outside-U0 UAVs, CMI-mu minus GR, GR-c, PH-strict and CMI, paired on
  common plans (95% interval over missions). Also the plan-returned share, CMI-mu minus each arm.
- Q2: certification at 10 s and 600 s, and the label minimum distribution.
- Q3: CMI-mu certificate CPU, and its median over the PH-strict first-plan median.

Smoke on the 4 x 4 grid (`results/locality_smoke_4x4`):
- 4 missions gave 11 admitted bands. There were no failures, and all records replay (11/11
  labels, 77/77 arena).
- At 10 s, CMI-mu certified 1, 1, 1, 2 and 0 instances in bands 1, 2, 4, 6 and 8 (band 3 had
  no instance). Its median certificate CPU was 2.8-5.6 s.
- In band 8, CMI and PH returned no plan at 10 s, while GR returned 3 of 4. This is the same
  global-end pattern as S2-S5.
- Too small for conclusions.

Full run (`results/locality_2026_11_01/REPORT.md`):
- 90 of 90 missions were accepted by the generator. 229 bands were admitted.
- Wall time: 8 min to build and 81 min for the 458 label and arena units, on 6 workers.
- No failures. All records replay: 229/229 labels and 1,603/1,603 arena results.

Admitted per band (|U0| = 1 / 2 / 3 / 4 / 6 / 8): 23 / 26 / 20 / 37 / 36 / 87.
- Most refusals at |U0| = 1 are `not_disrupted` (44 of 67 reached): a small update on one UAV
  often leaves the old plan feasible.
- In the middle bands most refusals are `not_reached`: the growth skipped that count.
- Missions do not appear in every band, so bands differ in mission mix. Comparisons are paired
  only across arms on the same instance.

| Band (UAVs) | Label certified at 600 s | Label minimum 1/2/3/none | Label certificate CPU, median | CMI-mu certified at 10 s | Plan at 10 s, CMI-mu / PH-strict / GR-c / GR |
|---|---:|---|---:|---:|---|
| 1 | 22/23 | 6/7/9/0 | 2.6 s | 17/23 (74%) | 19 / 19 / 23 / 22 |
| 2 | 26/26 | 6/7/13/0 | 3.0 s | 16/26 (62%) | 16 / 15 / 26 / 25 |
| 3 | 20/20 | 6/4/9/1 | 4.8 s | 11/20 (55%) | 11 / 11 / 19 / 19 |
| 4 | 37/37 | 13/9/14/1 | 3.5 s | 23/37 (62%) | 23 / 23 / 36 / 36 |
| 6 | 32/36 | 7/8/15/2 | 18.6 s | 13/36 (36%) | 13 / 12 / 33 / 33 |
| 8 | 79/87 | 5/8/48/18 | 43.1 s | 9/87 (10%) | 9 / 7 / 66 / 67 |

Findings:
- **Q1 holds at every band.** On common plans CMI-mu changes fewer UAVs than GR and GR-c, with
  intervals below 0 in every band:
  - against GR: -5.3 to -6.8 UAVs;
  - against GR-c: -0.64 to -1.44 UAVs.

  Against GR-c, the outside-U0 difference is -0.55 to -0.69 in bands 1-4. It is -0.31
  [-0.69, 0.00] at band 6, and 0 at band 8, where no UAV is outside U0. Against PH-strict and
  CMI it is about 0, as on FS.
- **Recovery at 10 s is where locality matters.** The share of instances with a plan, CMI-mu
  minus GR-c:

  | Band | 1 | 2 | 3 | 4 | 6 | 8 |
  |---|---|---|---|---|---|---|
  | Difference | -0.17 [-0.35, -0.04] | -0.38 | -0.40 | -0.35 | -0.56 | -0.66 [-0.76, -0.55] |

  PH-strict matches CMI-mu (intervals include 0), so the loss belongs to the minimal-level
  hierarchy, not to the certificate. The cause is Level 3: the label minimum is Level 3 on 39%
  of band-1 instances and 55% of band-8 instances, and at 10 s CMI-mu reaches few Level-3
  plans.
- **Q2.** At 600 s, label certification is 89-100% in every band. At 10 s it falls with
  locality, from 74% at |U0|/M = 1/8 to 36% at 3/4 and 10% at 1. The no-continuation share
  rises at the global end (18 of 87 at band 8).
- **Q3.** Label certificate CPU (median) grows from 2.6-4.8 s in bands 1-4 to 18.6 s at band 6
  and 43.1 s at band 8. At 10 s, the median CMI-mu certificate over the median PH-strict first
  plan is 0.39-0.58x in bands 1-6 and 1.16x at band 8. These are medians over the instances
  each arm solved, so they carry a selection effect.
- **Break-even.** In decisions changed, there is none: CMI-mu never changes more UAVs on a
  common plan. In plans returned within 10 s, the minimal-level arms trail GR-c at every band.
  The gap grows sharply from |U0|/M = 3/4, where 10 s certification falls to 36% and then 10%.
- **Ten seconds and 600 s disagree.** At 600 s, the method certifies 89-100% at every band. At
  10 s, the method's advantage holds only for local updates.

## 19. B5 as run: escalation staircase (1 November 2026; fixed before the run)

Script `scripts/run_staircase.py`, config `configs/final_study/staircase.json`.

What it tests: theory T3. As the wind gets stronger, does the certified minimum level k^F(alpha)
form a staircase (never decreasing, with thresholds alpha*_k)? The formulation does not
guarantee this. A stronger wind in a fixed direction also helps the legs flying with it.

Design:
- Missions: the 53 FS missions of the 60 s third, each with its stored reference variant, update
  cell and direction, at t = 0.
- Strengths: alpha = j/20 of the slowest airspeed, j = 1..16, so 0.05-0.80. The plan was 12
  steps of 1/15, but wind components must be terminating decimals and the directions have
  fifths.
  - j = 8, 12 and 16 are the FS strengths 2/5, 3/5 and 4/5. They keep the FS ids and must
    reproduce the FS payloads and labels.
- Labels: CMI at 600 s, replayed.
- Violations: a certified violation is a pair j_1 < j_2 whose lower bound at j_1 is above the
  upper bound at j_2.
- Thresholds: alpha*_k is the first j at which k^F > k and stays above it. It lies in
  ((j-1)/20, j/20].

Smoke (`results/staircase_smoke`): 2 missions x 16 strengths at 60 s. No label failures, and all
records replay. The FS payloads (6/6) and labels (6/6) match.

Both the smoke and the full run exited with a `UnicodeEncodeError` when printing the report ('∞' on
the cp1252 console). REPORT.md is written before the print, so no results were lost. Fixed by
switching stdout to UTF-8 before the print; rerunning `--stage report` reproduces REPORT.md byte for
byte.

Full run (`results/staircase_2026_11_01/REPORT.md`):
- 848 labels in 18 min on 6 workers, with no label failures.
- Integrity:
  - replays: 848/848;
  - FS-strength payloads equal the stored FS variants: 159/159;
  - their labels give the stored FS label bounds: 159/159;
  - U0 is the same at every strength: 53/53 missions.
- Certification: 837 of 848 labels certified. The 11 unresolved are on 3 missions:
  76053 at j = 8 ([1, 2]); 76079 at j = 8, 9 ([1, 3]); 76074 at j = 9-16 ([1, 3]).
  All 11 stopped at 13-89 s CPU of the 600 s budget with levels 1-2 open, so the gaps are
  not budget limits.
- **No certified violation: 0 pairs.** 50 of 53 staircases are fully certified and
  non-decreasing. The other 3 contain no certified violation, and the resolved points around
  their brackets are consistent with a staircase. The theory's caveat (stronger wind need not
  degrade feasibility) does not appear in this sample, which uses one cell and a fixed
  direction.
- Shape:
  - 43 of the 50 certified staircases have one step, and 7 have two.
  - 23 skip a level, most often jumping from 0 straight to 3.
  - Final levels: 1 on 25 missions, 2 on 8, 3 on 17. Level 4 and no continuation never occur.
- Saturation: the level at 3/5 (the FS reference) equals the level at 4/5 on 49 of 50
  missions. Strengthening further mostly does not escalate.
- Thresholds (counts of missions by the j at which the level is first exceeded):
  - alpha*_0: spread over j = 2-12, with modes at j = 4 (10 missions), j = 2 (7) and
    j = 3, 10 (6 each).
  - alpha*_1 and alpha*_2: mostly j = 2-4, because many missions jump from 0 straight to 3.
- For the paper: one figure, k^F against alpha per mission (or as shares per level). It shows
  the staircase, the level skips and the saturation. Whether it fits on the page is still open
  (D2).
