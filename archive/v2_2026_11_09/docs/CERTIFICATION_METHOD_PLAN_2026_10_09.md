# Certification method v2: one search for plans and proofs at every level

Date: 9 October 2026. Status: **proposal for approval**. No code has been changed.
Results that motivate it: `docs/ESCALATION_PRIMARY_RESULTS_2026_10_09.md`.

## Summary

1. Every level asks the same question: can the choices this level allows to change be
   re-made so that every delivery still meets its deadline and the battery, payload and
   stock limits hold? The answer is a plan, which the exact checker confirms, or a proof
   that no such plan exists.
2. Under the study's assumptions a faster flight never hurts. Each flight leg therefore
   enters the problem only through its fastest flight time, which we know as an
   interval: a proven lower bound and the time of an actual path.
3. One search answers each level's question, run twice. With the lower bounds, failure
   proves that the level is impossible. With actual path times, success gives a plan.
   If the two runs disagree, only the legs that decide the answer are refined.
4. The levels differ only in what the search may change. Level 0 changes nothing,
   Level 1 the paths, Level 2 the visiting order of the affected UAVs, Level 3 also who
   serves which task among the affected UAVs and one helper, and Level 4 everything.
5. Four parts implement it:
   - a flight-time table shared by all levels, searches and slack variants;
   - a route check that finds the best visiting order for one UAV;
   - an assignment search across UAVs;
   - the existing exact check of quantities, energy and payload, with a multi-trip
     fallback.

   The ladder alternates between looking for plans and proofs, so a usable plan exists
   early.
6. Each change targets one of the causes found in the records of the 286 open P1
   variants (Section 1). The method is versioned as v2. The v1 code and all frozen
   results stay as they are.

Decisions to confirm: Section 12.

## 1. Why the method needs to change

Primary P1 left 286 of 1,800 variants open:

- 160 with Level 3 undecided and Levels 0-2 proven impossible;
- 43 with Level 4 undecided and Levels 0-3 proven impossible;
- 83 with Level 1 or 2 undecided.

In the larger missions, 24 of 40 stayed open. The records of the six re-audited P1
missions and of the 40 larger missions show four causes:

| Cause | Evidence |
|---|---|
| Time goes into computing paths, mostly for pairs of points that only need a lower bound | Path computation took a median 55% of each open Level-3 search (range 26-76%) and 80% of each open Level-4 search (73-82%); the lower bounds themselves took about a quarter. In 5 of the 7 larger missions where the Level-2 search started, it visited no node: computing the pair bounds used all its time. |
| Helper patches are searched one after another | In all 29 open Level-3 searches, only the first helper's patch was opened. The other one or two helpers were never tried. |
| Pruning tests one task at a time | An assignment or a partial route is rejected only when a single task cannot be reached in time on its own. Each assignment therefore needs a full sequence search. The open Level-3 searches reached 1-5 complete assignments; one sequence search visited 18,681 nodes in 13 s without finishing. Of the 83 variants open at Levels 1-2, 80 stopped at the Level-2 time cap after 218-4,340 nodes; the other 3 finished with leaves left open by path gaps. |
| Plans come from a fixed list of 120 moves, each costing a full path optimization | On larger missions each proposal cost a median 0.68 s; in the open ones the screen spent most of the minute on 45-120 proposals. |

The method also has a structural problem. Levels 0-1 (the screen), Level 2 (the slot
search) and Levels 3-4 (the assignment search) are separate procedures, each with its
own rules for proofs and plans. That makes the method hard to state and its parts hard
to compare.

## 2. What the method must produce

For a variant and a level k, the patch Pi_k is the set of plans whose coordinates
outside level k's release mask equal the incumbent's. This is unchanged from
`env/local_scope.scope_family`.

- **Plan at level k:** a member of Pi_k accepted by the exact checker (`certify_witness`
  or the exact quantity witness).
- **Proof at level k:** a record showing that Pi_k contains no feasible plan. An
  independent checker replays it without optimizers.
