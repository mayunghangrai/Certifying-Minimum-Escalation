"""A physically grounded case study: one fixed small-area mission flown by DJI FlyCart 30s.

docs/PHYSICAL_CASE_STUDY_2026_10_21.md. The mission geometry, demands, depot stock, task
urgency classes and incumbent (assignment, order, straight legs) are those of FS mission
FS_4x3_medium_ample_uniform_76029 (2 km x 2 km, 4 x 4 wind cells of 500 m, 4 UAVs, 12
tasks). Aircraft, energy, turnaround, deadlines, horizon and wind are replaced by the values
below. The wind-update conditions are fixed by rule, before any recovery label is seen.
"""
from copy import deepcopy
from fractions import Fraction

from continuous.validation import previous_premise
from env.local_scope import affected_uavs
from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update
from escalation_study.missions import delivery_times

SOURCE = 'FS_4x3_medium_ample_uniform_76029'
SOURCE_VARIANT = SOURCE+'_r1_t0'

# DJI FlyCart 30, dual-battery mode (https://www.dji.com/flycart-30/specs, read 21 Oct 2026).
CRUISE_MS = 15                      # speed of DJI's flight-distance measurements
MASS_WITH_BATTERIES_KG = 65
MAX_TAKEOFF_KG = 95
PAYLOAD_KG = 30                     # winch load 5-30 kg in dual-battery mode
BATTERY_WH = Fraction('3968.8')     # 2 x DB2000, 1984.4 Wh each
DISTANCE_KM = {65: 28, 95: 16}      # max flight distance at 15 m/s, no wind, by take-off mass
HOVER_MIN = {65: 29, 95: 18}
WIND_LIMIT_MS = 12                  # max wind resistance

KMH = Fraction(36, 10)              # 1 m/s in km/h
AIRSPEED_KMH = CRUISE_MS*KMH        # 54 km/h
SPEED_BOUND_KMH = WIND_LIMIT_MS*KMH  # 43.2 km/h, below the airspeed as the formulation requires

# Energy surrogate P = gamma m v: fitted to the 95 kg distance point, so that it never
# underestimates the documented consumption (it overstates the 65 kg point by 20%).
GAMMA = Fraction('2.62')
RESERVE_WH = BATTERY_WH/5           # 20% landing reserve

UNIT_KG = 6                         # one relief-kit unit; the largest route load (4 units) is 24 kg
# Winch delivery: descend 30 m at 3 m/s (10 s), lower 20 m at 0.8 m/s (25 s), release (10 s),
# retract (25 s), climb 30 m at 5 m/s (6 s): 76 s, rounded up to 90 s.
SERVICE_H = Fraction(1, 40)
# Hover power at maximum take-off weight, 3968.8 Wh / 18 min = 13.23 kW, for 90 s.
SERVICE_WH = 331
# Depot turnaround: battery swap to a charged pair and cargo loading, 3 min. A charged pair
# is what makes the model's reset to full capacity valid; charging in place would take at
# least 3968.8 Wh / (2 x 5700 W) = 21 min at the battery's maximum charging power.
PREPARATION_H = Fraction(1, 20)

# Operating scenario: flash flood in a 2 km x 2 km district, field depot at the centre, all
# requests known at dispatch (t = 0). Priority targets by the FS urgency class of each task:
# urgent medical (class 1) within 15 min, essential (10) within 30 min, routine (50) within
# 60 min. The dispatch wave holds a 90 min airspace window: every UAV is back by then.
DEADLINE_H = {1: Fraction(1, 4), 10: Fraction(1, 2), 50: Fraction(1)}
HORIZON_H = Fraction(3, 2)

# Wind-update conditions, fixed before labelling: the FS draw's cell C33 (index 15) and two
# blocks grown from it toward the grid centre; four compass directions; three strengths up to
# the rated wind resistance. Previous forecast calm, update received at dispatch.
COVERAGE = {'K1': (15,), 'K2': (10, 11, 14, 15), 'K3': (5, 6, 7, 9, 10, 11, 13, 14, 15)}
DIRECTIONS = {'E': (1, 0), 'N': (0, 1), 'W': (-1, 0), 'S': (0, -1)}
STRENGTHS_MS = (4, 8, 12)


