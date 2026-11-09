"""Independent replay of a v2 run: every certificate, proof, plan and the bracket.

No optimizer, path generator or LP solver runs here. Lower-bound certificates are
checked in rational arithmetic, route checks and stop-sequence trees are
recomputed from the scenario and the cited tick matrices, Farkas combinations are
re-multiplied against rebuilt rows, and plans go through the exact quantity
checker. The bracket must equal the one implied by what replays.
"""
from fractions import Fraction

from continuous.physics import stationary_duration
from env.local_scope import affected_uavs, scope_family
from env.plan import active_count
from env.wind_dependency import diagnose_wind_update
from escalation_study.ladder import witness_level
from level2.quantities import verify_quantity_witness
from recovery.linear import rational
from recovery.local_search import bounds, digest
from recovery.transfers import BranchRejected
from .metrics import plan_decisions
from .oracle import UavModel, check
from .route import TICK, floor_ticks
from .skeleton import Frame, verify_tree
from .table import verify_lower
from .uav import uav_problem, verify_uav_exclusion


class ReplayError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise ReplayError(message)


class Lookup:
    """Verified lower bounds of one evidence block, keyed by (uid, start, goal)."""

    def __init__(self, scenario, evidence):
        self.scenario = scenario
        self.lower = {}
        verified = {}
        for uid, a, b, key in evidence['pairs']:
            cert = evidence['certificates'].get(key)
            _require(cert is not None and digest(cert) == key, 'certificate digest')
            if key not in verified:
                verified[key] = verify_lower(scenario, cert['uid'], cert['start'], cert['goal'], cert,
                                             Fraction(cert['lower']))
            _require(verified[key], 'lower-bound certificate fails')
            _require(cert['uid'] == uid and list(cert['start']) == list(a) and list(cert['goal']) == list(b),
                     'certificate cited for another leg')
            self.lower[uid, tuple(a), tuple(b)] = Fraction(cert['lower'])

    def ticks(self, uid, a, b):
        if tuple(a) == tuple(b):
            return 0
        return floor_ticks(self.lower.get((uid, tuple(a), tuple(b)), Fraction(0)))


def _matrix_ok(lookup, model, tasks, matrix):
    nodes = model.nodes(tasks)
    _require(len(matrix) == len(nodes) and all(len(row) == len(nodes) for row in matrix), 'matrix shape')
    for i, a in enumerate(nodes):
        for j, b in enumerate(nodes):
            value = matrix[i][j]
            _require(isinstance(value, int) and value >= 0, 'matrix entry')
            _require(value <= lookup.ticks(model.uid, a, b), 'matrix entry exceeds its certified bound')


def verify_route_proof(scenario, lookup, proof):
    """route_timing_v2 or skeleton_tree_v2: no route of proof['uid'] serves proof['tasks']."""
    model = UavModel(scenario, proof['uid'])
    tasks = list(proof['tasks'])
    _require(tasks == sorted(set(tasks)), 'task list')
    _matrix_ok(lookup, model, tasks, proof['matrix'])
    if proof['kind'] == 'route_timing_v2':
        _require(not check(model, tasks, proof['matrix'], optimistic=True).feasible, 'route check admits the set')
    elif proof['kind'] == 'skeleton_tree_v2':
        _require(verify_tree(scenario, Frame(model, tasks, proof['matrix']), proof['tree']), 'stop-sequence tree')
    else:
        raise ReplayError('unknown route proof kind')
    return proof['uid'], frozenset(tasks)


