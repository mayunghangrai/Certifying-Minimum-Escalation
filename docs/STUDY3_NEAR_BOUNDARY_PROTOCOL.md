# Study 3 refinement: missions near an incumbent feasibility boundary

Status: primary design frozen after two development pilots, 1 October 2026. The earlier frozen population and its results remain separate.

### Pilot refinement

The first development pilot (8 bases, 16 paired cases) certified seven of eight stressed cases at Level 1 and one at represented Level 2. Incumbent failure alone mostly tested path repair. The second development version therefore declares two reference strata: the incumbent deadline boundary and the **best represented fixed-sequence path repair** deadline boundary. The latter minimizes each flight duration under stationary wind while retaining sequence and quantities; it is a represented Level-1 boundary, not an unrestricted continuous-path boundary.

For the second anchor, replace `t_updated` in the pairing formula by that optimized reference delivery time. Require a positive delay from the previous incumbent delivery of at least 0.1% of the previous mission delivery-time scale (with a 0.1-hour scale floor). This threshold is also used in the second version of the incumbent stratum; it keeps the separation well above serialization rounding while admitting small delays for faster UAVs. The upper member has a feasible path repair, which need not be unchanged. The lower member excludes represented Level 1. No outcome above that boundary is prescribed.

The old pilot remains archived. These revisions occur before primary-seed use. No quotas are set for Levels 2, 3, 4, or infinity. Primary results will retain both anchors as separately labeled strata, including all unresolved cases and all failed generation slots.

The second pilot accepted all 16 requested bases (32 cases). The eight tighter incumbent-anchor cases certified Level 1. The eight tighter path-repair cases certified represented Level 2 in three cases and Level 3 in five; all eight full-domain minima remained unresolved. This confirms that the refined reference condition reaches beyond path repair without prescribing the required higher level. The primary run uses seeds 41001–41004, four sizes (3/3, 6/3, 12/4, 24/6 tasks/UAVs), both spatial families, both anchors, and both deadline sides: 64 requested base pairs, up to 128 cases. Each case has at most 120 generic proposals and a five-second soft proposal budget. Exact screens and bounded proofs are additional timed work.

The final review checked both represented proof arguments. Reporting corrections remove sampling confidence intervals for shared seeded draws, include represented proof construction in the cost breakdown, and distinguish the upper-control requirement for each anchor. The primary study will use the reviewed source snapshot; later changes require another run version.

## Scientific question and sampling population

Estimate intervention and certification requirements **conditional on a local adverse wind update and a deadline close to one of the two declared reference boundaries**. This is a stress population, not an estimate of the frequency of disruptions in operational traffic. The incumbent stratum locates loss of retention; the fixed-sequence stratum locates loss of represented path repair. Neither assumes knowledge of the full recovery feasibility boundary.

For each seeded geometry, assignment, and fleet, evaluate the incumbent exactly in the previous and updated forecasts. Choose an exposed delivery with a positive delay

`Delta = t_updated - t_previous`.

For the incumbent anchor, construct a matched pair with critical deadlines `t_updated - 0.1 Delta` and `t_updated + 0.1 Delta`. Deadlines use outward finite-decimal rounding, and the exact inequalities are checked after serialization. Both members must be exactly feasible before the update. This anchor's upper member must have an exact unchanged-plan witness after it. The lower member must have an independent fixed-deadline exclusion of Level 0. For the fixed-sequence anchor, use the optimized represented reference time and a Level-1 upper witness as specified above. These are design checks, not filters on the subsequent recovery level.

Draw task locations from uniform and clustered distributions on the existing rational grid. Use cardinal local wind of magnitude 0.6 and vehicle airspeeds 1, 1.275, and 1.56; the corresponding crosswind components 0.8, 1.125, and 1.44 are rational. Retain the existing two axis-order paths per pair of locations. Randomize assignment, energy coefficients, payload and stock headroom. Set battery capacity from the larger of the previous and updated incumbent requirements plus a declared margin; this cohort isolates a deadline boundary. Resource margins still constrain alternative repairs.

