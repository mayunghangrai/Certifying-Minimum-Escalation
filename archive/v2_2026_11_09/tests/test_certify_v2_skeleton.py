"""The complete stop-sequence search against enumeration of every sequence."""
from fractions import Fraction
from itertools import product
import json
from pathlib import Path
import random

import pytest

from certify_v2 import skeleton
from certify_v2.oracle import UavModel
from certify_v2.route import TICK
from certify_v2.uav import solve_uav, uav_problem
from env.scenario import Scenario
from recovery.transfers import BranchRejected

ROOT = Path(__file__).resolve().parents[1]
MISSION = ROOT/'results'/'escalation_study_primary'/'missions'/'P1_8_4_uniform_72001.json'


def _scenario(rng):
    if not MISSION.exists():
        pytest.skip('P1 primary records not available')
    item = json.loads(MISSION.read_text(encoding='utf-8'))
    p = item['scenarios'][sorted(item['scenarios'])[0]]
    for u in p['mission']['vehicles']:
        u['slot_bound'] = rng.choice([4, 5])
        u['payload_capacity_kg'] = rng.choice([1, 1.5, 3])
        u['battery_capacity_wh'] = max(u['battery_capacity_wh'], 1)*rng.choice([.15, .3, 1])
        p['state']['fleet'][u['id']]['battery_wh'] = u['battery_capacity_wh']
    for t in p['mission']['tasks']:
        t['deadline_h'] = rng.choice([None, round(rng.uniform(.3, 2.5), 4)])
    p['incumbent'], p['reserve_paths'] = _single_task_plan(p)
    try:
        return Scenario(p)
    except ValueError:
        return None


def _single_task_plan(p):
    from final_benchmark.controlled import make_plan
    sequences = {}
    for t in p['mission']['tasks']:
        uid = p['incumbent']['assignment'][t['id']]
        sequences.setdefault(uid, []).append(t['id'])
    for uid in sequences:
        sequences[uid] = sequences[uid][:1]
    plan, reserves = make_plan(p, sequences)
    for uid, route in plan['routes'].items():
        bound = next(u['slot_bound'] for u in p['mission']['vehicles'] if u['id'] == uid)
        for key, size in (('stops', bound), ('paths', bound), ('deliveries', bound+1), ('loads', bound+1)):
            route[key] = route[key][:size]+([None] if key == 'stops' else [[p['mission']['depot_xy']]] if key == 'paths' else [0])*(size-len(route[key]))
    kept = {i for s in sequences.values() for i in s}
    for t in p['mission']['tasks']:
        if t['id'] not in kept:
            t['demand'] = t['mandatory'] = 0
    p['state']['cumulative_delivered'] = {t['id']: 0 for t in p['mission']['tasks']}
    plan['assignment'] = {i: plan['assignment'][i] for i in kept}
    p['mission']['tasks'] = [t for t in p['mission']['tasks'] if t['id'] in kept]
    p['state']['cumulative_delivered'] = {i: 0 for i in kept}
    return plan, reserves


def _feasible(scenario, frame, stops):
    legs, reserves = skeleton.leg_times(frame, stops)
    try:
        built = uav_problem(scenario, frame.model.uid, stops, legs, reserves)
    except BranchRejected:
        return False
    return solve_uav(built, exclusion=False)[0] == 'WITNESS'


def _all_sequences(tasks, slots):
    for length in range(1, slots+1):
        for body in product(tasks+['DEPOT'], repeat=length-1):
            if set(tasks) <= set(body):
                yield list(body)+['DEPOT']


def test_search_is_complete_against_enumeration():
    rng = random.Random(2)
    compared = infeasible = 0
    while compared < 40:
        scenario = _scenario(rng)
        if scenario is None:
            continue
        d = scenario.data
        uid = sorted(d['state']['fleet'])[0]
        tasks = sorted(d['mission']['tasks'][j]['id'] for j in rng.sample(range(len(d['mission']['tasks'])), 2))
        model = UavModel(scenario, uid)
        nodes = model.nodes(tasks)
        # Synthetic "true" times: symmetric scaled distances on the tick grid.
        matrix = [[int(((a[0]-b[0])**2+(a[1]-b[1])**2)**.5*TICK) for b in nodes] for a in nodes]
        frame = skeleton.Frame(model, tasks, matrix)
        truth = any(_feasible(scenario, frame, s) for s in _all_sequences(tasks, model.slots))
        gen = skeleton.search(scenario, frame, route_for=lambda stops: stops if _feasible(scenario, frame, stops) else None,
                              limit=10**5)
        try:
            while True:
                next(gen)
        except StopIteration as stop:
            status, data = stop.value
        assert status in ('route', 'infeasible')
        assert (status == 'route') == truth
        if status == 'infeasible':
            infeasible += 1
            assert skeleton.verify_tree(scenario, frame, data['tree'])
        compared += 1
    assert 5 < infeasible < 35
