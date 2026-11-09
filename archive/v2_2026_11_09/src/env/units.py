"""Exact, unit-aware reads of v1/v2 (km, h) and v3 (m, s) scenarios.

Every value is returned as a Fraction in the scenario's own units. Energy is
always in Wh: v2 power is gamma * mass * airspeed, v3 power is a + b * mass,
and both are watts, so energy = power * dt * (hours per time unit).
"""
from __future__ import annotations

from fractions import Fraction

V1, V2, V3 = 'wind-benchmark-v1', 'wind-benchmark-v2', 'wind-benchmark-v3'
_TIME = {V1: '_h', V2: '_h', V3: '_s'}
_SPEED = {V1: '_kmh', V2: '_kmh', V3: '_mps'}
_HOURS_PER_TIME_UNIT = {V1: Fraction(1), V2: Fraction(1), V3: Fraction(1, 3600)}


def exact(value):
    return Fraction(str(value))


def version(data):
    v = data['schema_version']
    if v not in _TIME:
        raise ValueError(f'units are defined only for {V1}, {V2} and {V3}')
    return v


def time_field(data, stem):
    return stem + _TIME[version(data)]


def epoch(data):
    return exact(data['mission'][time_field(data, 'epoch')])


def horizon(data):
    return exact(data['mission'][time_field(data, 'horizon')])


def deadline(data, task):
    value = task[time_field(data, 'deadline')]
    return None if value is None else exact(value)


def time_knots(data):
    return tuple(map(exact, data['wind'][time_field(data, 'time_knots')]))


def service_duration(data):
    return exact(data['operations'][time_field(data, 'service_duration')])


def preparation_duration(data):
    return exact(data['operations'][time_field(data, 'preparation_duration')])


def residual_duration(data, residual):
    return exact(residual[time_field(data, 'duration')])


def issued_at(data, projection):
    return exact(data['wind'][projection][time_field(data, 'issued_at')])


def speed_field(data, stem):
    return stem + _SPEED[version(data)]


def airspeed(data, vehicle):
    return exact(vehicle['airspeed' + _SPEED[version(data)]])


def speed_bound(data):
    return exact(data['wind']['speed_bound' + _SPEED[version(data)]])


def wind_values(data, projection):
    """values[cell][bin] as exact (x, y) vectors in the scenario's speed unit."""
    return tuple(tuple(tuple(map(exact, w)) for w in row)
                 for row in data['wind'][projection]['values'])


def mass(data, vehicle, onboard):
    """Total flying mass in kg with `onboard` commodity units."""
    return exact(vehicle['empty_mass_kg']) + exact(data['mission']['commodity_unit_mass_kg'])*exact(onboard)


def energy_coefficients(data, vehicle, dt):
    """(constant Wh, Wh per kg of total mass) for a flight of duration dt.

    Energy is affine in total mass, so callers holding a symbolic load can
    build it as constant + per_kg * mass.
    """
    dt = exact(dt)
    hours = dt*_HOURS_PER_TIME_UNIT[version(data)]
    if version(data) != V3:
        return Fraction(0), exact(vehicle['energy_coefficient_wh_per_kg_km'])*airspeed(data, vehicle)*hours
    return exact(vehicle['power_a_w'])*hours, exact(vehicle['power_b_w_per_kg'])*hours


def energy_wh(data, vehicle, mass_kg, dt):
    constant, per_kg = energy_coefficients(data, vehicle, dt)
    return constant + per_kg*exact(mass_kg)


def power_w(data, vehicle, mass_kg):
    """Flight power in W (= Wh per hour)."""
    constant, per_kg = energy_coefficients(data, vehicle, 1/_HOURS_PER_TIME_UNIT[version(data)])
    return constant + per_kg*exact(mass_kg)
