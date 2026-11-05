# Mathematical Specification: Packet-Disturbance Dependency Graph and Closure

## Status and scope

This document formalizes the diagnostic mapping

\[
\Delta\widehat{\mathcal E}_{n+1}
\longmapsto
\text{directly contacted constraints}
\longmapsto
\text{downstream state and constraint changes}.
\]

It deliberately stops before repair, neighborhood selection, or optimization.
In particular, it does **not** infer a minimum escalation level from the
closure.  A later formulation may use the closure as an input, but must still
establish the existence of an acceptable plan in each intervention space.

The construction uses standard objects only:

1. two deterministic counterfactual evaluations of one fixed plan suffix;
2. a finite typed directed dependency graph;
3. graph reachability and transitive closure; and
4. the least fixed point of a monotone set operator on a finite powerset.

The word *dependency* means functional or constraint dependency.  It does not
assert statistical or philosophical causality.  Likewise, *disturbance*
means the received difference between consecutive environmental-information
packets, not unobserved environmental truth.

## 1. Indices, information boundary, and conventions

Let

\[
\mathcal U=\{1,\ldots,M\}
\]

be the UAV set and let \(t_n\) be a packet-update decision epoch.  For a
nonnegative integer \(m\), write \([m]:=\{1,\ldots,m\}\), with
\([0]=\varnothing\).  Superscripts
\(q\in\mathcal Q:=\{-,+\}\) distinguish two evaluations:

\[
q=-:\ \widehat{\mathcal E}^{-}=\widehat{\mathcal E}_{n},
\qquad
q=+:\ \widehat{\mathcal E}^{+}=\widehat{\mathcal E}_{n+1}.
\]

The diagnostic information is

\[
\mathscr I_{n+1}^{\mathrm{diag}}
=
\left(
t_n,X_n,\Pi_n^{\mathrm{rem}},
\widehat{\mathcal E}^{-},
\widehat{\mathcal E}^{+}
\right),
\tag{1}
\]

where \(X_n\) is the observed physical mission state and
\(\Pi_n^{\mathrm{rem}}\) is the incumbent remaining plan.  Static mission data
known at time zero, such as node coordinates, declared network geometry, UAV
parameters, and commodity masses, are parameters of (1).  No later packet or
latent environmental truth belongs to \(\mathscr I_{n+1}^{\mathrm{diag}}\).

For any partial quantity, \(\bot\) denotes that a numeric value is not
determined.  Physical infeasibility and lack of information are not identified:

\[
z_{u,r}^{q}\in
\{\mathsf{feasible},\mathsf{infeasible},\mathsf{undetermined}\}.
\tag{2}
\]

The value \(\mathsf{undetermined}\) is used when the received packet does not
cover the required traversal or when an upstream state is unavailable.  The
value \(\mathsf{infeasible}\) is reserved for a demonstrated violation under
the supplied packet.

Ordinary equality denotes exact equality in the mathematical model.  A
separate material-change predicate, defined in (32), uses the project
tolerances appropriate to each reported quantity: time tolerance
\(\varepsilon_t\), energy tolerance \(\varepsilon_E\), state tolerance
\(\varepsilon_x\), and wind-reporting tolerance \(\varepsilon_w\).
Categorical values are compared exactly.  Structural reachability is never
pruned by these reporting tolerances.

## 2. Incumbent remaining suffix

For UAV \(u\), write its ordered remaining leg sequence as

\[
\mathcal R_{u,n}
=
(\ell_{u,1},\ldots,\ell_{u,m_u}).
\tag{3}
\]

Each remaining leg is the record

\[
\ell_{u,r}
=
\left(
i_{u,r},j_{u,r},g_{u,r},\mathbf y_{u,r},\bar t_{u,r}
\right),
\tag{4}
\]

where \(i_{u,r}\) and \(j_{u,r}\) are the origin and destination,
\(g_{u,r}\) is the declared directed polyline, \(\mathbf y_{u,r}\) is the
declared delivery at the destination, and \(\bar t_{u,r}\) is its arrival
deadline.  When no separate deadline is declared,
\(\bar t_{u,r}=T\), the mission horizon.

If UAV \(u\) is airborne at \(t_n\), \(g_{u,1}\) is the immutable committed
remainder beginning at its observed position.  If it is stationary at a
declared stop, \(g_{u,1}\) is the next declared leg.  Completed occurrences
are excluded using the incumbent route cursor; repeated stops are not resolved
by guessing.

The common initial projected state is

\[
x_{u,1}^{-}=x_{u,1}^{+}=x_{u,n}
=
\left(t_n,b_{u,n},\mathbf q_{u,n}\right),
\tag{5}
\]

where \(b_{u,n}\) is battery energy and \(\mathbf q_{u,n}\) is onboard
commodity quantity.  For a not-yet-loaded UAV at the depot, the incumbent
declared load is used in (5), consistent with the current diagnostic contract.

The suffix is fixed in both projections.  Assignment, order, geometry,
delivery quantities, commitment status, and vehicle parameters therefore do
not differ between the two evaluations.

