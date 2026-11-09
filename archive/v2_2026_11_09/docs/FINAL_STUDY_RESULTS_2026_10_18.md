# Final study: results (run of 17-18 October 2026)

The full run of the final study under `configs/final_study/final.json`, after the
amendments of 15-17 October (`FINAL_STUDY_CONFIRMATION_PILOT_2026_10_15.md`). Every number
below is from the run's report, `results/final_study_2026_10_17/analysis/REPORT.md`.

## The run

- Run `results/final_study_2026_10_17`, run hash `cbd0f487a0ab342c...`. Code and
  configuration are bound by the manifest and `source.zip`.
- Laptop (Windows 11, 16 logical CPUs, Python 3.10), 6 workers. The CPU times run about
  1.5 times higher with 6 workers than with 1 (contention stage, median 1.51).
- Started 17 October at 18:07, finished 18 October at 19:17.
- **Interruption.** The process ended at 04:20 on 18 October with no error message and no
  sleep or restart event in the system log. The run was resumed at 10:00 with the same
  command, which keeps every finished unit, so no completed work was lost. It then ran as a
  process independent of the session. About 25 hours elapsed, of which about 19.5 were
  computing (10 h 13 min before the interruption, 9 h 17 min after).
- **Report regenerated.** On 19 October the report was regenerated from the stored records,
  opened read-only, after a fix to the report code (the ordinal regression, below). No
  result record changed. The report as first produced is kept as `REPORT_as_run_2026_10_18.md`.
- **Reporting review applied, 19 October.** Q1 now uses all variants, with the conditional
  known-minimum rate shown separately. Tables and curves use accepted events at or before
  the CPU cutoff, baseline Level-0 certificates are included, matched-subset comparisons
  and overruns are reported, and the post-plan timing statistic is labelled explicitly.
  The pre-review analysis and source/docs are preserved in
  `artifacts/final_study_reporting_review_2026_10_19/`. Methods and raw records are unchanged.
  A same-day follow-up scores outcomes from the plan each arm returned (stored and
  replayed) rather than the lowest plan logged during its search (protocol Section 13.2);
  the output under the logged-plan rule is kept in `analysis_logged_plan_rule/` there.
- 645 MB on disk, proof files included.

| Stage | Units | Time |
|---|---|---:|
| `fs-generate` | 162 missions, 1,221 update draws | 12 min |
| `fs-label` | 1,440 variants, CMI at 600 s | 44 min |
| `fs-arena-short` | 1,440 x 7 arms at 10 s | 3 h 20 min |
| `fs-arena-long` | 477 x 5 arms at 60 s | 40 min |
| `ls-build` | 3,312 draws, 1,119 admitted and labelled | 5 h 17 min before the interruption + 5 h 24 min after |
| `ls-arena-short`, `ls-arena-long` | 330 LS instances | 1 h 32 min |
| `p1-label`, `p1-arena` | 700 P1 variants | 41 min |
| `xr` | 360 chains, 1,800 variants | 22 min |
| `scaling` | 40 larger missions at 60 s and 300 s | 31 min |
| `fs-d1`, `contention`, `gr-seeds`, `report` | | 47 min |

## Integrity

- Every result replays with the independent checker: **20,655 of 20,655** arena results and
  **4,219 of 4,219** reference labels. Every proof is stored with its result.
- **No cross-check violation** in any set or budget: no plan below a proven lower bound, and
  no proof above a known plan.
- **No unit and no stage failed.**
- P1: **0 disagreements** with any v1 certificate (700 variants).

## Factorial study (FS)

**Population.** 160 of 162 missions were admitted after 1,221 update draws (13.1% of draws).
Of the rejected draws, 50% were not local and 37% did not break the plan. The two missing
missions are both 6 drones x 4 tasks with loose slack and ample battery: no update in 48
draws broke their plans. FS therefore has 1,440 variants, against 1,458 planned. Its shares
are shares of *disrupted* missions (scenario design, Section 4).

**The five metrics** (600 s reference pooled with every arm's plans; 95% intervals from a
bootstrap over missions):

| Metric | Value |
|---|---:|
| Certification rate | 98.9% [97.8, 99.7] |
| Unresolved rate | 1.1% [0.3, 2.2] |
| CPU to certificate, median / p90 | 1.41 s / 17.38 s |
| Recovery success, all variants | 92.6% [90.3, 94.8] |
| Recovery success, recoverable variants | 99.9% |
| Certified unrecoverable (no continuation) | 7.1% [5.0, 9.3] |

**Required level.** Level 0: 17.3%. Level 1: 41.3%. Level 2: 4.4% (18 missions). Level 3:
27.8%. Level 4: 0.9% (13 variants, 6 missions). No continuation: 7.1%. Unresolved: 1.1%.

Targets set in advance:

- Level 1 and Level 3: **met**.
- Level 2 (at least 20 missions; 18 observed): **missed**.
- Level 4 (at least 3% and 10 missions): **missed**.
- Unresolved at most 5% (1.1%): **met**.

