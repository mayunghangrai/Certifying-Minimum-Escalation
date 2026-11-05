# Final benchmark: implementation and execution

The runner implements the 2026-09-30 hierarchy in `wind-benchmark-v2`. The v1 fixtures and reports keep their earlier formulation. Use `recovery.local_search.recover_local` for v2; the old single-mask scope API rejects v2 releases above Level 0.

## Evidence contract

- `represented` reports the minimum in the exact stored finite nominal/reserve path library, written as k_R in tables.
- `full_domain` reports the unrestricted path-domain claim. Only an independently checked physical exclusion can raise its lower bound.
- `minimum: null` means unresolved, including feasible repairs whose minimum scope is not certified. `minimum: "infinity"` means a certified exclusion in the named domain.
- Numerical candidate validation never proves exact feasibility or emptiness. Exact rational primal/Farkas certificates and exact physical exclusions are checked separately.
- Every Level-3 helper patch is represented. Exhausting one patch is insufficient to exclude the union. Larger permitted patches subsume all smaller patches.
- `b=1` is a benchmark policy parameter, held fixed for comparability. It is not a universal definition of Level 3. Supplementary controlled runs vary it.
- U0 comes from owned nodes reached in the directed union of old/new incumbent query supports. Shared inventory and bay constraints are checked globally but do not create permission edges. Every affected UAV has a root-to-owned-node trace.
- Level 2 releases sequences, paths, and loading/delivery quantity decisions in U0. Task responsibility changes begin at Level 3.
- Reserve paths are auxiliary witnesses. Changing only an auxiliary reserve path does not count as intervention.

## Development pilot and freeze

The pilot contains 12 base missions / 24 independent counterfactual updates, with N/M = 3/3, 6/3 and 12/4, two spatial families, and seeds 1001 and 1002. These seeds are excluded from primary results.

The first pilot exposed a budget-accounting defect: setup time consumed the Level-0 stage allowance before retention was attempted. Re-evaluation of the actual incumbents established that 21 were still feasible. A common exact retention screen now precedes stage allocation for both H and G; setup and search time are recorded separately. The regression test failed before this fix and passed after it.

The second pilot certified 21 Level-0 cases and retained three unresolved cases. All 24 passed exact previous-forecast feasibility. Eight updates were irrelevant to incumbent queries; six reached the full fleet; mean |U0|/M was 0.493. The exposed-update population is reported separately. The generator was retained unchanged: neither the distribution nor the affected sets were adjusted to produce more attractive results.

Frozen primary configuration:

- Randomized: 48 base missions, 96 H updates, sizes 3/3, 6/3, 12/4, 24/6, two families, six new seeds. A prespecified 32-update subset also runs G. Search cap: 5 s, 40,000 enumeration nodes and 4,000 complete branches per case.
- Boundary: 180 wind/duration observations and 27 deadline/battery observations, plus at most 24 deterministic refinements. Refine adjacent differing certified represented labels; never use an unresolved observation to claim a boundary.
- Controlled: six analytic cases, with exact feasible witnesses and independent physical lower bounds. Separate nonzero operation-time and helper-budget companions.

Search time caps are soft: checked between operations, with at most one in-flight operation overrun. Setup, physical proof checks, source capture, generation, and replay auditing are additional measured overhead. Runs are serial and BLAS/OpenMP threads are fixed to one by the CLI.

### Boundary reference quantities

Each template holds geometry, incumbent assignments and routes, operation protocol, path library and helper policy fixed. The reference time tau is the largest previous-forecast relief completion time. Duration is d/tau. Severity is r(q)=2q/(1+q²), multiplied by a fixed reference airspeed (5 for C1, 1 for C2/C3). C3 retains its heterogeneous fleet speeds. The shared time partition contains multiples of tau/8 through 4 tau and the fixed horizon.

Deadlines equal previous completion plus a multiplier of the template's original slack. The battery reference is the largest capacity required by any incumbent UAV, including its reserve witnesses; all UAVs receive this reference plus the selected slack times the reference energy scale. The library is fixed across each template sweep. Primary wind is local; its unchanged tail is explicitly represented on the full horizon.

### Randomized reference quantities

Tasks lie on a 0.1-unit grid in [-1,1]², with uniform or two-cluster sampling. The generator alternates angular and randomized balanced task allocation, then uses nearest-next Manhattan travel to order each assigned route. HV/VH polylines and incumbent/reserve paths form the finite library. Common airspeed is 1. Wind magnitudes are stored as rational strings so crosswind speeds remain exact-compatible. General continuous geometry remains outside primary exact claims.

