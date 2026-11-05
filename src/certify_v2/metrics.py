"""Decisions a plan changes against the incumbent (comparison protocol, Q1).

``env.local_scope.change_metrics`` compares coordinates slot by slot, so one
insertion counts every later slot as changed. These counts follow the decisions:

- uavs_changed: UAVs whose stops, paths or quantities differ, and how many of them
  lie outside the affected fleet U0;
- tasks_reassigned: remaining tasks served by another UAV;
- sequence_edits: tasks kept by their UAV whose predecessor (the previous task on
  that UAV's route, or the start) changed;
- legs_rerouted: legs between the same two stops of the same UAV flown on a new
  path; legs_new: legs between stops the UAV did not fly consecutively before;
- deliveries_changed: tasks whose delivered amount or deliverer changed;
- depot_stops_added: intermediate depot stops added (negative when removed).
"""
from fractions import Fraction

from env.geometry import canonical_path
from env.local_scope import change_metrics
from env.plan import active_count
from recovery.linear import rational


def _routes(plan):
    out = {}
    for uid, route in plan['routes'].items():
        n = active_count(route)
        out[uid] = dict(stops=list(route['stops'][:n]), paths=[canonical_path(p) for p in route['paths'][:n]],
                        x=[rational(v) for v in route['deliveries'][:n+1]])
    return out


def _legs(route):
    legs, prev = {}, 'START'
    for stop, path in zip(route['stops'], route['paths']):
        legs.setdefault((prev, stop), set()).add(path)
        prev = stop
    return legs


def _predecessors(route):
    tasks = [s for s in route['stops'] if s != 'DEPOT']
    return {t: (tasks[i-1] if i else 'START') for i, t in enumerate(tasks)}


def _delivered(route, uid):
    out = {}
    for h, stop in enumerate(route['stops'], 1):
        if stop != 'DEPOT':
            out[stop] = out.get(stop, Fraction(0))+route['x'][h]
    return {t: (uid, v) for t, v in out.items()}


def decisions(scenario, plan, u0, *, exact_quantities=None):
    d = scenario.data
    old, new = _routes(d['incumbent']), _routes(plan)
    if exact_quantities:
        for key, value in exact_quantities.items():
            uid, h, a = key.split(':')
            if a == 'x':
                new[uid]['x'][int(h)] = Fraction(value)
    base = change_metrics(scenario, plan, u0, exact_quantities=exact_quantities)
    reassigned = sum(1 for t, o in plan['assignment'].items() if d['incumbent']['assignment'].get(t) != o)
    edits = rerouted = fresh = 0
    delivered_old, delivered_new = {}, {}
    for uid in sorted(new):
        a, b = old[uid], new[uid]
        before, after = _predecessors(a), _predecessors(b)
        edits += sum(1 for t, p in after.items() if t in before and before[t] != p
                     and d['incumbent']['assignment'].get(t) == uid)
        old_legs, new_legs = _legs(a), _legs(b)
        for key, paths in new_legs.items():
            if key in old_legs:
                rerouted += len(paths-old_legs[key])
            else:
                fresh += len(paths)
        delivered_old.update(_delivered(a, uid))
        delivered_new.update(_delivered(b, uid))
    deliveries = sum(1 for t in set(delivered_old) | set(delivered_new)
                     if delivered_old.get(t) != delivered_new.get(t))
    depots = sum(sum(1 for s in r['stops'][:-1] if s == 'DEPOT') for r in new.values()) - \
        sum(sum(1 for s in r['stops'][:-1] if s == 'DEPOT') for r in old.values())
    return dict(uavs_changed=base['changed_uav_count'], uavs_changed_outside_u0=base['outside_changed'],
                tasks_reassigned=reassigned, sequence_edits=edits, legs_rerouted=rerouted, legs_new=fresh,
                deliveries_changed=deliveries, depot_stops_added=depots,
                coordinates_changed={a: len(v) for a, v in base['changed_coordinates'].items()})


def plan_decisions(scenario, witness, u0):
    exact = {':'.join(map(str, c)): v for c, v in zip(witness['columns'], witness['values'])}
    return decisions(scenario, witness['plan'], u0, exact_quantities=exact)
