# Final study: confirmation pilot (15 October 2026)

This pilot answers the review of 15 October. It reruns the pilot design of 14 October
(same seeds) on one code version, with the changes the review asked for, and adds two
targeted checks: Level-4 constructions and the larger missions R1 left unresolved.

- Run: `results/final_study_confirmation_pilot_2026_10_15`, run hash
  `fd94f908f72e1e80a157a9712bdf95d075b8ce9356c2ec0ecfc90d70cf3fff04` (code and
  configuration bound by the manifest and `source.zip`).
- Configuration: `configs/final_study/confirmation_pilot.json`.
- Machine: this laptop (Windows 11, 16 logical CPUs, Python 3.10), 6 workers. 83 minutes
  from 16:16 to 17:39.
- Every table and figure below comes from this run: the report
  (`analysis/REPORT.md`) and `analysis/confirmation_extras.json`
  (`scripts/confirmation_pilot_extras.py`). The only exception is the exploration scans
  in Section 3, which are marked as such.

Pilot scale: 18 FS missions (L9 array x 2 layouts, 162 variants), labels at 120 s rather
than 600 s, and LS quotas of 2 per class and fleet. The numbers are for calibration, not
for the paper.

## 1. What ran

| Stage | Units | Time |
|---|---|---:|
| `fs-generate` | 18 missions, 87 update draws | 1.2 min |
| `fs-label` | 162 variants, CMI at 120 s | 8.0 min |
| `fs-arena-short`, `fs-arena-long` | 162 x 7 arms at 10 s; 54 x 5 arms at 60 s | 15.2 min |
| `ls-build` | 176 draws (24 per class and fleet at most), 52 admitted and labelled | 25.4 min |
| `ls-arena-short`, `ls-arena-long` | 24 LS instances | 7.5 min |
| `p1-label`, `p1-arena` | 40 P1 variants | 3.3 min |
| `xr` | 8 chains, 40 variants | 0.5 min |
| `scaling` | 8 larger missions R1 left unresolved, 5 arms at 60 s and 300 s | 16.1 min |
| `fs-d1`, `contention`, `gr-seeds`, `report` | | 6.3 min |

No unit and no stage failed.

## 2. The review items

### 2.1 Certificates are kept

Every label, arena result and XR chain now stores its evidence and records in a proof file
under `proofs/`, cited by digest from the record.

- 696 proof files, 55 MB in total, against 4 MB of result records. The largest file is
  1.3 MB, for a 48-task scaling mission. A full run is about ten times larger, so roughly
  0.5-1 GB.
- Replay at production time: 2,038 of 2,038 arena results and 362 of 362 labels.
- **Replay from disk** (a second, independent pass that reads only the saved record and its
  proof file): 2,038 of 2,038 arena results, 362 of 362 labels (FS, LS, P1 and the D1
  sensitivity labels) and 40 of 40 XR chain variants replay. No result failed, and none
  lacked its proof file or input.
- A saved CMI result without its proof file does not replay: its bracket cannot be
  rebuilt. The test `test_saved_labels_and_arena_results_keep_their_proofs_for_a_later_replay`
  checks this both ways.

### 2.2 Level 4: two constructions, both rare

The old Level-4 recipe was replaced by two constructions (`src/final_study/level4.py`;
scenario design, Section 4). Each builds a Level-4 witness first and then sets the
deadlines that make it necessary. A draw is admitted only if three checks pass:

- the witness passes the exact checker at Level 4;
- Level 0 is certified infeasible;
- a 60 s proof-free plan search at Levels 0-3 finds nothing.

The class still comes from the certified minimum alone.

LS Level-4 draws in this run:

| Recipe | Draws | No construction | Witness failed | Previous plan infeasible | Screen found a plan | Admitted | Certified minimum |
|---|---:|---:|---:|---:|---:|---:|---|
| chain | 36 | 20 | 3 | 3 | 8 (7 at Level 3, 1 at Level 1) | 2 | **4, 4** |
| deficit | 36 | 27 | 0 | 1 | 5 (Level 3) | 3 | 3, 3, 3 |