Accept a wind support only if it causes a positive nominal delivery delay and directed dependency diagnosis gives `0 < |U0| <= floor(M/2)`. Log every attempted support and rejection reason. Cap generation attempts and retain generation failures in the sampling ledger. Never select or reject using the recovery level, repair availability, or solver outcome. Deadline pairing and locality conditioning are part of the population definition.

## Evidence and search

Keep `b=1` as the benchmark policy. Level 2 changes sequences, paths, and loading/delivery quantities while fixing task ownership. Represented and full-domain minima remain separate, and unknowns remain in their denominators.

For this stationary-wind cohort, improve the represented Level 0/1 screen using shortest represented flight durations. With fixed sequence and quantities, nonnegative energy costs, no depot-bay coupling, and stationary complete admissible wind, independently shortest nominal and reserve paths minimize delivery times and energy use. A failed dominating plan can exclude that represented scope. This argument does not exclude unrepresented paths. Guard these assumptions, require exact arithmetic for all alternatives, and replay every such certificate.

For larger scopes, use a bounded, deterministic set of generic sequence and assignment proposals, with exact independent witness checks. Failure of proposals never proves infeasibility. Keep independent physical deadline relaxations as the only source of full-domain exclusions. Account separately for search, proof construction, generation, and replay.

A second represented proof relaxes all library paths to a graph of exact stationary travel durations. Shortest walks may concatenate paths through any task location, skip intermediate service and depot preparation, ignore capacity and energy, and use unlimited slots. Enumerate optimistic task orders (at most five tasks per UAV) and assignments (at most 512 total); exceeding either proof budget is unresolved. If every allowed assignment has a UAV whose every optimistic order misses a deadline, the represented scope is excluded. These certificates cannot exclude unrestricted continuous flight paths.

## Pilot, freeze, and reporting

1. Implement and test pair construction and evidence guards.
2. Run a small development pilot with disjoint seeds. Inspect boundary placement, generation rejections, `|U0|/M`, and certificate coverage. Do not target frequencies of particular intervention levels.
3. Freeze source, configuration, and new primary seeds in a new run directory. Any subsequent generator or solver change creates another version.
4. Report both anchors and both sides separately. The 50/50 pairing fixes the reference-feasible control proportion by design; pooled Level-0 prevalence is not an empirical discovery. Report descriptive frequencies and identification intervals for unknown labels. This small balanced panel shares random seeds across strata, so do not attach sampling confidence intervals that assume independent strata.

Main outputs remain: (i) certified level frequencies with unresolved intervals, (ii) dependency propagation versus returned-witness changes, (iii) intervention permitted/preserved by locality, and (iv) cost of obtaining the evidence. Changed-set counts are descriptive of the returned witness, not an optimized minimum cardinality. Higher-level sensitivities and H/G comparisons remain supplementary.

Timings describe single serial runs on this laptop. Cases can stop at different scopes and require different kinds of proof, so variation across mission sizes is not itself an asymptotic scaling result. A minimum Level-3 certificate establishes that reassignment permission is needed in the represented domain; it does not establish that an outside helper is necessary. Actual outside-U0 participation is reported separately.

## Implementation steps and review focus

- Add failing tests for exact two-sided placement, prior feasibility, deterministic generation, admission logs, and static-screen assumptions; then implement.
- Add bounded generic repair proposals and replayable records; test that heuristic failure and represented failure cannot become full infeasibility.
- Pilot, freeze, run, audit, and write a separate result report.
- Final read-only review must check the path-dominance theorem, unsupported arithmetic, commitment handling, paired denominators, selection bias, timing, and preservation claims.

Use the existing checkout. Preserve all pre-existing changes and frozen runs. No repository-wide cleanup or commit is part of this extension.
