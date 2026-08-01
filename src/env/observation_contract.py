"""Frozen legacy MAPPO/ALNS observation contract.

Scenario-v2 spatial state is deliberately excluded from these tensors. Any
future neural encoding change requires a separate methodology revision.
"""

from __future__ import annotations


OWN_FEATURE_ORDER = (
    "position_x",
    "position_y",
    "payload_medical",
    "payload_food",
    "payload_water",
    "payload_shelter",
    "payload_mass",
    "battery",
    "mode_depot",
    "mode_loading",
    "mode_charging",
    "mode_flying",
    "mode_delivering",
    "mode_returning",
    "sortie_index",
    "mission_time",
    "resolve_budget",
)

NODE_FEATURE_ORDER = (
    "position_x",
    "position_y",
    "known",
    "belief_mu_medical",
    "belief_mu_food",
    "belief_mu_water",
    "belief_mu_shelter",
    "belief_sigma_medical",
    "belief_sigma_food",
    "belief_sigma_water",
    "belief_sigma_shelter",
    "report_confidence",
    "report_age",
    "reported_vulnerability",
    "risk_adjusted_payload_mass",
    "oldest_believed_age",
    "log_believed_urgency",
    "in_scaffold",
    "next_scaffold_node",
    "believed_availability",
)

FLEET_FEATURE_ORDER = (
    "relative_x",
    "relative_y",
    "payload_mass",
    "battery",
    "mode_depot",
    "mode_loading",
    "mode_charging",
    "mode_flying",
    "mode_delivering",
    "mode_returning",
    "relative_distance",
)

EVENT_FEATURE_ORDER = (
    "p1_count",
    "p2_count",
    "p4_count",
    "availability_count",
    "plan_divergence",
    "demand_divergence",
    "ranking_divergence",
    "revealed_node_count",
    "invalid_leg_count",
    "scaffold_age",
    "stock_medical",
    "stock_food",
    "stock_water",
    "stock_shelter",
    "remaining_time",
)

ACTOR_BLOCK_ORDER = ("own", "nodes", "fleet", "event")
