# Coding plan for the final experiment design (method v3, larger realistic missions)

Date: 4 November 2026, updated 5 November 2026. Design: *Final experiment design: certified
minimum repair on larger, realistic missions* (4 November 2026, proposal for approval, with
the updated Section 4.3 incumbent). Status: **plan only; no code has been changed.** Every
statement about the current code below was checked by reading it.

## 0. Summary

- **Reused.** These parts already support most of what the design needs:
  - the float evaluator and the affected-fleet (U0) diagnosis, which already handle time bins;
  - the transfer compiler, which already passes the departure time to its duration provider;
  - the scope masks, the ladder, the run harness and the analysis helpers (bootstrap over
    missions, interval-censored ordinal regression).
- **Missing.** The exact interval checker, every v2 lower bound, the route check, the
  snapshot builder and both generators assume one stationary wind. The schema hard-codes km
  and h, and it has no affine power model. There is no independent verifier, no exhaustive
  ground truth, no band bisection and no Linux server harness.
- **Architecture.** Following the v1 to v2 precedent, v2 and every frozen module stay
  unchanged. Four new packages:
  - `certify_v3/` (method);
  - `study_v3/` (MS, LS, SC, CA, harness and report);
  - `verify/` (independent verifier and exhaustive search);
  - `continuous/binned.py` (exact binned checker).

  There is also a new schema `wind-benchmark-v3` (SI). About ten shared modules get a small
  dispatch on `schema_version`, through one new accessor module. The existing tests and a
  replay of archived records guard them.
- **Plan rules (adopted 5 November).** Rule 1: each task is served in one visit, all of its
  demand is mandatory, and every demand fits in one load. Rule 2: a UAV leaves each stop as
  soon as service or preparation ends (no ground waiting), and never makes two depot stops
  in a row. These two rules replace the earlier 2k + 3 stop limit: a UAV with a tasks makes
  at most 2a + 1 stops, the plan space is finite without an imposed slot cap, and plans
  carry no holds (D-5). Paper sentence: "UAVs do not
  wait on the ground; each task is served in a single visit."
- **Two changes to the design's build order:**
  - the exact binned checker must come first, because the generator needs binned times;
  - the admission rule ("Level 0 certified infeasible") and the label part of the rescaling
    test need method v3, so they move from Gate A to Gate B.
- **Open questions.** Section 6 lists them. Decided on 5 November: Q1 (front updates
  removed; magnitude only), Q2 (incumbent of design 4.3), Q3
  (C = R(1 + beta)/0.9), Q4 (plan rules; 0.5 kg packages, capacity 5), Q7 (no holds) and Q14
  (no v2 reduction check), Q17 (incumbent search details), Q6 (route-proof table, option c),
  Q12 (P(m) = 145.5 m - 368 W) and Q13 (label checks at Gate B). Nothing blocks code.

## 1. What the code does today

| Area | Module(s) | State relative to v3 |
|---|---|---|
| Scenario schema | `schemas/wind-benchmark-v2.schema.json`, `env/scenario.py` | `units` are `const` km, h, kg, Wh. Field names carry units (`airspeed_kmh`, `deadline_h`, `time_knots_h`, ...). Energy uses `energy_coefficient_wh_per_kg_km`. `_validate` already accepts several time bins (`time_knots_h` must partition [epoch, horizon]). |
| Float evaluator and U0 | `env/route_evaluator.py`, `env/wind.py`, `env/fixed_plan.py`, `env/wind_dependency.py`, `env/local_scope.affected_uavs` | Already time-binned: legs are split at bin knots, and changed atoms are (cell, bin) entries. Reusable once units go through an accessor. |
| Exact flight times | `continuous/physics.py` (`stationary_duration`, `stationary_guard`, `stationary_wind_guard`) | Stationary only. `stationary_wind_guard` returns `'time-dependent wind'` for any second bin. The guard is called from 24 modules. `recovery/physics.flight_duration(exact=True)` does split at bins, but it needs rational square roots, so it is unusable for arbitrary angles. |
| Exact plan check | `continuous/validation.certify_witness`, `level2/quantities.verify_quantity_witness` (`_provider` caches `stationary_duration` per path) | Stationary guard. The cache key ignores the departure time. |
| Transfer rows | `recovery/transfers.build_transfer_problem` | `duration_provider(uid, path, time)` is already departure-aware. `departure = delivery_time + preparation` (no holds, which matches Rule 2). Energy is hard-coded as `(m0 + mass*load) * gamma * v * dt`. |
| Lower bounds | `certify_v2/table.py`, `continuous/potential.py` | The linear potential and the per-pair fields are checked against `values[cell][0]` only. Entries are keyed `(airspeed, a, b)`, with no departure window. |
| Route check | `certify_v2/route.py`, `oracle.py` | Forward first-visit search with Pareto (time, energy) labels over a **constant** tick matrix and its closure. The energy rate is the empty-mass rate (payload dropped). The design mentions a latest-departure recursion of 9 October; it is in the 9 October plan only, not in the code. |
| Per-UAV rows, stop sequences | `certify_v2/uav.py`, `skeleton.py` | One constant duration per leg. The rows themselves keep the payload mass (exact). Only the route check drops it. |
| Levels, ladder, replay | `certify_v2/levels.py`, `ladder.py`, `replay.py` | `exact()` uses `table.exact_duration` (stationary). The replay re-checks potentials with `verify_potential` (stationary). |
| Baselines | `certify_v2/baselines.py` (`Routes` built on `Instance.context(4)`) | They use the stationary table. |
| Snapshots (in flight) | `escalation_study/snapshots.py` | Assumes a calm F0. Durations come from `stationary_duration`. The wind is rewritten to one bin `[t, horizon]` with one changed cell. D1 and D1' are both supported, and D3 (move to the end of a ground operation) is implemented. |
| Generators | `final_study/generator.py`, `levelsuite.py`, `level4.py`, `escalation_study/missions.py`, `final_benchmark/generators.random_pair` | 2 km region with a 4 x 4 grid. Round-robin assignment with nearest-neighbour order (`make_plan`). Calm F0, horizon 1000 h. The update is one cell (or the 2 x 2 deficit block), set in bin 0 only. Deadlines use urgency classes. |
| Harness | `final_study/stages.py`, `store.py`, `certify_v2/accounting.Clock` | `ProcessPoolExecutor` with `spawn`, workers reused, gzip records, manifest with source hash, resume, `failures/` directory, CPU budgets via `process_time`. No memory limit, no queues, no ordering. |
| Analysis | `final_study/analysis.py` | `bootstrap(...)` over a cluster key, `ordinal_regression(...)` (interval-censored, mission-clustered sandwich), five-metric tables, anytime curves. Reusable as functions. |
| Earlier ground-truth and tamper work | `scripts/run_planted.py` (B2), `scripts/run_mutation.py` (B3) | Patterns for the tamper tests of Section 5.7. Both go through `certify_v2` code, so neither is independent in the design's sense. |

