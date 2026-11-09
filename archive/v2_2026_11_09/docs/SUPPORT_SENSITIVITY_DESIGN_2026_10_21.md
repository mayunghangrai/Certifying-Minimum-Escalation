# Sensitivity of the results to the size of the wind update

Date: 21 October 2026. Status: **design only, not implemented.** Nothing under `src`,
`configs` or `results` has changed.

## Why

The formulation assumes a local update: the received wind table differs from the previous one
only on a declared support `B_Δ` (`system_model.tex`, eq. `local_wind_update`). The final study
uses the smallest form of this assumption:

- one 0.5 km x 0.5 km cell out of 16;
- one constant vector in that cell, zero change everywhere else;
- the update cell placed on a leg into a task;
- draws that affect more than m/2 UAVs rejected as `not_local`. That was 50% of FS
  rejections (`FINAL_STUDY_RESULTS_2026_10_18.md`).

A reviewer can argue that the small certified scopes come from assuming small disturbances.
This test asks one question: **on the same missions, how do the diagnosed neighbourhood, the
certified minimum level, certifiability and run time change when the update grows from one
cell to almost the whole region, or has a graded edge instead of a hard box?**

The formulation never needs `B_Δ` to be small. It only needs `B_Δ ⊊ R x J`. The test checks
whether the method still certifies when locality is weak, and how much of the benefit of a
small scope remains.

## Design

**Missions.** Use the 53 FS missions in the seeded random third already used for the 60 s
arena (`fs_long_missions`, `third_seed` 76002). That set was fixed before this question came
up, so the missions aren't chosen after the fact. It covers all fleet sizes, task densities,
slacks and battery margins.

**Base variant.** Use each mission's stored reference variant `_r1_t0` (strength 3/5,
update time 0). Generation admitted the mission on this variant. The geometry, incumbent,
deadlines, battery, stock and previous (calm) wind stay as stored. Only the received wind
table and `update_support` change. The direction `d` and strength `r = 3/5 · v_min` are the
mission's own.

**Conditions.** Let the seed cell be the stored update cell, with grid index `(x, y)` on the
4 x 4 grid. The rules below use only grid positions, never the plan:

| Code | Support | Received wind |
|---|---|---|
| S1 | the seed cell (as in FS) | `r·d` |
| S2 | 2 x 2 block containing the seed cell, extended toward the grid centre (x-range `x, x+1` if `x <= 1`, else `x-1, x`; same for y) | `r·d` on all 4 cells |
| S3 | 3 x 3 block, `x`-range starting at `clamp(x-1, 0, 1)` (same for y), so it always has 9 cells and contains the seed | `r·d` on all 9 cells |
| S4 | graded bump: the seed cell and its Chebyshev neighbours (4-9 cells, depending on the edge) | `r·d` on the seed cell, `r·d/2` on the neighbours |
| S5 | the whole grid except one cell: the corner farthest from the seed cell's centre (ties broken by cell id) | `r·d` on 15 cells |

- S1 to S3 and S5 vary the size of a uniform change.
- S4 against S1 and S3 tests whether the hard box edge matters.
- S5 approximates a region-wide forecast shift. A mean-wind change is the most common real
  update.
- All values are terminating decimals within the stored bound of 0.8 km/h. For example,
  `3/10 · (3/5, 4/5) = (0.18, 0.24)`.

**Not run:**
- A full 16-cell update. `env/scenario.py:120` enforces `B_Δ ⊊ R x J` and rejects a support
  that covers every cell-time entry. Adding a time bin doesn't help, because the certified
  solver accepts only stationary wind (`continuous/physics.py:25`). See Decision 1.
- Time-local updates, for the same stationarity reason. This is a limitation to state in the
  paper, not something this test can show.
- Strengths other than 3/5, and update times after 0. The snapshot builder writes the update
  into one cell only.

