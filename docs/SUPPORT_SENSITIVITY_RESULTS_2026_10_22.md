# Sensitivity of the results to the size of the wind update: results

Date: 22 October 2026. Design: `docs/SUPPORT_SENSITIVITY_DESIGN_2026_10_21.md`, with its recommended
decisions: S5 = 15 of 16 cells (1a, no change to `env/scenario.py`), the secondary 10 s arena (2),
and the 53-mission third of the 60 s arena (3, `third_seed` 76002).

- Code: `src/final_study/support_sensitivity.py`, `scripts/run_support_sensitivity.py`,
  `tests/test_support_sensitivity.py` (9 tests; full suite 639 passed).
- Run: `results/support_sensitivity_2026_10_22` (run hash `d5b8f9f0fb451c19`). It reads
  `results/final_study_2026_10_17` read-only and uses the `configs/final_study/final.json` settings
  (checked equal to the FS manifest). Smoke run on 3 missions: `results/support_sensitivity_smoke`.
- Labels: CMI with 600 s CPU, one pass, through `final_study.arena.label`. Arena: GR, GR-c, LR and CMI
  with 10 s each, through `run_instance`. Wall time: 66 min of labels, 18 min of arena and 9 min
  of replay, on 6 workers.
- Reproduce: `PYTHONPATH=src python scripts/run_support_sensitivity.py --out results/support_sensitivity_2026_10_22 --workers 6`.
  The run resumes if interrupted, under the same code. The tables below are the generated
  `analysis/REPORT.md`, copied at the end.

## Integrity

- S1 payloads are identical to the stored `_r1_t0` variants: 53/53 content hashes match.
- S1 labels give exactly the stored FS label bounds: 53/53. This includes the one FS instance
  left unresolved at 600 s, which is again unresolved with the same bracket.
- S1 arena: CMI returns a plan on 40/53, as in the FS 10 s arena, with the same plan level on 51/53.
  GR returns 51 plans here against 50 in FS; GR and GR-c are randomized under CPU timing.
- Replay:
  - in-run independent replay: 265/265 labels and 1060/1060 arena results;
  - second replay of every stored record from its proof file: 1325/1325.
- CMI's affected set equals the diagnosed `U0` on all 265 instances.
- One label overran its budget: 760.7 s CPU for a 600 s budget, on an S5 instance. Its bound
  is still replayed; the overrun is the same kind the final study reports.

## Findings

**1. Locality is gone as soon as the update grows past one cell.** In this 2 km x 2 km region, a
1 km x 1 km block (S2) is already crossed by almost every route:

| condition | `|U0|/m` | Level 3 = Level 4 (Level 3's release already covers the whole fleet) |
|---|---|---|
| S1 | 34.5% | 0% |
| S2, S4 | 95.8% | 94.3% |
| S3, S5 | 100% | 100% |

- The diagnosed sets of S4 equal those of S2 on every mission, and those of S5 equal S3.
- So S2-S5 test the non-local regime, not an intermediate one. Above S1 the diagnosed scope gives
  almost no reduction: Level 3 is global replanning.

**2. Certification mostly holds.**
- Label certification: 98.1% at S1, 92.5% at S2 and S4, 90.6% at S3 and S5.
- Every unresolved label but one has the bracket [3, no plan]: CMI proved Levels 0-2 infeasible,
  then found no Level-3 plan in 600 s.
- On every one of these, GR or GR-c returned a replayed plan within 10 s. That closes the pooled
  bracket at 3, so pooled certification is 98.1-100% in every condition.
- The certificates (lower bounds) survive weak locality. CMI's own plan search at Level 3 is the
  weak point (finding 4).

**3. Minima move up to global replanning or to no continuation.** Shares of the label's certified
minimum:

| condition | Level 1 | Level 2 | Level 3 | no continuation | Levels 0-2 together |
|---|---|---|---|---|---|
| S1 | 49.1% | 15.1% | 34.0% | 0% | - |
| S2 | 0% | 13.2% | 39.6% | 39.6% | - |
| S3 | 0% | 3.8% | 37.7% | 49.1% | - |
| S5 | 0% | 3.8% | 39.6% | 47.2% | - |
| S4 (graded) | - | - | 54.7% | 17.0% | 20.8% |

- Level 4 is never the certified minimum. Where Level 3 already releases the fleet, a plan gets
  the lower level, 3.
- Paired with S1, the minimum is higher on 73% (S2), 81% (S3) and 79% (S5) of the pairs where
  both labels certified.
- A minimum is lower only under S4, on 2 missions: one from Level 1 to 0 and one from 3 to 2,
  where the weaker neighbouring wind leaves more slack.
- Twelve to thirteen of the 26 missions with an S1 minimum of 1 have no continuation under S2,
  S3 and S5.

**4. CMI's 10 s advantage holds only at S1, and reverses beyond it.** Paired differences, CMI
minus GR:

| condition | at reference minimum | recovery success |
|---|---|---|
| S1 | +75.5 pp [64.2, 86.8] | −20.8 pp [−32.1, −9.4] |
| S2 | −32.1 pp [−50.9, −13.2] | −45.3 pp [−58.5, −32.1] |
| S3 | −39.6 pp [−54.7, −24.5] | −43.4 pp [−56.6, −30.2] |
| S4 | −32.1 pp [−52.8, −11.3] | −52.8 pp [−67.9, −39.6] |
| S5 | −39.6 pp [−52.8, −24.5] | −43.4 pp [−56.6, −30.2] |

- Returned plans on recoverable instances (reference has a plan):

  | condition | CMI | GR |
  |---|---|---|
  | S2 | 7/32 | 31/32 |
  | S3 | 2/27 | 25/27 |
  | S4 | 11/44 | 39/44 |
  | S5 | 1/28 | 24/28 |

- In most CMI failures CMI had already proved Levels 0-2 infeasible within the 10 s. Its lower
  bound was 3 on 39/46 failures at S2, 45/51 at S3 and 45/52 at S5. What failed was its Level-3
  plan search over the whole fleet.
- LR and GR-c also fall behind GR as the support grows.
- Where CMI and GR both return a plan, CMI still changes fewer UAVs (−1.5 to −3.6). This rests on
  only 1-11 pairs per condition.

**5. CPU time grows by an order of magnitude.**

| condition | median CPU to certificate | p90 |
|---|---|---|
| S1 | 2.4 s | 20 s |
| S2 | 21 s | 56 s |
| S3 | 28 s | 149 s |
| S4 | 21 s | 114 s |
| S5 | 21 s | 52 s |

The p90 of label CPU reaches the 600 s budget from S2 on, because of the unresolved instances.

**6. Graded edge (S4).** S4 diagnoses the same `U0` and `V^aff` as S2 on every mission. Its minima
are milder than S2's:
- no continuation: 17.0% against 39.6%;
- Levels 0-2: 20.8% against 13.2%;
- S1 minimum unchanged: 43.8% of pairs against 27.1%.

Its minima are also milder than the hard 3 x 3 box S3 (no continuation 49.1%). The hard box edge
doesn't make updates look milder, so it isn't what produces the small certified scopes. The size
of the minimum follows the wind strength on the cells the routes cross, not the diagnosed
neighbourhood.

## How to read it (against the design's three cases)

The outcome is the design's second case, with a qualification.
- **Holds:** certification stays high at S5 (90.6% from the label alone, 100% pooled) while minima
  move to Level 3, which equals global replanning here, or to no continuation. The formulation
  and its certificates don't depend on locality.
- **Qualification:** the method doesn't "reduce to certified global replanning" in efficiency. It
  proves the lower bound, but its own plan search falls far behind GR at 10 s, and at 600 s it
  misses 7.5-9.4% of instances (S2-S5) that GR solves in 10 s.
- **For the paper:**
  - the small certified scopes and CMI's advantage at FS are properties of local updates;
  - once the update covers most routes, CMI's value is the certificate, not the plan;
  - a practical method should hand the Level-3 plan search to global replanning when Level 3
    equals Level 4. This is not implemented or tested here.

## Limits

- Selection: the missions were admitted because S1 disrupted them with a local `U0`; every
  comparison is paired and conditional on that. Under S4, one mission is no longer disrupted
  (Level 0 is feasible).
- Only strength 3/5, update time 0 and one time bin were run (stationary wind; see the design's
  "Not run").
- The arena was run at 10 s only; the 60 s comparison was not run for S2-S5.
- 53 missions give wide intervals for per-condition shares, about ±13 pp.

---

# Appendix: generated report (`results/support_sensitivity_2026_10_22/analysis/REPORT.md`)

Run `results/support_sensitivity_2026_10_22`, run hash `d5b8f9f0fb451c19`; source `results/final_study_2026_10_17` (read-only). 53 missions x 5 conditions = 265 labelled instances. Labels: CMI, 600 s CPU, one pass. Arena: GR, GR-c, LR, CMI at 10 s. Intervals: 95% percentile bootstrap over missions (2000 resamples, seed 1).

### Integrity

| check | result |
|---|---:|
| S1 payload hash = stored `_r1_t0` hash | 53/53 |
| S1 label bounds = stored FS label bounds | 53/53 |
| labels replayed in-run (audit ok) | 265/265 |
| arena results replayed in-run (audit ok) | 1060/1060 |
| stored records replayed again from proof files | 1325/1325 ok, 0 failed, 0 not replayed |
| CMI affected set = diagnosed U0 | 265/265 |

### Diagnosis

Means per instance. "local": |U0| <= m/2 (the FS admission limit, not re-screened). "L3 = L4": the Level-3 release (U0 plus the helper budget) already covers the fleet. "disrupted": the label proved Level 0 infeasible.

| condition | n | |B_Δ| | |U0| | |U0|/m | |V^aff| | local | L3 = L4 | disrupted |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| S1 | 53 | 1.00 [1.00, 1.00] | 2.06 [1.81, 2.32] | 34.5% [30.9, 38.1] | 4.51 [3.92, 5.11] | 100.0% [100.0, 100.0] | 0.0% [0.0, 0.0] | 100.0% [100.0, 100.0] |
| S2 | 53 | 4.00 [4.00, 4.00] | 5.79 [5.34, 6.25] | 95.8% [92.4, 98.7] | 15.36 [13.87, 16.91] | 3.8% [0.0, 9.4] | 94.3% [86.8, 100.0] | 100.0% [100.0, 100.0] |
| S3 | 53 | 9.00 [9.00, 9.00] | 6.04 [5.62, 6.45] | 100.0% [100.0, 100.0] | 17.74 [16.11, 19.43] | 0.0% [0.0, 0.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] |
| S4 | 53 | 6.34 [5.98, 6.74] | 5.79 [5.34, 6.25] | 95.8% [92.4, 98.7] | 15.36 [13.87, 16.91] | 3.8% [0.0, 9.4] | 94.3% [86.8, 100.0] | 98.1% [94.3, 100.0] |
| S5 | 53 | 15.00 [15.00, 15.00] | 6.04 [5.62, 6.45] | 100.0% [100.0, 100.0] | 17.74 [16.11, 19.43] | 0.0% [0.0, 0.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] |

### Labels

Certified minimum level of the label (share of instances; "none" = no continuation is certified). Unresolved instances are listed with their bracket [lower, upper].

| condition | 0 | 1 | 2 | 3 | 4 | none | unresolved | brackets |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| S1 | 0.0% [0.0, 0.0] | 49.1% [35.8, 62.3] | 15.1% [5.7, 24.5] | 34.0% [20.8, 47.2] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 1.9% [0.0, 5.7] | [1, 3] x1 |
| S2 | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 13.2% [5.7, 22.6] | 39.6% [26.4, 52.8] | 0.0% [0.0, 0.0] | 39.6% [26.4, 52.8] | 7.5% [1.9, 15.1] | [3, no plan] x4 |
| S3 | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 3.8% [0.0, 9.4] | 37.7% [24.5, 50.9] | 0.0% [0.0, 0.0] | 49.1% [35.8, 62.3] | 9.4% [1.9, 18.9] | [3, no plan] x5 |
| S4 | 1.9% [0.0, 5.7] | 5.7% [0.0, 13.2] | 13.2% [5.7, 22.6] | 54.7% [41.5, 67.9] | 0.0% [0.0, 0.0] | 17.0% [7.5, 28.3] | 7.5% [1.9, 15.1] | [2, 3] x1; [3, no plan] x3 |
| S5 | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 3.8% [0.0, 9.4] | 39.6% [26.4, 52.8] | 0.0% [0.0, 0.0] | 47.2% [34.0, 60.4] | 9.4% [1.9, 18.9] | [3, no plan] x5 |

Certification rate and CPU seconds (process time). CPU to certificate is over certified instances; label CPU is the whole run, over all instances.

| condition | certified | CPU to certificate, median | p90 | label CPU, median | p90 |
|---|---:|---:|---:|---:|---:|
| S1 | 98.1% [94.3, 100.0] | 2.38 [1.78, 3.16] | 19.56 [6.05, 32.27] | 2.50 [1.80, 3.17] | 20.30 [7.32, 37.86] |
| S2 | 92.5% [84.9, 98.1] | 21.09 [18.92, 25.86] | 56.23 [40.01, 59.55] | 21.27 [19.81, 29.12] | 61.06 [48.07, 600.06] |
| S3 | 90.6% [81.1, 98.1] | 28.21 [23.69, 47.86] | 149.33 [62.43, 439.51] | 34.00 [23.81, 51.00] | 501.98 [119.69, 600.31] |
| S4 | 92.5% [84.9, 98.1] | 21.36 [16.81, 23.97] | 113.90 [55.45, 232.57] | 22.33 [17.58, 27.17] | 203.97 [63.64, 600.02] |
| S5 | 90.6% [81.1, 98.1] | 21.30 [20.41, 25.03] | 52.18 [29.28, 145.82] | 23.20 [20.81, 25.73] | 378.41 [51.65, 600.23] |

### Pairing with S1

Missions where both labels certified a minimum ("none" counts as above Level 4). "Unpaired": either label unresolved.

| transition | pairs | higher | equal | lower | unpaired |
|---|---:|---:|---:|---:|---:|
| S1 -> S2 | 48 | 72.9% [60.4, 85.4] | 27.1% [16.7, 39.6] | 0.0% [0.0, 0.0] | 5 |
| S1 -> S3 | 47 | 80.9% [68.1, 91.5] | 19.1% [8.5, 31.9] | 0.0% [0.0, 0.0] | 6 |
| S1 -> S4 | 48 | 52.1% [37.5, 66.7] | 43.8% [31.2, 58.3] | 4.2% [0.0, 10.4] | 5 |
| S1 -> S5 | 47 | 78.7% [66.0, 89.4] | 21.3% [10.6, 34.0] | 0.0% [0.0, 0.0] | 6 |

Transition counts (rows S1 minimum, columns the other condition):

S1 -> S2:

| S1 \ S2 | 0 | 1 | 2 | 3 | 4 | none | unresolved |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0 | 0 | 4 | 8 | 0 | 12 | 2 |
| 2 | 0 | 0 | 3 | 3 | 0 | 2 | 0 |
| 3 | 0 | 0 | 0 | 10 | 0 | 6 | 2 |
| unresolved | 0 | 0 | 0 | 0 | 0 | 1 | 0 |

S1 -> S3:

| S1 \ S3 | 0 | 1 | 2 | 3 | 4 | none | unresolved |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0 | 0 | 1 | 8 | 0 | 13 | 4 |
| 2 | 0 | 0 | 1 | 4 | 0 | 3 | 0 |
| 3 | 0 | 0 | 0 | 8 | 0 | 9 | 1 |
| unresolved | 0 | 0 | 0 | 0 | 0 | 1 | 0 |

S1 -> S4:

| S1 \ S4 | 0 | 1 | 2 | 3 | 4 | none | unresolved |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 3 | 2 | 14 | 0 | 6 | 0 |
| 2 | 0 | 0 | 4 | 1 | 0 | 1 | 2 |
| 3 | 0 | 0 | 1 | 14 | 0 | 1 | 2 |
| unresolved | 0 | 0 | 0 | 0 | 0 | 1 | 0 |

S1 -> S5:

| S1 \ S5 | 0 | 1 | 2 | 3 | 4 | none | unresolved |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0 | 0 | 1 | 8 | 0 | 13 | 4 |
| 2 | 0 | 0 | 1 | 4 | 0 | 3 | 0 |
| 3 | 0 | 0 | 0 | 9 | 0 | 8 | 1 |
| unresolved | 0 | 0 | 0 | 0 | 0 | 1 | 0 |

### Arena (10 s)

Each arm is scored on the plan it returned within the budget (replayed), as in the final study. "At reference minimum": the returned plan is at the pooled reference minimum (label bracket closed with every replayed arena plan); denominator all instances. "UAVs changed": mean over returned plans.

| condition | arm | n | plan at reference minimum | recovery success | UAVs changed | certified |
|---|---:|---:|---:|---:|---:|---:|
| S1 | GR | 53 | 0.0% [0.0, 0.0] | 96.2% [90.6, 100.0] | 5.98 [5.55, 6.41] | 0.0% [0.0, 0.0] |
| S1 | GR-c | 53 | 32.1% [18.9, 45.3] | 92.5% [84.9, 98.1] | 2.18 [1.96, 2.43] | 0.0% [0.0, 0.0] |
| S1 | LR | 53 | 75.5% [64.2, 86.8] | 81.1% [69.8, 90.6] | 1.53 [1.37, 1.72] | 0.0% [0.0, 0.0] |
| S1 | CMI | 53 | 75.5% [64.2, 86.8] | 75.5% [64.2, 86.8] | 1.43 [1.25, 1.62] | 75.5% [64.2, 86.8] |
| S2 | GR | 53 | 45.3% [32.1, 58.5] | 58.5% [45.3, 71.7] | 6.00 [5.42, 6.52] | 0.0% [0.0, 0.0] |
| S2 | GR-c | 53 | 43.4% [30.2, 56.6] | 52.8% [39.6, 66.0] | 4.00 [3.39, 4.57] | 0.0% [0.0, 0.0] |
| S2 | LR | 53 | 26.4% [15.1, 37.7] | 28.3% [17.0, 41.5] | 3.53 [2.87, 4.27] | 0.0% [0.0, 0.0] |
| S2 | CMI | 53 | 13.2% [5.7, 22.6] | 13.2% [5.7, 22.6] | 2.14 [1.57, 2.71] | 13.2% [5.7, 22.6] |
| S3 | GR | 53 | 43.4% [30.2, 56.6] | 47.2% [34.0, 60.4] | 5.84 [5.12, 6.48] | 0.0% [0.0, 0.0] |
| S3 | GR-c | 53 | 32.1% [20.8, 45.3] | 35.8% [22.6, 49.1] | 4.84 [4.16, 5.58] | 0.0% [0.0, 0.0] |
| S3 | LR | 53 | 9.4% [1.9, 18.9] | 9.4% [1.9, 18.9] | 4.80 [3.60, 6.00] | 0.0% [0.0, 0.0] |
| S3 | CMI | 53 | 3.8% [0.0, 9.4] | 3.8% [0.0, 9.4] | 2.50 [2.00, 3.00] | 3.8% [0.0, 9.4] |
| S4 | GR | 53 | 52.8% [39.6, 66.0] | 73.6% [62.3, 84.9] | 6.00 [5.49, 6.51] | 0.0% [0.0, 0.0] |
| S4 | GR-c | 53 | 54.7% [39.6, 67.9] | 71.7% [60.4, 83.0] | 3.26 [2.79, 3.76] | 1.9% [0.0, 5.7] |
| S4 | LR | 53 | 45.3% [32.1, 58.5] | 52.8% [39.6, 66.0] | 2.79 [2.25, 3.32] | 1.9% [0.0, 5.7] |
| S4 | CMI | 53 | 20.8% [9.4, 32.1] | 20.8% [9.4, 32.1] | 1.45 [1.09, 1.82] | 20.8% [9.4, 32.1] |
| S5 | GR | 53 | 41.5% [28.3, 54.7] | 45.3% [32.1, 58.5] | 5.92 [5.25, 6.58] | 0.0% [0.0, 0.0] |
| S5 | GR-c | 53 | 32.1% [18.9, 43.4] | 35.8% [24.5, 49.1] | 5.11 [4.37, 5.84] | 0.0% [0.0, 0.0] |
| S5 | LR | 53 | 11.3% [3.8, 20.8] | 11.3% [3.8, 20.8] | 4.17 [2.83, 5.67] | 0.0% [0.0, 0.0] |
| S5 | CMI | 53 | 1.9% [0.0, 5.7] | 1.9% [0.0, 5.7] | 2.00 | 3.8% [0.0, 9.4] |

Paired differences, CMI minus each arm (instances both ran; UAVs changed on instances where both returned a plan, count in the last column):

| condition | difference | n | at reference minimum | recovery success | UAVs changed | pairs with plans |
|---|---:|---:|---:|---:|---:|---:|
| S1 | CMI - GR | 53 | 0.755 [0.642, 0.868] | -0.208 [-0.321, -0.094] | -4.44 [-4.97, -3.92] | 39 |
| S1 | CMI - GR-c | 53 | 0.434 [0.226, 0.642] | -0.170 [-0.283, -0.057] | -0.64 [-0.82, -0.46] | 39 |
| S1 | CMI - LR | 53 | 0.000 [-0.113, 0.113] | -0.057 [-0.170, 0.038] | -0.05 [-0.13, 0.00] | 38 |
| S2 | CMI - GR | 53 | -0.321 [-0.509, -0.132] | -0.453 [-0.585, -0.321] | -3.00 [-4.29, -1.71] | 7 |
| S2 | CMI - GR-c | 53 | -0.302 [-0.472, -0.132] | -0.396 [-0.528, -0.264] | -0.57 [-0.86, -0.14] | 7 |
| S2 | CMI - LR | 53 | -0.132 [-0.245, -0.019] | -0.151 [-0.264, -0.038] | -0.17 [-0.50, 0.00] | 6 |
| S3 | CMI - GR | 53 | -0.396 [-0.547, -0.245] | -0.434 [-0.566, -0.302] | -1.50 [-2.00, -1.00] | 2 |
| S3 | CMI - GR-c | 53 | -0.283 [-0.415, -0.132] | -0.321 [-0.434, -0.208] | -0.50 [-1.00, 0.00] | 2 |
| S3 | CMI - LR | 53 | -0.057 [-0.151, 0.019] | -0.057 [-0.151, 0.019] | 0.00 | 1 |
| S4 | CMI - GR | 53 | -0.321 [-0.528, -0.113] | -0.528 [-0.679, -0.396] | -3.64 [-4.55, -2.73] | 11 |
| S4 | CMI - GR-c | 53 | -0.340 [-0.509, -0.151] | -0.509 [-0.642, -0.377] | -0.45 [-0.73, -0.18] | 11 |
| S4 | CMI - LR | 53 | -0.245 [-0.396, -0.094] | -0.321 [-0.453, -0.189] | -0.10 [-0.30, 0.00] | 10 |
| S5 | CMI - GR | 53 | -0.396 [-0.528, -0.245] | -0.434 [-0.566, -0.302] | -2.00 | 1 |
| S5 | CMI - GR-c | 53 | -0.302 [-0.434, -0.170] | -0.340 [-0.453, -0.226] | -1.00 | 1 |
| S5 | CMI - LR | 53 | -0.094 [-0.189, -0.019] | -0.094 [-0.189, -0.019] | 0.00 | 1 |