- **Chain works.** Both admitted chain draws certify Level 4: a Level-4 plan replays and
  every Level-3 patch is excluded.
  - `LS_L4_m4_0009`: fleet 4, t = 0, U0 = {U1}, helpers U2 and U3.
  - `LS_L4_m6_0019`: fleet 6, t = 1/4, U0 = {U6}, helpers U5 and U2.
- **Deficit does not, yet.** All three admitted deficit draws certify Level 3. The
  certified Level-3 plans escape by trading tasks between the affected UAVs and one
  helper, which the construction's screen does not anticipate.
- **Exploration scans** (separate seeds 77901, 77911 and 77921, never used by the study;
  labels at 120 s; code at successive stages of development): the chain construction gave
  certified Level-4 instances on 5 more base missions, at t = 0, 1/4 and 1/2. The deficit
  construction gave no Level-4 instance in about 180 draws.
- Together, chain has produced certified Level-4 instances on 7 independent base missions.
  The review asked for at least two mechanisms. **One is demonstrated; the second is not.**
- Yield: 1 certified Level-4 instance per 18 chain draws in this run (2 of 36), and 1 per
  20 in the last exploration scan (3 of 60). An earlier scan, on code before the last
  change, gave 1 in 60. The targeted pilot below gave none in 90, so these rates do not
  carry over to the full run (Section 2.2a).

FS itself, which uses no recipe: 3 Level-4 variants, all from one mission (as on 14
October).

### 2.2a Targeted Level-4 pilot (16 October)

After this run, the deficit recipe's update became a 2 x 2 block of cells, with one wind
blowing toward the depot (scenario design, amendment of 16 October). One cell rarely slows
two UAVs. Before the full run, both recipes were piloted under study conditions:

- run `results/final_study_level4_pilot_2026_10_16`, run hash `924b367a...b097`;
- configuration `configs/final_study/level4_pilot.json`;
- the level-suite stages only, on a seed of their own (77951);
- labels at the full run's 600 s;
- up to 60 draws per class and fleet, so 30 per recipe and fleet in the Level-4 cells.

| Recipe | Fleet 4 / 6 / 8 draws | No construction | Not local | Witness failed | Previous plan infeasible | Screen found a plan | Admitted | Label at 600 s |
|---|---|---:|---:|---:|---:|---:|---:|---|
| chain (one cell) | 30 / 30 / 30 | 61 | 0 | 3 | 3 | 21 | 2 (fleet 4) | both open between 3 and 4 |
| deficit (2 x 2 block) | 30 / 29 / 30 | 60 | 11 | 1 | 3 | 10 | 4 (fleets 4, 6) | 3, 3, 3; 1 open with Levels 0-2 excluded |

- **No constructed draw certified Level 4 in this pilot.**
  - Three constructed draws reach a bracket of [3, 4] at 600 s: Levels 0-2 are excluded,
    a Level-4 plan exists (for the deficit draw, the construction's own exact-checked
    witness), and Level 3 is not excluded in time. They go to the hard-residue pool, not
    the Level-4 class.
  - The three deficit draws that certify are Level 3.
- **The LS Level-4 class holds one instance**, `LS_inf_m4_0001`. A draw aimed at "no
  continuation" (fleet 4, t = 1/4) certified Level 4. Against a quota of 2 per fleet, the
  Level-4 class holds 1 at fleet 4 and none at fleets 6 and 8.
- **The deficit mechanism has one certified Level-4 instance in total.** With the block
  update, an exploration scan (seed 77941, 120 draws) admitted 12 deficit draws. Eleven
  certified Level 3. One (fleet 8, t = 1/2) certified Level 4 at 600 s in 212 s and
  replays. So deficit can produce Level 4, but about once in 120 draws.
- **Across everything so far:**
  - chain has certified Level-4 instances on 7 base missions (2 in the confirmation pilot,
    5 in exploration scans);
  - deficit has one (exploration);
  - the targeted pilot under study conditions added none.
  - Both mechanisms are demonstrated to exist, but neither yields Level 4 often enough to
    fill a quota of 20 per fleet. At these rates the full run's Level-4 cells would hold a
    handful of instances per fleet at most, mostly at fleet 4.
