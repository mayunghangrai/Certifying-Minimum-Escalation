# Final-study reporting corrections

Scope: implement the five confirmed findings in the 19 October review. Keep all solver, configuration, scenario and proof records unchanged. Work in the existing checkout because the study implementation is largely untracked and the frozen results live here. No commit or branch integration is part of this task.

Files: `src/final_study/analysis.py`, focused tests in `tests/test_final_study_reporting.py`, the comparison protocol's dated clarification, the results document and guide, and regenerated files under `results/final_study_2026_10_17/analysis/`. Preserve the current analysis output and touched source/docs in a separate review-backup folder before edits. Keep the original as-run report.

## Task 1: Correct and verify reporting

- [x] Add failing tests for all-instance versus known-minimum denominators, exact CPU-budget boundaries, late improvements/certificates, Level-0 certification, and mission-paired comparisons with unequal cohort membership.
- [x] Reconstruct within-budget outcomes from stored event timestamps without mutating raw rows. Use the same outcome definition for tables and curves. Preserve raw CPU/overrun data and distinguish available plan levels from the final stored plan used for decision counts.
- [x] Make Q1's primary rate use all instances; retain a labelled conditional secondary rate and denominator. Keep failed/unresolved cases in the all-instance denominator.
- [x] Add 60-second CMI-minus-PH intervals and matched-subset short/long certification counts and paired differences using the existing mission bootstrap.
- [x] Count Level-0 certification for every arm; distinguish it from positive-level/no-continuation certificates. Remove baseline optimality-claim attribution.
- [x] Relabel the existing post-plan timing statistic without changing its formula, and disclose that it excludes earlier proof work.
- [x] Report overrun counts/maxima and late events. Apply inclusive `cpu_s <= budget` cutoffs to arena outcome metrics; retain full evidence for reference pooling and integrity checks.
- [x] Run the focused tests, then the project test suite with unrelated pytest plugin auto-loading disabled. Investigate/report failures without changing unrelated code.
- [x] Regenerate the report through `Store(..., bind=False)` using the frozen manifest configuration. Verify raw-record hashes unchanged and independently reconcile primary rates, budget cutoffs, paired counts, audit totals and plot endpoints.
- [x] Update human-readable results and add dated protocol clarifications, marking the new 60-second paired comparison exploratory. Review the final changes and record validation.

Review focus: missing/late event timestamps; an earlier plan retained when a later result exceeds budget; baseline Level 0; empty/unknown reference denominators; pairing by instance while resampling whole missions.

Validation command: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; .\.venv\Scripts\python.exe -m pytest -q` from `code/`.

Implementation proceeds in this session under the confirmed review scope. A fresh reviewer will inspect the final changes under the executing-plans final-review instruction.


## Completion record

Completed on 19 October 2026 in the existing checkout. All five confirmed findings were implemented and the derived report, CSVs and figures regenerated. No commit or branch change was made.

Validation:

- Full suite: 622 passed in 273.77 seconds with unrelated pytest plugin auto-loading disabled.
- Final focused check after the presentation corrections: 7 passed, 16 deselected.
- Independent reconciliation: all 20,655 original CSV rows retain their original field values; all 20,655 within-budget event outcomes agree with the exported fields and comparison totals.
- Preservation: SHA-256 checks confirm all 19,510 stored experiment files outside analysis are unchanged.
- Independent code and document review: no Critical or Important findings; both minor presentation inconsistencies were corrected. No deferred review findings.
- The regenerated FS 10-second plot was visually checked; all table/curve endpoints were independently reconciled by the reviewer.

Implementation decisions:

- Keep final-witness reference pooling tied to stored replayable witnesses. No earlier logged plan improves the pooled reference upper bound in this frozen dataset.
- Credit earlier accepted plans for outcome rates, while using edit counts only from a final witness returned by the cutoff. This changes GR's FS minimum-level count to 140 and GR-c's to 587, and counts 41 GR Level-0 successes.
- Preserve the original as-run output and the complete pre-review analysis. Validation logs, preservation hashes and backups are under `artifacts/final_study_reporting_review_2026_10_19/`.
