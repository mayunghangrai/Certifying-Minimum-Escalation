"""Conservative mission witnesses checked without a numerical optimizer.

For stationary wind and uncoupled preparations, replacing flight durations by
upper bounds delays deliveries and increases every flight energy requirement.
All other constraints in the transfer compiler remain exact. A feasible proxy
therefore proves feasibility of the actual arbitrary-angle paths.
"""
from env.local_scope import affected_uavs, scope_family, patch_contains, scope_membership
from env.plan import coordinates
from env.scenario import Scenario, _thaw
from env.wind_dependency import diagnose_wind_update
from recovery.linear import rational
from recovery.local_search import digest
from recovery.transfers import build_transfer_problem
from env.units import time_field
from .binned import binned_guard, interval_provider
from .physics import stationary_duration, stationary_guard


def certify_witness(scenario, plan, reserves, level, digits=18, *, _diagnostic=None):
    try:
        v3 = scenario.data['schema_version'] == 'wind-benchmark-v3'
        reason = (binned_guard if v3 else stationary_guard)(scenario)
        if reason: return dict(accepted=False, reason=reason)
        plan = scenario.validate_candidate(plan)
        reserves = scenario.validate_reserve_paths(plan, reserves)
        diagnostic = _diagnostic or diagnose_wind_update(scenario)
        u0 = affected_uavs(scenario, diagnostic)['uavs']
        point = coordinates(scenario.data, plan)
        patches = [p for p in scope_family(scenario, level, u0) if patch_contains(scenario, point, p)]
        if not patches: return dict(accepted=False, reason='outside scope union')
        intervals = {}

        def duration(uid, path, time):
            key = uid, tuple(tuple(p) for p in path)
            if key not in intervals: intervals[key] = stationary_duration(scenario, uid, path, digits)
            return intervals[key][1]

        bounds = (dict(interval_provider=interval_provider(scenario, digits)) if v3
                  else dict(duration_provider=duration))
        compiled = build_transfer_problem(scenario, plan, reserves, patches[0].releases,
                                         exact=True, **bounds)
        values = tuple(rational(plan['routes'][uid]['deliveries' if a == 'x' else 'loads'][h])
                       for uid, h, a in compiled.columns)
        failed = next((r.label for r in compiled.problem.rows
                       if sum(a*x for a, x in zip(r.coefficients, values)) > r.bound), None)
        if failed: return dict(accepted=False, reason='conservative constraint: '+failed)
        membership = next(k for k in range(5) if scope_membership(scenario, point, k, u0))
        return dict(accepted=True, kind='binned_interval_witness_v3' if v3 else 'stationary_interval_witness_v1',
                    level=membership,
                    digits=digits, scenario_hash=scenario.content_hash(),
                    candidate_hash=digest(_thaw(plan)), reserve_hash=digest(_thaw(reserves)),
                    participants=list(patches[0].participants))
    except (ValueError, TypeError, KeyError, ArithmeticError, StopIteration) as error:
        return dict(accepted=False, reason=str(error))


def previous_premise(scenario, digits=18):
    p = scenario.to_dict()
    p['wind']['received'] = {**p['wind']['previous'],
                             time_field(p, 'issued_at'): p['mission'][time_field(p, 'epoch')]}
    p['wind']['update_support'] = []
    previous = Scenario(p)
    return certify_witness(previous, p['incumbent'], p['reserve_paths'], 0, digits)
