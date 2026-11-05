# Escalation study: primary results (9 October 2026)

Plan: `docs/EXPERIMENT_REDESIGN_PLAN_2026_10_07.md`. Guide and commands:
`docs/ESCALATION_STUDY.md`. Calibration: `docs/ESCALATION_PILOT_RESULTS_2026_10_08.md`.

All runs used the frozen configurations in `configs/escalation_study/` and the
code in this folder. They ran on the laptop (Windows 11, Python 3.13.3, 16
logical CPUs, 6 worker processes) on primary seeds 72001-72020, which the pilot
never used.

## Runs and checks

| Study | Directory under `results/` | Units | Wall time | Checks |
|---|---|---|---:|---|
| P1 | `escalation_study_primary` | 120 missions, 1,800 variants | 1.6 h (6.3 CPU-h) | Linux re-audit of six of the hardest missions (164 records) passed |
| Comparators C1-C3 | `escalation_study_comparators` | 700 variants x 3 policies | 1.4 h | `compare-audit` passed on the laptop; Linux re-check of 8 missions (103 variants, 59 plans) passed |
| R1 runtime profile | `escalation_study_r1_budget_third`, `..._r1_uncontended`, `..._r1_large` | 30 + 30 variants, 40 larger missions | 40 min | Linux re-run of `large-audit` on all 40 records passed |
| E1 in-flight updates | `escalation_study_e1_primary` | 240 snapshots, 1,200 variants | 30 min (1.7 CPU-h) | Linux re-audit of 6 snapshots (38 records) passed |

The full `audit` commands ran on the laptop; they print their result rather than
save it, so the independent re-audits above are the recorded check. All 120 P1
missions and all 240 E1 snapshots were admitted; 53 P1 draws were rejected as
not local (U0 empty or larger than two UAVs), as the admission rule requires.

## P1: minimum intervention for an update at t = 0

Certified minimum level of all 1,800 variants (120 missions x 3 wind strengths x
5 deadline slacks):

| Level 0 | Level 1 | Level 2 | Level 3 | Level 4 | No continuation | Unresolved |
|---:|---:|---:|---:|---:|---:|---:|
| 1,100 (61%) | 216 (12%) | 1 | 76 (4%) | 12 (1%) | 109 (6%) | 286 (16%) |

An unresolved variant still has certified bounds. 203 of the 286 are certified
to need at least Level 3. Grouping each variant by what its certificates
establish:

| Slack (x makespan) | Certified Level 0-1 | Certified Level 3 or more, or no continuation | Still open |
|---|---:|---:|---:|
| 1/10 | 345 (96%) | 11 (3%) | 4 (1%) |
| 1/30 | 310 (86%) | 40 (11%) | 10 (3%) |
| 1/100 | 253 (70%) | 90 (25%) | 17 (5%) |
| 1/300 | 213 (59%) | 121 (34%) | 26 (7%) |
| 1/1000 | 195 (54%) | 138 (38%) | 27 (8%) |

Each slack row holds 360 variants. "Still open" is the one Level-2 variant plus
unresolved variants whose lower bound is 1 or 2.

Findings:

1. **Deadline slack drives the minimum.** Level 0 falls from 89% of variants at
   slack 1/10 to 42% at 1/1000, and the share certified to need Level 3 or more,
   or to have no continuation, rises from 3% to 38%.
2. **Intermediate levels are almost empty.** Level 2 is the minimum in one
   variant and Level 4 in 12. When path repair fails, the minimum usually jumps
   to reassignment (Level 3) or to no continuation.
3. **Tasks per UAV change how missions fail.** With one task per UAV, failure
   mostly means no continuation (101 of 600 variants, against 8 of 600 with
   three tasks). With two or three tasks per UAV, the harder variants are mostly
   Level 3 or unresolved.
4. **A stronger wind needs more.** Level 0 covers 70%, 61% and 52% of variants at
   strengths 1/5, 2/5 and 3/5. A stronger wind never lowered the certified level
   of a mission at the same slack (981 pairs).
