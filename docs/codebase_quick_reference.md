# Belief-Graph Guided MAPPO–ALNS: quick reference

All paths below are relative to `D:\Post-disaster Logistics\code`.

| If you want to… | Start here | Then inspect |
|---|---|---|
| Change the simulated logistics rules or reward | `src/env/uav_env.py` | `entities.py`, `events.py`, `belief.py`, `energy.py`, `deprivation.py` |
| Change which actions are legal | `UAMTVRPIUEnv._action_mask` | `_leg_feasible`, `_c5_ok`, `decode_action` |
| Change ALNS plan construction | `src/env/alns_scaffold.py` | `UAMTVRPIUEnv._plan_context`, `_solve_scaffold` |
| Change graph node/edge/plan features | `src/methods/belief_graph.py` | `OperationalBeliefGraphBuilder.build_from_env` |
| Change graph neural-network architecture | `src/methods/graph_networks.py` | `BeliefGraphEncoder`, `GraphMAPPOActor` |
| Change the gate equation or guidance strength | `GraphMAPPOActor.forward` | YAML: `alns_guidance.beta`, `fixed_gate` |
| Change PPO or trajectory storage | `src/agents/mappo_agent.py` | `select_actions`, `record_*`, `update` |
| Run ordinary training | `scripts/train_mappo.py` | `run_episode`, `main` |
| Diagnose an adaptive gate | `scripts/diagnose_adaptive_gate.py` | `src/methods/adaptive_gate_diagnostics.py` |
| Run the matched fixed-vs-adaptive study | `scripts/run_gate_learning_development.py` | `validate_gate_learning_development.py` |
| Change experiment defaults | `configs/agent/belief_graph_guided.yaml` | development/diagnostic YAMLs |

## What is active

The runnable method is the `src/env` + `src/agents` + `src/methods` stack. `scripts/train_mappo.py` is the normal entry point; `run_gate_learning_development.py` drives the explicit fixed-versus-adaptive experiment. `results/` and `outputs/` are generated artifacts, not source of truth.

## Vocabulary

* **Operational / belief-side**: reports, estimated demand, known corridors, inventory, UAV state, and elapsed time. These may enter the actor.
* **Physical truth**: actual unmet demand/cohorts and truth-derived deprivation. It is excluded from the actor/graph, but `get_global_state()` deliberately gives it to the centralized critic during training.
* **Scaffold**: the incumbent ALNS plan (`Scaffold → Sortie → PlannedVisit`). It is a recommendation, not a command.
* **FOLLOW**: execute the next planned visit. The ALNS prior is one-hot only for this action when it is operationally legal.

## Run sequence

`train_mappo.py → run_episode → env.reset → graph build → agent.select_actions → env.step → agent.record_reward → agent.update → checkpoint`.

The development study additionally runs: common initialization → copy verification → fixed branch → adaptive branch → validation → matched-state/counterfactual analysis → verdict → plots/hashes.
