# RA-L Hierarchical Containment Manuscript Rewrite Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the active title, abstract, and problem formulation into a mathematically consistent RA-L formulation of disturbance propagation and minimum-sufficient escalation.

**Architecture:** Keep the active paper compact: `main.tex` supplies the IEEEtran shell, `abstract.tex` is rewritten last, and `system_model.tex` contains the complete mathematical body in a dependency-respecting subsection order.  Add a companion audit that maps each requested diagnosis to the complete replacement source and records the final notation and claim checks.  Legacy introduction, ALNS, urgency-aware, experiment, discussion, and conclusion sources remain inactive and unchanged.

**Tech Stack:** IEEEtran LaTeX, AMS mathematics packages, MiKTeX `pdflatex`, Poppler PDF rendering, Python/pytest for implementation-regression checks.

**Spec:** `docs/superpowers/specs/2026-08-31-ral-hierarchical-containment-manuscript-design.md`

## Global Constraints

- Target venue and style: compact IEEE Robotics and Automation Letters prose.
- Active content: title, keywords, abstract, and problem formulation only; no introduction.
- The latest received packet is operative within its stated coverage until superseded.
- Unknown environmental status is distinct from unsafe status, infeasibility, and operational inadmissibility.
- Every update-response construct uses the index (n+1) consistently.
- Executed history is a parameter, not a frozen optimization variable.
- Commitments are component-specific and precede intervention scope.
- Timing is induced; the current formulation contains no independently controlled waiting decision.
- Residual inventory and residual demand replace initial quantities in online constraints.
- All intervention spaces share one master remaining-mission domain and preserve commitments.
- The propagation graph remains a read-only, within-UAV incumbent-suffix diagnostic.
- (k^F) is existence-based hard-feasibility escalation; candidate failure is not a set-infeasibility certificate.
- (k^Q(\epsilon)) is a compact unimplemented reference definition.
- Do not activate or rewrite legacy urgency-aware, deprivation-triggered, belief-state, ALNS, RL, experiment, discussion, or conclusion sources.
- Preserve the existing dirty working tree; do not stage, commit, restore, or delete unrelated files.

---

### Task 1: Establish the active paper shell and terminology

**Files:**
- Modify: `D:/Post-disaster Logistics/manuscript/main.tex`

**Interfaces:**
- Consumes: the approved scope and terminology from the design specification.
- Produces: the final title, keywords, and active input order used by every later task.

- [ ] **Step 1: Audit the current shell**

Run:

```powershell
rg -n "documentclass|title|IEEEkeywords|input\{" "D:/Post-disaster Logistics/manuscript/main.tex"
```

Expected: `IEEEtran` journal class; active inputs only for `abstract.tex` and `system_model.tex`.

- [ ] **Step 2: Replace the title and keywords**

Use the approved title:

```latex
\title{Hierarchical Disturbance Propagation and Minimum-Sufficient Escalation
for Multi-UAV Relief Routing Under Short-Horizon Environmental Updates}
```

Use keywords centered on the contribution:

```latex
\begin{IEEEkeywords}
multi-UAV routing, environmental updates, disturbance propagation,
hierarchical containment, intervention scope, humanitarian logistics
\end{IEEEkeywords}
```

Keep `\input{sections/abstract}` followed by
`\input{sections/system_model}`.  Do not activate `introduction.tex` or any
other legacy source.

- [ ] **Step 3: Verify the active-input boundary**

Run:

```powershell
rg -n "^[^%]*\\input\{" "D:/Post-disaster Logistics/manuscript/main.tex"
```

Expected: exactly two active inputs, `sections/abstract` and
`sections/system_model`.

### Task 2: Rewrite the information model and remaining-mission domain

**Files:**
- Modify: `D:/Post-disaster Logistics/manuscript/sections/system_model.tex`

**Interfaces:**
- Consumes: the title terminology and update index (n+1).
- Produces: symbols used by feasibility, propagation, and escalation:
  (\mathscr I_{n+1}), (H_{n+1}),
  (\bar\Pi_{n+1}^{\mathrm{rem}}),
  (\mathcal C_{n+1}), and
  (\mathcal Y_{n+1}^{\mathrm{rem}}).

- [ ] **Step 1: Replace the opening problem statement**

State the research question directly: when a packet update invalidates the
incumbent continuation, which cumulative intervention space is the first to
contain a hard-feasible remaining mission?  State that environmental severity
and intervention scope are not equivalent.

- [ ] **Step 2: Define the operative packet convention**

Introduce the packet pair

