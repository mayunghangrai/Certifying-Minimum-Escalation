"""Certified helper-patch and assignment search around the full-slot kernel."""
from copy import deepcopy
from fractions import Fraction
import math
from time import perf_counter

from continuous.physics import depot_origin, stationary_guard
from env.local_scope import affected_uavs, scope_family
from env.wind_dependency import diagnose_wind_update
from recovery.linear import rational
from level2.search import search_sequence
from .cache import SharedContinuousCache


class _Limit(Exception):
    pass


def search_level3(scenario, *, max_seconds=60, max_nodes=100000, refinements=(2, 4),
                  digits=18, initial_bounds=(), max_operations=100000, max_rows=10000, cache=None):
    return _search_assignments(scenario, 3, max_seconds=max_seconds, max_nodes=max_nodes,
        refinements=refinements, digits=digits, initial_bounds=initial_bounds,
        max_operations=max_operations, max_rows=max_rows, cache=cache)


def _search_assignments(scenario, level, *, max_seconds=60, max_nodes=100000, refinements=(2, 4),
                        digits=18, initial_bounds=(), max_operations=100000, max_rows=10000, cache=None):
    if level not in (3, 4):
        raise ValueError('certified assignment search requires Level 3 or 4')
    if (isinstance(max_seconds, bool) or not math.isfinite(max_seconds) or max_seconds < 0
            or isinstance(max_nodes, bool) or not isinstance(max_nodes, int) or max_nodes < 0):
        raise ValueError(f'invalid Level-{level} budget')
    start = perf_counter()
    d = scenario.data
    affected = affected_uavs(scenario, diagnose_wind_update(scenario))['uavs']
    patches = scope_family(scenario, level, affected)
    tasks = sorted(d['incumbent']['assignment'])
    fleet = sorted(d['state']['fleet'])
    task_data = {t['id']: t for t in d['mission']['tasks']}
    vehicles = {u['id']: u for u in d['mission']['vehicles']}
    depot = d['mission']['depot_xy']
    # Bounds from a ground depot origin include preparation; an airborne origin
    # flies first from its observed position. Multi-sortie completion needs depot origins.
    ground = {uid: depot_origin(scenario, uid) for uid in fleet}
    start_at = {uid: depot if ground[uid] else d['state']['fleet'][uid]['position_xy'] for uid in fleet}
    entries = [dict(patch=p.to_dict(), tasks=tasks, root=0, status='UNRESOLVED',
                    nodes=[dict(prefix=[], kind='open', reason='shared search budget')]) for p in patches]
    report = dict(version=f'level{level}_certified_v1', scenario_hash=scenario.content_hash(),
                  domain='all_admissible_continuous_polylines', digits=digits, affected=affected,
                  unsupported=stationary_guard(scenario), lower_bounds=[], witness=None, status='UNRESOLVED',
                  budget=dict(max_seconds=max_seconds, max_nodes=max_nodes, refinements=list(refinements),
                              max_operations=max_operations, max_rows=max_rows),
                  effort=dict(assignment_nodes=0, sequence_nodes=0, assignment_prunes=0, sequences=0,
                              budget_exhausted=False, elapsed_s=0.))
    if level == 4:
        # The global domain is one original commitment-subtracted mask, not a
        # union of localized helper neighborhoods.
        report.update(scope_level=4, tree=entries[0])
    else:
        report['patches'] = entries
    effort = report['effort']
    if report['unsupported']:
        effort['elapsed_s'] = perf_counter()-start
        return report
    cache = cache or SharedContinuousCache(scenario, refinements=refinements, digits=digits,
                                          initial_bounds=initial_bounds)
    cache.check_scenario(scenario)
    if cache.refinements != tuple(refinements) or cache.digits != digits:
        raise ValueError('shared cache configuration differs from search')
    used_bounds = {}

    def check():
        if (perf_counter()-start >= max_seconds
                or effort['assignment_nodes']+effort['sequence_nodes'] >= max_nodes):
            effort['budget_exhausted'] = True
            raise _Limit()

    def lower(uid, task):
        check()
        q = cache.lower(uid, start_at[uid], task_data[task]['position_xy'])
        key = uid, tuple(q['start']), tuple(q['goal'])
        used_bounds[key] = deepcopy(q)
        return Fraction(q['lower'])

    def prune(prefix, patch):
        partial = dict(zip(tasks, prefix))
        if level == 4:
            # Each task constrains every assignment/sequence completion.
            # Capacity forces replenishment between delivering sorties;
            # all other visits/resources are optimistically ignored.
            for task in tasks:
                t = task_data[task]
                required = rational(t['mandatory'])-rational(d['state']['cumulative_delivered'][task])
                if required <= 0 or t['deadline_h'] is None:
                    continue
                owners = ([partial[task]] if task in partial else fleet
                          if task in patch.releases['A'] else [d['incumbent']['assignment'][task]])
                if owners == [None] or not all(ground[uid] for uid in owners):
                    continue
                candidates = []
                for uid in owners:
                    capacity = rational(vehicles[uid]['payload_capacity_kg'])/rational(d['mission']['commodity_unit_mass_kg'])
                    sorties = math.ceil(required/capacity)
                    outbound = lower(uid, task)
                    returning = Fraction(0)
                    if sorties > 1:
                        check()
                        q = cache.lower(uid, t['position_xy'], depot)
                        used_bounds[uid, tuple(q['start']), tuple(q['goal'])] = deepcopy(q)
                        returning = Fraction(q['lower'])
                    earliest = (rational(d['mission']['epoch_h'])
                        + sorties*(rational(d['operations']['preparation_duration_h'])
                                   +rational(d['operations']['service_duration_h'])+outbound)
                        + (sorties-1)*returning)
                    candidates.append(dict(uav=uid, sorties=sorties, earliest=str(earliest)))
                earliest = min(Fraction(c['earliest']) for c in candidates)
                if earliest > rational(t['deadline_h']):
                    return dict(kind='assignment_completion_deadline_v1', task=task, candidates=candidates,
                                earliest=str(earliest), limit=str(rational(t['deadline_h'])))
        for task, owner in partial.items():
            t = task_data[task]
            required, cumulative = rational(t['mandatory']), rational(d['state']['cumulative_delivered'][task])
            if owner is None and required > cumulative:
                return dict(kind='assignment_mandatory_v1', task=task,
                            mandatory=str(required), cumulative=str(cumulative))
            if owner is not None:
                route = d['incumbent']['routes'][owner]
                if (all(f'{owner}:{h}' not in patch.releases['S'] for h in range(1, len(route['stops'])+1))
                        and task not in route['stops']):
                    return dict(kind='assignment_fixed_owner_v1', task=task, uav=owner)
            for uid, route in sorted(d['incumbent']['routes'].items()):
                for h, site in enumerate(route['stops'], 1):
                    if site == task and f'{uid}:{h}' not in patch.releases['S'] and owner != uid:
                        return dict(kind='assignment_commitment_v1', task=task, uav=uid, slot=h)
            if owner is not None and required > cumulative and t['deadline_h'] is not None:
                earliest = (rational(d['mission']['epoch_h'])
                            +(rational(d['operations']['preparation_duration_h']) if ground[owner] else 0)
                            +rational(d['operations']['service_duration_h'])+lower(owner, task))
                if earliest > rational(t['deadline_h']):
                    return dict(kind='assignment_deadline_v1', task=task, uav=owner,
                                earliest=str(earliest), limit=str(rational(t['deadline_h'])))
        for uid in fleet:
            assigned = sorted(t for t, u in partial.items() if u == uid)
            available = vehicles[uid]['slot_bound']-1
            if len(assigned) > available:
                return dict(kind='assignment_slots_v1', uav=uid, tasks=assigned, available_slots=available)
        return None

    try:
        for patch, entry in zip(patches, entries):
            stack = [0]
            while stack:
                check()
                index = stack.pop()
                node = entry['nodes'][index]
                prefix = node['prefix']
                effort['assignment_nodes'] += 1
                proof = prune(prefix, patch)
                if proof:
                    node.pop('reason', None)
                    node.update(kind='assignment_prune', proof=proof)
                    effort['assignment_prunes'] += 1
                    continue
                if len(prefix) == len(tasks):
                    check()
                    assignment = dict(zip(tasks, prefix))
                    inner = search_sequence(scenario, assignment, patch, scope_level=level, oracle=cache.view(),
                        max_seconds=max(0, max_seconds-(perf_counter()-start)),
                        max_nodes=max(0, max_nodes-effort['assignment_nodes']-effort['sequence_nodes']),
                        refinements=refinements, digits=digits, max_operations=max_operations, max_rows=max_rows)
                    node.pop('reason', None)
                    node.update(kind='sequence', assignment=assignment, proof=inner)
                    effort['sequences'] += 1
                    effort['sequence_nodes'] += inner['effort']['visited']
                    if inner['status'] == 'WITNESS':
                        report['witness'] = deepcopy(inner['witness'])
                        break
                    # A surviving geometry/quantity gap is explicitly attached
                    # rather than being silently counted as an excluded branch.
                    continue
                task = tasks[len(prefix)]
                choices = [None, *fleet] if task in patch.releases['A'] else [d['incumbent']['assignment'][task]]
                children = []
                for owner in choices:
                    children.append(len(entry['nodes']))
                    entry['nodes'].append(dict(prefix=[*prefix, owner], kind='open', reason='shared search budget'))
                node.pop('reason', None)
                node.update(kind='branch', children=children)
                # Search order is heuristic; the full child partition is stored.
                ranked = sorted(children, key=lambda j: (entry['nodes'][j]['prefix'][-1] is None,
                    entry['nodes'][j]['prefix'][-1] != d['incumbent']['assignment'][task],
                    str(entry['nodes'][j]['prefix'][-1])))
                stack.extend(reversed(ranked))
            if report['witness']:
                break
    except _Limit:
        pass
    for entry in entries:
        nodes = entry['nodes']
        if any(n['kind'] == 'sequence' and n['proof']['status'] == 'WITNESS' for n in nodes):
            entry['status'] = 'WITNESS'
        elif (not any(n['kind'] == 'open' for n in nodes)
              and all(n['proof']['status'] == 'EMPTY' for n in nodes if n['kind'] == 'sequence')):
            entry['status'] = 'EMPTY'
    report['status'] = ('WITNESS' if report['witness'] else 'EMPTY'
                        if all(p['status'] == 'EMPTY' for p in entries) else 'UNRESOLVED')
    report['lower_bounds'] = [deepcopy(q) for _, q in sorted(used_bounds.items())]
    effort['shared_cache'] = deepcopy(cache.effort)
    effort['elapsed_s'] = perf_counter()-start
    return report
