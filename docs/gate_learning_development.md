# Adaptive-gate learning development experiment

This experiment trains the 10-to-64-to-1 sigmoid guidance gate with PPO plus a
configured paired directional hinge term. The correction was introduced after
the return-only run learned a stronger gate for stale plans and supplied no
usable `FRESH_AND_STABLE` decisions. It is methodology-development evidence,
not a final benchmark or superiority experiment.

## Invariants

The experiment preserves the repository's:

- actor, critic, graph encoder, gate architecture, and feature ordering;
- fixed gate `0.5`; guidance `beta` is explicit, centrally recorded, and
  defaults to `1.0` unless a calibrated pilot overrides it;
- one-hot prior on the exact operationally feasible `FOLLOW` action;
- reward, PPO clipping, masks, action space, ALNS operators, event
  transitions, report process, and demand process.

Only the adaptive branch receives the configured directional term. It compares
a fresh feasible plan-status vector with six adverse observable variants and
their combined variant. It requires `g_fresh - g_stale >= 0.10`; it does not
use a regime label, scenario truth, an outcome occurring after the decision,
or a new policy input.

Regime labels are written only after policy decisions. They are never placed in
observations, belief graphs, masks, actor/critic inputs, or gate inputs.
`solver_active` and `solver_request_age` remain truthful synchronous-solver
features and are excluded from the primary direction criteria.

## Seed split and operational fixtures

Training uses seeds 18440-18479. Validation uses 18480-18489. Seed 18427 is
reserved for a qualitative information-boundary replay and is excluded from
training and development metrics.

The seven target regimes cycle deterministically across episodes. Before
`env.reset`, the base seeded scenario is copied into a deterministic recorded
fixture. Observable events are suppressed and only the assigned P1, P2,
replenishment, or mixed intervention is installed. A partially invalid plan
uses a deterministic later incumbent-plan closure selected once before any
algorithm action. The execution-deviation fixture installs two early P1
decision events so an in-flight UAV can be observed without forcing an actor
action.

The incumbent is refreshed after initial loading. This removes the structural
inventory mismatch that previously made the first usable decision stale.
`FRESH_AND_STABLE` refreshes the incumbent at each decision and contains no
scripted observable exogenous changes. Every intervention is constructed
before replay and uses no runtime random sampling.

Actual decision labels still require the corresponding operational feature.
Training and validation fail explicitly when the configured number of
prior-bearing, feasible fresh decisions is absent. All other assigned regimes
must also produce usable decisions; target names never fabricate support.

## Runtime bounds

An unmodified 12-hour, 60-ALNS-iteration CPU episode did not finish within
604.1 seconds. The recorded development configuration therefore uses a
one-hour mission horizon and ten ALNS iterations. These are transparent
methodology-development runtime bounds, not silent tuning. All regime coverage,
prior-count, stability, truth-exclusion, and policy-distance requirements
remain mandatory.

## Final protocol

Run from the repository's `code` directory:

```powershell
$env:KMP_DUPLICATE_LIB_OK='TRUE'
python -m scripts.run_gate_learning_development `
  --agent-config configs/agent/belief_graph_guided.yaml `
  --experiment-config configs/agent/gate_learning_development.yaml `
  --output-dir results/gate_learning_final `
  --max-episodes 1000 `
  --min-episodes 200 `
  --device cuda

python -m scripts.validate_gate_learning_development `
  --results results/gate_learning_final `
  --extension-repeats 4

python -m scripts.plot_gate_learning_development `
  --results results/gate_learning_final `
  --output-dir results/gate_learning_final/figures
```

Use `--resume` only to continue checkpoints created by this corrected
fixture protocol. A checkpoint created before
`operational-regime-fixtures-v1` is rejected; start in a new output directory
from shared initialization instead.

The shared graph-MAPPO initialization is trained first. Fixed and adaptive
agents receive identical actor, critic, graph-encoder, optimizer, and
normalization components, verified by hashes before either guided branch
trains. Their training seed order and branch RNG start are identical.

Validation runs deterministic trajectories on all validation seeds, then adds
explicitly labelled reproducible stochastic state-collection rollouts.
Duplicate operational states are removed. Because the gate consumes only plan
features, the canonical fresh-versus-combined-stale probe is reported as one
exact deterministic contrast, not as thousands of duplicated bootstrap
observations.

## Verdicts

Exactly one of the following is emitted:

- `KEEP_EXISTING_ADAPTIVE_GATE`
- `GATE_LEARNED_POLICY_INERT`
- `MORE_TRAINING_REQUIRED`
- `WRONG_DIRECTION_GATE`
- `ACTOR_GATE_IDENTIFIABILITY_PROBLEM`
- `FIXED_GUIDANCE_SUFFICIENT`
- `TRAINING_OR_IMPLEMENTATION_FAILURE`

`MORE_TRAINING_REQUIRED` is available only when separation is moving in the
correct nonnegative direction. A negative exact fresh-minus-stale contrast
after at least 200 episodes produces `WRONG_DIRECTION_GATE`.
`GATE_LEARNED_POLICY_INERT` is emitted when the planned duration is complete,
the gate has learned the required direction, but adaptive-versus-fixed policy
TV and argmax changes remain below the development thresholds. This separates
an insufficient logit intervention from insufficient gate learning.
`KEEP_EXISTING_ADAPTIVE_GATE` additionally requires the adaptive branch to be
no worse than fixed guidance on true deprivation, fill rate, and reward. A
diagnostically valid gate that fails that logistics comparison produces
`FIXED_GUIDANCE_SUFFICIENT`; gate diagnostics alone do not select a checkpoint.