## 3. Packet fields and the environmental difference

For \(q\in\{-,+\}\), represent the received packet by the partial fields

\[
\begin{aligned}
c^{q}(t)&\in\{0,1\},
&&\text{packet coverage},\\
\mathbf w^{q}(t)&\in\mathbb R^2,
&&\text{global east--north wind when }c^q(t)=1,\\
\mathsf H^{q}(\mathbf x,t)&\in
\{\mathsf{clear},\mathsf{soft},\mathsf{hard},\bot_{\mathrm{cov}}\},
&&\text{weather state},\\
\mathsf A^{q}(\mathbf x,t)&\in
\{\mathsf{clear},\mathsf{blocked},\bot_{\mathrm{cov}}\},
&&\text{airspace state},
\end{aligned}
\tag{6}
\]

for location \(\mathbf x\in\mathbb R^2\).  The value
\(\bot_{\mathrm{cov}}\) applies outside the packet coverage interval.  Wind
is obtained by the packet's stated piecewise-linear interpolation.  Weather
and airspace values are induced by the declared polygon geometries and
validity intervals.

The environmental difference is described by the supports

\[
\begin{aligned}
D_c
&=\operatorname{cl}\{t:c^{-}(t)\ne c^{+}(t)\},\\
D_w
&=\operatorname{cl}\left\{t:c^{-}(t)c^{+}(t)=1,
\ \mathbf w^{-}(t)\ne\mathbf w^{+}(t)\right\},\\
D_h
&=\operatorname{cl}\{(\mathbf x,t):
\mathsf H^{-}(\mathbf x,t)\ne\mathsf H^{+}(\mathbf x,t)\},\\
D_a
&=\operatorname{cl}\{(\mathbf x,t):
\mathsf A^{-}(\mathbf x,t)\ne\mathsf A^{+}(\mathbf x,t)\}.
\end{aligned}
\tag{7}
\]

Here \(\operatorname{cl}\) denotes topological closure in the corresponding
time or space--time domain.
Thus a revision within the common packet horizon and a newly covered interval
are both represented.  In particular, \(D_w\) is the temporal support of the
interpolated wind-function difference; it is not merely the set of packet
sample timestamps at which values differ.  The exact comparison in (7) is
intentional: applying \(\varepsilon_w\) at the seed stage could discard a
small upstream change that a downstream equation amplifies beyond its own
reporting tolerance.

Equivalently, the packet comparison may return a finite set of atomic changes

\[
\Delta\widehat{\mathcal E}_{n+1}
=\{\delta_p:p\in[N_{\Delta}]\},
\tag{8}
\]

where each \(\delta\) has a domain, a temporal support, and, for weather or
airspace, a spatial support.  Every nonempty component of (7) must be covered
by at least one atomic record in (8).  Equation (7) is the semantic field-level
difference; (8) is a finite support cover used to construct the graph.  The
cover may be exact or conservative.  A conservative superset can enlarge the
structural closure but cannot create a false negative when support
completeness holds.

## 4. Deterministic two-packet projection

### 4.1 Directed wind kinematics

The dependency construction requires a single declared deterministic
leg-evaluation operator to be used in both packet projections.  Equations
(9)--(14) state the continuous-time traversal model.  A numerical
implementation may approximate this model, but its discretization must then
be declared as part of \(\operatorname{EvalLeg}\); the closure results below
require determinism and common solver semantics, not a particular integration
scheme.

Parameterize the polyline \(g_{u,r}\) by arc length
\(s\in[0,L_{u,r}]\).  On a straight polyline segment, let
\(\mathbf d_{u,r}(s)\) be its unit direction and

\[
\mathbf n_{u,r}(s)
=
\begin{bmatrix}
-d_{u,r,2}(s)\\ d_{u,r,1}(s)
\end{bmatrix}
\tag{9}
\]

its unit normal.  For UAV airspeed \(v_u\), the along-track and cross-track
wind components are

\[
w_{\parallel}^{q}(s,t)
=\mathbf w^{q}(t)^{\mathsf T}\mathbf d_{u,r}(s),
\qquad
w_{\perp}^{q}(s,t)
=\mathbf w^{q}(t)^{\mathsf T}\mathbf n_{u,r}(s).
\tag{10}
\]

The modeled ground progress is

\[
v_{g,u,r}^{q}(s,t)
=
w_{\parallel}^{q}(s,t)
+
\sqrt{v_u^2-\left(w_{\perp}^{q}(s,t)\right)^2}.
\tag{11}
\]

A wind-feasible traversal requires

\[
|w_{\perp}^{q}(s,t)|<v_u,
\qquad
v_{g,u,r}^{q}(s,t)>0
\tag{12}
\]

throughout the traversal.  If \(\xi_{u,r}^{q}(t)\) denotes traveled arc
length, then

\[
\frac{d\xi_{u,r}^{q}(t)}{dt}
=v_{g,u,r}^{q}(\xi_{u,r}^{q}(t),t),
\qquad
\xi_{u,r}^{q}(d_{u,r}^{q})=0,
\tag{13}
\]

