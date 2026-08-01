# Belief-Graph Guided MAPPO-ALNS

This optional method extends the active event-driven `UAMTVRPIUEnv`,
`ALNSPlanner`, and `MAPPOAgent`. It does not create a second simulator or
change actions, masks, rewards, event timing, FOFS service, ALNS operators, or
the PPO objective. Vanilla MAPPO remains the default.

## Operational belief graph

`OperationalBeliefGraphBuilder` builds a padded directed graph at each decision
epoch from `BeliefState` (active simulator) or `ControllerState`
(scenario-v2 audit). Unknown affected locations have masked padding slots and
no entity-ID mapping until P2 reception. Stable slots are
`UAVs | DEPOT | physical node index`, so adding a known node does not renumber
existing entities.

Affected-node features, in stored order, are four reported remaining-demand
slots, the four-slot active-commodity mask, cohort/deprivation-model urgency,
one-hour urgency growth, oldest operational cohort age and quantity, reported
vulnerability, report information age measured from generation time, report
confidence, normalized coordinates, known/active status, resource/status
fields, total operational demand, and operational cohort count. The active
legacy belief state has an estimated onset per commodity rather than explicit
cohort objects; its oldest-age and urgency fields use that existing
approximation. Scenario-v2 uses the explicit operational cohorts.

UAV nodes contain observable payload, position, battery, remaining
service/travel time, mode, committed destination, and payload mass. The depot
contains operational inventory, normalized location, bay utilization, and
resource availability.

Directed corridor edges contain believed condition
`NORMAL/DEGRADED/CLOSED/UNKNOWN`, believed directional time and energy,
believed risk, corridor report age, static feasibility, UAV-relation type, and
operational availability. The scenario-v2 values use the stored
direction-specific wind, climb/descent, and nominal-energy results. A hidden
physical closure or degradation cannot alter these values before its notice.
The active environment caches its initial operational risk assessment so later
physical hazard-field evolution is not read by the method.

All normalizations use fixed repository units or configuration references:
demand `/10`, positions `/region width`, time and age `/mission horizon`,
energy `/battery capacity`, payload `/capacity`, vulnerability `/3`, and
urgency `log1p(.)/8`. No per-seed extrema are used.

The pure-PyTorch encoder uses type-specific input projections, a node-type
embedding, directed edge key/value projections, masked multi-head attention,
two or more message-passing layers, masked mean pooling, and UAV-query
attention. It is permutation equivariant to affected-node ordering.

The graph actor receives:

```text
[existing own-UAV block,
 encoded UAV node,
 UAV-specific graph context,
 existing observable fleet/event remainder]
```

It intentionally skips the existing flat node block. The graph critic receives
only pooled operational graph, operational UAV-node summary, and operational
depot summary. Unlike the historical vanilla critic, it receives no latent
global-state tensor.

## ALNS prior and adaptive gate

The real action head is flat:

```text
FOLLOW, RETURN, REQUEST_RESOLVE,
INSERT(i), SKIP(i), SWAP(i, u')
```

The prior is one at `FOLLOW` only when the incumbent's exact next visit exists
and passes the current operational leg-feasibility check; otherwise it is all
zero. There are no partial-match heuristics.

Each UAV receives these individual plan features:

```text
plan_age
operational_demand_change
operational_inventory_change
newly_known_fraction
invalid_planned_corridor_fraction
completed_planned_service_fraction
execution_deviation
solver_active
solver_request_age
next_action_operationally_feasible
```

They compare current operational state with snapshots stored at incumbent
creation. They never compare against physical truth. The adaptive gate is an
MLP trained only through PPO:

```text
g = sigmoid(MLP(plan_features))
z_hybrid = z_MAPPO + beta * g * b_ALNS
z_masked = operational_action_mask(z_hybrid)
```

Masking is last, so positive guidance cannot restore an unavailable action.
Fixed guidance uses the configured constant; no guidance uses zero.

The active repository's ALNS solve is synchronous. It has no background worker
or incumbent-completion callback to reuse. The method therefore exposes
`solver_active` and `solver_request_age` with truthful synchronous values
(normally zero at a decision epoch) and does not invent asynchronous behavior.
All existing incumbent adoption semantics are preserved.

## Modes and commands

The four modes are:

```text
vanilla_mappo
graph_mappo
graph_mappo_fixed_alns
graph_mappo_adaptive_alns
```

Examples:

```powershell
python scripts/train_mappo.py --mode vanilla_mappo --episodes 1 --smoke --skip-eval
python scripts/train_mappo.py --mode graph_mappo --episodes 1 --smoke --skip-eval
python scripts/train_mappo.py --mode graph_mappo_fixed_alns --episodes 1 --smoke --skip-eval
python scripts/train_mappo.py --mode graph_mappo_adaptive_alns --episodes 1 --smoke --skip-eval
python scripts/train_mappo.py --agent-config configs/agent/belief_graph_guided.yaml --episodes 1 --smoke --skip-eval
python -m scripts.audit_belief_graph
```

Decision diagnostics are written under `results/logs`, and version-2
checkpoints under `results/models`. New checkpoints include actor, critic,
graph encoder, gate, optimizers, mode, feature schemas, and normalization
description. Checkpoints without a mode are treated as legacy vanilla
checkpoints and remain loadable only in vanilla mode. Loading a checkpoint in
the wrong method mode fails explicitly.

## Truth-exclusion contract

The active builder reads truth objects only for public static coordinates.
It reads demand and vulnerability only through `BeliefState`, availability
only through operational notices, and risk only through the cached operational
assessment. The audit builder selects only static geography/corridor geometry
plus `ControllerState`. It cannot access physical demand, true vulnerability,
unreceived reports, physical corridor conditions, or future events. Tests
mutate latent demand and vulnerability at the same decision epoch and require
graph tensors, plan features, masks, and actor inputs to remain unchanged.

Seed 18427 is an information-boundary fixture, not performance evidence.
`scripts/audit_belief_graph.py` strictly checks 3.7, 4.2, 4.8, 5.0, and 5.1 h.
Scenario-v2 has no live ALNS incumbent, so plan-change/gate behavior is tested
in the active simulator and smoke rollouts rather than fabricated in replay.