- **Certified minimum and no continuation.** Since Pi_0 ⊂ Pi_1 ⊂ ... ⊂ Pi_4, a proof at
  level k covers every lower level. The certified minimum is k when there is a plan at
  k and a proof at k - 1. "No continuation" is a proof at Level 4.
- **Bracket.** Whenever a run stops, it reports [lower, upper]. Lower is one more than
  the highest level proven impossible. Upper is the lowest level with a plan.

Unchanged: the level definitions, D1-D3, the P1 missions and admission rule, the exact
checker, and the transfers along the slack chain.

## 3. The key fact: each leg enters only through its fastest time

In P1 and E1 the following hold:

- the wind does not change after the update;
- a UAV never waits: it leaves each stop when service or preparation ends, and tasks
  have deadlines but no earliest times;
- depot preparation has no bay limit (`depot_bays = None`);
- a leg's energy is (empty mass + payload mass) x energy coefficient x airspeed x flight
  time (`recovery/transfers.py`).

Fix the assignment, the order of stops and the quantities. Flying any leg faster then
makes every later event earlier and uses less energy. Flying every leg, and every
reserve return to the depot, on a fastest path is therefore best for all deadlines, the
horizon, battery and reserves at once.

A leg matters only through T(a->b), the fastest flight time from a to b at that UAV's
airspeed. This holds for legs whose path the level releases and for reserve returns. A
fixed, committed or non-participant leg keeps its own path and enters with that path's
time interval, as now (`level2/bounds.py`, `continuous/search.py`). The method holds
each T as an interval:

- **Lower end:** proven for every possible path by a verified potential field
  (`continuous/potential.py`).
- **Upper end:** the exact flight time of an actual path.

Each level's question becomes a scheduling question with interval flight times: who
serves which task, in what order, with which depot visits. It also includes a small
linear problem for quantities, energy, reserves and stock, which `level2/quantities.py`
already solves exactly.

**Which assumptions soundness needs.** Proofs rest on steady wind, which the lower
bounds require, and on the energy model, in which energy grows with flight time. The
other assumptions matter only for the claim that fastest legs suffice, which keeps the
search small and complete.

If a later study adds earliest times or bay limits, the optimistic run can drop them.
That is a relaxation, so its proofs stay valid. Waiting would then become a real
choice. A no-wait optimistic run stays a relaxation only if it also drops every rule
under which arriving earlier can hurt. Plans are always checked exactly. Only
completeness would then need more work.

## 4. One test, run twice

For each level the same search runs over the same choices:

| Run | Flight times | If no plan meets the limits | If a plan meets them |
|---|---|---|---|
| Optimistic | lower bounds | **proof** that the level is impossible, because no flight can be faster than these times | nothing proven yet |
| Achievable | times of actual paths | nothing proven yet | **candidate**, sent to the exact checker |

If the optimistic run finds a plan but the achievable run does not, the gap has one of
three sources:

- **Wide intervals.** Some legs' intervals are too wide. Only those legs are refined: a
  finer potential field for the lower end, a better path for the upper end.
- **Large task sets.** The optimistic run used the cumulative bound for a large task
  set (5.2).
- **Energy and quantities.** Only the full check sees these (5.4). The full check and
  the slot search handle this source and the previous one.

If a leg is still too wide at the finest refinement, the level stays open.

What each level may change:

| Level | May change | Search |
|---|---|---|
| 0 | nothing | exact check of the incumbent |
| 1 | paths of U0 | one schedule per U0 UAV, order fixed |
| 2 | order, depot visits and quantities of U0; every task stays with its UAV | route check per U0 UAV (5.2) |
| 3 | also the owner of each task among the participants (U0 plus one helper), for every choice of helper | assignment search, helpers interleaved (5.3) |
| 4 | everything except commitments | assignment search over all UAVs (5.3) |

Commitments are fixed at every level, as now. In flight, D1 makes each airborne UAV's
current destination a commitment.