The finite polyline is solved segment by segment.  Because the interpolated
wind is continuous on each packet cell and (12) makes the segmentwise
progress strictly positive, the first-passage arrival is well-defined whenever
the destination is reached within packet coverage.

The arrival time is the first \(t\) satisfying
\(\xi_{u,r}^{q}(t)=L_{u,r}\).  The travel time is

\[
\tau_{u,r}^{q}=a_{u,r}^{q}-d_{u,r}^{q}.
\tag{14}
\]

The packet must cover the whole modeled interval
\([d_{u,r}^{q},a_{u,r}^{q}]\).  If it does not, the leg status is
\(\mathsf{undetermined}\), not physically infeasible.

### 4.2 Energy and state recursion

Let \(\mathbf m\) be the commodity unit-mass vector and let

\[
m_{u,r}^{\mathrm{pay},q}=\mathbf m^{\mathsf T}\mathbf q_{u,r}^{q}
\tag{15}
\]

be payload mass.  The current constant-airspeed power model is

\[
P_u(m^{\mathrm{pay}})
=e_{c,u}(m_{0,u}+m^{\mathrm{pay}})v_u,
\tag{16}
\]

so a successfully completed leg consumes

\[
E_{u,r}^{q}=P_u(m_{u,r}^{\mathrm{pay},q})\tau_{u,r}^{q}.
\tag{17}
\]

Define

\[
\iota_{u,r}
=
\mathbb 1
\left\{
j_{u,r}\ne\mathrm{DEPOT},\quad
\mathbf 1^{\mathsf T}\mathbf y_{u,r}>0
\right\}.
\tag{18}
\]

For every reached leg, the incumbent suffix must satisfy
\(\mathbf 0\le\mathbf y_{u,r}\le\mathbf q_{u,r}^{q}\) componentwise.
Failure of this relation is an inconsistent incumbent input, not an
environment-induced feasibility result.

When leg \((u,r)\) is feasible, the deterministic successor equations are

\[
\begin{aligned}
a_{u,r}^{q}
&=d_{u,r}^{q}+\tau_{u,r}^{q},\\
b_{u,r}^{\mathrm{flight},q}
&=b_{u,r}^{q}-E_{u,r}^{q},\\
b_{u,r}^{\mathrm{post},q}
&=b_{u,r}^{\mathrm{flight},q}-\iota_{u,r}e_{v,u},\\
\rho_{u,r}^{q}
&=b_{u,r}^{\mathrm{post},q}-\beta_u,\\
\operatorname{slack}_{u,r}^{q}
&=\bar t_{u,r}-a_{u,r}^{q},\\
d_{u,r+1}^{q}
&=a_{u,r}^{q}+\iota_{u,r}s^{\mathrm{serv}},\\
b_{u,r+1}^{q}
&=b_{u,r}^{\mathrm{post},q},\\
\mathbf q_{u,r+1}^{q}
&=\mathbf q_{u,r}^{q}-\mathbf y_{u,r}.
\end{aligned}
\tag{19}
\]

Here \(e_{v,u}\) is service energy, \(s^{\mathrm{serv}}\) is service time,
and \(\beta_u\) is the configured fixed reserve requirement.  Therefore
\(\rho_{u,r}^{q}\) is a fixed-reserve margin.  It is not a separately
recomputed return-path energy unless the return leg itself is present in the
declared suffix.

The hard conditions represented in the current projection are:

\[
\begin{aligned}
&m_{u,r}^{\mathrm{pay},q}\le W_u^{\max},\\
&b_{u,r}^{\mathrm{flight},q}\ge0,\\
&b_{u,r}^{\mathrm{post},q}\ge0,\\
&\rho_{u,r}^{q}\ge0,\\
&a_{u,r}^{q}+\iota_{u,r}s^{\mathrm{serv}}\le T,\\
&\text{no active hard-weather block on }g_{u,r},\\
&\text{no active airspace block on }g_{u,r},
\end{aligned}
\tag{20}
\]

together with (12) and full packet coverage.  A declared deadline is recorded
through \(\operatorname{slack}_{u,r}^{q}\); whether it is a hard feasibility
condition must be specified by the later planning model.  Soft weather is
recorded as exposure but does not currently alter travel time, energy, or
hard feasibility.

Let \(\mathcal H_{u,r}^{q}\) be the finite collection of hard-condition truth
values for the leg, with values in
\(\{\mathsf T,\mathsf F,\mathsf U\}\), where \(\mathsf U\) denotes unknown.
The aggregate status uses the standard three-valued conjunction rule

\[
z_{u,r}^{q}=
\begin{cases}
\mathsf{infeasible},
&\exists h\in\mathcal H_{u,r}^{q}:h=\mathsf F,\\
\mathsf{feasible},
&\forall h\in\mathcal H_{u,r}^{q}:h=\mathsf T,\\
\mathsf{undetermined},
&\text{otherwise}.
\end{cases}
\]

Thus a demonstrated hard violation is not relabeled as uncertainty merely
because another hard condition is unknown.

