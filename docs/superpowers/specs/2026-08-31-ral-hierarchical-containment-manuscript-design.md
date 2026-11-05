# RA-L Hierarchical Containment Manuscript Rewrite Design

## Status and approved scope

This specification governs a substantive rewrite of the active manuscript on
hierarchical disturbance propagation and minimum-sufficient escalation for
multi-UAV humanitarian relief routing.  The target style is a compact IEEE
Robotics and Automation Letters formulation.

The active manuscript will contain only:

1. the title and keywords;
2. the abstract; and
3. the problem formulation.

No introduction, related-work section, optimization algorithm, experiment,
discussion, or conclusion will be activated.  Existing legacy files remain
unchanged and excluded.  In particular, the rewrite must not revive the
urgency-aware, deprivation-triggered, belief-state, ALNS, or reinforcement-
learning framing.

## Scientific claim boundary

The paper formalizes the relationship

\[
\text{packet update}
\longrightarrow
\text{disturbance propagation on the fixed incumbent suffix}
\longrightarrow
\text{feasibility containment in nested intervention spaces}.
\]

The propagation diagnostic is read-only.  It identifies direct contact,
structural reachability, realized material change, and downstream state
propagation.  It does not construct a repaired plan and does not determine the
minimum intervention level by itself.

The feasibility-required escalation level is an existence-based mathematical
reference.  The current implementation can validate externally supplied
candidates, which yields upper-bound certificates only.  It does not search
an intervention space exhaustively.

A compact performance-aware reference level is included because the title
uses *minimum-sufficient escalation*.  This reference is explicitly labeled
as neither implemented nor empirically evaluated.

## Active source structure

The active LaTeX sources will be:

- `manuscript/main.tex`: IEEEtran shell, title, keywords, and active inputs;
- `manuscript/sections/abstract.tex`: abstract rewritten after the body;
- `manuscript/sections/system_model.tex`: complete problem formulation; and
- `manuscript/SECTION_BY_SECTION_REVISION.md`: diagnoses, rewrite map,
  substantive changes, author checks, and the final consistency table.

The mathematical body remains in `system_model.tex` to avoid unnecessary file
proliferation in a short letter.  It is reorganized into focused subsections.

## Index and information convention

The packet update is indexed by (n+1).  Packet
\(\widehat{\mathcal E}_{n+1}\) arrives at decision epoch (t_{n+1}) and
supersedes \(\widehat{\mathcal E}_{n}\) on any overlapping coverage.  Every
state, residual quantity, commitment mask, decision space, and escalation
level used for the response is indexed by (n+1).

The latest packet is operative on its stated coverage domain
\(\Omega_{n+1}^{E}\).  It is not modeled as an uncertain belief about a
hidden current environment.  Information can be unavailable outside the
received coverage domain.  Non-anticipativity is expressed by

\[
\Pi_{n+1}^{\mathrm{rem}}
=\phi_{n+1}(\mathscr I_0,\ldots,\mathscr I_{n+1}),
\]

with no dependence on later information states.

## Remaining-mission ontology

At (t_{n+1}), the model distinguishes:

- executed history (H_{n+1}), which is a parameter and is absent from the
  decision space;
- the incumbent remaining plan
  \(\bar\Pi_{n+1}^{\mathrm{rem}}\);
- future committed decision components; and
- future mutable decision components.

A candidate remaining plan contains assignment, sequence, path, and
loading/delivery decisions:

\[
\Pi^{\mathrm{rem}}=(\mathcal A,\mathcal S,\mathcal P,\mathcal L).
\]

Travel time, arrival time, energy, battery, and exposure are induced by these
decisions, the current physical state, and the received packet:

\[
\mathcal T
=\Gamma(\mathcal A,\mathcal S,\mathcal P,\mathcal L;
X_{n+1}^{\mathrm{fleet}},\widehat{\mathcal E}_{n+1}).
\]

They are not intervention decisions.  The present model contains no
independently controlled waiting decision.  If one is introduced later, it
must be represented separately rather than hidden inside induced timing.

Commitment is component-specific:

\[
\mathcal C_{n+1}
=(C_{n+1}^{A},C_{n+1}^{S},C_{n+1}^{P},C_{n+1}^{L}).
\]

The committed-component projection must match the incumbent.  A destination
can therefore be committed while its remaining path is mutable.  Emergency
release of an ordinary commitment is a separate safety override and is not
classified as intervention level four.