## 5. Building blocks

### 5.1 Shared flight-time table

- **One table per mission and wind strength.** All levels, all searches and all five
  slack variants share it, because deadlines do not change flight times.
- **Lower bounds, computed when needed, cheapest first:**
  1. distance / (airspeed + largest wind speed), in exact arithmetic with a lower bound
     on the square root;
  2. a shared potential field per goal point and airspeed, whose mesh contains every
     mission point;
  3. a per-pair field at refinement 2, 4, 8 and then 16, only when a decision depends on
     that leg.
- **Upper bounds, computed when needed:** first the exact time of the straight chord,
  which is always a valid path because the operating region is a rectangle. Then a
  conic-optimized path (`ContinuousOracle._optimize`), only for a leg of a candidate plan
  whose chord is too slow.
- **Pruning never waits for an upper bound.** This removes the path computation that
  dominated the open searches.

A field phi that passes the existing triangle-by-triangle check bounds every path,
whatever its endpoints: T(x->y) >= max(0, phi(y) - phi(x)). Today each field serves the
one pair it was optimized for. A shared field serves every pair, for the same airspeed
and wind, with every mission point a mesh vertex. It needs a new certificate kind (the
field plus its point list), checked once.

An independent review confirmed this bound. In a scratch test, a field built for one
pair bounded 60 random vertex pairs; the bound reached at most 0.996 of the
corresponding flight time. The mesh limit of 5,000 vertices and the many distinct
in-flight positions in E1 limit how many points one field can serve.

### 5.2 Route check for one UAV

The route check asks: can a UAV that leaves point p at time t serve task set R, each task
by its deadline, and reach the depot by the horizon H?

- **Inputs.**
  - R is every task assigned to the UAV and not yet visited. Every assigned task needs
    a visit by its owner (`env/plan.py`).
  - A task carries its deadline only while mandatory demand remains. Otherwise it only
    has to be visited by H.
  - t is the departure time, which includes preparation for a ground depot origin.
- **Latest departure.** Let s be the service time. Compute

  ```text
  tau(p, {})  = H - T(p->depot)
  tau(p, R)   = max over r in R of  min( d_r - T(p->r) - s ,  tau(r, R - {r}) - T(p->r) - s )
  ```

  R can be served iff t <= tau(p, R). Departure time only shifts all later times, so one
  table of values serves every departure time. A scratch check against brute force over
  all orders (3,000 random instances, exact arithmetic) found no mismatch.
- **Optimistic run (lower bounds).** If t > tau(p, R), no order works even when every leg
  takes its lower bound. Depot visits and repeat visits cannot help, because the fastest
  times obey the triangle inequality and each visit adds service or preparation time.
  This is a proof for R. It also covers every set that contains R, because dropping a
  task from a feasible route keeps the route feasible.
- **Achievable run (upper bounds).** The order that attains tau is a candidate route.
- **Payload.** Loading happens only at a ground origin or at an intermediate depot stop,
  and each of these includes preparation.
  - The set needs at least k = max(0, ceil((Q - L0) / C)) further reloads, where:
    - Q is the remaining mandatory demand;
    - C is the payload capacity in units;
    - L0 is the most the UAV can hold when the check starts: C at a ground depot origin
      (its preparation is already in t) and after a prefix, and the observed onboard
      load for a UAV in flight.
  - The optimistic run adds k preparation times to the horizon test only, not to the
    deadlines.
- **Size.** The check is exact for up to about 12 tasks per UAV (2^12 subsets). Beyond
  that, the optimistic run uses a cumulative bound. The tasks with deadline at most D
  need, before D, their service times plus, for each task, its cheapest incoming leg.
  That leg may come from any possible predecessor: the start, the depot or any task,
  including tasks outside the set.
- **Proof record.** The record holds the UAV, the start, the set, the lower bounds used
  (each with its certificate) and tau. The checker recomputes tau exactly.
  - When a smaller set's failure closes a larger set, the record cites the smaller
    set's tau.
  - It does not recompute tau for the larger set, because lower bounds of mixed
    quality need not obey the triangle inequality.

