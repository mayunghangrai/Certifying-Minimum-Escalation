# Controlled recovery benchmark — 2026-09-28

**Finding:** ascending-scope search spends work proving minimal intervention; immediate Level 4 can find more recoveries under a tight budget. At the medium budget, Level 4 recovered 65 configurations versus 54 for ascending search. At the high budget, both recovered 67, while ascending certified 67 minimum levels versus 24. These results support an objective-dependent tradeoff, not universal superiority.

## Study and controls

The study follows the finalized **2026-09-17 formulation**: one divisible commodity, fixed geometry/state/commitments within each wind pair, complete horizon wind tables with proper local support, wind-aware time and energy, and the five nested intervention scopes. All 88 incumbents were exactly feasible before their update. Original manuscript fixtures remain unchanged.

Three families—worked A, worked B and a one-UAV fractional-delivery case—each have separate sweeps of headwind magnitude, disturbance duration, deadline slack, full-charge battery headroom, and nested path libraries. A fourth family isolates a useful wind-bypass path. The [frozen protocol](superpowers/plans/2026-09-28-controlled-benchmark.md) lists every value and the claim-to-evidence checks. Geometry/state/commitments are held fixed within each sweep except the explicitly varied battery capacity and initial charge in the battery sweep; they remain identical across the two wind projections.

There are **88 configuration labels, 79 distinct serialized scenario/library inputs, 528 strategy/budget reports, 1,584 timing measurements, and 88 separate reference searches**. Repeated controls stay in their respective sweeps; three timing repetitions measure local variability and are not independent scientific samples.

Both strategies use identical inputs, path order and continuous quantity feasibility. Shared node/branch ceilings are 64/4, 256/16 and 2,048/128; each LP has the same 10,000-operation/2,000-row cap. Numerical fallback is disabled. Reference searches receive 100,000 nodes/10,000 branches. Counterbalanced sequential timing covers the whole recovery call, including diagnosis and validation; input construction, serialization and independent audits are excluded. A warm-up pair is excluded.

## Recovery and certification

Every cell below is **ascending / immediate Level 4**, across 88 labels. Recovery requires an exact witness; a minimum certificate additionally excludes all smaller levels. An exhausted search remains unresolved.

| Budget: nodes / branches | Exact recoveries | Minimum certified | No represented continuation | Unresolved |
|---|---:|---:|---:|---:|
| Low: 64 / 4 | 27 / 27 | 27 / 24 | 0 / 1 | 61 / 60 |
| Medium: 256 / 16 | 54 / 65 | 54 / 24 | 14 / 14 | 20 / 9 |
| High: 2,048 / 128 | 67 / 67 | 67 / 24 | 19 / 19 | 2 / 2 |

References certify **69 recoverable configurations**: 24 at Level 0, three at Level 1, 12 at Level 2 and 30 at Level 3. The remaining 19 have no continuation in their declared representation. Every reference is resolved; no case requires minimum Level 4.

Every returned witness in this pilot matched its reference minimum. The certification gap therefore reflects missing lower-scope exclusion proofs in immediate Level-4 search; it does not demonstrate that its recovered plans intervene more broadly. Immediate Level 4 intentionally spends its comparison budget on feasibility, so its only minimum certificates here are the 24 Level-0 witnesses.

The medium-budget pairing is informative: 52 configurations recover under both strategies, 13 only under Level 4, and two only under ascending search. Those two are the expanded divisible-case libraries: ascending uses 7 and 10 branches, whereas Level 4 needs 17 and 25, exceeding the common 16-branch cap. Removing repeated controls preserves the tradeoff: recoveries are 48/56 over 79 unique inputs at medium budget and 58/58 at high budget.

![Exact recovery, minimum certification and consumed enumeration work](../results/controlled_benchmark_2026_09_28_verified/figures/comparison.png)

*The three panels separate feasibility, minimality and work consumed under identical ceilings. Counts include repeated within-sweep controls; they are descriptive, not independent sample estimates. Vector [PDF](../results/controlled_benchmark_2026_09_28_verified/figures/comparison.pdf) and [SVG](../results/controlled_benchmark_2026_09_28_verified/figures/comparison.svg) are available.*

## Disturbance, slack and path findings

