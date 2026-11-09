# Physically grounded case study: one FlyCart 30 mission under 36 fixed wind updates

Date: 21 October 2026. Code: `src/final_study/physical_case.py`, `scripts/run_physical_case.py`,
`tests/test_physical_case.py`. Results: `results/physical_case_2026_10_21/` (`scenarios.json.gz`,
`diagnosis.json`, `labels/`, `summary.json`).

This case study supplements the FS experiments, which remain the broad synthetic evaluation. It shows
engineering relevance for one mission only. It does not establish general recovery frequencies, or
validity for other platforms.

**Status of the parameters.**

- The energy surrogate is **fitted** to documented consumption data (one parameter, two points).
- Service and turnaround durations are engineering estimates built from documented winch and
  descent rates. They are not fitted.
- Deadlines and the horizon come from a stated scenario.

The case is therefore **physically grounded**, not fully calibrated.

## 1. Operating scenario

A flash flood hits a 2 km x 2 km urban district. A field depot at the centre dispatches four
identical cargo drones to 12 shelters and clinics. All requests are known at dispatch (t = 0).

- **Taken unchanged from FS mission `FS_4x3_medium_ample_uniform_76029`:**
  - the geometry, demands and depot stock (15 units);
  - the urgency class of each task;
  - the incumbent: assignment, visiting order, straight legs, one sortie per UAV;
  - the wind grid, 4 x 4 cells of 500 m.

  This keeps the case reproducible and traceable to FS.
- **Delivery targets by priority** (the FS class of each task):

  | Priority | Example | Target |
  |---|---|---|
  | Urgent | medical | within 15 min |
  | Essential | water treatment, food for vulnerable groups | within 30 min |
  | Routine | | within 60 min |

  These are scenario assumptions, not data. Deadlines are absolute times from dispatch. They are
  not offsets from the plan's arrival times, as they are in FS.
- **Horizon:** 90 min, the airspace window of the dispatch wave. Every UAV must be back at the
  depot by then.
- **Wind:** the previous forecast is calm, and the update is received at dispatch.

## 2. Reference aircraft: DJI FlyCart 30, dual-battery mode