- **Why constructions fail.** Three causes:
  - Most draws find no construction (121 of 179): the screens rule out every candidate
    witness.
  - Among the admitted, Level 3 escapes through task trades between the affected UAVs and
    one helper, which neither the construction's insertion screen nor the 60 s plan search
    anticipates.
  - When Level 3 is truly excluded, the exclusion is hard to certify within 600 s.
- **One failed unit**, `LS_L4_m6_0006`, was not a construction failure. A leg through a
  cell corner made the shared route evaluator divide by zero while sizing batteries (it
  split the leg into an empty piece). This is fixed in `src/env/route_evaluator.py`, with
  a regression test. With the fix, that draw is an admitted deficit draw; labelled outside
  the run at 600 s, it certifies Level 3 (18 s, replays).
- Eight further draws first failed because of a source edit made while the run was going.
  The same command was rerun, as the guide prescribes, and they completed. The LS
  selection is in draw order, so the rerun gives the same selection as an uninterrupted
  run.
- Other cells: Level 2 at fleets 4 and 8 also stayed short of quota within 60 draws.

### 2.2b Tightened re-pilot (16 October)

Section 2.2a showed Level 3 escaping the constructions through task trades. Both
constructions now tighten deadlines against the plans the screen finds (scenario design,
second amendment of 16 October):

- When the 60 s plan search at Levels 0-3 finds a plan P, every task that P delivers later
  than the witness W (by at least 1e-6 h) gets W's delivery time as its deadline. The
  deadline never goes below the previous plan's time.
- The search then runs again, up to 8 rounds.
- The draw is rejected when P is no later than W on any task whose deadline can drop, or
  when the rounds run out.

The re-pilot ran under the same conditions as Section 2.2a (level-suite stages, 600 s
labels, up to 60 draws per class and fleet), on a fresh seed (77961) so that it does not
rest on the draws used during development:

- run `results/final_study_level4_pilot_tightened_2026_10_16`, run hash
  `3bb1a993...8b2a`;
- configuration `configs/final_study/level4_pilot_tightened.json`;
- 299 draws, 80 admitted and labelled; no unit failed;
- replay: 348/348 arena results and 80/80 labels.

Level-4 draws, both pilots (different seeds, so not a paired comparison):

| | Untightened (2.2a, seed 77951) | Tightened (seed 77961) |
|---|---|---|
| chain: draws | 90 | 90 |
| chain: tightening attempted / admitted | - / 2 (fleet 4) | 21 / 4 (fleets 4, 6, 8) |
| chain: label at 600 s | 2 open between 3 and 4 | **4, 4**, 3, 3 |
| deficit: draws | 89 | 90 |
| deficit: tightening attempted / admitted | - / 4 | 10 / 11 |
| deficit: label at 600 s | 3, 3, 3; 1 open | 3 (x8); 3 open |
| Level-4 class (quota 2 per fleet) | 1, at fleet 4 (from a "no continuation" draw) | 2, at fleets 6 and 8 (both chain) |
| Cells filled | 10 / 15 | 12 / 15 |

The two certified Level-4 instances:

| Draw | Fleet | t | Rounds | Deadlines lowered | CPU to certificate at 600 s | Replays |
|---|---:|---:|---:|---:|---:|---|
| `LS_L4_m6_0009` | 6 | 0 | 1 | 1 | 425 s | yes |
| `LS_L4_m8_0015` | 8 | 0 | 2 | 6 | 28 s | yes |

- **Tightening helps chain.** Chain now produces certified Level-4 instances under study
  conditions, at fleets 6 and 8, where no chain draw was even admitted before. That is 2 in
  90 draws, against 0 in 90 untightened. The development check (Section 2.2a seed, draws
  the old screen rejected) gave two more: `LS_L4_m4_0005` and `LS_L4_m4_0021`, each
  certified Level 4 after one round.
- **Deficit is admitted more often but still certifies Level 3.** Most admitted deficit
  draws were never tightened: the 60 s plan search found no Level-3 plan, yet the 600 s
  reference run found one, usually within 15-110 s. The screen, not the tightening rule,
  limits deficit: tightening acts only on the plans the search finds.
