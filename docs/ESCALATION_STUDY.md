# Escalation study: implementation and reproduction guide

Plan: `docs/EXPERIMENT_REDESIGN_PLAN_2026_10_07.md`. Status: `docs/EXPERIMENT_IMPLEMENTATION_STATUS.md`.
Pilot results and calibration: `docs/ESCALATION_PILOT_RESULTS_2026_10_08.md`.

All code is in `src/escalation_study/` and runs through `scripts/run_escalation_study.py`.
Earlier frozen results are not read or changed, except that the comparators and
the E1 report read a finished P1 run directory.

## What each study answers

| Study | Question | Unit | Command |
|---|---|---|---|
| P1 | How does the certified minimum level depend on deadline slack, wind strength and tasks per UAV? | 120 missions x 3 strengths x 5 slacks | `p1`, `audit`, `report` |
| C1-C3 | Which level does a finite path library, a global-first policy or time-sliced escalation return, compared with the certified minimum? | P1 variants with certified lower bound >= 1 | `compare`, `compare-audit` |
| R1 | How does certification depend on budget, contention and mission size? | Event logs; 2 rerun missions; 40 larger missions | `report`, `runtime-compare`, `large` |
| E1 | What changes when the same update arrives at 1/4 or 1/2 of the makespan? | 120 missions x 2 times x 5 slacks at strength 2/5 | `e1`, `audit`, `e1-report` |

## P1 missions (`missions.py`)

- Fleet of 4 UAVs; airspeeds 1, 1.275 and 1.56 shuffled and cycled; 4, 8 or 12
  tasks (1, 2 or 3 per UAV); uniform or clustered task layouts from
  `final_benchmark.generators.random_pair`; straight zero-wind incumbent legs.
- Every task with a positive incumbent delivery has deadline
  `upper previous delivery time + slack x makespan`, rounded up to 1e-10 h.
- Battery capacity is the previous-forecast requirement plus 3/2 of its scale,
  so capacity >= reserve + 5/2 x (requirement - reserve). An admitted update has
  |w| <= 3/5 of the slowest airspeed, which lengthens any flight by at most
  v/(v-|w|) <= 5/2. Energy therefore cannot make the incumbent sequence infeasible,
  and energy never binds at Levels 0-1.
- The update changes one cell of the 4x4 grid, drawn from the cells the
  incumbent's nominal legs cross; the direction is one of 12 rational unit
  vectors and the magnitude 1/5, 2/5 or 3/5 of the slowest airspeed.
  Diagonal winds are new to the certified runs, so
  `tests/test_escalation_study_diagonal_control.py` checks certified durations
  and all-path lower bounds against the closed form under uniform diagonal wind.
- Admission: certified previous premise for all 15 variants, 1 <= |U0| <= 2, and
  the same U0 for every variant. At most 24 draws, new geometry every 12. Every
  attempt is logged; a failed slot is kept and never replaced. No recovery
  outcome is consulted.
- The ledger also records each strength's certified incumbent delay, so results
  can be reported for updates that delay at least one delivery. It is a
  covariate, not a selection rule.

## Certification ladder (`ladder.py`)

1. `continuous.search.recover_continuous`: Level 0-1 screens and exclusions,
   bounded Level 2-4 proposals, physical certificates.
2. `level2.search.search_level2` unless Level 2 is excluded or witnessed.
3. `level3.search.search_level3` only after Level 2 is excluded.
4. `level4.search.search_level4` only after Level 3 is excluded.

Within one mission and strength the variants are certified from the loosest to
the tightest slack:

- **Seeds.** Verified path queries from earlier variants pre-fill the oracle
  (`initial_bounds`). They are valid because only deadlines differ.
  `recover_continuous` now reports only the queries it used.
- **Exclusion transfer.** An exclusion at a looser variant holds at every tighter
  one. Each record stores a `monotone_transfer_v1` item naming the source case
  and record hash.
- **Witness back-propagation.** After the chain, each variant's own lowest-level
  witness is re-validated on looser unresolved variants and stored in full.