def _number(value):
    number = float(value)
    if Fraction(str(number)) != Fraction(value):
        raise ValueError('value is not a short decimal')
    return number


def energy_fit():
    """Documented and modelled energy per km at 15 m/s, by take-off mass."""
    rows = {}
    for mass, km in DISTANCE_KM.items():
        documented = BATTERY_WH/km
        hover_kw = BATTERY_WH/Fraction(HOVER_MIN[mass], 60)/1000
        rows[mass] = dict(documented_wh_per_km=float(documented), model_wh_per_km=float(GAMMA*mass),
                          relative_error=float(GAMMA*mass/documented-1), gamma_exact=float(documented/mass),
                          cruise_power_kw=float(documented*AIRSPEED_KMH/1000), hover_power_kw=float(hover_kw))
    return rows


def nominal_mission(source_payload):
    """The FlyCart 30 mission before the update (received wind = previous, calm)."""
    p = deepcopy(source_payload)
    p['benchmark_id'] = 'PHY_FC30'
    for u in p['mission']['vehicles']:
        u.update(airspeed_kmh=_number(AIRSPEED_KMH), empty_mass_kg=MASS_WITH_BATTERIES_KG,
                 energy_coefficient_wh_per_kg_km=_number(GAMMA), battery_capacity_wh=_number(BATTERY_WH),
                 reserve_wh=_number(RESERVE_WH), payload_capacity_kg=PAYLOAD_KG)
        p['state']['fleet'][u['id']]['battery_wh'] = _number(BATTERY_WH)
    p['mission']['commodity_unit_mass_kg'] = UNIT_KG
    p['mission']['horizon_h'] = _number(HORIZON_H)
    p['operations'].update(service_duration_h=_number(SERVICE_H), service_energy_wh=SERVICE_WH,
                           preparation_duration_h=_number(PREPARATION_H))
    wind = p['wind']
    wind.update(time_knots_h=[0, _number(HORIZON_H)], speed_bound_kmh=_number(SPEED_BOUND_KMH), update_support=[])
    wind['previous']['values'] = [[[0, 0]] for _ in wind['cells']]
    wind['received'] = deepcopy(wind['previous'])
    return p


def with_deadlines(p, classes):
    q = deepcopy(p)
    for t in q['mission']['tasks']:
        t['deadline_h'] = _number(DEADLINE_H[classes[t['id']]])
    return q


def conditions():
    return [(c, d, s) for c in COVERAGE for d in DIRECTIONS for s in STRENGTHS_MS]


def condition_id(coverage, direction, strength):
    return f'PHY_FC30_{coverage}_{direction}_{strength}ms'


def apply_update(p, coverage, direction, strength):
    q = deepcopy(p)
    q['benchmark_id'] = condition_id(coverage, direction, strength)
    vector = [_number(strength*KMH*c) for c in DIRECTIONS[direction]]
    for c in COVERAGE[coverage]:
        q['wind']['received']['values'][c][0] = vector
    q['wind']['update_support'] = [[q['wind']['cells'][c]['id'], 0] for c in COVERAGE[coverage]]
    return Scenario(q).to_dict()


def diagnosis(payload):
    """Affected UAVs, whether Level 3 already releases the whole fleet, incumbent delays."""
    s = Scenario(payload)
    u0 = affected_uavs(s, diagnose_wind_update(s))['uavs']
    fleet = len(s.data['state']['fleet'])
    l3_participants = len(u0)+min(s.data['hierarchy']['helper_budget'], fleet-len(u0))
    calm = deepcopy(payload)
    calm['wind']['received'] = deepcopy(calm['wind']['previous'])
    calm['wind']['update_support'] = []
    before, after = delivery_times(Scenario(calm)), delivery_times(s)
    due = {t['id']: Fraction(str(t['deadline_h'])) for t in s.data['mission']['tasks']}
    late = sorted(i for i in after if after[i][0] > due[i])
    return dict(u0=u0, l3_equals_l4=l3_participants >= fleet,
                max_delay_s=float(max(after[i][1]-before[i][0] for i in after)*3600),
                incumbent_late_tasks=late,
                min_slack_after_s=float(min(due[i]-after[i][1] for i in after)*3600),
                previous_premise=previous_premise(s)['accepted'])
