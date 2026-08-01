# Beginner-friendly codebase function map

Paths and line spans below were inspected in the current repository on 2026-07-25. “Active” means reachable from the listed CLI scripts/imports, not merely present on disk.

## File inventory

| File | Category | Main responsibility | Called by | Calls | Active? |
|---|---|---|---|---|---|
| `src/env/uav_env.py` | Production | Event-driven UAV logistics world, masks, observations, rewards | training/diagnostic/development scripts | belief, events, energy, ALNS, graph builder | Yes; critical |
| `src/env/alns_scaffold.py` | Production | Plan objects and ALNS-style incumbent solver | `uav_env` | energy/deprivation | Yes; critical |
| `src/env/belief.py` | Production | Report-derived belief entries and known-node state | `uav_env`, graph builder | — | Yes |
| `src/env/entities.py` | Production | UAV, inventory, true-node, cohort data models | environment | — | Yes |
| `src/env/events.py` | Production | Event types and priority queue | environment | — | Yes |
| `src/env/graph.py` | Production | Corridor availability/risk and geometry | environment | — | Yes |
| `src/env/params.py` | Production/config model | Nested environment parameter dataclasses/constants | all runners/environment | — | Yes |
| `src/env/scenario.py`, `scenario_generator.py` | Production | Scenario schema and seeded scenario generation | runners/environment | graph/events | Yes |
| `src/env/energy.py`, `deprivation.py` | Production | Physical energy and objective/urgency calculations | env, ALNS, graph builder | — | Yes |
| `src/env/observation_contract.py` | Production | Feature ordering constants for flat observations | `uav_env` | — | Yes |
| `src/methods/belief_graph.py` | Production | Belief graph schema, builder, plan confidence and prior | env/agent/tests | belief urgency/energy | Yes; critical |
| `src/methods/graph_networks.py` | Production | Graph tensors, GNN, graph actor/critic, gate | `mappo_agent` | PyTorch | Yes; critical |
| `src/agents/networks.py` | Production | Older flat Transformer actor/critic | `mappo_agent` in flat mode | PyTorch | Yes, flat ablation |
| `src/agents/mappo_agent.py` | Production | MAPPO selection, buffer, PPO, checkpoints | runners | networks/graph networks | Yes; critical |
| `src/agents/baselines.py` | Production baseline | Random/EDF/urgency/pure-ALNS baselines | `train_mappo` | env | Yes, optional |
| `src/methods/adaptive_gate_diagnostics.py` | Diagnostic | Gate evidence, counterfactuals, reports | diagnostic runners/tests | NumPy/YAML | Diagnostic-only |
| `src/methods/gate_learning_development.py` | Experiment infrastructure | Seed splits, regime/matched-state metrics, verdict helpers | development/validation | diagnostics | Yes, development study |
| `scripts/train_mappo.py` | CLI | Standard training/evaluation loop | user command | env/agent/baselines | Yes |
| `scripts/diagnose_adaptive_gate.py` | CLI | Diagnostics collection | user command | train helpers/diagnostics | Diagnostic-only |
| `scripts/plot_adaptive_gate_diagnostics.py` | CLI | Plot diagnostic CSV/JSON | user command | matplotlib | Diagnostic-only |
| `scripts/run_gate_learning_development.py` | CLI | Common-init fixed/adaptive experiment | user command | env/agent/development helpers | Yes, study |
| `scripts/validate_gate_learning_development.py` | CLI | Independent evidence and verdict | user command | development runner/helpers | Yes, study |
| `scripts/plot_gate_learning_development.py` | CLI | Plot study artifacts | user command | matplotlib | Study output only |
| `configs/agent/*.yaml` | Configuration | Method, diagnostics, development thresholds | selected CLI arguments | — | Active when selected |
| `tests/test_belief_graph_method.py` | Test | Graph schema/truth-boundary/encoder checks | pytest | env/methods | Test only |
| `tests/test_guided_mappo.py` | Test | Guided actor/PPO/checkpoint checks | pytest | agent/env | Test only |
| `tests/test_adaptive_gate_diagnostics.py` | Test | Diagnostic/counterfactual/plot checks | pytest | diagnostics | Test only |
| `tests/test_gate_learning_development.py` | Test | Development metrics/copy/plot checks | pytest | development runners | Test only |

## Data structures and feature contracts

`BeliefGraph` (`belief_graph.py:108–157`) owns NumPy arrays for nodes, directed edges, masks, entity/slot mappings, action mappings, ALNS prior, and plan features. Node features have **32** ordered dimensions and edge features **11**; their exact names are in `codebase_function_map.json` and `belief_graph.py:30–90`. Plan features have **10** dimensions, in this exact order: `plan_age`, `operational_demand_change`, `operational_inventory_change`, `newly_known_fraction`, `invalid_planned_corridor_fraction`, `completed_planned_service_fraction`, `execution_deviation`, `solver_active`, `solver_request_age`, `next_action_operationally_feasible`.

