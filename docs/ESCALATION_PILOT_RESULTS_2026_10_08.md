# Escalation study pilot: results and calibration (8 October 2026)

Plan: `docs/EXPERIMENT_REDESIGN_PLAN_2026_10_07.md` (Section 7, step 2). Guide:
`docs/ESCALATION_STUDY.md`. The pilot uses seeds 71001-71002, which the primary
runs never reuse. Its purpose is calibration and a full dry run of every
command; it is not evidence for the paper.

All numbers below come from the run directories listed at the end. They were run
on a 2-core cloud container with 2 worker processes, so wall times include
contention and will differ on the laptop.

## What was run

| Run | Units | Outcome |
|---|---|---|
| Diagonal-wind control (plan 2.3) | 12 directions x 3 strengths x 3 airspeeds x 5 chords; 24 all-path bounds | 20 tests pass. Certified chord durations enclose the closed form exactly (largest relative difference 3e-16); every verified all-path lower bound is below it and within 2.5e-9 h. |
| P1 pilot | 12 missions x 3 strengths x 7 slacks = 252 variants | 252 certified (243 in pass 1, 9 in pass 2); audit passed (261 records) |
| E1 pilot | 12 missions x 2 update times x 7 slacks = 168 variants at strength 2/5 | 24 of 24 snapshots admitted; 163 certified, 5 unresolved; audit passed (173 records) |
| Comparators C1-C3 | the 76 P1 pilot variants with certified lower bound >= 1 | every returned plan re-verified (76 variants) |

The pilot slack grid was 2/5, 1/10, 1/20, 1/50, 1/100, 1/300, 1/1000 of the
incumbent makespan, wider than the plan's 2/5-1/50, to find where levels change.

## Admission (P1)

All 12 missions were admitted. Two needed extra draws: 6 draws were rejected
because more than m/2 = 2 UAVs were affected. No draw failed the previous
premise and U0 never varied across a mission's variants. U0 had one UAV in 6
missions and two in 6.

## P1 outcomes

Certified minimum level by slack, pooled over the three strengths (36 variants
per slack, one per mission and strength):

| Slack | Level 0 | Level 1 | Level 2 | Level 3 | Level 4 | No continuation | Unresolved |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2/5 | 36 | 0 | 0 | 0 | 0 | 0 | 0 |
| 1/10 | 33 | 2 | 0 | 1 | 0 | 0 | 0 |
| 1/20 | 30 | 2 | 0 | 2 | 0 | 2 | 0 |
| 1/50 | 25 | 5 | 0 | 2 | 0 | 4 | 0 |
| 1/100 | 21 | 8 | 0 | 3 | 0 | 4 | 0 |
| 1/300 | 17 | 11 | 0 | 3 | 0 | 5 | 0 |
| 1/1000 | 14 | 13 | 0 | 3 | 0 | 6 | 0 |

At strength 2/5 alone (12 missions per slack), the tightest slack 1/1000 gives
5 Level 0, 4 Level 1, 1 Level 3 and 2 with no continuation. The figure is
`analysis/level_shares.png` in the P1 pilot run.

Findings:

1. **The update is small relative to the makespan.** Across the 36
   mission-strength pairs, the certified incumbent delay is at most 39% of the
   makespan, the median of the largest delay is 0.5%, and in 13 pairs no
   delivery is delayed at all: the affected UAVs meet the changed cell with a
   tailwind before their deliveries, and any headwind falls on a return leg or
   is outweighed by an earlier tailwind gain. Slack 2/5 therefore leaves every
   variant at Level 0. The four pilot slacks that the plan's grid shares (2/5,
   1/10, 1/20, 1/50) left 124 of 144 variants (86%) at Level 0.
2. **Level 1 absorbs most delays.** Every Level-1 witness changed only UAVs in
   U0 (30 changed one UAV, 11 two). No variant needed Level 2 or Level 4.
3. **Tasks per UAV shape the outcome.** With 1 task per UAV, every variant that
   path repair could not fix had no continuation at all (L0 58, L1 5, none 21).
   With 2 tasks, one mission (P1_8_4_uniform_71002) needs Level 3 in 14 of its
   21 variants (L0 56, L1 14, L3 14 overall); each of these witnesses moves two
   task assignments between the mission's two affected UAVs, so no helper
   outside U0 was needed. With 3 tasks, path repair always sufficed (L0 62,
   L1 22).
4. **Monotonicity held.** No chain produced a tighter variant with a lower
   level, and a stronger wind never lowered the certified level (0 of 168
   strength pairs).
5. **n = 12 stays.** No n = 12 variant was unresolved after pass 2, so the
   plan's drop rule does not apply.