5. **Most updates delay a delivery.** In 211 of the 360 mission-strength pairs
   (59%) the update certifiably delays at least one incumbent delivery; in the
   rest every variant is Level 0.
6. **Unresolved variants come from search caps.** They mostly stopped at the
   Level-3 or Level-4 search cap after pass 2 (387 variants entered pass 2; 101
   closed there). The share is 8%, 17% and 22% for 4, 8 and 12 tasks, below the
   plan's one-quarter threshold for dropping n = 12.

Mission-level 95% intervals (bootstrap over missions) are in
`analysis/shares_pooled.csv` and `analysis/shares_by_tasks.csv`, with
identification bounds that place each unresolved variant in every category its
bounds allow. For example, at strength 2/5 and slack 1/1000 Level 0 covers 42%
(95% interval 33-50%).

![P1 level shares](../results/escalation_study_primary/analysis/level_shares.png)

### Time to certificate

Over the 1,514 certified variants, the median wall time to a full certificate
was 0.46 s, the 90th percentile 7.6 s and the maximum 70 s (pass 2 included).
Fraction certified within a wall-time budget (`analysis/certified_by_wall_budget.csv`):

| Tasks per UAV | 1 s | 8 s | 30 s | 120 s |
|---|---:|---:|---:|---:|
| 1 | 76% | 80% | 89% | 92% |
| 2 | 69% | 79% | 82% | 83% |
| 3 | 55% | 68% | 74% | 78% |

No variant was certified after 70 s; the rest are unresolved.

## Comparators

The comparators ran on the 700 P1 variants whose certified lower bound is at
least 1: 305 with a finite certified minimum, 109 with no continuation and 286
unresolved.

| Policy | Plans found | At the certified minimum | Above it | Median UAVs changed | Median s to first plan |
|---|---:|---:|---:|---:|---:|
| C1 finite axis-path library | 0 | 0 | 0 | - | - |
| C2 global first | 112 | 10 | 101 | 4 | 21.5 |
| C3 time-sliced escalation | 225 | 215 | 0 | 1 | 3.6 |

C2 also found one plan and C3 ten plans for unresolved variants, whose minimum is
not known.

- **C1** found no plan at all: its library has only L-shaped paths between
  sites, too slow for these deadlines.
- **C2** over-intervened in 101 of its 111 plans on variants with a known
  minimum; 78 of them change all four UAVs, and every C2 plan changes UAVs
  outside U0.
- **C3** always returned the minimum level when it found a plan, quickly, but it
  found plans for 204 of the 216 Level-1 variants, 10 of the 76 Level-3 variants
  and none of the 12 Level-4 variants. It cannot prove minimality or
  infeasibility.
- **Consistency with P1.** No comparator found a plan for any of the 109
  variants P1 certifies as having no continuation, or below a certified minimum,
  and no comparator plan closes an unresolved variant.

## R1: runtime profile

R1 reruns make one pass, so they are compared with the 15 of their 30 variants
that P1 closed in pass 1.

- **Contention.** On one worker all 15 kept their category and wall times were
  38% shorter. Wall times from the 6-worker runs include about 1.6x contention;
  report CPU time or this factor.
- **One-third budget.** With every stage cap divided by 3, 12 of the 15 kept
  their category. The three lost certificates needed the screen to run up to or
  past its reduced 3.3 s cap, or borrowed a witness from a variant that did. The
  budget curve above is therefore approximate near the caps.
- **Larger missions** (24 or 48 tasks, 6 or 8 UAVs, strength 2/5, slack 1/1000,
  one 60 s cap; 10 missions per size). All 40 were generated. The certified
  minimum is known for 16 (13 at Level 0, 2 at Level 1, 1 at Level 3). In the
  other 24, Levels 0-1 are certified insufficient (in one also Level 2), but no
  witness was found within the cap; the screen used the whole minute in most of
  them. This marks the method's present size limit.

