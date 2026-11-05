"""Flight power in W: v2 linear surrogate (Wh, kg, km, h) or v3 affine model."""
import math


def ground_speed(airspeed_kmh, direction, wind_xy):
    along = wind_xy[0]*direction[0] + wind_xy[1]*direction[1]
    across = -wind_xy[0]*direction[1] + wind_xy[1]*direction[0]
    # The scenario's strict wind bound guarantees a positive radicand and speed.
    return along + math.sqrt(airspeed_kmh**2 - across**2)


def flight_power(vehicle, unit_mass_kg, onboard):
    if 'power_a_w' in vehicle:      # v3: P = a + b*m
        return vehicle['power_a_w'] + vehicle['power_b_w_per_kg']*(vehicle['empty_mass_kg'] + unit_mass_kg*onboard)
    return (vehicle['energy_coefficient_wh_per_kg_km']
            * (vehicle['empty_mass_kg'] + unit_mass_kg*onboard)
            * vehicle['airspeed_kmh'])