Graph node values are operational: UAV status/payload, depot stock, and belief entries/reports. Unknown affected nodes are masked. Corridor condition is read from the operational graph. The builder explicitly documents that demand and vulnerability come only from `env.belief` (`build_from_env:226–231`). True demand/cohorts are never graph features. In contrast, `UAMTVRPIUEnv.get_global_state` (`1053–1072`) appends `d_true` and true deprivation rate to the **critic** state—this is centralized training information, not actor observation.

## Important API map

### `UAMTVRPIUEnv.reset(scenario=None, seed=None)`

**File:** `src/env/uav_env.py` — **Lines:** 119–238  
**Purpose:** initializes a complete episode and advances to its first decision event.  
**Called by:** `train_mappo.run_episode`, development `_run_episode`, diagnostics collectors, tests. **Calls:** scenario generation/reset setup, `_solve_scaffold`, `_begin_turnaround`, `_advance`.  
**Inputs/returns:** optional `Scenario`/seed → `{uav_id: actor_observation}`, `{masks, deciders, t}`.  
**Writes:** time, true/belief/environment state, event queue, scaffold, metrics and mask cache. **Side effects:** seeded RNG/event scheduling.  
**Tests/config:** environment and guided-MAPPO tests; `EnvParams`.

### `UAMTVRPIUEnv.step(actions)`

**File:** `src/env/uav_env.py` — **Lines:** 243–303  
**Purpose:** applies all current UAV decisions and calculates the reward until the next decision epoch.  
**Called by:** all episode loops. **Calls:** `decode_action`, `_solve_scaffold`, `Scaffold.remove_node/insert_next`, `_apply_movement`, `_advance`.  
**Inputs/returns:** `{uav: flat_action}` → `(next_obs, reward, done, info)`.  
**Reads/writes:** mask cache, scaffold, event queue and interval reward accumulators; invalid choices are converted to FOLLOW with violation penalty. **Controller information only?:** no (environment transition).

### `UAMTVRPIUEnv._action_mask(u)` / `_leg_feasible(u,node)` / `_c5_ok(u,node)`

**File:** `src/env/uav_env.py` — **Lines:** 645–708  
**Purpose:** declares legal flattened actions using known-node (C1), corridor availability (C2), demand/cargo/stock (C3/C6), and safe return energy (C5).  
**Called by:** `_advance`, training runners, graph guidance. **Returns:** Boolean `[action_dim]`; FOLLOW/RETURN always legal and RESOLVE requires budget. **Relevant tests:** `test_guided_mappo.py`; **configuration:** hybrid budget/penalty and physics parameters.

### `UAMTVRPIUEnv._solve_scaffold(initial=False)` and `_plan_context()`

**File:** `src/env/uav_env.py` — **Lines:** 780–842  
**Purpose:** constructs an operational planning snapshot, calls ALNS, and records snapshots for divergence features.  
**Calls:** `ALNSPlanner.solve`; **writes:** `scaffold.created_t`, belief/inventory/known-node snapshots and planned service count. **Important assumption:** no true demand is passed; `PlanContext` is belief-side.

### `UAMTVRPIUEnv.get_operational_belief_graph()` / `_build_obs(u)` / `get_global_state()`

**File:** `src/env/uav_env.py` — **Lines:** 808–814, 1045–1072  
**Purpose:** exposes respectively graph actor data, flat actor data, and critic data. **Calls:** `OperationalBeliefGraphBuilder.build_from_env`; flat observation helpers. **Returns:** `BeliefGraph`, actor vector, critic vector. **Important assumption:** only the third includes truth and must not be passed to the policy.

### `ALNSPlanner.solve(ctx,rng,warm=None)` and helpers

**File:** `src/env/alns_scaffold.py` — **Lines:** 203–509  
**Purpose:** builds/refines `Scaffold(plans)` from `PlanContext`. **Calls:** `_construct`, `_absorb_warm`, `_extend_plan`, `_destroy_repair`, `_evaluate`, `_finalize`. **Returns:** an incumbent plan of `Sortie`/`PlannedVisit`. **Side effects:** uses provided RNG only. `plan_divergence` (`513–545`) compares current operational state with scaffold snapshots.

### `OperationalBeliefGraphBuilder.build_from_env(env)`

**File:** `src/methods/belief_graph.py` — **Lines:** 226–490  
**Purpose:** converts the live operational environment into a padded graph and guidance payload. **Calls:** `_active_action_mappings`, `_plan_guidance`, belief urgency and flight-energy functions. **Returns:** `BeliefGraph`. **Reads:** public coordinates, `env.belief`, operational availability/risk, UAV/depot/scaffold state. **Writes:** no environment state. **Relevant tests:** graph method truth-exclusion/schema tests.

### `OperationalBeliefGraphBuilder._plan_guidance(env)`

**File:** `src/methods/belief_graph.py` — **Lines:** 530–655  
**Purpose:** emits normalized ten-feature confidence vector plus one-hot ALNS prior per UAV. **Returns:** `[M,10]` features, `[M,A]` priors, recommendations and audit metadata. **Prior is nonzero only when:** a next planned visit exists and `_leg_feasible` confirms known target, available corridor, and C5 safety; the single `A_FOLLOW` slot is then set to one. **Zero reasons actually emitted by this active builder:** `RECOMMENDATION_ALREADY_COMPLETED`, `NO_UAV_RECOMMENDATION`, `RECOMMENDATION_INVALID`, or default `OTHER`; the alternate `build_from_controller` compatibility path emits `NO_INCUMBENT_PLAN`. The function does not separately label every C1/C2/C5 failure. **Side effects:** none.

