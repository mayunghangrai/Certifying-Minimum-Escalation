"""
MAPPO controller for the event-driven UA-MTVRP-IU environment.

Centralized Training with Decentralized Execution (CTDE), action masking,
and *semi-Markov* GAE: because decisions occur at nonuniform event times
(eq:event_times) and agents decide asynchronously, each agent's transition
spans from one of its own decisions to the next. The shared event-interval
rewards r_n (eq:event_reward) accrued in between are discounted continuously:

    R_u   = sum_n  gamma_hour^(t_n - t_dec) * r_n        (accumulated reward)
    Gamma = gamma_hour^(t_dec' - t_dec)                   (bridge discount)
    delta = R_u + Gamma * V(s') * (1 - done) - V(s)
    A_t   = delta_t + Gamma_t * lambda * A_{t+1}          (per-agent SMDP GAE)
"""

from __future__ import annotations

import math
import os
import sys
from typing import Dict, List, Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.distributions import Categorical

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from agents.networks import MAPPOActor, MAPPOCritic  # noqa: E402
from methods.belief_graph import (  # noqa: E402
    EDGE_FEATURE_NAMES,
    NODE_FEATURE_NAMES,
    NORMALIZATION_REFERENCES,
    PLAN_FEATURE_NAMES,
)
from methods.graph_networks import (  # noqa: E402
    GraphMAPPOActor,
    GraphMAPPOCritic,
    TorchBeliefGraphBatch,
)


METHOD_MODES = {
    "vanilla_mappo": ("flat", "none"),
    "graph_mappo": ("belief_graph", "none"),
    "graph_mappo_fixed_alns": ("belief_graph", "fixed"),
    "graph_mappo_adaptive_alns": ("belief_graph", "adaptive"),
}


class _Pending:
    """An open macro-transition for one agent."""

    __slots__ = (
        "obs", "gobs", "action", "log_prob", "mask", "value",
        "t_dec", "acc_reward", "graph", "uav_id", "plan_features",
        "alns_prior",
    )

    def __init__(
        self, obs, gobs, action, log_prob, mask, value, t_dec,
        graph=None, uav_id=None, plan_features=None, alns_prior=None,
    ):
        self.obs = obs
        self.gobs = gobs
        self.action = action
        self.log_prob = log_prob
        self.mask = mask
        self.value = value
        self.t_dec = t_dec
        self.acc_reward = 0.0
        self.graph = graph
        self.uav_id = uav_id
        self.plan_features = plan_features
        self.alns_prior = alns_prior


