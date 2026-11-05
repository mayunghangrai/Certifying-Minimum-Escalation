# Final-study pilot (14 October 2026)

> **Superseded for numbers (15 October).** A review found that this page's figures do not
> come from one run: the calibration table says CMI certified 134 of 162 (82.7%), while the
> results table's 82.1% is 133 of 162. The pilot ran three times (below), and the runs are
> not available here to establish which figure came from which. The figures are kept as
> they were reported. The confirmation pilot
> (`FINAL_STUDY_CONFIRMATION_PILOT_2026_10_15.md`) reruns this design on one code version,
> and its tables are generated from that single run. Two statements below are also
> corrected there: FS does not measure an unrestricted "natural frequency" of Level 4 (it
> admits only disrupted missions), and the H2 verdict here meant only that the observed
> rate met the 80% target.

The pilot checks, on seeds of its own, that method v2 and the study pipeline work end to end
before the full run, and settles the remaining calibration. Configuration:
`configs/final_study/pilot.json`. It ran on the cloud workspace (2 workers, 2 CPUs) in 85
minutes, using the same command as the full run.

## What ran

| Stage | Units | Time (2 workers) |
|---|---|---:|
| `fs-generate` | 18 FS missions (L9 array of fleet, tasks per UAV, slack and battery, x 2 layouts) | 1.8 min |
| `fs-label` | 162 variants, CMI at 120 s (the full run uses 600 s) | 12.1 min |
| `fs-arena-short` | 162 instances x 7 arms at 10 s | 24.9 min |
| `fs-arena-long` | 54 instances x 5 arms at 60 s | 3.1 min |
| `ls-build` | 120 LS draws (quota 2 per class and fleet, at most 12 draws per cell) | 10.0 min |
| `ls-arena-short`, `ls-arena-long` | 22 LS instances | 16.2 min |
| `p1-label`, `p1-arena` | 40 P1 variants | 8.9 min |
| `xr` | 8 chains (40 variants) | 0.8 min |
| `scaling` | 2 larger missions at 60 s | 0.5 min |
| `fs-d1` | 108 in-flight variants under D1 | 3.9 min |
| `contention`, `gr-seeds` | 6 instances each | 2.5 min |
| `report` | | 0.2 min |

## Checks

- Every result replays: 1,944 of 1,944 arena results and 367 of 367 reference labels.
- No cross-check violation in any set or budget: no plan below a proven lower bound, and no
  proof above a known plan.
- No unit and no stage failed.
- P1: no disagreement with any v1 certificate (40 variants). v2 certifies 18 of the 19
  variants that v1 left open.
- All 40 XR variants replay.

## Bugs found and fixed

The pilot ran three times. Each fix below has a regression test, and the full suite passes
(606 tests).

1. **Ladder idle loop.** When the lowest open level ended undecided, the ladder could spin
   until the slice overflowed (`OverflowError`). The lowest level still being decided now
   runs its full search, and the loop stops when no search did any work.
2. **noAF plans rejected.** noAF releases the whole fleet, so its Level-3 search can return a
   true Level-4 plan. The ladder now checks a plan against the masks of its own run and
   scores the level against the true U0, as the replay already did.
3. **Plans from a higher patch.** A level's search could accept a plan through a higher
   level's quantity releases. The exact check now stops at the level doing the search.
4. **LS draw crash.** One in-flight draw failed the previous-wind premise, and the U0
   diagnosis raised an error instead of rejecting the draw. The premise is now checked
   first, so such a draw is rejected.
5. **Failure handling.** A failed unit could stop the LS stage, and a failed stage stopped
   the whole run. Now:
   - every failure is logged and kept under `failures/` until a rerun succeeds;
   - the report lists the failures;
   - later stages still run;
   - D1 snapshots are built inside each unit.

## Calibration decisions (frozen in `configs/final_study/final.json`)