This replaces the present test, which asks only whether each unvisited task can be
reached on its own, with a test of all remaining tasks together. At Level 1 the order
is fixed, and the check reduces to the existing schedule test (`deadline_certificate`).

### 5.3 Assignment search (Levels 3-4)

- **Branching.** Branch on the owner of each released task, most urgent first. Each
  branch lists every allowed owner, so, as now, the tree covers every assignment exactly
  once.
- **Pruning.** Prune a node when any of these holds:
  - some owner's decided tasks (fixed plus branched) fail the optimistic route check
    from that owner's true start;
  - a task cannot be reached in time by any allowed owner;
  - an owner has more tasks than its slots allow.
- **Helper interleaving.** At Level 3 the helper is the first branching choice. Open
  nodes from all helpers share one queue, ordered by promise, with depth-first dives.
  No helper can use the whole budget. This best-first order decides only where to look
  first; only proofs remove anything from the search.
- **Order for plans.** Try keeping each task with its current owner first, then other
  owners by slack.
- **Optional, for larger missions.** A linear workload bound over all participants:
  fractional assignment with cumulative deadline limits per UAV. It uses the same
  cheapest incoming legs as the cumulative bound. When it is infeasible, it gives an
  exact Farkas certificate, as `level2/quantities.py` already does.

### 5.4 Full check and multi-trip fallback

- **Full check of a candidate.** For an assignment with its orders, the exact linear
  problem (`evaluate_quantities`) sets quantities and checks energy, reserves and stock.
  With lower times it can prove that one stop sequence impossible. With upper times it
  gives a plan.
- **Fallback when the check fails.** A failed candidate proves nothing about its
  assignment: another order or added depot visits may work, because energy depends on
  the order. The existing complete slot search (`level2/skeletons.py`) then decides that
  assignment, with the route check as its prefix bound. An assignment is closed only by
  a route-check failure or by a slot search that finds no feasible skeleton.
- **Two reductions in the slot search:**
  - no two consecutive depot stops;
  - no two consecutive visits to the same task.

  Each excluded skeleton is dominated by merging the two stops into the first one.

  **Conditions for the reductions.** The independent review set these:
  - both stops lie in released, uncommitted slots of a participant;
  - every later slot of that UAV has its order, path and quantities released, because
    merging shifts the later slots;
  - the kept stop's quantity is released;
  - a ground origin counts as a depot stop only for an idle depot origin whose initial
    load is released;
  - a lone depot stop is never merged into an empty route, because that would lose the
    recharge.

  These conditions hold for participants in P1, which has no commitments, and in E1,
  which commits only the first stop and its task's owner. Both reductions will be
  proven in writing and tested against full enumeration before use.

### 5.5 Plan finder

- **Same route check, achievable times.** At Level 2 it returns the best order for each
  U0 UAV. At Levels 3-4 the assignment search with achievable times returns a complete
  plan.
- **Large pools.** When a pool is too large for the exact route check, the finder uses
  cheapest insertion of the late tasks, then local moves: relocate, swap, reorder, or
  insert a depot visit. Each move is scored by total lateness with achievable times.
- **Scoring before checking.** Candidates are scored from the table. Only a candidate
  that passes goes, with its actual paths, to the exact checker.
- **Heuristic-only comparator.** Run without proofs, the same finder serves as the
  heuristic-only comparator in Section 10.

## 6. The ladder: alternate between plans and proofs

1. **Quick global proofs.** The committed-prefix certificate, reach of each task by any
   UAV, and the physical certificates, as now.
2. **Lowest open level first.** Decide each level with the two runs within a time
   slice. A plan ends the ladder, because the lower levels are already proven
   impossible. A proof moves on to the next level.
3. **Undecided levels.** If a level stays undecided in its slice, the ladder first looks
   for plans at the higher levels, so that an upper bound exists early. It then returns
   to the undecided level with the remaining budget.
