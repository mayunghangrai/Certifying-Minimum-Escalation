# Guidance-strength calibration and pilot

The completed `beta=1` development run learned the required gate direction but
did not materially change the action distribution. Do not continue the same
run blindly. Calibrate the existing one-hot ALNS logit intervention offline,
then train a short isolated guided-branch pilot from the frozen unguided
checkpoint.

## Offline calibration

`scripts/calibrate_guidance_strength.py` reads the saved matched-state logits,
action masks, one-hot ALNS priors, and gates. It does not replay the
environment, sample an action, update a model, or mutate a checkpoint. For
each candidate beta it exactly evaluates:

```text
hybrid_logits = base_logits + beta * gate * one_hot_follow_prior
```

The smallest candidate is eligible only if:

- median adaptive-versus-fixed TV is at least `0.003`, or adaptive/fixed
  argmax changes are at least `1%`;
- adaptive-versus-unguided argmax changes are between `1%` and `10%`;
- fresh/feasible ALNS-following exceeds combined stale/deviated following by
  at least `5%`; and
- no more than `5%` of recommended-action probabilities exceed `0.95`.

The completed run's 16,000 matched profile states recommend `beta=5.591`.
This is a pilot value, not a final hyperparameter claim.

## Isolated pilot

`--guidance-beta` records the resolved value in the experiment YAML,
metadata, and new guided checkpoints. A guided checkpoint fails to load if its
recorded beta or fixed gate differs from the requested agent. Old checkpoints
without these fields remain readable.

`--guided-only` requires an imported graph-MAPPO checkpoint. The imported
unguided policy is persisted and evaluated in the new output directory at
checkpoint episode zero; it is not retrained. Fixed and adaptive guided
branches still begin from identical copied parameters and optimizer state.

After validation, `scripts/check_guidance_pilot_acceptance.py` applies the
predeclared influence, separation, saturation, validity, gradient, and
stability checks. It also requires adaptive guidance to be no worse than the
fixed branch on true deprivation, fill rate, and reward. Gate diagnostics
alone cannot accept or promote a checkpoint.

Checkpoint evaluation reads `beta` and the fixed gate from the loaded actor.
Both values are written into every evaluation row; counterfactual TV, argmax,
and ALNS-follow metrics must never use a hard-coded guidance strength.

After a 200-episode pilot, re-evaluate the saved adaptive checkpoints before
continuing:

```powershell
python -m scripts.reevaluate_adaptive_checkpoints `
  --results results/gate_learning_beta5591_pilot `
  --episodes 75,100,125,150,175,200 `
  --device cuda
```

The audit first applies gate-validity checks, then ranks valid adaptive
checkpoints by true deprivation, fill rate, and reward. Fixed guidance remains
the guided baseline unless an adaptive checkpoint is no worse on all logistics
measures. The locked 40-seed performance benchmark subsequently passed every
predeclared promotion check, so production is now fixed guidance
(`g=0.5`, `beta=5.591`). See
`results/fixed_vs_unguided_final_benchmark/promotion_decision.json`.
Adaptive guidance remains rejected and excluded from promotion.

## Recommended order

Run the repository tests, calibrate, store the recommended beta in a
PowerShell variable, run a 200-episode pilot, validate it, render the standard
figures, and run the acceptance audit. Proceed to a new longer run only if the
pilot is accepted. Never resume a beta-1 guided checkpoint with beta 5.591;
the loader rejects that mismatch by design.
