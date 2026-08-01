"""
train_mappo.py — train and evaluate the hybrid ALNS+MAPPO controller on the
manuscript-faithful UA-MTVRP-IU environment.

    python scripts/train_mappo.py --episodes 500 --train-seed 42
    python scripts/train_mappo.py --scenario results/maps/scenario_seed42.json \
                                  --episodes 200
    python scripts/train_mappo.py --episodes 5 --smoke     # quick sanity run

Ablations (spec: 2026-07-02-mappo-architecture-design):
    ALNS+MAPPO (default), Pure MAPPO No Intent (--no-intent), and the
    rule-based baselines Pure ALNS / Greedy Urgency / Earliest Deadline /
    Random evaluated on the --eval-seeds scenarios.

Logs per episode: shared return, J_dep_true (eq:true_objective), J_dep_belief,
fill rate, resolves used, termination reason, losses -> CSV under
results/logs; checkpoints under results/models.
"""

import argparse
import csv
import json
import os
import random
import sys

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import numpy as np
import torch
import yaml

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from env.params import EnvParams  # noqa: E402
from env.scenario import Scenario  # noqa: E402
from env.scenario_generator import generate_scenario  # noqa: E402
from env.uav_env import UAMTVRPIUEnv  # noqa: E402
from env.alns_scaffold import Scaffold  # noqa: E402
from methods.belief_graph import PLAN_FEATURE_NAMES  # noqa: E402

METHOD_MODES = (
    "vanilla_mappo",
    "graph_mappo",
    "graph_mappo_fixed_alns",
    "graph_mappo_adaptive_alns",
)

DEFAULT_AGENT_CONFIG = {
    "lr_actor": 3e-4,
    "lr_critic": 1e-3,
    "gae_lambda": 0.95,
    "clip_param": 0.2,
    "entropy_coef": 0.01,
    "update_epochs": 4,
    "hidden_dim": 256,
    "encoder_dim": 128,
    "num_heads": 4,
    "num_layers": 2,
}
MAX_STEPS = 6000        # hard cap on decision events per episode (safety)


# ---------------------------------------------------------------------------
def load_agent_config(path):
    """Load the repository-style optional method YAML into agent kwargs."""
    if path is None:
        return {}, None
    with open(path, "r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Agent config must be a mapping: {path}")
    config = {
        key: payload[key]
        for key in DEFAULT_AGENT_CONFIG
        if key in payload
    }
    graph = payload.get("belief_graph", {})
    guidance = payload.get("alns_guidance", {})
    aliases = {
        "hidden_dim": "graph_hidden_dim",
        "num_layers": "graph_num_layers",
        "num_heads": "graph_num_heads",
        "dropout": "graph_dropout",
        "use_edge_features": "use_edge_features",
    }
    for source, target in aliases.items():
        if source in graph:
            config[target] = graph[source]
    for source, target in {
        "hidden_dim": "guidance_hidden_dim",
        "beta": "guidance_beta",
        "fixed_gate": "fixed_guidance_gate",
    }.items():
        if source in guidance:
            config[target] = guidance[source]
    method = payload.get("method", {})
    encoder = method.get("observation_encoder")
    guidance_mode = method.get("alns_guidance")
    inferred_mode = None
    if encoder == "flat":
        inferred_mode = "vanilla_mappo"
    elif encoder == "belief_graph":
        inferred_mode = {
            "none": "graph_mappo",
            "fixed": "graph_mappo_fixed_alns",
            "adaptive": "graph_mappo_adaptive_alns",
        }.get(guidance_mode)
        if inferred_mode is None:
            raise ValueError(
                "belief_graph method requires alns_guidance none/fixed/adaptive"
            )
    return config, inferred_mode


