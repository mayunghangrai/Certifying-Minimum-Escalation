"""
UAMTVRPIUEnv — the UA-MTVRP-IU event-driven SMDP environment
(manuscript secs: event_process, constraints, objective, termination).

Decisions occur at an ordered sequence of nonuniform event times
(eq:event_times). At each decision event the deciding UAVs receive
observations o_u (eq:agent_observation) and select from the high-level
action set {FOLLOW, INSERT(i), SKIP(i), SWAP(i,u'), RETURN, REQUEST_RESOLVE}
(eq:high_level_actions) masked by feasibility constraints C1-C6 (eq:cst_*).
The cooperative reward over each event interval is
    r_n = -int C_hat dt - xi_E E_n - xi_R R_n - xi_C 1{RESOLVE} - P_viol
(eq:event_reward), with the deprivation integral computed in closed form.

Partial observability: the policy sees only the shared belief B(t); the
latent truth drives outcomes and the evaluation objective J_dep_true
(eq:true_objective). P3 mutations and demand onsets are silent — they are
not decision events and are excluded from phi_event.

Design notes (documented simplifications within the manuscript's degrees of
freedom):
  * Arrival at a node starts the delivery maneuver automatically; the
    arrival's decision is realized at the delivery-completion event a short
    dwell later. Depot return triggers a decision on arrival, and loading/
    charging completion triggers another (eq:event_times lists all of these).
  * Flying UAVs may divert mid-leg when an information event arrives
    (P1/P2/P4/availability): energy and risk are settled pro-rata at the
    diversion point.
  * Recharge duration scales with the battery deficit:
    T_charge_eff = T_charge * (B_max - b)/B_max (T_charge = full recharge).
  * Realized legs fly straight lines from the UAV's current position; when
    path_mode = "field_astar", node-to-node planning lengths use the
    discretized weighted-path functional (eq:feasible_path).
"""

from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from .alns_scaffold import (ALNSPlanner, PlanContext, PlannedVisit, Scaffold,
                            Sortie, UAVPlanStart, plan_divergence)
from .belief import BeliefState
from .deprivation import (belief_deprivation_integral, belief_deprivation_rate,
                          belief_urgency, true_deprivation_integral,
                          true_deprivation_rate, true_urgency)
from .energy import flight_energy, safe_return_energy, service_energy
from .entities import DepotInventory, Mode, NodeTruth, UAVState
from .events import (INFO_DECISION_TYPES, SILENT_TYPES, Event, EventQueue,
                     EventType)
from .graph import DEPOT, DynamicFields, ReliefGraph
from .metrics import EpisodeMetrics
from .observation_contract import (
    EVENT_FEATURE_ORDER,
    FLEET_FEATURE_ORDER,
    NODE_FEATURE_ORDER,
    OWN_FEATURE_ORDER,
)
from .params import N_COMMODITIES, EnvParams
from .scenario import Scenario
from .scenario_generator import generate_scenario

SERVICE_DWELL = 0.02        # descent-delivery-ascent duration [h]
EPS = 1e-9


class UAMTVRPIUEnv:
    """Cooperative, event-driven, partially observable SMDP (manuscript sec 2)."""

    # -- action layout ------------------------------------------------------
    A_FOLLOW = 0
    A_RETURN = 1
    A_RESOLVE = 2
    A_BASE = 3

    def __init__(self, params: Optional[EnvParams] = None):
        self.p = params or EnvParams()
        self.N = self.p.map.n_nodes
        self.M = self.p.mission.M
        self.n_actions = 3 + 2 * self.N + self.N * (self.M - 1)
        self.scenario: Optional[Scenario] = None

    # ------------------------------------------------------------------
    # Action encoding
    # ------------------------------------------------------------------
    def encode_insert(self, i: int) -> int:
        return self.A_BASE + i

    def encode_skip(self, i: int) -> int:
        return self.A_BASE + self.N + i

    def encode_swap(self, i: int, u: int, u_other: int) -> int:
        rank = u_other if u_other < u else u_other - 1
        return self.A_BASE + 2 * self.N + i * (self.M - 1) + rank

    def decode_action(self, u: int, a: int) -> Tuple[str, Optional[int], Optional[int]]:
        """Returns (kind, node, other_uav)."""
        if a == self.A_FOLLOW:
            return "FOLLOW", None, None
        if a == self.A_RETURN:
            return "RETURN", None, None
        if a == self.A_RESOLVE:
            return "REQUEST_RESOLVE", None, None
        a -= self.A_BASE
        if a < self.N:
            return "INSERT", a, None
        a -= self.N
        if a < self.N:
            return "SKIP", a, None
        a -= self.N
        i, rank = divmod(a, self.M - 1)
        other = rank if rank < u else rank + 1
        return "SWAP", i, other

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------
    def reset(self, scenario: Optional[Scenario] = None, seed: Optional[int] = None):
        if scenario is None:
            scenario = generate_scenario(seed if seed is not None else 0, self.p)
        self.scenario = scenario
        self.p = scenario.env_params()
        self.N = len(scenario.nodes)
        self.M = self.p.mission.M
        self.n_actions = 3 + 2 * self.N + self.N * (self.M - 1)
        phys = self.p.physics
        self.T = self.p.mission.T

        self.t = 0.0
        self.depot_pos = np.asarray(scenario.depot, dtype=float)
        self.fields = scenario.fields()
        self.graph = ReliefGraph(self.p, self.depot_pos,
                                 scenario.node_positions(), self.fields)

        # latent truth ---------------------------------------------------
        self.nodes: List[NodeTruth] = []
        for n in scenario.nodes:
            nt = NodeTruth(idx=n.idx, pos=np.array([n.x, n.y]), nu=n.nu,
                           onset_time=n.onset_time, reveal_time=n.reveal_time)
            self.nodes.append(nt)

        # shared belief ----------------------------------------------------
        self.belief = BeliefState(self.p.belief)

        # depot ------------------------------------------------------------
        self.inventory = DepotInventory(S0=np.asarray(scenario.S0_init, dtype=float))
        self._bay_free = [0.0] * self.p.mission.n_depot_bays

        # fleet --------------------------------------------------------------
        self.uavs = [UAVState(idx=u, pos=self.depot_pos.copy(), b=phys.B_max)
                     for u in range(self.M)]
        self._settled_t = [0.0] * self.M          # per-UAV energy settle time
        self._arrival_seq: List[Optional[int]] = [None] * self.M
        self._committed_x_plan: List[Optional[np.ndarray]] = [ None for _ in range(self.M)] #added 7/31
        self._in_turnaround = [False] * self.M
        self._load_done_t = [0.0] * self.M

        # events ---------------------------------------------------------------
        self.queue = EventQueue()
        self._rng_p4 = np.random.default_rng(scenario.p4_seed)
        self._rng_alns = np.random.default_rng(scenario.seed + 2000)
        # Independent deterministic RNG for counterfactual audit solves.
