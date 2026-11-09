# Physically grounded case study 2: off-centre depot, multiple sorties (design)

Date: 21 October 2026. Status: **design only, not implemented.** No scenario has been built and
no label computed. Everything below is fixed before any recovery outcome is seen.

## Why a second case

Case 1 (`PHYSICAL_CASE_STUDY_2026_10_21.md`) left the hierarchy little to do:

- the 13-min nominal wave beat its 15/30/60-min targets by at least 3.6 min;
- one sortie per UAV and a central depot meant no depot decisions;
- every update covering the centre affected the whole fleet, so Level 3 equalled Level 4 in 24 of
  the 36 conditions;
- 33 of 36 conditions were Level 0; the rest needed Level 1 or 2.

Case 2 asks the same questions on a mission with less slack and more structure. Do restricted
repairs still suffice sometimes? Do broader permissions (reassignment, global reoptimisation)
become necessary sometimes? It changes three things:

- **More tasks per UAV:** 6 UAVs and 24 tasks, 4 tasks per UAV.
- **Multiple sorties:** a heavier commodity unit forces most UAVs to return to reload, so the plan
  contains depot stops.
- **Off-centre depot:** at the district's south-west edge. Return legs no longer converge on the
  centre, and updates away from the depot leave part of the fleet unaffected.

It remains one mission. It cannot give recovery frequencies, and nothing is redrawn or retuned
after labelling.

## 1. Operating scenario

The flash-flood district of case 1: 2 km x 2 km, with the same 4 x 4 wind cells of 500 m.

- **Depot:** the forward depot is a stadium on dry ground at the south-west edge,
  `depot_xy = (-0.95, -0.95)`. It sits off the 100 m task grid, so no task coincides with it,
  inside wind cell C00.
- **Tasks:** positions, demands, urgency classes and depot stock come from FS mission
  `FS_6x4_medium_ample_uniform_76101`:
  - 24 tasks, total demand 20.5 units;
  - stock 25.625 units (1.25 x demand), so a repair can draw extra units;
  - 8 tasks in each class.
- **Requests:** all known at dispatch (t = 0).

## 2. Aircraft and physics: unchanged from case 1, except the unit mass

- **Aircraft:** DJI FlyCart 30, dual battery. Same values as case 1:
  - airspeed 54 km/h, mass with batteries 65 kg, payload 30 kg;
  - battery 3968.8 Wh, reserve 20%;
  - energy coefficient gamma 2.62 Wh/(kg km), fitted as in case 1;
  - service 90 s and 331 Wh;
  - turnaround 3 min, battery swap;
  - wind limit 12 m/s.
- **Commodity unit: 10 kg**, one combined medical and water-treatment kit. Demands of 0.5, 1 and
  1.5 units are 5, 10 and 15 kg, all inside the documented 5-30 kg winch range. This removes case
  1's below-minimum winch limitation. A sortie carries at most 3 units (30 kg).
- **Depot:** unlimited bays, `depot_bays = None`. The certified solver does not model bay
  capacity, so swaps never wait. This is a stated limitation.

## 3. Nominal plan: a stated dispatcher rule

The incumbent is built by rule, and nothing in the rule reads a recovery result:

1. **Sectors.** Sort tasks by bearing from the depot; ties go to the nearer task, then the lower
   id. Cut the sorted list into 6 contiguous blocks of 4 and give block j to UAV U(j+1). FS used
   round-robin assignment; a dispatcher would assign contiguous sectors.
2. **Order within a UAV.** Urgent tasks first, then essential, then routine. Within each class,
   use nearest neighbour from the current position, starting at the depot.
3. **Sorties.** Walk that order. Before a task whose full demand would push the onboard load over
   30 kg, insert a depot stop: swap batteries and load the next sortie. Each visit delivers its
   full demand.
4. **Paths:** straight legs; reserve paths straight back to the depot. The slot bound stays at 11,
   the FS value for 4 tasks per UAV.

## 4. Deadlines and horizon

Two priority-target profiles, both fixed now:

| Profile | Urgent | Essential | Routine | Reading |
|---|---:|---:|---:|---|
| **P15** | 15 min | 30 min | 60 min | the case 1 targets |
| **P10** | 10 min | 20 min | 40 min | surge triage: the coordination cell shortens all targets |

**Promised-time fallback.** Some tasks cannot meet their target even in the nominal plan:
nominal certified arrival + 1 min > target. Their deadline becomes the promised time instead:
nominal arrival rounded up to the next whole minute, plus 1 min. This is what a dispatcher
tells a site that cannot be served in time. The number of fallback tasks per profile is reported.
No other deadline is adjusted.

**Horizon:** 90 min, as in case 1.

**Nominal checks before any update.** Under the calm previous forecast:

- the exact checker (`previous_premise`) must accept the incumbent under both profiles;
- the following are reported:
  - each UAV's sorties and loads;
  - every arrival time and margin;
  - every battery margin at depot arrival.

If either profile fails the check, the study stops there and the failure is reported. The rule is
not tuned.

## 5. Wind-update conditions

