"""Independent proof-tree replay; no producer or numerical solver imports.

The partition is reconstructed from the model's raw slot coordinates. Geometry
certificates and rational LP certificates are checked by their existing trusted
arithmetic primitives. Search ordering, pruning decisions and LP proposals are
never reused from the Level-2 implementation.
"""
from collections import Counter
from fractions import Fraction
import hashlib
import json

from env.geometry import canonical_path
from env.local_scope import affected_uavs, scope_family
from env.wind_dependency import diagnose_wind_update
from continuous.oracle import verify_query
from continuous.physics import depot_origin, stationary_guard, stationary_duration
from recovery.linear import rational, verify_exclusion
from recovery.transfers import build_transfer_problem, BranchRejected


class InvalidProof(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise InvalidProof(reason)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def _domain(scenario, affected, assignment=None, patch=None):
    data = scenario.data
    releases = (scope_family(scenario, 2, affected)[0] if patch is None else patch).releases
    assignment = data['incumbent']['assignment'] if assignment is None else assignment
    fleet = {u['id']: u for u in data['mission']['vehicles']}
    slots = [(uid, h) for uid in sorted(fleet) for h in range(1, fleet[uid]['slot_bound']+1)]
    assigned = {uid: sorted(i for i, u in assignment.items() if u == uid)
                for uid in fleet}
    choices = [(None, 'DEPOT', *assigned[uid]) if f'{uid}:{h}' in releases['S']
               else (data['incumbent']['routes'][uid]['stops'][h-1],) for uid, h in slots]
    return slots, choices, releases, assigned


def _structural_reasons(scenario, prefix, slots, releases, assigned):
    """Necessary domain conditions, derived directly from slot meanings."""
    d = scenario.data
    fleet = {u['id']: u for u in d['mission']['vehicles']}
    tasks = {t['id']: tuple(t['position_xy']) for t in d['mission']['tasks']}
    depot = tuple(d['mission']['depot_xy'])
    selected = {uid: [] for uid in fleet}
    for (uid, _), stop in zip(slots, prefix):
        selected[uid].append(stop)
    reasons = set()
    for uid, stops in selected.items():
        if not stops:
            continue
        bound = fleet[uid]['slot_bound']
        old = d['incumbent']['routes'][uid]
        initial = d['state']['fleet'][uid]
        if any(stop not in (None, 'DEPOT') and stop not in assigned[uid] for stop in stops):
            reasons.add('assignment_visit_owner')
        n = stops.index(None) if None in stops else len(stops)
        closed = None in stops or len(stops) == bound
        if any(s is not None for s in stops[n:]):
            reasons.add('padding')
        if closed and n and stops[n-1] != 'DEPOT':
            reasons.add('termination')
        if not n and (initial['mode'] != 'idle' or tuple(initial['position_xy']) != depot):
            reasons.add('idle_origin')
        missing = set(assigned[uid])-set(stops[:n])
        if missing and (closed or len(missing)+1 > bound-len(stops)):
            reasons.add('assignment_coverage')
        if initial['mode'] == 'servicing' and (not n or stops[0] == 'DEPOT'
                or tasks.get(stops[0]) != tuple(initial['position_xy'])):
            reasons.add('pending_service')
        previous = tuple(initial['position_xy'])
        for h, stop in enumerate(stops, 1):
            active = h <= n
            point = depot if stop in (None, 'DEPOT') else tasks[stop]
            if f'{uid}:{h}' not in releases['P']:
                path = canonical_path(old['paths'][h-1])
                if ((not active and path != (depot,))
                        or (active and (path[0] != previous or path[-1] != point))):
                    reasons.add('fixed_path_endpoints')
            if active:
                previous = point
        origin = tuple(initial['position_xy']) == depot and initial['mode'] in ('idle', 'preparing')
        for h in range(len(stops)+1):
            stop = None if h == 0 else stops[h-1]
            for a, values in (('x', old['deliveries']), ('y', old['loads'])):
                if f'{uid}:{h}:{a}' in releases['L'] or values[h] == 0:
                    continue
                if a == 'x':
                    forbidden = h == 0 or h > n or stop == 'DEPOT'
                else:
                    forbidden = ((h == 0 and not origin) or (h > 0 and (h > n or stop != 'DEPOT'))
                                 or (closed and h == n) or h == bound)
                if forbidden:
                    reasons.add('fixed_transfer_eligibility')
    return reasons


def _leg_table(scenario, queries, digits):
    _require(isinstance(queries, list), 'invalid leg bound table')
    table = {}
    for q in queries:
        _require(verify_query(scenario, q, digits), 'invalid continuous leg certificate')
        key = (q['uid'], tuple(q['start']), tuple(q['goal']))
        _require(key not in table, 'duplicate continuous leg certificate key')
        table[key] = Fraction(q['lower'])
    return table


def _resource_violations(scenario, prefix, slots, releases, assigned, table, digits):
    """Reconstruct optimistic empty-mass mission inequalities independently."""
    d = scenario.data
    fleet = {u['id']: u for u in d['mission']['vehicles']}
    tasks = {t['id']: t for t in d['mission']['tasks']}
    depot = tuple(d['mission']['depot_xy'])
    op, mission = d['operations'], d['mission']
    epoch, horizon = rational(mission['epoch_h']), rational(mission['horizon_h'])
    prep, service, service_energy = map(rational, (op['preparation_duration_h'],
                                     op['service_duration_h'], op['service_energy_wh']))
    selected = {uid: [] for uid in fleet}
    for (uid, _), stop in zip(slots, prefix):
        selected[uid].append(stop)
    violations = []
    for uid in sorted(fleet):
        u, initial = fleet[uid], d['state']['fleet'][uid]
        # Only a ground depot origin prepares and recharges before its first flight.
        origin = depot_origin(scenario, uid)
        time, battery, seen, n = epoch, rational(initial['battery_wh']), set(), 0
        previous = depot if origin else tuple(initial['position_xy'])
        capacity, reserve = rational(u['battery_capacity_wh']), rational(u['reserve_wh'])
        empty_cost = rational(u['empty_mass_kg'])*rational(u['energy_coefficient_wh_per_kg_km'])*rational(u['airspeed_kmh'])

        def lower(start, goal):
            return table.get((uid, tuple(start), tuple(goal)), Fraction(0))

        def record(rule, value, limit, slot, task):
            if value < limit if rule in ('battery', 'reserve') else value > limit:
                violations.append(dict(kind='prefix_resource_v1', uav=uid, rule=rule,
                                       value=str(value), limit=str(limit), slot=slot, task=task))

        previous_site = 'DEPOT' if origin else 'ORIGIN'
        for h, stop in enumerate(selected[uid], 1):
            if stop is None:
                break
            n += 1
            if previous_site == 'DEPOT':
                time += prep
                # The depot operation recharges before the first/next sortie.
                battery = capacity
            point = depot if stop == 'DEPOT' else tuple(tasks[stop]['position_xy'])
            dt = (stationary_duration(scenario, uid, d['incumbent']['routes'][uid]['paths'][h-1], digits)[0]
                  if f'{uid}:{h}' not in releases['P'] else lower(previous, point))
            time += dt
            battery -= empty_cost*dt
            if stop != 'DEPOT':
                seen.add(stop)
                time += service
                battery -= service_energy
                back = lower(point, depot)
                record('reserve', battery, reserve+empty_cost*back, h, stop)
                record('return_horizon', time+back, horizon, h, stop)
            else:
                record('reserve', battery, reserve, h, stop)
            record('horizon', time, horizon, h, stop)
            record('battery', battery, Fraction(0), h, stop)
            if stop == 'DEPOT':
                battery = capacity
            previous, previous_site = point, stop
        for site in assigned[uid]:
            task = tasks[site]
            if (site in seen or task['mandatory'] <= d['state']['cumulative_delivered'][site]
                    or task['deadline_h'] is None):
                continue
            earliest = time+(prep if previous_site == 'DEPOT' else 0)
            earliest += lower(previous, task['position_xy'])+service
            record('unvisited_deadline', earliest, rational(task['deadline_h']), n+1, site)
    return violations


def _match_plan(scenario, plan, prefix, slots, assignment=None):
    _require(len(prefix) == len(slots), 'quantity or witness leaf has incomplete skeleton')
    assignment = scenario.to_dict()['incumbent']['assignment'] if assignment is None else assignment
    _require(plan['assignment'] == assignment, 'quantity plan changes supplied assignment')
    _require([plan['routes'][uid]['stops'][h-1] for uid, h in slots] == prefix,
             'quantity plan differs from proof-tree skeleton')


def _quantity_exclusion(scenario, node, prefix, slots, releases, table, assignment=None):
    plan, reserves, proof = node['plan'], node['reserve_paths'], node['proof']
    _match_plan(scenario, plan, prefix, slots, assignment)
    _require(proof['scenario_hash'] == scenario.content_hash()
             and proof['candidate_hash'] == _digest(plan)
             and proof['reserve_hash'] == _digest(reserves), 'quantity proof identity mismatch')
    kind = proof['kind']
    _require(kind in ('quantity_farkas_v1', 'quantity_ground_rejection_v1'), 'unknown quantity exclusion')

    def duration(uid, path, time):
        return table.get((uid, tuple(path[0]), tuple(path[-1])), Fraction(0))

    try:
        compiled = build_transfer_problem(scenario, plan, reserves, releases,
                                          exact=True, duration_provider=duration)
    except BranchRejected as error:
        _require(kind == 'quantity_ground_rejection_v1' and error.exact
                 and proof['reason'] == str(error), 'ground rejection proof mismatch')
        return
    _require(kind == 'quantity_farkas_v1' and verify_exclusion(compiled.problem, proof['certificate']),
             'invalid rational Farkas exclusion')


def _quantity_witness(scenario, witness, prefix, slots, releases, digits, assignment=None):
    w = witness
    _require(w['kind'] == 'quantity_primal_v1' and w['scenario_hash'] == scenario.content_hash()
             and type(w['digits']) is int and w['digits'] == digits, 'quantity witness identity mismatch')
    plan, reserves = w['plan'], w['reserve_paths']
    _match_plan(scenario, plan, prefix, slots, assignment)
    _require(w['candidate_hash'] == _digest(plan) and w['reserve_hash'] == _digest(reserves),
             'quantity witness hashes mismatch')
    compiled = build_transfer_problem(scenario, plan, reserves, releases, exact=True,
        duration_provider=lambda uid, path, time: stationary_duration(scenario, uid, path, digits)[1])
    _require(w['columns'] == [list(c) for c in compiled.columns], 'quantity witness columns mismatch')
    _require(isinstance(w['values'], list) and all(isinstance(v, str) for v in w['values']),
             'quantity witness requires rational string values')
    values = tuple(Fraction(v) for v in w['values'])
    _require(compiled.problem.accepts(values), 'quantity witness violates conservative exact constraints')
    _require(all(plan['routes'][uid]['deliveries' if a == 'x' else 'loads'][h] == float(value)
                 for (uid, h, a), value in zip(compiled.columns, values)), 'quantity witness projection mismatch')


def _replay(scenario, report, assignment=None, patch=None, scope_level=3):
    """Return validity and independently established coverage/conclusion.

    ``covered`` means that every terminal region has been adjudicated, with no
    open region. An UNRESOLVED report can still be valid replayable evidence.
    """
    try:
        explicit = assignment is not None
        _require(report['version'] == ('sequence_exhaustive_v1' if explicit else 'level2_exhaustive_v1'),
                 'unsupported proof version')
        _require(report['scenario_hash'] == scenario.content_hash(), 'scenario identity mismatch')
        _require(report['domain'] == 'all_admissible_continuous_polylines', 'path domain mismatch')
        digits = report['digits']
        _require(type(digits) is int and 1 <= digits <= 60, 'invalid enclosure precision')
        status = report['status']
        _require(status in ('WITNESS', 'EMPTY', 'UNRESOLVED'), 'unknown report status')
        reason = stationary_guard(scenario)
        _require(report['unsupported'] == reason, 'unsupported model declaration mismatch')
        if reason:
            _require(status == 'UNRESOLVED' and report['witness'] is None
                     and not report['leg_bounds'], 'unsupported model claims a certificate')
        affected = affected_uavs(scenario, diagnose_wind_update(scenario))['uavs']
        _require(report['affected'] == affected, 'affected fleet mask mismatch')
        if explicit:
            _require(type(scope_level) is int and scope_level in (3, 4), 'invalid explicit sequence scope level')
            recorded_level = report.get('scope_level', 3)
            _require(type(recorded_level) is int and recorded_level == scope_level,
                     'sequence scope level mismatch')
            patch_value = patch.to_dict() if hasattr(patch, 'to_dict') else patch
            authorized = next((p for p in scope_family(scenario, scope_level, affected)
                               if p.to_dict() == patch_value), None)
            _require(authorized is not None, 'sequence patch is not an original permitted scope patch')
            _require(report['patch'] == patch_value, 'sequence release mask mismatch')
            old = scenario.data['incumbent']['assignment']
            fleet = set(scenario.data['state']['fleet'])
            _require(isinstance(assignment, dict) and set(assignment) == set(old)
                     and all(u is None or u in fleet for u in assignment.values()),
                     'invalid supplied assignment')
            _require(report['assignment'] == assignment, 'sequence assignment mismatch')
            _require(all(assignment[i] == old[i] for i in old if i not in authorized.releases['A']),
                     'sequence assignment changes a fixed original coordinate')
            patch = authorized
        slots, choices, releases, assigned = _domain(scenario, affected, assignment, patch)
        table = _leg_table(scenario, report['leg_bounds'], digits)
        nodes = report['nodes']
        _require(isinstance(nodes, list) and nodes and report['root'] == 0,
                 'missing proof root')
        _require(nodes[0]['prefix'] == [], 'root must cover the entire slot domain')
        visited, prefixes, counts, witnesses = set(), set(), Counter(), []
        stack = [0]
        while stack:
            index = stack.pop()
            _require(type(index) is int and 0 <= index < len(nodes), 'invalid child identifier')
            _require(index not in visited, 'shared node or cycle')
            visited.add(index)
            node = nodes[index]
            prefix, kind = node['prefix'], node['kind']
            _require(isinstance(prefix, list) and len(prefix) <= len(slots), 'invalid prefix dimension')
            _require(all(s in choices[j] for j, s in enumerate(prefix)), 'prefix changes fixed assignment or slot')
            key = tuple(prefix)
            _require(key not in prefixes, 'duplicated prefix')
            prefixes.add(key)
            if kind == 'branch':
                _require(len(prefix) < len(slots), 'branch exceeds route slot domain')
                children = node['children']
                _require(isinstance(children, list) and len(children) == len(choices[len(prefix)]),
                         'branch omits or duplicates a raw slot choice')
                for child, stop in zip(children, choices[len(prefix)]):
                    _require(type(child) is int and 0 <= child < len(nodes), 'invalid child identifier')
                    _require(nodes[child]['prefix'] == [*prefix, stop], 'branch choice partition mismatch')
                stack.extend(reversed(children))
            else:
                _require(not node.get('children'), 'terminal region has children')
                counts[kind] += 1
                if kind == 'structural':
                    _require(node['reason'] in _structural_reasons(scenario, prefix, slots, releases, assigned),
                             'unproved structural exclusion')
                elif kind == 'open':
                    pass
                elif kind == 'resource':
                    _require(not reason, 'unsupported model resource proof')
                    _require(node['proof'] in _resource_violations(scenario, prefix, slots, releases,
                              assigned, table, digits), 'unproved mission-resource exclusion')
                elif kind == 'quantity':
                    _require(not reason, 'unsupported model quantity proof')
                    _quantity_exclusion(scenario, node, prefix, slots, releases, table, assignment)
                elif kind == 'witness':
                    _require(not reason, 'unsupported model witness')
                    _quantity_witness(scenario, node['witness'], prefix, slots, releases, digits, assignment)
                    witnesses.append(node['witness'])
                else:
                    raise InvalidProof('unknown terminal proof kind')
        _require(len(visited) == len(nodes), 'unreachable proof nodes')
        covered = counts['open'] == 0
        if witnesses:
            _require(len(witnesses) == 1 and report['witness'] == witnesses[0], 'top-level witness differs from tree')
        else:
            _require(report['witness'] is None, 'unverified top-level witness')
        derived = 'WITNESS' if witnesses else 'EMPTY' if covered else 'UNRESOLVED'
        _require(status == derived, 'report conclusion lacks terminal coverage')
        return dict(valid=True, status=derived, covered=covered, nodes=len(visited),
                    leaf_counts=dict(counts), reason=None)
    except (ValueError, TypeError, KeyError, ArithmeticError, IndexError, StopIteration) as error:
        return dict(valid=False, status='INVALID', covered=False, nodes=0,
                    leaf_counts={}, reason=str(error))


def replay_tree(scenario, report):
    """Replay the legacy fixed-incumbent Level-2 domain."""
    return _replay(scenario, report)


def replay_sequence(scenario, report, assignment, patch, *, scope_level=3):
    """Replay an attached sequence proof against the unchanged original epoch.

    The candidate assignment determines visit symbols; the requested original
    scope patch alone determines released coordinates. Neither rebases commitments.
    """
    return _replay(scenario, report, assignment, patch, scope_level)


def verify_sequence(scenario, report, assignment, patch, *, scope_level=3):
    return replay_sequence(scenario, report, assignment, patch, scope_level=scope_level)['valid']


def verify_tree(scenario, report):
    return replay_tree(scenario, report)['valid']