4. **Slack chain.** The shared table, exclusion transfer and witness back-propagation
   work as now.

Each variant gets one wall-clock budget. Slices are calibrated in the pilot. As now,
every bound change is logged with its time.

## 7. Records and audit

- **New proof kinds:**
  - route check (`route_timing_v2`);
  - shared potential field (`potential_field_v2`);
  - workload bound (`workload_farkas_v2`), if used;
  - the two reductions in the slot search.
- **What each record stores.** Each node of the assignment tree stores its full list of
  children, and each closed node stores its proof. Plans are stored with their paths and
  checked exactly. As today, the audit replays everything without optimizers.
- **Frozen results.** The v1 modules stay, so the frozen records (P1 primary,
  comparators, R1, E1) still replay.

## 8. Guarantees and limits

- **Sound.** A plan is accepted only by the exact checker. A proof uses only verified
  lower bounds, dropped constraints and complete child lists.
- **Complete on its domain.** The choices are finite, because each UAV has a slot
  bound. With enough time every level is decided, except when the answer hinges on a
  leg whose interval stays too wide at the finest refinement. Such variants stay open
  and are reported as open.
- **Anytime.** The bracket is valid whenever a run stops.
- **Limits:**
  - exact route checks stop at about 12 tasks per UAV;
  - Level-4 proofs on 48-task missions may stay out of reach, although plans should not;
  - the bounds require steady wind.

## 9. Code changes

| Part | Status | Location |
|---|---|---|
| Exact checker, potential verification, quantity LP and Farkas checks, committed-prefix and physical certificates, scope families, run store, audit framework | kept | as now |
| Flight-time table with lower and upper bounds computed when needed | new | `src/certify_v2/table.py`, using `continuous/oracle.py` and `continuous/potential.py` |
| Shared potential field and its verifier | new | `continuous/potential.py`, as new functions; existing ones unchanged |
| Route check and its verifier | new | `src/certify_v2/route.py` |
| Assignment search with helper interleaving | new | `src/certify_v2/search.py`; takes the role of `level3/search.py::_search_assignments` in v2 runs |
| Slot-search fallback with the route check as prefix bound | changed | `level2/search.py`, through a new optional argument; default behavior unchanged |
| Plan finder | new | `src/certify_v2/plans.py`; takes the role of `_proposals` in v2 runs |
| Ladder v2 and run switch | new | `src/certify_v2/ladder.py`; `--method v2` in `scripts/run_escalation_study.py` |
| Replay of the new proof kinds | new | `src/certify_v2/replay.py`, called from `escalation_study/audit.py` |

## 10. Tests and experiments

### Before any run

1. **Unit tests.**
   - The route check agrees with brute force over all orders on random instances,
     including a test fixture with true flight times.
   - Optimistic times never exceed the closed form under uniform wind, as in the
     diagonal control.
   - Shared-field bounds never exceed achievable times.
   - Both reductions agree with full enumeration on small slot domains.
   - Every new proof kind replays, and tampered records fail.
2. **Agreement check.** Rerun all 1,514 P1 variants that v1 certified. Any difference in
   the certified level is a defect, to be fixed before going on.
3. **Pilot.** The pilot missions (seeds 71001-71002), the 286 open P1 variants, and a
   stratified sample of 200 certified ones. Calibrate the slices, fix the success
   criteria, then freeze v2. The pilot uses primary variants, so the confirmation set in
   M1, which no part of the design has seen, gives the unbiased estimate. The primary
   seeds give the paired comparison with v1.

### Experiments after the freeze

Each experiment's outcomes are fixed before it runs.