If a leg is infeasible or undetermined, its unavailable numerical outputs are
set to \(\bot\), and every later state in that same projection is
\(\bot\).  The other packet projection continues independently.

### 4.3 Order of construction

The two projections are evaluated completely before the explanatory graph is
instantiated.  This order avoids circularity: revised leg times are available
before determining whether a time-supported packet change contacts that leg.

## 5. Typed dependency graph

Define the finite directed graph

\[
\mathcal G_n=(\mathcal V_n,\mathcal A_n,\kappa),
\tag{21}
\]

where \(\kappa\) assigns a type to every vertex.  The vertex set is the
disjoint union

\[
\mathcal V_n
=
\mathcal V_n^{\Delta}
\mathbin{\dot\cup}
\mathcal V_n^{\mathrm{state}}
\mathbin{\dot\cup}
\mathcal V_n^{\mathrm{eval}}
\mathbin{\dot\cup}
\mathcal V_n^{\mathrm{qty}}
\mathbin{\dot\cup}
\mathcal V_n^{\mathrm{stat}}.
\tag{22}
\]

The types are:

- \(\mathcal V_n^{\Delta}\): atomic packet-change records \(\delta\);
- \(\mathcal V_n^{\mathrm{state}}\): the departure time, battery, and payload
  entering each remaining leg;
- \(\mathcal V_n^{\mathrm{eval}}\): one composite deterministic evaluator for
  each remaining leg;
- \(\mathcal V_n^{\mathrm{qty}}\): payload mass, travel time, arrival time,
  flight energy, post-flight battery, post-service battery, reserve margin,
  deadline slack, and other numerical outputs; and
- \(\mathcal V_n^{\mathrm{stat}}\): coverage, wind-progress, weather,
  airspace, payload, battery, reserve, horizon, deadline, aggregate leg
  status, and reason-code outputs.

Each modeled record field is represented by exactly one vertex of exactly one
type.  In particular, the state entering leg \((u,r+1)\) is a state vertex,
not a second copy of a post-state vertex for leg \((u,r)\).

Each non-change vertex \(v\) has two values

\[
\nu^{-}(v),\nu^{+}(v)\in\mathcal Z_v\cup\{\bot\},
\tag{23}
\]

obtained from the two projections.  Fixed plan inputs such as geometry,
deliveries, deadlines, and vehicle parameters label the structural equations;
because they are identical in both projections, they are not disturbance
seeds.

### 5.1 Dependency-edge rule

For non-change vertices \(u,v\), include \((u,v)\in\mathcal A_n\) exactly
when the structural equation defining \(v\) uses \(u\) as an argument.  This
is syntactic functional dependence; it does not depend on the observed sign or
magnitude of a derivative.

The packet-aware traversal calculation is represented by one composite
evaluator vertex

\[
\mathsf{Eval}_{u,r}^{q}
=
\operatorname{EvalLeg}
\left(
g_{u,r},d_{u,r}^{q},m_{u,r}^{\mathrm{pay},q},
\theta_u,\widehat{\mathcal E}^{q}
\right),
\tag{24}
\]

where \(\theta_u\) collects the fixed UAV parameters.  This is the standard
computational-graph representation of an algorithm whose kinematic
integration, packet-coverage test, and active-region test are evaluated
jointly.  It avoids introducing a false algebraic cycle between an unknown
arrival time and the coverage test used to determine whether that arrival can
be computed.

The required parent relations are summarized below.

| Child quantity or condition | Required parents |
|---|---|
| payload mass \(m_{u,r}^{\mathrm{pay}}\) | payload vector \(\mathbf q_{u,r}\) |
| leg-evaluation record \(\mathsf{Eval}_{u,r}\) | departure time, payload mass, fixed geometry, fixed UAV parameters, supplied packet |
| coverage, wind-progress, weather, and airspace status | leg-evaluation record |
| travel time \(\tau_{u,r}\) and flight energy \(E_{u,r}\) | leg-evaluation record |
| arrival time \(a_{u,r}\) | departure time, travel time |
| battery after flight | battery before flight, flight energy |
| battery after service | battery after flight, service indicator and service energy |
| reserve margin \(\rho_{u,r}\) | battery after service, fixed reserve requirement |
| deadline slack \(\operatorname{slack}_{u,r}\) | arrival time, declared deadline |
| leg status \(z_{u,r}\) | all hard condition/status vertices for the leg |
| next departure time | leg status, arrival time, service indicator, service time |
| next battery | leg status, post-service battery |
| next payload | leg status, current payload, declared delivery |

For successive legs of the same UAV, the feasibility-gated recursion in (19)
therefore includes the transition arcs

\[
\begin{aligned}
\{&
(a_{u,r},d_{u,r+1}),
(z_{u,r},d_{u,r+1}),
(b_{u,r}^{\mathrm{post}},b_{u,r+1}),
(z_{u,r},b_{u,r+1}),\\
&
(\mathbf q_{u,r},\mathbf q_{u,r+1}),
(z_{u,r},\mathbf q_{u,r+1})
\}
\subseteq\mathcal A_n .
\end{aligned}
\tag{25}
\]

