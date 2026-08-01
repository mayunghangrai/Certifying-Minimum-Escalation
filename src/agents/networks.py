"""
Actor/critic networks for the event-driven UA-MTVRP-IU environment.

Observation layout (see UAMTVRPIUEnv.obs_dims / eq:agent_observation):
  actor : [ own(17) | nodes(N x 20) | fleet((M-1) x 11) | event(15) ]
  critic: [ uavs(M x 17) | nodes(N x 26) | event(15) ]   (eq:global_state)

Node slot 2 is the "known" flag (C1); unknown nodes are zero vectors and are
excluded from actor attention via the padding mask — the policy physically
cannot attend to unrevealed nodes (partial observability). The centralized
critic attends to all nodes, including latent truth features.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

KNOWN_FLAG_IDX = 2


class TransformerNodeEncoder(nn.Module):
    """Multi-head self-attention over node slots with masked mean pooling."""

    def __init__(self, node_dim, embed_dim=128, num_heads=4, num_layers=2):
        super().__init__()
        self.embedding = nn.Linear(node_dim, embed_dim)
        layer = nn.TransformerEncoderLayer(d_model=embed_dim, nhead=num_heads,
                                           batch_first=True)
        self.transformer = nn.TransformerEncoder(layer, num_layers=num_layers)

    def forward(self, nodes, padding_mask=None):
        # nodes: (B, N, node_dim); padding_mask: (B, N), True = hidden
        x = F.relu(self.embedding(nodes))
        if padding_mask is not None and bool(padding_mask.all(dim=1).any()):
            # guard: a fully masked row would produce NaNs — unmask slot 0
            padding_mask = padding_mask.clone()
            padding_mask[padding_mask.all(dim=1), 0] = False
        x = self.transformer(x, src_key_padding_mask=padding_mask)
        if padding_mask is not None:
            keep = (~padding_mask).unsqueeze(-1).float()
            return (x * keep).sum(dim=1) / keep.sum(dim=1).clamp(min=1e-8)
        return x.mean(dim=1)


class MAPPOActor(nn.Module):
    """Decentralized actor over o_u with C1-C6 action masking (eq:high_level_actions)."""

    def __init__(self, own_dim, node_dim, n_nodes, rest_dim, action_dim,
                 hidden_dim=256, encoder_dim=128, num_heads=4, num_layers=2):
        super().__init__()
        self.own_dim = own_dim
        self.node_dim = node_dim
        self.n_nodes = n_nodes
        self.rest_dim = rest_dim          # fleet + event features
        self.encoder = TransformerNodeEncoder(node_dim, encoder_dim,
                                              num_heads, num_layers)
        combined = own_dim + encoder_dim + rest_dim
        self.fc1 = nn.Linear(combined, hidden_dim)
        self.ln1 = nn.LayerNorm(hidden_dim)
        self.fc2 = nn.Linear(hidden_dim, hidden_dim)
        self.ln2 = nn.LayerNorm(hidden_dim)
        self.fc3 = nn.Linear(hidden_dim, hidden_dim)
        self.ln3 = nn.LayerNorm(hidden_dim)
        self.action_out = nn.Linear(hidden_dim, action_dim)

    def forward(self, obs, action_mask=None):
        if obs.dim() == 1:
            obs = obs.unsqueeze(0)
            if action_mask is not None and action_mask.dim() == 1:
                action_mask = action_mask.unsqueeze(0)
        own = obs[:, :self.own_dim]
        node_end = self.own_dim + self.n_nodes * self.node_dim
        nodes = obs[:, self.own_dim:node_end].view(-1, self.n_nodes, self.node_dim)
        rest = obs[:, node_end:]
        padding_mask = nodes[:, :, KNOWN_FLAG_IDX] == 0        # C1: unknown hidden
        pooled = self.encoder(nodes, padding_mask)
        x = torch.cat([own, pooled, rest], dim=-1)
        x = F.relu(self.ln1(self.fc1(x)))
        x = F.relu(self.ln2(self.fc2(x)))
        x = F.relu(self.ln3(self.fc3(x)))
        logits = self.action_out(x)
        if action_mask is not None:
            logits = logits.masked_fill(action_mask == 0, -1e8)
        return F.softmax(logits, dim=-1), logits


class MAPPOCritic(nn.Module):
    """Centralized critic over the latent global state s(t) (eq:global_state)."""

    def __init__(self, n_agents, own_dim, node_dim, n_nodes, event_dim,
                 hidden_dim=256, encoder_dim=128, num_heads=4, num_layers=2):
        super().__init__()
        self.uav_dim = n_agents * own_dim
        self.node_dim = node_dim
        self.n_nodes = n_nodes
        self.event_dim = event_dim
        self.uav_encoder = nn.Sequential(
            nn.Linear(self.uav_dim, encoder_dim),
            nn.LayerNorm(encoder_dim), nn.ReLU())
        self.node_encoder = TransformerNodeEncoder(node_dim, encoder_dim,
                                                   num_heads, num_layers)
        self.event_encoder = nn.Sequential(
            nn.Linear(event_dim, encoder_dim),
            nn.LayerNorm(encoder_dim), nn.ReLU())
        self.fc1 = nn.Linear(encoder_dim * 3, hidden_dim)
        self.ln1 = nn.LayerNorm(hidden_dim)
        self.fc2 = nn.Linear(hidden_dim, hidden_dim)
        self.ln2 = nn.LayerNorm(hidden_dim)
        self.value_out = nn.Linear(hidden_dim, 1)

    def forward(self, global_obs):
        if global_obs.dim() == 1:
            global_obs = global_obs.unsqueeze(0)
        uavs = global_obs[:, :self.uav_dim]
        node_end = self.uav_dim + self.n_nodes * self.node_dim
        nodes = global_obs[:, self.uav_dim:node_end].view(
            -1, self.n_nodes, self.node_dim)
        event = global_obs[:, node_end:node_end + self.event_dim]
        # the critic attends to every node (it sees latent truth)
        x = torch.cat([self.uav_encoder(uavs),
                       self.node_encoder(nodes, None),
                       self.event_encoder(event)], dim=-1)
        x = F.relu(self.ln1(self.fc1(x)))
        x = F.relu(self.ln2(self.fc2(x)))
        return self.value_out(x)