Within disrupted missions, Level 2 and Level 4 are rare. That is why the level suite
exists.

**What moves the required level** (interval-censored ordinal regression, errors clustered
by mission; both models converge, largest gradient below 1e-5):

- Wind strength raises it: odds ratio 2.74 at 3/5 and 3.42 at 4/5, against 2/5.
- Loose slack lowers it: odds ratio 0.19 against tight.
- Fleet size, tasks per UAV, battery margin and update time show no clear effect once the
  others are held fixed.
- Of the eight interaction blocks tested (mission factors x strength and x update time),
  only **slack x strength** is clearly non-zero (Wald chi2 32.5, 4 df, p < 0.001). Fleet x
  update time is borderline (p = 0.066). No correction for multiple tests.
- The update time changes the mix rather than the level. At half the makespan, Level 0
  rises to 26% and no continuation to 17%, against 10% and 1% at t = 0, and recovery
  success falls to 83.3%.

## Equal-resource comparison

**FS at 10 s** (1,440 instances). The primary Q1 denominator is all 1,440 variants.
The conditional secondary rate uses the 1,322 variants with a known finite minimum;
102 certified unrecoverable and 16 unresolved variants are excluded only from that
secondary denominator. An unresolved minimum is not a verified success, rather than
proof that a plan is nonminimal.

| Arm | Plan at minimum, all 1,440 (Q1) | Plan at minimum, known 1,322 | Certified | Recovery success | UAVs changed per returned plan |
|---|---:|---:|---:|---:|---:|
| CMI | 78.1% [72.9, 83.0] | 85.1% | 81.0% [76.2, 85.7] | 78.4% | 1.12 |
| PH (no exclusion proofs) | 81.3% [76.9, 85.5] | 88.6% | 17.3% (Level 0 only) | 82.5% | 1.20 |
| LR (local repair) | 71.5% [66.0, 77.0] | 77.8% | 17.3% (Level 0 only) | 73.5% | 1.11 |
| GR-c (global, from the incumbent) | 40.7% [36.7, 44.9] | 44.3% | 17.3% (Level 0 only) | 75.7% | 1.62 |
| GR (global replanning) | 9.4% [7.2, 11.8] | 10.3% | 2.8% (Level 0 only) | 70.4% | 4.77 |
| noAF (no affected-fleet identification) | 72.8% | 79.3% | 75.3% | 73.8% | 1.06 |
| noER (no evidence reuse) | 69.7% | 75.9% | 70.4% | 69.7% | 0.98 |

Outcomes score the plan each arm returned, if it replays and was returned by the 10 s
cutoff; only that plan is stored and independently replayed. In 16 GR runs and 1 GR-c
run the search logged a lower-level plan than the one returned; such plans are not
credited (the logged-plan rule had given GR 140 minimum-level plans and GR-c 587). A
further 19 GR runs returned their plan only during an operation overrun, after 10 s, and
count as having no plan by the cutoff: GR's recovery success is 70.4%, or 71.7% if those
late returns are counted. PH, LR and GR-c each establish 249 Level-0 minima, and GR 40.
Only CMI arms certify positive intervention minima or no continuation.

**FS at 60 s** (53 missions; 477 instances): CMI certifies 95.6% [91.4, 99.0]. Its
minimum-level success is 412/477 = 86.4%, versus PH's 403/477 = 84.5%. Conditional on
the 417 known finite minima, the rates are 98.8% and 96.6%; LR, GR-c and GR achieve
73.6%, 40.5% and 9.1%, respectively, on that conditional denominator.

The added exploratory paired CMI-minus-PH interval is **+1.9 percentage points
[-0.8, 5.5]** over all 477, or **+2.2 [-1.0, 6.3]** conditional on the 417 known minima.
Both include zero, so the observed advantage does not establish superiority. These
intervals use the report's 2,000 mission-cluster bootstrap resamples, seed 1; the earlier
review's exploratory 5,000-resample calculation differs slightly in its endpoints.

On the **same 477-instance subset**, CMI certification rises from **368/477 = 77.1% at
10 s to 456/477 = 95.6% at 60 s**, a paired increase of **18.4 percentage points
[10.5, 27.0]**. The all-FS 81.0% figure is a different cohort.

**Hypotheses** (directions fixed in advance; arm comparisons paired by instance):