Fixed service data and declared deliveries label the corresponding transition
equations.  No transition arc is introduced between different UAVs because
the present diagnostic does not project shared depot bays, new loading
decisions, charging decisions, or inventory competition.

### 5.2 Packet-contact arcs

Let \(h^q\) be the validity-horizon endpoint of packet \(q\).  The diagnostic
attribution interval is

\[
I_{u,r}^{q}
=
\begin{cases}
[d_{u,r}^{q},a_{u,r}^{q}],
&d_{u,r}^{q}\ne\bot,\ a_{u,r}^{q}\ne\bot,\\
[d_{u,r}^{q},\max\{d_{u,r}^{q},h^q\}],
&d_{u,r}^{q}\ne\bot,\ a_{u,r}^{q}=\bot,\\
\varnothing,
&d_{u,r}^{q}=\bot.
\end{cases}
\tag{26}
\]

The second case is the current conservative fallback when evaluation does not
return an arrival time; it is an attribution envelope, not a claim that the
vehicle physically traverses until \(h^q\).  Let

\[
I_{u,r}^{\cup}=I_{u,r}^{-}\cup I_{u,r}^{+}.
\tag{27}
\]

For an atomic wind or coverage change \(\delta\), define

\[
\operatorname{contact}(\delta,\ell_{u,r})=1
\iff
T_{\delta}\cap I_{u,r}^{\cup}\ne\varnothing,
\tag{28}
\]

where \(T_\delta\) is its temporal support.  For weather or airspace,

\[
\operatorname{contact}(\delta,\ell_{u,r})=1
\iff
\left(T_{\delta}\cap I_{u,r}^{\cup}\ne\varnothing\right)
\land
\left(\operatorname{im}(g_{u,r})\cap R_{\delta}\ne\varnothing\right),
\tag{29}
\]

where \(R_\delta\) is the union of the before/after polygon support and
\(\operatorname{im}(g)\) is the polyline image.  Equation (29) matches the
current conservative leg-level region rule: spatial intersection and temporal
overlap are required, but exact vehicle position inside the region at each
instant is not reconstructed.

When (28) or (29) holds, add an arc from \(\delta\) to
\(\mathsf{Eval}_{u,r}\) and to the corresponding coverage, wind, weather, or
airspace condition vertex of leg \((u,r)\).

## 6. Direct contact, propagated state, and realized change

These concepts are distinct and are not forced to be mutually exclusive.

### 6.1 Directly contacted legs

The directly contacted leg set is

\[
\mathcal L_{n+1}^{\mathrm{dir}}
=
\left\{
\ell_{u,r}:
u\in\mathcal U,\ r\in[m_u],\
\exists\delta\in\Delta\widehat{\mathcal E}_{n+1},
\ \operatorname{contact}(\delta,\ell_{u,r})=1
\right\}.
\tag{30}
\]

Direct contact describes exposure to a changed packet field.  It does not
require a travel-time, energy, or feasibility change.  For example, a soft
weather revision can contact a leg while leaving its current hard-feasibility
and kinematic outputs unchanged.  If the atomic support cover in (8) is
conservative rather than exact, \(\mathcal L_{n+1}^{\mathrm{dir}}\) is also a
conservative no-false-negative contact set.

### 6.2 Propagated pre-state

For \(r>1\), leg \((u,r)\) has propagated input change when

\[
\operatorname{prop}_{u,r}=1
\iff
\max\left\{
\chi(d_{u,r}),
\chi(b_{u,r}),
\chi(\mathbf q_{u,r})
\right\}=1,
\tag{31}
\]

where \(\chi\) is the typed predicate in (32).  Set
\(\operatorname{prop}_{u,1}=0\) because (5) is common to both projections.

A leg may satisfy both (30) and (31): it can inherit a changed departure state
and also encounter a packet revision itself.  Such a leg has mixed direct and
propagated influence.

### 6.3 Vertex-level change predicate

For every non-change vertex \(v\), define

\[
\chi(v)=
\begin{cases}
1,&\text{exactly one of }\nu^-(v),\nu^+(v)\text{ equals }\bot,\\
1,&\text{both are categorical and unequal},\\
1,&\text{both are scalar and differ by more than }\varepsilon_v,\\
1,&\text{both are vectors and their normed difference exceeds }\varepsilon_v,\\
0,&\text{otherwise}.
\end{cases}
\tag{32}
\]

Here \(\varepsilon_v\) is the reporting tolerance assigned to the type of
vertex \(v\), as specified in Section 1.

For a composite evaluator record, \(\chi(v)=1\) if and only if at least one
of its typed components satisfies (32).  Reason/status vertices ensure that two unavailable numeric projections with
different causes, such as physical blockage and missing packet coverage, are
still distinguished.

## 7. Structural closure and realized impact support

### 7.1 Relevant disturbance seeds

Discard packet changes that contact no remaining leg:

\[
\Delta_{n+1}^{\mathrm{rel}}
=
\left\{
\delta\in\Delta\widehat{\mathcal E}_{n+1}:
\exists u\in\mathcal U,\ \exists r\in[m_u],
\ \operatorname{contact}(\delta,\ell_{u,r})=1
\right\}.
\tag{33}
\]