| Factor | Levels |
|---|---|
| Anchor cell | **A1 = C33**, the far corner from the depot (as in case 1). **A2 = C11**, diagonally next to the depot cell. |
| Coverage | **K1:** the anchor cell. **K2:** a 2 x 2 block. **K3:** a 3 x 3 block. Blocks grow toward the grid centre by the rule of `SUPPORT_SENSITIVITY_DESIGN_2026_10_21.md`: x range `x, x+1` if `x <= 1`, else `x-1, x`; 3 x 3 starts at `clamp(x-1, 0, 1)`; the same for y. |
| Direction | E, N, W, S: the direction the wind blows toward |
| Strength | 4, 8 and 12 m/s |
| Update time | at dispatch, t = 0 |

The resulting blocks:

- **A1:** K2 is {C22, C23, C32, C33}; K3 is C11 to C33. Neither contains the depot cell.
- **A2:** K2 is {C11, C12, C21, C22}; K3 is C00 to C22. K3 contains the depot cell and the
  depot.

A1 and A2 were chosen for their position relative to the depot, not from any plan or label. A1
mostly hits outbound task legs. A2-K3 hits every departure, the case most likely to make
Level 3 equal Level 4.

**Size:** 2 anchors x 3 coverages x 4 directions x 3 strengths = 72 updates per profile, so
**144 labelled instances**.

## 6. Labels and run

- **Labels:** each instance is labelled exactly as in case 1 and `fs-label`:
  - CMI with a 600 s CPU budget, one pass;
  - the final-study settings;
  - an independent replay of every result, with its proof stored.
- **Two-phase runner.** `build` writes the nominal plans, the 144 scenarios and their content
  hashes, plus the source hashes, and commits nothing. `label` refuses to run if any scenario hash
  differs from the build record.
- **Smoke test before labelling.** One control instance gets a declared update support with zero
  change: support on C33, received wind equal to the previous. It must certify Level 0 and replay.
  This checks that the solver and replay handle multi-sortie incumbents (mid-route depot stops)
  without revealing any condition's outcome. If it fails, the study stops for a fix.
- **Cost on 6 workers:** worst case 144 x 600 s / 6 = 4 h. Case 1's labels took 0.4-2.8 s each,
  but 6 UAVs with depot stops will be slower. Expect well under an hour.

## 7. What is reported

**Per instance:**

- the affected UAVs, and whether Level 3 already releases the whole fleet (|U0| >= 5 with 6 UAVs
  and one helper);
- the certified incumbent delay, and the tasks late under the incumbent;
- the excluded levels and the certified minimum, or the bracket if unresolved;
- the decisions in the minimum-level plan:
  - UAVs changed, and those changed outside U0;
  - tasks reassigned, sequence edits, re-routed and new legs;
  - depot stops added or removed;
- CPU time to the first plan and to the certificate;
- the replay result;
- the smallest battery margin in the returned plan (does energy ever bind?).

**Summaries:**

- the distribution of minima by profile, anchor, coverage, direction and strength;
- the unresolved count;
- the share of instances where Level 3 equals Level 4.

**Pairing with case 1:** for anchor A1 under P15, the same coverage, direction and strength
conditions as case 1. They differ in mission, so this is a description, not a test.

There are no pass or fail thresholds. Any of these outcomes is reportable:

- restricted repairs suffice throughout;
- broader levels appear;
- certification degrades on the larger mission.

## 8. Limitations, stated in advance

- One mission, one aircraft and one district.
- Calm previous forecast, stationary wind, and updates at dispatch only.
- Unlimited depot bays.
- The linear energy surrogate is conservative by up to 20% when the aircraft is light.
- The dispatcher rule is one reasonable rule, not an optimised plan; a better incumbent would
  usually leave more slack.

## 9. Decisions before implementation

1. **Profiles.** Both P15 and P10 (recommended: P15 links to case 1, and P10 is the low-slack
   test), or P15 only (72 instances).
2. **Anchors.** Both A1 and A2 (recommended), or A1 only (72 instances with both profiles).
3. **Update time.** At dispatch only (recommended, as in case 1), or also at half the makespan
   under D1'. That would test an update arriving during second sorties and double the instances.
   The in-flight snapshot builder supports blocks, as FS's Level-4 recipe already used.
4. **Fleet.** 6 UAVs x 4 tasks (recommended; with 4 UAVs one helper often already covers most of
   the fleet), or 4 UAVs x 4 tasks from `FS_4x4_medium_ample_uniform`.

## 10. Implementation outline (after approval)

- `src/final_study/physical_case2.py`:
  - the depot, unit and dispatcher-rule plan builder (multi-sortie loads at depot stops);
  - the two profiles with the promised-time fallback;
  - the anchors and coverage rule;
  - the aircraft constants, imported from `physical_case.py` so both cases share them.
- `scripts/run_physical_case2.py`, with `build`, `smoke`, `label` and `summary` phases. It writes
  to `results/physical_case2_2026_10_xx/`.
- `tests/test_physical_case2.py`:
  - sectors are contiguous and each holds 4 tasks;
  - no sortie exceeds 30 kg, and loads at depot stops balance the deliveries;
  - urgent tasks precede essential, which precede routine, within each UAV;
  - fallback deadlines follow the stated formula, and only where the target is unreachable;
  - each condition changes only the received wind on its cells;
  - the nominal plan passes the previous premise under both profiles.
- Run order: tests, then build with the nominal report, then the smoke control, then labels, then
  the report `PHYSICAL_CASE_STUDY_2_2026_10_xx.md`.