```latex
\widehat{\mathcal E}_{n}\longrightarrow
\widehat{\mathcal E}_{n+1}
```

and coverage domain (\Omega_{n+1}^{E}\).  State that the received packet is
operative on that domain until superseded.  Define non-anticipativity as

```latex
\Pi_{n+1}^{\mathrm{rem}}
=\phi_{n+1}(\mathscr I_0,\ldots,\mathscr I_{n+1}).
```

Do not use `latent truth`, `uncertain current forecast`, or `belief` in the
online decision model.

- [ ] **Step 3: Define executed, committed, and mutable components**

Define executed history (H_{n+1}) as a parameter.  Define the incumbent
remaining plan and generic candidate by

```latex
\bar\Pi_{n+1}^{\mathrm{rem}},
\qquad
\Pi^{\mathrm{rem}}=(\mathcal A,\mathcal S,\mathcal P,\mathcal L).
```

Define a disjoint partition of the complete mission-decision index set into
done, committed, and mutable components.  Explicitly remove the done set from
the candidate decision space.

- [ ] **Step 4: Define component-specific commitments**

Introduce

```latex
\mathcal C_{n+1}
=(C_{n+1}^{A},C_{n+1}^{S},C_{n+1}^{P},C_{n+1}^{L})
```

and the projection equality

```latex
\rho_{\mathcal C_{n+1}}(\Pi^{\mathrm{rem}})
=\rho_{\mathcal C_{n+1}}(\bar\Pi_{n+1}^{\mathrm{rem}}).
```

Explain that a destination can remain committed while its path is mutable.
State that hard safety override has priority over ordinary commitment and is
outside the ordinary levels (0,\ldots,4).

- [ ] **Step 5: Define induced timing**

Use

```latex
\mathcal T
=\Gamma(\mathcal A,\mathcal S,\mathcal P,\mathcal L;
X_{n+1}^{\mathrm{fleet}},\widehat{\mathcal E}_{n+1}).
```

State that travel times, arrivals, energy, battery, and exposure may change at
level zero without constituting an intervention.

- [ ] **Step 6: Define the master remaining-mission space**

Define (\mathcal Y_{n+1}^{\mathrm{rem}}) using current-state anchoring,
residual-mission consistency, and the commitment projection equality.  State
that it is a causal base domain, not the hard-feasibility set.

- [ ] **Step 7: Run a terminology and index audit**

Run:

```powershell
rg -n -i "latent truth|belief|uncertain current|partially observed|I\^0|initial inventory" "D:/Post-disaster Logistics/manuscript/sections/system_model.tex"
```

Expected: no use of these terms in the active online formulation.

### Task 3: Formalize residual resources, environmental status, and hard feasibility

**Files:**
- Modify: `D:/Post-disaster Logistics/manuscript/sections/system_model.tex`

**Interfaces:**
- Consumes: (\mathscr I_{n+1}), the current fleet state,
  (\mathcal Y_{n+1}^{\mathrm{rem}}), and the received packet.
- Produces: residual quantities, (\chi_E), `Adm`, induced trajectory
  evaluation, and (\mathcal F(\mathscr I_{n+1})).

- [ ] **Step 1: Anchor routes at the current physical state**

Define each remaining route as

```latex
r_{u,n+1}
=(v_{u,n+1}^{\mathrm{cur}},i_{u,1},\ldots,i_{u,m_u},v_0),
```

where (v_{u,n+1}^{\mathrm{cur}}) is a virtual node carrying the observed
position, time, battery, and payload.  Clarify that this node equals the depot
only when the UAV is physically at the depot.

- [ ] **Step 2: Replace initial resource accounting with residual accounting**

Define

```latex
d_{ik,n+1}^{\mathrm{rem}}
=\bigl[d_{ik}-q_{ik}^{\mathrm{del}}(t_{n+1})\bigr]_+,
```

and constrain future loading by

```latex
\sum_{u,h}y_{u,h,k}\le I_{k,n+1}^{\mathrm{rem}}.
```

Use residual demand as an upper bound on future service.  Distinguish any
declared mandatory minimum service from service-quality optimization.

- [ ] **Step 3: Define environmental status independently of admissibility**

Introduce

```latex
\chi_E(P;\widehat{\mathcal E}_{n+1})
\in\{\mathsf{safe},\mathsf{unsafe},\mathsf{unknown}\}.
```

Define `unknown` only as insufficient packet coverage.  Under the conservative
policy, define

