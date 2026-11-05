# Continuous-path experiment results — October 5, 2026

All three experiment stages are implemented and have passed independent evidence replay. Paths are admissible continuous polylines throughout the flight region. A numerical path generator supplies candidates; independently checked rational intervals and global travel-time bounds establish the reported conclusions.

## Primary results

| Stage | Inputs | Certified minimum intervention levels | Feasible recovery witnesses |
|---|---:|---:|---:|
| Controlled validation | 10 cases | 10 | 9; the remaining case is certified infeasible |
| Paired frozen Study 3 cases | 128 cases | 127 | 128 |
| Fresh continuous boundary cohort: bounded search | 62 cases | 49 | 50 |
| Same cohort: search plus stored admission evidence | 62 cases | 50 | 51 |

The cohort requested 32 base missions and admitted 31, producing 31 tight/loose pairs. The capped failure `CB_6_3_clustered_61003` is retained with all 24 attempts. It was not replaced. Development pilots used seed 51001; primary cohort seeds are 61001–61004.

The full test suite passed **387 tests**, including 35 continuous-path tests. Tests cover analytic physics, wind-cell interface ownership, nonconvex regions, scope commitments, reserve-only repair, altered certificates, paired input integrity and sampling-ledger tampering. See the [verification log](../results/continuous_paths_2026_10_05/full_suite_after_review.log).

## 1. Controlled validation

| Control | Certified outcome | Check |
|---|---:|---|
| C0 | Level 0 | Retain the incumbent |
| C1 | Level 1 | Generate a wind detour without a stored bypass |
| C2 | Level 2 | Change the sequence |
| C3 | Level 3 | Change task assignment |
| C4 | Level 4 | Use the larger helper scope |
| Cinf | Infeasible | Replay an exclusion covering all levels |
| arbitrary_angle | Level 1 | Generate a diagonal repair absent from the axis-path library |
| analytic_diagonal | Level 0 | Check irrational flight time with outward rational bounds |
| constant_headwind | Level 0 | Check the analytical uniform-wind travel-time bound |
| reserve_only | Level 0 | Replace an auxiliary reserve curve while preserving nominal coordinates |

All expected outcomes passed. Controlled path observations also store independently validated curves, global lower bounds and their gaps. These observations are measured separately from recovery search.

Artifacts: [control report](../results/continuous_paths_2026_10_05/primary/controlled/analysis/report.md), [case table](../results/continuous_paths_2026_10_05/primary/controlled/analysis/cases.csv), [path bounds](../results/continuous_paths_2026_10_05/primary/controlled/analysis/paths.csv).

## 2. Paired comparison on the existing 128 cases

Every scenario, incumbent, mission quantity, affected-set rule and helper budget matches the frozen October 1 record. The new manifest binds all original record hashes, file hashes and the original source archive.

| Evidence source | Certified minima | Unknown minima |
|---|---:|---:|
| Archived finite-library search | 116 | 12 |
| Archived evidence valid over unrestricted paths | 89 | 39 |
| New continuous-path search and global bounds | 127 | 1 |

The new continuous minima are Level 0 in 45 cases and Level 1 in 82 cases. All 128 have a feasible witness. In **39 cases**, the new continuous witness has an intervention level strictly below the archived finite-library lower bound. These are verified examples where restricting paths to the library increases the required intervention or prevents a represented recovery.

The remaining case, `NB_3_3_uniform_41002_fixed_sequence_below`, has a certified lower bound of Level 2 and a verified Level-3 recovery. Its true minimum remains in **[2, 3]**. The archived library lower bound is Level 4, so this case also demonstrates a library penalty.

The four paired groups each contain 32 cases: incumbent/above gives 32 Level-0 minima; incumbent/below gives 32 Level-1 minima; fixed-sequence/above gives 13 Level-0 and 19 Level-1 minima; fixed-sequence/below gives 31 Level-1 minima and the single [2, 3] gap.

Both configurations specify five seconds, but the archived limit covers proposal search while the new limit covers total search between operations. Runtime versions also differ. The comparison supports conclusions about recoverability and intervention, without a speed ranking.

Artifacts: [paired report](../results/continuous_paths_2026_10_05/primary/paired/analysis/report.md), [case table](../results/continuous_paths_2026_10_05/primary/paired/analysis/cases.csv), [library-to-continuous transitions](../results/continuous_paths_2026_10_05/primary/paired/analysis/transitions.csv).