Environment notes:

- `environment.yml` pins Python 3.10, but the manifests and the design use 3.13.3.
- `code/` is a git repository, but its last commit is from 7 October. `certify_v2/`, the
  final-study pipeline and its configurations are untracked (199 untracked, 339 deleted
  and 6 modified entries).

## 2. Architecture decisions (recommended)

- **D-1. v2 stays frozen; v3 is a new package.**
  - `src/certify_v3/` starts as a copy of `certify_v2/` and changes `table`, `route`,
    `oracle`, `uav`, `skeleton`, `levels`, `ladder` (import only), `replay` and `baselines`.
  - It imports `accounting` and `metrics` from v2 unchanged, and adds `metrics_v3`.
  - Reason: every frozen record must keep replaying under v2. v3 is a new design, so it is
    not checked against v2 (Q14), and `certify_v3` only needs to read v3 scenarios.
- **D-2. Schema v3 in SI, read through one accessor.**
  - New `schemas/wind-benchmark-v3.schema.json`, with SI field names (Section 3, A0.1).
  - New `src/env/units.py`, which returns exact Fractions for airspeed, power(m), energy(m,
    dt), epoch, horizon, deadlines, knots, service, preparation and wind values, for both v2
    and v3 scenarios. (The shared `env` modules still read v2 scenarios.)
  - Only modules on the v3 path call it. v2 values come out numerically identical, so v2
    behaviour is unchanged.
  - Why SI in the file and not only at input/output: times such as 60 s are 1/60 h, which
    is not a terminating decimal. JSON floats in hours could therefore not keep the
    deadlines exact.
- **D-3. One new study package, `src/study_v3/`.** It holds MS, LS, SC, CA, bands, harness
  and report. It reuses the `final_study.store` and `stages` patterns. `final_study/` stays
  unchanged, so the archived runs still open with `bind=False`.
- **D-4. `src/verify/` imports only the standard library.** That rules out every package
  under `src/`, not just the six the design lists: `recovery` and `certify_v3` are solver
  code too. A test enforces it.
- **D-5. No holds (Rule 2).** A UAV departs each stop exactly when service or preparation
  ends, so every departure time follows from the plan and the wind. The exact checker
  flies each plan from its actual departures. On a fixed path the wind satisfies FIFO
  (abs(w) < v), so arriving earlier never hurts and waiting is never needed. A window
  upper arrival computed at the window's latest departure is therefore valid for any
  earlier departure (Section 5.2 of the design). Plans have no floor or hold field.
- **D-6. Slot bound derived, not imposed (Rule 1 and Rule 2; replaces the 2k + 3 stop
  limit).** The `slot_bound` field and
  the fixed-length plan arrays stay, because `validate_plan`, `UavModel.slots`,
  `RouteInput.slots` and `skeleton.children` use them. For v3 it is set to 2a + 1, where a
  is the number of tasks the UAV could hold (all remaining tasks at Level 4), so it never
  binds. Plans are not checked against the two rules by the verifier (decided 5 November);
  see Section 7.

## 3. Work packages and where the code changes

Each work package lists new (N) and modified (M) files, what it does, and the test that
closes it.

### Phase A0: physics core (moved ahead of the generator)