All demand is mandatory. Per-mission deadline/battery slack regimes cycle across three settings; demands, energy coefficients, payload headroom, and stock headroom vary using the fixed seed. Each base mission has one uniformly located update A and one update B anchored to an incumbent nominal query. They are separate counterfactuals from the same state, not consecutive updates.

## Reproduce

From `code/`, using its existing virtual environment:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.venv\Scripts\python.exe scripts/final_benchmark.py controlled --output results/final_benchmark_reproduction/controlled
.venv\Scripts\python.exe scripts/final_benchmark.py boundary --config configs/final_benchmark/boundary_primary.json --output results/final_benchmark_reproduction/boundary
.venv\Scripts\python.exe scripts/final_benchmark.py random --config configs/final_benchmark/random_primary.json --output results/final_benchmark_reproduction/random
.venv\Scripts\python.exe scripts/final_benchmark.py audit --output results/final_benchmark_reproduction/random
.venv\Scripts\python.exe scripts/plot_final_benchmark.py --root results/final_benchmark_reproduction
```

Completed cases are atomically written, bound to input/config/source hashes, and verified before reuse. Interrupted individual cases restart; no serialized iterator is claimed. A changed source/config requires a new output directory. Each run includes a source archive and environment/package versions. Audit also works on existing records independently of rerunning search.

## Main-paper outputs

1. Certified intervention frequencies with every unresolved observation retained; identification intervals for the unknown true frequencies.
2. Directed affected UAVs versus actually changed UAV plans, with both normalized by fleet size.
3. Preserved plans in the returned feasible witness and the plans held fixed by its scope. These are separate quantities; full release does not imply every plan changes.
4. Enumeration/LP effort and time to a witness versus time to a minimum-scope certificate. Unfinished certification is censored and labeled.

The base mission is the statistical unit. Cluster bootstrap resamples base missions and keeps A/B together. H/G is supplementary: both receive the same retention screen, then G requests a feasible repair while H requests minimum-scope evidence. Failure to request a stronger G certificate is never counted as a solver failure.

The 32 paired H/G updates use the first and fourth frozen seeds in every size/family stratum. Both seeds belong to the tight margin regime. Their timing conclusions therefore apply to that prespecified subset, not the entire randomized population.

### Post-run budget check

The frozen five-second randomized run certified 84 Level-0 outcomes and left 12 minima unresolved. Three of the unresolved cases already had exact Level-1 witnesses. A separate, disclosed computational sensitivity applies a 60-second cap, 480,000 nodes and 48,000 branches to all 96 original updates. The generator, seeds, missions and path libraries are unchanged; original results are not replaced. Its configuration is `configs/final_benchmark/random_budget_sensitivity.json`, and its records are in `results/final_benchmark_2026_09_30/random_budget60`.

This additional check was selected after seeing the primary run. It measures the effect of extra computation and must be identified as post-run sensitivity in the paper. It cannot establish that unobserved levels are rare in other mission populations.

The completed check yields 85 certified Level-0 outcomes, one certified represented Level-1 outcome and ten unresolved represented minima. Full-domain labels are 85 Level 0 and eleven unresolved. The generator and representation inputs are checked for exact equality across the two budgets by `scripts/report_final_benchmark.py`.

To reproduce it, run `scripts/final_benchmark.py random --config configs/final_benchmark/random_budget_sensitivity.json --output <fresh-directory>`. Reusing an old output directory requires the exact source/config captured in that directory's `source.zip`. Later reporting changes are bound separately in `figures/figure_manifest.json`; use a fresh directory when running the current source.

Published figures are rebuilt from archived records. Fresh wall-time-capped searches may reach different stopping points on a different run or machine. Replay of a stored exact witness or exclusion checks its validity independently of that timing variation. To rebuild the completed September 30 report data and verify all five run archives, use `scripts/report_final_benchmark.py --root results/final_benchmark_2026_09_30`.

The fresh code review found and verified fixes for record-consumption integrity, source-archive restart integrity, supplemental evidence timestamps, and commitment-aware preservation counts. The full starting source snapshot is retained because the repository's active runtime was already largely uncommitted. No pre-existing user work is committed or discarded by this implementation.

### Figure contract

Detected axes: multi-panel; evidence mapping, readability, statistical presentation; Python/matplotlib, two-column width 7.16 in, text at least 8 pt. Figures use exact record JSON as source data, editable SVG/PDF and 300 dpi PNG. Boundary points carry explicit categorical labels and unknown markers, with no interpolated surfaces. Main panels map to the four questions above; captions state the domain, denominator and witness conditioning. Timing plots retain unresolved observations. Supplementary tables cover H/G and scope collapse. The recoverability membership CSV labels each observation inside, outside or unresolved for each D_{<=k}, separately by domain; exact witnesses can establish membership even when minimum scope is unknown.
