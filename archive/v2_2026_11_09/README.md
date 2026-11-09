# Archive: v2 study and everything before it (snapshot of 9 November 2026)

This folder holds all v1 and v2 work: the recovery search, continuous paths, Levels 2-4, the
escalation study, the v2 final study and the B-series runs. It was moved here when `code/` was
reduced to the v3 study (`docs/V3_CODING_PLAN_2026_11_04.md` in the code root). Taken from git
commit `794e2f6` on branch `codex/final-simulation-benchmark`. Git history has every earlier
version.

The folder keeps the code-root layout, so scripts and tests that resolve paths from their own
location (`parents[1]/'src'`, `ROOT/'results/...'`) work here without edits.

| Folder | Contents |
|---|---|
| `src/` | All v1/v2 packages, complete. `env/`, `recovery/`, `continuous/{__init__,binned,physics,validation}.py` and `level2/{__init__,quantities}.py` are copies of the files the v3 code still uses (they already carry the v3 schema dispatch of Phase A0). |
| `scripts/`, `configs/` | v1/v2 runners, replays, plots and their configurations |
| `tests/` | The v1/v2 test suite (`conftest.py` is a copy) |
| `docs/` | Designs, protocols and results notes, the 2026-09-17 formulation snapshots, `superpowers/` plans and specs |
| `scenarios/`, `examples/`, `schemas/` | Fixtures and the v1/v2/v3 schemas (copy) |
| `results/` | Every v1/v2 run (gitignored) |
| `artifacts/`, `presentation_update/` | Figures and presentation material (untracked) |
| `README.md.orig`, `PROJECT_CONTEXT.md` | The previous top-level README and project context |

The manuscript's current Sec. IV comes from `results/final_study_2026_10_17` and
`results/support_sensitivity_2026_10_22` (figures: `scripts/plot_manuscript_*.py`).

## Running from the archive

Run from this folder, with the code root's `.venv` (Python 3.13):

```powershell
cd archive\v2_2026_11_09
$env:PYTHONPATH="src"; $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
..\..\.venv\Scripts\python.exe -m pytest -q tests
..\..\.venv\Scripts\python.exe -P scripts\run_final_study.py --help
```

Scripts write into this folder's `results/`. Use a fresh output directory when rerunning.

Known result (9 November 2026): 642 of 643 tests pass here. The exception,
`test_benchmark_artifacts.py::test_preserved_predecessor_is_exact_non_executable_archive`, looks
for `archive/pre_2026_09_17` under this folder, but that archive stays at `code/archive/`. The
same check passes there.