## E1: the same update arriving in flight

The P1 update at strength 2/5 arrives at 1/4 or 1/2 of the makespan; t = 0 is
the P1 result for the same missions and slacks. Each row holds 600 variants (120
missions x 5 slacks).

| Update at | Level 0 | Level 1 | Level 2 | Level 3 | Level 4 | No continuation | Unresolved |
|---|---:|---:|---:|---:|---:|---:|---:|
| t = 0 | 365 (61%) | 73 (12%) | 1 | 25 (4%) | 4 (1%) | 36 (6%) | 96 (16%) |
| 1/4 x makespan | 386 (64%) | 57 (10%) | 0 | 0 | 0 | 98 (16%) | 59 (10%) |
| 1/2 x makespan | 437 (73%) | 47 (8%) | 0 | 0 | 0 | 101 (17%) | 15 (3%) |

Findings:

1. **A later update usually needs less.** Level 0 rises from 61% to 73%. In 95
   variants at t = 1/2 (10 at t = 1/4) no remaining leg crosses the changed
   cell, so U0 is empty.
2. **In flight, failures become infeasibility.** No continuation rises from 6%
   to 16-17%. In 198 of the 199 in-flight cases the cause is the
   committed-destination certificate: under D1 an airborne UAV must deliver to
   the destination it is flying to, and even its fastest path arrives after that
   task's deadline (certified directly in 61 variants and carried to tighter
   slacks in 137). For example, in P1_12_4_clustered_72001 at t = 1/2 and slack
   1/100, U3 cannot complete its delivery at T11 until at least 0.026 h (about
   1.6 min) after the deadline.
3. **No in-flight variant has a certified minimum at Level 2-4.** Of the 29
   variants that need Level 3 or 4 at t = 0, at t = 1/4 14 have no continuation,
   13 are unresolved and 2 need nothing; at t = 1/2, 17 have no continuation, 9
   need nothing, 2 are unresolved and 1 needs Level 1.
4. **Unresolved variants shrink** from 16% at t = 0 to 10% and 3%. Of the 96
   variants unresolved at t = 0, 47 (t = 1/4) and 55 (t = 1/2) are certified to
   have no continuation in flight, and 10 and 30 need nothing.

The infeasibility in finding 2 follows from decision D1, not from the search. A
rule that lets an airborne UAV divert or hand over its load could make some of
these cases recoverable, so the paper should state D1 next to this result.

![E1 level shares](../results/escalation_study_e1_primary/analysis/level_shares_by_update_time.png)

## For the manuscript

- **Main figure:** P1 level shares against slack (`results/escalation_study_primary/analysis/level_shares.pdf`).
- **Comparator table:** the table above; C3 is the strongest baseline, C2 shows
  over-intervention, C1 the limits of a finite path library.
- **Runtime:** the time-to-certificate table, CPU times (wall times carry about
  1.6x contention), and the larger-mission result as the size limit.
- **E1 panel:** `results/escalation_study_e1_primary/analysis/level_shares_by_update_time.pdf`
  with a paragraph defining D1-D3.
- **Unresolved variants** are reported with their certified bounds. Only the
  "still open" column (at most 8% per slack) is undecided between "Level 0-1"
  and "Level 3 or more".

## Caveats

- The P1 grid uses slacks of 1/10 to 1/1000 of the makespan, chosen in the pilot
  because looser slacks left almost every variant at Level 0.
- 16% of P1 variants (10% and 3% in flight) are unresolved within the
  pre-declared caps. A separate rerun with longer caps for just those variants
  would narrow the bounds; it would be reported apart from these results.
- Two stray copies, `src/continuous/search-1.py` and `search-2.py`, are part of
  every primary run's source archive. Nothing imports them.
- Pilot results and calibration are in `docs/ESCALATION_PILOT_RESULTS_2026_10_08.md`.
