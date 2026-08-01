"""
UAV energy model (manuscript sec: uav_fleet).

Implements eq:flight_energy, eq:service_energy, eq:sortie_energy and the
safe-return feasibility constraint C5 (eq:safe_return_constraint).
"""

from __future__ import annotations

from typing import Sequence

from .params import PhysicsParams


def flight_energy(L: float, payload_mass: float, p: PhysicsParams) -> float:
    """E^fly_{ij,u} = L_ij * e_c * (m0 + w_pay)   (eq:flight_energy)."""
    return L * p.e_c * (p.m0 + payload_mass)


def service_energy(p: PhysicsParams) -> float:
    """E^serv = e_v   (eq:service_energy)."""
    return p.e_v


def sortie_energy(leg_lengths: Sequence[float],
                  leg_payload_masses: Sequence[float],
                  p: PhysicsParams) -> float:
    """
    Total sortie energy (eq:sortie_energy).

    ``leg_lengths`` are the lengths of all flight legs including the final
    return leg to the depot; ``leg_payload_masses[i]`` is the onboard payload
    mass *before* flying leg i (payload-dependent energy evaluated with the
    load carried on that leg). A service maneuver (E^serv) is charged after
    every leg except the final return leg.
    """
    if len(leg_lengths) != len(leg_payload_masses):
        raise ValueError("leg_lengths and leg_payload_masses must have equal length")
    e = 0.0
    n = len(leg_lengths)
    for i, (L, w) in enumerate(zip(leg_lengths, leg_payload_masses)):
        e += flight_energy(L, w, p)
        if i < n - 1:                       # service at every intermediate stop
            e += service_energy(p)
    return e


def safe_return_energy(L_to_i: float, L_i_to_depot: float,
                       payload_mass: float, payload_mass_after: float,
                       p: PhysicsParams) -> float:
    """
    Energy required by C5's right-hand side, excluding beta_safe:
    E^fly(q_u -> i, current payload) + E^serv + E^fly(i -> v0, post-delivery payload).
    The return leg is evaluated at t_i^+ i.e. with the payload remaining after
    the delivery at i (eq:safe_return_constraint).
    """
    return (flight_energy(L_to_i, payload_mass, p)
            + service_energy(p)
            + flight_energy(L_i_to_depot, payload_mass_after, p))


def is_safe_return_feasible(b: float, L_to_i: float, L_i_to_depot: float,
                            payload_mass: float, payload_mass_after: float,
                            p: PhysicsParams) -> bool:
    """C5: b_u >= E^fly(q,i) + E^serv + E^fly(i,0) + beta_safe   (eq:safe_return_constraint)."""
    return b >= safe_return_energy(L_to_i, L_i_to_depot,
                                   payload_mass, payload_mass_after, p) + p.beta_safe


def max_service_radius(p: PhysicsParams, conservative: bool = True) -> float:
    """
    Maximum depot-to-node distance r such that a fully loaded single-stop
    out-and-back sortie satisfies C5 at full charge:

        B_max - beta_safe >= r*e_c*(m0+W_max) + e_v + r*e_c*(m0 + w_ret)

    conservative=True assumes the worst-case return still fully loaded
    (w_ret = W_max, e.g. demand vanished before arrival); otherwise an
    empty return (w_ret = 0). The scenario generator places all nodes
    within feasible_frac * (conservative radius), guaranteeing every node
    is C5-serviceable at full payload.
    """
    budget = p.B_max - p.beta_safe - p.e_v
    w_ret = p.W_max if conservative else 0.0
    denom = p.e_c * (2.0 * p.m0 + p.W_max + w_ret)
    return budget / denom