| WP | Files | Content | Done when |
|---|---|---|---|
| A0.1 | N `schemas/wind-benchmark-v3.schema.json` | v3 copy of the v2 schema:<br>- units `m, s, kg, Wh`;<br>- vehicles `airspeed_mps`, `empty_mass_kg`, `power_a_w`, `power_b_w_per_kg`, `battery_capacity_wh`, `reserve_wh`, `payload_capacity` (in packages, 5), `slot_bound` (D-6);<br>- `epoch_s`, `horizon_s`, `deadline_s`, `service_duration_s`, `preparation_duration_s`, residual `duration_s`;<br>- wind `time_knots_s`, `speed_bound_mps`, values in m/s;<br>- tasks carry only mandatory demand, an integer number of 0.5 kg packages (no optional part, Rule 1); `package_mass_kg` = 0.5. | The schema validates hand-written v3 fixtures. |
| A0.2 | N `env/units.py` | The accessors of D-2. `energy_wh(vehicle, mass_kg, dt)` returns `(a + b*m)*dt/3600` for v3, and `gamma*v*m*dt` with dt in hours for v2. | Unit tests: v2 values equal the current inline formulas exactly. |
| A0.3 | M `env/scenario.py`, `env/plan.py` | Add a third validator for v3, with the same rules in SI. The wind bound is checked exactly. Each task's demand must not exceed the payload capacity of some UAV (Rule 1). | The full existing suite passes unchanged (606+ tests); the v3 fixtures validate. |
| A0.4 | M `env/energy.py`, `env/route_evaluator.py`, `env/wind.py`, `env/fixed_plan.py`, `env/wind_dependency.py` | Read through the accessor. For v3, `wind_dependency` gets SI tolerances (1e-6 s and the matching values). | U0 on v3 fixtures equals a hand computation; the v2 suite is unchanged. |
| A0.5 | M `recovery/transfers.py` | Energy through the accessor. Departure stays `ready` time (Rule 2). | Row-by-row equality on v2 fixtures; one v3 fixture checked by hand. |
| A0.6 | N `continuous/binned.py` | - `binned_guard`: complete coverage, all cells admissible, abs(w) < v in every cell and bin (the FIFO condition), no depot bays, idle-depot or airborne origins.<br>- `split_binned`: split at cell **and** bin boundaries.<br>- `binned_duration(scenario, uid, path, departure)` returns [lo, hi]. It runs two rational passes, one with the lower and one with the upper ground-speed enclosures. Arrival is monotone in progress along a fixed path, so each pass bounds one side.<br>- `position_at(path, departure, t)` returns an interval, for the snapshots. | - On every one-bin fixture, `binned_duration == stationary_duration` (a checker test, not a v2 comparison).<br>- Two-bin analytic control (design 5.6): a straight leg in uniform wind that changes at a knot, for all 12 directions and 4 strengths; the enclosure contains the closed form. |
| A0.7 | M `continuous/validation.py`, `level2/quantities.py` | Dispatch the guard by schema version. The `_provider` cache key becomes `(uid, path, departure)`, and v3 uses `binned_duration`. | `verify_quantity_witness` accepts a binned witness and rejects a tampered one. |

### Phase A: generator and setting (`src/study_v3/`, `configs/study_v3/`)

