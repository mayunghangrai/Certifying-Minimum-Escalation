"""The one-UAV rows must equal the full transfer compiler's rows for that UAV."""
from fractions import Fraction
import json
from pathlib import Path
import random

import pytest

from certify_v2.uav import solve_uav, uav_problem, verify_uav_exclusion
from env.local_scope import scope_family
from env.scenario import Scenario
from recovery.linear import rational
from recovery.transfers import BranchRejected, build_transfer_problem

ROOT = Path(__file__).resolve().parents[1]
MISSIONS = ROOT/'results'/'escalation_study_primary'/'missions'


def _scenarios():
    names = sorted(MISSIONS.glob('P1_*.json'))[:12]
    if not names:
        pytest.skip('P1 primary records not available')
    for path in names:
        item = json.loads(path.read_text(encoding='utf-8'))
        if item['scenarios']:
            key = sorted(item['scenarios'])[-1]
            yield Scenario(item['scenarios'][key])


def _random_plan(scenario, rng):
    p = scenario.to_dict()
    plan = p['incumbent']
    depot = p['mission']['depot_xy']
    tasks = {t['id']: t['position_xy'] for t in p['mission']['tasks']}
    reserves = {}
    for uid, route in plan['routes'].items():
        own = [i for i, o in plan['assignment'].items() if o == uid]
        bound = len(route['stops'])
        rng.shuffle(own)
        stops = []
        for i in own:
            if stops and rng.random() < .3 and stops[-1] != 'DEPOT':
                stops.append('DEPOT')
            stops.append(i)
            if rng.random() < .15:
                stops += ['DEPOT', i]
        if own:
            stops.append('DEPOT')
        stops = stops[:bound]
        if own and (set(own)-set(stops) or stops[-1] != 'DEPOT'):
            stops = own+['DEPOT']
        n = len(stops)
        points = [depot]+[depot if s == 'DEPOT' else tasks[s] for s in stops]
        route['stops'] = stops+[None]*(bound-n)
        route['paths'] = [[a, b] for a, b in zip(points, points[1:])]+[[depot]]*(bound-n)
        route['deliveries'] = [0]+[0 if s == 'DEPOT' else rng.choice([0, .5, 1]) for s in stops]+[0]*(bound-n)
        route['loads'] = [rng.choice([0, 1, 2.5])]+[rng.choice([0, 1]) if s == 'DEPOT' and h < n else 0
                                                    for h, s in enumerate(stops, 1)]+[0]*(bound-n)
        reserves[uid] = {'initial': [depot]} if n else {}
        for h, s in enumerate(stops, 1):
            if s != 'DEPOT':
                reserves[uid][str(h)] = [tasks[s], depot]
    return plan, reserves


def _times(rng):
    cache = {}

    def duration(uid, path, time):
        key = uid, tuple(map(tuple, path))
        if key not in cache:
            cache[key] = Fraction(rng.randint(0, 2000), 1000) if len(path) > 1 else Fraction(0)
        return cache[key]
    return duration, cache


def test_rows_match_the_full_compiler():
    rng = random.Random(3)
    compared = 0
    for scenario in _scenarios():
        releases = scope_family(scenario, 4, sorted(scenario.data['state']['fleet']))[0].releases
        for _ in range(6):
            plan, reserves = _random_plan(scenario, rng)
            duration, cache = _times(rng)
            try:
                full = build_transfer_problem(scenario, plan, reserves, releases, exact=True,
                                              duration_provider=duration)
            except BranchRejected as error:
                full = error
            for uid, route in plan['routes'].items():
                stops = [s for s in route['stops'] if s is not None]
                legs = [duration(uid, path, 0) for path in route['paths'][:len(stops)]]
                res = {label: duration(uid, path, 0) for label, path in reserves[uid].items()}
                try:
                    own = uav_problem(scenario, uid, stops, legs, res)
                except BranchRejected:
                    continue
                if isinstance(full, BranchRejected):
                    continue
                cols = [full.problem.variables.index(name) for name in own.problem.variables]
                mine = {r.label: (r.coefficients, r.bound) for r in own.problem.rows}
                theirs = {}
                tasks = {i for i, o in plan['assignment'].items() if o == uid}
                for r in full.problem.rows:
                    parts = r.label.split(':')
                    if (len(parts) > 1 and parts[1] == uid) or (parts[0] == 'service' and parts[1] in tasks):
                        others = [c for j, c in enumerate(r.coefficients) if j not in cols]
                        assert not any(others), r.label
                        theirs[r.label] = (tuple(r.coefficients[j] for j in cols), r.bound)
                inventory = mine.pop(f'inventory:{uid}')
                assert mine == theirs
                stock = next(r for r in full.problem.rows if r.label == 'inventory')
                assert inventory == (tuple(stock.coefficients[j] for j in cols), stock.bound)
                compared += 1
    assert compared > 100


def test_farkas_proof_replays_and_rejects_tampering():
    for scenario in _scenarios():
        d = scenario.data
        uid, route = next((u, r) for u, r in sorted(d['incumbent']['routes'].items()) if r['stops'][0])
        stops = [s for s in route['stops'] if s is not None]
        legs = [Fraction(0)]*len(stops)
        res = {'initial': Fraction(0), **{str(h): Fraction(0) for h, s in enumerate(stops, 1) if s != 'DEPOT'}}
        # A capacity of zero load forces every mandatory delivery to fail.
        built = uav_problem(scenario, uid, stops, legs, res, released={(0, 'x')})
        status, proof = solve_uav(built, exclusion=True)
        assert status == 'EMPTY'
        assert verify_uav_exclusion(built, proof)
        label = next(iter(proof))
        assert not verify_uav_exclusion(built, {**proof, label: '-1'})
        assert not verify_uav_exclusion(built, {'unknown': '1'})
        return