- **Tightening can stop short.** One chain draw (`LS_L4_m4_0033`) was admitted after 3
  rounds and still certified Level 3. Here too the search found no further Level-3 plan
  that the reference run then found.
- **Level 4 is hard to certify quickly.** On the two Level-4 instances CMI certifies none
  at 10 s and one at 60 s (LS report, class 4). GR's global replans reach Level 4 on both,
  as expected: they change many UAVs anyway.
- **Projection for the full run.** All certified Level-4 instances under study conditions
  are at t = 0. LS fills each class and fleet with at most ceil(20/3) = 7 instances per
  update time, so in-flight Level-4 instances would be needed to pass 7 per fleet. At about
  1 certified instance per 45 chain draws per fleet, the cap of 800 draws per cell (400
  chain) gives roughly 7-9 Level-4 candidates per fleet, almost all at t = 0. The Level-4
  class would hold about 7 per fleet against a quota of 20, and the report would state the
  shortfall. These estimates rest on two instances and should be read as rough.
  (Superseded by Section 2.2c, which found in-flight Level-4 instances.)

### 2.2c Re-pilot with CMI as the screen (16 October)

Section 2.2b showed that the 60 s PH screen missed most of the Level-3 plans the reference
run later found. Tightening can only act on plans the screen finds, so the screen is now the
reference method itself: CMI with the arena's settings, 120 s per round. Only the best plan
it returns is used, and its proofs play no part in selection. A plan at Level 3 or below
replays, so the screen still never rejects a Level-4 draw.

**Development check** (seed 77961, the draws of Section 2.2b; 600 s labels):

- both certified Level-4 draws (`m6_0009`, `m8_0015`) are still admitted and still certify
  Level 4;
- 5 of the 6 admitted draws that had certified Level 3 are now caught by the screen,
  tightened for 1-4 rounds, and rejected when the next Level-3 plan is no later than the
  witness on any task whose deadline can drop;
- the sixth (`m6_0042`, deficit) still slips through: the reference needed about 130 s to
  certify Level 3, just over the 120 s screen;
- none of the five became Level 4: each has a Level-3 plan as early as the witness.

**Re-pilot** on a fresh seed (77971), under the conditions of Sections 2.2a and 2.2b:

- run `results/final_study_level4_pilot_cmi_screen_2026_10_16`, run hash
  `bb6c7acc...f78d`;
- configuration `configs/final_study/level4_pilot_cmi_screen.json`;
- 389 draws, 103 admitted and labelled; no unit failed;
- replay: 324/324 arena results and 103/103 labels;
- level-suite build: 101 minutes, against 95 (PH screen) and 93 (untightened, including the
  rerun).

Level-4 draws in the three targeted pilots (90 per recipe; different seeds, so not paired):

| | Untightened (2.2a) | PH screen (2.2b) | CMI screen (2.2c) |
|---|---|---|---|
| chain: tightened / admitted | - / 2 | 21 / 4 | 19 / 4 |
| chain: label at 600 s | open [3,4] x2 | **4, 4**, 3, 3 | **4, 4**, open [4,-], open [1,3] |
| deficit: tightened / admitted | - / 4 | 10 / 11 | 16 / 2 |
| deficit: label at 600 s | 3, 3, 3, open | 3 (x8), open x3 | **4**, 3 |
| Certified Level 4 from constructions | 0 | 2 (t = 0) | 3 (two at t = 0, one at t = 1/4) |
| Admitted constructions that did not certify Level 4 | 6 | 13 | 3 |
| Level-4 class (quota 2 per fleet) | 1 | 2 | 3 (one per fleet) |
| Cells filled | 10 / 15 | 12 / 15 | 11 / 15 |

The three certified Level-4 instances (all labels replay):

| Draw | Recipe | Fleet | t | Tightening rounds | CPU to certificate (s) |
|---|---|---:|---:|---:|---:|
| `LS_L4_m4_0030` | deficit (2 x 2) | 4 | 0 | 0 | 13 |
| `LS_L4_m4_0039` | chain | 4 | 0 | 0 | 13 |
| `LS_L4_m6_0031` | chain | 6 | 1/4 | 0 | 11 |