| WP | Files | Content |
|---|---|---|
| A1 | N `configs/study_v3/physics.json` | Matrice 350 RTK values (6.5 kg airframe, 2.7 kg rated payload, of which 5 packages = 2.5 kg are used, airspeeds 10, 12.5 and 15 m/s), the Dorling et al. coefficients per airspeed with their source and fit error, the package mass (0.5 kg) and capacity (5 packages), beta, the reserve rule (Q3) and the bin width of 900 s. Blocked by Q12. |
| A2 | N `study_v3/wind_model.py` | F0: prevailing direction from the 12 rational vectors, speed in {0, ..., 4} m/s, a factor in {1/2, 3/4, 1, 5/4} and an optional turn to a neighbouring direction for each cell and bin, drawn once per mission. abs(w) <= 0.8 v_min. Bins of 900 s up to the horizon (Q5). F0 has no front (Q1). |
| A3 | N `study_v3/geometry.py` | `random_pair` scaled to a 10,000 m x 10,000 m region with 8 x 8 cells of 1,250 m. Demands of 1 to 5 packages of 0.5 kg (0.5 to 2.5 kg), all mandatory and each within one load of 5 packages (Rule 1, Q4). Stock as in `random_pair`. Airspeeds cycled over the fleet. |
| A4 | N `study_v3/incumbent.py` | The incumbent of design 4.3:<br>- **Construction:** regret-2 insertion (Potvin and Rousseau 1993), exactly k tasks per UAV, at most 5 packages (2.5 kg) per sortie, depot reload stops with 240 s preparation, straight legs. Plans obey Rules 1 and 2 by construction.<br>- **Regret ties (Q17):** a task that only one UAV can still take has infinite regret and is placed first; among several such tasks, and among equal regrets, the lowest task number wins.<br>- **Local search:** relocate, 2-opt, swap between UAVs and move-depot-stop. Best improvement: every move is scanned in the fixed order relocate, 2-opt, swap, depot move, each by UAV number and then task number; among equally good moves the first met wins. A move is kept if it lowers the makespan by more than 1e-6 s, or changes it by at most 1e-6 s and lowers total flight time by more than 1e-6 s. At most 2,000 iterations.<br>- **Times (Q17):** during the search, the same leg-through-cells-and-bins calculation as `binned_duration`, in ordinary floats, using only + - * / and square root in a fixed order (the 12 rational wind directions need no trigonometry), so Linux and Windows give bit-identical results. Payload is counted in whole packages and stays exact.<br>- **Afterwards:** one exact `binned_duration` pass over the final plan. Each u_i is an interval; deadlines `u_i + kappa_i * 125 s` use its upper end, and batteries use the upper energy (A5). Float times can only make the plan less efficient, never invalid, because deadlines and batteries come from these exact values. The planner does not see deadlines (Q2).<br>- No OR-Tools.<br>Test: every plan validates, obeys both rules, and a fixed seed gives the same plan twice (also across Linux and Windows). |
| A5 | in `study_v3/missions.py` | Deadlines `d_i = u_i + kappa_i * C` with C = 125 s, where u_i is the upper end of the exact delivery-time interval (A4). kappa_i is drawn log-uniform in each slack level's range and rounded to a rational grid (1e-3 cell crossing). The 60 s guard stays. Battery capacity C_u = R x (1 + beta) / 0.9 (written C in the agreed rule; renamed here because C is also the 125 s crossing), with R the UAV's energy requirement under F0 (upper end of its exact interval), so the reserve is 10% of C_u and the usable 90% equals R x (1 + beta) (Q3). Previous premise: `certify_witness` under F0 (v3). |
| A6 | N `study_v3/update.py` | One update kind, magnitude (front onset and passage removed; Q1, decided 5 November). The block's wind takes strength r and a new direction. F0 is the same in every r variant, so the incumbent and deadlines are shared and the variants stay paired along r. Blocks of 1, 4 or 9 cells over a run of bins. A Latin schedule balances block size over the 81 design cells. Placement: on an incumbent leg into a delivery that starts after tau/2, so that all three update times share the block. Records how many legs change bin. |
| A7 | N `study_v3/snapshots.py` | Binned rewrite of `escalation_study/snapshots.py`:<br>- the timeline uses `binned_duration` under F0;<br>- airborne positions come from `position_at`, rounded to a 1e-6 m grid;<br>- batteries are rounded down;<br>- D1' only, plus D2 and D3;<br>- the knots are cut at t_u, F1 applies from t_u on, and the previous premise is re-certified. |
| A8 | N `study_v3/missions.py` | MS generator: 81 cells x 4 missions (2 uniform, 2 clustered) = 324 missions, 9 variants each = 2,916 variants. Up to 48 draws per slot with new geometry every 12, rising in steps to 192, with every draw logged and the slack ranges never changed. Admission: premise, 1 <= abs(U0) <= ceil(m/3), and disrupted at r = 0.6, t_u = 0. Decided 5 November: Level 0 changes nothing, so the exact checker alone decides (no method needed): conservative pass accepts -> reject; optimistic pass finds a certain violation -> admit; an interval straddling a limit -> reject and log (`study_v3/admission.py`). The nine variants share one block. SC generator: the 8 size cells of design Section 9, medium slack and battery, r = 0.6, t_u in {0, 1/2}; within each size cell the 15 missions get 5 blocks each of 1, 4 and 9 cells by mission index. Uneven fleets (64 tasks on 12 UAVs) give the first n mod m UAVs one extra task. |

**Gate A (Q13, decided 5 November)** tests only what the generator produces:

- payload conservation;
- the admission rule (A8, on the exact checker);
- the incumbent's feasibility under F0;
- determinism from the seed;
- rescaling: a rescaled scenario is the same mission in other units (same U0, incumbent
  order, premise outcome and float-evaluator ratios), on 200 missions.

The label rescaling check moves to Gate B. The "v3 equal to v2 on one-bin scenarios" check is dropped (Q14, confirmed 5 November).

### Phase B: method v3 (`src/certify_v3/`)

