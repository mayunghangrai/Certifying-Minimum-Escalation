"""Independent rational replay of Level-3 helper and assignment coverage.

No producer, branch ordering, bound proposal, cache, or numerical solver is
imported. The raw assignment alphabet and each exclusion are reconstructed
from the original epoch; attached sequence trees receive that same epoch.
"""
from collections import Counter
from fractions import Fraction

from continuous.physics import depot_origin, stationary_guard
from continuous.potential import verify_potential
from env.local_scope import affected_uavs, scope_family
from env.wind_dependency import diagnose_wind_update
from level2.replay import InvalidProof, _require, replay_sequence
from recovery.linear import rational


def _lower_table(scenario, entries):
    _require(isinstance(entries, list), 'invalid global lower-bound table')
    fleet = set(scenario.data['state']['fleet'])
    table = {}
    for entry in entries:
        _require(entry['kind'] == 'global_leg_lower_v1' and entry['uid'] in fleet,
                 'invalid global leg lower-bound identity')
        start, goal = entry['start'], entry['goal']
        _require(isinstance(start, list) and isinstance(goal, list)
                 and len(start) == len(goal) == 2, 'invalid global leg endpoints')
        # Reject malformed coordinates even when the certificate claims zero.
        for value in [*start, *goal]:
            _require(type(value) in (int, float), 'invalid global leg coordinate')
            rational(value)
        _require(isinstance(entry['lower'], str), 'global lower bound must be rational text')
        lower, certificate = Fraction(entry['lower']), entry['lower_certificate']
        _require(lower >= 0, 'negative global lower bound')
        if certificate is None:
            _require(lower == 0, 'positive global lower bound lacks certificate')
        else:
            _require(certificate['start'] == start and certificate['goal'] == goal
                     and certificate['uid'] == entry['uid']
                     and verify_potential(scenario, entry['uid'], certificate)
                     and lower == Fraction(certificate['lower']),
                     'invalid global potential certificate')
        key = entry['uid'], tuple(start), tuple(goal)
        _require(key not in table, 'duplicate global lower-bound key')
        table[key] = lower
    return table


