# Certification method v2: what is implemented

Date: 14 October 2026. Code: `src/certify_v2/`. Plan: `docs/CERTIFICATION_METHOD_PLAN_2026_10_09.md`
with the 10 October amendments (`ROOT_CAUSE_AND_REDESIGN_PLAN_2026_10_10.md`, Section 7). The v1
modules and every frozen result are unchanged; v2 is a separate method.

## Summary

Each level asks one question: can the choices this level releases be re-made so that every
delivery meets its deadline and every battery, payload and stock limit holds? The answer is a
plan accepted by the exact checker, or a proof that none exists, which an independent replay
re-checks without optimizers.

| Part | Module | What it does |
|---|---|---|
| Flight-time table | `table.py` | Interval [lower, upper] of the fastest flight time per leg and airspeed. Lower: linear potential (any wind), closed form under uniform wind, verified per-pair potential at refinement 2, 4, 8, 16 when a decision needs it. Upper: exact time of the chord, then detours, interface probes and conic-optimized paths. |
| Route check | `route.py`, `oracle.py` | Can one UAV serve a task set from its current state? First-visit search with Pareto (time, energy budget) states, depot stops (preparation, recharge, reload) and the slot bound. With lower bounds: a proof for the set and every superset. With achieved times: a visiting order. |
| One-UAV rows | `uav.py` | Exactly the rows `recovery/transfers.py` builds for one UAV (tested row by row), plus its tasks' service rows and its own stock row. Farkas proofs on them exclude a stop sequence whatever the other UAVs do. |
| Stop-sequence search | `skeleton.py` | Complete search over one UAV's stop sequences (repeats and depot stops included) with two dominance reductions, prefix bounds and Farkas leaves. Used when the route check admits a set but no plan is found (energy, payload, splits). Tested against full enumeration. |
| Levels | `levels.py` | Level 0: exact check of the incumbent / fixed-route proof. Level 1: better paths for U0 legs / fixed-route proof with released legs at their lower bounds. Level 2: route check of each U0 UAV's own tasks. Levels 3-4: assignment search over released tasks (most constrained first, current owner first), cut by the route check, helpers interleaved round-robin. |
| Ladder | `ladder.py` | CMI: Level 0, then rounds over open levels. The lowest open level runs its full search (proofs and plans) for the slice. Every open level from Level 2 up, the lowest included, also runs a plan-only search for a quarter of the slice, so plans appear early. A level's search accepts only plans inside its own patches. A plan's level is always scored against the true U0, which matters for the noAF ablation (masks built from the whole fleet). PH: the plan-only searches, Levels 0-4 in order with fixed CPU shares. |
| Baselines | `baselines.py` | GR (regret insertion from scratch + local search), GR-c (local search from the incumbent minimizing changes), LR (greedy repair of late deliveries). |
| Replay | `replay.py` | Re-checks every certificate, route proof, stop-sequence tree, assignment tree, Farkas combination and plan, and recomputes the bracket. |
| Metrics | `metrics.py` | Decisions changed: UAVs, outside U0, reassigned tasks, sequence edits (predecessor changes), re-routed and new legs, deliveries, depot stops. |

## Proof kinds

| Kind | Claim | Replay |
|---|---|---|
| `linear_potential_v2` | flight time from a to b is at least g.(b - a) | the gradient satisfies w.g + v abs(g) <= 1 in every cell |
| `continuous_potential_v1` | per-pair potential bound (existing) | `continuous/potential.verify_potential` |
| `route_timing_v2` | no route of UAV u serves task set R | rebuild the route check from the scenario and the cited tick matrix; every entry at most its certified bound |
| `skeleton_tree_v2` | no stop sequence of u serves R | re-enumerate children, recheck prefix bounds, re-multiply Farkas leaves |
| `fixed_route_lower_v2` | Level 0 or 1: a UAV's fixed sequence fails | one-UAV rows with path lower ends and certified leg bounds; Farkas or ground rejection |
| `level2_route_v2` | Level 2: an affected UAV cannot serve its own tasks | cites a route or stop-sequence proof for a subset |
| `assignment_tree_v2` | Level 3 patch or Level 4: every owner choice is closed | every node closed by a cited proof for a subset of an owner's set, or branched over every participant |
| plans | exact feasibility | `level2/quantities.verify_quantity_witness` on the recorded patch, and the level recomputed from the original masks |

Lower bounds enter proofs on a 1e-12 h grid, rounded down; deadlines, horizon and budgets are
rounded up. A proof therefore stays valid when its leg's certificate is later replaced by a
stronger one.

## Soundness conditions

As in plan Section 3: stationary wind (lower bounds need it); energy grows with flight time;
no waiting; no earliest times; no depot-bay limit (`continuous/physics.stationary_guard`
enforces the last two cases it cannot handle). Proofs drop constraints only: payload mass in
the energy bound, service at repeat visits, the ground time of stops inside a gap, stock
coupling between UAVs.

## Differences from the plan

- **Shared potential fields** (plan 5.1, tier 2) are not implemented. The cheap tier is a
  linear potential per pair (any wind, exact rational check); per-pair fields at refinement 2,
  4, 8, 16 are computed lazily, only for legs on the optimistic route of an undecided check.
  A per-pair field costs 0.05-0.2 s at refinement 2-4.
- **Workload bound** (plan 5.3, optional) is not implemented; it was not needed in the pilot.
- **Slot-search fallback** is the new per-UAV stop-sequence search (`skeleton.py`) rather than
  `level2/skeletons.py`, because UAVs are independent once the assignment is fixed (stock is
  relaxed in proofs and checked exactly in plans).
- **Energy and reloads in the route check.** The 9 October route check covered timing and a
  reload count; v2 also carries the energy budget per sortie (empty-mass rate, recharge at
  depot stops, reserve returns), which closes most battery-driven Level-2 cases without the
  stop-sequence search.
- **Budgets** are CPU time (`process_time`), checked between units of work, as the comparison
  protocol requires.

## Checks done

- Route check: never rejects a feasible explicit route (400 random instances with arbitrary
  times, energy, reloads and slots) and is exact for metric times without stops (300 instances).
- One-UAV rows equal the full compiler's rows for that UAV (randomized plans on 12 P1 missions).
- Stop-sequence search agrees with enumeration of every sequence (40 random cases).
- Agreement with v1 on a stratified sample of 113 v1-certified P1 variants (25 each at Levels
  0, 1, 3 and no continuation, all 12 at Level 4, the single Level 2): 113 agree, all replay.
  Of 40 sampled v1-unresolved variants, v2 certifies 38 within 30 s.
- Every run in the tests and the pilot is replayed by `replay.verify_run`; tampered brackets
  and tampered proof matrices are rejected.
- Final-study pilot (`docs/FINAL_STUDY_PILOT_2026_10_14.md`, 162 FS variants, 22 LS
  instances, 40 P1 variants):
  - 1,944 of 1,944 arena results and 367 of 367 labels replay;
  - no cross-check violation;
  - no disagreement with a v1 certificate.
