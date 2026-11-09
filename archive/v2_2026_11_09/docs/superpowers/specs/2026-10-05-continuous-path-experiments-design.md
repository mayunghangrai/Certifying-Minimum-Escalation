# Continuous-path recovery experiments

User authorization: implement the selected three-stage continuous-path experiment design from the chat on 5 October 2026. This is the continuous-region direction, rather than adopting a fixed graph as the mathematical path domain.

## Objective and domain

Generate new admissible polylines anywhere in the operating region and verify them independently of `PathLibrary`. Preserve the existing five intervention scopes, component commitments, quantities, operation protocol, and auxiliary reserve semantics. A finite numerical initialization mesh never defines the admissible path domain and its exhaustion never proves infeasibility.

The first executable study targets stationary, completely covered, admissible wind, idle depot origins, and unconstrained depot bays. These are the current Study 3 conditions. Other inputs return an explicit unsupported/unresolved result. The complete time-varying experiment extension is subsequent work.

## Physics and evidence

Use rational outward enclosures of square roots to integrate arbitrary-angle polylines after exact rational splitting at wind-cell boundaries. A fixed-payload flight has constant power, so stationary flight time and energy are proportional. Upper duration enclosures give a conservative mission feasibility check; lower enclosures can reject a particular candidate. Neither numerical optimizer status nor failed proposals excludes a scope.

For global travel-time bounds, use continuous piecewise-affine potentials on a rectangular mesh aligned with the rectangular wind partition. On every triangle check `w dot grad(phi) + v*norm(grad(phi)) <= 1` using rational inequalities. Continuity and complete spatial coverage imply `phi(goal)-phi(start)` is a bound on every admissible continuous path. Conic optimization proposes potential values; a separate checker certifies them. Include interface ownership and bind certificates to the region, wind and UAV speed. Unsupported partitions retain the elementary all-path physical bounds and unresolved conclusions.

Generate candidate paths from straight flights, incumbent curves, and spatial seeds, then optimize wind-cell boundary crossing positions continuously using second-order cone problems. Validate the actual returned polyline, including boundary ownership. The proposed cell itineraries are search aids, not a completeness claim. Retain the best validated candidate and record the certified lower/upper travel-time gap.

Level 0 retains every nominal coordinate but may choose new reserve witnesses. Level 1 optimizes only released nominal paths plus auxiliary reserve paths. Construct global deadline exclusions using lower bounds on all released flights and fixed-path interval bounds elsewhere. Higher levels use the existing generic sequence/assignment proposals with newly generated paths; failed bounded search remains unresolved. Existing independent physical exclusions may strengthen the result.

## Three experiment stages

1. Controlled validation: analytic constant-wind and arbitrary-angle flights, a wind detour, a reserve-only repair, and a globally excluded deadline. Check exact equality, interval uncertainty, commitments and altered proof objects.
2. Paired migration: use all 128 frozen October 1 Study 3 scenarios without changing their incumbent, wind, quantities, helper policy or critical deadline. Bind the archived baseline records and report both represented and unrestricted baseline conclusions against the continuous results. This is a comparison of domain/evidence coverage; archived baseline timings are historical and do not establish a speed ranking. Count all continuous path generation, proof construction and replay cost. Include every unresolved case.
3. Continuous boundary cohort: use fresh seeds and continuous pre-update incumbent paths. Bracket the updated fixed-sequence Level-1 reference by certified lower/upper bounds. Construct a tight deadline below the lower bound and a loose deadline above the upper bound, while independently verifying previous feasibility. Condition only on declared exposure, locality and positive certified delay; log capped generation attempts and keep failed slots. No recovery-level quotas.

Pilot before freezing a new primary configuration. Preserve the frozen source/configuration snapshots and all earlier results. Store source, configuration, scenario, record and input-bank hashes; independent replay uses rational evidence and does not rerun numerical optimization. Use new result directories after source/configuration changes.

## Deliverables and validation

Python APIs, a command-line runner for all stages and replay, frozen pilot/primary configurations, a paired 128-case run, a fresh continuous boundary run, case-level observations and a human-readable report. Run targeted analytic/regression tests and the complete current test suite. Report continuous-domain bounds, witnesses, minimum-certification coverage, uncertainty, deadline/resource margins and measured cost. No claim of complete unrestricted path search or general solver superiority.