| Hypothesis | Observed | Verdict |
|---|---|---|
| H1: GR changes more UAVs than CMI | CMI minus GR -3.46 [-3.75, -3.18] UAVs, 857 paired returned plans by cutoff | supported |
| H1: LR reaches the minimum less often than CMI | 78.1% vs 71.5%; difference 6.7 percentage points [2.9, 10.5], all FS | supported |
| H1: PH reaches the minimum less often than CMI | 78.1% vs 81.3%; difference -3.2 percentage points [-5.0, -1.5], all FS | not supported: PH does better at 10 s |
| H2: observed certification rate meets 80% | 81.0% | target met |
| H2: underlying rate exceeds 80% | lower bound 76.2% | not established |
| H2: every certificate replays, no plan contradicts a proof | 100%, 0 violations | supported |
| H3: certificate within 3x PH's time to its first plan (paired) | 1.13x [1.08, 1.17] on the same 1,122 instances; CMI did not certify 273, PH found no plan on 252 | supported |
| H3: noAF costs more than CMI | 5.7% [3.6, 8.1] fewer certificates | supported |
| H3: noER costs more than CMI | 10.6% [7.8, 13.6] fewer certificates; +0.56 s paired | supported |

Notes:

- At 10 s PH reaches the minimum more often than CMI; CMI also spends budget on proofs.
  At 60 s the point estimate favors CMI, but the paired interval includes zero.
- The returned plan is above the reference minimum on 868 GR instances, 498 GR-c
  instances, 24 LR instances, 8 PH instances and no CMI instances. Baselines do
  not assert optimality; these are intervention gaps, not false claims.
- The median additional delay after the certified-level plan is 0 s. This is the unchanged
  statistic previously called "proof overhead" and excludes proof computation before the
  plan. The paired CMI/PH timing ratio and coverage give a more useful cost comparison;
  the 1.13x ratio applies to the 1,122 common successes, not every instance. Independent
  replay takes a median 0.8 s.

**Overruns.** Full per-arm counts and maxima are in report Section 9c. At FS 10 s,
CMI overruns on 226/1,440 runs (maximum 0.938 s), and noER on 356/1,440 (2.734 s).
At FS 60 s, PH overruns on 29/477 runs (7.125 s maximum); its LS 60 s maximum is
7.891 s. Runtime includes this work, but tables and curves exclude late events. There
are no late CMI certificates in these arenas. Only GR and GR-c ever returned a plan after
the budget: 19 GR runs at FS 10 s (above), and 3 GR and 1 GR-c runs at LS 10 s, which
lowers their LS recovery counts from 171 to 168/330 and from 161 to 160/330.

## Level suite (LS)

All 15 cells are filled: 60 instances in each of Levels 1, 2, 3, 4 and no continuation,
20 per fleet size, from 300 distinct base missions, plus 30 hard instances.

- 3,312 draws, 1,119 admitted and labelled; 2.8% were left undecided at the reference
  budget.
- **Level 4:** 60 instances. 31 come from the chain construction, 12 from the deficit
  construction and 17 from draws aimed at other classes. Update times split 19 at t = 0,
  21 at t = 1/4 and 20 at t = 1/2. Three of the 60 are certified by pooling the label with
  the construction's exact-checked witness.
- **Level 2:** 10 of the 60 reference plans add a depot stop; 50 only reorder.

CMI by class (certified within the budget; LS holds instances v2 certifies at 600 s, so
these are rates within each class, not general performance):

| Class | 10 s | 60 s |
|---|---:|---:|
| Level 1 | 100% | 100% |
| Level 2 | 100% | 100% |
| Level 3 | 25% | 95% |
| Level 4 | 8% | 63% |
| No continuation | 25% | 90% |

Level 4 is the hardest class to certify quickly. At 60 s, GR's global replans reach the
Level-4 minimum on 40% and CMI on 65%.

## Secondary results

- **P1** (700 earlier variants): v2 certifies 696 at 600 s, including 282 of the 286 that v1
  had left open. At 10 s it decides 82.1%, so the method criterion of 90% is **missed**.
- **Reuse across a mission's deadline variants (XR):** 98.3% certified with reuse against
  93.1% for each variant alone, at about half the CPU (0.52 h against 0.94 h).
- **Larger missions** (R1's 40, 24-48 tasks; regenerated identically to R1). CMI decides
  88% at 60 s and 95% at 300 s. The criterion of 75% within 60 s is met. Of the 24 that R1
  left unresolved, CMI decides 79% at 60 s and 92% at 300 s; every plan it finds there is at
  Level 3. The baselines certify none of these 24.
- **In-flight rule** (960 in-flight FS variants). Under D1 (an airborne UAV keeps its
  destination), 136 of the variants with a Level 2-4 minimum under the primary rule D1'
  have no continuation. The primary rule matters for in-flight recovery.
- **GR seeds:** results for seeds 0, 1 and 2 agree closely (plan at minimum, all instances:
  7% for GR, 37-40% for GR-c).

## Limitations

- FS shares are frequencies among disrupted missions, not general frequencies. LS rates
  hold within LS's selection.
- H2's underlying rate above 80% is not established. The CPU budgets ran on a laptop where
  6 workers inflate CPU time by about 1.5x.
- Level 2 and Level 4 are rare in FS: their FS-based estimates rest on 18 and 6 missions.
- The run was interrupted once and resumed; finished units were kept, so this affects only
  the elapsed time.
