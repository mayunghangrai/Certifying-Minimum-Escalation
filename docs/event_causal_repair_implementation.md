# Event-Causal Belief-Repair ALNS: implementation contract

## Purpose

This implementation evaluates whether an incumbent multi-UAV relief plan
should be retained or selectively repaired after an operational report. It
never queries latent demand truth. Truth remains available only to the
environment for realized service and ex-post evaluation.

## Decision sequence

1. Capture the current operational snapshot: known nodes, risk-adjusted
   reported demand, reported corridor availability, UAV battery/payload, and
   depot inventory.
2. Difference it against the previous operational snapshot.
3. Trace changed resources through the explicit plan--belief dependency graph.
4. Classify the trace as hard infeasibility, value impact, or opportunity
   impact, then close the impact through the affected sortie and downstream
   route decisions.
5. Apply the continuation screen.
6. If a solve is invoked, remove only mutable decisions, preserve the remaining
   decisions as a warm start, and prevent ALNS destroy operators from removing
   frozen nodes.
7. Expand to a full replan only when the localized candidate remains infeasible
   or is non-improving.
8. Install a feasible candidate when it restores feasibility or improves the
   incumbent belief-side value. In-flight legs remain committed.

## Trigger interpretation

Let `V_current` be the capped belief-side value of the incumbent and
`V_upper` the relaxed value obtained by immediate, zero-cost, unconstrained
service of all currently reported demand. Define

```text
J_current = V_upper - V_current
LB = 0
```

Because `V_upper` is an upper bound on achievable plan value, `LB` is a valid
lower bound on regret-to-ideal cost. Therefore:

```text
J_current - LB <= C_solve
```

is a valid certificate that no reoptimization can recover more than the solve
cost under this relaxation. The converse is not a certificate: a gap greater
than `C_solve` only makes repair eligible.

Since the relaxed bound is intentionally safe and can be loose, an
event-impact value proxy filters small corrections and unused corridor
changes when the certificate is inconclusive. This proxy is logged separately
and must not be described in the manuscript as a mathematical bound.
The calibrated activation threshold is

```text
max(C_solve, proxy_threshold_fraction * V_upper).
```

The default fraction is `0.30`, selected to prevent low-impact reports from
exhausting the repair budget. Infeasibility bypasses both value screens.

## Dependency coverage

Each future visit depends on:

- its reported demand and commodity-level deprivation cohort;
- its incoming and safe-return corridor reports;
- assigned UAV energy and payload;
- required depot inventory commodities;
- depot service capacity;
- route precedence.

The current simulator has a mission horizon and deprivation cohorts but no
separate hard per-delivery deadline field. A deadline-specific dependency
should only be added if such deadlines are introduced into the scenario
schema.

## Experiment outputs

`run_event_causal_repair_experiment.py` runs paired seeds for:

- Event-Causal Belief-Repair ALNS;
- regret-gated full-replan ALNS;
- every-event full-replan ALNS;
- initial-plan-only ALNS.

It writes:

- `episode_metrics.csv`;
- `repair_diagnostics.csv`;
- `paired_comparisons.csv`;
- `summary.json`;
- `run_manifest.json`;
- three PNG/PDF figure pairs when `--plot` is supplied.

Episode metrics include the number of repair invocations, the number of
actual solver calls (including full-replan fallbacks), total online repair
wall time, mean wall time per solver call, and total episode wall time.
Event-level diagnostics separately report localized-solve, fallback-solve,
and total repair wall time.

The two-seed smoke run verifies execution, accounting, feasibility, diagnostic
coverage, and plotting. It is not evidence of statistical superiority; use
the paired manuscript run before making performance claims.

## Commands

Smoke:

```powershell
python scripts/run_event_causal_repair_experiment.py --smoke --plot
```

Final information-obsolescence experiment and figures:

```powershell
Set-Location "D:\Post-disaster Logistics\code"
python scripts/run_event_causal_repair_experiment.py `
  --config configs/env/event_causal_hard.yaml `
  --method-config configs/method/event_causal_repair.yaml `
  --seed-start 200 --n-seeds 40 `
  --output-dir results/event_causal_repair_final `
  --plot
```

The final seed range starts at 200 so it remains separate from the calibration
and earlier manuscript runs.