**No admission screen.** No condition is re-screened for disruption or for `|U0| <= m/2`.
Both are reported as outcomes. Note the selection: these missions were admitted because S1
disrupted them with a local `U0`. The comparison is paired and conditional on that.

**Size.** 53 missions x 5 conditions = 265 instances. S1 is re-labelled, not reused, for
three reasons:
- CPU times then come from the same run;
- it gives an integrity check: the S1 label must agree with the stored FS label of `_r1_t0`;
- the S1 payload hash must equal the stored variant's hash.

## Runs

1. **Labels.** CMI at the FS reference budget (600 s CPU, one pass), replayed independently,
   with proofs stored, exactly as `fs-label`. Worst case 265 x 600 s / 6 workers = 7.4 h.
   FS labels took 44 min for 1,440 instances, so expect under an hour, although larger
   supports may be slower.
2. **Arena (secondary).** CMI, LR, GR-c and GR at 10 s, as in `fs-arena-short`. That's about
   265 x 4 x 10 s / 6 = 30 min. It shows whether CMI's lead over global replanning shrinks as
   the update grows. The labels alone can't show that.

## What is reported

Per condition, with 95% intervals from a bootstrap over missions:

**Diagnosis**
- update cells `|B_Δ|`;
- affected UAVs `|U0|` and their share of the fleet;
- affected tasks `|V^aff|`;
- share of instances where Level 3's release already covers the whole fleet (Level 3 equals
  Level 4);
- share still disrupted (Level 0 certified infeasible). A larger field also contains
  tailwinds, so it can help as well as hurt.

**Labels**
- distribution of the certified minimum (0-4, no continuation, unresolved with bracket);
- certification rate;
- CPU to certificate, median and p90.

**Pairing**
- a transition table of the S1 minimum against each other condition: share higher, equal,
  lower.

**Arena**
- per arm: plan at the reference minimum, recovery success, and UAVs changed per returned
  plan;
- the CMI-minus-GR differences against condition.

## How to read it

Every outcome supports a defensible statement, so nothing here is a pass/fail threshold:

- **Minima and the CMI advantage roughly stable from S1 to S4.** The results don't depend on
  the single-cell box; neighbourhood-sized and graded updates behave alike.
- **Certification stays high at S5 while minima move to Levels 3-4 or no continuation.** The
  method doesn't assume locality: it uses locality when present and reduces to certified
  global replanning when absent.
- **Certification falls sharply at S5.** This is a real limit. Report it as a scope condition
  of the method, not of the formulation.

The S4 versus S3 contrast answers the "unphysical box edge" objection directly.

## Decisions before implementation

1. **Largest condition.** (a) S5 with 15 of 16 cells, needing no change to core code. This is
   recommended, because it keeps the frozen solver untouched. (b) Relax `scenario.py:120` to
   allow a full support and write `⊆` in the formulation. Before (b), check that nothing in
   `diagnose_wind_update` or `certify_v2` relies on an unchanged cell existing.
2. **Arena.** Run the secondary 10 s arena (recommended, about 30 min), or labels only.
3. **Mission set.** The existing 53-mission third (recommended), or all 160 missions. With all
   160 the worst case is about 22 h.

## Implementation outline (after approval)

- `src/final_study/support_sensitivity.py`: build S1-S5 from a stored `_r1_t0` payload and its
  ledger (`cell_index`, `direction`).
- `scripts/run_support_sensitivity.py`: read missions from `results/final_study_2026_10_17`
  read-only, write to a new `results/support_sensitivity_2026_10_xx/` through `Store`, reuse
  `label` and `run_instance`, and resume like the final study.
- Tests:
  - each payload differs from its source only in received wind values and `update_support`;
  - support sizes are as specified;
  - the S1 payload equals the stored variant;
  - all values are within the bound;
  - the previous premise is unchanged;
  - the rules never read the incumbent's legs.
- Run order: smoke run on 3 missions, then the full 53, then the report.