### Caps and time to certificate

Pass 1 (10/8/6/6 s per stage) certified 243 of 252 variants. Pass 2
(20/40/30/30 s) certified the remaining 9: seven became "no continuation"
through Level-4 exclusions in one mission (P1_4_4_uniform_71001) and two became
Level 3 (P1_8_4_uniform_71002). Most variants were decided in the continuous
screen or by transfer: over both passes the Level-2 search ran 13 times, the
Level-3 search 14 times and the Level-4 search 6 times.

54 variants started from exclusions transferred from a looser slack, and one
witness was back-propagated from a tighter one. Transferred exclusions count as
available when the variant's own run starts, so 11 of the 21 "no continuation"
variants close at 0 s.

| Category | Variants | Median wall s to certificate | Max |
|---|---:|---:|---:|
| Level 0 | 176 | 0.33 | 0.6 |
| Level 1 | 41 | 0.99 | 8.1 |
| Level 3 | 14 | 3.33 | 23.2 |
| No continuation | 21 | 0.00 | 68.5 |

Fraction certified within a wall budget (`analysis/certified_by_wall_budget.csv`):

| Tasks per UAV | 0.5 s | 1 s | 4 s | 8 s | 30 s | 120 s |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 0.83 | 0.83 | 0.85 | 0.88 | 0.96 | 1.00 |
| 2 | 0.61 | 0.76 | 0.92 | 0.95 | 1.00 | 1.00 |
| 3 | 0.61 | 0.88 | 0.98 | 1.00 | 1.00 | 1.00 |

Total CPU time was 541 s for 252 variants. Pass 1 took 4.1 min and pass 2
2.4 min of wall time; the audit 1.5 min.

## E1 outcomes

The P1 update at strength 2/5 arrives at 1/4 or 1/2 of the makespan; t = 0 is
the P1 run. All 24 snapshots passed conservation, the shared-U0 check and the
previous premise. Counts over 84 variants per update time (12 missions x 7
slacks):

| Update at | Level 0 | Level 1 | Level 3 | No continuation | Unresolved |
|---|---:|---:|---:|---:|---:|
| t = 0 | 60 | 12 | 5 | 7 | 0 |
| 1/4 x makespan | 59 | 13 | 0 | 7 | 5 |
| 1/2 x makespan | 73 | 6 | 0 | 5 | 0 |

Findings:

1. **A later update usually needs less.** At t = 1/2 three missions (21
   variants) have empty U0: no remaining incumbent leg crosses the changed
   cell.
2. **But not always.** In P1_8_4_uniform_71001 (slacks 1/100 and 1/300) the
   minimum rises from Level 0 at t = 0 to Level 1 at t = 1/4. At t = 0, U2's
   tailwind on its first leg through the cell offsets the headwind on its
   second. By t = 1/4 it had flown part of the first leg under the previous
   wind (0.14 of 0.30 km in the cell remained), while the headwind leg was
   still ahead.
3. **Commitments can make a case infeasible.** Under D1 an airborne UAV keeps
   its destination at every level. In three variants, each in a different
   snapshot, the committed-prefix certificate showed that this destination
   cannot be reached before its deadline; the exclusion then transferred to the
   tighter slacks of that snapshot. For example,
   P1_4_4_clustered_71001 at slack 1/10 needs Level 1 at t = 0 but has no
   continuation at t = 1/4.
4. **Unresolved cases.** The 5 unresolved variants are one snapshot
   (P1_8_4_uniform_71002 at t = 1/4, slacks 1/20-1/1000). Level 2 is excluded;
   the Level-3 search used its full 30 s pass-2 cap after 1,650 sequence nodes,
   about a third of it on path queries (52 potential fields). At t = 0 the same
   variants are Level 3. They are reported as unresolved with identification
   bounds {3, 4, no continuation}.

Total CPU time was 393 s for the 168 in-flight variants.

## Comparators

The comparators ran on the 76 P1 pilot variants whose certified lower bound is
at least 1: 41 with minimum Level 1, 14 with minimum Level 3 and 21 with no
continuation. Caps follow `configs/escalation_study/comparators.json`.

| Policy | Plans found | At the certified minimum | Above it | Median UAVs changed | Median s to first plan |
|---|---:|---:|---:|---:|---:|
| C1 finite axis-path library (10 s) | 0 | 0 | 0 | - | - |
| C2 global first (10 s proposals, then 20 s Level-4 search) | 30 | 0 | 30 | 4 | 27.8 |
| C3 time-sliced escalation (2 s per level) | 41 | 41 | 0 | 1 | 2.1 |
| Certified ladder (P1) | 55 | 55 | 0 | 1 | 2.6 |

