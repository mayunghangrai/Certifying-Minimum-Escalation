"""Canonical units and explicit legacy conversion helpers.

Scenario-v2 structured state uses SI-like mission units: metres, seconds,
watt-hours, kilograms, and standardized demand units.  The pre-existing
MAPPO/ALNS adapter continues to use kilometres and hours at its boundary.
"""

from __future__ import annotations

METRES_PER_KILOMETRE = 1000.0
SECONDS_PER_HOUR = 3600.0

CANONICAL_UNITS = {
    "distance": "metre",
    "time": "second",
    "energy": "watt_hour",
    "mass": "kilogram",
    "demand": "standardized_unit",
}


def metres_to_km(value: float) -> float:
    return float(value) / METRES_PER_KILOMETRE


def km_to_metres(value: float) -> float:
    return float(value) * METRES_PER_KILOMETRE


def seconds_to_hours(value: float) -> float:
    return float(value) / SECONDS_PER_HOUR


def hours_to_seconds(value: float) -> float:
    return float(value) * SECONDS_PER_HOUR


def metres_per_second_to_km_per_hour(value: float) -> float:
    return float(value) * 3.6


def km_per_hour_to_metres_per_second(value: float) -> float:
    return float(value) / 3.6
