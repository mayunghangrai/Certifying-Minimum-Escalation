"""A8 admission (design 7.3), decided by the exact checker alone.

The test runs at the strongest update a study runs (decided 6 November): r = 0.8
for MS (r in {0.4, 0.6, 0.8}) and r = 0.6 for SC (its only strength). At
r = 0.6 the pilot fill left 56 of 72 generous-margin MS slots empty.

Level 0 changes nothing, so "the update breaks the plan" means the unchanged
incumbent, flown under F1, misses a deadline, battery or reserve limit or the
horizon. Two exact passes decide it:

- conservative (upper times and energy): `certify_witness` at Level 0. If it
  accepts, every limit is met: the draw is rejected;
- optimistic (lower times and energy): `certain_violations`. Any violation
  holds for the true flight: the mission is admitted;
- otherwise an interval straddles a limit: the draw is rejected and logged.

Payload and stock do not depend on wind, so they cannot change between F0 and F1.
"""
import math
from fractions import Fraction as F

from continuous.binned import binned_guard, binned_interval
from continuous.validation import certify_witness, previous_premise
from env.local_scope import affected_uavs
from env.plan import active_count
from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update
from .update import apply_magnitude

MS_ADMISSION_R = 0.8
SC_ADMISSION_R = 0.6


def _r(value):
    return F(str(value))


def certain_violations(scenario):
    """Limits the fixed incumbent breaks for every flight consistent with the enclosures.

    Times follow the lower chain. A flight departing in [lo, hi] lasts at least
    max(0, arrival_lo - hi), which bounds its energy from below.
    Requires idle depot origins (t_u = 0 admission).
    """
    d = scenario.data
    if binned_guard(scenario):
        raise ValueError(binned_guard(scenario))
    if any(s['mode'] != 'idle' for s in d['state']['fleet'].values()):
        raise ValueError('admission check expects idle depot origins')
    service, prep = _r(d['operations']['service_duration_s']), _r(d['operations']['preparation_duration_s'])
    service_energy = _r(d['operations']['service_energy_wh'])
    horizon, unit = _r(d['mission']['horizon_s']), _r(d['mission']['commodity_unit_mass_kg'])
    tasks = {t['id']: t for t in d['mission']['tasks']}
    violations = []
    for u in d['mission']['vehicles']:
        uid = u['id']
        route = d['incumbent']['routes'][uid]
        n = active_count(route)
        usable = _r(u['battery_capacity_wh']) - _r(u['reserve_wh'])

        def power(load):
            return _r(u['power_a_w']) + _r(u['power_b_w_per_kg'])*(_r(u['empty_mass_kg']) + unit*load)
        lo = hi = _r(d['mission']['epoch_s']) + (prep if n else 0)
        load, used = _r(route['loads'][0]), F(0)
        for h in range(1, n + 1):
            stop = route['stops'][h-1]
            alo, ahi = binned_interval(scenario, uid, route['paths'][h-1], lo, hi)
            if alo is None:
                violations.append(f'horizon:{uid}:{h}:flight')
                break
            if ahi is None:         # no upper time: later lower energy bounds would be unsound
                break
            used += power(load)*max(F(0), alo - hi)/3600
            lo, hi = alo, ahi
            if stop == 'DEPOT':
                if used > usable:
                    violations.append(f'depot_arrival_reserve:{uid}:{h}')
                if h < n:
                    lo, hi = lo + prep, hi + prep
                    used, load = F(0), _r(route['loads'][h])
                    if lo > horizon:
                        violations.append(f'horizon:{uid}:{h}:ground')
                        break
                continue
            lo, hi = lo + service, hi + service
            deadline = tasks[stop]['deadline_s']
            if deadline is not None and lo > _r(deadline):
                violations.append(f'deadline:{uid}:{h}:{stop}')
            used += service_energy + power(load)*service/3600
            load -= _r(route['deliveries'][h])
            back = d['reserve_paths'][uid].get(str(h))
            if back is not None:
                rlo, _ = binned_interval(scenario, uid, back, lo, hi)
                if rlo is None:
                    violations.append(f'reserve_horizon:{uid}:{h}')
                elif used + power(load)*max(F(0), rlo - hi)/3600 > usable:
                    violations.append(f'reserve:{uid}:{h}')
    return violations


def admit(mission, block, r):
    """Decide one draw at strength r, t_u = 0. Returns a loggable dict."""
    payload = mission.to_dict()
    m = len(payload['mission']['vehicles'])
    premise = previous_premise(mission)
    if not premise['accepted']:
        return dict(admitted=False, reason='previous premise not certified: ' + premise['reason'])
    updated = Scenario(apply_magnitude(payload, block, r))
    u0 = affected_uavs(updated, diagnose_wind_update(updated))['uavs']
    result = dict(u0=u0)
    if not 1 <= len(u0) <= math.ceil(m/3):
        return dict(result, admitted=False, reason=f'|U0| = {len(u0)} outside [1, {math.ceil(m/3)}]')
    witness = certify_witness(updated, payload['incumbent'], payload['reserve_paths'], 0)
    if witness['accepted']:
        return dict(result, admitted=False, reason='level 0 certified feasible: update does not break the plan')
    violations = certain_violations(updated)
    if violations:
        return dict(result, admitted=True, reason='level 0 certified infeasible', violations=violations)
    return dict(result, admitted=False, reason='straddle: enclosure crosses a limit (logged)',
                conservative_failure=witness['reason'])