- **Monotonicity check.** A tighter variant with a lower certified minimum than a
  looser one raises an error; it would indicate a defect.

Budgets bind per stage (wall cap, plus 120 proposals or 100,000 nodes). Pass 1
uses 10/8/6/6 s; pass 2 reruns unresolved variants with 20/40/30/30 s, starting
from their pass-1 bounds (`same_case_prior_v1`). Each record logs every bound
change with wall time (and CPU time for search stages), per-stage CPU and wall
time, and which limit stopped each stage.

## Records and audit (`store.py`, `audit.py`)

A run directory holds `manifest.json` (configuration, source hashes, runtime and
real worker count), `source.zip`, one sampling ledger per mission under
`missions/`, and gzip records under `records/pass1/` and `records/pass2/`. A
chain of five records is renamed into place as one directory, so an interrupted
run resumes at the next chain. Changing any file under `src/` or the configs
makes the run refuse to resume; use a new directory.

`audit` replays every stage with the optimizer-free checkers
(`verify_continuous_evidence`, Level-2/3/4 tree replay), re-checks each transfer
(same scenario except deadlines, no later deadline, same U0, source exclusion
verified), each prior-pass claim and each re-validated witness, and recomputes
the bounds. Any mismatch stops the audit.

## In-flight starts (E1)

Decisions in force (plan Section 5.2):

- **D1** An airborne UAV keeps its destination: `S {u}:1` and, for a task, that
  task's `A` coordinate are committed. Its path is not committed, so Level 1 may
  re-route the rest of the current leg.
- **D2** The initial reserve witness returns directly from the observed position.
- **D3** A snapshot inside a service or preparation moves to the end of that
  operation (and past an arrival less than 1e-6 h away).

Verifier changes. Every rule below is unchanged for idle depot origins; the full
suite, including replays of the frozen Level-2/3/4 records, passes.

| File | Change |
|---|---|
| `continuous/physics.py` | The guard admits airborne origins; servicing and preparing origins stay unsupported. `depot_origin` is the evaluator's predicate. |
| `continuous/search.py` | Deadline certificates and their verifier add preparation only for a depot origin. Initial reserves start at the observed position. New `committed_prefix_lower_v1` certificate (below). |
| `level2/bounds.py`, `level2/replay.py` | Prefix bounds start at the observed position, battery and epoch, without preparation or recharge, for an airborne origin. |
| `level2/search.py` | Skeleton paths, reserves and pre-queried bounds start at the observed origin. |
| `level3/search.py`, `level3/replay.py` | The assignment deadline bound uses each owner's origin. The multi-sortie completion bound is applied only when every candidate owner is a depot origin. |

Physical, represented and static-path proofs keep their idle-depot guards, so
they never exclude an airborne domain.

**Committed-prefix certificate.** Under D1 every candidate first flies from the
observed position to the committed stop with the observed payload, and a task
stop is then owned by that UAV. With a verified all-path lower bound `L` on that
flight, every level is excluded when any of these holds:
battery - (empty mass + payload) x coefficient x airspeed x L < 0; epoch + L >
horizon; for a depot stop, the arrival battery is below the reserve; for a task
stop with positive remaining mandatory demand and a deadline,
epoch + L + service duration > deadline. The verifier re-checks the potential,
the commitments and the arithmetic.

**Witness soundness.** With stationary wind and uncoupled preparations, upper
duration bounds only delay operations and increase flight energy from a fixed
observed state, so a witness checked with upper durations is feasible, as at
depot origins.

**Snapshots (`snapshots.py`).** The incumbent is executed under the previous
wind to `t = fraction x makespan` with certified rational event times. Completed
deliveries, loads and stock are exact; positions are rounded to a 1e-9 km grid,
batteries down to 1e-9 Wh. Each UAV's slot bound drops by its completed stops.
The received packet starts at the snapshot epoch with the P1 update. Admission
requires conservation of stock + onboard + delivered, the same U0 for all slack
variants, and a certified previous premise. U0 may be empty; then Level 0 follows.

## Commands (Windows, from `code/`)

Run the tests first:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Primary P1 (6 workers on the 8-core laptop):