Let \(\mathcal V_n^{\mathrm{env}}\subseteq\mathcal V_n^{\mathrm{stat}}\)
denote the coverage, wind-progress, weather, and airspace status vertices.
The seed set is defined exactly by

\[
\mathcal S_{n+1}
=
\Delta_{n+1}^{\mathrm{rel}}
\cup
\left\{
v\in\mathcal V_n^{\mathrm{env}}:
\exists\delta\in\Delta_{n+1}^{\mathrm{rel}},
(\delta,v)\in\mathcal A_n
\right\}.
\]

The environmental-status vertices are retained in the seed so that direct
contact remains reportable even when it causes no material numerical change.

### 7.2 Structural closure

Compute structural reachability independently of any numerical reporting
tolerance.  Initialize

\[
\mathcal B_{n+1}^{[0]}=\mathcal S_{n+1}
\tag{34}
\]

and iterate

\[
\mathcal B_{n+1}^{[h+1]}
=
\mathcal B_{n+1}^{[h]}
\cup
\left\{
v\in\mathcal V_n:
\exists v'\in\mathcal B_{n+1}^{[h]}
\text{ with }(v',v)\in\mathcal A_n
\right\}.
\tag{35}
\]

Denote the set operator on the right-hand side of (35) by
\(\Psi_{n+1}\).  The structural disturbance closure is

\[
\begin{aligned}
\mathcal C_{n+1}^{\mathrm{str}}
&=
\bigcup_{h\ge 0}\mathcal B_{n+1}^{[h]} \\
&=
\operatorname{Reach}_{\mathcal G_n}(\mathcal S_{n+1}) \\
&=
\operatorname{lfp}\!\left(\Psi_{n+1};\mathcal S_{n+1}\right),
\end{aligned}
\tag{36}
\]

where \(\operatorname{Reach}_{\mathcal G_n}(S)\) contains \(S\) itself and
every vertex reachable from a member of \(S\) by a directed path of positive
length.  The notation
\(\operatorname{lfp}(\Psi_{n+1};\mathcal S_{n+1})\) denotes the least fixed
point of \(\Psi_{n+1}\) among sets containing \(\mathcal S_{n+1}\).

It is a conservative set of quantities that can depend on the contacted
packet changes according to the declared structural equations.  It does not
claim that every reachable value actually changed in this update.

### 7.3 Realized material-change support

The realized material-change support contains the structurally reachable
non-change vertices whose paired projections differ according to the typed
predicate (32).  Its operational subset excludes environmental-input
vertices.  This distinction prevents a changed environmental condition from
being counted, by itself, as a changed operational consequence.  The
reportable vertex set additionally retains the direct seeds:

\[
\begin{aligned}
\mathcal V_{n+1}^{\mathrm{mat}}
&=
\left\{
v\in
\mathcal C_{n+1}^{\mathrm{str}}\setminus\mathcal V_n^{\Delta}:
\chi(v)=1
\right\},\\
\mathcal V_{n+1}^{\mathrm{op}}
&=
\mathcal V_{n+1}^{\mathrm{mat}}\setminus\mathcal V_n^{\mathrm{env}},\\
\mathcal V_{n+1}^{\mathrm{rep}}
&=
\mathcal S_{n+1}\cup\mathcal V_{n+1}^{\mathrm{mat}}.
\end{aligned}
\tag{37}
\]

The order in (34)--(37) is essential: reachability is computed first and the
typed materiality predicate is applied second.  Filtering an intermediate
vertex out of a propagation path merely because its own change is below its
reporting tolerance would be unsound; a downstream structural equation may
amplify that change beyond the downstream tolerance.  The seed vertices
remain present even when a contacted soft condition produces no downstream
material difference.  Only \(\mathcal C_{n+1}^{\mathrm{str}}\) is a closure
in the graph-theoretic sense; the remaining sets in (37) are filtered
supports and are not asserted to satisfy closure-operator axioms.

### 7.4 Reportable affected legs and tasks

For a leg \(\ell_{u,r}\), let \(V(\ell_{u,r})\) be all of its state,
evaluation, numerical-output, and status vertices.  The reportable
affected-leg set is

\[
\mathcal L_{n+1}^{\mathrm{aff}}
=
\left\{
\ell_{u,r}:
u\in\mathcal U,\ r\in[m_u],\
V(\ell_{u,r})\cap
\mathcal V_{n+1}^{\mathrm{rep}}
\ne\varnothing
\right\}.
\tag{38}
\]

For unambiguous reporting, define the three binary flags

\[
\eta_{u,r}^{\mathrm{dir}}
=\mathbb 1\{\ell_{u,r}\in\mathcal L_{n+1}^{\mathrm{dir}}\},
\qquad
\eta_{u,r}^{\mathrm{prop}}=\operatorname{prop}_{u,r},
\qquad
\eta_{u,r}^{\mathrm{mat}}=\mathbb 1\!\left\{
V(\ell_{u,r})\cap\mathcal V_{n+1}^{\mathrm{op}}\ne\varnothing
\right\}.
\]

Thus
\((\eta^{\mathrm{dir}},\eta^{\mathrm{prop}},\eta^{\mathrm{mat}})
=(1,0,1)\) is direct-only material influence, \((0,1,1)\) is
propagated-only material influence, and \((1,1,1)\) is mixed influence.
The pair \((\eta^{\mathrm{dir}},\eta^{\mathrm{mat}})=(1,0)\) denotes direct
contact without a material modeled change.  These are diagnostic labels, not
intervention decisions.

Let \(\mathcal I_n^{\mathrm{rem}}\) denote the uncommitted remaining task set.
An affected task set can be obtained without proposing a reassignment:

\[
\mathcal I_{n+1}^{\mathrm{aff}}
=
\mathcal I_n^{\mathrm{rem}}
\cap
\left\{
i:
\exists\ell_{u,r}\in\mathcal L_{n+1}^{\mathrm{aff}}
\text{ with }i\in\{i_{u,r},j_{u,r}\}
\right\}
\setminus\{\mathrm{DEPOT}\}.
\tag{39}
\]

Equation (39) identifies tasks incident to affected suffix legs.  It does not
state that their UAV assignments must change.

## 8. Standard properties

The properties below use the following standing assumptions, cited where
needed:

- **A1 (finiteness):** every remaining suffix, packet record, polyline, and
  environmental-region list is finite;
- **A2 (common deterministic semantics):** both projections use identical
  non-packet inputs and the same deterministic \(\operatorname{EvalLeg}\);
- **A3 (support and contact completeness):** (8) covers every semantic packet
  difference in (7), and every changed packet value queried by an evaluator
  induces the corresponding packet arc;
- **A4 (parent completeness):** every non-packet argument of every structural
  equation is represented by a parent vertex or an identical fixed label; and
- **A5 (diagnostic separability):** no projected shared-resource or cross-UAV
  dependency is present.  This assumption is used only in Proposition 6.

### Proposition 1: finiteness and termination

For a finite remaining suffix and a finite packet-transition record,
\(\mathcal G_n\) is finite.  Iteration (35) stabilizes after at most
\(|\mathcal V_n|\) strict set expansions and has a unique least fixed point
among subsets of \(\mathcal V_n\) that contain \(\mathcal S_{n+1}\).

**Justification.**  The operator in (35) is monotone and inflationary on the
finite lattice \(2^{\mathcal V_n}\).  Every strict iteration adds at least one
previously absent vertex, so more than \(|\mathcal V_n|\) strict expansions
are impossible.

### Proposition 2: acyclicity of the fixed-suffix graph

After the two projections and contact arcs have been instantiated,
\(\mathcal G_n\) is a directed acyclic graph when vertices are ordered by:

1. packet-change roots;
2. leg index \(r\); and
3. within-leg order: entering state and payload mass, composite leg
   evaluation, raw evaluator outputs, derived numerical quantities,
   individual condition statuses, aggregate leg status, successor state.

**Justification.**  All within-leg edges follow the structural equations in
that order, and every cross-leg edge points from index \(r\) to \(r+1\).
There are no cross-UAV edges in the present diagnostic.  Consequently, the
same closure may be computed by one topological pass; fixed-point notation is
retained because it is the standard definition of closure and remains valid
if shared-resource vertices are added later.

### Proposition 3: structural invariance outside the closure

Under A2--A4, if a vertex is not reachable from
\(\mathcal S_{n+1}\), its two projected values are equal:

\[
v\notin\mathcal C_{n+1}^{\mathrm{str}}
\quad\Longrightarrow\quad
\nu^-(v)=\nu^+(v).
\tag{40}
\]

**Justification.**  Proceed in a topological order.  Root inputs outside the
packet are identical by construction.  A nonreachable vertex has no changed
packet ancestor, so all arguments of its deterministic structural equation
are identical in the two projections; its output is therefore identical.

### Proposition 4: exact support of material modeled changes

Under the same completeness and common-input assumptions as Proposition 3,

\[
\mathcal V_{n+1}^{\mathrm{mat}}
=
\left\{
v\in\mathcal V_n\setminus\mathcal V_n^{\Delta}:\chi(v)=1
\right\}.
\]

**Justification.**  Inclusion from left to right follows directly from (37).
For the reverse inclusion, \(\chi(v)=1\) implies
\(\nu^-(v)\ne\nu^+(v)\).  The contrapositive of (40) therefore gives
\(v\in\mathcal C_{n+1}^{\mathrm{str}}\), after which (37) gives
\(v\in\mathcal V_{n+1}^{\mathrm{mat}}\).

This is a soundness statement, not a claim that every structurally reachable
vertex changes.  Cancellation and inactive constraints may make
\(\chi(v)=0\).

### Proposition 5: non-anticipativity

There exist deterministic mappings \(F^{\mathrm{str}}\),
\(F^{\mathrm{mat}}\), and \(F^{\mathrm{rep}}\) such that the closure and
support sets in (36)--(37) equal the corresponding mapping evaluated at
\(\mathscr I_{n+1}^{\mathrm{diag}}\) in (1).  Consequently, they are
unchanged by modifying packets issued after \(t_n\) or latent truth values
while keeping (1) fixed.

**Justification.**  Both projections, all contact tests, graph values, and
closure iterations use only the arguments listed in (1) and static mission
data.

### Proposition 6: fleet separability of the present diagnostic

With no shared-resource projection vertices,

\[
\mathcal V_{n+1}^{\mathrm{rep}}
=
\bigcup_{u\in\mathcal U}
\mathcal V_{u,n+1}^{\mathrm{rep}},
\tag{41}
\]

Here \(\mathcal V_{u,n+1}^{\mathrm{rep}}\) is computed on the subgraph
consisting of UAV \(u\)'s indexed vertices together with the packet-change
seeds that contact its suffix.  The union need not be disjoint because one
packet-change seed may contact more than one UAV.

A change on UAV \(u\)'s suffix cannot propagate into UAV \(v\)'s suffix
for \(u\ne v\).

This is a property of the diagnostic boundary, not a general property of the
later routing problem.  Fleet coupling enters only when depot capacity,
inventory, task coverage, or reassignment constraints are introduced in the
planning formulation.

## 9. Boundary to hierarchical escalation

Conditional on \((t_n,X_n,\Pi_n^{\mathrm{rem}})\) and the static mission
data, the diagnostic establishes the deterministic mapping

\[
\begin{aligned}
\Delta\widehat{\mathcal E}_{n+1}
&\longmapsto
\mathcal S_{n+1}
\longmapsto
\mathcal C_{n+1}^{\mathrm{str}}
\longmapsto
\mathcal V_{n+1}^{\mathrm{mat}},\\
\mathcal V_{n+1}^{\mathrm{mat}}
&\longmapsto
\mathcal V_{n+1}^{\mathrm{op}},\\
(\mathcal S_{n+1},\mathcal V_{n+1}^{\mathrm{mat}})
&\longmapsto
\mathcal V_{n+1}^{\mathrm{rep}}
\longmapsto
\mathcal L_{n+1}^{\mathrm{aff}}
\longmapsto
\mathcal I_{n+1}^{\mathrm{aff}}.
\end{aligned}
\tag{42}
\]

The construction through (42) does not define an escalation level
\(k^\star\).  That quantity requires a separate recovery model.  In
particular:

- a directly blocked leg does not prove that path-only repair is feasible;
- downstream timing changes do not prove that the task sequence must change;
- an affected task does not prove that its UAV assignment must change; and
- failure of one heuristic candidate does not prove that an intervention
  space contains no feasible plan.

The later optimization must define the nested intervention spaces and test
whether an acceptable plan exists in each space.  The closure may restrict or
prioritize that search only after the required soundness relationship is
proved.

## 10. Correspondence with the current code

The current `env.diagnostics.diagnose_environmental_packet_update`
implementation realizes the diagnostic contract through (42) by providing:

1. the information boundary (1) and remaining-suffix extraction (3)--(5);
2. two deterministic packet projections using common leg-evaluation and
   suffix-state-update relations;
3. a support-complete finite representation of changed coverage and changed
   interpolated wind over the fixed diagnostic horizon;
4. independent direct-contact and propagated-input flags, including mixed
   influence on the same leg;
5. feasible, infeasible, and undetermined projection states;
6. the explicit acyclic dependency graph, structural closure, material,
   operational, and reportable supports; and
7. affected-leg and affected-task reports without changing the incumbent
   plan.

The packet comparison uses a numerical equality tolerance only to suppress
machine-arithmetic noise at interpolation endpoints.  It does not use the
reporting tolerances in (30) to remove structural seeds.  Those typed
tolerances are applied only after structural reachability has been computed.

Three modeling boundaries remain and must be stated explicitly before the
simulation study:

1. **Cross-UAV coupling.** The present diagnostic contains no shared fleet,
   depot-capacity, inventory, or task-assignment constraints.  It therefore
   cannot establish assignment propagation across UAVs.
2. **Traversal solver.** Equations (13)--(14) give the continuous-time
   physical reference, whereas the current evaluator uses midpoint-constant
   wind over packet-defined temporal cells.  The study must either adopt this
   discrete operator as \(\operatorname{EvalLeg}\) or implement and validate
   a solver for (13); the two are not mathematically identical.
3. **Recovery boundary.** The graph diagnoses disturbance propagation.  It
   neither constructs a repaired plan nor determines an escalation level.

## 11. Excluded claims

This specification does not claim:

- that every contacted leg requires repair;
- that every changed downstream leg requires sequence modification;
- that every affected task requires reassignment;
- that the closure is a minimal repair set;
- that a particular escalation level is feasible;
- that the graph provides statistical causal identification; or
- that future packet conditions are predicted.

Its sole claim is that, under the stated fixed-plan projection model, the
construction precisely and non-anticipatively distinguishes quantities that
are structurally reachable from the received packet difference from quantities
that materially differ between the two packet-conditioned projections.