The Level-4 class holds `m4_0030`, `m6_0031` and a draw aimed at "no continuation"
(`LS_inf_m8_0001`). `m4_0039` was not needed: the quota of 2 at fleet 4 allows one per update
time, and t = 0 was already taken.

- **The CMI screen mainly sharpens admission.** Of the admitted constructions, 3 of 6
  certify Level 4, against 2 of 15 with the PH screen. Labels are no longer wasted on
  draws that certify Level 3.
- **Both mechanisms now have certified Level-4 instances under study conditions.** Deficit
  (2 x 2 block) has `m4_0030`, and chain has instances at t = 0 and, for the first time,
  in flight (`m6_0031`, t = 1/4).
- **Tightening converted no draw in this run.** Every draw where it ran ended rejected;
  every admitted draw passed the screen in round 0. Tightening converted draws in Section
  2.2b and in the development checks, but its contribution here is nil. The screen did the
  work.
- **A screen miss remains possible.** `m6_0045` was admitted and its label found a Level-3
  plan (open between 1 and 3). As with `m6_0042` in the development check, the reference
  found what the 120 s screen did not.
- **Pooling would add one more.** `LS_L4_m8_0007` (chain, fleet 8, t = 1/4) ends at 600 s
  with Levels 0-3 excluded, yet CMI found no Level-4 plan. The construction's witness is
  exactly such a plan: it passed the exact checker on this scenario. Pooling the two would
  certify minimum 4. That is how the protocol already pools arm plans with the reference
  proofs (comparison protocol, Section 5). It is the only draw in the three pilots with
  Levels 0-3 excluded and no plan. Today the ledger records only the witness's level, so
  pooling would need the witness stored with the draw and replayed with the label.
- **Projection.** 3 certified instances in 180 constructed draws, about 1 per fleet per 60
  Level-4 draws, with one in three in flight. At the full run's cap of 800 draws per class
  and fleet, that suggests 10-15 Level-4 instances per fleet against a quota of 20. The
  per-update-time cap of 7 binds less now that in-flight instances occur. A shortfall
  remains likely. The estimate rests on 3 instances and is rough.

### 2.2d Pooling the construction witness with the label (16 October)

The draw now keeps its construction witness. After the 600 s reference run, the LS stage
checks the witness the way the replay checker checks plans: the exact quantity checker on
its patch, and its level against the true U0. It then records **pooled bounds** in the
label record: the label's replayed exclusions, with the witness's level as an upper bound.
The CMI label itself is unchanged. The LS class and the analysis read the pooled bounds.
`scripts/confirmation_pilot_extras.py` re-checks the witness and recomputes the pooled bounds
from disk.

End-to-end check on `LS_L4_m8_0007`, the one draw of Section 2.2c left open with Levels 0-3
excluded. Same seed and configuration, through the LS stage, into a scratch store
(`results/level4_scan_2026_10_15/pool_check`):

- The draw is admitted again (chain, fleet 8, t = 1/4) and stores its witness.
- The CMI label: Levels 0-3 excluded, no plan, audit passed. It used 908 s CPU against
  the 600 s budget; one long operation overran it, and the clock records the overrun.
- The witness checks at Level 4, so the pooled bounds are lower 4 = upper 4, minimum 4,
  and the LS class is 4.
- Replay from disk: the label replays, and the re-checked witness reproduces the pooled
  bounds.

Tests:

- the chain test now runs through the LS stage: witness stored, label replayed, pooled
  bounds equal to the label's when the label already certifies 4;
- a label that only excludes Levels 0-3 pools to minimum 4;
- without the label's audit, the witness only bounds from above;
- a tampered witness adds nothing.

The full suite passes (614 tests).

With pooling, the CMI-screen re-pilot would have had 4 Level-4 instances from 180
constructed draws, two of them in flight. Pooling adds a Level-4 instance only where both
a replayed reference exclusion of Levels 0-3 and an exact-checked Level-4 plan exist.

### 2.2e Battery, placement and depot stock (17 October)

A diagnosis of the constructions that produced no candidate (scenario design, third
amendment of 16 October) led to five changes:

- a task the affected UAV can no longer reach on its battery counts as in trouble;
- the battery estimate counts everything a UAV in the air has on board, and every
  screened candidate goes through the exact checker;
