# Physically grounded case study 2: results (off-centre depot, 6 UAVs x 4 tasks, multiple sorties)

Date: 21 October 2026.

- **Design:** `PHYSICAL_CASE_STUDY_2_DESIGN_2026_10_21.md`, run with its recommended decisions: both
  deadline profiles, both anchors, update at dispatch only, 6 UAVs x 4 tasks. Nothing in the design
  was changed after labelling began.
- **Code:** `src/final_study/physical_case2.py`, `scripts/run_physical_case2.py`,
  `tests/test_physical_case2.py`.
- **Results:** `results/physical_case2_2026_10_21/`:
  - `build.json`: nominal report, fallbacks, scenario and source hashes;
  - `scenarios.json.gz`;
  - `smoke.json.gz`;
  - `labels/`, `summary.json` and `label.log`.

This is one mission. It shows how the hierarchy behaves on a physically grounded multi-sortie
mission. It does not give recovery frequencies.

## 1. Nominal mission (before any update)

The dispatcher rule (sectors by bearing from the depot, priority order, a depot stop before an
overload) gives the following plan:

| UAV | Stops | Sortie loads (units of 10 kg) | Back at depot |
|---|---|---|---:|
| U1 | T6, T12, T11, DEPOT, T24, DEPOT | 3.0, 0.5 | 20.3 min |
| U2 | T1, T15, T18, DEPOT, T5, DEPOT | 3.0, 1.0 | 19.3 min |
| U3 | T13, T16, T21, T19, DEPOT | 3.0 | 13.5 min |
| U4 | T17, T4, DEPOT, T3, T7, DEPOT | 2.5, 1.5 | 21.2 min |
| U5 | T14, T20, T22, T8, DEPOT | 3.0 | 13.7 min |
| U6 | T10, T2, T23, T9, DEPOT | 3.0 | 13.9 min |

