# Adaptive-gate diagnostics

This subsystem diagnoses the existing confidence-adaptive ALNS guidance gate
without changing the policy, PPO objective, reward, environment, masks, action
semantics, ALNS operators, gate dimensions, `beta`, or fixed-gate value.

## Exact implementation

The gate is:

```text
gate_logit = Linear64to1(ReLU(Linear10to64(plan_features)))
gate_adaptive = sigmoid(gate_logit)
```

The actor then selects the configured branch:

```text
adaptive mode: gate = gate_adaptive
fixed mode:    gate = 0.5
no guidance:  gate = 0
guided = base_logits + beta * gate * alns_prior
masked = guided.masked_fill(operational_mask == 0, -1e8)
```

The default `beta` is `1.0`. The prior is exactly one at `FOLLOW` when the
incumbent next visit exists and passes current operational C1/C2/C5 checks,
and zero elsewhere. No partial-match heuristic exists.

The ten gate inputs and their authoritative definitions are exported to
`adaptive_gate_feature_schema.json`. They are, in order:

1. `plan_age`
2. `operational_demand_change`
3. `operational_inventory_change`
4. `newly_known_fraction`
5. `invalid_planned_corridor_fraction`
6. `completed_planned_service_fraction`
7. `execution_deviation`
8. `solver_active`
9. `solver_request_age`
10. `next_action_operationally_feasible`

All inputs are operational-only ratios or binary values clipped to `[0,1]`.
Raw pre-clipping inputs, normalized gate inputs, clipping flags, default flags,
feature indices, and normalization references are logged separately.

## Behavior preservation

Diagnostics consume detached copies after the exact actor tensors exist.
They perform no action sampling, environment transition, backward call, or
optimizer operation. PPO diagnostics read gradients after `backward()` and
before gradient clipping; parameter movement is measured from tensors copied
immediately before and after the existing optimizer step.

The automated Stage-A audit restores the RNG state around diagnostics-off and
diagnostics-on calls and requires identical actions, log probabilities, value,
gate logit, and gate values. Unit tests additionally require identical losses,
gradients, and parameter updates.

## Protocol

Run:

```powershell
python -m scripts.diagnose_adaptive_gate `
  --agent-config configs/agent/belief_graph_guided.yaml `
  --diagnostic-config configs/agent/adaptive_gate_diagnostics.yaml `
  --seed 18427 `
  --episodes 10 `
  --evaluation-seeds 100 2026 `
  --output-dir results/adaptive_gate_diagnostics

python -m scripts.plot_adaptive_gate_diagnostics `
  --diagnostics results/adaptive_gate_diagnostics `
  --output-dir results/adaptive_gate_diagnostics/figures
```

Stage A verifies forward algebra, mask precedence, prior mapping, and
diagnostics-on/off identity. Stage B trains for ten short one-hour episodes
using five deterministic scenario seeds and the existing hyperparameters.
The shortened mission horizon and ten-iteration ALNS solve are diagnostic
runtime overrides recorded in `metadata.json`; they are not changed training
defaults. Stage C evaluates the same stored decision states counterfactually
under no, fixed, and adaptive guidance using the final adaptive checkpoint.

The diagnostic CLI fixes CPU BLAS execution to one thread and enables
PyTorch deterministic algorithms. This is scoped to the diagnostic process:
it prevents low-order parallel-reduction differences from changing a later
categorical draw, without changing the policy equation or repository training
defaults.

Controlled profiles test network sensitivity only. No monotonic response is
assumed, and no probe is performance evidence.

## Synchronous ALNS limitation

ALNS is synchronous in this repository. Consequently, decisions normally
observe `solver_active=0` and `solver_request_age=0`. Diagnostics identify
these inputs as constant and emit `SYNCHRONOUS_ALNS_FEATURE_LIMITATION`; they
do not fabricate solve durations or background activity.

## Outputs

The main CSV contains decision summaries. Exact per-action logits,
probabilities, masks, and priors are stored in deterministic gzip JSONL files.
PPO gate gradients and parameter updates have their own CSV. Feature summaries,
controlled probes, automatic evidence classifications, reproducibility hashes,
and ten question-specific figures are generated in the selected output
directory.

None of these diagnostics establishes reward or performance superiority.
