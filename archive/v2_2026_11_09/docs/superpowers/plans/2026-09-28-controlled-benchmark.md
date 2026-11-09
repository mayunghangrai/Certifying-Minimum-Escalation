# Controlled benchmark protocol and implementation plan

Source: finalized formulation 2026-09-17; existing deterministic simulator and finite-path recovery search. Authorized by the user's request to run controlled benchmark experiments. This is a constructed small-instance pilot, not a scalability or field-performance study.

## Frozen design (before measured experiments)

Use three instance families: worked A (committed paths), worked B (mutable paths), and a one-UAV/two-task divisible-transfer case (demands 0.75 and 0.5, mutable quantities). For each, run five separate one-factor sweeps, holding all other inputs fixed within a sweep:

- East-cell headwind magnitude: 0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75 km/h (constant bound 0.875).
- Disturbed early time bins: 0, 1, 2, 3 on common knots [0, 1, 2, 4]; headwind 0.5 km/h. West remains unchanged, so support is always proper.
- T1 deadline: [1, 1.25, 1.5, 1.75, 2, 2.5, 3] h for A/B; [1.4, 1.5, 2, 2.2, 2.3, 2.4, 3] h for the divisible case.
- Full-charge battery capacity (capacity and observed initial charge jointly): [1.3, 1.35, 1.4, 1.45, 1.5, 2, 10] Wh for A/B; [1.4, 1.45, 1.5, 1.55, 1.6, 2, 10] Wh for the divisible case. Reserve is 1 Wh. Pre-run validation corrected the divisible lower endpoint from 1.325 to 1.4: after the first delivery, the required emergency return still carries 0.75 units. Terminal energy alone understated the feasible-before-update battery requirement. No measured results informed this correction.
- Nominal outbound alternatives per depot/task-location pair: 1, 2, 3. Add nested collinear backtracks at 1/4 and 1/2 of the outbound segment. Return library remains fixed. These are deliberately dominated paths to expose enumeration overhead, not a claim of useful route diversity.

A fourth one-UAV family isolates useful path expansion: direct outbound plus 0, 1, 2, 3 rectangular bypasses at heights 0.5, 1, 1.5 km. Target [2,0], airspeed 5 km/h, lower-east wind [-3,0], deadline 0.75 h. Return paths stay direct. The shortest bypass has exact flight time 0.625 h versus 1 h direct. Geometry, state, commitments and the paired wind tables stay fixed across library variants.

Total: 3*(7+4+7+7+3)+4 = 88 configuration labels. Repeated controls are retained for within-sweep comparisons; report distinct scenario/representation pairs and avoid treating repeats as independent instances.

Compare ascending levels 0..4 with direct Level 4, using identical deterministic path order, transfer solver, input and representation. Both receive one **shared total** enumeration-node and branch-attempt budget: low 64/4, medium 256/16, high 2048/128. Each LP gets the same 10,000 exact elimination operations and 2,000-row cap. Numerical fallback is disabled. No adaptive budget tuning after results. Budget exhaustion means unresolved, not infeasible. Equivalent release masks are reused by ascending search without double charging work.

Run three sequential timing repetitions, counterbalancing which strategy runs first; one excluded warm-up pair on worked B. Time the entire recovery call including diagnosis, input validation and returned certificate construction. Exclude fixture generation, serialization and independent certificate audits. Timing repetitions measure local runtime variability, not statistical replication. A separate generous reference run (100,000 nodes, 10,000 branches, same per-LP caps) establishes the represented minimum or represented infeasibility where possible; unresolved references remain unresolved.

## Claim-to-evidence checks

| Question | Evidence | Limit |
|---|---|---|
| Does disturbance/slack change recovery requirements? | Exact reference minima or represented infeasibility for each factor value | OFAT, constructed geometry; no interaction study |
| Does ascending search help under equal work budgets? | Paired recovery coverage, minimum certificates, nodes, branches and elapsed time at each tier | Same ceilings do not mean identical consumed work; runtime is secondary |
| Does path expansion matter? | Nested manifests, dominated-path overhead, useful bypass feasibility threshold | Only the declared finite library; no continuous-path impossibility claim |
| Are results reproducible and sound? | Frozen inputs/protocol, source and data hashes, repeat report hashes, replayed witnesses and exclusion certificates | Machine-dependent runtime |

## Implementation and verification

1. Add direct-Level-4 mode and a shared branch budget to `recover`; preserve default ascending behavior. Test global accounting, direct-scope bounds, invalid budgets and representation identity.
2. Add deterministic scenario/library builders and a run recorder. Test OFAT invariants, complete wind tables, proper support, exact feasible-before-update premise, nested libraries and the analytical bypass threshold.
3. Freeze protocol and inputs before any measured run. Record source/environment provenance, references, deterministic reports, paired timing measurements, aggregated denominators and audit results. Refuse accidental overwrite of completed or partial runs.
4. Run all tests, execute the frozen experiment, independently verify every unique report's witness and empty-level certificates, and check deterministic repeats.
5. Write a concise findings report with actual outcomes and limits; review it against raw results. Preserve original fixtures and existing uncommitted work.
