# Scenario design for the next round: balanced levels and systematic factors

Date: 14 October 2026. Status: **implemented** (`src/final_study`; pilot of 14 October in
`FINAL_STUDY_PILOT_2026_10_14.md`), **amended on 15 October** after a review (Section 11).
Answers supervisor comment 3.

This design replaces Section 8 (P2 and E2) of `ROOT_CAUSE_AND_REDESIGN_PLAN_2026_10_10.md`.
The instance sets of `COMPARISON_PROTOCOL_2026_10_14.md` change to match it. The method is
v2, from `CERTIFICATION_METHOD_PLAN_2026_10_09.md` with the 10 October amendments.

## Summary

1. **Two studies.**
   - **Factorial study (FS).** It varies the six factors the supervisor named on
     randomly drawn missions whose plan the update breaks. It shows how the required
     level depends on each factor.
   - **Level suite (LS).** It is built deliberately: 60 instances whose certified
     minimum is Level 1, 60 each for Levels 2, 3 and 4, and 60 with no continuation,
     drawn from many different base missions. It measures performance level by level and
     is used for the comparison in comment 4.
2. **Generator changes.** Each change targets a cause found on 10 October:
   - urgency classes in the deadlines, which Level 2 needs;
   - battery margin as a factor, because a recharge stop is a second way to reach
     Level 2;
   - fleets of 6 and 8 UAVs and longer routes, which Level 4 needs;
   - updates placed ahead of the UAVs, so the update time can vary.
3. **Labels come only from certification.** LS draws are aimed at a target level, but a
   draw enters a level class only through its certified minimum at the reference budget
   (10-60 times the evaluation budgets). LS therefore holds instances v2 can certify, and
   its rates hold within its classes only; overall rates come from FS, which keeps every
   admitted variant, unresolved ones included (Section 4, "Two populations").
4. **Unresolved cases.** Method v2 is the remedy. The unresolved rate becomes a reported
   outcome with a target set in advance.
5. **Metrics.** Every result reports certification rate, unresolved rate, required
   level, computation time and mission recovery success rate, by factor level, by level
   class and by method.

## 1. The comment and the cause behind each point

| Comment point | Cause (10 October analysis) | Remedy here |
|---|---|---|
| Level 2 is the minimum in one case | One slack s for all tasks makes the incumbent order the only feasible order. Energy cannot bind by design, and each UAV's payload covers its own demand. | Urgency classes in the deadlines; battery margin as a factor; 2-4 tasks per UAV |
| All 12 Level-4 cases come from one base mission | With 4 UAVs, Level 3 (affected UAVs plus one helper) already involves half the fleet or more, so Level 4 rarely adds a useful option. | Fleets of 6 and 8; Level-4 sampling recipes; at most one instance per base mission in each class |
| 286 of the 700 disrupted cases are unresolved | The method's order of work: it computes paths before it needs them, never splits the search by UAV, and searches strictly upward | Method v2; unresolved rate reported with a target |
| 24 of the 40 larger missions are unresolved | Same causes, at larger size | v2; fleet size and task density as factors up to 8 UAVs x 4 tasks; a scaling study beyond |
| Vary the six factors systematically | P1 varied only strength and slack | FS (Section 3) |
| Report the five metrics | | Section 6 |

## 2. Generator

The base mission is built as in P1:

- `random_pair` geometry;
- round-robin sweep assignment and nearest-neighbour order;
- straight legs under the calm previous forecast;
- airspeeds 1, 1.275 and 1.56 km/h;
- service and preparation 0.01 h each;
- 4 x 4 wind cells over 2 km x 2 km.

The table lists what changes.