- deficit prefers a 2 x 2 block containing two affected UAVs' remaining deliveries;
- chain prefers a task that only one other UAV's route passes near;
- the Level-4 recipes give the depot the generator's largest stock (1.5 x total demand),
  and a constructed deadline that the in-flight previous-plan check rejects rises in small
  steps until it is accepted.

Two diagnostic findings decided the last change. In flight, the goods for a moved task
are already on board the affected UAV, so a helper must load new units at the depot, which
often held none: a candidate that failed the exact checker passed with two more units. And
for a UAV already in the air, the take-off-based deadline floor can be slightly tighter than
the in-flight check of the previous plan.

**Paired development scan** (exploration seed 77981; the same 60 Level-4 draws before and
after the stock change; 600 s labels):

- deficit draws with no candidate fell from 21 to 16 of 30;
- one in-flight deficit draw (fleet 4, t = 1/2) became a certified Level-4 instance
  (21 s, replays), where the same draws had given none;
- chain was unchanged (23 of 30 with no candidate): another single helper can usually take
  its task, which stock does not change;
- four draws then failed the in-flight previous-plan check; with the deadline-floor change
  they pass it after one or two steps of 1e-5 to 2e-5 h, and all four certify Level 3.

**Test run** under the conditions of Sections 2.2a-2.2c (fresh seed 77991):

- run `results/final_study_level4_pilot_battery_stock_2026_10_17`, run hash
  `ce854359...aa3d`, configuration `configs/final_study/level4_pilot_battery_stock.json`;
- 301 draws, 94 admitted and labelled; level-suite build 90 minutes;
- replay: 372/372 arena results and 94/94 labels;
- the Level-4 cells at fleets 4 and 6 filled early, so this run needed 54 Level-4 draws per
  recipe, against 90 in the earlier runs.

The run's report stage failed on a defect in the report code: a list named like an
analysis function shadowed it. The defect is fixed with a regression test. The report was
regenerated from the stored records, opened read-only; no result record changed. The
failure note stays in the run directory.

| | Untightened (2.2a) | PH screen (2.2b) | CMI screen (2.2c) | Battery + stock (2.2e) |
|---|---:|---:|---:|---:|
| chain: draws / no candidate / screened out / admitted | 90 / 61 / 21 / 2 | 90 / 56 / 17 / 4 | 90 / 58 / 19 / 4 | 54 / 34 / 17 / 2 |
| chain: certified Level 4 | 0 | 2 | 2 | 2 |
| deficit: draws / no candidate / screened out / admitted | 89 / 60 / 10 / 4 | 90 / 57 / 9 / 11 | 90 / 55 / 16 / 2 | 54 / 25 / 18 / 5 |
| deficit: certified Level 4 | 0 | 0 | 1 | 3 |
| **Certified Level 4 per constructed draw** | 0 / 179 | 2 / 180 (1.1%) | 3 / 180 (1.7%) | **5 / 108 (4.6%)** |
| of them in flight | - | 0 | 1 | 4 |
| Level-4 class (quota 2 per fleet) | 1 | 2 | 3 | 5 |
| Cells filled | 10 / 15 | 12 / 15 | 11 / 15 | 13 / 15 |

The five certified Level-4 instances (all certified by the label itself; none needed
pooling; all replay):

| Draw | Recipe | Fleet | t | CPU to certificate (s) |
|---|---|---:|---:|---:|
| `LS_L4_m4_0015` | chain | 4 | 0 | 14 |
| `LS_L4_m4_0026` | deficit | 4 | 1/2 | 36 |
| `LS_L4_m6_0019` | chain | 6 | 1/4 | 99 |
| `LS_L4_m8_0008` | deficit | 8 | 1/2 | 57 |
| `LS_L4_m8_0038` | deficit | 8 | 1/2 | 157 |

`LS_L4_m8_0038` was not needed: the quota of 2 at fleet 8 allows one per update time, and
t = 1/2 was already taken. The class's fifth place is a draw aimed at "no continuation"
(`LS_inf_m6_0008`).

- **Deficit is now the stronger mechanism.** It gave 3 certified instances in 54 draws, all
  in flight, where it had given 1 in 90. Stock was its main obstacle in flight.
