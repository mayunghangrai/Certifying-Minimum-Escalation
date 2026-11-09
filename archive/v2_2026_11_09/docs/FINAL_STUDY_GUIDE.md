# Final study: how to run it and what it produces

Date: 14 October 2026. Designs: `docs/SCENARIO_DESIGN_2026_10_14.md` (FS and LS),
`docs/COMPARISON_PROTOCOL_2026_10_14.md` (equal-resource comparison) and method v2
(`docs/CERTIFICATION_METHOD_V2_IMPLEMENTATION.md`). Configuration:
`configs/final_study/final.json`, frozen after the pilot
(`docs/FINAL_STUDY_PILOT_2026_10_14.md`). Amended on 15 October after a review (certificates
kept, Level-4 constructions, battery-aware LR, corrected statistics, scaling strata); run the
confirmation pilot (`configs/final_study/confirmation_pilot.json`,
`docs/FINAL_STUDY_CONFIRMATION_PILOT_2026_10_15.md`) before the full run.

The 19 October reporting corrections are described in Section 13 of the comparison
protocol. They regenerate analysis from stored records; they do not rerun the study.

## The one command

From the `code` folder, in the project environment:

```
.venv\Scripts\python.exe scripts\run_final_study.py --workers 6
```

It runs every stage below in order, writes everything under `results\final_study\`, and ends
with `results\final_study\analysis\REPORT.md`. It can be stopped (Ctrl+C, sleep, power cut) and
started again with the same command: finished units are kept and the run continues where it
stopped. Do not change any file under `src`, `configs\final_study` or `scripts` between
restarts; the run refuses to mix code versions (start a new `--out` folder if you must).

Useful variants:

```
.venv\Scripts\python.exe scripts\run_final_study.py --workers 6 --stages report
.venv\Scripts\python.exe scripts\run_final_study.py --workers 6 --stages fs-generate,fs-label,fs-arena-short,report
```

Those commands require the original source binding. To regenerate analysis after a
reporting-only source change, open the archived run with `bind=False` and use the
configuration in its manifest. From the project Python environment, run the following
Python code (preserve the existing `analysis/` output first):

```python
import json
import sys
from pathlib import Path
sys.path.insert(0, "src")
from final_study.store import Store
from final_study.analysis import write_report