```latex
\operatorname{Adm}(P;\widehat{\mathcal E}_{n+1})=1
\iff
\chi_E(P;\widehat{\mathcal E}_{n+1})=\mathsf{safe}.
```

- [ ] **Step 4: Retain the directed wind and energy model with correct numerical semantics**

Keep the directed along-track/cross-track ground-speed relation and the
continuous-time travel relation as a physical reference.  State that the
current evaluator uses midpoint-constant wind on packet-defined temporal
cells and does not claim an exact continuous-time solution.

- [ ] **Step 5: Define the complete hard-feasibility set**

Define (\mathcal F(\mathscr I_{n+1})) separately from intervention spaces.
Include current-state continuity, environmental admissibility, wind progress,
hard-region avoidance, payload, residual inventory, battery, reserve, horizon,
hard deadlines when declared, commitment consistency, safe continuation or
return, and non-anticipativity.

State that absence of declared service minima means hard feasibility does not
guarantee acceptable humanitarian service quality.

- [ ] **Step 6: Audit status semantics**

Run:

```powershell
rg -n -i "unknown.*infeasible|infeasible.*unknown|coverage.*hard feasibility failure" "D:/Post-disaster Logistics/manuscript/sections/system_model.tex"
```

Expected: no sentence equates unknown environmental status with demonstrated
physical infeasibility.

### Task 4: Rebuild the disturbance-propagation diagnostic and affected sets

**Files:**
- Modify: `D:/Post-disaster Logistics/manuscript/sections/system_model.tex`

**Interfaces:**
- Consumes: the fixed incumbent suffix, previous and received packets, induced
  timing, and the path evaluator.
- Produces: the typed graph, structural closure, material support,
  (\mathcal I_{n+1}^{\mathrm{aff}}), and
  (\mathcal I_{n+1}^{\mathrm{reassign}}).

- [ ] **Step 1: Preserve the two-packet fixed-suffix projection**

Evaluate the identical incumbent suffix under
(\widehat{\mathcal E}_{n}) and
(\widehat{\mathcal E}_{n+1}).  Retain independent feasible, infeasible, and
undetermined projection states.

- [ ] **Step 2: Preserve the finite typed dependency graph**

Define packet-change, environmental, state, evaluator, quantity, and status
vertices.  Define arcs by syntactic functional dependence and state that the
graph contains no cross-UAV arc.

- [ ] **Step 3: Separate reachability from realized change**

Keep

```latex
\mathcal C_{n+1}^{\mathrm{str}}
=\operatorname{Reach}_{\mathcal G_{n+1}}(\mathcal S_{n+1})
```

and rename the material predicate from (\chi(v)) to (\mu(v)).  Define
material, operational-material, and reportable supports.  State that typed
tolerances are applied after reachability.

- [ ] **Step 4: Define independent influence flags and affected legs**

Keep direct contact, propagated entering-state change, and operational
material change as independent flags.  Preserve mixed direct-plus-propagated
influence.

- [ ] **Step 5: Define the reassignment coupling closure**

Define a bipartite task--constraint incidence graph for active nonseparable
hard constraints.  Project it to a task-coupling graph and set

```latex
\mathcal I_{n+1}^{\mathrm{reassign}}
=\operatorname{Reach}_{\mathcal G_{n+1}^{\mathrm{task}}}
(\mathcal I_{n+1}^{\mathrm{aff}})
\cap\mathcal I_{n+1}^{\mathrm{mut}}.
```

State that this closure may equal the complete mutable set and that it is a
reassignment neighborhood, not evidence that every included task must move.

- [ ] **Step 6: State the diagnostic boundary**

Use the exact claim: disturbance propagation diagnoses consequences;
containment is determined by the existence of a feasible plan inside an
intervention space.

### Task 5: Rebuild the cumulative intervention hierarchy

**Files:**
- Modify: `D:/Post-disaster Logistics/manuscript/sections/system_model.tex`

**Interfaces:**
- Consumes: (\mathcal Y_{n+1}^{\mathrm{rem}}), the incumbent decisions,
  component masks, and (\mathcal I_{n+1}^{\mathrm{reassign}}).
- Produces: (\mathcal X_{0,n+1},\ldots,\mathcal X_{4,n+1}) and their
  cumulative permissions.

- [ ] **Step 1: Define level zero as decision retention**

Set

```latex
\mathcal X_{0,n+1}=\{\bar\Pi_{n+1}^{\mathrm{rem}}\}.
```

Explain that all induced quantities are reevaluated under the new packet.

- [ ] **Step 2: Define path repair**