# It must never affect the operational ALNS RNG.
        self._rng_shadow_audit = np.random.default_rng(
            np.random.SeedSequence(
                [int(scenario.seed), 9001]
            )
        )
        self._corridor_report_generation: Dict[Tuple[int, int], float] = {}
        for n in scenario.nodes:
            if n.onset_time <= 0.0:
                for k in range(N_COMMODITIES):
                    self.nodes[n.idx].add_cohort(k, n.d0[k], 0.0)
            else:
                self.queue.push(Event(n.onset_time, EventType.DEMAND_ONSET,
                                      {"node": n.idx}))
            if n.reveal_time <= 0.0:
                self.belief.reveal(n.idx, np.array(n.mu0), np.array(n.sigma0),
                                   n.gamma0, n.onset_time, 0.0,
                                   n.nu if n.nu_reported is None else n.nu_reported)
            else:
                self.queue.push(Event(n.reveal_time, EventType.P2_REVEAL,
                                      {"node": n.idx}))
        for r in scenario.p1_reports:
            self.queue.push(Event(r.t, EventType.P1_REPORT,
                                  {"node": r.node, "eps": np.array(r.eps),
                                   "gamma": r.gamma}))
        for m in scenario.p3_mutations:
            self.queue.push(Event(m.t, EventType.P3_MUTATION,
                                  {"node": m.node, "delta": np.array(m.delta_d)}))
        for a in scenario.avail_changes:
            self.queue.push(Event(a.t, EventType.AVAIL_CHANGE,
                                  {"i": a.i, "j": a.j, "available": a.available}))
        for rp in scenario.replenishments:
            self.queue.push(Event(rp.t, EventType.REPLENISH,
                                  {"R": np.array(rp.R)}))
        self.queue.push(Event(self.T, EventType.HORIZON, {}))

        # objectives / accounting ------------------------------------------------
        self.metrics = EpisodeMetrics(delivered_units=np.zeros(N_COMMODITIES),
                                      generated_units=np.zeros(N_COMMODITIES))
        for n in scenario.nodes:
            self.metrics.generated_units += np.array(n.d0)
        self._last_integration_t = 0.0
        self._interval_belief_dep = 0.0     # int C_hat dt since last decision
        self._interval_energy = 0.0         # E_n
        self._interval_risk = 0.0           # R_n
        self._interval_resolve = False
        self._interval_viol = 0.0
        self._events_since: List[Dict[str, int]] = [
            {"P1": 0, "P2": 0, "P4": 0, "AVAIL": 0} for _ in range(self.M)]
        self.last_decision_event_type: Optional[EventType] = None
        self._invalid_legs = 0
        self._reveals_since_scaffold = 0
        self.done = False
        self.done_reason = ""
        self._action_mask_cache: Dict[int, np.ndarray] = {}

        # hybrid planning interface ------------------------------------------------
        self.K_rem = self.p.hybrid.K_max
 
        # Operational planner used by installed repair transactions.
        self.planner = ALNSPlanner(self.p)

        # Independent planner instance used only for counterfactual
        # evaluation of screened events.
        self._shadow_audit_planner = ALNSPlanner(self.p)
        self.alns_solving = False
        self.alns_request_t: Optional[float] = None
        # Exact ALNS-only accounting. The initial scaffold construction is
        # deliberately excluded from repair statistics.
        self.repair_solver_calls = 0
        self.repair_solver_wall_time_s = 0.0
        # Counterfactual audit accounting. These values must never be   