| WP | Files | Content |
|---|---|---|
| B1 | N `certify_v3/table.py`, `certify_v3/potential.py` | - **Envelope bound:** the linear potential's `worst` is taken over every bin's wind in every cell. The per-pair fields get one SOC row per (triangle, distinct wind of that cell over all bins). The proof kind is `envelope_potential_v3`.<br>- **Window bound:** only the bins overlapping `[t1, t2 + U]`, where U is an exact upper time (`window_potential_v3`).<br>- Entries are keyed `(airspeed, a, b, window)`. Windows start at one per bin and are halved on legs of a failing optimistic route.<br>- Upper bounds: the path's exact arrival at the window's latest departure t2 bounds the arrival for any earlier departure (FIFO, D-5). The energy upper bound uses that arrival minus t1 as the duration.<br>- `alpha(t) = min over t' >= t of (t' + l(t'))`, in ticks.<br>`continuous/potential.py` stays unchanged. |
| B2 | N `certify_v3/route.py` | Forward first-visit search.<br>- The gap from x to q gets arrival bound `min(alpha_xq(t), t + closure_env[x][q])`. The closure runs over the envelope bounds only, which are valid for any departure time, so multi-hop gaps stay sound.<br>- Labels carry (time, energy, load). Energy is charged with the departure-independent envelope bound at rate a + b(m0 + a lower bound on payload); alpha is used only for times (B10). This keeps (time <=, energy >=) dominance sound under time-dependent wind.<br>- The achievable mode uses the window upper bounds.<br>- **Size:** exact up to about 12 tasks per UAV (Rule 1 and Rule 2 bound the stops at 2a + 1). Above that, a weaker relaxation (for example the energy and time bound of the closure without ordering) proves what it can; instances it cannot decide are reported in the unresolved rate. |
| B3 | N `certify_v3/oracle.py`, `uav.py`, `skeleton.py` | - Leg durations become a function of the departure time. Proofs compute legs sequentially as alpha(departure) (no waiting is optimal by FIFO, design 5.1, and Rule 2 forbids it).<br>- `uav_problem` takes per-leg times; plans use `binned_duration` at the actual departure.<br>- `Frame.walk` and the leaf Farkas proofs use the alpha chain. |
| B4 | N `certify_v3/levels.py`, `ladder.py` | Levels 0 and 1 use binned fixed-route checks. `exact()` uses the binned provider. The ladder is v2's, with the v3 `Instance`. `run_cmi`, `run_ph` and the noAF and noER switches are kept. `fifo_condition_v3` is recorded once per run. |
| B5 | N `certify_v3/replay.py` | Replays `envelope_potential_v3`, `window_potential_v3`, `route_timing_tv_v3` and `fifo_condition_v3`. Each run exports its decisive legs with their [lower, upper] intervals, because the LS band rule (C2) needs them. |
| B6 | N `certify_v3/baselines.py`, `metrics_v3.py` | GR, GR-c and LR on `Routes.time(uid, a, b, departure)`. Metrics add finish time, total energy, the tightest deadline margin, the time available (update to the first affected UAV entering changed wind), and the dimensionless ratios of design 3.3. |
| B7 | N `tests/test_v3_*.py` | The tests of design 5.6, without the v2 reduction (Q14):<br>- two-bin analytic control;<br>- FIFO on 500 legs;<br>- the route check never rejects a feasible explicit route (1,000 instances) and is exact against brute force up to 8 tasks;<br>- replay and tamper tests for every new proof kind;<br>- label invariance under a rational rescaling. |
| B8 | N `docs/VERIFIER_SPEC_V3.md`, N `src/verify/` (target under 2,000 lines) | Written from the spec only. Modules:<br>- `scenario`: SI parsing;<br>- `arith`: Fractions and square-root enclosures;<br>- `wind`: own binned integrator;<br>- `u0`: own dependency rule;<br>- `masks`: level masks;<br>- `plan`: exact re-fly from the actual departures;<br>- `bounds`: gradient check per mesh triangle per covered bin;<br>- `routes`: local checks of the route-proof table (Q6 (c), four checks, no search);<br>- `farkas`: own one-UAV rows;<br>- `trees`: stop-sequence and assignment trees;<br>- `level`: the bracket.<br>Tests: an AST and `sys.modules` guard against any `src` import, and tamper tests (one number changed, one branch deleted, one multiplier negated). |
| B9 | N `src/verify/exhaustive.py`, `src/verify/tiny.py` | 600 tiny missions (2-3 UAVs x 2-3 tasks):<br>- **Exact set:** spatially uniform wind in each bin. The fastest flight has one fixed heading, and the time solves `abs(b - a - W(T)) = v*T` bin by bin (a quadratic per bin). Every assignment, order and depot stop allowed by Rules 1 and 2 is enumerated, and quantities use an own small rational LP.<br>- **Realistic set:** an own space-time grid path finder gives achievable plans, which the verifier re-flies.<br>- Agreement rules as in design 5.7. |
| B10 | N `docs/FIFO_PROOF_V3.md` | The written FIFO and energy argument (the gate before primary runs), **before B2 is coded**. It fixes:<br>- the payload lower bound used in B2's energy labels (Q15);<br>- energy dominance: under time-dependent wind a label that arrives earlier may have spent more energy on a slower leg, so (time <=, energy >=) pruning is unsound if energy is charged from the actual leg time. Proofs therefore charge energy with the departure-independent envelope bound and use alpha only for arrival times;<br>- why plans need no holds (FIFO on a fixed path plus Rule 2). |

**Gate B:**

- every B7 test passes;
- labels are unchanged under a rational rescaling (moved from Gate A, Q13);
- `verify/` and the exhaustive search agree with v3 on all 600 tiny missions.

A8 admission needs only the exact checker (decided 5 November), so MS and SC generation can run before Phase B.

### Phase C: builders, comparison and server

