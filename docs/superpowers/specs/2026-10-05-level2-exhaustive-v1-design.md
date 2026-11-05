# Level-2 Exhaustive Search v1

The user authorizes implementation of four modules and a run on exactly the 13 unresolved targeted cases. All work stays under `code/`; frozen continuous experiments remain unchanged.

## Domain and supported physics

Level 2 preserves assignment and every unreleased/committed coordinate. Branch over every fixed route slot, with task repetitions, depot repetitions/revisits, and inactive suffixes. Assignment requires each assigned remaining task to appear at least once, including optional tasks; unassigned tasks cannot appear. The existing idle-depot, stationary fully covered wind and uncoupled preparation guard applies. Unsupported scenarios remain unresolved.

## Search and evidence

Use an explicit prefix tree. Every branch lists every raw permitted next-slot symbol. Structural contradictions and safe optimistic resource bounds close subtrees. Continuous oracle potentials provide lower bounds over all paths; selected path interval upper bounds support feasible missions only. Failed paths do not exclude geometry.

At a complete skeleton, compile an optimistic rational quantity problem with global leg lower bounds. A verified Farkas contradiction or exact ground/horizon contradiction closes that skeleton. Otherwise optimize permissible paths and reserves, compile conservative upper-duration quantity constraints, and accept only an exact rational primal. Feasible optimistic quantities and failed upper-duration models leave an open geometry/quantity leaf.

The independent replay implementation does not import the generator, branch-and-bound or quantity orchestration modules. It reconstructs the domain from scenario fields, checks child coverage and every terminal proof using exact arithmetic, and reports exclusion only if all nodes are closed without an open leaf. A witness requires only its independently checked existential proof; the remaining frontier is explicitly open.

## Targeted execution

Select the 12 unresolved tight fresh-cohort records and the single unresolved paired record from their frozen outputs. Bind inputs and existing continuous evidence by hashes. Replay existing lower/upper evidence and combine it with the Level-2 result. Store a new source snapshot, records, coverage audits and descriptive summary. No new benchmark generation or scaling study in this milestone.

Search is exhaustive in domain, not guaranteed to finish under a finite budget. Geometry gaps, rational solver limits and search limits remain explicit. Floating LP statuses are never exclusions.