- **Wind matters.** For A/B, tested headwinds 0–0.25 km/h retain Level 0; 0.375–0.625 require Level 3; 0.75 has no represented continuation. With headwind 0.5, disturbing only the first one-hour bin retains Level 0, while disturbing the first two or all three bins requires Level 3.
- **Slack changes the needed intervention.** At headwind 0.5, A/B need Level 3 for tested T1 deadlines 1–1.75 h and Level 0 at 2–3 h. In the divisible case, deadlines 1.4, 1.5 and 2 h have no represented continuation; 2.2–2.3 h require Level 2; 2.4–3 h retain Level 0. A/B battery capacities through 1.45 Wh fail, while the tested 1.5, 2 and 10 Wh capacities admit Level 3. The divisible case changes from failure at 1.4–1.5 Wh to Level 2 at 1.55 Wh and above in this sweep.
- **Useful path diversity changes feasibility.** The bypass case has no direct-path recovery. Adding its first bypass yields minimum Level 1: outbound time falls from 1 h to exactly 0.625 h, meeting the 0.75 h deadline. Further bypasses retain that minimum.
- **Extra paths also cost enumeration.** In B, increasing the nominal library from 9 to 11 to 13 curves increases reference ascending work from 296 to 2,455 to 10,420 nodes. The latter two are the high-budget unresolved cases for both strategies, despite reference-certified Level-3 recoveries. The added backtracks are deliberately dominated. In A they have no effect because nominal paths are committed.

## Cost and limits

| Budget | Total nodes, ascending / Level 4 | Total branches | Median elapsed ms [Q1, Q3], ascending | Level 4 |
|---|---:|---:|---:|---:|
| Low | 4,155 / 3,656 | 198 / 173 | 64.6 [35.9, 78.2] | 45.7 [34.5, 53.6] |
| Medium | 10,529 / 8,409 | 471 / 437 | 100.7 [67.8, 120.7] | 85.2 [67.3, 102.9] |
| High | 16,853 / 14,710 | 799 / 711 | 88.1 [60.9, 127.5] | 83.6 [67.4, 134.2] |

Runtime statistics are across the 88 per-configuration medians, each from three repetitions. These are local timings on Windows 11, Python 3.13.3, AMD64 Family 25 Model 80, 16 logical CPUs; exact package versions and source hashes are saved in provenance. Lower high-budget medians than medium-budget medians reflect timing variability; no significance or real-time claim is made. Work ceilings are not wall-clock limits.

This is a small constructed OFAT pilot. It does not test factor interactions, broad geometry/fleet scaling, general irrational geometry, alternative enumeration orders, or stochastic disturbances. Level-3 and Level-4 release masks coincide in 26/28 B cases and 26/28 divisible cases, limiting any locality claim. No reference minimum is Level 4. Every impossibility statement concerns the supplied finite path library and fixed operating protocol.

The next evidence gap is a richer held-out suite with genuine Level-4-only recoveries, distinct local/global assignment scopes, and wind/slack interactions. Path ordering or pruning is another testable bottleneck; this experiment does not implement such a method or a policy/learning layer.

## Verification and reproduction

**277 tests passed. All 616 saved reports were audited (553 distinct reports); every exact witness and empty-level certificate replayed, and all 1,584 repeated search reports matched.** The initial run's final auditor incorrectly replayed a Level-0 fractional certificate using Level-4 variables. That verification bug and record-context checks were fixed and regression-tested; the full unchanged protocol was rerun. Both runs' deterministic reference/comparison report files are byte-identical. The [initial run explanation](../results/controlled_benchmark_2026_09_28/RUN_STATUS.md) and all raw measurements are preserved.

The completed [run directory](../results/controlled_benchmark_2026_09_28_verified/) contains [summary](../results/controlled_benchmark_2026_09_28_verified/summary.json), [audit](../results/controlled_benchmark_2026_09_28_verified/audit.json), [per-condition analysis](../results/controlled_benchmark_2026_09_28_verified/analysis.json), immutable inputs, raw JSONL records, integrity locks, and a source ZIP. Since the workspace was dirty, source hashes and the ZIP identify the actual measured implementation. Raw results remain local artifacts under the repository's existing ignore rule. Figure metadata identifies the later label-layout adjustment; it does not change any measured value.

From `code/`:

```powershell
# Audit the recorded study; rerun into a NEW directory to preserve this evidence.
.venv\Scripts\python.exe scripts/run_controlled_benchmark.py --output results/controlled_benchmark_2026_09_28_verified --verify
.venv\Scripts\python.exe scripts/run_controlled_benchmark.py --output results/my_controlled_run
.venv\Scripts\python.exe results/controlled_benchmark_2026_09_28_verified/analyze_findings.py
.venv\Scripts\python.exe scripts/plot_controlled_benchmark.py results/controlled_benchmark_2026_09_28_verified

# Unrelated installed Dash plug-in fails pytest startup; isolate project tests.
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Core dependencies are in `requirements.txt`; `requirements-experiments.txt` additionally installs matplotlib for figure regeneration. No manuscript text, original pinned fixtures, optimizer objective, policy, or learning method was changed.
