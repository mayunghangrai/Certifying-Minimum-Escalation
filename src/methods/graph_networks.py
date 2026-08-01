"""Pure-PyTorch edge-aware graph networks for the optional methodology."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, List

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from .belief_graph import (
    NODE_TYPE_DEPOT,
    NODE_TYPE_UAV,
    PLAN_FEATURE_NAMES,
    BeliefGraph,
)


@dataclass
class TorchBeliefGraphBatch:
    node_features: torch.Tensor
    node_type_ids: torch.Tensor
    edge_index: torch.Tensor
    edge_features: torch.Tensor
    node_mask: torch.Tensor
    edge_mask: torch.Tensor
    graph_batch_index: torch.Tensor
    uav_to_node: torch.Tensor

    @classmethod
    def collate(
        cls, graphs: Iterable[BeliefGraph], device: torch.device
    ) -> "TorchBeliefGraphBatch":
        items = list(graphs)
        if not items:
            raise ValueError("Cannot collate an empty graph batch")
        return cls(
            node_features=torch.as_tensor(
                np.stack([g.node_features for g in items]),
                dtype=torch.float32,
                device=device,
            ),
            node_type_ids=torch.as_tensor(
                np.stack([g.node_type_ids for g in items]),
                dtype=torch.long,
                device=device,
            ),
            edge_index=torch.as_tensor(
                np.stack([g.edge_index for g in items]),
                dtype=torch.long,
                device=device,
            ),
            edge_features=torch.as_tensor(
                np.stack([g.edge_features for g in items]),
                dtype=torch.float32,
                device=device,
            ),
            node_mask=torch.as_tensor(
                np.stack([g.node_mask for g in items]),
                dtype=torch.bool,
                device=device,
            ),
            edge_mask=torch.as_tensor(
                np.stack([g.edge_mask for g in items]),
                dtype=torch.bool,
                device=device,
            ),
            graph_batch_index=torch.as_tensor(
                np.stack([g.graph_batch_index for g in items]),
                dtype=torch.long,
                device=device,
            ),
            uav_to_node=torch.as_tensor(
                np.stack([g.uav_to_node for g in items]),
                dtype=torch.long,
                device=device,
            ),
        )


class EdgeAwareAttentionLayer(nn.Module):
    """Directed edge-aware multi-head message passing with masked softmax."""

    def __init__(
        self,
        hidden_dim: int,
        edge_dim: int,
        num_heads: int,
        dropout: float,
        use_edge_features: bool,
    ):
        super().__init__()
        if hidden_dim % num_heads:
            raise ValueError("hidden_dim must be divisible by num_heads")
        self.hidden_dim = hidden_dim
        self.num_heads = num_heads
        self.head_dim = hidden_dim // num_heads
        self.use_edge_features = use_edge_features
        self.q = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.k = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.v = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.edge_k = nn.Linear(edge_dim, hidden_dim, bias=False)
        self.edge_v = nn.Linear(edge_dim, hidden_dim, bias=False)
        self.out = nn.Linear(hidden_dim, hidden_dim)
        self.norm1 = nn.LayerNorm(hidden_dim)
        self.ff = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim * 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim * 2, hidden_dim),
        )
        self.norm2 = nn.LayerNorm(hidden_dim)
        self.dropout = nn.Dropout(dropout)

    def forward(
        self,
        nodes: torch.Tensor,
        edge_index: torch.Tensor,
        edge_features: torch.Tensor,
        node_mask: torch.Tensor,
        edge_mask: torch.Tensor,
    ) -> torch.Tensor:
        batch_size, node_count, _ = nodes.shape
        q = self.q(nodes).view(
            batch_size, node_count, self.num_heads, self.head_dim
        )
        k = self.k(nodes).view_as(q)
        v = self.v(nodes).view_as(q)
        edge_k = self.edge_k(edge_features).view(
            batch_size, edge_features.shape[1], self.num_heads, self.head_dim
        )
        edge_v = self.edge_v(edge_features).view_as(edge_k)
        if not self.use_edge_features:
            edge_k = torch.zeros_like(edge_k)
            edge_v = torch.zeros_like(edge_v)
        messages = torch.zeros_like(q)
        scale = float(self.head_dim) ** -0.5
        for batch in range(batch_size):
            valid = torch.nonzero(edge_mask[batch], as_tuple=False).flatten()
            if valid.numel() == 0:
                continue
            source = edge_index[batch, 0, valid]
            destination = edge_index[batch, 1, valid]
            scores = (
                q[batch, destination]
                * (k[batch, source] + edge_k[batch, valid])
            ).sum(dim=-1) * scale
            values = v[batch, source] + edge_v[batch, valid]
            for target in torch.unique(destination):
                selected = torch.nonzero(
                    destination == target, as_tuple=False
                ).flatten()
                weights = torch.softmax(scores[selected], dim=0)
                messages[batch, target] = (
                    weights.unsqueeze(-1) * values[selected]
                ).sum(dim=0)
        messages = messages.reshape(batch_size, node_count, self.hidden_dim)
        updated = self.norm1(nodes + self.dropout(self.out(messages)))
        updated = self.norm2(updated + self.dropout(self.ff(updated)))
        return updated * node_mask.unsqueeze(-1).to(updated.dtype)


class BeliefGraphEncoder(nn.Module):
    """Type-aware, permutation-equivariant masked graph encoder."""

    def __init__(
        self,
        node_dim: int,
        edge_dim: int,
        hidden_dim: int = 128,
        num_layers: int = 2,
        num_heads: int = 4,
        dropout: float = 0.0,
        use_edge_features: bool = True,
    ):
        super().__init__()
        self.type_projections = nn.ModuleList(
            [nn.Linear(node_dim, hidden_dim) for _ in range(3)]
        )
        self.type_embedding = nn.Embedding(3, hidden_dim)
        self.layers = nn.ModuleList(
            [
                EdgeAwareAttentionLayer(
                    hidden_dim,
                    edge_dim,
                    num_heads,
                    dropout,
                    use_edge_features,
                )
                for _ in range(num_layers)
            ]
        )

    def forward(
        self, graph: TorchBeliefGraphBatch
    ) -> tuple[torch.Tensor, torch.Tensor]:
        nodes = torch.zeros(
            *graph.node_features.shape[:-1],
            self.type_embedding.embedding_dim,
            device=graph.node_features.device,
            dtype=graph.node_features.dtype,
        )
        for type_id, projection in enumerate(self.type_projections):
            selected = graph.node_type_ids == type_id
            projected = projection(graph.node_features)
            nodes = nodes + projected * selected.unsqueeze(-1).to(projected.dtype)
        nodes = F.relu(nodes + self.type_embedding(graph.node_type_ids))
        nodes = nodes * graph.node_mask.unsqueeze(-1).to(nodes.dtype)
        for layer in self.layers:
            nodes = layer(
                nodes,
                graph.edge_index,
                graph.edge_features,
                graph.node_mask,
                graph.edge_mask,
            )
        keep = graph.node_mask.unsqueeze(-1).to(nodes.dtype)
        pooled = (nodes * keep).sum(dim=1) / keep.sum(dim=1).clamp(min=1.0)
        return nodes, pooled


class GuidanceGate(nn.Module):
    """End-to-end sigmoid gate over individual observable plan features."""

    def __init__(self, hidden_dim: int):
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(len(PLAN_FEATURE_NAMES), hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )

    def logits(self, plan_features: torch.Tensor) -> torch.Tensor:
        """Return the exact pre-sigmoid gate activation."""
        return self.network(plan_features)

    def forward(self, plan_features: torch.Tensor) -> torch.Tensor:
        return torch.sigmoid(self.logits(plan_features))


class GraphMAPPOActor(nn.Module):
    """Belief-consistent graph actor with optional ALNS logit guidance."""

    def __init__(
        self,
        own_dim: int,
        flat_node_dim: int,
        flat_node_count: int,
        rest_dim: int,
        node_dim: int,
        edge_dim: int,
        action_dim: int,
        hidden_dim: int = 128,
        num_layers: int = 2,
        num_heads: int = 4,
        dropout: float = 0.0,
        use_edge_features: bool = True,
        guidance_mode: str = "none",
        guidance_hidden_dim: int = 64,
        beta: float = 1.0,
        fixed_gate: float = 0.5,
    ):
        super().__init__()
        if guidance_mode not in {"none", "fixed", "adaptive"}:
            raise ValueError(f"Unsupported ALNS guidance mode: {guidance_mode}")
        self.own_dim = own_dim
        self.flat_node_dim = flat_node_dim
        self.flat_node_count = flat_node_count
        self.rest_dim = rest_dim
        self.guidance_mode = guidance_mode
        self.beta = float(beta)
        self.fixed_gate = float(fixed_gate)
        self.graph_encoder = BeliefGraphEncoder(
            node_dim,
            edge_dim,
            hidden_dim,
            num_layers,
            num_heads,
            dropout,
            use_edge_features,
        )
        self.own_projection = nn.Sequential(
            nn.Linear(own_dim, hidden_dim), nn.LayerNorm(hidden_dim), nn.ReLU()
        )
        self.rest_projection = nn.Sequential(
            nn.Linear(rest_dim, hidden_dim), nn.LayerNorm(hidden_dim), nn.ReLU()
        )
        self.context_query = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.policy = nn.Sequential(
            nn.Linear(hidden_dim * 4, hidden_dim * 2),
            nn.LayerNorm(hidden_dim * 2),
            nn.ReLU(),
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
        )
        self.action_out = nn.Linear(hidden_dim, action_dim)
        self.guidance_gate = GuidanceGate(guidance_hidden_dim)

    def forward(
        self,
        obs: torch.Tensor,
        graph: TorchBeliefGraphBatch,
        uav_ids: torch.Tensor,
        action_mask: torch.Tensor,
        plan_features: torch.Tensor,
        alns_prior: torch.Tensor,
    ):
        if obs.dim() == 1:
            obs = obs.unsqueeze(0)
        encoded, pooled = self.graph_encoder(graph)
        batch_index = torch.arange(obs.shape[0], device=obs.device)
        uav_slots = graph.uav_to_node[batch_index, uav_ids]
        uav_context = encoded[batch_index, uav_slots]
        scores = torch.einsum(
            "bd,bnd->bn", self.context_query(uav_context), encoded
        ) / math.sqrt(encoded.shape[-1])
        scores = scores.masked_fill(~graph.node_mask, -1e9)
        attention = torch.softmax(scores, dim=-1)
        graph_context = torch.einsum("bn,bnd->bd", attention, encoded)

        node_end = self.own_dim + self.flat_node_count * self.flat_node_dim
        own = self.own_projection(obs[:, : self.own_dim])
        rest = self.rest_projection(obs[:, node_end:])
        policy_hidden = self.policy(
            torch.cat([own, uav_context, graph_context, rest], dim=-1)
        )
        base_logits = self.action_out(policy_hidden)
        gate_logit = self.guidance_gate.logits(plan_features)
        adaptive_gate = torch.sigmoid(gate_logit)
        if self.guidance_mode == "adaptive":
            gate = adaptive_gate
        elif self.guidance_mode == "fixed":
            gate = torch.full(
                (obs.shape[0], 1),
                self.fixed_gate,
                dtype=obs.dtype,
                device=obs.device,
            )
        else:
            gate = torch.zeros(
                (obs.shape[0], 1), dtype=obs.dtype, device=obs.device
            )
        hybrid_logits = base_logits + self.beta * gate * alns_prior
        masked_logits = hybrid_logits.masked_fill(action_mask == 0, -1e8)
        # Detached observability only: no RNG, backward, or policy-path change.
        self.last_gate_logit = gate_logit.detach()
        self.last_adaptive_gate = adaptive_gate.detach()
        self.last_hybrid_logits = hybrid_logits.detach()
        return (
            F.softmax(masked_logits, dim=-1),
            masked_logits,
            gate,
            base_logits,
            attention,
        )


class GraphMAPPOCritic(nn.Module):
    """Centralized critic using only the pooled operational belief graph."""

    def __init__(
        self,
        node_dim: int,
        edge_dim: int,
        hidden_dim: int = 128,
        num_layers: int = 2,
        num_heads: int = 4,
        dropout: float = 0.0,
        use_edge_features: bool = True,
    ):
        super().__init__()
        self.graph_encoder = BeliefGraphEncoder(
            node_dim,
            edge_dim,
            hidden_dim,
            num_layers,
            num_heads,
            dropout,
            use_edge_features,
        )
        self.value = nn.Sequential(
            nn.Linear(hidden_dim * 3, hidden_dim * 2),
            nn.LayerNorm(hidden_dim * 2),
            nn.ReLU(),
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, graph: TorchBeliefGraphBatch) -> torch.Tensor:
        encoded, pooled = self.graph_encoder(graph)
        uav_mask = (
            (graph.node_type_ids == NODE_TYPE_UAV) & graph.node_mask
        ).unsqueeze(-1)
        uav_summary = (
            encoded * uav_mask.to(encoded.dtype)
        ).sum(dim=1) / uav_mask.sum(dim=1).clamp(min=1).to(encoded.dtype)
        depot_mask = (
            (graph.node_type_ids == NODE_TYPE_DEPOT) & graph.node_mask
        ).unsqueeze(-1)
        depot_summary = (
            encoded * depot_mask.to(encoded.dtype)
        ).sum(dim=1) / depot_mask.sum(dim=1).clamp(min=1).to(encoded.dtype)
        return self.value(torch.cat([pooled, uav_summary, depot_summary], dim=-1))