run_path = Path("results/final_study_2026_10_17")
config = json.loads((run_path / "manifest.json").read_text())["config"]
write_report(Store(run_path, config, bind=False), config)
```

This replaces derived files under `analysis/`; stored scenarios, labels, arena results,
proofs, the manifest and the frozen source archive remain unchanged.

Progress, with an estimate of the time left for each stage, is printed and appended to
`results\final_study\run.log`.

## Stages

| Stage | What it does | Units | Worst case (6 workers) | Expected (from the pilot) |
|---|---|---|---:|---:|
| `fs-generate` | 162 FS missions (fleet 4/6/8 x tasks per UAV 2/3/4 x slack x battery x 2 layouts), 9 variants each (3 strengths x 3 update times), disrupted plans only | 162 missions | 0.5 h | 5-10 min |
| `fs-label` | reference labels: CMI with 600 s CPU, one pass, replayed | 1,458 variants | 40 h if all hit the cap | 1-1.5 h |
| `fs-arena-short` | GR, GR-c, LR, PH, CMI, noAF, noER at 10 s each, random order per instance | 1,458 | 4.7 h | 1-1.5 h |
| `fs-arena-long` | GR, GR-c, LR, PH, CMI at 60 s on a random third of the missions | 486 | 6.8 h | 10-30 min |
| `ls-build` | level-suite draws toward Levels 1-4 and no continuation (20 per fleet size each), labelled at 600 s; at most 800 draws per class and fleet. Level-4 draws are constructed (deficit and chain, `src/final_study/level4.py`), then screened and tightened by CMI runs of 120 s, up to 8 rounds per draw; their labels are pooled with the construction's exact-checked witness (`pooled` in the label record) | up to 12,000 draws | long if many draws hit the cap | to be set from the confirmation pilot |
| `ls-arena-short`, `ls-arena-long` | the arms on the LS instances (up to 330) at 10 s and 60 s | up to 330 + 330 | 4 h | about 1.5 h |
| `p1-label`, `p1-arena` | P1 secondary set: the 700 variants with lower bound at least 1; labels and arms at 10 s | 700 | 2 h | about 1 h |
| `xr` | reuse across the deadline chain of each P1 mission and strength, against CMI alone, 10 s per variant | 360 chains | 1.7 h | 15 min |
| `scaling` | the 40 larger missions (24-48 tasks, 6-8 UAVs), arms at 60 s and 300 s | 40 | 2.7 h | minutes if they stay at Level 0 |
| `fs-d1` | in-flight FS variants rebuilt under D1 (destination committed), labelled at 600 s | 972 | long if many hit the cap | 20-30 min |
| `contention` | 30 FS instances again on one worker (contention factor) | 30 | 0.6 h | 10-15 min |
| `gr-seeds` | GR and GR-c with two more seeds on 30 FS instances (variance of the randomized arms) | 60 | 0.1 h | 5 min |
| `report` | tables, figures and `REPORT.md` | - | minutes | minutes |

Expected total: about 10-14 hours, i.e. one night. The machine must stay awake; in Windows set
"Sleep: never" while plugged in.

## If something fails

A unit that fails (one mission, instance or chain) is logged in `run.log`, leaves no result,
and is listed in section 10 of the report ("Units and stages that failed"), with a file under
`results\final_study\failures\`. Later units and stages still run. Running the same command
again retries only what failed or is missing; the file disappears when the unit succeeds.

## What the report contains

- Screening: how many update draws were needed per admitted mission.
- FS: the five metrics (certification rate, unresolved rate, required level, computation time,
  recovery success) overall and by each of the six factors; the interval-censored ordinal
  regression of the required level; the targets set in advance, marked met or missed.
- Comparison at 10 s and 60 s (FS and LS): per arm, plans, plans at the reference minimum
  over all instances (primary) and known finite minima (conditional secondary),
  levels above the minimum, certification, CPU to first plan and to certificate, replay rate;
  decisions changed (UAVs, outside U0, reassigned tasks, sequence edits, re-routed and new
  legs, deliveries, depot stops) with paired CMI-minus-arm differences; cross-check violations
  (target 0); additional delay after the certified-level plan; CPU time by part;
  matched-subset budget comparisons and the exploratory paired 60 s CMI-PH interval;
  the primary endpoints of Q1-Q3.
- LS by class: composition (fleet, update time, recipes, distinct missions) and per-arm results.
- P1: agreement of v2 with every v1 certificate (target 0 disagreements) and the arms at 10 s.
- XR, scaling, the D1 sensitivity table, contention, operation overruns/late events,
  and the replay summary. All arena outcome metrics score the returned plan if it was
  returned by the inclusive CPU cutoff, and proofs logged by then; baseline certification
  includes Level 0.

CSV files (`instances.csv`, `arena_<set>_<budget>.csv`) and `summary.json` sit next to the
report for further analysis. Arena CSVs retain the original final-result fields and add
`within_budget_*` fields for the corrected outcomes, and `unreturned_better_plan` for runs
that logged a lower-level plan than they returned by the cutoff. Figures: `fs_levels_by_factor.png`
and the anytime curves (all-instance denominators).

## Before the full run

1. Tests: `.venv\Scripts\python.exe -m pytest -q` (all must pass; 606 tests on 14 October).
2. Optional smoke run on a tiny configuration (about 15 minutes):
   `.venv\Scripts\python.exe scripts\run_final_study.py --config configs\final_study\smoke.json --out results\final_study_smoke --workers 6`

## Notes

- Budgets are CPU time per arm (`process_time`); wall times include contention from the other
  workers, which the contention stage measures.
- Every label and arena result keeps its certificates: the evidence and records go to a proof
  file under `proofs\` (same relative path as the record), cited by digest from the record. To
  replay a saved result later: `final_study.arena.replay_saved(payload, record,
  store.load_proofs(record))`.
- Every result is replayed independently right after it is produced; failures are listed in
  the report, never hidden.
- The frozen v1 runs keep their own `source.zip`. Their old command-line tools refuse to open
  them under the current code (the source hash changed when v2 was added); to re-audit one,
  unpack its `source.zip` into a separate folder and run the tool from there.