- **In-flight Level 4 is now common.** 4 of the 5 instances are at t = 1/4 or 1/2, so the
  per-update-time cap no longer limits the class to t = 0.
- **Chain improved less.** Its rate per draw rose from 2.2% to 3.7%, but most chain draws
  still find no candidate, because another helper could take the task.
- **Projection.** About 4.6% of Level-4 draws certify Level 4, spread over all three
  update times. At that rate a cell of 20 needs about 430 draws, within the cap of 800. The
  full run's Level-4 cells could fill; this rests on five instances from one seed, and the
  rates of the earlier runs varied by seed, so a shortfall remains possible and would be
  reported.

### 2.3 Populations and screening

- The scenario design and protocol now say what FS and LS are. FS is the population of
  disrupted missions, kept whole, unresolved variants included; general claims come from
  it. LS is selected on certification and is read class by class only.
- The disruption check now records `screening_unresolved` and `screening_error` instead of
  `not_disrupted`. In this run neither occurred. FS: 42 draws not local, 27 not disrupted,
  18 accepted. LS: none either.

### 2.4 Statistics

Results from FS at 10 s, against the 120 s reference pooled with every arm's plans:

| Hypothesis | Observed | Verdict |
|---|---|---|
| H1: GR changes more UAVs than CMI | CMI minus GR -3.78 [-4.66, -2.84] | supported |
| H1: LR reaches the minimum less often than CMI | 85.6% vs 74.7%; difference 11.0% [-1.4, 25.9] | not supported |
| H1: PH reaches the minimum less often than CMI | 85.6% vs 86.3%; difference -0.7% [-4.1, 2.0] | not supported |
| H2: observed certification rate meets 80% | 79.0% [60.5, 93.2] | **target missed** |
| H2: underlying rate exceeds 80% | lower bound 60.5% | not established |
| H2: every certificate replays, no plan contradicts a proof | 100%, 0 violations | supported |
| H3: certificate within 3x PH's first plan, paired | 1.23x [1.06, 1.56] on the same 125 of 162 instances; CMI did not certify 34, PH found no plan on 35 | supported |
| H3: noAF costs more | CMI minus noAF 1.9% [0.0, 5.6] certified | not supported |
| H3: noER costs more | CMI minus noER 5.6% [0.0, 13.0] certified; +0.78 [0.39, 1.44] s paired | supported |

- **Recoverable** now means a verified plan at Level 4 or below. For example, recovery
  success over recoverable FS variants is 98.7% for the reference.
- **H2 is missed.** The observed rate, 79.0% (128 of 162), is below the 80% that was set
  on 14 October from a reported 82.1%. The same FS instances were used: the level spread
  matches 14 October within one variant, with 5 unresolved now against 4. One likely
  reason is the machine. On this laptop, CPU time itself rises by a median factor of 1.40
  with 6 workers against 1 (contention stage). The 10 s budget therefore buys less search
  here than on the 2-CPU cloud workspace. The threshold was fixed in advance, so it stands
  and the verdict is "missed".
- **H3 is now paired.** 1.23x is close to the 1.22x reported before, now on the same
  instances and with its interval and coverage.
- **Interactions.** The model with all eight mission-factor x strength and x update-time
  blocks did not converge at pilot scale (18 clusters, 49 parameters). Its Wald tests
  (for example m x strength p < 0.001) are not interpretable here. The main-effects model
  converged. The full run has 162 clusters and 1,458 variants.

### 2.5 LR repairs battery and reserve shortfalls

LR now handles battery and reserve shortfalls, with re-routing, depot stops and task moves.

- FS at 10 s: LR reaches the reference minimum on 74.7% of variants (73.3% on 14 October)
  and returns an accepted plan on 71.0%.
- On the LS Level-2 class (reordering and recharge), LR reaches the minimum on 2 of 3.
- A regression test fixes one recharge draw where LR failed before the change and
  succeeds after it (`test_lr_repairs_an_energy_shortfall_when_no_delivery_is_late`).

### 2.6 The difficult larger missions