Source: [DJI FlyCart 30 specifications](https://www.dji.com/flycart-30/specs), read 21 October 2026.
DJI marks these figures as reference values measured at zero altitude without wind.

| Documented | Value | Model parameter |
|---|---|---|
| Weight with two DB2000 batteries | 65 kg | `empty_mass_kg` = 65 |
| Max take-off weight | 95 kg | |
| Winch load, dual battery | 5-30 kg | `payload_capacity_kg` = 30 |
| Battery | 2 x DB2000, 1984.4 Wh each | `battery_capacity_wh` = 3968.8 |
| Max flight distance at constant 15 m/s, no wind | 28 km at 65 kg; 16 km at 95 kg (30 kg load) | energy fit (Section 3) |
| Hover time | 29 min at 65 kg; 18 min at 95 kg | cross-check and service energy |
| Max wind resistance | 12 m/s | wind bound 12 m/s (43.2 km/h) |
| Max horizontal speed | 20 m/s | airspeed 15 m/s (54 km/h), DJI's measurement speed |
| Winch | 20 m cable, 0.8 m/s | service duration |
| Descent / ascent | 3 m/s / 5 m/s | service duration |

Other values:

- **Commodity unit:** 6 kg, one relief kit. The largest route load is 4 units (24 kg).
- **Landing reserve:** 20% of the battery, 793.76 Wh. This is an operating policy, not a DJI figure.
- **Fleet:** homogeneous. The FS heterogeneous airspeeds are dropped, because the energy fit holds
  only at the documented 15 m/s.

## 3. Energy surrogate fit

The formulation's power model is `P = gamma * m * v_air`. In still air the energy per km is
`gamma * m`, whatever the speed. The table uses the two documented distance points and assumes the
whole 3968.8 Wh is used:

| Take-off mass | Documented Wh/km | gamma that fits this point | Model, gamma = 2.62 | Error |
|---|---:|---:|---:|---:|
| 65 kg | 141.7 | 2.18 | 170.3 | +20.1% |
| 95 kg | 248.1 | 2.61 | 248.9 | +0.3% |

- **No single coefficient fits both points.** Consumption grows faster than linearly with mass.
- **Choice: gamma = 2.62 Wh/(kg km), fitted to the heavy point.** The surrogate then never
  underestimates documented consumption, and overstates it by up to 20% when the aircraft is light.
- Assuming the whole battery is used also makes the documented Wh/km an upper bound.

**Cross-check against hover data.** Documented cruise power is Wh/km x 54 km/h:

| Mass | Cruise power at 15 m/s | Hover power |
|---|---:|---:|
| 65 kg | 7.65 kW | 8.21 kW |
| 95 kg | 13.39 kW | 13.23 kW |

Cruise power is close to hover power, as expected for a multirotor near its endurance speed.

## 4. Service and turnaround

**Service (winch delivery): 90 s = 0.025 h.**

| Step | Time |
|---|---:|
| Descend 30 m at 3 m/s | 10 s |
| Lower 20 m at 0.8 m/s | 25 s |
| Release | 10 s |
| Retract 20 m | 25 s |
| Climb 30 m at 5 m/s | 6 s |
| **Total** | **76 s, rounded up to 90 s** |

**Service energy: 331 Wh.** This is hover power at max take-off weight (13.23 kW) for 90 s. It is
conservative, and in the model it does not depend on mass.

**Depot turnaround: 3 min = 0.05 h**, a swap to a charged battery pair plus cargo loading.

- The model resets the battery to full capacity at a depot stop. That is valid for **swapping**
  only.
- Charging in place would take at least 3968.8 Wh / (2 x 5700 W) = 21 min at the batteries'
  maximum charging power, and longer in practice. It would need a different turnaround model.

## 5. Nominal mission

The incumbent was checked under the previous (calm) forecast before any update was applied.

- **Previous premise:** accepted by the exact checker (`previous_premise`).
- **Timing:** deliveries land between 4.6 and 11.4 min, and every UAV is back by 12.9 min.
  - The tightest margin is urgent T8, U3's third stop: it arrives at 11.43 min against a 15 min
    target, a margin of **3.6 min**.
  - The next tightest is urgent T3, with 5.0 min.
- **Energy:** each UAV returns with 2,098-2,418 Wh against a 794 Wh reserve.

In a 2 km area with one sortie per UAV, **the battery cannot bind**. The FS recharge mechanism for
Level 2 is therefore absent here.

## 6. Wind-update conditions, fixed before labelling

The 3 x 4 x 3 = 36 conditions were written in code before any label was computed:

| Factor | Levels |
|---|---|
| Coverage | **K1:** cell C33, the FS generator's random draw for the source mission. **K2:** the 2 x 2 block containing C33, grown toward the grid centre. **K3:** the 3 x 3 block, grown the same way. Same rule as `SUPPORT_SENSITIVITY_DESIGN_2026_10_21.md`. |
| Direction | E, N, W, S: the direction the wind blows toward |
| Strength | 4, 8 and 12 m/s; 12 m/s is the rated wind resistance |

**Labels:** each condition was labelled like `fs-label`:

- CMI with a 600 s CPU budget, one pass;
- the final-study settings;
- every result replayed independently.

## 7. Results

**All 36 conditions** have a certified minimum and replay independently. None is unresolved, and
the previous premise holds in every one.

| Certified minimum | Conditions |
|---|---:|
| Level 0 (the update does not break the plan) | 33 |
| Level 1 (re-route only) | 2: K2-S-12 and K3-W-12 |
| Level 2 (re-sequence) | 1: K3-S-12 |
| Level 3, Level 4, no continuation | 0 |

CPU time to the certificate: 0.4-0.6 s at Level 0, and 1.3-2.8 s for the three repairs.

| Coverage | Dir | m/s | Affected UAVs | L3 = L4 | Max incumbent delay (s) | Late under incumbent | Excluded | Certified minimum | UAVs changed | Reassigned | Sequence edits | Rerouted/new legs | CPU to certificate (s) |
|---|---|---:|---|---|---:|---|---|---:|---:|---:|---:|---|---:|
| K1 | E | 4 | 2 (U2,U3) | no | 2 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.48 |
| K1 | E | 8 | 2 (U2,U3) | no | 7 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.53 |
| K1 | E | 12 | 2 (U2,U3) | no | 26 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.48 |
| K1 | N | 4 | 2 (U2,U3) | no | 0 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.50 |
| K1 | N | 8 | 2 (U2,U3) | no | 0 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.55 |
| K1 | N | 12 | 2 (U2,U3) | no | 0 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.41 |
| K1 | W | 4 | 2 (U2,U3) | no | 1 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.55 |
| K1 | W | 8 | 2 (U2,U3) | no | 5 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.56 |
| K1 | W | 12 | 2 (U2,U3) | no | 18 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.48 |
| K1 | S | 4 | 2 (U2,U3) | no | 12 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.50 |
| K1 | S | 8 | 2 (U2,U3) | no | 38 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.50 |
| K1 | S | 12 | 2 (U2,U3) | no | 133 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.47 |
| K2 | E | 4 | 4 (U1,U2,U3,U4) | yes | 4 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.45 |
| K2 | E | 8 | 4 (U1,U2,U3,U4) | yes | 15 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.48 |
| K2 | E | 12 | 4 (U1,U2,U3,U4) | yes | 53 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.48 |
| K2 | N | 4 | 4 (U1,U2,U3,U4) | yes | 3 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.45 |
| K2 | N | 8 | 4 (U1,U2,U3,U4) | yes | 16 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.45 |
| K2 | N | 12 | 4 (U1,U2,U3,U4) | yes | 71 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.48 |
| K2 | W | 4 | 4 (U1,U2,U3,U4) | yes | 6 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.47 |
| K2 | W | 8 | 4 (U1,U2,U3,U4) | yes | 21 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.50 |
| K2 | W | 12 | 4 (U1,U2,U3,U4) | yes | 73 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.45 |
| K2 | S | 4 | 4 (U1,U2,U3,U4) | yes | 24 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.45 |
| K2 | S | 8 | 4 (U1,U2,U3,U4) | yes | 76 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.45 |
| K2 | S | 12 | 4 (U1,U2,U3,U4) | yes | 267 | T8 | 0 | 1 | 1 | 0 | 0 | 1/0 | 1.59 |
| K3 | E | 4 | 4 (U1,U2,U3,U4) | yes | 9 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.50 |
| K3 | E | 8 | 4 (U1,U2,U3,U4) | yes | 32 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.52 |
| K3 | E | 12 | 4 (U1,U2,U3,U4) | yes | 111 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.52 |
| K3 | N | 4 | 4 (U1,U2,U3,U4) | yes | 16 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.48 |
| K3 | N | 8 | 4 (U1,U2,U3,U4) | yes | 56 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.52 |
| K3 | N | 12 | 4 (U1,U2,U3,U4) | yes | 210 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.48 |
| K3 | W | 4 | 4 (U1,U2,U3,U4) | yes | 25 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.50 |
| K3 | W | 8 | 4 (U1,U2,U3,U4) | yes | 86 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.47 |
| K3 | W | 12 | 4 (U1,U2,U3,U4) | yes | 304 | T8 | 0 | 1 | 1 | 0 | 0 | 1/0 | 1.28 |
| K3 | S | 4 | 4 (U1,U2,U3,U4) | yes | 31 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.47 |
| K3 | S | 8 | 4 (U1,U2,U3,U4) | yes | 110 | - | - | 0 | 0 | 0 | 0 | 0/0 | 0.55 |
| K3 | S | 12 | 4 (U1,U2,U3,U4) | yes | 410 | T8 | 0,1 | 2 | 1 | 0 | 2 | 1/3 | 2.77 |

Column definitions:

- **Max incumbent delay:** the largest certified increase in a delivery time when the incumbent is
  flown under the received wind.
- **Late under incumbent:** the tasks whose certified earliest delivery then misses its target.
- **Unresolved:** none in any condition, so the table has no unresolved column.

### How the hierarchy behaved

**Restricted repairs sufficed.** Only a 12 m/s wind over 2 x 2 or 3 x 3 cells broke the plan. In
every such case:

- the late task was urgent T8, the last stop of U3;
- the repair changes one UAV (U3) and reassigns no task.

**Broader permissions became necessary as the update grew.**

| Condition | Excluded | Repair | Minimum |
|---|---|---|---:|
| K2-S-12 | Level 0 | U3 re-routes one leg around the strong wind | 1 |
| K3-W-12 | Level 0 | U3 re-routes one leg around the strong wind | 1 |
| K3-S-12 | Levels 0 and 1 | With the wind over 1.5 km x 1.5 km, re-routing cannot save T8. U3 reorders its stops to reach T8 earlier. | 2 |

**Wider permissions were never needed.** No condition needed reassignment (Level 3) or global
reoptimisation (Level 4), and none was unrecoverable.

**Level 3 against Level 4.**

- Under K1 the affected fleet is {U2, U3}. Level 3 (the affected UAVs plus one helper) involves 3 of
  4 UAVs, so it stays distinct from Level 4.
- Under K2 and K3, every UAV has a leg in the update region, including return legs into the depot at
  the grid centre. So the affected set is the whole fleet, and **Level 3 coincides with Level 4 in
  24 of the 36 conditions**.
- With a central depot, an update that covers the centre makes every UAV affected. Levels 3 and 4
  stay distinct only for updates away from the depot.

**Why the result differs from FS.** The source mission, with the same geometry and update cell in FS
units, certifies Level 1 at strength 2/5 and Level 3 at 3/5 and 4/5. Here every K1 condition is
Level 0. The main reason is **deadline slack relative to the wind delay**, not the aircraft:

- FS deadlines are the plan's arrival times plus a few percent of the makespan. Here deadlines are
  absolute targets, which the 13-min nominal wave beats by 3.6 to 55 min.
- A one-cell 12 m/s update delays the incumbent by at most 133 s.
- Only 2 x 2 and 3 x 3 coverage pushes the delay (267-410 s) past T8's 3.6-min margin.

## 8. Limitations

- **Scope:** one mission, one aircraft type and one scenario. The results are not frequencies and do
  not validate other platforms or mission sizes.
- **Energy model:**
  - the linear surrogate overstates light-aircraft consumption by up to 20%;
  - the service energy does not depend on mass;
  - the 5 kg minimum winch load is not modelled. Divisible deliveries can make a drop below 5 kg; no
    plan here needed one.
- **Wind:** the previous forecast is calm and the wind stationary, as the certified solver
  requires. Gusts, turbulence and wind-dependent power at the same airspeed are not modelled.
- **Timing:** updates arrive at dispatch only. In-flight updates were not run.
- **Scenario:** deadlines and the horizon are assumptions. Tighter targets, more tasks per UAV, or
  several sorties per UAV would leave less slack and would probably need higher levels. Such variants
  must be specified before they are run, as a separate design.

## 9. Method comparison at 10 s (added 22 October 2026)

**Setup:**
- **Instances:** the 3 disrupted instances.
- **Arms and budget:** the five arms of the final-study comparison (CMI, PH, LR, GR-c, GR), each
  with 10 s of CPU, a cold start and the final-study settings (`scripts/run_physical_arena.py`).
- **Scoring:** the FS rule. A returned plan counts only if it replays and was returned by the
  10 s cutoff.
- **Replay:** all 15 arm results replay, and no run overran its budget.

| Instance | Reference minimum | CMI | PH | LR | GR-c | GR |
|---|---:|---|---|---|---|---|
| K2-S-12 | 1 | L1 (1 UAV, 0 reassigned), **certified** | L1 (1 UAV, 0 reassigned) | L1 (1 UAV, 0 reassigned) | L2 (1 UAV, 0 reassigned) | L3 (4 UAVs, 9 reassigned) |
| K3-W-12 | 1 | L1 (1 UAV, 0 reassigned), **certified** | L1 (1 UAV, 0 reassigned) | L1 (1 UAV, 0 reassigned) | L2 (1 UAV, 0 reassigned) | L3 (4 UAVs, 11 reassigned) |
| K3-S-12 | 2 | L2 (1 UAV, 0 reassigned), **certified** | L2 (1 UAV, 0 reassigned) | L2 (1 UAV, 0 reassigned) | L2 (1 UAV, 0 reassigned) | L3 (4 UAVs, 11 reassigned) |

| Arm | Plan returned | Plan at reference minimum | Certified | Mean UAVs changed | Mean tasks reassigned |
|---|---:|---:|---:|---:|---:|
| CMI | 3/3 | 3/3 | 3/3 | 1.00 | 0.00 |
| PH | 3/3 | 3/3 | 0/3 | 1.00 | 0.00 |
| LR | 3/3 | 3/3 | 0/3 | 1.00 | 0.00 |
| GR-c | 3/3 | 1/3 | 0/3 | 1.00 | 0.00 |
| GR | 3/3 | 0/3 | 0/3 | 4.00 | 10.33 |

**Findings:**

- **The local arms tie.** CMI, PH and LR all return the minimum-level plan, changing one UAV.
- **Only CMI also proves the plan minimal**, within 0.9-3.7 s.
- **GR-c** goes one level above the minimum on the two Level-1 instances.
- **Global replanning (GR)** changes all 4 UAVs and reassigns 9-11 of the 12 tasks to fix a delay
  that one re-routed leg resolves. Its plans score as Level 3, not 4: every UAV is affected here,
  so Level 3 already releases the whole fleet.
- **Contention:** CPU times are inflated, because another study shared the machine during this run.
  A rerun without it (Section 10) gave identical outcomes and did not lower the CPU times.

## 10. Rerun without contention, and the comparison at 60 s (added 23 October 2026)

**Setup:**
- **Runs:** the Section 9 comparison again at 10 s, and once at 60 s, both cases together
  (`scripts/run_physical_arena.py --budget 60 --out ...`). Same code, settings, `wind_benchmark`
  environment (Python 3.10.21) and 3 workers as Section 9. Of the source files, only
  `src/final_study/support_sensitivity.py` had changed since Section 9, and the arena does not use it.
- **Machine:** no other study or Python process ran; ordinary desktop applications did (about 20% CPU
  in total).
- **Results:** `results/physical_arena_idle_2026_10_23/case1/` (`arena_10s/`, `arena_60s/` and
  their summaries). Section 9's files are unchanged.
- **Replay:** all 15 arm results at each budget replay, and no run overran its budget.

**10 s rerun.**
- Every arm's outcome is identical to Section 9: plan level, plan at the minimum, certified, UAVs
  changed and tasks reassigned.
- CPU times are not lower: CMI's certificates took 1.14-4.33 s, against 0.92-3.73 s in Section 9. The
  budget is CPU time, which the other study barely affected. The Section 9 contention note therefore
  changes no result.

**60 s.** Every arm's outcome is again identical to 10 s. All three instances were already decided
at 10 s; CMI certifies them in 1.41-4.14 s.

## Reproduce

```
python scripts/run_physical_case.py --out results/physical_case_2026_10_21 --workers 6
python -m pytest -q tests/test_physical_case.py
```

- **Environment:** the `wind_benchmark` environment.
- **Inputs:** the run reads `results/final_study_2026_10_17` read-only, and resumes if interrupted.
- **Provenance:** `diagnosis.json` records the git commit and the SHA-256 of the two source files.
- **Run time:** the 36 labels took about 4 minutes on 6 workers.
- **Comparison (Section 9):** `python scripts/run_physical_arena.py --workers 3` covers both case
  studies. It writes `arena_10s/` and `arena_10s_summary.json` into each case's results folder.
- **Section 10:** the same script with `--out OUT` writes to `OUT/case1` and `OUT/case2` instead;
  `--budget 60` sets the CPU budget per arm (default 10).

  ```
  python scripts/run_physical_arena.py --workers 3 --out results/physical_arena_idle_2026_10_23
  python scripts/run_physical_arena.py --workers 3 --budget 60 --out results/physical_arena_idle_2026_10_23
  ```
