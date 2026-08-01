"""
UA-MTVRP-IU environment package.

Implements the System Model of the manuscript (manuscript/sections/system_model.tex):
an uncertainty-aware multi-trip VRP with information updates, formulated as a
cooperative, event-driven, partially observable semi-Markov decision process.

Modules
-------
params              All model parameters, named after manuscript symbols.
energy              UAV energy model (eq:flight_energy .. eq:safe_return_constraint).
deprivation         Deprivation cost f_k, closed-form interval integrals, urgency.
entities            Cohorts, node truth state, UAV state, depot inventory.
belief              Shared belief state B(t) and P1/P2/P4 update rules.
graph               Time-varying graph G(t): hazard/wind fields, edge attributes.
scenario            Scenario container (pre-sampled exogenous timeline) + JSON I/O.
scenario_generator  Seeded, feasibility-aware scenario ("map") generation.
events              Typed events and the deterministic event queue.
alns_scaffold       ALNS route-and-loading scaffold Pi^ALNS, plan divergence.
metrics             Episode objectives J_true, J_belief, J_energy, J_risk, J_fair.
uav_env             UAMTVRPIUEnv: the event-driven SMDP environment.
"""

from .params import EnvParams  # noqa: F401