## 3. Fresh cohort around continuous Level-1 bounds

The cohort spans (tasks, UAVs) = (3, 3), (6, 3), (12, 4), (24, 6), with uniform and clustered task locations. Admission requires previous feasibility, a local adverse update affecting at most half the fleet, and a material positive delay proved by a continuous-domain lower bound. It does not select cases by the resulting recovery level.

For each accepted base mission, the critical fixed-sequence delivery time has a certified lower bound and a feasible upper bound. The tight deadline is below the lower bound; the loose deadline is above the upper bound. Their offset is one tenth of the certified wind-induced delay, with outward decimal rounding. The median reference gap is about **2.40 × 10⁻¹⁰ h**, and the maximum is **0.0580 h**. The interval brackets the infimum over allowed fixed-sequence paths; it is not assumed to be an exact optimal boundary.

| Side | Cases | Conclusions using all independently checked evidence |
|---|---:|---|
| Tight / below | 31 | All exclude Levels 0 and 1; 19 certify Level 2; 12 retain an unknown higher minimum |
| Loose / above | 31 | 5 certify Level 0; 26 certify Level 1 |

The bounded search timed out on `CB_24_6_uniform_61002_above` after excluding Level 0. The constructor had already stored and verified a Level-1 reference witness for this loose control. Combining that witness with the search exclusion certifies Level 1. The frozen search record remains unchanged, and the combined evidence has its own table and source binding.

Of the 12 tight cases with unknown minima, `CB_3_3_clustered_61003_below` has a verified Level-3 recovery and a [2, 3] gap. The other 11 have a certified lower bound of Level 2 and no verified recovery within the search budget. They remain unresolved.

Measured cohort search took 248.863 s in total, generation took 286.455 s, and per-record independent replay took 26.947 s. The screen and proof counters overlap; adding them would double-count work. Later complete-run audits and report replay are additional verification work.

Artifacts: [bounded-search report](../results/continuous_paths_2026_10_05/primary/cohort/analysis/report.md), [search case table](../results/continuous_paths_2026_10_05/primary/cohort/analysis/cases.csv), [combined evidence table](../results/continuous_paths_2026_10_05/primary/analysis/cohort_combined_evidence.csv), [combined summary](../results/continuous_paths_2026_10_05/primary/analysis/summary.json).

## Scope and interpretation

The implemented scope is stationary, fully covered admissible wind, idle depot origins and uncoupled depot preparations. Feasibility checks include time, energy, reserve, inventory, delivery and commitment constraints. Global potential bounds apply to every allowed continuous path; their mesh parameterizes the proof field.

Continuous deadline bounds can certify Level-1 infeasibility even when the path generator has explored only some candidates. High. 0
;er-level physical relaxations can also exclude scopes. Numerical search exhaustion, an energy failure on one curve or an unsuccessful reserve proposal cannot certify global infeasibility. Higher-level route and quantity proposals remain bounded; this implementation is not a complete continuous solver for every combination of constraints.

The paired cases share base missions, and the new cohort is conditionally sampled around a boundary. These results are descriptive for the declared inputs. They do not estimate an unconditional recovery rate or justify independence-based confidence intervals.

## Reproduction and provenance

The [implementation guide](CONTINUOUS_PATH_EXPERIMENTS.md) gives the runner, audit and report commands. Primary artifacts are under `results/continuous_paths_2026_10_05/primary/`. Each stage has an immutable manifest, source archive and case records; the cohort also has immutable sampling ledgers. All three stages share frozen experiment source hash `558c67788d11bc6cbf3059460bd7cb8bb832c3f7d4cf5473182a4d46c5b7305b`.

After regenerating the three stage reports, regenerate the combined evidence without numerical optimization:

```powershell
.venv\Scripts\python.exe scripts/summarize_continuous_results.py --root results/continuous_paths_2026_10_05/primary
```

The aggregation replays the continuous records and admission evidence and checks the original paired input binding. Its [analysis manifest](../results/continuous_paths_2026_10_05/primary/analysis/analysis_manifest.json) binds the reporting script, stage manifests, case records, sampling ledgers and derived outputs. This reporting source is captured separately because it was added after the experiment source freeze.