| Setting | Decision | Evidence |
|---|---|---|
| Slack 1/400, 1/100, 1/25; battery 3/20, 1/2, 4 | kept | FS levels spread: Level 0 14%, 1 40%, 2 8%, 3 27%, 4 2%, no continuation 7%, unresolved 2.5% (120 s) |
| CMI plan search at the lowest open level | added: the lowest open level now also runs a plan-only search for a quarter of each slice, as the levels above it already did | At 10 s on the 162 FS instances, PH found Level-3 plans that CMI missed: CMI's full Level-3 search spends its time on route checks before it reaches plans. With the change, CMI certified 134 instances instead of 132, found 132 plans instead of 129, and mean CPU fell from 3.2 s to 2.9 s; every result replays |
| PH shares (0.05, 0.15, 0.2, 0.3, 0.3); base slice B/40; plan-search share 1/4 | kept | PH and CMI reach the minimum equally often |
| Hypothesis thresholds: H2 80% certified at 10 s, H3 at most 3x | kept | Observed: 82.1% [66.7, 95.1]; ratio 1.22x |
| Hypothesis verdicts that compare arms | paired by instance; supported only if the 95% bootstrap interval over missions excludes zero | Point comparisons called differences of 1-3 instances "supported" |
| LS reordering recipe | uses the loosest slack (as the recharge recipe does) | All 13 FS Level-2 cases came from loose-slack missions. In a 36-draw check, 2 of 18 reordering draws were Level 2, against 0 of 18 before |
| LS Level-4 recipe | unchanged | Level 4 is rare: 3 of 162 FS variants, all from one mission, and none of about 120 LS draws aimed at it under four recipe variants (stronger wind, tasks farther apart, 4 tasks per UAV, tight or medium slack) |

## Results in brief (pilot scale, own seeds; not for the paper)

FS at 10 s (162 instances; reference = the 120 s label pooled with every arm's plans):

| Arm | Plan at the minimum | Certified | Levels above the minimum (mean) |
|---|---:|---:|---:|
| CMI | 89.0% | 82.1% | 0 |
| PH | 89.7% | cannot certify | 0 |
| LR | 73.3% | cannot certify | 0.05 |
| GR-c | 43.8% | cannot certify | 0.81 |
| GR | 10.3% | cannot certify | 2.17 |
| noAF / noER | 87.0% / 88.4% | 80.2% / 81.5% | 0.02 / 0 |

- At 60 s (54 instances), CMI reaches the minimum on all of them and certifies 98.1%.
- GR changes 3.7 more UAVs than CMI per plan, and GR-c changes 0.46 more.
- A CMI certificate takes a median 0.74 s CPU, against 0.61 s for PH's first plan.
- On LS at 10 s, CMI certifies 68% and reaches the minimum on 79% (PH: 71%).
- The pilot verdicts: H1 is supported for GR and LR but not for PH; H2 is supported; H3 is
  supported for the cost ratio and for noER, but not for noAF.

## What to expect in the full run

- **Duration.** Extrapolated from the pilot's per-unit times, with 6 workers, about 10-14
  hours.
  - Labels take about 1.3 h, the 10 s arena about 1.3 h, and the P1, XR, D1 and contention
    stages under an hour each.
  - The longest stage is likely the LS build, at 2-3 h. The Level-4 class rarely fills, so
    the design's cap of 800 draws per class and fleet is reached there.
  - Scaling takes minutes if the larger missions stay at Level 0, and at most 2.8 h.
- **Level 4.** The final run will probably not fill the LS Level-4 class. The design's stop
  rule applies, and the report gives the shortfall. FS measures Level 4 within its
  disrupted population (about 2% at pilot scale), not as an unrestricted frequency.
- **Scaling.** The 40 larger missions keep the R1 update (strength 2/5). Both pilot missions
  were Level 0: the update did not break their plans. If most of the 40 are Level 0 too,
  the scaling stage measures the cost of the Level-0 check at size.
- **Targets that count missions.** For example, Level 2 in at least 20 missions. These
  cannot be judged at pilot scale (18 missions).
