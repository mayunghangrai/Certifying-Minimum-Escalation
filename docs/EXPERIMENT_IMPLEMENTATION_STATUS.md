# Experiment implementation status

Plan: `docs/EXPERIMENT_REDESIGN_PLAN_2026_10_07.md`. This file records what is
implemented in this folder, so an interrupted session resumes from here rather
than starting over. Each component is copied here as soon as its tests pass.

Last updated: 14 October 2026 (method v2, FS/LS generators and the equal-resource arena
implemented; pilot done, configuration frozen; the full run is the one command in
`docs/FINAL_STUDY_GUIDE.md`; see "Final study" below).

## Decisions in force

- D1: an airborne UAV keeps its destination (`S {u}:1` and that task's `A`
  committed); Level 1 may re-route the rest of its current leg.
- D2: the initial reserve witness returns directly from the observed position.
- D3: a snapshot that finds any UAV mid-service or mid-preparation moves to the
  earliest later time at which none is.
- Battery: sized from the previous forecast with slack 3/2 (capacity at least
  reserve + 5/2 x previous requirement). Every admitted update keeps flight
  durations within v/(v - |w|) <= 5/2 of their previous values, so the
  incumbent sequence stays energy-feasible and energy cannot bind at Levels 0-1.
- Primary slack grid 1/10, 1/30, 1/100, 1/300, 1/1000 of the makespan (pilot
  calibration, see `docs/ESCALATION_PILOT_RESULTS_2026_10_08.md`).

## Components

| Component | Status | Location |
|---|---|---|
| Baseline suite on the unmodified code | 546 passed (8 Oct 2026) | - |
| Diagonal-wind analytic control (plan 2.3) | done, passes | `tests/test_escalation_study_diagonal_control.py` |
| P1 mission generator and admission ledger | done, tested | `src/escalation_study/missions.py` |
| Certification ladder, transfers, event log | done, tested | `src/escalation_study/ladder.py`; seeds and events added to `continuous/search.py`, `continuous/oracle.py` |
| Run store, parallel runner, audit | done, tested | `store.py`, `runner.py`, `audit.py`, `cli.py`, `scripts/run_escalation_study.py` |
| Analysis | done, tested | `src/escalation_study/analysis.py` (tables, bootstrap, bands, figures) |
| Comparators C1-C3, runtime profile R1 | done, tested | `comparators.py`, `compare.py`, `runtime.py`; `configs/escalation_study/comparators.json`, `r1_*.json` |
| In-flight verifier (E1) | done, tested | origin-aware rules in `continuous/physics.py`, `continuous/search.py` (incl. committed-prefix certificate), `level2/bounds.py`, `level2/search.py`, `level2/replay.py`, `level3/search.py`, `level3/replay.py` |
| In-flight snapshots (E1) | done, tested | `src/escalation_study/snapshots.py`, `inflight.py` |
| Pilot (P1, E1, comparators) | done, audited | `results/escalation_study_pilot_2026_10_08`, `..._e1_pilot_2026_10_08`, `..._pilot_comparators_2026_10_08`; report `docs/ESCALATION_PILOT_RESULTS_2026_10_08.md` |
| Primary configuration | frozen | `configs/escalation_study/p1_primary.json`, `e1_primary.json`, `r1_*.json` |
| Primary P1 | done 9 Oct 2026 on the laptop (6 workers, 1.6 h wall, 6.3 h CPU); report written | `results/escalation_study_primary` |
| Comparators C1-C3 | done 9 Oct 2026 on the laptop (1.4 h wall); compare-audit passed | `results/escalation_study_comparators` |
| R1 runtime profile | done 9 Oct 2026 on the laptop (about 40 min); large-mission audit re-run on Linux passed | `results/escalation_study_r1_budget_third`, `..._r1_uncontended`, `..._r1_large` |
| E1 in-flight updates | done 9 Oct 2026 on the laptop (30 min); Linux re-audit of 6 snapshots passed | `results/escalation_study_e1_primary` |
| Primary results write-up | done | `docs/ESCALATION_PRIMARY_RESULTS_2026_10_09.md` |

## Resume notes

Full suite: 590 passed (546 original + 44 new, including the 20 diagonal-wind
control tests), 8 October 2026, Linux container. The laptop run (step 1 of
the guide, 9 October 2026) was not recorded here.