| Study | Question | Units |
|---|---|---|
| M1 method comparison | Does v2 decide more variants, faster, under v1's budgets (30 s, then 120 s for open variants)? | The 1,800 P1 primary variants, plus a confirmation set of 120 new missions (seeds 74001-74020) that no part of the design has seen |
| M2 equal resources | With one cap, one pass, no slack chain and no reused evidence, what do the proofs add over the same plan finder alone and over C3? | The 700 variants with lower bound at least 1, at 10 s; the 286 v1-open variants plus 100 others at 60 s |
| M3 ablations | Which part accounts for the gain? Remove in turn the shared table, the route check (use the single-task test), interleaving, and the plan finder. | The 700 variants, at 10 s |
| M4 scaling | How large can missions be? | The 40 larger missions, at 60 s and 300 s |
| M5 in flight | Does E1 change? | The 1,200 E1 variants; alternatives to D1 are a separate decision |

M2 reports, for each method:

- the share of variants with a proven answer;
- the share with a plan at the true minimum, and the time to that plan;
- the time spent at levels that are impossible;
- how often the heuristic-only ladder gives up on a level that has a plan.

These outcomes show what proofs are worth in practice. They tell the ladder when to
stop searching a level, and they settle "no continuation" so that the decision can move
to the mission level.

**Proposed success criteria, to fix after the pilot and before M1:**

- no disagreement with any v1 certificate, and every v2 proof replays;
- under v1's budgets, at most 5% of P1 variants stay open (v1: 16%);
- at equal resources and 10 s, v2 decides at least 90% of the 700 variants;
- at least 75% of the larger missions are decided within 60 s (v1: 40%).

A missed criterion is reported as missed.

## 11. Budget on the laptop

Worst case on six workers, every run hitting its cap and at most 20% of variants
entering the 120 s second pass:

| Block | Units | Cap | Wall |
|---|---:|---|---:|
| Agreement check (before the freeze) | 1,514 variants | 30 s | 2.1 h |
| M1 on primary seeds | 1,800 variants | 30 s, then 120 s | 4.5 h |
| M1 confirmation set | 1,800 variants | same | 4.5 h |
| M2 | 3 methods x (700 at 10 s + 386 at 60 s) | as listed | 4.2 h |
| M3 | 4 ablations x 700 | 10 s | 1.3 h |
| M4 | 40 missions x 2 caps | 60 s, 300 s | 0.7 h |
| M5 | 1,200 variants | 30 s, then 120 s | 3 h |

The worst case is about 20 h, or three overnight runs. Typical costs should be far
lower, because most variants already close in under a second.

## 12. Decisions for you

1. **The method.** Approve Sections 3-8, including the assumptions in Section 3.
2. **Versioning.** v2 is a separate method. v1 and all frozen results stay untouched.
3. **Confirmation set.** Use a confirmation set of new missions for M1, because this
   design was informed by the primary records.
4. **Success criteria.** Agree the proposed criteria in Section 10 as a starting point.
   They are fixed after the pilot and before M1.
5. **Implementation order.** Build in this order, with tests at each step: table (5.1),
   route check (5.2), assignment search (5.3), full check and fallback (5.4), plan finder
   (5.5), ladder (6), replay (7). Then run the agreement check and the pilot.

Out of scope, as before: time-varying wind, depot-bay limits, repeated updates, flight
tests.

## Verification of this plan

Section 1 figures were recomputed on 9 October 2026 from
`results/escalation_study_primary/analysis/variants.csv`, the pass-2 records of the six
re-audited missions (29 open Level-3 and 14 open Level-4 searches) and the 40
larger-mission records. The assumptions in Section 3 were read in `recovery/transfers.py`
(no waiting, energy formula, bay limit) and in the P1 scenarios (`depot_bays = None`, no
earliest times). The recursion in 5.2 was checked against brute force in a scratch
script outside the code folder.

A separate review, which had not seen the design being written, checked eight claims
against the code:

- fastest legs suffice;
- the assumptions that soundness needs;
- the recursion;
- the first-visit relaxation;
- the reload count;
- the shared field;
- the two reductions;
- assignment pruning.

None was wrong. The conditions it set are now in Sections 3, 4, 5.1, 5.2, 5.3 and 5.4.
No other file was changed.
