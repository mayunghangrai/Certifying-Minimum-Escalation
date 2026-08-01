# Locked fixed-guidance final benchmark

This benchmark is the only promotion test for the completed guidance pilot.
It compares exactly two frozen policies:

- production baseline: unguided graph-MAPPO, `g=0`;
- challenger: fixed guidance, `g=0.5`, `beta=5.591`.

Adaptive guidance is rejected and is neither loaded nor evaluated.

The benchmark is prepared before any policy evaluation. Preparation verifies
that all requested seeds are absent from prior repository text artifacts,
records the generated scenario hashes, records both checkpoint SHA-256 hashes,
and locks the protocol, manifests, promotion rule, and benchmark-runner hash.
The run refuses changed manifests, source, scenarios, or checkpoints.

The primary paired outcome is true deprivation cost. Fixed guidance is
promoted only if all predeclared conditions pass:

- mean deprivation reduction is at least 5%;
- the paired 95% bootstrap confidence interval has a lower bound above zero;
- mean fill rate is not worse;
- there are no additional feasibility violations;
- at least 60% of seeds improve; and
- the mean improvement remains positive after removing the two largest
  improvements.

The benchmark uses 40 untouched seeds, identical scenarios for both policies,
deterministic actions, alternating policy execution order, and no tuning or
selection on benchmark outcomes.

Run from the `code` directory:

```powershell
python -m scripts.run_locked_guidance_benchmark `
  --prepare `
  --results results\gate_learning_beta5591_pilot `
  --output-dir results\fixed_vs_unguided_final_benchmark `
  --seed-start <explicit-unused-start> `
  --seed-count 40 `
  --device cuda

python -m scripts.run_locked_guidance_benchmark `
  --verify-only `
  --output-dir results\fixed_vs_unguided_final_benchmark

python -m scripts.run_locked_guidance_benchmark `
  --run `
  --results results\gate_learning_beta5591_pilot `
  --output-dir results\fixed_vs_unguided_final_benchmark `
  --device cuda
```

The run is resumable only for missing policy/seed pairs and always re-verifies
the immutable lock and checkpoint hashes first. Publication artifacts include
paired seed data, a summary CSV, a LaTeX table, PNG/PDF figures, the production
decision, and a SHA-256 reproducibility report.

## Locked result

The benchmark used untouched seeds 730001--730040. Fixed guidance passed every
predeclared rule:

- mean true-deprivation reduction: 10.890%;
- paired 95% bootstrap interval for absolute reduction:
  [11.129, 16.286];
- improving seeds: 39/40;
- mean reduction after removing the two largest improvements: 12.653;
- mean fill rate: 0.03354 unguided versus 0.08297 fixed;
- feasibility violations: 0 for both policies;
- mission completion: 100% for both policies.

Production is therefore promoted to fixed guidance (`g=0.5`,
`beta=5.591`) using checkpoint SHA-256
`d730f89ea92a8a3c9af41a0d0706594e1753afaa9d6808f1ba32fc073e72ce15`.
Adaptive guidance remains rejected and was not evaluated in this benchmark.