The master remaining-mission space
\(\mathcal Y_{n+1}^{\mathrm{rem}}\) contains causally valid continuations
anchored at the observed fleet state, defined over residual tasks and
resources, and consistent with commitments.  It is not itself the
hard-feasibility set.

## Residual mission data

Every remaining UAV route starts from its current physical state, represented
by a virtual current-state node or directly by the continuous state.  It does
not restart at the depot unless the UAV is physically there.

Future loading uses remaining depot inventory:

\[
\sum_{u,h}y_{u,h,k}\le I_{k,n+1}^{\mathrm{rem}}.
\]

Residual demand is

\[
d_{ik,n+1}^{\mathrm{rem}}
=\bigl[d_{ik}-q_{ik}^{\mathrm{del}}(t_{n+1})\bigr]_+.
\]

Residual demand bounds future deliveries.  Any mandatory service obligation
must be declared separately as a hard requirement.  Otherwise, unmet
humanitarian demand contributes to service quality rather than being silently
equated with physical infeasibility.

## Environmental status and admissibility

The environmental path-status mapping uses a symbol distinct from the graph
materiality predicate:

\[
\chi_E(P;\widehat{\mathcal E}_{n+1})
\in\{\mathsf{safe},\mathsf{unsafe},\mathsf{unknown}\}.
\]

Unknown means that the received packet does not cover enough of the required
space--time path to classify it.  It neither questions information inside the
coverage domain nor demonstrates physical infeasibility.

Under the declared conservative operating rule,

\[
\operatorname{Adm}(P;\widehat{\mathcal E}_{n+1})=1
\iff
\chi_E(P;\widehat{\mathcal E}_{n+1})=\mathsf{safe}.
\]

Thus an unknown path is operationally inadmissible without being relabeled as
physically unsafe.

## Hard mission feasibility

The hard-feasibility set
\(\mathcal F(\mathscr I_{n+1})\) is separate from intervention scope.  It
contains remaining plans satisfying:

1. current-state anchoring and state continuity;
2. environmental admissibility;
3. wind-dependent traversal and progress;
4. path and active-region constraints;
5. payload capacity and residual inventory;
6. battery, service energy, and reserve constraints;
7. residual-demand upper bounds and any explicitly declared mandatory
   service obligations;
8. hard deadlines and mission horizon, when declared;
9. commitment consistency;
10. safe continuation or return; and
11. non-anticipativity.

The paper calls (k^F) the minimum intervention required to recover hard
mission feasibility.  It does not claim that (k^F) guarantees acceptable
humanitarian service quality.

## Disturbance-propagation diagnostic

The diagnostic evaluates the same incumbent remaining suffix under the
previous and received packets.  It retains the finite typed acyclic dependency
graph, structural reachability, material support, direct environmental
contact, propagated entering-state change, affected legs, and affected tasks.

The environmental status symbol is \(\chi_E\); the vertex-level material
change predicate is renamed \(\mu(v)\) to avoid overloading.  Reporting
tolerances are applied only after graph reachability.

There are no cross-UAV arcs.  The graph diagnoses propagation on the fixed
incumbent continuation.  Sequence and assignment escalation are determined
later by feasibility in the corresponding intervention spaces.

## Reassignment neighborhood

The directly reportable task set is
\(\mathcal I_{n+1}^{\mathrm{aff}}\).  Level three uses an expanded, declared
reassignment set
\(\mathcal I_{n+1}^{\mathrm{reassign}}\), obtained from a task--constraint
incidence graph.  Two tasks are coupled when their mutable decisions occur in
a common nonseparable hard constraint, such as one UAV's residual capacity,
route-time, or energy constraint, or a shared residual-inventory constraint.

The reassignment set is the graph closure of the directly affected set within
the mutable remaining tasks.  It is not expanded by an arbitrary geometric
radius.  If this closure contains every mutable task, levels three and four
may coincide; strict inclusion is not assumed.

## Cumulative intervention spaces

All spaces are subsets of \(\mathcal Y_{n+1}^{\mathrm{rem}}\) and preserve
executed history and component-specific commitments.

- \(\mathcal X_{0,n+1}\): the singleton incumbent remaining decision plan;
  only induced quantities are reevaluated.
- \(\mathcal X_{1,n+1}\): assignment, sequence, and loading/delivery remain
  fixed; mutable path components may change.
- \(\mathcal X_{2,n+1}\): assignment remains fixed; sequence, path, and
  sequence-consistent loading/delivery components may change.
