"""Pure integration of caller-supplied paths; no route construction or search."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math

from .energy import flight_power, ground_speed
from .units import speed_field, time_field
from .wind import WindField


@dataclass(frozen=True)
class WindSlice:
    cell_id: str
    bin_index: int
    start_h: float
    end_h: float
    distance_km: float
    ground_speed_kmh: float
    energy_wh: float


@dataclass(frozen=True)
class FlightResult:
    status: str
    arrival_h: float | None
    duration_h: float | None
    energy_wh: float | None
    slices: tuple[WindSlice, ...]

    def to_dict(self):
        return asdict(self)


def evaluate_path(scenario, uav_id, path, departure_h, onboard, projection='received'):
    """Integrate exact distances in each constant-wind bin, including at T.

    Times, distances and speeds are in the scenario's units (v2: h, km;
    v3: s, m) under the historical `_h`/`_km`/`_kmh` names; energy is Wh.

    A late path has no final duration, energy or arrival. Its slices contain
    only defined prefix integration records, never an extrapolation past T.
    Flight completion says nothing about available battery or payload capacity.
    """
    for value in (departure_h, onboard):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('departure time and onboard quantity must be finite scalars')
    if onboard < 0 or departure_h < scenario.data['mission'][time_field(scenario.data, 'epoch')]:
        raise ValueError('negative load or pre-epoch departure')
    fleet = {u['id']: u for u in scenario.data['mission']['vehicles']}
    if uav_id not in fleet:
        raise ValueError('unknown UAV')
    field = WindField(scenario, projection)
    pieces = field.split_path(path)
    horizon = field.knots[-1]
    if departure_h > horizon:
        return FlightResult('late', None, None, None, ())
    vehicle = fleet[uav_id]
    power = flight_power(vehicle, scenario.data['mission']['commodity_unit_mass_kg'], onboard)
    if scenario.data['schema_version'] == 'wind-benchmark-v3':
        power = power/3600          # W -> Wh per second
    airspeed = vehicle[speed_field(scenario.data, 'airspeed')]
    time = departure_h
    slices = []
    admissible = True
    for start,end,cell in pieces:
        length = math.dist(start, end)
        if length == 0:     # a path through a cell corner can split into an empty piece
            continue
        direction = ((end[0]-start[0])/length, (end[1]-start[1])/length)
        remaining = length
        while remaining > 0:
            if time >= horizon:
                return FlightResult('late', None, None, None, tuple(slices))
            j = field.time_bin(time)
            if field.coverage[j] == 'missing':
                return FlightResult('unavailable', None, None, None, tuple(slices))
            admissible = admissible and field.admissible[cell][j]
            speed = ground_speed(airspeed, direction, field.values[cell][j])
            bin_end = field.knots[j+1]
            finish = time + remaining/speed
            if finish <= bin_end:
                end_time, distance = finish, remaining
                remaining = 0.
            else:
                end_time = bin_end
                distance = speed*(end_time-time)
                remaining -= distance
            slices.append(WindSlice(field.data['cells'][cell]['id'], j, time, end_time, distance, speed, power*(end_time-time)))
            time = end_time
    return FlightResult('complete' if admissible else 'closed', time, time-departure_h,
                        power*(time-departure_h), tuple(slices))
