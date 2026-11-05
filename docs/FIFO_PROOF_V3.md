# FIFO and energy argument for method v3 (B10)

Date: 5 November 2026. Status: draft for supervisor review; gate before B2 is coded.
Scope: straight or polygonal fixed paths in wind that is piecewise constant over
convex polygonal cells and time bins (`wind-benchmark-v3`), with abs(w) < v in every
cell and bin (checked by `continuous.binned.binned_guard`). Plans obey Rule 1 (one
visit per task, all demand mandatory, each demand fits in one load) and Rule 2 (a
UAV leaves each stop as soon as service or preparation ends; never two depot stops
in a row).

## 1. Progress on a fixed path

Split the path at every cell boundary into pieces P_1, ..., P_K (exact rational
cut points). On piece k with displacement d_k and in bin j with wind w, the UAV
flies with heading chosen so that its ground velocity is parallel to d_k. Its
ground speed along d_k is

    g = a + sqrt(v^2 - c^2),  a = w . u,  c = w x u,  u = d_k / |d_k|,

which is positive because abs(w) < v. Let p in [0, K] be progress (piece index
plus fraction flown). Then dp/dt = r(p, t) with r = 1/T_kj on piece k in bin j,
where T_kj is the piece's full duration under bin j's wind,
`displacement_duration(v, w_j, d_k)`. r is positive and piecewise constant.

## 2. Lemma 1 (FIFO)

For departures s1 < s2 along the same path, arrivals satisfy A(s1) <= A(s2).

Proof. Let p1, p2 be the progress functions. At time s2, p1(s2) >= 0 = p2(s2).
Suppose p2 overtakes p1, so there is a first time t* with p2(t*) = p1(t*) and
p2 > p1 just after. At (p1(t*), t*) both share the same state, and r depends only
on (p, t). Over each interval where (piece, bin) is fixed, both solve the same
linear equation from the same state, so they coincide; the switching times are
the same for both (piece boundaries are hit at the same time, bin knots are
global). Hence p2 = p1 after t*, a contradiction. So p2 <= p1 throughout and
A(s2) >= A(s1).

## 3. Lemma 2 (enclosure passes)

Let T^lo_kj <= T_kj <= T^hi_kj be the rational square-root enclosures. The pass
with T^lo from departure s_lo arrives at A_lo, the pass with T^hi from s_hi at
A_hi. For every departure s in [s_lo, s_hi], A_lo <= A(s) <= A_hi.

Proof. The fast pass has rate r^lo = 1/T^lo >= r pointwise in (p, t). By the same
first-crossing argument as Lemma 1 (now the leader has the larger rate at the
shared state), the fast pass from s_lo is never behind the true flight from s;
the slow pass from s_hi is never ahead. Lemma 1 handles the departure shift.
This is `continuous.binned.binned_interval`; `position_at` uses the same two
passes stopped at a time t.

## 4. Lemma 3 (energy)

Power is affine in total mass, P = a + b m, and constant along a leg because the
onboard load only changes at stops. Leg energy is P * D / 3600 Wh with D the true
flight duration.

- **Upper bound (witnesses).** If the departure lies in [s_lo, s_hi], then
  D = A(s) - s <= A_hi - s_lo. The transfer compiler's interval mode
  (`recovery.transfers`, `interval_provider`) keeps the upper time chain and,
  per UAV, the gap to a lower bound of the true time, and charges P * (A_hi - s_lo).
  With D = A_hi - s_hi instead, an earlier departure into slower wind could need
  more energy than charged; this is why the window's lower end is used.
- **Lower bound (exclusions).** D >= l_env(x, y), the envelope lower bound over all
  bins (B1), which holds for every departure time. Proofs charge P_lo * l_env with
  P_lo the power at the payload lower bound of Section 6.

## 5. Lemma 4 (no waiting, and the arrival function alpha)

Rule 2 forbids ground waiting. Even if it were allowed, by Lemma 1 leaving later
never arrives earlier, and by Lemma 3 energy grows only with airborne time (hover
power equals cruise power; Dorling et al.), so waiting never helps timing and the
fastest admissible path is also least-energy for a fixed load. For lower bounds
on a gap from x to y departing at t, B1 uses

    alpha_xy(t) = min over t' >= t of (t' + l_xy(t')),

which is non-decreasing in t, so chaining alpha along a route gives a valid lower
bound on every arrival.

## 6. Dominance in the route check (B2)

Labels carry (time lower bound, energy lower bound, load). A label L1 dominates
L2 at the same node and visited set if t1 <= t2, e1 <= e2 and the remaining
obligations are the same.

- Time: future arrival lower bounds are alpha chains, non-decreasing in the start
  time, so t1 <= t2 keeps every future arrival of L1 at most that of L2.
- Energy: every future charge is P_lo * l_env, which does not depend on the
  departure time. Future energy is therefore the same for both labels and
  e1 <= e2 is preserved.

If energy were charged from the time-dependent bound l_xy(t), a label that
arrives earlier could meet slower wind and be charged more later, and pruning
by (time <=, energy <=) would be unsound. Charging energy only with l_env is the
rule for B2.

## 7. Payload lower bound (Q15)

Rule 1 delivers every remaining task's full demand in one visit. A UAV with
remaining mandatory demand R (packages) and a remaining tasks can make at most
a - 1 further reloads (Rule 2: a depot stop needs a task on each side, except the
final return). With capacity C packages, its onboard load on the current leg is
at least

    max(0, R - C * (a - 1)),

and for an airborne start at least the exact observed onboard load. The route
check uses P_lo = a_u + b_u * (m0 + package mass * that bound). It is weak but
valid; zero is always valid.

## 8. What this does not cover

- Depot bays (coupled preparations) are excluded by `binned_guard`.
- Ground origins other than idle at the depot are excluded, as in v2.
- The verifier (B8) re-derives Lemmas 1-3 in its own code from
  `docs/VERIFIER_SPEC_V3.md`; it does not import this argument's implementation.
