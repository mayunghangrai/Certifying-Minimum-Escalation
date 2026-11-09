# Certified minimum repair on larger, realistic missions (study v3)

Code for the v3 study: UAV delivery missions in time-binned wind, a forecast update that breaks
the incumbent plan, and a certified smallest intervention level that repairs it. The design is
`docs/Final experiment design certified minimum repair on larger, realistic missions (1).docx`.
The coding plan, with its work packages, gates and decisions Q1-Q19, is
`docs/V3_CODING_PLAN_2026_11_04.md`.

All v1 and v2 work (earlier studies, their results and the runs behind the manuscript's current
Sec. IV) is in `archive/v2_2026_11_09/`. See its README.

## Layout

```
configs/study_v3/   physics.json: Matrice 350 RTK values, power model, packages, bins
docs/               design, coding plan and review, FIFO proof, v3 Sec. II draft
schemas/            wind-benchmark v1, v2, v3 (env/scenario.py loads all three)
src/study_v3/       v3 generator, incumbent, update, snapshots, admission, Phase A
src/env/            scenario, units, float evaluator, U0 diagnosis, scope masks   (shared with v2)
src/recovery/       transfer rows and their solver support                         (shared with v2)
src/continuous/     binned.py (exact binned checker); physics, validation          (shared with v2)
src/level2/         quantities.py (exact quantity witnesses)                       (shared with v2)
scripts/            run_v3_phase_a.py, probe_v3_admission_r.py, keep_awake_until.py
tests/              test_v3_*.py; v2_fixtures.py and fixtures/ (copied v2 fixtures)
results/            v3_phase_a, v3_phase_a_r08, v3_phase_a_smoke (gitignored)
archive/            pre_2026_09_17 (v1 runtime) and v2_2026_11_09 (everything v1/v2)
```

## Environments

- `.venv` (Python 3.13.3) runs the tests and the Phase A scripts (use `-P`).
- The conda env `wind_benchmark` (`environment.yml`, Python 3.10) matches the frozen v2
  manifests. `requirements.txt` lists the packages (v3 needs shapely, jsonschema, scipy, pytest).

## Commands

```powershell
$env:PYTHONPATH="src"; $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
.venv\Scripts\python.exe -m pytest -q tests
.venv\Scripts\python.exe -P scripts\run_v3_phase_a.py --workers 14 --stages fill gate --out results\v3_phase_a
.venv\Scripts\python.exe -P scripts\probe_v3_admission_r.py --workers 14 --draws 24
.venv\Scripts\python.exe scripts\keep_awake_until.py results\v3_phase_a\gate_summary.json
```

Phase A runs resume: finished slots and missions are kept.

## Code shared with v2

v3 imports these v2 files. They stay in `src/` with their original package names, so no
imports changed. Identical copies (as of the archive date) are in `archive/v2_2026_11_09/src/`,
where the v2 code still uses them. Change them here only through the v3 plan (Phase A0 adds a
`schema_version` dispatch; v2 behaviour must stay unchanged).

| Files | Used by |
|---|---|
| `env/*` (14 files, incl. `units.py`, new in A0.2) | every `study_v3` module, all v3 tests |
| `recovery/*` (11 files; the package `__init__` loads them all) | `continuous/physics.py`, `continuous/validation.py`, `level2/quantities.py`; `recovery/transfers.py` also by `test_v3_binned.py`, `test_v3_units.py` |
| `continuous/physics.py`, `continuous/validation.py` | `study_v3` (flight, admission, phase_a: premise and witness checks), `continuous/binned.py` |
| `continuous/binned.py` (new in A0.6) | `study_v3` (admission, missions, snapshots), `continuous/validation.py`, `level2/quantities.py` |
| `level2/quantities.py` | `test_v3_binned.py` (binned quantity witness, A0.7) |
| `schemas/wind-benchmark-v1/v2.schema.json` | `env/scenario.py` (loaded at import) |
| `tests/v2_fixtures.py`, `tests/fixtures/local_delay.json` | `test_v3_units.py`, `test_v3_binned.py` (copied from the v2 tests and `scenarios/benchmark/`) |

When Phase B needs more v2 code (for example `certify_v2` as the starting point of
`certify_v3`, or `final_study.analysis` for the bootstrap), copy it from the archive into a v3
package and add it to this table.
