"""
Rule-based baselines for the ablation suite (spec: mappo-architecture-design):

  RandomAgent               uniform over the feasibility mask
  EarliestDeadlineFirst     serve the oldest believed unmet demand first
  GreedyUrgencyAgent        serve the highest belief-urgency node (eq:dynamic_urgency)
  PureALNSAgent             always FOLLOW the scaffold; spend the RESOLVE
                            budget when Delta_plan exceeds a threshold
                            (eq:plan_divergence)
  (ALNS+MAPPO = the learned MAPPOAgent; "no intent" = trainer ablation that
   empties the scaffold and disables RESOLVE)

All baselines share one interface:
    act(env, obs, masks, deciders) -> {uav: action_index}
They may introspect the environment's *belief-side* state (they are
command-center controllers) but never the latent truth.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np

from env.deprivation import belief_urgency
from env.uav_env import UAMTVRPIUEnv


class BaseAgent:
    name = "base"

    def act(self, env: UAMTVRPIUEnv, obs, masks, deciders) -> Dict[int, int]:
        raise NotImplementedError


class RandomAgent(BaseAgent):
    name = "Random"

    def __init__(self, seed: int = 0):
        self.rng = np.random.default_rng(seed)

    def act(self, env, obs, masks, deciders):
        return {u: int(self.rng.choice(np.flatnonzero(masks[u])))
                for u in deciders}


def _insert_or_follow(env, masks, u, target):
    """INSERT(target) if feasible and not already the next stop, else FOLLOW."""
    if target is None:
        return env.A_FOLLOW
    nxt = env.scaffold.peek_next(u)
    if nxt is not None and nxt.node == target:
        return env.A_FOLLOW
    a = env.encode_insert(target)
    return a if masks[u][a] else env.A_FOLLOW


class EarliestDeadlineFirstAgent(BaseAgent):
    """Oldest outstanding believed demand first (belief age_hat as deadline)."""

    name = "Earliest Deadline"

    def act(self, env, obs, masks, deciders):
        actions = {}
        claimed = set()
        for u in deciders:
            candidates = []
            for i in env.belief.known:
                if i in claimed or env.belief.d_tilde(i).sum() <= 1e-9:
                    continue
                age = float(env.belief.age_hat(i, env.t).max())
                candidates.append((age, i))
            candidates.sort(reverse=True)
            target = None
            for _, i in candidates:
                if masks[u][env.encode_insert(i)]:
                    target = i
                    break
            actions[u] = _insert_or_follow(env, masks, u, target)
            if target is not None and actions[u] != env.A_FOLLOW:
                claimed.add(target)
        return actions


class GreedyUrgencyAgent(BaseAgent):
    """Highest dynamic belief urgency U_hat_i first (eq:dynamic_urgency)."""

    name = "Greedy Urgency"

    def act(self, env, obs, masks, deciders):
        w_k, lambda_k, alpha_k, kappa_k = env.p.commodities.as_arrays()
        actions = {}
        claimed = set()
        for u in deciders:
            best, best_u = None, -1.0
            for i in env.belief.known:
                if i in claimed or env.belief.d_tilde(i).sum() <= 1e-9:
                    continue
                if not masks[u][env.encode_insert(i)]:
                    continue
                U = belief_urgency(env.nodes[i].nu, env.belief.d_tilde(i),
                                   env.belief.age_hat(i, env.t),
                                   lambda_k, alpha_k, kappa_k)
                if U > best_u:
                    best, best_u = i, U
            actions[u] = _insert_or_follow(env, masks, u, best)
            if best is not None and actions[u] != env.A_FOLLOW:
                claimed.add(best)
        return actions


class PureALNSAgent(BaseAgent):
    """FOLLOW the scaffold; trigger a global re-solve when the plan-divergence
    descriptor exceeds a threshold and budget remains (sec: hybrid_interface)."""

    name = "Pure ALNS"

    def __init__(self, divergence_threshold: float = 4.0):
        self.threshold = divergence_threshold

    def act(self, env, obs, masks, deciders):
        actions = {u: env.A_FOLLOW for u in deciders}
        if env.K_rem > 0:
            dp, _ = env.plan_divergence_now()
            if dp > self.threshold:
                u0 = deciders[0]
                if masks[u0][env.A_RESOLVE]:
                    actions[u0] = env.A_RESOLVE
        return actions


def make_baselines(seed: int = 0) -> List[BaseAgent]:
    return [RandomAgent(seed), EarliestDeadlineFirstAgent(),
            GreedyUrgencyAgent(), PureALNSAgent()]