| WP | Files | Content |
|---|---|---|
| C1 | N `study_v3/bands.py` | A lambda-bisection engine shared by the MS bands and LS.<br>- One probe is a CMI v3 run at `d_i(lambda) = u_i + lambda * margin_i`. A plan at level k at lambda holds for every larger lambda, and a proof for every smaller one. All thresholds are narrowed together.<br>- MS: 12 probes of 20 s on a seeded third of the missions (972 variants).<br>- Probe records are compact: level, bound, and a witness or proof hash.<br>- Note: at lambda near 0 the deadline equals u_i, so the previous premise needs a positive floor on lambda. |
| C2 | N `study_v3/levelsuite.py` | Replaces `final_study/levelsuite.py` and `level4.py` (the constructions are dropped).<br>- **Recipes:** helper, split, chain, wide, reorder, recharge, no continuation, path repair (bin timing dropped; Q1, Q9). Each sets a target set K.<br>- **Band acceptance:** at least 60 s wide and at least twice the widest decisive-leg interval (from B5).<br>- **Labelling:** midpoint placement, then a cold 600 s label; a label that disagrees with the band is discarded and logged.<br>- **Mechanism from the witness:** "helper required" also needs the Level-3 allowance-0 exclusion (`level3(allowance=0)`, the existing CMI-mu machinery; Q10).<br>- **Quotas and caps:** design 8.2 and 8.4, with the 30 bin-timing instances moved to reorder and recharge (45 each).<br>- **Stages:** 12 x 20 s, then 6 x 120 s, then 600 s and replay.<br>- **Stop:** 120 draws per mechanism x fleet cell.<br>- **Hard instances:** 50 from probes left open at 600 s. |
| C3 | N `study_v3/harness.py`, `scripts/server/` | - Workers: physical cores - 2, capped by memory.<br>- `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS` and `MKL_NUM_THREADS` set in the launcher before any import.<br>- Pool: `ProcessPoolExecutor(mp_context=forkserver, max_tasks_per_child=1)`.<br>- Memory: a worker initializer sets `resource.setrlimit(RLIMIT_AS, 2.5 GB)` (Linux only). A `MemoryError` is logged and retried once alone at 8 GB.<br>- SC runs on its own queue: 8 workers, 8 GB each.<br>- Units run longest-expected first.<br>- Records: zstd (needs `zstandard`; Q16), atomic writes, flight-time certificates stored once by content hash and cited.<br>- The manifest adds `lscpu`, kernel, governor and the `uv.lock` hash.<br>- A systemd or tmux unit and a nightly `rsync --checksum` script. |
| C4 | N `study_v3/arena.py`, `study_v3/reference.py` | - Arms GR, GR-c, LR, PH, CMI, noAF and noER on `certify_v3`, with the budgets of design 10.2.<br>- GR and GR-c get two extra seeds on 300 MS variants.<br>- Reference labels follow rules 1-5 of design 10.4:<br>  - verified plans are pooled from every arm and budget;<br>  - proofs count only if checked by `verify/`;<br>  - undecided instances get 600 s runs of GR, GR-c, LR and PH;<br>  - everything is re-scored without CMI's plans;<br>  - every arm is also scored on the 600 tiny missions.<br>- CMI+ is optional (Q11). |
| C5 | N `study_v3/stages.py`, `study_v3/cli.py`, `scripts/run_study_v3.py` | Stages in dependency order:<br>- `ms-generate`, `sc-generate`;<br>- `ms-label`, `sc-label` (SC on its own queue), `ms-bands`;<br>- `ls-build`;<br>- `tiny`;<br>- `ca-ms-10`, `ca-ms-60`, `ca-ls`, `ca-sc`;<br>- `ref-undecided`, `ca-seeds`, `cmi-plus`;<br>- `contention`, `audit`, `report`.<br>Reference labels run before CA, as the design requires. Resume and failure notes work as now. |
| C6 | N `study_v3/analysis.py` | Report on the metrics of design 11.1:<br>- every value in SI next to its dimensionless ratio;<br>- identification bounds for open instances;<br>- 2,000 bootstrap resamples over base missions (reusing `final_study.analysis.bootstrap`);<br>- the interval-censored ordinal regression on the six factors (reusing `ordinal_regression`);<br>- paired comparisons;<br>- the targets of design 11.3 marked met or missed;<br>- the pilot measurements (thread-sharing factor, peak memory, bytes per record). |

**Gate C:** a smoke configuration (`configs/study_v3/smoke.json`) runs every stage on the
server and is resumed once after a forced stop.

### Phases D-F