def strip_intent(env: UAMTVRPIUEnv) -> None:
    """'Pure MAPPO No Intent' ablation: empty scaffold, no RESOLVE budget —
    the policy must route via INSERT alone. Any cargo already loaded from the
    initial ALNS solve is returned to stock so no scaffold intent leaks in."""
    env.scaffold = Scaffold(plans={u: [] for u in range(env.M)},
                            created_t=env.t)
    env.scaffold.mu_snapshot = env.belief.snapshot_mu()
    env.scaffold.urgency_rank_snapshot = env._urgency_ranking()
    env.scaffold.known_snapshot = set(env.belief.known)
    env.K_rem = 0
    for uav in env.uavs:
        if uav.ell.sum() > 0:
            env.inventory.replenish(uav.ell)
            uav.ell = np.zeros_like(uav.ell)


def episode_metrics(env: UAMTVRPIUEnv, total_reward: float, steps: int) -> dict:
    m = env.metrics.summary()
    return {
        "reward": float(total_reward),
        "J_dep_true": m["J_dep_true"],
        "J_dep_belief": m["J_dep_belief"],
        "J_energy": m["J_energy"],
        "J_risk": m["J_risk"],
        "J_fair_gini": m["J_fair_gini"],
        "fill_rate": m["fill_rate"],
        "n_resolves": m["n_resolves"],
        "termination": m["termination_reason"],
        "steps": int(steps),
    }