- **Exact checker:** accepts the incumbent under the calm previous forecast for both profiles.
- **Battery:** the smallest nominal reserve margin is 900 Wh.
- **Delivery margins:** the tightest is 4.8 min under P15 and 1.5 min under P10.
- **Fallbacks:** P15 needs none. Under P10, urgent T23 (U6's third stop) arrives at 10.16 min
  against a 10 min target, so it gets the promised time of 12 min.
- **Smoke control:** a declared zero-change update on C33 certified Level 0 and replayed. The
  solver handles the multi-sortie incumbent.

## 2. Outcomes

All 144 instances are certified and replay independently, and none is unresolved. The previous
premise holds in every instance.

| Certified minimum | P15 (72) | P10 (72) | Total |
|---|---:|---:|---:|
| Level 0 | 69 | 66 | 135 |
| Level 1 (re-route) | 2 | 2 | 4 |
| Level 2 (re-sequence, depot stops) | 1 | 0 | 1 |
| Level 3 (reassign) | 0 | 2 | 2 |
| Level 4 | 0 | 0 | 0 |
| No continuation (certified unrecoverable) | 0 | 2 | 2 |

CPU time to certificate:

- median 1.34 s and p90 1.53 s;
- maximum 55.9 s, for an unrecoverable instance;
- Level-3 certificates took 44-46 s.

### Minimum by condition

Each cell lists the minimum at 4/8/12 m/s; NC means no continuation. Affected UAVs and L3 = L4 do
not depend on direction or strength.

| Profile | Anchor | Coverage | Affected UAVs | L3 = L4 | E (4/8/12 m/s) | N | W | S |
|---|---|---|---:|---|---|---|---|---|
| P15 | A1 | K1 | 1 | no | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 |
| P15 | A1 | K2 | 2 | no | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 |
| P15 | A1 | K3 | 5 | yes | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 |
| P15 | A2 | K1 | 3 | no | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 |
| P15 | A2 | K2 | 5 | yes | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 |
| P15 | A2 | K3 | 6 | yes | 0/0/0 | 0/0/1 | 0/0/1 | 0/0/2 |
| P10 | A1 | K1 | 1 | no | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 |
| P10 | A1 | K2 | 2 | no | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 |
| P10 | A1 | K3 | 5 | yes | 0/0/0 | 0/0/0 | 0/0/1 | 0/0/0 |
| P10 | A2 | K1 | 3 | no | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 |
| P10 | A2 | K2 | 5 | yes | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 |
| P10 | A2 | K3 | 6 | yes | 0/0/0 | 0/0/1 | 0/3/NC | 0/3/NC |

### The nine disrupted instances

| Instance | Incumbent breaks | Max incumbent delay (s) | Excluded | Minimum | UAVs changed | Reassigned | Sequence edits | Rerouted/new legs | Depot stops added | Battery margin of plan (Wh) | CPU to certificate (s) |
|---|---|---:|---|---:|---:|---:|---:|---|---:|---:|---:|
| P10-A1-K3-W-12 | deadline T15 | 420 | 0 | 1 | 1 | 0 | 0 | 1/0 | 0 | 205 | 2.2 |
| P15-A2-K3-N-12 | U6 return reserve | 320 | 0 | 1 | 1 | 0 | 0 | 1/0 | 0 | 142 | 3.9 |
| P10-A2-K3-N-12 | U6 return reserve | 320 | 0 | 1 | 1 | 0 | 0 | 1/0 | 0 | 142 | 4.8 |
| P15-A2-K3-W-12 | U2, U3 return reserves | 730 | 0 | 1 | 2 | 0 | 0 | 2/0 | 0 | 33 | 2.5 |
| P15-A2-K3-S-12 | deadline T23; U5, U6 reserves | 661 | 0, 1 | 2 | 5 | 0 | 4 | 1/13 | 0 | 22 | 22.6 |
| P10-A2-K3-W-8 | deadline T15 | 187 | 0, 1, 2 | 3 | 4 | 2 | 3 | 1/14 | 1 | 656 | 44.2 |
| P10-A2-K3-S-8 | deadline T23 | 169 | 0, 1, 2 | 3 | 5 | 1 | 2 | 1/14 | 1 | 728 | 46.0 |
| P10-A2-K3-W-12 | 6 deadlines; U2, U3 reserves | 730 | 0-4 | none | | | | | | | 34.7 |
| P10-A2-K3-S-12 | 6 deadlines; U5, U6 reserves | 661 | 0-4 | none | | | | | | | 55.9 |

In P15-A2-K3-S-12, the Level-2 search ran out of its time slice. The plan that certifies minimum 2
was found during the Level-3 search, and its own level is 2. Level 1 had already been excluded by
proof.

## 3. How the hierarchy behaved

**Restricted repairs often suffice.** Five of the nine disruptions are repaired at Level 1 or 2.

- **Level 1:** the repair re-routes one or two legs, mostly return legs. They then avoid the
  strongest headwind on the way back to the depot.
- **Level 2:** one plan re-sequences routes without moving any task between UAVs.

**Broader permissions become necessary.** Under the surge profile with an 8 m/s wind over the
depot side (P10-A2-K3, W and S), Levels 0-2 are excluded by proof. The certified repair:

- reassigns one or two tasks between UAVs;
- adds a depot stop (a third sortie for one UAV);
- re-plans 14 legs across 4-5 UAVs.

This is the first physically grounded instance in which reassignment is provably necessary.

**The update can make the mission unrecoverable.** At 12 m/s over the depot side under P10, six
deadlines and two landing reserves fail. Every level, including global replanning, is excluded by
proof, so the method returns a certificate that no continuation exists. The same strength under
P15 is recoverable at Level 1 or 2. Under P10, the strength rising from 8 to 12 m/s moves these
conditions from Level 3 to unrecoverable.

**Energy now binds.** Case 1's battery never could. Here a 12 m/s wind over the depot side makes
the long final return legs of fully loaded single-sortie routes (U3, U5, U6) and of U2 cost up to
5 times their calm energy, which breaks the 20% landing reserve.

- In P15-A2-K3-N-12, P10-A2-K3-N-12 and P15-A2-K3-W-12 the incumbent breaks only a reserve, not
  a deadline.
- The repaired plans keep as little as 22-33 Wh above the reserve.

**Level 3 against Level 4.** With 6 UAVs and one helper, the two levels coincide when 5 or more
UAVs are affected.

| Conditions | Affected UAVs | Level 3 vs Level 4 | Outcome |
|---|---:|---|---|
| A1-K1 | 1 | distinct | all Level 0 |
| A1-K2 | 2 | distinct | all Level 0 |
| A2-K1 | 3 | distinct | all Level 0 |
| A1-K3 | 5 | coincide | |
| A2-K2 | 5 | coincide | |
| A2-K3 | 6 | coincide | both Level-3 minima and both unrecoverable cases |

- Level 3 and Level 4 are distinct in 72 of the 144 instances, and coincide in the other 72.
- Moving the depot off-centre kept far updates local, and Levels 3 and 4 distinct there. But
  every disruption needing more than Level 2 came from the large depot-side update. There, the
  Level-3 release already covers the whole fleet.
- So this case shows reassignment is sometimes **necessary**. It does not show a case where
  reassignment within a strict subset of the fleet is enough while Level 4 adds options. Updates
  far from the depot (A1) affected 1-2 UAVs but caused no disruption except one Level-1 case.

**Deadline profile.** P10 (shorter targets) produced 6 non-zero outcomes against 3 under P15,
including every Level-3 and unrecoverable case. As in case 1 and FS, slack relative to the
wind-induced delay largely decides the level.

## 4. Comparison with case 1

| | Case 1 | Case 2 |
|---|---|---|
| Fleet and tasks | 4 x 3, one sortie each | 6 x 4, three UAVs fly two sorties |
| Depot | centre | south-west edge |
| Instances | 36 | 144 |
| Disrupted | 3 (8%) | 9 (6%) |
| Minima above 0 | Levels 1-2 only | Levels 1, 2, 3 and no continuation |
| Energy binding | never | a landing reserve breaks in 6 of 9 disruptions |
| Level 3 = Level 4 | 24 / 36 | 72 / 144 |
| Unresolved | 0 | 0 |

## 5. Limitations

All of case 1's limitations still apply: one mission, one aircraft and one district; calm previous
forecast; stationary wind; updates at dispatch only; and the conservative linear energy surrogate.
Case 2 adds:

- **Depot bays:** unlimited, because the certified solver does not model bay capacity. Re-planned
  depot stops never wait.
- **Incumbent:** the dispatcher rule is not optimised. A better plan would usually leave more slack.
- **Selection:** the outcomes are conditional on this geometry. Most of the hierarchy's work comes
  from one region (A2-K3, the 3 x 3 block over the depot side) at the higher strengths.

## 6. Method comparison at 10 s (added 22 October 2026)

**Setup:**
- **Instances:** the 9 disrupted instances. 7 are recoverable; the 2 unrecoverable ones are kept,
  because recognising them is part of the task.
- **Arms and budget:** CMI, PH, LR, GR-c and GR, each with 10 s of CPU, a cold start and the
  final-study settings (`scripts/run_physical_arena.py`).
- **Scoring:** the FS rule. A returned plan counts only if it replays and was returned by the
  10 s cutoff.
- **Replay:** all 45 arm results replay. The largest operation overrun was 1.06 s, by GR-c on an
  unrecoverable instance; no plan was returned late.

| Instance | Reference minimum | CMI | PH | LR | GR-c | GR |
|---|---:|---|---|---|---|---|
| P10-A1-K3-W-12 | 1 | L1 (1 UAV, 0 reassigned), **certified** | L1 (1 UAV, 0 reassigned) | L1 (1 UAV, 0 reassigned) | L3 (2 UAVs, 2 reassigned) | L3 (6 UAVs, 21 reassigned) |
| P10-A2-K3-N-12 | 1 | L1 (1 UAV, 0 reassigned), **certified** | L2 (3 UAVs, 0 reassigned) | L1 (1 UAV, 0 reassigned) | L3 (5 UAVs, 11 reassigned) | L3 (6 UAVs, 20 reassigned) |
| P15-A2-K3-N-12 | 1 | L1 (1 UAV, 0 reassigned), **certified** | L2 (4 UAVs, 0 reassigned) | L1 (1 UAV, 0 reassigned) | L3 (3 UAVs, 3 reassigned) | L3 (6 UAVs, 19 reassigned) |
| P15-A2-K3-W-12 | 1 | L1 (2 UAVs, 0 reassigned), **certified** | L1 (2 UAVs, 0 reassigned) | L1 (2 UAVs, 0 reassigned) | L3 (3 UAVs, 3 reassigned) | L3 (6 UAVs, 23 reassigned) |
| P15-A2-K3-S-12 | 2 | no plan | L2 (5 UAVs, 0 reassigned) | L3 (2 UAVs, 1 reassigned) | L3 (3 UAVs, 3 reassigned) | L3 (6 UAVs, 20 reassigned) |
| P10-A2-K3-S-8 | 3 | no plan | no plan | L3 (2 UAVs, 1 reassigned) | L3 (2 UAVs, 2 reassigned) | L3 (6 UAVs, 23 reassigned) |
| P10-A2-K3-W-8 | 3 | no plan | no plan | L3 (2 UAVs, 1 reassigned) | L3 (2 UAVs, 2 reassigned) | no plan |
| P10-A2-K3-S-12 | none | no plan | no plan | no plan | no plan | no plan |
| P10-A2-K3-W-12 | none | no plan | no plan | no plan | no plan | no plan |

| Arm | Plan returned (of 7 recoverable) | Plan at reference minimum | Certified (of 9) | Mean UAVs changed | Mean tasks reassigned |
|---|---:|---:|---:|---:|---:|
| CMI | 4 | 4 | 4 | 1.25 | 0.00 |
| PH | 5 | 3 | 0 | 3.00 | 0.00 |
| LR | 7 | 6 | 0 | 1.57 | 0.43 |
| GR-c | 7 | 2 | 0 | 2.86 | 3.71 |
| GR | 6 | 1 | 0 | 6.00 | 21.00 |

Means are over the plans each arm returned.

**Where the repair is local (the four Level-1 instances), CMI is best.**

- It returns and certifies the minimum on all four, within 1.7-3.5 s, changing 1-2 UAVs.
- LR matches its plans but cannot prove them minimal.
- PH twice returns a Level-2 plan that changes 3-4 UAVs.
- GR-c reassigns tasks needlessly.
- GR re-plans the whole fleet, moving 19-23 of 24 tasks.

**On the harder instances, CMI fails at 10 s.**

- On the Level-2 instance and both Level-3 instances, CMI returns no plan within 10 s. It works
  upward, excluding lower levels first, and its reference labels needed 22.6-46 s to certify these
  minima.
- LR and GR-c reach a recoverable plan on all of them by working at Level 3 directly. LR's plans
  are at the minimum on both Level-3 instances, and change only 2 UAVs.
- So at this budget LR has the better recovery success (7/7 against 4/7). CMI is the only arm that
  certifies anything.
- On the two unrecoverable instances, no arm returns a plan. CMI's proof of infeasibility needed
  35-56 s in the reference run, so at 10 s nobody can tell the operator that no repair exists.

**Comparison with FS.** This matches the final study: CMI leads where repairs are local and
certification is fast, while Level 3-4 and infeasibility certificates are its short-budget
limitation (`FINAL_STUDY_REVIEW_2026_10_19.md`, claims table). A deployment would pair CMI with a
fast fallback plan, such as LR's, while certification continues.

**Contention:** CPU times are inflated, because another study shared the machine during this run.
A rerun without it (Section 7) gave identical outcomes and did not lower the CPU times.

## 7. Rerun without contention, and the comparison at 60 s (added 23 October 2026)

**Setup:**
- **Runs:** the Section 6 comparison again at 10 s, and once at 60 s
  (`scripts/run_physical_arena.py --budget 60 --out ...`). Same code, settings, `wind_benchmark`
  environment (Python 3.10.21) and 3 workers as Section 6. Of the source files, only
  `src/final_study/support_sensitivity.py` had changed since Section 6, and the arena does not use it.
- **Machine:** no other study or Python process ran; ordinary desktop applications did (about 20% CPU
  in total).
- **Results:** `results/physical_arena_idle_2026_10_23/case2/` (`arena_10s/`, `arena_60s/` and
  their summaries). Section 6's files are unchanged.
- **Scoring:** the FS rule, as in Section 6.
- **Replay:** all 45 arm results at each budget replay.

**10 s rerun.**
- Every arm's outcome is identical to Section 6: plan level, plan at the minimum, certified, UAVs
  changed and tasks reassigned.
- CPU times are not lower: CMI's certificates took 1.78-4.48 s, against 1.70-3.52 s in Section 6. The
  budget is CPU time, which the other study barely affected.
- The largest overrun was 2.05 s, by GR-c on unrecoverable P10-A2-K3-W-12; no plan was returned late.

**60 s, by instance.** Changes from 10 s in bold.

| Instance | Reference minimum | CMI | PH | LR | GR-c | GR |
|---|---:|---|---|---|---|---|
| P10-A1-K3-W-12 | 1 | L1 (1 UAV, 0 reassigned), certified | L1 (1 UAV, 0 reassigned) | L1 (1 UAV, 0 reassigned) | L3 (2 UAVs, 2 reassigned) | L3 (6 UAVs, 21 reassigned) |
| P10-A2-K3-N-12 | 1 | L1 (1 UAV, 0 reassigned), certified | **L1 (1 UAV, 0 reassigned)** | L1 (1 UAV, 0 reassigned) | L3 (5 UAVs, 11 reassigned) | L3 (6 UAVs, 20 reassigned) |
| P15-A2-K3-N-12 | 1 | L1 (1 UAV, 0 reassigned), certified | **L1 (1 UAV, 0 reassigned)** | L1 (1 UAV, 0 reassigned) | L3 (3 UAVs, 3 reassigned) | L3 (6 UAVs, 19 reassigned) |
| P15-A2-K3-W-12 | 1 | L1 (2 UAVs, 0 reassigned), certified | L1 (2 UAVs, 0 reassigned) | L1 (2 UAVs, 0 reassigned) | L3 (3 UAVs, 3 reassigned) | L3 (6 UAVs, 23 reassigned) |
| P15-A2-K3-S-12 | 2 | **L2 (5 UAVs, 0 reassigned), certified** | L2 (5 UAVs, 0 reassigned) | L3 (2 UAVs, 1 reassigned) | L3 (3 UAVs, 3 reassigned) | L3 (6 UAVs, 20 reassigned) |
| P10-A2-K3-S-8 | 3 | **L3 (5 UAVs, 1 reassigned), certified** | no plan | L3 (2 UAVs, 1 reassigned) | L3 (2 UAVs, 2 reassigned) | L3 (6 UAVs, 23 reassigned) |
| P10-A2-K3-W-8 | 3 | **L3 (4 UAVs, 2 reassigned), certified** | no plan | L3 (2 UAVs, 1 reassigned) | L3 (2 UAVs, 2 reassigned) | no plan |
| P10-A2-K3-S-12 | none | **no continuation, certified** | no plan | no plan | no plan | no plan |
| P10-A2-K3-W-12 | none | **no continuation, certified** | no plan | no plan | no plan | no plan |

| Arm | Plan returned (of 7 recoverable), 10 s / 60 s | Plan at reference minimum | Certified (of 9) | Mean UAVs changed | Mean tasks reassigned |
|---|---:|---:|---:|---:|---:|
| CMI | 4 / **7** | 4 / **7** | 4 / **9** | 1.25 / 2.71 | 0.00 / 0.43 |
| PH | 5 / 5 | 3 / **5** | 0 / 0 | 3.00 / 2.00 | 0.00 / 0.00 |
| LR | 7 / 7 | 6 / 6 | 0 / 0 | 1.57 / 1.57 | 0.43 / 0.43 |
| GR-c | 7 / 7 | 2 / 2 | 0 / 0 | 2.86 / 2.86 | 3.71 / 3.71 |
| GR | 6 / 6 | 1 / 1 | 0 / 0 | 6.00 / 6.00 | 21.00 / 21.00 |

Means are over the plans each arm returned.

**Findings:**
- **CMI decides every instance at 60 s.** It certifies the Level-2 minimum in 21.1 s, the two Level-3
  minima in 26.9-32.0 s, and no continuation on both unrecoverable instances in 31.2-38.0 s. The
  reference labels took 22.6-55.9 s on the same five instances. No CMI run overran.
- **No other arm can tell the operator that no repair exists**, at either budget.
- **PH improves on the two Level-1 instances**, where it had returned Level-2 plans at 10 s. Its
  5/15/20/30/30% split gives Level 1 9 s at 60 s against 1.5 s at 10 s, which probably explains
  this. It still returns no plan on
  either Level-3 instance. Its largest overrun was 0.58 s.
- **LR, GR-c and GR are unchanged.** None of them certifies anything here, so more time does not help
  them.
- **CMI's higher-level plans change more UAVs than LR's.** At Level 3 they change 4-5 UAVs where LR's
  change 2; at Level 2, 5 UAVs, like PH's. CMI minimizes the level, not the edits within it.
- So the short-budget limitation of Section 6 is a budget effect: at 60 s CMI returns the minimum on
  all 7 recoverable instances and certifies all 9, as on the FS 60 s subset (`FINAL_STUDY_RESULTS_2026_10_18.md`).

## Reproduce

```
python -m pytest -q tests/test_physical_case2.py
python scripts/run_physical_case2.py build
python scripts/run_physical_case2.py smoke
python scripts/run_physical_case2.py label --workers 6
python scripts/run_physical_case2.py summary
```

- **Environment:** the `wind_benchmark` environment.
- **Integrity:** `label` and `summary` refuse to run if a scenario differs from the hashes in
  `build.json` or from what the current code builds.
- **Inputs:** `results/final_study_2026_10_17` is read only.
- **Run time:** the 144 labels took about 3 minutes on 6 workers.
- **Tests:** the full suite passes, 630 tests, including the new ones.
- **Comparison (Section 6):** `python scripts/run_physical_arena.py --workers 3`.
- **Section 7:** `--out OUT` writes to `OUT/case1` and `OUT/case2` instead of the case results
  folders; `--budget 60` sets the CPU budget per arm (default 10).

  ```
  python scripts/run_physical_arena.py --workers 3 --out results/physical_arena_idle_2026_10_23
  python scripts/run_physical_arena.py --workers 3 --budget 60 --out results/physical_arena_idle_2026_10_23
  ```