Changes made after the pilot, none of which touch the certification logic:
figure labels in `analysis.py`, the freeze-note numbers in `p1_primary.json`,
and the R1 larger-mission sizes (now all four (n, m) combinations from the plan,
40 missions). `src/level2/search.py` keeps its original CRLF line endings.

All primary runs are complete; results, checks and caveats are in
`docs/ESCALATION_PRIMARY_RESULTS_2026_10_09.md`. In short: P1 certifies 1,514
of 1,800 variants (Level 0 61%, no continuation 6%, unresolved 16%, mostly
certified to need at least Level 3); C3 matches the minimum when it finds a plan
but rarely finds Level 3-4 plans, C2 over-intervenes, C1 finds nothing; in
flight, failures turn into certified infeasibility under D1.

`src/continuous/search-1.py` and `search-2.py` on the laptop are copies of the
backup attachments (`continuous/search.py` and `level2/search.py`). Nothing
imports them, but they are inside every primary run's source archive; they can
be deleted now that the runs are finished.

## Final study (14 October 2026)

Implemented with the recommended defaults of the four plans (method v2 with the 10 October
amendments; FS/LS scenario design; equal-resource comparison with GR-c; D1' primary and D1 as
sensitivity; one-cell update; disrupted plans only):

| Component | Status | Location |
|---|---|---|
| Method v2 (table, route check, one-UAV rows, stop-sequence search, levels, ladder, replay) | done, tested | `src/certify_v2/`; `docs/CERTIFICATION_METHOD_V2_IMPLEMENTATION.md` |
| Baselines GR, GR-c, LR, PH; ablations noAF, noER; XR chain | done, tested | `src/certify_v2/baselines.py`, `ladder.py`; `src/final_study/arena.py` |
| Decision metrics (predecessor changes, re-routed legs) | done | `src/certify_v2/metrics.py` |
| FS generator (six factors, urgency classes, battery margin, placement, 4/5 strength, D1' snapshots, disruption admission) | done, tested | `src/final_study/generator.py`; D1' option in `src/escalation_study/snapshots.py` |
| LS sampler (recipes, quotas, draw order, residue) | done, tested | `src/final_study/levelsuite.py` |
| Run store, stages, CLI, one command | done | `src/final_study/store.py`, `stages.py`, `cli.py`, `scripts/run_final_study.py` |
| Analysis and report (five metrics, Q1-Q3, primary endpoints, ordinal regression, figures) | done | `src/final_study/analysis.py` |
| Configurations | final (frozen after the pilot), pilot, smoke | `configs/final_study/final.json`, `pilot.json`, `smoke.json` |
| Pilot | done | `docs/FINAL_STUDY_PILOT_2026_10_14.md` |
| Guide | done | `docs/FINAL_STUDY_GUIDE.md` |

Checks:
- v2 agrees with v1 on a stratified sample of 113 v1-certified P1 variants, and certifies 38
  of 40 sampled v1-open ones within 30 s.
- The pilot ran all 15 stages on its own seeds: every result replays, with no cross-check
  violation and no failed unit.
- The bugs it found are fixed, each with a regression test.
- The full suite passes: 606 tests.
- A final smoke run of all 15 stages used the frozen code.

Next step: the full run on the laptop.

```
.venv\Scripts\python.exe scripts\run_final_study.py --workers 6
```

It takes about 10-14 hours and writes `results\final_study\analysis\REPORT.md`.

Earlier plans (now implemented as above):

- `docs/CERTIFICATION_METHOD_PLAN_2026_10_09.md`: method v2, one search for plans and
  proofs at every level.
- `ROOT_CAUSE_AND_REDESIGN_PLAN_2026_10_10.md`, kept in the claude.ai Project only: the
  root causes of the P1 and E1 results, and amendments to v2. Its instance sets P2 and E2
  are replaced by the scenario design below.
- `docs/SCENARIO_DESIGN_2026_10_14.md`: a factorial study (FS) and a level suite (LS)
  that answer supervisor comment 3.
- `docs/COMPARISON_PROTOCOL_2026_10_14.md`: the equal-resource comparison that answers
  supervisor comment 4. It replaces C1-C3, M2 and M3.

Frozen earlier results are untouched.