| Phase | Files | Content |
|---|---|---|
| D pilot | N `configs/study_v3/pilot.json`, `scripts/pilot_fallback_v3.py` | - Seeds 75001-75004 (unused so far).<br>- 27 MS missions: a 3^(4-1) fraction of the four mission factors (design: "an orthogonal fraction of the 81 cells").<br>- 20 draws per LS mechanism and 12 SC missions.<br>- Slack ranges and battery rule are fixed in advance, not calibrated. The pilot checks that every MS cell can be filled within the draw limits of A8.<br>- **Incumbent quality check (design 4.3, Q17):** on 50 missions, rerun the local search 10x longer (20,000 iterations) with 5 restarts. Restart r takes the finished plan, removes floor(0.2 k m) tasks (at least 2) chosen with seed = first 8 bytes of SHA-256 of "mission seed \| restart \| r" (not Python's salted `hash()`), reinserts them by regret and runs the local search again. Report the best exact makespan over the restarts against the first run; about 1-2 % improvement is expected. The incumbent itself is always the deterministic first run.<br>- The fallback rule of design 14.3 is a script that reads the pilot's undecided rate.<br>- Then freeze `configs/study_v3/final.json`. |
| Release | repository | Commit the clean tree, then tag it, and lock the environment (`uv.lock`, Python 3.13.3; retire `environment.yml`'s 3.10 pin). Archive with a DOI. |
| E primary | `configs/study_v3/final.json` | Seeds per Q8. Night 1: MS labels and bands, plus SC labels. Night 2: LS. Night 3: CA. |
| F analysis | `study_v3/analysis.py`, `verify/` | Report the targets as met or missed, and replay 200 records on the Windows laptop. `verify/` is pure Python, so it runs there unchanged. |

## 4. Order and critical path

1. A0 (schema, accessor, binned checker). Verify: the v2 suite is unchanged, the one-bin
   checker equality holds, and the two-bin control passes.
2. B10 (written FIFO and energy argument). Verify: the supervisor accepts it, including
   the payload lower bound and the energy-dominance rule.
3. A1-A7, then B1-B4, then the A8 admission, then B5-B7. Verify: Gate A as reduced, then
   the B7 tests.
4. B8-B9 (verifier, tiny missions). These can run in parallel with step 3 once A0.1 and the
   proof formats are fixed. Verify: Gate B.
5. C1-C6. Verify: Gate C on the server.
6. D, release, E, F.

The longest chain is A0 → B1 → B2 → B3 → B4 → A8 → C1/C2 → D. B8 and B9 run beside it.

## 5. Unchanged (and why)

These stay as they are:

- `certify_v2/`;
- `final_study/`, `escalation_study/`, `level2/` to `level4/` (apart from A0.7's dispatch in
  `level2/quantities.py`), `continuous/potential.py`, `continuous/physics.py`;
- every `configs/final_study/*` file and every record under `results/`.

The archived runs open with `Store(..., bind=False)`. Their bit-for-bit reproduction is
checked by:

- running the full existing test suite after every A0 step;
- replaying a seeded sample of 200 records from `results/final_study_2026_10_17` before and
  after A0.

## 6. Open questions (B = blocks code)

| # | Question | Recommendation |
|---|---|---|
| Q1 | **Decided 5 November: front updates removed.** Onset and passage need a front in F0, which brings in a fairness and pairing problem across the r variants. | Magnitude updates only (A2, A6). The LS "bin timing" class (design 8.2 and 8.3, 30 instances, recipe "front onset") is dropped (5 November); its quota moves to reorder and recharge (45 each, C2). |
| Q2 | **Decided 5 November: incumbent of design 4.3.** Regret-2 insertion plus local search on makespan and flight time; deadlines and batteries are set from the built plan, so the planner never needs them. | Done (A4). |
| Q3 | **Decided 5 November: C = R x (1 + beta) / 0.9.** "Requirement x (1 + beta) + reserve", with the reserve at 10% of capacity, made the capacity depend on itself. | The reserve is 0.1 C and the usable 0.9 C equals R x (1 + beta), with R the requirement under F0 (A5). |
| Q4 | **Decided 5 November.** One visit per task and no back-to-back depot stops (Rules 1 and 2) replace the 2k + 3 stop limit; the slot bound is derived as 2a + 1 (D-6). Quantities are counted in packages of 0.5 kg, with a capacity of 5 packages. | Done (A0.1, A3, A4). Demands of 1-5 packages always fit in one load. |
| Q5 | **Horizon.** The current generators use 1,000 h, which would mean 4,000 bins. | The horizon is the F0 makespan + the largest margin + 1 h, rounded up to 900 s. |
| Q6 | **Decided 5 November: (c), a table of best partial routes, checked locally.** The independent second search of option (b) already comes from the 600 tiny missions checked exhaustively (B9). | **What B2 records.** State key: (tasks done, current place: a task or the depot after a reload, packages on board). Label: optimistic arrival time (from the B1 lower-bound tables) and optimistic energy left. Saved: every label not beaten within its key, with the hash of each flight-time certificate it used; dropped branches are not saved. Beaten: same key, no later arrival and no less energy.<br>**What `verify/` checks** (no search of its own): (1) the UAV's real starting state is in the table; (2) every extension is covered: for each saved label and each allowed next step (an undone task, or a depot stop then an undone task) the result computed from the certified bounds either breaks something (a deadline with demand still due; the horizon, using the lower bound on the return flight; the battery reserve, using the lower bound on the return energy; the payload) or is beaten by a saved label with the new key; (3) no saved label with all tasks done can reach the depot by the horizon with its reserve; (4) monotonicity: each cited arrival bound is non-decreasing in departure time, and P(m) > 0 over 6.5-9.0 kg, so energy left falls as flight time grows. |
| Q7 | **Decided 5 November: no holds.** Rule 2 forbids ground waiting, and FIFO on a fixed path means an earlier arrival never hurts. | Done (D-5). |
| Q8 | **Seeds.** "Primary from 76001" collides with the 14 October study: FS 76001-76162, the arena third 76002, variance 76003 and 76004, the smoke run 79001, LS 78001, and scans in 77001-77991. | Primary from 81001. The pilot's 75001-75004 are unused. |
| Q9 | **Closed 5 November: the "bin timing" class is dropped (Q1).** | Nothing to decide. |
| Q10 | **"Helper required".** Does it mean Level 3 at helper allowance 0 is excluded (the existing `level3(allowance=0)`)? | Yes. |
| Q11 | **CMI+.** The fewest reassigned *tasks* is a new search; the existing CMI-mu counts the fewest *outside UAVs*. Which one? | Keep it optional and decide after the pilot (design decision 6). |
| Q12 | **Decided 5 November.** From the Matrice 350 RTK: two 263.2 Wh batteries, 55 min without payload, so about 574 W at 6.47 kg; scaled with mass^1.5 and fitted by a line over 6.5-9.0 kg. | P(m) = 145.5 W/kg x m - 368 W for all three airspeeds (about 578 W empty, 942 W fully loaded), exact rationals, in `configs/study_v3/physics.json`. Service: 60 s at P(mass on arrival), so v3 `service_energy_wh` = 0 and the code adds the hover energy. The schema allows a negative a; the validator requires P > 0 at the empty mass. |
| Q13 | **Decided 5 November: the label rescaling check moves to Gate B; the v3 = v2 label check is dropped (Q14).** Any check that compares certified labels needs Phase B. | Gate A tests the generator only (Section 3). Admission no longer needs labels (A8). |
| Q14 | **Decided 5 November: no v2 reduction check.** v3 is a new design, so its labels are not compared with v2. | Done (B7, Gate B, D-1). |
| Q15 | **The payload lower bound in route-check energy.** The "current sortie" is unknown while the forward search is running. | `max(0, remaining mandatory demand - C x reloads still possible)`, plus the exact onboard mass for an airborne start. Energy charged with the envelope bound, alpha for times only. Fix it in B10 first. |
| Q16 | **zstd.** It needs the `zstandard` package (Python 3.13 has no `compression.zstd`). | Add it to the lock file, or keep gzip (about 20-30% larger). |
| Q17 | **Decided 5 November: incumbent search details** that design 4.3 left open (speed and reproducibility):<br>- float times during the search, restricted to + - * / and square root in a fixed order; one exact pass at the end, with deadlines and batteries from the upper ends of the exact intervals;<br>- best improvement over the fixed move order, ties to the first move met, a 1e-6 s threshold on both makespan and flight time;<br>- a task only one UAV can take has infinite regret; ties go to the lowest task number (k x m tasks for k x m places, so a task with no room cannot occur);<br>- pilot restarts remove floor(0.2 k m) tasks (at least 2) chosen with a SHA-256 seed and reinsert them; the incumbent is always the first run. | Done (A4, A5, D pilot). Design Section 4.3 to be updated with the same text. |

### 6.1 Design-doc text still to update

These are edits to the design docx, not to code:

- Sections 4.2 (the three kinds and the Latin balance of kind), 8.2 and 8.3 (the "bin timing" class, now dropped:
  remove it and give reorder and recharge 45 each), 14.1 (Gate A) and 15.1 ("Setting") still describe front updates
  (Q1).
- Sections 4.3 and 6 ("plus the reserve") should give C = R x (1 + beta) / 0.9 (Q3).
- Section 4.3's "payload at most 2.7 kg per sortie" should read 5 packages of 0.5 kg, and
  any 2k + 3 stop limit should give way to the two plan rules (Q4).
- Section 4.3 should add the Q17 rules (float times and the exact pass, tie-breaks, the
  1e-6 s threshold, infinite regret, the restart recipe).
- Section 5 and the 5.6 "Reduction" bullet still describe the v2 reduction check (Q14).
- "Mandatory and optional parts" of demand should go (Rule 1), and the two plan rules
  should be stated with the paper sentence above.

## 7. Risks

- **Proof size:** route-proof tables (Q6) and windowed certificates can exceed the 2 MB per
  instance the design assumes. The pilot measures it, and the design's 60 GB rule applies.
- **`RLIMIT_AS` at 2.5 GB:** numpy, scipy and clarabel reserve virtual address space at
  import, so the limit may need to be on resident memory instead. Measure it in the Gate C
  smoke run.
- **Route-check size:** it is 2^n in the tasks per UAV, and at Level 4 one UAV may take many
  tasks. B2 is exact to about 12 tasks and weaker beyond, so some large SC instances may
  stay undecided; they count in the unresolved rate.
- **Potential cost:** per-pair fields grow with the number of distinct winds per cell
  (up to the number of bins). Dedupe the winds, and let the pilot measure the cost against
  the design's assumed factor of 3.
- **Incumbent speed:** regret insertion and local search over 96 tasks with binned exact
  times uses float times during the search and one exact pass at the end (Q17); the pilot measures the run time.
- **Plan rules not verified (assumption):** Rules 1 and 2 are not checked by `verify/`,
  because the planners obey them by construction. The baseline arms also produce plans; a
  few lines in `env/plan.validate_plan` (no split task, no two depot stops in a row) would
  catch a planner bug cheaply, if wanted.
- **Working tree:** the untracked state blocks the "clean tree, tagged release" step until
  it is committed (this plan commits nothing).