- **C1** found no plan, not even for the 41 variants that a continuous path
  repair solves. Its library holds only L-shaped axis paths between sites,
  while the incumbent flies straight legs and these deadlines leave at most
  1/10 of the makespan.
- **C2** found plans only for variants whose minimum is Level 1. All 30 plans
  change more than needed (27 change all four UAVs, 3 use Level 3), and every
  one changes UAVs outside U0. It found nothing for the 14 Level-3 variants.
- **C3** returned the minimum level whenever that level is 1 but found nothing
  for the Level-3 variants within its slices. Without exclusions it cannot
  claim minimality or show that no continuation exists.
- None of the comparators can identify the 21 variants with no continuation;
  the ladder certifies them.

The ladder row counts the variants with a finite certified minimum; its time is
the median wall time to the full certificate (witness and exclusions) of those
55 variants, so it is not directly comparable with a first-plan time.

## Calibration decisions (frozen in the primary configurations)

1. **Slack grid** 1/10, 1/30, 1/100, 1/300, 1/1000 of the makespan instead of
   the plan's 2/5-1/50 (finding 1).
2. **Caps unchanged**: pass 1 10/8/6/6 s, pass 2 20/40/30/30 s, 120 proposals,
   100,000 nodes.
3. **Battery slack 3/2 unchanged**; energy never bound at Levels 0-1, as the
   sizing argument requires.
4. **n = 12 kept.**
5. **E1** at strength 2/5 and t = 1/4, 1/2 of the makespan, with D1-D3.
6. **R1 larger missions** cover all four combinations of n in {24, 48} and m in
   {6, 8}, 10 missions each, as in the plan (the earlier configuration had only
   (24, 6) and (48, 8)). Generation was checked for the two added sizes.

## Open question for you

The plan asked for a grid whose tightest slack is "mostly Level 2 or higher" at
strength 2/5. Slack alone cannot achieve this here. 1/1000 of the makespan is
already close to the tightest meaningful deadline (the previous delivery time
itself), and there 9 of 12 missions still need at most Level 1, because many
one-cell updates delay little or nothing and path repair absorbs most of the
rest. The options are:

- **Proceed as frozen (recommended).** The share needing Level 2 or more is then
  a finding about local one-cell updates, not a design choice. The record of
  each variant's incumbent delay allows a secondary breakdown restricted to
  updates that delay a delivery.
- **Change the update model** (for example, several cells per update). This
  needs new admission rules and a new pilot. Strengths above 3/5 would break the
  battery argument and the `speed_bound_kmh` limit.

## Expected cost of the primary runs

Extrapolated from per-chain CPU in the pilot (one chain = one mission and
strength), assuming a laptop core is about as fast as a container core:

| Block | Units | Estimated CPU | Wall, 6 workers |
|---|---:|---:|---:|
| P1 primary (pass 1 + 2) | 1,800 variants | about 1.5 h | 20-40 min |
| E1 primary (pass 1 + 2) | 1,200 variants | about 1.1 h | 15-30 min |
| Comparators | about 675 variants | about 7.5 h (40 s per variant in the pilot) | about 1.3 h |
| R1 (budget/3, uncontended, larger missions) | 30 + 30 variants, 40 missions | about 1 h | about 1 h (larger missions run on one worker) |

Pass 2 adds a tail: each unresolved variant may use up to 120 s. The plan's
worst-case budget (Section 8) remains the upper limit.

## Files

| Directory under `results/` | Contents |
|---|---|
| `escalation_study_pilot_2026_10_08/` | P1 pilot: manifest, source archive, 12 sampling ledgers, pass-1 and pass-2 records, `analysis/` |
| `escalation_study_e1_pilot_2026_10_08/` | E1 pilot: 24 snapshot ledgers, records, `analysis/` (levels by update time, including t = 0 from the P1 pilot) |
| `escalation_study_pilot_comparators_2026_10_08/` | C1-C3 records and `analysis/comparators.csv`, `comparators_summary.json` |

The pilot ran with the source archived in each run directory. Afterwards the
certification code did not change. The later changes are two figure-label fixes
in `src/escalation_study/analysis.py` (E1 column titles; a legend instead of
overlapping end labels in the budget figure), the freeze note in
`p1_primary.json`, the larger-mission sizes in `r1_large.json`, the new control
test, and the original CRLF line endings restored in `src/level2/search.py`
(same content). The figures were regenerated with the fixed code; every table
was byte-identical. Because source files are bound to a run, a pilot directory
cannot be resumed with the current code; the audit and the reports still work.