def _assignment_exclusions(scenario, prefix, tasks, patch, table, scope_level=3):
    """Necessary conditions on a partial assignment, using only optimistic data."""
    d = scenario.data
    mission, state = d['mission'], d['state']
    task_data = {t['id']: t for t in mission['tasks']}
    fleet = {u['id']: u for u in mission['vehicles']}
    routes, releases = d['incumbent']['routes'], patch.releases
    selected = dict(zip(tasks, prefix))
    proofs = []
    # Same origin rule as the producer: only a ground depot origin prepares first.
    ground_origin = {uid: depot_origin(scenario, uid) for uid in fleet}
    for task, uid in selected.items():
        t = task_data[task]
        mandatory = rational(t['mandatory'])
        cumulative = rational(state['cumulative_delivered'][task])
        if uid is None:
            if mandatory > cumulative:
                proofs.append(dict(kind='assignment_mandatory_v1', task=task,
                                   mandatory=str(mandatory), cumulative=str(cumulative)))
        else:
            u = fleet[uid]
            if (all(f'{uid}:{h}' not in releases['S'] for h in range(1, u['slot_bound']+1))
                    and task not in routes[uid]['stops']):
                proofs.append(dict(kind='assignment_fixed_owner_v1', task=task, uav=uid))
            if mandatory > cumulative and t['deadline_h'] is not None:
                start = tuple(mission['depot_xy']) if ground_origin[uid] else tuple(state['fleet'][uid]['position_xy'])
                earliest = (rational(mission['epoch_h'])
                            + (rational(d['operations']['preparation_duration_h']) if ground_origin[uid] else 0)
                            + rational(d['operations']['service_duration_h'])
                            + table.get((uid, start, tuple(t['position_xy'])), Fraction(0)))
                limit = rational(t['deadline_h'])
                if earliest > limit:
                    proofs.append(dict(kind='assignment_deadline_v1', task=task, uav=uid,
                                       earliest=str(earliest), limit=str(limit)))
        for owner, u in fleet.items():
            for h in range(1, u['slot_bound']+1):
                if (f'{owner}:{h}' not in releases['S'] and routes[owner]['stops'][h-1] == task
                        and uid != owner):
                    proofs.append(dict(kind='assignment_commitment_v1', task=task, uav=owner, slot=h))
    for uid, u in fleet.items():
        owned = sorted(i for i, owner in selected.items() if owner == uid)
        available = u['slot_bound']-1
        if len(owned) > available:
            proofs.append(dict(kind='assignment_slots_v1', uav=uid, tasks=owned, available_slots=available))
    if scope_level == 4:
        depot = tuple(mission['depot_xy'])
        epoch = rational(mission['epoch_h'])
        ground = (rational(d['operations']['preparation_duration_h'])
                  + rational(d['operations']['service_duration_h']))
        mass = rational(mission['commodity_unit_mass_kg'])
        for task in tasks:
            t = task_data[task]
            required = rational(t['mandatory'])-rational(state['cumulative_delivered'][task])
            if required <= 0 or t['deadline_h'] is None:
                continue
            if task in selected:
                owner = selected[task]
                owners = [] if owner is None else [owner]
            else:
                owner = d['incumbent']['assignment'][task]
                owners = sorted(fleet) if task in releases['A'] else ([] if owner is None else [owner])
            if not all(ground_origin[uid] for uid in owners):
                continue
            candidates = []
            point = tuple(t['position_xy'])
            for uid in owners:
                ratio = required*mass/rational(fleet[uid]['payload_capacity_kg'])
                # Exact integer ceiling, reconstructed without proposal code.
                sorties = -(-ratio.numerator//ratio.denominator)
                outward = table.get((uid, depot, point), Fraction(0))
                backward = table.get((uid, point, depot), Fraction(0))
                earliest = epoch+sorties*(ground+outward)+(sorties-1)*backward
                candidates.append(dict(uav=uid, sorties=sorties, earliest=str(earliest)))
            limit = rational(t['deadline_h'])
            if candidates:
                earliest = min(Fraction(c['earliest']) for c in candidates)
                if earliest > limit:
                    proofs.append(dict(kind='assignment_completion_deadline_v1', task=task,
                                       candidates=candidates, earliest=str(earliest), limit=str(limit)))
    return proofs


def _patch_tree(scenario, record, patch, task_order, table, digits, unsupported, scope_level=3):
    _require(record['patch'] == patch.to_dict(), 'helper patch identity or release mask mismatch')
    _require(record['tasks'] == task_order, 'assignment tree omits or reorders original tasks')
    nodes = record['nodes']
    _require(isinstance(nodes, list) and nodes and type(record['root']) is int and record['root'] == 0,
             'missing assignment root')
    _require(nodes[0]['prefix'] == [], 'assignment root must cover the whole patch')
    if unsupported:
        _require(len(nodes) == 1 and nodes[0]['kind'] == 'open', 'unsupported model claims assignment evidence')
    old = scenario.data['incumbent']['assignment']
    fleet = sorted(scenario.data['state']['fleet'])
    choices = [[None, *fleet] if i in patch.releases['A'] else [old[i]] for i in task_order]
    visited, prefixes, counts, witnesses, sequences = set(), set(), Counter(), [], []
    covered = True
    stack = [0]
    while stack:
        index = stack.pop()
        _require(type(index) is int and 0 <= index < len(nodes), 'invalid assignment child identifier')
        _require(index not in visited, 'shared assignment node or cycle')
        visited.add(index)
        node = nodes[index]
        prefix, kind = node['prefix'], node['kind']
        _require(isinstance(prefix, list) and len(prefix) <= len(task_order), 'invalid assignment prefix')
        _require(all(uid in choices[j] for j, uid in enumerate(prefix)), 'prefix changes fixed assignment')
        key = tuple(prefix)
        _require(key not in prefixes, 'duplicate assignment prefix')
        prefixes.add(key)
        if kind == 'branch':
            _require(not unsupported and len(prefix) < len(task_order), 'assignment branch exceeds domain')
            children = node['children']
            _require(isinstance(children, list) and len(children) == len(choices[len(prefix)]),
                     'assignment branch omits or duplicates a raw owner choice')
            for child, owner in zip(children, choices[len(prefix)]):
                _require(type(child) is int and 0 <= child < len(nodes), 'invalid assignment child identifier')
                _require(nodes[child]['prefix'] == [*prefix, owner], 'assignment child partition mismatch')
            stack.extend(reversed(children))
            continue
        _require(not node.get('children'), 'terminal assignment region has children')
        counts[kind] += 1
        if kind == 'open':
            covered = False
        elif kind == 'assignment_prune':
            _require(not unsupported and node['proof'] in _assignment_exclusions(
                scenario, prefix, task_order, patch, table, scope_level), 'unproved assignment exclusion')
        elif kind == 'sequence':
            _require(not unsupported and len(prefix) == len(task_order), 'sequence proof needs complete assignment')
            assignment = dict(zip(task_order, prefix))
            _require(node['assignment'] == assignment, 'attached sequence assignment differs from prefix')
            proof = node['proof']
            _require(proof['digits'] == digits, 'attached sequence precision mismatch')
            checked = replay_sequence(scenario, proof, assignment, patch, scope_level=scope_level)
            _require(checked['valid'], 'invalid attached sequence proof: '+str(checked['reason']))
            sequences.append(checked)
            covered &= checked['covered']
            if checked['status'] == 'WITNESS':
                witnesses.append(proof['witness'])
        else:
            raise InvalidProof('unknown assignment terminal kind')
    _require(len(visited) == len(nodes), 'unreachable assignment nodes')
    derived = 'WITNESS' if witnesses else 'EMPTY' if covered else 'UNRESOLVED'
    _require(record['status'] == derived, 'helper patch conclusion lacks assignment coverage')
    return dict(status=derived, covered=covered, nodes=len(visited), leaf_counts=dict(counts),
                witnesses=witnesses, sequences=sequences)


def _replay_assignments(scenario, report, level):
    """Check original assignment coverage for a local union or global tree."""
    try:
        _require(type(level) is int and level in (3, 4), 'invalid assignment replay level')
        _require(report['version'] == f'level{level}_certified_v1', 'unsupported assignment proof version')
        if level == 4:
            _require(type(report['scope_level']) is int and report['scope_level'] == 4,
                     'global scope level mismatch')
        _require(report['scenario_hash'] == scenario.content_hash(), 'original scenario identity mismatch')
        _require(report['domain'] == 'all_admissible_continuous_polylines', 'path domain mismatch')
        digits = report['digits']
        _require(type(digits) is int and 1 <= digits <= 60, 'invalid enclosure precision')
        unsupported = stationary_guard(scenario)
        _require(report['unsupported'] == unsupported, 'unsupported model declaration mismatch')
        affected = affected_uavs(scenario, diagnose_wind_update(scenario))['uavs']
        _require(report['affected'] == affected, 'original affected fleet mask mismatch')
        family = scope_family(scenario, level, affected)
        records = report['patches'] if level == 3 else [report['tree']]
        _require(isinstance(records, list) and len(records) == len(family),
                 'missing or duplicate permitted helper patches')
        table = _lower_table(scenario, report['lower_bounds'])
        _require(not unsupported or not table, 'unsupported model claims global bounds')
        tasks = sorted(scenario.data['incumbent']['assignment'])
        checked = [_patch_tree(scenario, r, p, tasks, table, digits, unsupported, level)
                   for r, p in zip(records, family)]
        witnesses = [w for patch in checked for w in patch['witnesses']]
        covered = all(p['covered'] for p in checked)
        derived = 'WITNESS' if witnesses else 'EMPTY' if covered else 'UNRESOLVED'
        _require(report['status'] == derived, 'assignment conclusion lacks complete original scope coverage')
        if witnesses:
            _require(any(report['witness'] == w for w in witnesses), 'top-level witness is not an attached exact witness')
        else:
            _require(report['witness'] is None, 'unverified top-level witness')
        leaf_counts = Counter()
        for patch in checked:
            leaf_counts.update(patch['leaf_counts'])
        return dict(valid=True, status=derived, covered=covered, patches=len(checked),
                    nodes=sum(p['nodes'] for p in checked),
                    sequence_proofs=sum(len(p['sequences']) for p in checked),
                    leaf_counts=dict(leaf_counts), reason=None)
    except (ValueError, TypeError, KeyError, ArithmeticError, IndexError, StopIteration) as error:
        return dict(valid=False, status='INVALID', covered=False, patches=0, nodes=0,
                    sequence_proofs=0, leaf_counts={}, reason=str(error))


def replay_tree(scenario, report):
    """Check the complete helper union, every owner child, and every sequence tree."""
    return _replay_assignments(scenario, report, 3)


def verify_tree(scenario, report):
    return replay_tree(scenario, report)['valid']


replay_level3 = replay_tree
verify_level3 = verify_tree