# included in operational repair-time or repair-call metrics.
        self.shadow_audit_solver_calls = 0
        self.shadow_audit_wall_time_s = 0.0

        location_ids = [DEPOT] + list(range(self.N))
        self._operational_edge_risk = {
            (i, j): self.graph.R(i, j, 0.0)
            for i in location_ids
            for j in location_ids
            if i != j
        }
        self.scaffold = self._solve_scaffold(initial=True)

        # start the mission: all UAVs enter loading for their first sortie
        for u in range(self.M):
            self._begin_turnaround(u, 0.0)

        obs, masks, deciders = self._advance()
        # deprivation accrued before the first decision is not attributable to
        # any action; drop it from the reward accumulators (it is still counted
        # in metrics.J_dep_belief / J_dep_true).
        self._interval_belief_dep = 0.0
        self._interval_energy = 0.0
        self._interval_risk = 0.0
        self._interval_resolve = False
        self._interval_viol = 0.0
        return obs, {"masks": masks, "deciders": deciders, "t": self.t}

    # ------------------------------------------------------------------
    # Step
    # ------------------------------------------------------------------
    def step(self, actions: Dict[int, int]):
        """Apply the decision batch, advance to the next decision event, and
        compute the event-interval reward r_n (eq:event_reward)."""
        assert not self.done, "episode finished; call reset()"
        t_n = self.t

        # validate against the masks issued at decision time; infeasible
        # choices fall back to FOLLOW and incur P_viol (eq:event_reward)
        eff: Dict[int, Tuple[str, Optional[int], Optional[int]]] = {}
        for u, a in actions.items():
            kind, node, other = self.decode_action(u, a)
            if not self._action_mask_cache.get(u, np.ones(self.n_actions, bool))[a]:
                self._interval_viol += self.p.hybrid.P_viol
                kind, node, other = "FOLLOW", None, None
            eff[u] = (kind, node, other)

        # 1. REQUEST_RESOLVE (deduped over the batch, eq:resolve_budget)
        resolved = False
        if any(k == "REQUEST_RESOLVE" for k, _, _ in eff.values()) and self.K_rem > 0:
            self.K_rem -= 1
            self.metrics.n_resolves += 1
            self._interval_resolve = True
            self.scaffold = self._solve_scaffold()
            resolved = True

        # 2. plan-edit actions (SKIP / SWAP), then movement outcomes
        for u, (kind, node, other) in eff.items():
            if kind == "SKIP" and node is not None:
                self.scaffold.remove_node(u, node)
            elif kind == "SWAP" and node is not None and other is not None:
                v = self.scaffold.remove_node(u, node)
                if v is not None:
                    self.scaffold.insert_next(other, node, v.x_plan)
        for u, (kind, node, other) in eff.items():
            self._apply_movement(u, kind, node, resolved)

        # 3. advance to the next decision event
        obs, masks, deciders = self._advance()

        # 4. event-interval reward (eq:event_reward)
        dt = self.t - t_n
        reward = (-self._interval_belief_dep
                  - self.p.hybrid.xi_E * self._interval_energy
                  - self.p.hybrid.xi_R * self._interval_risk
                  - (self.p.hybrid.xi_C if self._interval_resolve else 0.0)
                  - self._interval_viol)
        info = {
            "t": self.t, "dt": dt, "deciders": deciders, "masks": masks,
            "K_rem": self.K_rem,
            "reward_terms": {
                "dep_belief": self._interval_belief_dep,
                "E_n": self._interval_energy, "R_n": self._interval_risk,
                "resolve": self._interval_resolve, "P_viol": self._interval_viol},
            "done_reason": self.done_reason,
        }
        self._interval_belief_dep = 0.0
        self._interval_energy = 0.0
        self._interval_risk = 0.0
        self._interval_resolve = False
        self._interval_viol = 0.0
        return obs, reward, self.done, info

    # ------------------------------------------------------------------
    # Event loop
    # ------------------------------------------------------------------
    def _advance(self):
        """Pop events until a nonempty decision set emerges or the episode ends."""
        while True:
            if self.done:
                return {}, {}, []
            ev = self.queue.pop()
            if ev is None:
                # nothing left: idle fleet, drained exogenous timeline
                self._integrate_to(self.T)
                self.t = self.T
                self._terminate("horizon")
                return {}, {}, []
            self.metrics.n_events += 1
            self._integrate_to(ev.t)
            self.t = ev.t
            deciders = self._apply_event(ev)
            self._check_termination()
            if self.done:
                return {}, {}, []
            if deciders:
                deciders = sorted(set(deciders))
                self.last_decision_event_type = ev.etype
                self.metrics.n_decisions += 1
                obs = {u: self._build_obs(u) for u in deciders}
                masks = {u: self._action_mask(u) for u in deciders}
                self._action_mask_cache = masks
                for u in deciders:
                    self._events_since[u] = {"P1": 0, "P2": 0, "P4": 0, "AVAIL": 0}
                return obs, masks, deciders

    def _apply_event(self, ev: Event) -> List[int]:
        et = ev.etype
        # -- silent truth-side events ------------------------------------
        if et == EventType.DEMAND_ONSET:
            n = self.scenario.nodes[ev.payload["node"]]
            for k in range(N_COMMODITIES):
                self.nodes[n.idx].add_cohort(k, n.d0[k], ev.t)
            return []
        if et == EventType.P3_MUTATION:
            node = ev.payload["node"]
            delta = ev.payload["delta"]
            for k in range(N_COMMODITIES):
                self.nodes[node].add_cohort(k, delta[k], ev.t)   # eq:p3_mutation
            self.metrics.generated_units += delta
            return []                                            # eq:p3_stale_belief
        if et == EventType.REPLENISH:
            self.inventory.replenish(ev.payload["R"])
            # wake idle depot UAVs so replenished stock can be dispatched
            # (the manuscript's decision-event list is non-exhaustive)
            return [u for u, uav in enumerate(self.uavs)
                    if uav.mode == Mode.DEPOT and not self._in_turnaround[u]]
        if et == EventType.HORIZON:
            self._terminate("horizon")
            return []

        # -- information events (decision events) --------------------------
        if et == EventType.P1_REPORT:
            node = ev.payload["node"]
            if self.belief.is_known(node):
                d_true = self.nodes[node].demand_vector()
                y = np.maximum(d_true + ev.payload["eps"], 0.0)  # eq:p1_observation
                self.belief.apply_report(node, y, ev.payload["gamma"], ev.t)
                self._bump_event_counts("P1")
                return self._info_deciders()
            return []
        if et == EventType.P2_REVEAL:
            n = self.scenario.nodes[ev.payload["node"]]
            self.belief.reveal(n.idx, np.array(n.mu0), np.array(n.sigma0),
                               n.gamma0, n.onset_time, ev.t,
                               n.nu if n.nu_reported is None else n.nu_reported)
            self._reveals_since_scaffold += 1
            self._bump_event_counts("P2")
            return self._info_deciders()
        if et == EventType.P4_REPORT:
            node = ev.payload["node"]
            if self.belief.is_known(node):
                d_true = self.nodes[node].demand_vector()
                y = np.maximum(d_true + ev.payload["eps"], 0.0)  # eq:p4_report
                self.belief.apply_report(node, y, ev.payload["gamma"], ev.t,
                                         sigma_obs=ev.payload["sigma_obs"])
                self._bump_event_counts("P4")
                return self._info_deciders()
            return []
        if et == EventType.AVAIL_CHANGE:
            self.graph.set_available(ev.payload["i"], ev.payload["j"],
                                     ev.payload["available"])
            self._corridor_report_generation[
                (ev.payload["i"], ev.payload["j"])
            ] = ev.t
            self._corridor_report_generation[
                (ev.payload["j"], ev.payload["i"])
            ] = ev.t
            if not ev.payload["available"]:
                self._invalid_legs += self._count_planned_legs(
                    ev.payload["i"], ev.payload["j"])
            self._bump_event_counts("AVAIL")
            return self._info_deciders()

        # -- fleet events -----------------------------------------------------
        if et == EventType.UAV_ARRIVAL:
            return self._handle_arrival(ev)
        if et == EventType.SERVICE_COMPLETE:
            u = ev.payload["uav"]
            self.uavs[u].mode = Mode.FLYING       # free to move; decision follows
            return [u]
        if et == EventType.DEPOT_ARRIVAL:
            u = ev.payload["uav"]
            uav = self.uavs[u]
            self._settle(u, ev.t)
            uav.pos = self.depot_pos.copy()
            uav.mode = Mode.DEPOT
            uav.origin = None
            self._arrival_seq[u] = None
            self._committed_x_plan[u] = None #NEW
            return [u]                            # depot-return decision event
        if et == EventType.LOAD_COMPLETE:
            u = ev.payload["uav"]
            uav = self.uavs[u]
            # loading vector fixed at completion from the *current* scaffold
            # (a RESOLVE during turnaround is honored), trimmed to W_max (C4,
            # eq:payload_capacity) and clipped by stock (C6)
            sortie = self.scaffold.advance_sortie(u)
            if sortie is not None:
                uav.ell = self.inventory.load(          # eq:inventory_transition
                    self._trim_to_capacity(sortie.y))
            uav.b = self.p.physics.B_max          # eq:depot_reset
            uav.s += 1
            uav.mode = Mode.DEPOT
            self._in_turnaround[u] = False
            return [u]
        return []

    def _consume_served_visit(self, u: int, node: int) -> None:
        """Remove a just-served node from the UAV's current scaffold sortie."""
        ss = self.scaffold.plans.get(u)
        if not ss:
            return
        sortie = ss[0]
        for vi, visit in enumerate(sortie.visits):
            if visit.node == node:
                sortie.visits.pop(vi)
                sortie.y = np.sum(
                    [v.x_plan for v in sortie.visits], axis=0
                ) if sortie.visits else np.zeros(N_COMMODITIES)
                if not sortie.visits:
                    ss.pop(0)
                return

    # -- arrival / delivery ------------------------------------------------
    def _handle_arrival(self, ev: Event) -> List[int]:
        u = ev.payload["uav"]
        node = ev.payload["node"]
        uav = self.uavs[u]
        self._settle(u, ev.t)
        uav.pos = self.nodes[node].pos.copy()
        uav.origin = None
        self._arrival_seq[u] = None
        self._committed_x_plan[u] = None #NEW
        uav.mode = Mode.DELIVERING

        # delivery amounts: x <= min(ell, d_true) and the planned cap
        # (eq:delivery_amount); FOFS cohort allocation (sec: demand_model)
        cap = ev.payload.get("x_plan")
        nt = self.nodes[node]
        x_served = np.zeros(N_COMMODITIES)
        x_attempted = np.zeros(N_COMMODITIES)
        for k in range(N_COMMODITIES):
            want = uav.ell[k] if cap is None else min(uav.ell[k], cap[k])
            x_attempted[k] = max(float(want), 0.0)
            want = min(want, nt.d(k))
            if want > EPS:
                x_served[k] = nt.serve_fofs(k, want)
        uav.ell = np.maximum(uav.ell - x_served, 0.0)     # eq:payload_transition
        uav.b -= service_energy(self.p.physics)           # eq:service_energy
        self._interval_energy += service_energy(self.p.physics)
        self.metrics.J_energy += service_energy(self.p.physics)
        self.metrics.delivered_units += x_served
        self.belief.apply_delivery(
            node, x_served, ev.t, attempted=x_attempted,
        )

        # Consume the served visit from the incumbent scaffold so the
        # controller does not treat the rest of the sortie as hard infeasible.
        self._consume_served_visit(u, node)

        # P4: delivery-triggered situational report (policy-dependent, online)
        if self._rng_p4.random() < self.p.events.p_P4:
            delay = float(self._rng_p4.exponential(self.p.events.delta_P4_mean)) \
                if self.p.events.delta_P4_mean > 0 else 0.0
            eps = self._rng_p4.normal(0.0, self.p.events.sigma_P4, N_COMMODITIES) \
                if self.p.events.sigma_P4 > 0 else np.zeros(N_COMMODITIES)
            gamma = float(self._rng_p4.uniform(0.6, 0.95))
            t_report = min(ev.t + SERVICE_DWELL + delay, self.T - EPS)
            self.queue.push(Event(t_report, EventType.P4_REPORT,
                                  {"node": node, "eps": eps, "gamma": gamma,
                                   "sigma_obs": self.p.events.sigma_P4}))

        self.queue.push(Event(ev.t + SERVICE_DWELL, EventType.SERVICE_COMPLETE,
                              {"uav": u, "node": node}))
        return []

    # ------------------------------------------------------------------
    # Movement semantics
    # ------------------------------------------------------------------
    def _apply_movement(self, u: int, kind: str, node: Optional[int],
                        resolved: bool = False) -> None:
        uav = self.uavs[u]
        if self._in_turnaround[u]:
            return                     # turnaround continues regardless
        en_route = (self._arrival_seq[u] is not None
                    and uav.mode in (Mode.FLYING, Mode.RETURNING))
        if kind == "INSERT" and node is not None:
            if en_route and uav.dest_node == node:
                return                 # already heading there
            if uav.mode == Mode.DEPOT and uav.ell.sum() <= EPS:
                # ad-hoc single-node sortie loaded from stock
                x = self._fit_stock_delivery(node)
                if x.sum() > EPS:
                    self.scaffold.plans.setdefault(u, []).insert(
                        0, Sortie(visits=[PlannedVisit(node, x)], y=x.copy()))
                    self._begin_turnaround(u, self.t)
                return
            x_plan = np.minimum(uav.ell, self.belief.d_tilde(node)) \
                if self.belief.is_known(node) else uav.ell.copy()
            self.scaffold.insert_next(u, node, x_plan)
            self._follow(u)            # divert to the inserted node
            return
        if kind == "RETURN":
            if uav.mode == Mode.DEPOT:
                return                 # already home: idle
            if en_route and uav.dest_node == DEPOT:
                return                 # already returning
            self._launch(u, DEPOT)
            return
        # A leg already in execution is an operational commitment.
        # Replanning may modify only the route suffix after that leg.
        if en_route :
            return
        self._follow(u)

    def _follow(self, u: int) -> None:
        """FOLLOW: execute the next step of pi_u^ALNS from the current state."""
        uav = self.uavs[u]
        nxt = self.scaffold.peek_next(u)
        if uav.mode == Mode.DEPOT:
            if uav.ell.sum() > EPS:
                if nxt is not None and self._leg_feasible(u, nxt.node):
                    v = self.scaffold.pop_next(u)
                    self._launch(u, v.node, v.x_plan)
                elif nxt is None:
                    # cargo but no current-sortie plan: recycle via turnaround
                    self._begin_turnaround(u, self.t)
                # else: planned stop currently infeasible — idle, wait for events
                return
            sortie = self.scaffold.advance_sortie(u)
            loadable = sortie is not None and \
                float(np.minimum(sortie.y, self.inventory.S0).sum()) > EPS
            if loadable:
                self._begin_turnaround(u, self.t)
            # else: idle at the depot until a future decision event
            return
        # airborne (post-service or diverting after a re-solve)
        if nxt is not None and self._leg_feasible(u, nxt.node):
            v = self.scaffold.pop_next(u)
            self._launch(u, v.node, v.x_plan)
        else:
            self._launch(u, DEPOT)

    def _launch(self, u: int, target: int,
                x_plan: Optional[np.ndarray] = None) -> None:
        """Begin a flight leg to a node (target >= 0) or the depot (DEPOT)."""
        uav = self.uavs[u]
        # cancel any in-flight arrival (mid-leg diversion)
        if self._arrival_seq[u] is not None:
            self.queue.cancel(self._arrival_seq[u])
            self._arrival_seq[u] = None
        phys = self.p.physics
        w_k = np.asarray(self.p.commodities.w_k)
        tgt_pos = self.depot_pos if target == DEPOT else self.nodes[target].pos
        # depart from the settled (possibly mid-leg) position
        origin = uav.position_at(self.t)
        L = float(np.linalg.norm(np.asarray(tgt_pos) - origin))
        tau = L / phys.v_uav
        uav.origin = origin
        uav.pos = np.asarray(tgt_pos, dtype=float).copy()
        uav.depart_time = self.t
        uav.arrive_time = self.t + tau
        uav.leg_energy = flight_energy(L, uav.payload_mass(w_k), phys)
        uav.leg_risk = self._risk_between(origin, tgt_pos)
        uav.dest_node = target
        if target == DEPOT:
            self._committed_x_plan[u] = None
        else:
            self._committed_x_plan[u] = (
                None
                if x_plan is None
                else np.asarray(x_plan, dtype=float).copy()
            )
        self._settled_t[u] = self.t
        if target == DEPOT:
            uav.mode = Mode.RETURNING
            seq = self.queue.push(Event(uav.arrive_time, EventType.DEPOT_ARRIVAL,
                                        {"uav": u}))
        else:
            uav.mode = Mode.FLYING
            payload = {"uav": u, "node": target}
            if x_plan is not None:
                payload["x_plan"] = np.asarray(x_plan, dtype=float)
            seq = self.queue.push(Event(uav.arrive_time, EventType.UAV_ARRIVAL,
                                        payload))
        self._arrival_seq[u] = seq

    def _begin_turnaround(self, u: int, t: float) -> None:
        """Depot service: queue for a bay (T_queue), then T_load + T_charge_eff
        (eq:turnaround_time). Leftover cargo is returned to depot stock; the
        loading vector is fixed at LOAD_COMPLETE from the then-current
        scaffold (so a mid-turnaround RESOLVE is honored)."""
        uav = self.uavs[u]
        phys = self.p.physics
        mission = self.p.mission
        if uav.ell.sum() > EPS:                   # unload leftovers (conservation)
            self.inventory.replenish(uav.ell)
            uav.ell = np.zeros(N_COMMODITIES)
        self._in_turnaround[u] = True
        uav.mode = Mode.LOADING
        bay = int(np.argmin(self._bay_free))
        t_start = max(t, self._bay_free[bay])     # T_queue = t_start - t
        charge_eff = mission.T_charge * max(phys.B_max - uav.b, 0.0) / phys.B_max
        t_done = t_start + mission.T_load + charge_eff
        self._bay_free[bay] = t_done
        self._load_done_t[u] = t_done
        self.queue.push(Event(t_done, EventType.LOAD_COMPLETE, {"uav": u}))

    def _trim_to_capacity(self, y: np.ndarray) -> np.ndarray:
        """Enforce C4 on a loading vector: trim least-critical units until
        the total mass fits W_max (eq:payload_capacity)."""
        w_k, lambda_k, _, _ = self.p.commodities.as_arrays()
        y = np.maximum(np.asarray(y, dtype=float).copy(), 0.0)
        W = self.p.physics.W_max
        for k in np.argsort(lambda_k):            # least-critical trimmed first
            while y[k] > 0 and float(np.dot(w_k, y)) > W + EPS:
                y[k] = max(0.0, y[k] - 1.0)
        return y

    def _fit_stock_delivery(self, node: int) -> np.ndarray:
        """Loading for an ad-hoc single-node sortie: min(d_tilde, stock) fit to W_max."""
        w_k, lambda_k, _, _ = self.p.commodities.as_arrays()
        want = np.floor(np.minimum(self.belief.d_tilde(node), self.inventory.S0))
        want = np.maximum(want, 0.0)
        order = np.argsort(lambda_k)
        while float(np.dot(w_k, want)) > self.p.physics.W_max + EPS:
            for k in order:
                if want[k] > 0:
                    want[k] -= 1
                    break
            else:
                break
        return want

    # ------------------------------------------------------------------
    # Feasibility (constraints C1-C6, eq:cst_*)
    # ------------------------------------------------------------------
    def _anchor_node(self, u: int) -> int:
        """Node context for availability lookups (C2)."""
        uav = self.uavs[u]
        if uav.mode in (Mode.DEPOT, Mode.LOADING, Mode.CHARGING):
            return DEPOT
        if uav.dest_node is not None:
            return uav.dest_node
        return DEPOT

    def _leg_feasible(self, u: int, node: int) -> bool:
        """C1 ^ C2 ^ C5 for flying from the UAV's current position to `node`."""
        if not self.belief.is_known(node):                       # C1
            return False
        if not self.graph.A(self._anchor_node(u), node):         # C2
            return False
        return self._c5_ok(u, node)                              # C5

    def _c5_ok(self, u: int, node: int) -> bool:
        uav = self.uavs[u]
        phys = self.p.physics
        w_k = np.asarray(self.p.commodities.w_k)
        pos = uav.position_at(self.t)
        L_to = float(np.linalg.norm(self.nodes[node].pos - pos))
        L_back = float(np.linalg.norm(self.nodes[node].pos - self.depot_pos))
        mass = uav.payload_mass(w_k)
        x_exp = np.minimum(uav.ell, self.belief.d_tilde(node)) \
            if self.belief.is_known(node) else np.zeros(N_COMMODITIES)
        mass_after = float(np.dot(w_k, np.maximum(uav.ell - x_exp, 0.0)))
        need = safe_return_energy(L_to, L_back, mass, mass_after, phys)
        return uav.b >= need + phys.beta_safe                    # eq:safe_return_constraint

    def _action_mask(self, u: int) -> np.ndarray:
        """Feasibility mask over the flattened action space (C1-C6)."""
        mask = np.zeros(self.n_actions, dtype=bool)
        uav = self.uavs[u]
        mask[self.A_FOLLOW] = True
        mask[self.A_RETURN] = True
        mask[self.A_RESOLVE] = self.K_rem > 0                     # eq:resolve_budget
        can_fly = (not self._in_turnaround[u]) and \
            uav.mode in (Mode.DEPOT, Mode.FLYING, Mode.RETURNING, Mode.DELIVERING)
        planned = set(self.scaffold.planned_nodes(u))
        for i in range(self.N):
            if not self.belief.is_known(i):                       # C1
                continue
            d_t = self.belief.d_tilde(i)
            # INSERT(i)
            if can_fly:
                if uav.mode == Mode.DEPOT and uav.ell.sum() <= EPS:
                    # ad-hoc sortie: C3 against depot stock (C6), C5 at full charge
                    c3 = bool(np.any((self.inventory.S0 > EPS) & (d_t > EPS)))
                    if c3 and self.graph.A(DEPOT, i) \
                            and self._c5_full_charge_ok(i):
                        mask[self.encode_insert(i)] = True
                else:
                    c3 = bool(np.any((uav.ell > EPS) & (d_t > EPS)))  # C3
                    if c3 and self.graph.A(self._anchor_node(u), i) \
                            and self._c5_ok(u, i):
                        mask[self.encode_insert(i)] = True
            # SKIP(i)
            if i in planned:
                mask[self.encode_skip(i)] = True
                # SWAP(i, u')
                for other in range(self.M):
                    if other == u:
                        continue
                    o = self.uavs[other]
                    if o.ell.sum() > EPS:
                        c3o = bool(np.any((o.ell > EPS) & (d_t > EPS)))
                    else:
                        c3o = bool(np.any((self.inventory.S0 > EPS) & (d_t > EPS)))
                    if c3o and self.graph.A(self._anchor_node(other), i):
                        mask[self.encode_swap(i, u, other)] = True
        return mask

    def _c5_full_charge_ok(self, i: int) -> bool:
        phys = self.p.physics
        L = float(np.linalg.norm(self.nodes[i].pos - self.depot_pos))
        need = safe_return_energy(L, L, phys.W_max, 0.0, phys)
        return phys.B_max >= need + phys.beta_safe

    # ------------------------------------------------------------------
    # Continuous accounting
    # ------------------------------------------------------------------
    def _integrate_to(self, t: float) -> None:
        """Advance the closed-form deprivation integrals to time t
        (eq:true_objective, eq:belief_objective) and settle flight energy."""
        t = min(t, self.T)
        dt = t - self._last_integration_t
        if dt <= EPS:
            return
        w_k, lambda_k, alpha_k, kappa_k = self.p.commodities.as_arrays()
        t0 = self._last_integration_t
        for nt in self.nodes:
            if nt.onset_time <= t0 + EPS:
                val = true_deprivation_integral(nt.nu, nt.cohorts, t0, dt,
                                                lambda_k, alpha_k, kappa_k)
                self.metrics.add_true_deprivation(nt.idx, val)
        for i in self.belief.known:
            d_t = self.belief.d_tilde(i)
            if d_t.sum() <= EPS:
                continue
            val = belief_deprivation_integral(
                self.nodes[i].nu, d_t, self.belief.age_hat(i, t0), dt,
                lambda_k, alpha_k, kappa_k)
            self.metrics.J_dep_belief += val
            self._interval_belief_dep += val
        for u in range(self.M):
            self._settle(u, t)
        self._last_integration_t = t

    def _settle(self, u: int, t: float) -> None:
        """Charge pro-rata flight energy/risk for UAV u up to time t."""
        uav = self.uavs[u]
        if uav.mode not in (Mode.FLYING, Mode.RETURNING) or uav.origin is None:
            self._settled_t[u] = t
            return
        dur = uav.arrive_time - uav.depart_time
        if dur <= EPS:
            self._settled_t[u] = t
            return
        t_c = min(t, uav.arrive_time)
        frac = max(t_c - self._settled_t[u], 0.0) / dur
        if frac <= 0.0:
            return
        e = uav.leg_energy * frac
        r = uav.leg_risk * frac
        uav.b -= e
        self._interval_energy += e
        self._interval_risk += r
        self.metrics.J_energy += e
        self.metrics.J_risk += r
        self._settled_t[u] = t_c

    def _risk_between(self, a: np.ndarray, b: np.ndarray, n_samples: int = 12) -> float:
        L = float(np.linalg.norm(b - a))
        if L <= EPS:
            return 0.0
        fr = (np.arange(n_samples) + 0.5) / n_samples
        pts = a[None, :] + fr[:, None] * (b - a)[None, :]
        return float(np.mean(self.fields.H(pts, self.t)) * L)

    # ------------------------------------------------------------------
    # Hybrid interface
    # ------------------------------------------------------------------

    def _run_planner(
        self,
        ctx: PlanContext,
        warm: Optional[Scaffold],
        frozen_nodes_by_uav: Optional[Dict[int, Set[int]]],
        removal_weights_by_uav_node: Optional[
            Dict[Tuple[int, int], float]
        ],
        respect_onboard: bool,
        count_as_repair: bool,
    ) -> Scaffold:
        """Run ALNS through one instrumented interface."""

        started = time.perf_counter()

        self.alns_solving = True
        self.alns_request_t = self.t

        try:
            return self.planner.solve(
                ctx,
                self._rng_alns,
                warm=warm,
                frozen_nodes_by_uav=frozen_nodes_by_uav,
                removal_weights_by_uav_node=(
                    removal_weights_by_uav_node
                ),
                respect_onboard=respect_onboard,
            )
        finally:
            elapsed = time.perf_counter() - started

            self.alns_solving = False
            self.alns_request_t = None

            if count_as_repair:
                self.repair_solver_calls += 1
                self.repair_solver_wall_time_s += elapsed
            
    def _solve_scaffold(self, initial: bool = False) -> Scaffold:
        ctx = self._plan_context()
        warm = (
        None
        if initial
        else getattr(self, "scaffold", None))
        scaffold = self._run_planner(
        ctx=ctx,
        warm=warm,
        frozen_nodes_by_uav=None,
        removal_weights_by_uav_node=None,
        respect_onboard=not initial,
        count_as_repair=not initial,
        )

        return self._stamp_scaffold(scaffold)

    def _stamp_scaffold(self, scaffold: Scaffold) -> Scaffold:
        """Attach the operational snapshots used by downstream diagnostics."""
        scaffold.created_t = self.t
        scaffold.mu_snapshot = self.belief.snapshot_mu()
        scaffold.urgency_rank_snapshot = self._urgency_ranking()
        scaffold.known_snapshot = set(self.belief.known)
        scaffold.inventory_snapshot = self.inventory.S0.copy()
        scaffold.planned_service_count = sum(
            len(sortie.visits)
            for sorties in scaffold.plans.values()
            for sortie in sorties
        )
        scaffold.uav_position_snapshot = {
            u: uav.position_at(self.t).copy()
            for u, uav in enumerate(self.uavs)
        }
        self._reveals_since_scaffold = 0
        self._invalid_legs = 0
        return scaffold

    def begin_external_resolve(self) -> bool:
        """Account for one externally controlled repair attempt.

        The solve cost is charged when optimization is invoked, even if the
        resulting candidate is later rejected.
        """
        if self.K_rem <= 0:
            return False
        self.K_rem -= 1
        self.metrics.n_resolves += 1
        self._interval_resolve = True
        return True

    def propose_scaffold_repair(
        self,
        warm: Optional[Scaffold],
        frozen_nodes_by_uav: Optional[
            Dict[int, Set[int]]
        ] = None,
        removal_weights_by_uav_node: Optional[
            Dict[Tuple[int, int], float]
        ] = None,
        ) -> Scaffold:
        """Solve a belief-consistent candidate without installing it."""

        ctx = self._plan_context()

        return self._run_planner(
            ctx=ctx,
            warm=warm,
            frozen_nodes_by_uav=frozen_nodes_by_uav,
            removal_weights_by_uav_node=(
                removal_weights_by_uav_node
            ),
            respect_onboard=True,
            count_as_repair=True,
        )
    def propose_shadow_scaffold_repair(
        self,
        ctx: PlanContext,
        warm: Optional[Scaffold],
        frozen_nodes_by_uav: Optional[Dict[int, Set[int]]] = None,
        removal_weights_by_uav_node: Optional[
            Dict[Tuple[int, int], float]
        ] = None,
    ) -> Scaffold:
        """Solve a non-invasive counterfactual repair candidate.

        This method deliberately does not:

        * decrement the repair budget;
        * increment operational resolve statistics;
        * increment operational solver counters;
        * use or advance the operational ALNS RNG;
        * install or stamp the resulting scaffold;
        * change the simulator's operational solving state.

        The supplied PlanContext must contain operational belief only.
        """

        started = time.perf_counter()

        try:
            return self._shadow_audit_planner.solve(
                ctx,
                self._rng_shadow_audit,
                warm=warm,
                frozen_nodes_by_uav=frozen_nodes_by_uav,
                removal_weights_by_uav_node=(
                    removal_weights_by_uav_node
                ),
                respect_onboard=True,
            )

        finally:
            elapsed = time.perf_counter() - started

            self.shadow_audit_solver_calls += 1
            self.shadow_audit_wall_time_s += elapsed

    def install_scaffold_repair(self, scaffold: Scaffold) -> None:
        """Install an already-accounted repair candidate."""
        self.scaffold = self._stamp_scaffold(scaffold)

    def get_operational_belief_graph(self):
        """Return the optional methodology graph without exposing truth."""
        from methods.belief_graph import OperationalBeliefGraphBuilder

        return OperationalBeliefGraphBuilder(
            max_known_nodes=self.N
        ).build_from_env(self)
    
    def _remaining_committed_leg_energy(self, u: int) -> float:
        """Return the unsettled energy of UAV u's active committed leg.

        The UAV battery already reflects energy settled up to
        ``self._settled_t[u]``. Therefore, only the remaining fraction of the
        active leg must be deducted when projecting the UAV to its destination.
        """
        uav = self.uavs[u]

        if self._arrival_seq[u] is None:
            return 0.0

        if uav.mode not in (Mode.FLYING, Mode.RETURNING):
            return 0.0

        leg_duration = float(uav.arrive_time - uav.depart_time)

        if leg_duration <= EPS:
            return 0.0

        settled_time = min(
            max(float(self._settled_t[u]), float(uav.depart_time)),
            float(uav.arrive_time),
        )

        remaining_duration = max(
            float(uav.arrive_time) - settled_time,
            0.0,
        )

        remaining_fraction = remaining_duration / leg_duration

        return max(
            float(uav.leg_energy) * remaining_fraction,
            0.0,
        )


    def _project_empty_uav_to_depot(
        self,
        u: int,
        current_pos: np.ndarray,
        current_battery: float,
        available_time: float,
    ) -> UAVPlanStart:
        """Project an empty UAV through return and depot turnaround.

        This helper is used when the UAV will have no payload after completing
        its committed delivery. Since it cannot serve further demand, its next
        mutable loaded sortie begins after returning to the depot, loading, and
        charging.

        The projection follows the current ALNS planning approximation and does
        not predict a future depot-bay queue.
        """
        phys = self.p.physics
        mission = self.p.mission

        current_pos = np.asarray(current_pos, dtype=float)

        distance_to_depot = float(
            np.linalg.norm(current_pos - self.depot_pos)
        )
        return_time = distance_to_depot / phys.v_uav

        return_energy = flight_energy(
            distance_to_depot,
            0.0,  # empty payload
            phys,
        )

        battery_at_depot = max(
            float(current_battery) - return_energy,
            0.0,
        )

        charge_time = (
            mission.T_charge
            * max(phys.B_max - battery_at_depot, 0.0)
            / phys.B_max
        )

        ready_time = (
            float(available_time)
            + return_time
            + mission.T_load
            + charge_time
        )

        return UAVPlanStart(
            uav=u,
            pos=self.depot_pos.copy(),
            ell=np.zeros(N_COMMODITIES, dtype=float),
            b=float(phys.B_max),
            ready_time=ready_time,
            at_depot=True,
            payload_committed=False,
            anchor=DEPOT,
        )


    def _project_committed_plan_start(
        self,
        u: int,
        projected_demand: Dict[int, np.ndarray],
    ) -> UAVPlanStart:
        """Project UAV u through its currently committed flight operation.

        Repair is not allowed to interrupt an active leg. This function
        therefore returns the state from which the mutable route suffix may
        begin.

        The projection uses only operational belief demand. It does not inspect
        latent true demand.
        """
        uav = self.uavs[u]

        if self._arrival_seq[u] is None:
            raise RuntimeError(
                "_project_committed_plan_start called without an active leg"
            )

        if uav.dest_node is None:
            raise RuntimeError(
                f"UAV {u} has an active arrival event but no destination"
            )

        remaining_leg_energy = self._remaining_committed_leg_energy(u)

        battery_at_arrival = max(
            float(uav.b) - remaining_leg_energy,
            0.0,
        )

        arrival_time = float(uav.arrive_time)
        target = int(uav.dest_node)
        assert arrival_time >= self.t - EPS, (
            f"UAV {u}: projected arrival precedes current time"
        )

        assert battery_at_arrival <= uav.b + EPS, (
            f"UAV {u}: projection increased battery during flight"
        )

        assert battery_at_arrival >= -EPS, (
            f"UAV {u}: projected negative battery"
        )

        # ---------------------------------------------------------------
        # Case 1: the committed operation is a return to the depot.
        # ---------------------------------------------------------------
        if uav.mode == Mode.RETURNING or target == DEPOT:
            payload_at_depot = uav.ell.copy()

            # The environment permits leftover cargo to be used after the
            # UAV reaches the depot. It therefore remains committed onboard.
            if payload_at_depot.sum() > EPS:
                return UAVPlanStart(
                    uav=u,
                    pos=self.depot_pos.copy(),
                    ell=payload_at_depot,
                    b=battery_at_arrival,
                    ready_time=arrival_time,
                    at_depot=True,
                    payload_committed=True,
                    anchor=DEPOT,
                )

            # An empty returning UAV must complete loading and charging
            # before beginning a new loaded sortie.
            charge_time = (
                self.p.mission.T_charge
                * max(
                    self.p.physics.B_max - battery_at_arrival,
                    0.0,
                )
                / self.p.physics.B_max
            )

            return UAVPlanStart(
                uav=u,
                pos=self.depot_pos.copy(),
                ell=np.zeros(N_COMMODITIES, dtype=float),
                b=float(self.p.physics.B_max),
                ready_time=(
                    arrival_time
                    + self.p.mission.T_load
                    + charge_time
                ),
                at_depot=True,
                payload_committed=False,
                anchor=DEPOT,
            )

        # ---------------------------------------------------------------
        # Case 2: the committed operation is delivery to a demand node.
        # ---------------------------------------------------------------
        node = target

        believed_demand = projected_demand.get(
            node,
            np.zeros(N_COMMODITIES, dtype=float),
        ).copy()

        # Belief-consistent estimate of what the committed visit will serve.
        projected_delivery = np.minimum(
            uav.ell,
            believed_demand,
        )
       
        # Respect the planned delivery cap attached to the active leg.
        committed_cap = self._committed_x_plan[u]

        if committed_cap is not None:
            projected_delivery = np.minimum(
                projected_delivery,
                committed_cap,
            )

        projected_delivery = np.maximum(
            projected_delivery,
            0.0,
        )
        assert np.all(projected_delivery >= -EPS), (
            f"UAV {u}: negative projected delivery"
        )

        assert np.all(projected_delivery <= uav.ell + EPS), (
            f"UAV {u}: projected delivery exceeds onboard payload"
        )

        assert np.all(projected_delivery <= believed_demand + EPS), (
            f"UAV {u}: projected delivery exceeds believed demand"
        )

        # Remove the expected committed delivery from the demand made
        # available to the mutable suffix planner.
        projected_demand[node] = np.maximum(
            believed_demand - projected_delivery,
            0.0,
        )

        payload_after_delivery = np.maximum(
            uav.ell - projected_delivery,
            0.0,
        )
        assert np.all(payload_after_delivery >= -EPS), (
            f"UAV {u}: projected negative payload"
        )

        assert np.all(payload_after_delivery <= uav.ell + EPS), (
            f"UAV {u}: projected payload increased after delivery"
        )

        battery_after_service = max(
            battery_at_arrival - service_energy(self.p.physics),
            0.0,
        )

        service_complete_time = arrival_time + SERVICE_DWELL
        destination_pos = self.nodes[node].pos.copy()

        # The UAV may continue from the serviced node using its remaining
        # onboard payload.
        if payload_after_delivery.sum() > EPS:
            return UAVPlanStart(
                uav=u,
                pos=destination_pos,
                ell=payload_after_delivery,
                b=battery_after_service,
                ready_time=service_complete_time,
                at_depot=False,
                payload_committed=True,
                anchor=node,
            )

        # With no payload remaining, the next loaded mutable suffix begins
        # after returning to the depot and completing turnaround.
        return self._project_empty_uav_to_depot(
            u=u,
            current_pos=destination_pos,
            current_battery=battery_after_service,
            available_time=service_complete_time,
        )
    def _plan_context(self) -> PlanContext:
        """Construct the belief-side state used by ALNS.

        Active flight legs are immutable. Their UAV states are projected to
        completion before the mutable plan suffix is constructed.
        """
        d_tilde: Dict[int, np.ndarray] = {}
        age_hat: Dict[int, np.ndarray] = {}
        nu: Dict[int, float] = {}
        pos: Dict[int, np.ndarray] = {}

        # ---------------------------------------------------------------
        # 1. Copy controller-visible belief information.
        # ---------------------------------------------------------------
        for i in self.belief.known:
            dt_i = np.asarray(
                self.belief.d_tilde(i),
                dtype=float,
            ).copy()

            if dt_i.sum() <= EPS:
                continue

            d_tilde[i] = dt_i
            age_hat[i] = np.asarray(
                self.belief.age_hat(i, self.t),
                dtype=float,
            ).copy()
            nu[i] = float(self.belief.vulnerability(i))
            pos[i] = self.nodes[i].pos.copy()

        starts_by_uav: Dict[int, UAVPlanStart] = {}

        # ---------------------------------------------------------------
        # 2. Project active committed legs.
        #
        # Use deterministic arrival order because two UAVs may be committed
        # to the same demand node.
        # ---------------------------------------------------------------
        committed_uavs = [
            u
            for u, uav in enumerate(self.uavs)
            if (
                self._arrival_seq[u] is not None
                and uav.mode in (Mode.FLYING, Mode.RETURNING)
            )
        ]

        committed_uavs.sort(
            key=lambda u: (
                float(self.uavs[u].arrive_time),
                int(u),
            )
        )

        for u in committed_uavs:
            starts_by_uav[u] = self._project_committed_plan_start(
                u=u,
                projected_demand=d_tilde,
            )

        # ---------------------------------------------------------------
        # 3. Construct starts for UAVs without active committed legs.
        # ---------------------------------------------------------------
        for u, uav in enumerate(self.uavs):
            if u in starts_by_uav:
                continue

            # A UAV currently loading/charging becomes available when its
            # already scheduled turnaround finishes.
            if self._in_turnaround[u]:
                starts_by_uav[u] = UAVPlanStart(
                    uav=u,
                    pos=self.depot_pos.copy(),
                    ell=np.zeros(N_COMMODITIES, dtype=float),
                    b=float(self.p.physics.B_max),
                    ready_time=max(
                        float(self._load_done_t[u]),
                        float(self.t),
                    ),
                    at_depot=True,
                    payload_committed=False,
                    anchor=DEPOT,
                )
                continue

            current_pos = uav.position_at(self.t).copy()
            current_payload = uav.ell.copy()
            current_battery = float(uav.b)

            at_depot = uav.mode == Mode.DEPOT

            # A non-depot UAV with no payload cannot serve another node.
            # Project it through return and turnaround.
            if not at_depot and current_payload.sum() <= EPS:
                starts_by_uav[u] = self._project_empty_uav_to_depot(
                    u=u,
                    current_pos=current_pos,
                    current_battery=current_battery,
                    available_time=float(self.t),
                )
                continue

            # Loaded depot UAVs and non-depot UAVs with remaining cargo must
            # preserve and use their existing onboard payload.
            payload_committed = bool(
                current_payload.sum() > EPS
            )

            starts_by_uav[u] = UAVPlanStart(
                uav=u,
                pos=current_pos,
                ell=current_payload,
                b=current_battery,
                ready_time=float(self.t),
                at_depot=at_depot,
                payload_committed=payload_committed,
                anchor=self._anchor_node(u),
            )

        # ---------------------------------------------------------------
        # 4. Remove demand already covered by committed projected visits.
        # ---------------------------------------------------------------
        active_nodes = {
            i
            for i, demand in d_tilde.items()
            if demand.sum() > EPS
        }

        d_tilde = {
            i: d_tilde[i]
            for i in active_nodes
        }
        age_hat = {
            i: age_hat[i]
            for i in active_nodes
        }
        nu = {
            i: nu[i]
            for i in active_nodes
        }
        pos = {
            i: pos[i]
            for i in active_nodes
        }

        starts = [
            starts_by_uav[u]
            for u in range(self.M)
        ]

        return PlanContext(
            t=self.t,
            T=self.T,
            params=self.p,
            d_tilde=d_tilde,
            age_hat=age_hat,
            nu=nu,
            pos=pos,
            depot_pos=self.depot_pos.copy(),
            stock=self.inventory.S0.copy(),
            avail=lambda i, j: self.graph.A(i, j),
            risk=lambda i, j: self.graph.R(i, j, self.t),
            uav_starts=starts,
        )

    def _urgency_ranking(self) -> List[int]:
        w_k, lambda_k, alpha_k, kappa_k = self.p.commodities.as_arrays()
        vals = []
        for i in self.belief.known:
            U = belief_urgency(self.belief.vulnerability(i), self.belief.d_tilde(i),
                               self.belief.age_hat(i, self.t),
                               lambda_k, alpha_k, kappa_k)
            vals.append((U, i))
        vals.sort(key=lambda x: -x[0])
        return [i for _, i in vals]

    def plan_divergence_now(self) -> Tuple[float, np.ndarray]:
        """Delta_plan against the incumbent scaffold (eq:plan_divergence)."""
        return plan_divergence(
            self.scaffold, self.t, self.belief.snapshot_mu(),
            self._urgency_ranking(), self._reveals_since_scaffold,
            self._invalid_legs, self.p.hybrid.omega)

    def _count_planned_legs(self, i: int, j: int) -> int:
        """Planned consecutive legs using edge (i,j) — for N_invalid."""
        count = 0
        for u in range(self.M):
            seq = [DEPOT] + self.scaffold.planned_nodes(u) + [DEPOT]
            for a, b in zip(seq[:-1], seq[1:]):
                if (a, b) == (i, j) or (a, b) == (j, i):
                    count += 1
        return count

    # ------------------------------------------------------------------
    # Decision sets
    # ------------------------------------------------------------------
    def _info_deciders(self) -> List[int]:
        """UAVs that re-decide on an information event: flying/returning ones
        (mid-leg diversion) and idle loaded/empty UAVs at the depot."""
        out = []
        for u, uav in enumerate(self.uavs):
            if self._in_turnaround[u]:
                continue
            if uav.mode in (Mode.FLYING, Mode.RETURNING):
                # settle so masks/observations see the mid-leg position
                self._settle(u, self.t)
                out.append(u)
            elif uav.mode == Mode.DEPOT:
                out.append(u)
        return out

    def _bump_event_counts(self, key: str) -> None:
        for c in self._events_since:
            c[key] += 1

    # ------------------------------------------------------------------
    # Termination (manuscript sec: termination)
    # ------------------------------------------------------------------
    def _terminate(self, reason: str) -> None:
        self._integrate_to(self.T if reason == "horizon" else self.t)
        self.done = True
        self.done_reason = reason
        self.metrics.termination_reason = reason

    def _check_termination(self) -> None:
        if self.done:
            return
        if self.t >= self.T - EPS:
            self._terminate("horizon")
            return
        fleet_home = all(
            self.uavs[u].mode == Mode.DEPOT and not self._in_turnaround[u]
            for u in range(self.M))
        if not fleet_home:
            return
        # information still in flight that could revive demand or reveal nodes
        pending_info = any(
            ev[3].etype in (EventType.P1_REPORT, EventType.P2_REVEAL,
                            EventType.P4_REPORT, EventType.DEMAND_ONSET)
            for ev in self.queue._heap)
        # (2) all known and serviceable demand satisfied
        if self.p.mission.terminate_on_belief_zero and not pending_info:
            if all(self.belief.d_tilde(i).sum() <= 1e-6 for i in self.belief.known):
                self._terminate("demand_satisfied")
                return
        # (3) depot exhausted and no beneficial feasible delivery remains
        replen_pending = any(ev[3].etype == EventType.REPLENISH
                             for ev in self.queue._heap)
        stock_empty = bool(np.all(self.inventory.S0 <= 1e-6))
        payload_empty = all(u.ell.sum() <= 1e-6 for u in self.uavs)
        if stock_empty and payload_empty and not replen_pending:
            self._terminate("depot_exhausted")
            return
        # (4) fleet can no longer execute a safe sortie
        any_feasible = False
        for i in self.belief.known:
            if self.belief.d_tilde(i).sum() <= 1e-6:
                continue
            if self.graph.A(DEPOT, i) and self._c5_full_charge_ok(i):
                any_feasible = True
                break
        has_demand = any(self.belief.d_tilde(i).sum() > 1e-6
                         for i in self.belief.known)
        if has_demand and not any_feasible and not pending_info:
            self._terminate("fleet_infeasible")

    # ------------------------------------------------------------------
    # Observations (eq:agent_observation) and global state (eq:global_state)
    # ------------------------------------------------------------------
    @property
    def obs_dims(self) -> Dict[str, int]:
        return {"own": len(OWN_FEATURE_ORDER),
                "node": len(NODE_FEATURE_ORDER),
                "fleet": len(FLEET_FEATURE_ORDER),
                "event": len(EVENT_FEATURE_ORDER),
                "n_nodes": self.N, "n_others": self.M - 1,
                "actor": len(OWN_FEATURE_ORDER)
                + self.N * len(NODE_FEATURE_ORDER)
                + (self.M - 1) * len(FLEET_FEATURE_ORDER)
                + len(EVENT_FEATURE_ORDER),
                "critic_node": 26,
                "critic": self.M * len(OWN_FEATURE_ORDER)
                + self.N * 26
                + len(EVENT_FEATURE_ORDER)}

    def _own_feats(self, u: int) -> np.ndarray:
        uav = self.uavs[u]
        R = self.p.map.region_km
        phys = self.p.physics
        pos = uav.position_at(self.t)
        mode_1h = np.zeros(6)
        mode_1h[uav.mode.value] = 1.0
        w_k = np.asarray(self.p.commodities.w_k)
        return np.concatenate([
            pos / R,
            uav.ell / 10.0,
            [uav.payload_mass(w_k) / phys.W_max,
             uav.b / phys.B_max],
            mode_1h,
            [uav.s / 5.0, self.t / self.T,
             self.K_rem / max(self.p.hybrid.K_max, 1)],
        ])

    def _node_feats(self, u: int, i: int) -> np.ndarray:
        R = self.p.map.region_km
        nt = self.nodes[i]
        known = self.belief.is_known(i)
        if not known:
            return np.zeros(20)
        e = self.belief.entries[i]
        d_t = self.belief.d_tilde(i)
        w_k, lambda_k, alpha_k, kappa_k = self.p.commodities.as_arrays()
        age = self.belief.age_hat(i, self.t)
        reported_nu = self.belief.vulnerability(i)
        U_hat = belief_urgency(reported_nu, d_t, age, lambda_k, alpha_k, kappa_k)
        planned = self.scaffold.planned_nodes(u)
        nxt = self.scaffold.peek_next(u)
        return np.concatenate([
            nt.pos / R,
            [1.0],
            e.mu / 10.0,
            e.sigma / 5.0,
            [e.gamma, min(e.eta(self.t), 2.0) / 2.0, reported_nu / 3.0,
             float(np.dot(w_k, d_t)) / self.p.physics.W_max,
             float(age.max()) / self.T,
             math.log1p(U_hat) / 5.0,
             1.0 if i in planned else 0.0,
             1.0 if (nxt is not None and nxt.node == i) else 0.0,
             1.0 if self.graph.A(self._anchor_node(u), i) else 0.0],
        ])

    def _fleet_feats(self, u: int) -> np.ndarray:
        R = self.p.map.region_km
        phys = self.p.physics
        w_k = np.asarray(self.p.commodities.w_k)
        my_pos = self.uavs[u].position_at(self.t)
        feats = []
        for o in range(self.M):
            if o == u:
                continue
            ov = self.uavs[o]
            opos = ov.position_at(self.t)
            mode_1h = np.zeros(6)
            mode_1h[ov.mode.value] = 1.0
            feats.append(np.concatenate([
                (opos - my_pos) / R,
                [ov.payload_mass(w_k) / phys.W_max, ov.b / phys.B_max],
                mode_1h,
                [float(np.linalg.norm(opos - my_pos)) / R],
            ]))
        return np.concatenate(feats) if feats else np.zeros(0)

    def _event_feats(self, u: int) -> np.ndarray:
        c = self._events_since[u]
        dp, comps = self.plan_divergence_now()
        S0_ref = np.maximum(np.asarray(self.scenario.S0_init, dtype=float), 1.0)
        return np.concatenate([
            [min(c["P1"], 5) / 5.0, min(c["P2"], 5) / 5.0,
             min(c["P4"], 5) / 5.0, min(c["AVAIL"], 5) / 5.0],
            [math.log1p(dp) / 3.0],
            [min(comps[0], 2.0) / 2.0, comps[1], min(comps[2], 5.0) / 5.0,
             min(comps[3], 5.0) / 5.0, min(comps[4], self.T) / self.T],
            self.inventory.S0 / S0_ref,
            [(self.T - self.t) / self.T],
        ])

    def _build_obs(self, u: int) -> np.ndarray:
        """o_u = [s_u^local, B(t), phi_fleet, phi_event, pi_u^ALNS]
        (eq:agent_observation); the scaffold intent enters through the
        per-node in-plan/next flags."""
        nodes = np.concatenate([self._node_feats(u, i) for i in range(self.N)])
        return np.concatenate([self._own_feats(u), nodes,
                               self._fleet_feats(u), self._event_feats(u)])

    def get_global_state(self) -> np.ndarray:
        """Centralized-critic state s(t) (eq:global_state): truth + belief."""
        w_k, lambda_k, alpha_k, kappa_k = self.p.commodities.as_arrays()
        parts = [self._own_feats(u) for u in range(self.M)]
        for i in range(self.N):
            nt = self.nodes[i]
            base = self._node_feats(0, i)
            d_true = nt.demand_vector()
            rate = true_deprivation_rate(nt.nu, nt.cohorts, self.t,
                                         lambda_k, alpha_k, kappa_k)
            extra = np.concatenate([
                d_true / 10.0,
                [max(nt.oldest_age(k, self.t) for k in range(N_COMMODITIES))
                 / self.T if any(nt.cohorts[k] for k in range(N_COMMODITIES))
                 else 0.0],
                [math.log1p(rate) / 5.0],
            ])
            parts.append(np.concatenate([base, extra]))
        parts.append(self._event_feats(0))
        return np.concatenate(parts)

    # ------------------------------------------------------------------
    # Introspection for visualization / demos
    # ------------------------------------------------------------------
    def snapshot(self) -> Dict:
        w_k, lambda_k, alpha_k, kappa_k = self.p.commodities.as_arrays()
        return {
            "t": self.t,
            "K_rem": self.K_rem,
            "S0": self.inventory.S0.copy(),
            "uavs": [{
                "pos": uav.position_at(self.t), "mode": uav.mode.name,
                "b": uav.b, "ell": uav.ell.copy(), "s": uav.s,
                "dest": uav.dest_node,
            } for uav in self.uavs],
            "true_demand": {nt.idx: nt.demand_vector() for nt in self.nodes
                            if nt.onset_time <= self.t},
            "true_dep_rate": {nt.idx: true_deprivation_rate(
                nt.nu, nt.cohorts, self.t, lambda_k, alpha_k, kappa_k)
                for nt in self.nodes if nt.onset_time <= self.t},
            "known": sorted(self.belief.known),
            "belief_mu": self.belief.snapshot_mu(),
            "d_tilde": {i: self.belief.d_tilde(i) for i in self.belief.known},
            "available": self.graph.available.copy(),
        }