def run_episode(
    env, scenario, agent=None, baseline=None, train=False,
    deterministic=False, no_intent=False, diagnostics=None,
):
    obs, info = env.reset(scenario=scenario)
    if no_intent:
        strip_intent(env)
        # rebuild masks/obs for the initial deciders under the empty scaffold
        info["masks"] = {u: env._action_mask(u) for u in info["deciders"]}
        env._action_mask_cache = info["masks"]
        obs = {u: env._build_obs(u) for u in info["deciders"]}
    if train:
        agent.begin_episode()
    total_reward, steps = 0.0, 0
    while not env.done and steps < MAX_STEPS:
        deciders = info["deciders"]
        masks = info["masks"]
        if baseline is not None:
            actions = baseline.act(env, obs, masks, deciders)
        else:
            gstate = env.get_global_state()
            graph = (
                env.get_operational_belief_graph()
                if agent.observation_encoder == "belief_graph"
                else None
            )
            actions, logps, value = agent.select_actions(
                obs, masks, gstate, deterministic=deterministic, graph=graph)
            if diagnostics is not None:
                for u in deciders:
                    detail = agent.last_diagnostics.get(u, {})
                    features = np.asarray(
                        detail.get(
                            "plan_features",
                            np.zeros(len(PLAN_FEATURE_NAMES), dtype=float),
                        )
                    )
                    recommended = int(detail.get("recommended_action", -1))
                    diagnostics.append({
                        "decision_time_h": float(env.t),
                        "uav_id": int(u),
                        "known_node_count": int(
                            len(env.belief.known)
                        ),
                        "selected_action": int(actions[u]),
                        "operational_action_mask": json.dumps(
                            masks[u].astype(int).tolist(),
                            separators=(",", ":"),
                        ),
                        "alns_recommended_action": recommended,
                        "gate": float(detail.get("gate", 0.0)),
                        **{
                            name: float(features[index])
                            for index, name in enumerate(PLAN_FEATURE_NAMES)
                        },
                        "followed_alns": int(
                            recommended >= 0 and actions[u] == recommended
                        ),
                        "deviated_from_alns": int(
                            recommended >= 0 and actions[u] != recommended
                        ),
                    })
            if train:
                agent.record_decisions(env.t, obs, masks, gstate,
                                       actions, logps, value, graph=graph)
        t_interval_start = env.t
        obs, r, done, info = env.step(actions)
        if train:
            agent.record_reward(r, t_interval_start)
        total_reward += r
        steps += 1
    if train:
        agent.end_episode(env.t)
    return episode_metrics(env, total_reward, steps)


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=str, default=None,
                    help="env-params YAML (defaults to manuscript values)")
    ap.add_argument("--scenario", type=str, default=None,
                    help="fixed scenario JSON to train on (from create_map.py)")
    ap.add_argument("--train-seed", type=int, default=42)
    ap.add_argument("--eval-seeds", type=int, nargs="+", default=[100, 2026])
    ap.add_argument("--episodes", type=int, default=500)
    ap.add_argument("--mode", choices=METHOD_MODES, default=None,
                    help="optional belief-graph and ALNS-guidance mode")
    ap.add_argument("--agent-config", type=str, default=None,
                    help="optional agent/method YAML")
    ap.add_argument("--device", type=str, default="cpu")
    ap.add_argument("--no-intent", action="store_true",
                    help="also train the Pure-MAPPO-No-Intent ablation")
    ap.add_argument("--resume", type=str, default=None)
    ap.add_argument("--smoke", action="store_true",
                    help="short episodes for a quick sanity check")
    ap.add_argument("--skip-eval", action="store_true",
                    help="skip post-training evaluation (useful for smoke CI)")
    ap.add_argument("--output-dir", type=str,
                    default=os.path.join(os.path.dirname(__file__), "..",
                                         "results"))
    args = ap.parse_args()
    loaded_agent_config, inferred_mode = load_agent_config(args.agent_config)
    args.mode = args.mode or inferred_mode or "vanilla_mappo"
    random.seed(args.train_seed)
    np.random.seed(args.train_seed)
    torch.manual_seed(args.train_seed)

    from agents.baselines import make_baselines  # noqa: E402 (torch-free)
    from agents.mappo_agent import MAPPOAgent  # noqa: E402 (needs torch)

    params = EnvParams.from_yaml(args.config) if args.config else EnvParams()
    if args.smoke:
        params.mission.T = 1.0
        params.hybrid.alns_iterations = 10

    os.makedirs(os.path.join(args.output_dir, "logs"), exist_ok=True)
    os.makedirs(os.path.join(args.output_dir, "models"), exist_ok=True)

    fixed_scenario = Scenario.from_json(args.scenario) if args.scenario else None
    env = UAMTVRPIUEnv(params)
    # probe dims
    probe = fixed_scenario or generate_scenario(args.train_seed, params)
    env.reset(scenario=probe)
    agent_cfg = dict(
        DEFAULT_AGENT_CONFIG,
        **loaded_agent_config,
        gamma_hour=params.mission.gamma_hour,
        device=args.device,
        method_mode=args.mode,
    )
    agent = MAPPOAgent(num_agents=env.M, obs_dims=env.obs_dims,
                       action_dim=env.n_actions, config=agent_cfg)
    if args.resume:
        agent.load(args.resume)
        print(f"resumed from {args.resume}")

    # ---- training loop --------------------------------------------------
    log_path = os.path.join(
        args.output_dir, "logs", f"{args.mode}_train_log.csv"
    )
    diagnostics_path = os.path.join(
        args.output_dir, "logs", f"{args.mode}_decision_diagnostics.csv"
    )
    diagnostic_rows = []
    fields = ["episode", "actor_loss", "critic_loss", "reward", "J_dep_true",
              "J_dep_belief", "J_energy", "J_risk", "J_fair_gini",
              "fill_rate", "n_resolves", "termination", "steps"]
    write_header = not (args.resume and os.path.exists(log_path))
    log_f = open(log_path, "a" if not write_header else "w",
                 newline="", encoding="utf-8")
    writer = csv.DictWriter(log_f, fieldnames=fields)
    if write_header:
        writer.writeheader()

    print(f"training {args.mode}: {args.episodes} episodes, "
          f"{'fixed scenario ' + str(args.scenario) if fixed_scenario else 'seeds from ' + str(args.train_seed)}")
    interval = max(1, args.episodes // 20)
    for ep in range(1, args.episodes + 1):
        scenario = fixed_scenario or generate_scenario(
            args.train_seed + ep, params)
        agent.set_train()
        m = run_episode(
            env, scenario, agent=agent, train=True,
            diagnostics=diagnostic_rows,
        )
        a_loss, c_loss = agent.update()
        row = {"episode": ep, "actor_loss": a_loss, "critic_loss": c_loss, **m}
        writer.writerow(row)
        log_f.flush()
        if ep == 1 or ep % interval == 0:
            print(f"  ep {ep:4d} | R {m['reward']:10.1f} | "
                  f"J_true {m['J_dep_true']:9.1f} | fill {m['fill_rate']:.2f} | "
                  f"resolves {m['n_resolves']} | {m['termination']:<16} | "
                  f"aL {a_loss:+.3f} cL {c_loss:.3f}")
        if ep % 50 == 0 or ep == args.episodes:
            agent.save(os.path.join(args.output_dir, "models",
                                    f"{args.mode}.pt"))
    log_f.close()
    model_path = os.path.join(args.output_dir, "models", f"{args.mode}.pt")
    agent.save(model_path)
    diagnostic_fields = [
        "decision_time_h", "uav_id", "known_node_count", "selected_action",
        "operational_action_mask", "alns_recommended_action", "gate",
        *PLAN_FEATURE_NAMES, "followed_alns", "deviated_from_alns",
    ]
    with open(diagnostics_path, "w", newline="", encoding="utf-8") as f:
        diagnostic_writer = csv.DictWriter(f, fieldnames=diagnostic_fields)
        diagnostic_writer.writeheader()
        diagnostic_writer.writerows(diagnostic_rows)

    # ---- evaluation ------------------------------------------------------
    rows = []
    if not args.skip_eval:
        agent.set_eval()
        for seed in args.eval_seeds:
            scn = generate_scenario(seed, params)
            m = run_episode(env, scn, agent=agent, deterministic=True)
            rows.append({"Agent": args.mode, "Seed": seed, **m})
            for b in make_baselines(seed):
                m = run_episode(env, scn, baseline=b)
                rows.append({"Agent": b.name, "Seed": seed, **m})

    if args.no_intent:
        print("training Pure-MAPPO-No-Intent ablation")
        agent_ni = MAPPOAgent(num_agents=env.M, obs_dims=env.obs_dims,
                              action_dim=env.n_actions, config=agent_cfg)
        for ep in range(1, args.episodes + 1):
            scenario = fixed_scenario or generate_scenario(
                args.train_seed + ep, params)
            run_episode(env, scenario, agent=agent_ni, train=True,
                        no_intent=True)
            agent_ni.update()
        agent_ni.save(os.path.join(args.output_dir, "models",
                                   "mappo_no_intent.pt"))
        for seed in args.eval_seeds:
            scn = generate_scenario(seed, params)
            m = run_episode(env, scn, agent=agent_ni, deterministic=True,
                            no_intent=True)
            rows.append({"Agent": "Pure MAPPO No Intent", "Seed": seed, **m})

    eval_path = os.path.join(
        args.output_dir, "logs", f"{args.mode}_eval_metrics.csv"
    )
    if rows:
        with open(eval_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["Agent", "Seed"] + [
                k for k in rows[0] if k not in ("Agent", "Seed")])
            w.writeheader()
            w.writerows(rows)

        print("\nevaluation (lower J_dep_true is better):")
        for r in rows:
            print(f"  {r['Agent']:<28} seed {r['Seed']:<5} "
                  f"J_true {r['J_dep_true']:10.1f}  fill {r['fill_rate']:.2f}  "
                  f"reward {r['reward']:10.1f}  [{r['termination']}]")
    print(f"\nlogs -> {log_path}")
    print(f"diagnostics -> {diagnostics_path}")
    print(f"checkpoint -> {model_path}")
    if rows:
        print(f"eval -> {eval_path}")


if __name__ == "__main__":
    main()