class MAPPOAgent:
    def __init__(self, num_agents: int, obs_dims: Dict[str, int],
                 action_dim: int, config: Optional[Dict] = None):
        config = config or {}
        self.num_agents = num_agents
        self.obs_dims = dict(obs_dims)
        self.action_dim = action_dim
        self.method_mode = config.get("method_mode", "vanilla_mappo")
        if self.method_mode not in METHOD_MODES:
            raise ValueError(
                f"Unsupported method_mode {self.method_mode!r}; expected one "
                f"of {sorted(METHOD_MODES)}"
            )
        self.observation_encoder, self.guidance_mode = METHOD_MODES[
            self.method_mode
        ]

        self.lr_actor = config.get("lr_actor", 3e-4)
        self.lr_critic = config.get("lr_critic", 1e-3)
        self.gamma_hour = config.get("gamma_hour", 0.98)   # SMDP discount base
        self.lam = config.get("gae_lambda", 0.95)
        self.clip_param = config.get("clip_param", 0.2)
        self.entropy_coef = config.get("entropy_coef", 0.01)
        self.update_epochs = config.get("update_epochs", 4)
        self.gate_directional_regularization_coef = float(
            config.get("gate_directional_regularization_coef", 0.0)
        )
        self.gate_directional_margin = float(
            config.get("gate_directional_margin", 0.10)
        )
        if self.gate_directional_regularization_coef < 0.0:
            raise ValueError("gate directional regularization must be nonnegative")
        if not 0.0 <= self.gate_directional_margin <= 1.0:
            raise ValueError("gate directional margin must be in [0, 1]")
        hidden = config.get("hidden_dim", 256)
        enc = config.get("encoder_dim", 128)
        heads = config.get("num_heads", 4)
        layers = config.get("num_layers", 2)
        req = config.get("device", "cuda" if torch.cuda.is_available() else "cpu")
        self.device = torch.device(
            req if req == "cpu" or torch.cuda.is_available() else "cpu")

        d = self.obs_dims
        if self.observation_encoder == "belief_graph":
            graph_hidden = config.get("graph_hidden_dim", enc)
            graph_layers = config.get("graph_num_layers", max(layers, 2))
            graph_heads = config.get("graph_num_heads", heads)
            self.actor = GraphMAPPOActor(
                own_dim=d["own"],
                flat_node_dim=d["node"],
                flat_node_count=d["n_nodes"],
                rest_dim=d["n_others"] * d["fleet"] + d["event"],
                node_dim=len(NODE_FEATURE_NAMES),
                edge_dim=len(EDGE_FEATURE_NAMES),
                action_dim=action_dim,
                hidden_dim=graph_hidden,
                num_layers=graph_layers,
                num_heads=graph_heads,
                dropout=config.get("graph_dropout", 0.0),
                use_edge_features=config.get("use_edge_features", True),
                guidance_mode=self.guidance_mode,
                guidance_hidden_dim=config.get("guidance_hidden_dim", 64),
                beta=config.get("guidance_beta", 1.0),
                fixed_gate=config.get("fixed_guidance_gate", 0.5),
            ).to(self.device)
            self.critic = GraphMAPPOCritic(
                node_dim=len(NODE_FEATURE_NAMES),
                edge_dim=len(EDGE_FEATURE_NAMES),
                hidden_dim=graph_hidden,
                num_layers=graph_layers,
                num_heads=graph_heads,
                dropout=config.get("graph_dropout", 0.0),
                use_edge_features=config.get("use_edge_features", True),
            ).to(self.device)
        else:
            self.actor = MAPPOActor(
                own_dim=d["own"], node_dim=d["node"], n_nodes=d["n_nodes"],
                rest_dim=d["n_others"] * d["fleet"] + d["event"],
                action_dim=action_dim, hidden_dim=hidden, encoder_dim=enc,
                num_heads=heads, num_layers=layers).to(self.device)
            self.critic = MAPPOCritic(
                n_agents=num_agents, own_dim=d["own"], node_dim=d["critic_node"],
                n_nodes=d["n_nodes"], event_dim=d["event"], hidden_dim=hidden,
                encoder_dim=enc, num_heads=heads, num_layers=layers).to(self.device)
        self.actor_optimizer = optim.Adam(self.actor.parameters(),
                                          lr=self.lr_actor, eps=1e-5)
        self.critic_optimizer = optim.Adam(self.critic.parameters(),
                                           lr=self.lr_critic, eps=1e-5)
        self.last_diagnostics: Dict[int, dict] = {}
        self.last_gradient_norms: Dict[str, float] = {}
        self.last_update_diagnostics: List[dict] = []
        self.last_gate_gradient_vector_preclip = torch.zeros(0)
        self.last_gate_parameters_before_update = torch.zeros(0)
        self.last_gate_parameters_after_update = torch.zeros(0)
        self.last_gate_directional_diagnostics: Dict[str, float] = {}
        self._update_counter = 0
        self.begin_episode()

    # ------------------------------------------------------------------
    # Acting
    # ------------------------------------------------------------------
    def select_actions(self, obs: Dict[int, np.ndarray],
                       masks: Dict[int, np.ndarray],
                       global_state: np.ndarray,
                       deterministic: bool = False, graph=None,
                       diagnostics_enabled: bool = False):
        """Sample actions for the current decision set (a dict of agents)."""
        deciders = sorted(obs.keys())
        with torch.no_grad():
            ob = torch.FloatTensor(np.stack([obs[u] for u in deciders])).to(self.device)
            mk = torch.FloatTensor(np.stack([masks[u].astype(np.float32)
                                             for u in deciders])).to(self.device)
            if self.observation_encoder == "belief_graph":
                if graph is None:
                    raise ValueError(
                        "A BeliefGraph is required for a graph MAPPO mode"
                    )
                graph_batch = TorchBeliefGraphBatch.collate(
                    [graph] * len(deciders), self.device
                )
                uav_ids = torch.as_tensor(
                    deciders, dtype=torch.long, device=self.device
                )
                plan_features = torch.as_tensor(
                    np.stack([graph.plan_features[u] for u in deciders]),
                    dtype=torch.float32,
                    device=self.device,
                )
                alns_prior = torch.as_tensor(
                    np.stack([graph.alns_prior[u] for u in deciders]),
                    dtype=torch.float32,
                    device=self.device,
                )
                probs, masked_logits, gates, base_logits, attention = self.actor(
                    ob, graph_batch, uav_ids, mk, plan_features, alns_prior
                )
                value = float(
                    self.critic(
                        TorchBeliefGraphBatch.collate([graph], self.device)
                    ).view(-1)[0]
                )
                for row, u in enumerate(deciders):
                    recommended = int(graph.recommended_actions[u])
                    self.last_diagnostics[u] = {
                        "gate": float(gates[row, 0].cpu()),
                        "gate_logit": float(
                            self.actor.last_gate_logit[row, 0].cpu()
                        ),
                        "gate_adaptive": float(
                            self.actor.last_adaptive_gate[row, 0].cpu()
                        ),
                        "gate_fixed": float(self.actor.fixed_gate),
                        "beta": float(self.actor.beta),
                        "recommended_action": recommended,
                        "alns_prior": graph.alns_prior[u].copy(),
                        "plan_features": graph.plan_features[u].copy(),
                        "attention": attention[row].cpu().numpy().copy(),
                    }
                    if diagnostics_enabled:
                        self.last_diagnostics[u].update({
                            "base_logits": (
                                base_logits[row].cpu().numpy().copy()
                            ),
                            "masked_logits": (
                                masked_logits[row].cpu().numpy().copy()
                            ),
                            "probabilities": probs[row].cpu().numpy().copy(),
                        })
            else:
                probs, _ = self.actor(ob, mk)
                g = torch.FloatTensor(global_state).to(self.device)
                value = float(self.critic(g).view(-1)[0])
            dist = Categorical(probs)
            acts = torch.argmax(probs, dim=-1) if deterministic else dist.sample()
            logps = dist.log_prob(acts)
        actions = {u: int(a) for u, a in zip(deciders, acts.cpu().numpy())}
        log_probs = {u: float(l) for u, l in zip(deciders, logps.cpu().numpy())}
        for u in deciders:
            self.last_diagnostics.setdefault(u, {})
            self.last_diagnostics[u]["selected_action"] = actions[u]
            self.last_diagnostics[u]["action_mask"] = masks[u].copy()
        return actions, log_probs, value

    # ------------------------------------------------------------------
    # SMDP rollout bookkeeping
    # ------------------------------------------------------------------
    def begin_episode(self):
        self._pending: Dict[int, _Pending] = {}
        self._traj: Dict[int, List[dict]] = {u: [] for u in range(self.num_agents)}

    def record_decisions(self, t: float, obs, masks, global_state,
                         actions, log_probs, value, graph=None):
        """Close any open transitions for these agents and open new ones."""
        for u in obs.keys():
            if u in self._pending:
                self._close(u, value_next=value, done=False)
            stored_graph = graph.clone() if graph is not None else None
            self._pending[u] = _Pending(
                obs=obs[u],
                gobs=(
                    np.zeros(0, dtype=np.float32)
                    if self.observation_encoder == "belief_graph"
                    else np.asarray(global_state)
                ),
                action=actions[u],
                log_prob=log_probs[u], mask=masks[u].astype(np.float32),
                value=value, t_dec=t, graph=stored_graph, uav_id=u,
                plan_features=(
                    graph.plan_features[u].copy() if graph is not None else None
                ),
                alns_prior=(
                    graph.alns_prior[u].copy() if graph is not None else None
                ))

    def record_reward(self, r: float, t_interval_start: float):
        """Credit the shared event-interval reward to all open transitions,
        discounted from each agent's own decision time."""
        for p in self._pending.values():
            p.acc_reward += (self.gamma_hour
                             ** max(t_interval_start - p.t_dec, 0.0)) * r

    def end_episode(self, t_final: float):
        for u in list(self._pending.keys()):
            self._close(u, value_next=0.0, done=True, t_close=t_final)

    def _close(self, u: int, value_next: float, done: bool,
               t_close: Optional[float] = None):
        p = self._pending.pop(u)
        t_end = t_close if t_close is not None else None
        self._traj[u].append({
            "obs": p.obs, "gobs": p.gobs, "action": p.action,
            "log_prob": p.log_prob, "mask": p.mask, "value": p.value,
            "reward": p.acc_reward,
            "gamma_bridge": self.gamma_hour ** max(
                ((t_end if t_end is not None else p.t_dec) - p.t_dec), 0.0),
            "value_next": value_next, "done": float(done),
            "t_dec": p.t_dec, "graph": p.graph, "uav_id": p.uav_id,
            "plan_features": p.plan_features, "alns_prior": p.alns_prior})

    # ------------------------------------------------------------------
    # PPO update with per-agent SMDP GAE
    # ------------------------------------------------------------------
    def _gate_directional_loss(self):
        """Pair fresh status against each adverse observable plan condition."""
        zero = torch.zeros((), dtype=torch.float32, device=self.device)
        if (
            self.guidance_mode != "adaptive"
            or self.gate_directional_regularization_coef <= 0.0
        ):
            return zero, zero, zero, zero
        indices = {name: index for index, name in enumerate(PLAN_FEATURE_NAMES)}
        fresh = torch.zeros(
            (1, len(PLAN_FEATURE_NAMES)),
            dtype=torch.float32,
            device=self.device,
        )
        fresh[0, indices["next_action_operationally_feasible"]] = 1.0
        adverse_names = (
            "plan_age",
            "operational_demand_change",
            "operational_inventory_change",
            "newly_known_fraction",
            "invalid_planned_corridor_fraction",
            "execution_deviation",
        )
        variants = []
        for name in adverse_names:
            variant = fresh.clone()
            variant[0, indices[name]] = 1.0
            variants.append(variant)
        combined = fresh.clone()
        for name in adverse_names:
            combined[0, indices[name]] = 1.0
        variants.append(combined)
        stale = torch.cat(variants, dim=0)
        fresh_gate = torch.sigmoid(
            self.actor.guidance_gate.logits(fresh)
        ).view(())
        stale_gates = torch.sigmoid(
            self.actor.guidance_gate.logits(stale)
        ).view(-1)
        differences = fresh_gate - stale_gates
        loss = F.relu(self.gate_directional_margin - differences).mean()
        satisfied = (
            differences >= self.gate_directional_margin
        ).float().mean()
        return loss, fresh_gate, stale_gates.mean(), satisfied

    def update(
        self,
        diagnostics=None,
        diagnostic_context: Optional[Dict[str, object]] = None,
    ):
        obs, gobs, acts, logps, masks, advs, rets = [], [], [], [], [], [], []
        graphs, uav_ids, plan_features, alns_priors = [], [], [], []
        for u, traj in self._traj.items():
            if not traj:
                continue
            # bridge discount uses the *next* decision time of this agent
            for i, tr in enumerate(traj):
                t_next = traj[i + 1]["t_dec"] if i + 1 < len(traj) else tr["t_dec"]
                tr["gamma_bridge"] = self.gamma_hour ** max(t_next - tr["t_dec"], 0.0) \
                    if not tr["done"] else tr["gamma_bridge"]
            gae = 0.0
            for tr in reversed(traj):
                nonterm = 1.0 - tr["done"]
                delta = (tr["reward"] + tr["gamma_bridge"] * tr["value_next"]
                         * nonterm - tr["value"])
                gae = delta + tr["gamma_bridge"] * self.lam * nonterm * gae
                tr["adv"] = gae
                tr["ret"] = gae + tr["value"]
            for tr in traj:
                obs.append(tr["obs"])
                gobs.append(tr["gobs"])
                acts.append(tr["action"])
                logps.append(tr["log_prob"])
                masks.append(tr["mask"])
                advs.append(tr["adv"])
                rets.append(tr["ret"])
                if self.observation_encoder == "belief_graph":
                    graphs.append(tr["graph"])
                    uav_ids.append(tr["uav_id"])
                    plan_features.append(tr["plan_features"])
                    alns_priors.append(tr["alns_prior"])
        self.begin_episode()
        if not obs:
            return 0.0, 0.0

        obs = torch.FloatTensor(np.stack(obs)).to(self.device)
        gobs = torch.FloatTensor(np.stack(gobs)).to(self.device)
        acts = torch.LongTensor(np.array(acts)).to(self.device)
        logps_old = torch.FloatTensor(np.array(logps)).to(self.device)
        masks = torch.FloatTensor(np.stack(masks)).to(self.device)
        advs = torch.FloatTensor(np.array(advs)).to(self.device)
        rets = torch.FloatTensor(np.array(rets)).to(self.device)
        advs = (advs - advs.mean()) / (advs.std(unbiased=False) + 1e-8)
        if self.observation_encoder == "belief_graph":
            graph_batch = TorchBeliefGraphBatch.collate(graphs, self.device)
            uav_ids_t = torch.as_tensor(
                uav_ids, dtype=torch.long, device=self.device
            )
            plan_features_t = torch.as_tensor(
                np.stack(plan_features), dtype=torch.float32, device=self.device
            )
            alns_priors_t = torch.as_tensor(
                np.stack(alns_priors), dtype=torch.float32, device=self.device
            )

        a_loss_sum, c_loss_sum = 0.0, 0.0
        self.last_update_diagnostics = []
        for epoch_index in range(self.update_epochs):
            if self.observation_encoder == "belief_graph":
                probs, masked_logits, production_gates, base_logits, _ = self.actor(
                    obs, graph_batch, uav_ids_t, masks,
                    plan_features_t, alns_priors_t,
                )
            else:
                probs, _ = self.actor(obs, masks)
            dist = Categorical(probs)
            new_logps = dist.log_prob(acts)
            entropy = dist.entropy().mean()
            ratio = torch.exp(new_logps - logps_old)
            surr1 = ratio * advs
            surr2 = torch.clamp(ratio, 1 - self.clip_param,
                                1 + self.clip_param) * advs
            ppo_actor_loss = -torch.min(surr1, surr2).mean() \
                - self.entropy_coef * entropy
            (
                gate_directional_loss,
                fresh_probe_gate,
                stale_probe_gate,
                directional_margin_satisfied,
            ) = self._gate_directional_loss()
            actor_loss = (
                ppo_actor_loss
                + self.gate_directional_regularization_coef
                * gate_directional_loss
            )
            self.last_gate_directional_diagnostics = {
                "loss": float(gate_directional_loss.detach()),
                "fresh_probe_gate": float(fresh_probe_gate.detach()),
                "mean_stale_probe_gate": float(stale_probe_gate.detach()),
                "margin_satisfied_fraction": float(
                    directional_margin_satisfied.detach()
                ),
            }
            gate_module = getattr(self.actor, "guidance_gate", None)
            gate_parameters = (
                list(gate_module.parameters()) if gate_module is not None else []
            )
            gate_before = [
                parameter.detach().clone() for parameter in gate_parameters
            ]
            gate_norm_before = math.sqrt(
                sum(float(value.pow(2).sum()) for value in gate_before)
            )
            self.actor_optimizer.zero_grad()
            actor_loss.backward()
            self.last_gradient_norms["graph_encoder"] = self._gradient_norm(
                getattr(self.actor, "graph_encoder", None)
            )
            self.last_gradient_norms[
                "actor_graph_projection"
            ] = self._gradient_norm(
                getattr(self.actor, "context_query", None)
            )
            self.last_gradient_norms["guidance_gate"] = self._gradient_norm(
                gate_module
            )
            gate_gradients = [
                parameter.grad.detach().clone()
                for parameter in gate_parameters
                if parameter.grad is not None
            ]
            gate_gradient_values = (
                torch.cat([gradient.reshape(-1) for gradient in gate_gradients])
                if gate_gradients
                else torch.zeros(0, device=self.device)
            )
            self.last_gate_gradient_vector_preclip = (
                gate_gradient_values.detach().cpu().clone()
            )
            self.last_gate_parameters_before_update = torch.cat(
                [value.reshape(-1) for value in gate_before]
            ).cpu() if gate_before else torch.zeros(0)
            nn.utils.clip_grad_norm_(self.actor.parameters(), 0.5)
            self.actor_optimizer.step()
            gate_after = [
                parameter.detach().clone() for parameter in gate_parameters
            ]
            gate_norm_after = math.sqrt(
                sum(float(value.pow(2).sum()) for value in gate_after)
            )
            gate_update_norm = math.sqrt(
                sum(
                    float((after - before).pow(2).sum())
                    for before, after in zip(gate_before, gate_after)
                )
            )
            self.last_gate_parameters_after_update = torch.cat(
                [value.reshape(-1) for value in gate_after]
            ).cpu() if gate_after else torch.zeros(0)

            values = (
                self.critic(graph_batch).squeeze(-1)
                if self.observation_encoder == "belief_graph"
                else self.critic(gobs).squeeze(-1)
            )
            critic_loss = F.mse_loss(values, rets)
            self.critic_optimizer.zero_grad()
            critic_loss.backward()
            self.last_gradient_norms[
                "critic_graph_projection"
            ] = self._gradient_norm(
                getattr(self.critic, "graph_encoder", None)
            )
            nn.utils.clip_grad_norm_(self.critic.parameters(), 0.5)
            self.critic_optimizer.step()
            if (
                diagnostics is not None
                and self.observation_encoder == "belief_graph"
            ):
                with torch.no_grad():
                    unguided_logits = base_logits.masked_fill(
                        masks == 0, -1e8
                    )
                    unguided_probs = torch.softmax(unguided_logits, dim=-1)
                    safe_current = probs.clamp(min=1e-30)
                    safe_unguided = unguided_probs.clamp(min=1e-30)
                    guidance_kl = (
                        safe_current
                        * (safe_current.log() - safe_unguided.log())
                    ).sum(dim=-1)
                    argmax_changed = (
                        probs.argmax(dim=-1)
                        != unguided_probs.argmax(dim=-1)
                    ).float()
                    adaptive_gates = self.actor.last_adaptive_gate.view(-1)
                all_gate_parameter_ids = {
                    id(parameter) for parameter in gate_parameters
                }
                optimizer_parameter_ids = {
                    id(parameter)
                    for group in self.actor_optimizer.param_groups
                    for parameter in group["params"]
                }
                gate_lr = next(
                    (
                        float(group["lr"])
                        for group in self.actor_optimizer.param_groups
                        if any(
                            id(parameter) in all_gate_parameter_ids
                            for parameter in group["params"]
                        )
                    ),
                    math.nan,
                )
                update_row = {
                    **(diagnostic_context or {}),
                    "update_index": self._update_counter,
                    "minibatch_index": epoch_index,
                    "actor_loss": float(actor_loss.detach()),
                    "ppo_actor_loss": float(ppo_actor_loss.detach()),
                    "gate_directional_loss": float(
                        gate_directional_loss.detach()
                    ),
                    "gate_directional_regularization": float(
                        self.gate_directional_regularization_coef
                        * gate_directional_loss.detach()
                    ),
                    "gate_fresh_probe": float(fresh_probe_gate.detach()),
                    "gate_mean_stale_probe": float(stale_probe_gate.detach()),
                    "gate_directional_margin_satisfied_fraction": float(
                        directional_margin_satisfied.detach()
                    ),
                    "critic_loss": float(critic_loss.detach()),
                    "entropy": float(entropy.detach()),
                    "ppo_kl_estimate": float(
                        (logps_old - new_logps).mean().detach()
                    ),
                    "ppo_clipping_fraction": float(
                        ((ratio - 1.0).abs() > self.clip_param)
                        .float().mean().detach()
                    ),
                    "gate_gradient_l2_norm": float(
                        gate_gradient_values.pow(2).sum().sqrt()
                    ),
                    "gate_gradient_max_absolute": float(
                        gate_gradient_values.abs().max()
                        if gate_gradient_values.numel() else 0.0
                    ),
                    "gate_gradient_mean_absolute": float(
                        gate_gradient_values.abs().mean()
                        if gate_gradient_values.numel() else 0.0
                    ),
                    "gate_nonzero_gradient_parameter_count": int(
                        (gate_gradient_values != 0).sum()
                    ),
                    "gate_zero_gradient_fraction": float(
                        (gate_gradient_values == 0).float().mean()
                        if gate_gradient_values.numel() else 1.0
                    ),
                    "gate_gradients_all_finite": int(
                        bool(torch.isfinite(gate_gradient_values).all())
                    ),
                    "gate_parameter_l2_norm_before": gate_norm_before,
                    "gate_parameter_l2_norm_after": gate_norm_after,
                    "gate_parameter_update_l2_distance": gate_update_norm,
                    "gate_relative_parameter_update": (
                        gate_update_norm / max(gate_norm_before, 1e-30)
                    ),
                    "gate_optimizer_learning_rate": gate_lr,
                    "gate_parameters_in_optimizer": int(
                        all_gate_parameter_ids.issubset(
                            optimizer_parameter_ids
                        )
                    ),
                    "gate_parameters_require_grad": int(
                        all(parameter.requires_grad for parameter in gate_parameters)
                    ),
                    "gate_module_in_train_mode": int(
                        bool(gate_module.training) if gate_module is not None else 0
                    ),
                    "average_gate": float(adaptive_gates.mean()),
                    "gate_standard_deviation": float(
                        adaptive_gates.std(unbiased=False)
                    ),
                    "gate_below_005_fraction": float(
                        (adaptive_gates < 0.05).float().mean()
                    ),
                    "gate_above_095_fraction": float(
                        (adaptive_gates > 0.95).float().mean()
                    ),
                    "average_abs_gate_minus_fixed": float(
                        (adaptive_gates - self.actor.fixed_gate).abs().mean()
                    ),
                    "prior_coverage_rate": float(
                        (alns_priors_t.abs().sum(dim=-1) > 0).float().mean()
                    ),
                    "average_policy_kl_from_guidance": float(
                        guidance_kl.mean()
                    ),
                    "adaptive_guidance_argmax_change_fraction": float(
                        argmax_changed.mean()
                    ),
                }
                diagnostics.record_update(update_row)
                self.last_update_diagnostics.append(update_row)
                self._update_counter += 1
            a_loss_sum += float(actor_loss)
            c_loss_sum += float(critic_loss)
        return a_loss_sum / self.update_epochs, c_loss_sum / self.update_epochs

    # ------------------------------------------------------------------
    @staticmethod
    def _gradient_norm(module) -> float:
        if module is None:
            return 0.0
        total = 0.0
        for parameter in module.parameters():
            if parameter.grad is not None:
                total += float(parameter.grad.detach().pow(2).sum())
        return total ** 0.5

    def save(self, path: str):
        guidance_beta = getattr(self.actor, "beta", None)
        fixed_guidance_gate = getattr(self.actor, "fixed_gate", None)
        torch.save({
            "actor": self.actor.state_dict(),
            "critic": self.critic.state_dict(),
            "num_agents": self.num_agents,
            "obs_dims": self.obs_dims,
            "action_dim": self.action_dim,
            "model_version": 3,
            "method_mode": self.method_mode,
            "guidance_beta": (
                float(guidance_beta) if guidance_beta is not None else None
            ),
            "fixed_guidance_gate": (
                float(fixed_guidance_gate)
                if fixed_guidance_gate is not None
                else None
            ),
            "node_feature_names": NODE_FEATURE_NAMES,
            "edge_feature_names": EDGE_FEATURE_NAMES,
            "plan_feature_names": PLAN_FEATURE_NAMES,
            "normalization": NORMALIZATION_REFERENCES,
            "actor_optimizer": self.actor_optimizer.state_dict(),
            "critic_optimizer": self.critic_optimizer.state_dict(),
        }, path)

    def load(self, path: str):
        try:
            ckpt = torch.load(
                path, map_location=self.device, weights_only=False
            )
        except TypeError:
            ckpt = torch.load(path, map_location=self.device)
        saved_mode = ckpt.get("method_mode", "vanilla_mappo")
        if saved_mode != self.method_mode:
            raise ValueError(
                f"Checkpoint mode {saved_mode!r} does not match agent mode "
                f"{self.method_mode!r}"
            )
        if self.guidance_mode != "none":
            saved_beta = ckpt.get("guidance_beta")
            if (
                saved_beta is not None
                and not math.isclose(
                    float(saved_beta),
                    float(self.actor.beta),
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
            ):
                raise ValueError(
                    f"Checkpoint guidance beta {saved_beta!r} does not match "
                    f"agent guidance beta {self.actor.beta!r}"
                )
            saved_gate = ckpt.get("fixed_guidance_gate")
            if (
                saved_gate is not None
                and not math.isclose(
                    float(saved_gate),
                    float(self.actor.fixed_gate),
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
            ):
                raise ValueError(
                    f"Checkpoint fixed guidance gate {saved_gate!r} does not "
                    f"match agent fixed gate {self.actor.fixed_gate!r}"
                )
        self.actor.load_state_dict(ckpt["actor"])
        self.critic.load_state_dict(ckpt["critic"])
        if "actor_optimizer" in ckpt:
            self.actor_optimizer.load_state_dict(ckpt["actor_optimizer"])
        if "critic_optimizer" in ckpt:
            self.critic_optimizer.load_state_dict(ckpt["critic_optimizer"])

    def set_eval(self) -> None:
        self.actor.eval()
        self.critic.eval()

    def set_train(self) -> None:
        self.actor.train()
        self.critic.train()
