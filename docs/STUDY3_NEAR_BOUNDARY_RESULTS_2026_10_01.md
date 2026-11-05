# Study 3 refinement: results and interpretation

The refined experiment is implemented and complete: **64 base pairs, 128 primary cases**, with 32 base pairs per boundary type. Development pilots use different seeds and are excluded from these counts. Every record and certificate passed replay.

## What changed in the study

The generator deliberately places a critical deadline on either side of two reference boundaries:

1. **Incumbent boundary:** the updated delivery time with the mission plan retained.
2. **Represented path-repair boundary:** the best updated delivery time obtained by changing represented paths while retaining sequence and quantities.

For reference delivery time \(t^{\mathrm{ref}}\) and previous delivery time \(t^-\), the paired deadlines are

\[
D_{\pm}=t^{\mathrm{ref}}\pm0.1\bigl(t^{\mathrm{ref}}-t^-\bigr),
\]

rounded outward before exact validation. Both members were feasible before the wind update. The paired members share geometry, wind, assignments, and resources; only the critical deadline changes.

The frozen panel covers 3/3, 6/3, 12/4, and 24/6 tasks/UAVs, two spatial families, and four fresh seeds. The helper policy remains **b=1**. Admission requires a positive reference delay and \(0<|U_0|\le\lfloor M/2\rfloor\). All 64 requested base pairs were accepted within the fixed attempt limit: 429 support trials included 250 rejected for locality and 115 rejected for insufficient reference delay. No recovery-level quotas or post-run tuning were used.

These are frequencies in a **conditional stress population**. The paired controls and local affected sets are deliberate design choices.

## 1. Which intervention levels were required?

The main comparison uses the tighter-deadline member of each pair:

| Boundary crossed | n | Level 1 | Level 2 | Level 3 | Level 4 | Represented ∞ | Unresolved |
|---|---:|---:|---:|---:|---:|---:|---:|
| Incumbent | 32 | 25 | 1 | 2 | 0 | 2 | 2 |
| Represented path repair | 32 | 0 | 4 | 14 | 0 | 4 | 10 |

These are certified **represented minima, \(k_R^F\)**. Level 0 is excluded for every tighter-deadline case.

- Crossing the incumbent boundary often permits path repair: 25/32 cases have minimum Level 1, certified in both domains.
- Once represented path repair fails, four cases certify Level 2 and fourteen certify Level 3. Thus reassignment permission is necessary in those fourteen cases within the represented domain. Level 3 permits up to one outside helper; the minimum-scope certificate alone does not prove that a helper must participate.
- Across both rows, twelve represented minima remain unresolved. Nine exclude Levels 0–2; three exclude Levels 0–3. The latter three need Level 4 if a represented recovery exists. They cannot yet be labeled Level 4 or infinity.
- No Level-4 minimum was certified in this panel. Unknown cases prevent interpreting that zero as absence of a Level-4 requirement.

The looser controls behave as intended: all 32 incumbent controls certify Level 0; the path-repair controls certify thirteen Level-0 and nineteen Level-1 cases.

### Evidence domain matters

All 32 tighter path-repair cases have **unresolved unrestricted minima, \(k^F\)**. Eighteen nevertheless have exact feasible recovery witnesses, which also establish full-domain upper bounds. The six represented infinities across both rows do not establish unrestricted impossibility.

Across all 128 cases, 116 represented minima and 89 unrestricted minima are certified. The unrestricted certificates are 45 Level-0 and 44 Level-1 results. The experiment supports higher-level necessity within the stored representation; unrestricted higher-level necessity remains a limitation.

## 2. How does propagation differ from intervention?

The following comparison uses the **same witnessed cases** for both UAV counts:

| Tighter-deadline cohort | Exact witnesses / cases | Mean affected UAVs | Mean changed UAV plans | Median dependency-closure nodes |
|---|---:|---:|---:|---:|
| Incumbent boundary | 28/32 | 1.32 | 1.36 | 78 |
| Path-repair boundary | 18/32 | 1.44 | 2.17 | 80 |

Dependency closure and physical intervention count different objects. The closure can contain many evaluations, while a repair changes a few vehicle plans. In the path-repair cohort, fourteen returned witnesses change one outside UAV. These returned plans change more UAVs than were initially affected. Only two of the 46 tighter-deadline witnesses change fewer UAV plans than the number initially affected.

Changed sets describe the returned plans. They are not optimized for minimum cardinality within a scope.

## 3. How much can locality preserve?

Among the exact tighter-deadline witnesses:

| Cohort | Mean fraction held fixed by the witness scope | Mean fraction unchanged in the returned plan |
|---|---:|---:|
| Incumbent boundary, 28 witnesses | 65.2% | 65.8% |
| Path-repair boundary, 18 witnesses | 42.6% | 43.5% |

These are feasible preservation guarantees. They do not measure a causal improvement over a globally released solver, which could also return a local repair.

The admission rule deliberately limits \(|U_0|/M\); its mean is 0.336 in each cohort. With these fleet sizes and b=1, equality of the complete Level-3 and Level-4 release masks is excluded by construction. Use the original broader randomized population for release-mask collapse frequency, and treat this panel as the study of local escalation boundaries.

## 4. What does certification cost?

| Tighter-deadline cohort | Median solve | Maximum solve | Median independent replay |
|---|---:|---:|---:|
| Incumbent boundary | 1.42 s | 62.40 s | 0.72 s |
| Path-repair boundary | 3.26 s | 75.25 s | 1.70 s |

The five-second budget applies to repair proposals. Exact screens, proof construction, and replay are additional measured work. The largest case spent 67.52 of its 75.25 solving seconds on represented proof construction. Its represented minimum remains unresolved, with a lower bound of 3.

For the sixteen certified Level-3 cases, median time to construct the represented certificate was 4.33 s. The median additional time after finding a feasible repair was 1.28 s. Independent replay is additional. For unresolved cases, the reported time is effort spent under the protocol, not a completed time-to-certificate measurement.

Generation, solving, and first replay totaled about **15.5 minutes**. Later reporting and compatibility audits are additional. Timings are single serial runs on this laptop and describe this workload; they are not an asymptotic scaling law or an H-versus-G ranking.

## Figure and artifacts

![Study 3: certified levels, propagation, and evidence cost](<D:/Post-disaster Logistics/code/results/study3_near_boundary_2026_10_01/primary/analysis/study3_near_boundary.png>)

- [Frozen protocol](STUDY3_NEAR_BOUNDARY_PROTOCOL.md)
- [Complete generated tables and report](../results/study3_near_boundary_2026_10_01/primary/analysis/REPORT.md)
- [Case-level observations](../results/study3_near_boundary_2026_10_01/primary/analysis/observations.csv)
- [Level frequencies and identification intervals](../results/study3_near_boundary_2026_10_01/primary/analysis/level_frequencies.csv)
- [PDF figure](../results/study3_near_boundary_2026_10_01/primary/analysis/study3_near_boundary.pdf)
- [Analysis hashes](../results/study3_near_boundary_2026_10_01/primary/analysis/manifest.json)

The generated report also gives affected-set means across all 32 cases in each tighter-deadline cohort. The matched table above conditions both means on exact witnesses for direct comparison. No sampling confidence intervals are used for the refined panel because seeded draws are shared across strata.

Validation: **352 tests passed**. All **128 primary**, **48 development**, and **497 earlier benchmark** records passed exact evidence replay. The primary source/configuration snapshot is unchanged. Original benchmark records were preserved; no manuscript edits were made.