```powershell
.venv\Scripts\python.exe scripts/run_escalation_study.py p1 --config configs/escalation_study/p1_primary.json --out results/escalation_study_primary --workers 6
.venv\Scripts\python.exe scripts/run_escalation_study.py p1 --config configs/escalation_study/p1_primary.json --out results/escalation_study_primary --workers 6 --phase pass2
.venv\Scripts\python.exe scripts/run_escalation_study.py audit --out results/escalation_study_primary --workers 6
.venv\Scripts\python.exe scripts/run_escalation_study.py report --out results/escalation_study_primary
```

Comparators and R1:

```powershell
.venv\Scripts\python.exe scripts/run_escalation_study.py compare --p1 results/escalation_study_primary --config configs/escalation_study/comparators.json --out results/escalation_study_comparators --workers 6
.venv\Scripts\python.exe scripts/run_escalation_study.py compare-audit --p1 results/escalation_study_primary --out results/escalation_study_comparators
.venv\Scripts\python.exe scripts/run_escalation_study.py p1 --config configs/escalation_study/r1_budget_third.json --out results/escalation_study_r1_budget_third --workers 6
.venv\Scripts\python.exe scripts/run_escalation_study.py p1 --config configs/escalation_study/r1_uncontended.json --out results/escalation_study_r1_uncontended --workers 1
.venv\Scripts\python.exe scripts/run_escalation_study.py runtime-compare --reference results/escalation_study_primary --other results/escalation_study_r1_budget_third --csv results/escalation_study_r1_budget_third/runtime_compare.csv
.venv\Scripts\python.exe scripts/run_escalation_study.py runtime-compare --reference results/escalation_study_primary --other results/escalation_study_r1_uncontended --csv results/escalation_study_r1_uncontended/runtime_compare.csv
.venv\Scripts\python.exe scripts/run_escalation_study.py large --config configs/escalation_study/r1_large.json --out results/escalation_study_r1_large
.venv\Scripts\python.exe scripts/run_escalation_study.py large-audit --out results/escalation_study_r1_large
```

E1 (after the primary P1 run, which its report reuses for t = 0):

```powershell
.venv\Scripts\python.exe scripts/run_escalation_study.py e1 --config configs/escalation_study/e1_primary.json --out results/escalation_study_e1_primary --workers 6
.venv\Scripts\python.exe scripts/run_escalation_study.py e1 --config configs/escalation_study/e1_primary.json --out results/escalation_study_e1_primary --workers 6 --phase pass2
.venv\Scripts\python.exe scripts/run_escalation_study.py audit --out results/escalation_study_e1_primary --workers 6
.venv\Scripts\python.exe scripts/run_escalation_study.py e1-report --p1 results/escalation_study_primary --e1 results/escalation_study_e1_primary --out results/escalation_study_e1_primary/analysis
```

Plug the laptop in, choose the best-performance power mode and disable sleep. If
a run stops, rerun the same command; finished chains are skipped.

## Outputs of `report`

Under `<run>/analysis/`: `variants.csv` (one row per variant: level or bounds,
evidence sources, U0, headwind, incumbent delay, speed ranks, witness changes,
times, stop reasons, work counters), `shares_by_tasks.csv` and
`shares_pooled.csv` (shares with mission-cluster bootstrap 95% intervals and
identification bounds for unresolved variants), `bands.csv` (per mission and
strength, the slack brackets where each level stops sufficing),
`stronger_wind_relief.csv`, `certified_by_wall_budget.csv` and
`certified_by_cpu_budget.csv` (fraction certified within each budget),
`level_shares.png/.pdf`, `certified_by_wall_budget.png/.pdf` and `summary.json`.

## Limits

- Stationary, fully covered wind; uncoupled depot preparation; one update.
- Witness-closing times use own events; a certificate closed by a back-propagated
  witness is charged the variant's full time.
- Snapshot positions and batteries are rounded (at most 1e-9 km and 1e-9 Wh, the
  battery downward); the previous premise is re-certified on the rounded state.
- The comparators claim no exclusions except C1's own finite-library proofs.
