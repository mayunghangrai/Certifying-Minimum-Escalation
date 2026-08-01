"""Energy model tests against the manuscript equations (sec: uav_fleet)."""

import numpy as np
import pytest

from env.energy import (flight_energy, is_safe_return_feasible,
                        max_service_radius, safe_return_energy,
                        service_energy, sortie_energy)
from env.params import PhysicsParams


@pytest.fixture
def phys():
    return PhysicsParams()  # manuscript constants


def test_manuscript_constants(phys):
    assert phys.W_max == 2.5
    assert phys.m0 == 4.0
    assert phys.B_max == 230.0
    assert phys.e_c == 3.125
    assert phys.e_v == 2.5


def test_flight_energy_formula(phys):
    # eq:flight_energy: E = L * e_c * (m0 + w_pay)
    assert flight_energy(2.0, 1.5, phys) == pytest.approx(2.0 * 3.125 * 5.5)
    assert flight_energy(0.0, 2.5, phys) == 0.0
    # fully loaded, 1 km: 3.125 * 6.5 = 20.3125 Wh
    assert flight_energy(1.0, 2.5, phys) == pytest.approx(20.3125)


def test_service_energy(phys):
    assert service_energy(phys) == 2.5  # eq:service_energy


def test_sortie_energy_two_stops(phys):
    # depot -> A (2 km, full 2.5 kg) -> B (1 km, 1.0 kg left) -> depot (3 km, empty)
    legs = [2.0, 1.0, 3.0]
    masses = [2.5, 1.0, 0.0]
    expected = (2.0 * 3.125 * 6.5 + 2.5      # leg 1 + service at A
                + 1.0 * 3.125 * 5.0 + 2.5    # leg 2 + service at B
                + 3.0 * 3.125 * 4.0)         # return leg, no service
    assert sortie_energy(legs, masses, phys) == pytest.approx(expected)


def test_safe_return_constraint_boundary(phys):
    # eq:safe_return_constraint: b >= E(q->i) + e_v + E(i->0) + beta_safe
    need = safe_return_energy(3.0, 3.0, 2.5, 0.0, phys)
    expected = 3.0 * 3.125 * 6.5 + 2.5 + 3.0 * 3.125 * 4.0
    assert need == pytest.approx(expected)
    b_exact = need + phys.beta_safe
    assert is_safe_return_feasible(b_exact, 3.0, 3.0, 2.5, 0.0, phys)
    assert not is_safe_return_feasible(b_exact - 1e-6, 3.0, 3.0, 2.5, 0.0, phys)


def test_max_service_radius(phys):
    # conservative: (B_max - beta - e_v) / (e_c * (2 m0 + 2 W_max))
    r_cons = max_service_radius(phys, conservative=True)
    assert r_cons == pytest.approx((230.0 - 23.0 - 2.5) / (3.125 * 13.0))
    # optimistic (empty return) is larger
    r_opt = max_service_radius(phys, conservative=False)
    assert r_opt > r_cons
    assert r_opt == pytest.approx((230.0 - 23.0 - 2.5) / (3.125 * 10.5))
    # a fully loaded out-and-back at the conservative radius is C5-feasible
    need = safe_return_energy(r_cons, r_cons, 2.5, 2.5, phys)
    assert phys.B_max >= need + phys.beta_safe - 1e-9