def _fixed_route(scenario, lookup, record, mask_u0):
    d = scenario.data
    uid, level = record['uid'], record['level']
    _require(level in (0, 1), 'fixed-route level')
    released = scope_family(scenario, level, mask_u0)[0].releases['P']
    route = d['incumbent']['routes'][uid]
    n = active_count(route)
    model = UavModel(scenario, uid)
    stops = list(route['stops'][:n])
    legs = [Fraction(v) for v in record['legs']]
    _require(len(legs) == n == len(record['sources']), 'leg count')
    prev = model.start
    for h, (path, source, value) in enumerate(zip(route['paths'][:n], record['sources'], legs), 1):
        goal = model.depot if stops[h-1] == 'DEPOT' else model.position[stops[h-1]]
        if source[0] == 'pair':
            _require(f'{uid}:{h}' in released and source[1:] == [list(prev), list(goal)], 'released leg')
            _require(value*TICK <= lookup.ticks(uid, prev, goal), 'leg bound')
        else:
            _require(source == ['path', h], 'fixed leg')
            lo = stationary_duration(scenario, uid, path)[0]
            _require(value == Fraction(floor_ticks(lo), TICK), 'fixed path bound')
        prev = goal
    reserves = {k: Fraction(v) for k, v in record['reserves'].items()}
    for label, value in reserves.items():
        if label == 'initial':
            a = model.start if not model.origin else model.depot
        else:
            a = model.position[stops[int(label)-1]]
        _require(value*TICK <= lookup.ticks(uid, a, model.depot), 'reserve bound')
    fixed = {}
    for h in range(n+1):
        fixed[h, 'x'] = rational(route['deliveries'][h])
        fixed[h, 'y'] = rational(route['loads'][h])
    try:
        built = uav_problem(scenario, uid, stops, legs, reserves, released=set(), fixed=fixed)
    except BranchRejected as error:
        _require(record.get('rejected') == str(error), 'rejection reason')
        return
    _require('farkas' in record and verify_uav_exclusion(built, record['farkas']), 'fixed-route Farkas')


def _tree(scenario, routes, record, patch):
    """An assignment tree covers every owner choice; each closed node cites a route proof."""
    d = scenario.data
    participants = list(patch.participants)
    _require(record['participants'] == participants, 'participants')
    order = record['order']
    _require(sorted(order) == sorted(patch.releases['A']) and len(set(order)) == len(order), 'branching order')
    old = d['incumbent']['assignment']
    fixed = {u: sorted(t for t, o in old.items() if o == u and t not in patch.releases['A']) for u in participants}
    _require(record['fixed'] == fixed, 'fixed tasks')
    nodes = record['nodes']
    stack = [()]
    while stack:
        choice = stack.pop()
        node = nodes.get(','.join(choice))
        _require(node is not None, 'missing node')
        sets = {u: set(fixed[u]) for u in participants}
        for t, u in zip(order, choice):
            sets[u].add(t)
        if node['kind'] == 'route':
            uid, tasks = routes.get(node['proof'], (None, None))
            _require(uid == node['uid'] and tasks is not None and tasks <= sets[uid], 'cited route proof')
            continue
        _require(node['kind'] == 'branch' and len(choice) < len(order), 'open node in a proof')
        for u in participants:
            stack.append(choice+(u,))


