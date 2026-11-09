"""Safe prefix exclusions over the unrestricted continuous path domain.

Zero payload and independent depot resets deliberately relax resource use.
Deadline exclusions refer only to mandatory tasks with no visit in the prefix.
A ground depot origin prepares and recharges before its first flight; an
airborne origin starts from its observed position, battery and epoch.
"""
from fractions import Fraction

from continuous.physics import depot_origin, stationary_duration
from recovery.linear import rational


def prefix_exclusion(scenario, domain, prefix, lower_durations, *, digits=18):
    d = scenario.data
    depot = tuple(d['mission']['depot_xy'])
    tasks = {t['id']: t for t in d['mission']['tasks']}
    vehicles = {v['id']: v for v in d['mission']['vehicles']}
    op = d['operations']
    horizon = rational(d['mission']['horizon_h'])
    selected = {uid: [] for uid in vehicles}
    for (uid, h), site in zip(domain.slots, prefix):
        selected[uid].append(site)

    def lower(uid, a, b):
        return Fraction(lower_durations.get((uid, tuple(a), tuple(b)), 0))

    def proof(uid, rule, value, limit, h, site=None):
        return dict(kind='prefix_resource_v1', uav=uid, rule=rule,
                    value=str(value), limit=str(limit), slot=h, task=site)

    for uid in sorted(vehicles):
        v, state = vehicles[uid], d['state']['fleet'][uid]
        time = rational(d['mission']['epoch_h'])
        battery = rational(state['battery_wh'])
        reserve = rational(v['reserve_wh'])
        coefficient = rational(v['empty_mass_kg'])*rational(v['energy_coefficient_wh_per_kg_km'])*rational(v['airspeed_kmh'])
        # An airborne origin flies first from its observed state, without preparation or recharge.
        origin = depot_origin(scenario, uid)
        previous = depot if origin else tuple(state['position_xy'])
        previous_site, seen, n = 'DEPOT' if origin else 'ORIGIN', set(), 0
        for h, site in enumerate(selected[uid], 1):
            if site is None:
                break
            if previous_site == 'DEPOT':
                time += rational(op['preparation_duration_h'])
                battery = rational(v['battery_capacity_wh'])
            goal = depot if site == 'DEPOT' else tuple(tasks[site]['position_xy'])
            if f'{uid}:{h}' not in domain.patch.releases['P']:
                dt = stationary_duration(scenario, uid, d['incumbent']['routes'][uid]['paths'][h-1], digits)[0]
            else:
                dt = lower(uid, previous, goal)
            time += dt
            battery -= coefficient*dt
            if site != 'DEPOT':
                seen.add(site)
                time += rational(op['service_duration_h'])
                battery -= rational(op['service_energy_wh'])
            if time > horizon:
                return proof(uid, 'horizon', time, horizon, h, site)
            if battery < 0:
                return proof(uid, 'battery', battery, Fraction(0), h, site)
            return_time = lower(uid, goal, depot) if site != 'DEPOT' else Fraction(0)
            needed = reserve+coefficient*return_time
            if battery < needed:
                return proof(uid, 'reserve', battery, needed, h, site)
            if site != 'DEPOT' and time+return_time > horizon:
                return proof(uid, 'return_horizon', time+return_time, horizon, h, site)
            if site == 'DEPOT':
                battery = rational(v['battery_capacity_wh'])
            previous, previous_site, n = goal, site, h
        # A later visit may serve a previously visited task; never infer x > 0
        # merely from the presence of a visit in a quantity-released scope.
        for site in domain.assigned[uid]:
            task = tasks[site]
            if site in seen or task['deadline_h'] is None:
                continue
            if rational(task['mandatory']) <= rational(d['state']['cumulative_delivered'][site]):
                continue
            earliest = time+lower(uid, previous, task['position_xy'])+rational(op['service_duration_h'])
            if previous_site == 'DEPOT':
                earliest += rational(op['preparation_duration_h'])
            deadline = rational(task['deadline_h'])
            if earliest > deadline:
                return proof(uid, 'unvisited_deadline', earliest, deadline, n+1, site)
    return None