The scaling stage regenerates R1's 40 larger missions; none of the regenerated scenarios
differs from R1's. R1: 13 at Level 0, 2 at Level 1, 1 at Level 3, and 24 without a
witness. The pilot ran a stratified subset of the 24 unresolved missions: two per size,
drawn with seed 76005.

| Mission | CMI at 60 s | CMI at 300 s | CMI CPU to certificate (s), first budget that certified | PH plan, 60 s / 300 s |
|---|---|---|---:|---|
| P1_24_6_clustered_73001 | Level 3 certified | Level 3 certified | 24.6 | none / Level 3 |
| P1_24_6_clustered_73004 | Level 3 certified | Level 3 certified | 23.3 | Level 3 / Level 3 |
| P1_24_8_clustered_73004 | Level 3 certified | Level 3 certified | 21.8 | Level 3 / Level 3 |
| P1_24_8_uniform_73005 | Level 3 certified | Level 3 certified | 30.9 | Level 3 / Level 3 |
| P1_48_6_clustered_73004 | Level 3 certified | Level 3 certified | 33.3 | Level 3 / Level 3 |
| P1_48_6_uniform_73004 | Levels 0-2 excluded, open | Level 3 certified | 297.1 | none / none |
| P1_48_8_uniform_73002 | Levels 0-2 excluded, open | Level 3 certified | 281.4 | none / none |
| P1_48_8_uniform_73004 | Level 3 certified | Level 3 certified | 56.1 | none / none |

- At 60 s, CMI certifies 6 of the 8; at 300 s, all 8. Every one is Level 3, so R1's
  unresolved larger missions were missing Level-3 witnesses.
- Two of the 48-task missions certify only at 281 s and 297 s, at the edge of the 300 s
  cap. Expect some of the 24 to stay open at 300 s in the full run.
- The baselines rarely find these plans. At 300 s: GR 2 of 8, GR-c 5, LR 1, PH 5.

### 2.7 Protocol documents

- The scenario design and the comparison protocol are marked implemented, with their
  amendments of 15 October (Section 11 and Section 12 respectively).
- The pilot page of 14 October carries a note: its two figures for CMI's 10 s
  certification (134 of 162 and 82.1% = 133 of 162) come from different runs, which are
  not available here. This page replaces it for numbers.

## 3. Other results at pilot scale

- **FS levels** (120 s reference): Level 0 14.2%, 1 39.5%, 2 8.0%, 3 26.5%, 4 1.9%, no
  continuation 6.8%, unresolved 3.1%. These are shares of the disrupted population. FS
  certification at the reference is 96.9%.
- **FS at 60 s** (random third): CMI certifies 98.1% and reaches the minimum on all 54.
- **LS:** 10 of 15 cells filled. 1 of 52 labelled draws was left undecided at 120 s.
- **P1:** 0 disagreements with v1 certificates; v2 certifies 18 of the 19 variants v1 left
  open. The method criterion of deciding 90% at 10 s is missed: 80.0%.
- **XR:** all 40 variants certified and replayed.
- **D1 against D1':** 108 in-flight variants. Under D1 (destination committed), 33 have no
  continuation, against 11 under D1'. The 22 extra cases had a minimum of 2, 3 or 4, or were
  unresolved, under D1'.

## 4. Decisions before the full run

1. **Level-4 class** (updated 17 October, Sections 2.2a-2.2e). With the battery,
   placement and stock changes, both mechanisms certify Level 4 under study conditions at
   about 4.6% of constructed draws: deficit 3, chain 2, four of them in flight. The
   Level-4 cells could fill in the full run (about 430 draws per cell needed, cap 800). This
   is a single-seed estimate, and any shortfall will be reported. The code is ready for the
   full run.
2. **H2 threshold.** It was missed at 79.0% on this machine. It stays fixed. The full run
   could be moved to a machine with less CPU contention, or the contention factor reported
   next to the verdict, but the threshold should not be lowered after the fact.
3. **Interaction model.** Keep it as specified and check convergence in the full run. If
   it does not converge there, report that and do not interpret the Wald tests.
4. **LS Level-4 quota.** The full quota of 20 per fleet is within reach (Section 2.2e), with
   instances at all three update times. The estimate rests on five instances from one seed,
   so a shortfall in some fleet remains possible.