def verify_run(scenario, result, *, transferred=None):
    """Replay one run. Returns a summary dict or raises ReplayError.

    ``transferred``: exclusions the caller has verified on a looser deadline variant of
    the same mission and wind (XR study); a run may cite only those.
    """
    diagnostic = diagnose_wind_update(scenario)
    true_u0 = affected_uavs(scenario, diagnostic)['uavs']
    _require(result['affected'] == true_u0, 'affected fleet')
    mask_u0 = result['mask_u0']
    _require(set(mask_u0) >= set(true_u0) and set(mask_u0) <= set(scenario.data['state']['fleet']), 'mask fleet')
    excluded, mu_excluded = set(result.get('transferred', ())), set()
    _require(excluded <= set(transferred or ()), 'transferred exclusion without a verified source')
    checked = dict(certificates=0, route_proofs=0, level_proofs=0, plan=False, transferred=sorted(excluded))
    if result.get('records') is not None:
        blocks = result['evidence']
        lookups = [Lookup(scenario, block) for block in blocks]
        checked['certificates'] = sum(len(b['certificates']) for b in blocks)
        routes = {}
        # Under noER each level has its own block; record ids are per block.
        for index, (block, lookup) in enumerate(zip(blocks, lookups)):
            for proof in block['proofs']:
                routes[index, proof['id']] = verify_route_proof(scenario, lookup, proof)
                checked['route_proofs'] += 1
        records = {r['id']: r for r in result['records']}

        def block_for(level):
            return 0 if len(blocks) == 1 else result['context_levels'].index(level)

        def level_ok(level, rid):
            record = records[rid]
            lookup = lookups[block_for(level)]
            local = {pid: value for (b, pid), value in routes.items() if b == block_for(level)}
            kind = record['kind']
            if kind == 'fixed_route_lower_v2':
                _require(record['level'] == level, 'record level')
                _fixed_route(scenario, lookup, record, mask_u0)
            elif kind == 'level2_route_v2':
                _require(level == 2 and record['uid'] in mask_u0, 'level-2 UAV')
                own = sorted(t for t, o in scenario.data['incumbent']['assignment'].items() if o == record['uid'])
                _require(record['tasks'] == own, 'level-2 task set')
                uid, tasks = local.get(record['proof'], (None, None))
                _require(uid == record['uid'] and tasks is not None and tasks <= set(own), 'level-2 proof')
            elif kind == 'level3_patches_v2':
                patches = scope_family(scenario, 3, mask_u0)
                _require(level == 3 and len(record['trees']) == len(patches), 'level-3 patches')
                for patch, tree_id in zip(patches, record['trees']):
                    _tree(scenario, local, records[tree_id], patch)
            elif kind == 'assignment_tree_v2':
                _require(level == 4 and record['level'] == 4, 'level-4 tree')
                _tree(scenario, local, record, scope_family(scenario, 4, mask_u0)[0])
            else:
                raise ReplayError('unknown level proof')
            checked['level_proofs'] += 1

        for level, rid in result.get('level_proofs', {}).items():
            level = int(level)
            level_ok(level, rid)
            excluded.update(range(level+1))
        for b, rid in result.get('mu_proofs', {}).items():
            # CMI-mu: no plan in the Level-3 patches at allowance b.
            b, record = int(b), records[rid]
            local = {pid: value for (k, pid), value in routes.items() if k == block_for(3)}
            patches = scope_family(scenario, 3, mask_u0, helper_budget=b)
            _require(record['kind'] == 'allowance_patches_v1' and record['allowance'] == b
                     and len(record['trees']) == len(patches), 'allowance patches')
            for patch, tree_id in zip(patches, record['trees']):
                _tree(scenario, local, records[tree_id], patch)
            mu_excluded.add(b)
            checked['level_proofs'] += 1
    upper = None
    plan = result.get('plan')
    if plan is not None:
        witness = plan['witness']
        patch_info = witness['patch']
        allowance = patch_info.get('allowance')
        _require(allowance is None or patch_info['level'] == 3, 'allowance patch level')
        patch = next(p for p in scope_family(scenario, patch_info['level'], mask_u0, helper_budget=allowance)
                     if list(p.participants) == patch_info['participants'])
        _require(verify_quantity_witness(scenario, witness, patch.releases), 'plan fails the exact checker')
        level = witness_level(scenario, witness, true_u0)[0]
        _require(level == plan['level'], 'plan level')
        upper = level
        checked['plan'] = True
    expected = bounds(excluded, upper)
    _require(expected == result['bounds'], f'bracket {result["bounds"]} differs from replay {expected}')
    if 'mu_bounds' in result:
        # mu* >= b+1 for an allowance b with no plan (allowances nest); at Level 4 the Level-3
        # exclusion covers the scenario's allowance. mu* <= the plan's own mu.
        minimum = expected['minimum']
        _require(minimum in (3, 4) and plan is not None, 'mu bracket without a certified Level 3 or 4')
        outside = len(set(scenario.data['state']['fleet'])-set(mask_u0))
        lower = 0 if minimum == 3 else min(scenario.data['hierarchy']['helper_budget'], outside)+1
        lower = max([lower]+[b+1 for b in mu_excluded])
        mu_upper = plan_decisions(scenario, witness, true_u0)['uavs_changed_outside_u0']
        _require(lower <= mu_upper, 'plan changes fewer outside UAVs than an allowance proof permits')
        mu = dict(lower=lower, upper=mu_upper, minimum=lower if lower == mu_upper else None)
        _require(mu == result['mu_bounds'], f'mu bracket {result["mu_bounds"]} differs from replay {mu}')
        checked['mu_bounds'] = mu
    return dict(checked, bounds=expected)