At level one, fix assignment, sequence, and loading/delivery decisions to the
incumbent on all mutable components; permit only mutable path geometry to
change.

- [ ] **Step 3: Define sequence repair**

At level two, fix assignment; permit mutable sequence, path, and
sequence-consistent loading/delivery decisions to change.

- [ ] **Step 4: Define partial reassignment**

At level three, retain all level-two permissions and permit assignment changes
only for tasks in (\mathcal I_{n+1}^{\mathrm{reassign}}).

- [ ] **Step 5: Define unrestricted remaining-mission reoptimization**

At level four, permit every mutable assignment, sequence, path, and
loading/delivery component to change.  Keep executed history absent and
committed components fixed.

- [ ] **Step 6: Check that every level controls all genuine decisions**

Verify that assignment, sequence, path, and loading/delivery are either fixed
or explicitly released at every level.  Timing must appear only as an induced
mapping.

### Task 6: Add containment propositions and escalation references

**Files:**
- Modify: `D:/Post-disaster Logistics/manuscript/sections/system_model.tex`

**Interfaces:**
- Consumes: the nested intervention spaces and hard-feasibility set.
- Produces: formal nesting, monotonicity, minimality, candidate certification,
  global infeasibility, secondary distance, and (k^Q(\epsilon)).

- [ ] **Step 1: State assumptions for nesting**

State assumptions A1--A4: common master domain, invariant done/committed
components, cumulative relaxation, and no new higher-level restriction.

- [ ] **Step 2: Add the nesting proposition and proof**

Prove

```latex
\mathcal X_{k,n+1}\subseteq\mathcal X_{k+1,n+1},
\qquad k=0,\ldots,3,
```

by showing that every equality restriction retained at level (k+1) is also
present at level (k), while level (k+1) removes at least no permission.
Do not claim strict inclusion.

- [ ] **Step 3: Add feasibility-containment monotonicity**

Derive that a nonempty feasible intersection at level (k) implies a nonempty
intersection at every higher level.

- [ ] **Step 4: Define and characterize (k_{n+1}^{F})**

Use

```latex
k_{n+1}^{F}=\min\{k:\mathcal X_{k,n+1}
\cap\mathcal F(\mathscr I_{n+1})\ne\varnothing\}.
```

State and prove the minimality conditions for the selected level.

- [ ] **Step 5: Add the global-infeasibility outcome**

If the level-four feasible intersection is empty, return
`\mathsf{MISSION\_INFEASIBLE}` and pass control to a separate safety action.
Do not call commitment override level four.

- [ ] **Step 6: Add candidate certification**

Prove that a feasible supplied candidate at level (k) implies
(k_{n+1}^{F}\le k).  State explicitly that failed candidate evaluation has
no converse set-emptiness implication.

- [ ] **Step 7: Replace simple Hamming disruption with a configurable metric**

Define

```latex
d_{n+1}=\alpha_A d_A+\alpha_S d_S+\alpha_P d_P+\alpha_L d_L,
```

with nonnegative component distances and a geometry-sensitive path term.
Use it only after the intervention level has been selected.

- [ ] **Step 8: Add the compact performance-aware reference**

Define (J_{k,n+1}^{\star}), the feasibility-qualified containment indicator,
and (k_{n+1}^{Q}(\epsilon)).  State the assumptions (J\ge0), finite
level-four reference, and (\epsilon\ge0).  Establish
(k_{n+1}^{F}\le k_{n+1}^{Q}(\epsilon)) and monotone non-increase with
increasing tolerance.  Label the definition as unimplemented and unevaluated.

### Task 7: Rewrite the abstract after the mathematical body

**Files:**
- Modify: `D:/Post-disaster Logistics/manuscript/sections/abstract.tex`

**Interfaces:**
- Consumes: the final definitions and claim boundary from `system_model.tex`.
- Produces: a compact abstract consistent with every active body claim.

- [ ] **Step 1: Draft the abstract in nine moves**

Cover operational motivation, limitation of full replanning, central question,
operative packet convention, fixed-suffix propagation graph, nested
intervention spaces, existence-based (k^F), distinction between propagation
and containment, and current implementation boundary.

- [ ] **Step 2: Exclude unsupported claims**

Do not claim novelty priority, empirical superiority, real-time performance,
or successful optimization.  State that (k^Q(\epsilon)) is a reference
definition only if mentioned.

- [ ] **Step 3: Check abstract/body terminology**

Run:

```powershell
rg -n -i "repair layer|planning layer|severity class|belief|latent|urgenc|ALNS|reinforcement" "D:/Post-disaster Logistics/manuscript/sections/abstract.tex"
```

Expected: none of the inconsistent or legacy terms.

### Task 8: Produce the requested section-by-section revision audit

**Files:**
- Create: `D:/Post-disaster Logistics/manuscript/SECTION_BY_SECTION_REVISION.md`

**Interfaces:**
- Consumes: every final active LaTeX section and the user's ordered checklist.
- Produces: the requested diagnosis/rewrite/change record and final issue
  table.

- [ ] **Step 1: Follow the requested order without an introduction item**

Create entries for title/terminology, problem statement, information state,
remaining mission, decision partition, environmental evaluation, hard
feasibility, propagation, affected sets, hierarchy, nesting, containment,
(k^F), global infeasibility, candidate certification, intervention
magnitude, (k^Q), abstract, and notation audit.

- [ ] **Step 2: Use the A/B/C structure for every entry**

For each entry provide:

```markdown
### A. Diagnose
[Only substantive issues]

### B. Rewrite
[Exact active source file and heading containing the complete replacement]

### C. Major changes
[Only mathematical or scientific-writing changes]
```

The complete replacement text is the active LaTeX source; do not duplicate it
into a second manuscript that can drift out of sync.

- [ ] **Step 3: Add author checks**

State that literature novelty, experimental performance, and the operational
calibration of (d_{n+1}) remain unverified.  Do not invent citations or
results.

- [ ] **Step 4: Add the final consistency table**

Use exactly:

```markdown
| Issue | Original problem | Revision | Why it matters |
|---|---|---|---|
```

Include only substantive issues.

### Task 9: Run mathematical, implementation, and LaTeX verification

**Files:**
- Verify: `D:/Post-disaster Logistics/manuscript/main.tex`
- Verify: `D:/Post-disaster Logistics/manuscript/sections/abstract.tex`
- Verify: `D:/Post-disaster Logistics/manuscript/sections/system_model.tex`
- Verify: `D:/Post-disaster Logistics/manuscript/SECTION_BY_SECTION_REVISION.md`
- Verify: `D:/Post-disaster Logistics/manuscript/main.pdf`
- Verify: `D:/Post-disaster Logistics/code/tests`

**Interfaces:**
- Consumes: all rewritten sources.
- Produces: a verified active manuscript and evidence for every completion
  claim.

- [ ] **Step 1: Run the notation audit**

Check duplicate LaTeX labels, undefined references, balanced environments,
definition-before-use order, and collisions among information, inventory,
assignment, airspace, environmental status, and materiality symbols.

- [ ] **Step 2: Run legacy-language and claim-boundary scans**

Run:

```powershell
rg -n -i "urgenc|depriv|belief|ALNS|reinforcement|latent truth|uncertain current" "D:/Post-disaster Logistics/manuscript/main.tex" "D:/Post-disaster Logistics/manuscript/sections/abstract.tex" "D:/Post-disaster Logistics/manuscript/sections/system_model.tex"
```

Expected: no active legacy framing.

- [ ] **Step 3: Run the full implementation regression suite**

Run from `D:/Post-disaster Logistics/code`:

```powershell
python -m pytest -q
```

Expected: all tests pass.  This verifies that the implementation claims remain
consistent with the unchanged code base.

- [ ] **Step 4: Compile twice with `pdflatex`**

Run from `D:/Post-disaster Logistics/manuscript`:

```powershell
pdflatex -interaction=nonstopmode -halt-on-error main.tex
pdflatex -interaction=nonstopmode -halt-on-error main.tex
```

Expected: exit code zero on both passes.

- [ ] **Step 5: Inspect the LaTeX log**

Run:

```powershell
rg -n "Overfull|Underfull|undefined|multiply defined|LaTeX Warning|^!" main.log
```

Expected: no matches.

- [ ] **Step 6: Reopen and render the PDF**

Use `pypdf` to confirm page count, extract nonempty text from every page, and
check for unresolved `??`.  Render every page with Poppler and inspect title,
equations, column boundaries, page balance, and final-page density.

- [ ] **Step 7: Complete the harsh IEEE reviewer pass**

Audit scope, novelty wording, validity, missing data, clarity, compliance, and
advancement.  Record any remaining evidence gaps in the revision audit rather
than repairing them with invented material.

- [ ] **Step 8: Confirm exact changed-file scope**

Verify that only the approved active manuscript sources, the revision audit,
the design specification, and this plan were changed by this rewrite.