### `TorchBeliefGraphBatch.collate(graphs,device)` and `BeliefGraphEncoder.forward(graph)`

**File:** `src/methods/graph_networks.py` — **Lines:** 34–81 and 197–222  
**Purpose:** converts padded NumPy graphs to tensors, then uses edge-aware attention layers to obtain node and pooled graph embeddings. **Called by:** agent selection/update. **Inputs/returns:** graph list → tensor batch; tensor batch → `(encoded_nodes, pooled_embedding)`. **Writes:** no environment state; gradients flow through encoder parameters.

### `GuidanceGate.logits(plan_features)` / `forward(plan_features)`

**File:** `src/methods/graph_networks.py` — **Lines:** 225–241  
**Purpose:** `Linear(10,hidden) → ReLU → Linear(hidden,1)`, then sigmoid. **Inputs/returns:** `[B,10]` → `[B,1]` logit or gate. **Controller information only?:** yes; inputs are operational plan features.

### `GraphMAPPOActor.forward(obs, graph, uav_ids, action_mask, plan_features, alns_prior)`

**File:** `src/methods/graph_networks.py` — **Lines:** 303–359  
**Purpose:** produces action probabilities/logits from local observation and graph context, then optionally guides them with ALNS. **Calls:** graph encoder and gate. **Returns:** probabilities, masked logits, selected gate, base logits, attention. **Writes:** detached `last_gate_logit`, `last_adaptive_gate`, `last_hybrid_logits` for diagnostics. **Side effects:** no sampling; no RNG. **Equation/mask:** documented in `codebase_call_graph.md`. Fixed mode uses `torch.full(..., fixed_gate)`, normally `0.5`; adaptive selects sigmoid output; none selects zero.

### `MAPPOAgent.select_actions(...)`, `record_decisions(...)`, `record_reward(...)`, `_close(...)`

**File:** `src/agents/mappo_agent.py` — **Lines:** 170–306  
**Purpose:** batch deciders, sample/choose actions, and convert irregular per-UAV decision intervals into PPO transitions. **Calls:** graph collation/actor/critic/Categorical. **Inputs:** per-UAV actor obs/masks, global critic state, optional graph. **Writes:** `_Pending` buffers and `trajectories`; stores action, old log probability, critic value, decision time, graph, UAV ID, plan features and prior. **Side effects:** categorical RNG when nondeterministic.

### `MAPPOAgent.update(diagnostics=None, diagnostic_context=None)`

**File:** `src/agents/mappo_agent.py` — **Lines:** 311–582  
**Purpose:** computes time-aware returns/GAE and performs PPO minibatch gradient updates. **Calls:** actor/critic forward, Categorical log-probability/entropy, `backward`, gradient clipping, Adam `step`. **Reads:** trajectories. **Writes:** model/optimizer parameters, optional diagnostic update rows; clears trajectory buffers. **Relevant tests:** guided MAPPO architecture/checkpoint/update tests. **Configuration:** learning rates, GAE lambda, clip parameter, entropy coefficient, update epochs.

### `run_episode(...)` / `load_agent_config(path)`

**File:** `scripts/train_mappo.py` — **Lines:** 65–221  
**Purpose:** adapter between environment and agent; maps nested YAML method fields to `MAPPOAgent` kwargs. **Calls:** reset, graph builder, select/record/step/end. **Important behavior:** YAML `observation_encoder: belief_graph` and `alns_guidance: adaptive|fixed|none` select the graph modes.

### Diagnostics and development functions

**`counterfactual_policy`** (`adaptive_gate_diagnostics.py:188–229`) recomputes masked base/adaptive/fixed distributions with supplied vectors; **`build_decision_diagnostic`** (`282–536`) records operational evidence; **`AdaptiveGateDiagnostics.write`** (`1055–1152`) writes CSV/JSON/JSONL-gz outputs; **`assert_truth_exclusion`** (`1155–1161`) rejects prohibited truth keys.

**`evaluate_matched_states`** (`gate_learning_development.py:472–552`) forwards the actor on stored matched vectors; **`select_gate_learning_verdict`** (`583–669`) applies evidence thresholds. The runner’s `_copy_initialization` (`run_gate_learning_development.py:285–293`) copies weights so branch comparison starts identical; `_train_branch` (`669–786`) trains/evaluates/checkpoints each branch. Validation `_collect_validation` (`validate_gate_learning_development.py:241–323`) and `_validation_metrics` (`406–559`) create independent evidence and verdict input.

## Tests as navigation

Use `test_belief_graph_method.py` for feature order, graph construction, and truth-exclusion expectations; `test_guided_mappo.py` for mask/gate/PPO/checkpoint behavior; `test_adaptive_gate_diagnostics.py` for diagnostic report semantics; and `test_gate_learning_development.py` for branch equality, matching, verdict, and plotting expectations.