- \(\mathcal X_{3,n+1}\): level-two permissions plus assignment changes for
  tasks in \(\mathcal I_{n+1}^{\mathrm{reassign}}\).
- \(\mathcal X_{4,n+1}\): every mutable assignment, sequence, path, and
  loading/delivery component may change.

The nesting proposition states sufficient assumptions explicitly: common base
domain, invariant executed and committed components, cumulative release of
equality restrictions, and no new restriction at a higher level.  Under these
assumptions,

\[
\mathcal X_{k,n+1}\subseteq\mathcal X_{k+1,n+1}.
\]

Equality between adjacent spaces is permitted.

## Escalation references

The feasibility-required escalation level is

\[
k_{n+1}^{F}
=\min\left\{
k\in\{0,\ldots,4\}:
\mathcal X_{k,n+1}\cap\mathcal F(\mathscr I_{n+1})
\ne\varnothing
\right\}.
\]

If the level-four intersection is empty, the ordinary hierarchy returns
\(\mathsf{MISSION\_INFEASIBLE}\).  A separate safety controller may suspend,
hold, land, return, or invoke commitment override.  No ordinary level is
reported as successful.

The manuscript includes short proofs of:

1. intervention-space nesting;
2. feasibility-containment monotonicity;
3. minimality of \(k_{n+1}^{F}\); and
4. the candidate upper-bound implication.

If an externally supplied candidate
\(\widetilde\Pi_k\in\mathcal X_{k,n+1}\cap
\mathcal F(\mathscr I_{n+1})\), then
\(k_{n+1}^{F}\le k\).  Candidate failure has no converse implication.

## Secondary intervention magnitude

Within the selected level, disruption is measured by a configurable composite
distance

\[
d_{n+1}(\Pi,\bar\Pi)
=\alpha_A d_A+\alpha_S d_S+\alpha_P d_P+\alpha_L d_L,
\]

where each component is a declared nonnegative distance and vanishes exactly
when the corresponding decision component is unchanged.  The path component
must be geometry-sensitive; it is not reduced to a binary changed/unchanged
indicator.  The distance is secondary and is not claimed as a central
contribution or a finalized operational valuation.

## Performance-aware reference

For nonnegative mission-quality cost (J), define

\[
J_{k,n+1}^{\star}
=\inf_{\Pi\in\mathcal X_{k,n+1}\cap
\mathcal F(\mathscr I_{n+1})}
J(\Pi;\mathscr I_{n+1}),
\]

with (J_{k,n+1}^{\star}=+\infty) for an empty feasible intersection.  The
performance-aware reference level is

\[
k_{n+1}^{Q}(\epsilon)
=\min\left\{k:
J_{k,n+1}^{\star}
\le(1+\epsilon)J_{4,n+1}^{\star}
\right\},
\qquad \epsilon\ge0.
\]

The definition is used only when the level-four problem is feasible and has a
finite reference cost.  The manuscript states
\(k_{n+1}^{F}\le k_{n+1}^{Q}(\epsilon)\) and the monotone non-increase of
\(k_{n+1}^{Q}\) with increasing tolerance.  This reference is not implemented
or evaluated in the current phase.

## Writing and output contract

The prose must be compact, formal, and nonpromotional.  Standard mathematical
objects are described as definitions rather than novelty claims.  Claims are
limited to the formal relationship between disturbance propagation and
hierarchical containment.

The abstract is rewritten only after the body and must distinguish diagnosis
from intervention sufficiency.  It contains no invented result, baseline,
metric, or empirical improvement.

The section-by-section revision audit follows the user's requested order but
omits the introduction item by approval.  For each item it provides:

1. a diagnosis of substantive mathematical or writing problems;
2. the location of the complete replacement text in the active LaTeX source;
3. the substantive changes; and
4. author checks where empirical or literature evidence is unavailable.

The final table uses the columns *Issue*, *Original problem*, *Revision*, and
*Why it matters*.

## Verification requirements

Before delivery:

1. every active symbol must be defined before use;
2. notation collisions must be absent;
3. packet, state, residual-data, and escalation indices must be consistent;
4. unknown, unsafe, inadmissible, and infeasible must remain distinct;
5. all five intervention spaces must share the same master domain;
6. all proposition assumptions and proof directions must be explicit;
7. implementation claims must match the current read-only diagnostic and
   candidate checker;
8. the active IEEEtran source must compile twice without unresolved labels,
   overfull boxes, or underfull-box warnings;
9. the final PDF must be rendered and visually inspected page by page; and
10. no legacy urgency-aware or ALNS text may be active.