| Item | P1 | Next round |
|---|---|---|
| Fleet size | 4 | Factor: 4, 6, 8 |
| Task density (tasks per UAV) | 1-3 | Factor: 2, 3, 4, so 8-32 tasks in the same region |
| Deadlines | `u_i + s x makespan`, one s for all tasks | `u_i + max(1 min, c_i x sigma x makespan)`. Class multiplier c_i is 1, 10 or 50 (urgent, normal or routine task; one third each, at random; this is the 10 October mixed profile). Slack level sigma is a factor: tight, medium or loose, starting at 1/400, 1/100 and 1/25 and calibrated in the pilot. |
| Battery | requirement + 3/2 x scale; never binds | Factor: margin beta of 0.15 (tight: a strong headwind can force a recharge stop), 0.5 (medium) or 4 (ample: never binds). Capacity = requirement + beta x scale, as in `battery_reference`. |
| Update region | one cell crossed by any leg, return legs included | one cell on a leg that starts after half the makespan and precedes a delivery, so the disruption still lies ahead at every update time |
| Wind strength | 1/5, 2/5, 3/5 of the slowest airspeed | Within each mission: 2/5, 3/5, 4/5. The generator's strength guard and wind speed bound rise from 3/5 to 4/5. |
| Update time | 0; 1/4 and 1/2 of the makespan only in E1, under D1 | Within each mission: 0, 1/4 and 1/2 of the makespan. D1' (the level masks decide what an airborne UAV may change) is the primary rule, with D1 as a sensitivity analysis. |
| Admission | previous plan feasible; 1 <= abs(U0) <= m/2 | As P1, plus **disrupted**: Level 0 certified infeasible at strength 3/5 and t = 0 |

Every rejected draw is logged with its outcome. The disruption check has four outcomes:
`disrupted` (Level 0 certified infeasible), `not_disrupted` (a Level-0 plan),
`screening_unresolved` (neither within the 30 s check) and `screening_error`. Only the
first admits, and only the second counts as "the update does not break the plan". The
screening rate is reported for each design cell; it carries P1's finding that most random
updates do not break the plan.

## 3. Factorial study (FS)

- **Between missions:**
  - fleet size (4, 6, 8);
  - tasks per UAV (2, 3, 4);
  - slack level (tight, medium, loose);
  - battery margin (tight, medium, ample).

  All 81 combinations, two missions each (one uniform and one clustered layout): 162
  missions.
- **Within each mission:** 3 wind strengths x 3 update times, all with the same update
  cell and direction, so the comparisons are paired. That gives 9 variants per mission
  and 1,458 in total.
- **Pilot.** Separate seeds. It sets the slack and battery values so that the medium
  levels give a spread of required levels, then the design is frozen and primary seeds
  are drawn.
- **Questions.**
  - How does each factor move the required level, the certification and unresolved
    rates, computation time and recovery success?
  - How do the four mission factors interact with strength and update time?

## 4. Level suite (LS)

**Classes.** 60 instances in each of five classes, by certified minimum: Level 1, 2, 3, 4,
and no continuation (300 instances). A further 30 instances are drawn at random from the
draws that the reference run leaves undecided (the hard residue).

**Diversity rules:**

- in each class, at most one instance per base mission, and at most two per base mission
  overall;
- in each class, 20 instances for each fleet size, with update times balanced within
  them;
- reported for each class:
  - the factor values that occurred;
  - the mechanism (for Level 2, reordering or recharge);
  - the number of affected UAVs;
  - the number of distinct base missions.

**Sampling toward a class.** These recipes change only which draws are tried, never the
label:

| Class | Recipe |
|---|---|
| Level 1 | ordinary draws (common) |
| Level 2, reordering | 3-4 tasks per UAV; update on the leg into an urgent task that is not first in its UAV's order |
| Level 2, recharge | tight battery, loose slack, strongest headwind on a long leg |
| Level 3 | tight margin on the affected UAV's urgent task, normal or routine margins elsewhere, and another UAV with a stop near that task |
| Level 4 | Constructions with a global witness (amended 15 October; `src/final_study/level4.py`). **Deficit:** two tasks the affected UAVs now deliver late (typically one each of two affected UAVs) go to two different helpers; no affected UAV can deliver either on time and no single helper can deliver both. **Chain:** a task the affected UAV now delivers late goes to the only helper that can deliver it on time; that helper then cannot keep one of its own tasks, which goes to a second helper. The witness W is built first; the tasks W moves get W's delivery times as deadlines (never below the previous plan's certified delivery time under the previous forecast, so the previous plan stays feasible), the affected UAVs' remaining tasks become urgent at W's times, and other deadlines rise only where W needs it. The update is placed so that U0 is small. For chain: one cell, on a leg into a task inside the cell. For deficit (amended 16 October): a 2 x 2 block of cells with one wind blowing toward the depot, chosen to affect exactly two UAVs when the fleet allows (one cell rarely slows two UAVs); this is the only recipe whose update is larger than one cell. W must pass the exact checker at Level 4 on the final scenario. Then a screen runs: the reference method itself (CMI, the arena's settings), 120 s per round (amended 16 October; it was a 60 s proof-free PH search, which missed Level-3 plans that CMI finds). Only the best plan it returns is used; its proofs play no part in the selection. When that plan P is at Level 3 or below, the tasks P delivers later than W (by at least 1e-6 h) get W's delivery times as deadlines, never below the previous plan's times. This excludes P and keeps W, and the screen runs again, up to 8 rounds. The draw is rejected when P is no later than W on any task whose deadline can drop, or when the rounds run out. A plan the screen finds replays, so the screen rejects only draws that cannot be Level 4 as they stand. The class still comes from the certified minimum alone: a Level-4 label means a Level-4 plan replays and every Level-3 patch is excluded. |
| No continuation | tight slack, strongest headwind on legs into urgent tasks |

Some recipes aim the wind at a leg, which FS never does. LS reports this.

**Labels.**

- Each draw is labelled by a reference run of v2 with 600 s per instance, audited by the
  independent replay checker. The label's evidence and records are kept with it, so the
  label can be replayed again later.
- A constructed Level-4 draw keeps its construction witness W with the draw (amended 16
  October). After the reference run, W is checked the way the replay checker checks plans:
  the exact quantity checker on its patch, and its level against the true U0. Its level is
  then pooled with the label's exclusions as an upper bound, just as the comparison protocol
  pools arm plans with reference proofs. When the label excludes Levels 0-3 and W checks at
  Level 4, the pooled minimum is 4. The class is read from the pooled bounds; the label
  itself is unchanged, and both the label and W replay from disk.
- A draw left undecided goes to the hard-residue pool, never into a class. LS classes
  therefore hold only instances v2 certifies within 600 s. A longer reference budget
  weakens this selection but does not remove it: LS rates at 10 s and 60 s are rates on
  v2-certifiable instances of each class, not general performance.
- The share of all draws left undecided at 600 s is reported.

**Stop rule.** Draw until every quota is filled, with at most 800 draws for each class
and fleet size (40 per instance needed). Any shortfall is reported.

**Two populations** (amended 15 October). FS and LS answer different questions.

- FS admits a mission only when Level 0 is certified infeasible at its reference variant
  (strength 3/5, t = 0). It is a population of *disrupted* missions, selected on that one
  outcome, and it keeps every admitted variant, including those the reference leaves
  unresolved. Its level shares are frequencies within this disrupted population, as
  screened by the generator; they are not unrestricted natural frequencies of Level 4 or
  of any other level. The screening table reports how many draws each admission took.
- LS gives enough instances at every level to measure performance there. It is selected
  on certification (above), so its shares are never read as frequencies and its rates
  are never read as general performance.
- General performance claims (overall certification, unresolved and recovery rates, the
  primary endpoints) come from FS, which retains unresolved cases.

## 5. Unresolved cases and larger missions

- **Unresolved cases.** Method v2 addresses the causes behind the 286 open P1 cases.
  In scratch checks on 10 October, a v2 prototype decided 153 of the 203 cases open at
  Level 3 or 4, and a per-UAV route check excluded Level 2 in 41 of the 42 cases open
  there. The unresolved rate is reported for every budget, with each unresolved case's
  bracket.
- **Larger missions.** FS reaches 8 UAVs x 4 tasks (32 tasks). Beyond that, the 40
  larger missions (24-48 tasks, 6-8 UAVs) run at 60 s and 300 s for all methods under
  the comment-4 protocol. They are regenerated identically to R1 (the report checks the
  scenario hashes) and reported three ways: all 40, the 27 that R1 left disrupted (not
  Level 0), and the 24 that R1 left unresolved. A stratified subset of the 24 (two per
  size) is piloted first (`configs/final_study/confirmation_pilot.json`).

## 6. Metrics

| Metric | Definition |
|---|---|
| Certification rate | Share of instances with a certified answer within the budget (10 s, 60 s and the 600 s reference): a minimum with its proof, or no continuation |
| Unresolved rate | One minus the certification rate. Each unresolved instance is reported with its bracket. |
| Required intervention level | The certified minimum (0-4, or no continuation). An unresolved instance enters only through its bracket, as identification bounds. |
| Computation time | CPU time to the first plan and to the certificate: median and 90th percentile. Wall time and the contention factor alongside. |
| Mission recovery success rate | Share of disrupted instances for which the method returns a plan the exact checker accepts: every delivery on time, and every battery, payload and stock limit met under the updated wind. Reported over all instances and over recoverable ones: instances with a verified finite upper bound (some plan at Level 4 or below that replays, from the reference or any arm; a certified minimum is not needed). The share certified unrecoverable is reported separately; only the certified method can establish it. |

**Breakdowns:**

- by factor level (FS);
- by level class (LS);
- by method (comment-4 protocol);
- by update time.

**Analysis:**

- shares with 95% intervals from a bootstrap over missions;
- an ordinal regression of the required level on the six factors, with errors clustered
  by mission;
- times as medians and 90th percentiles.

## 7. Targets set in advance

- **FS.** Each of Levels 1-4 is the certified minimum in at least 3% of variants and in
  at least 10 base missions; Level 2 in at least 20.
- **LS.** Every class filled, each from at least 50 distinct base missions.
- **Unresolved.** At most 5% of FS variants at the 600 s reference.

A missed target is reported as missed. Nothing is redrawn after the freeze.

## 8. What must be built

1. **Generator.** A new generator beside the P1 one, which stays unchanged so P1 remains
   reproducible. It adds:
   - fleet size and tasks per UAV;
   - urgency classes and slack levels;
   - battery margin;
   - the placement rule;
   - the 4/5 strength;
   - the disruption admission rule.
2. **Update times.** `snapshots.py` gains a D1' option. D1 stays available.
3. **LS sampler.** Recipes, quotas, per-mission caps and full draw ledgers.
4. **Analysis.**
   - tables by factor and by class;
   - the ordinal regression;
   - recovery success;
   - figures.
5. **Tests:**
   - stock is conserved, and admission and the previous plan's feasibility are checked;
   - quotas and caps hold;
   - labels come only from audited certified records;
   - recipes never read a label.

**Order.** Method v2 first, then the generator. A pilot sets the slack and battery values
and checks the spread of levels. Then freeze, label FS and LS, and run the comment-4
comparison.

## 9. Cost on the laptop

Worst case on six workers, assuming 5% of instances reach the 600 s reference cap:

| Block | Wall |
|---|---:|
| FS labels: 1,458 variants | 2.4 h |
| LS draws and labels: about 1,500 draws, the number to be checked in the pilot | 2.4 h |
| Comment-4 comparison on FS and LS, ablations, reuse and scaling | about 20 h, worst case (see the protocol) |

The total is about three nights in the worst case. Typical runs should be far shorter,
because most variants close within seconds.

## 10. Decisions

1. **Two studies.** FS for how often and why; LS for performance at each level.
2. **Factor levels.** Fleet size 4/6/8; tasks per UAV 2/3/4; slack tight/medium/loose;
   battery tight/medium/ample; strength 2/5, 3/5, 4/5; update time 0, 1/4, 1/2. Slack
   and battery values are calibrated in the pilot.
3. **Population.** Disrupted missions only (Level 0 infeasible at 3/5 and t = 0), with
   the screening rate reported.
4. **In-flight rule.** D1' primary and D1 as sensitivity (decision D-D of 10 October).
5. **Update size.** One cell, fixed. A 2 x 2 block could be added as a seventh factor; it
   would double FS.

## Verification of this plan

Generator details were read in `src/escalation_study/missions.py`:

- the deadline rule `hi + s*tau`;
- the update cell drawn from all crossed cells, with the direction uniform over 12;
- the strength guard `r <= 3/5` and the wind bound 0.6;
- `battery_reference` and the admission rules.

The causes and scratch-check figures in Sections 1 and 5 come from the 10 October plan.
(When this was proposed on 14 October, no other file had been changed.)

## 11. Amendments of 15 October (review)

1. **Certificates kept.** Every label and arena result keeps its evidence and records in a
   proof file under `proofs/`, cited by digest from the result record, so any result can
   be replayed independently later (`final_study.arena.replay_saved`).
2. **Level 4.** The LS Level-4 recipe is replaced by the two constructions of Section 4.
   Their yield is checked in a targeted pilot before the full run
   (`FINAL_STUDY_CONFIRMATION_PILOT_2026_10_15.md`).
3. **Population and selection.** FS is a disrupted population and LS a certified one
   (Section 4, "Two populations"); screening outcomes separate "not disrupted" from
   "unresolved" and "error" (Section 2).
4. **Recoverable** means a verified finite upper bound (Section 6).
5. **Larger missions** are reported by their R1 strata, and a stratified subset of the
   unresolved ones is piloted first (Section 5).

Third amendment of 16 October (battery and placement): a diagnosis of the constructions
showed three things. Most of them never produced a candidate. With tight batteries, their
witness failed the exact checker: affected UAVs kept routes that ran out of battery, and
the construction misjudged the load a UAV in the air carries. Changes:

- **Trouble.** A task is in trouble when the affected UAV now delivers it late, or can no
  longer reach it on its battery.
- **Battery in W.** The affected UAVs' remaining routes in W must be within battery, with
  a recharge stop if one makes them so. The battery estimate counts everything a UAV in
  the air has on board.
- **Exact check per candidate.** Each candidate that passes the screens goes through the
  exact checker with its deadlines (up to 6 per draw). A failed candidate is skipped; it
  no longer ends the draw.
- **Deficit placement.** The 2 x 2 block preferred is one where two or more affected UAVs
  still have deliveries inside it.
- **Chain placement.** The leg preferred is the one into a task that one other UAV's
  remaining route passes much nearer than any other's.

- **Depot stock** (17 October). In flight, the goods for the tasks W moves are already on
  board the affected UAVs, so the helpers must load new units at the depot, which often had
  none left. A diagnosis confirmed this: the candidate passed with two more units. The
  Level-4 recipes therefore set the depot stock to the generator's largest level, 1.5 x total
  demand; other draws keep the generator's random 1, 1.25 or 1.5.
- **In-flight deadline floor** (17 October). The previous-plan check made from the
  snapshot state can need slightly more time for a UAV in the air than the take-off floor
  gives. A constructed deadline that check rejects rises in doubling steps from 1e-5 h until
  it is accepted; the number of steps is recorded.

All of these change only which draws are tried and how W is built. The class still comes
from the certified (or pooled) minimum alone. In a paired development scan (exploration
seed 77981, 60 Level-4 draws, 600 s labels), the stock change turned one in-flight deficit
draw into a certified Level-4 instance; before it, the same draws gave none.

Amendment of 16 October: with a one-cell update the deficit construction produced no
Level-4 instance. Its update is now a 2 x 2 block (Section 4, Level 4). Decision 5 of
Section 10 (one cell, fixed) still holds for FS and for every other LS recipe; LS reports
the update size of each Level-4 instance through its recipe.

Second amendment of 16 October: a targeted pilot showed that Level 3 usually escapes the
constructions through task trades. Both constructions now tighten deadlines against each
lower-level plan the screen finds (Section 4, Level 4). A re-pilot showed that the 60 s PH
screen missed most of the Level-3 plans the reference run later found, so the screen is now
CMI itself. A further re-pilot left one draw with Levels 0-3 excluded at 600 s and no plan
found by CMI, while its construction witness is an exact-checked Level-4 plan. The label is
therefore pooled with that witness (Section 4, Labels). Every lowered deadline is recorded in
the draw's ledger. Lowering a deadline only removes plans: the witness stays feasible, and
the class still comes from the certified minimum alone.
