import sys
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))

import pytest

from continuous.physics import depot_origin, stationary_guard
from continuous.search import (committed_prefix_certificate, recover_continuous, verify_committed_prefix_certificate,
                               verify_continuous_evidence)
from continuous.oracle import ContinuousOracle
from continuous.validation import previous_premise
from env.local_scope import scope_family
from env.scenario import Scenario
from escalation_study.ladder import certify_variant
from escalation_study.missions import base_mission, variant_id
from escalation_study.snapshots import build_snapshot, conservation, phase, timeline
from final_benchmark.controlled import base_payload, make_plan
from level2.bounds import prefix_exclusion
from level2.replay import replay_tree as replay_level2
from level2.search import search_level2
from level2.skeletons import SkeletonDomain
from level3.replay import _assignment_exclusions, replay_tree as replay_level3
from level4.replay import replay_tree as replay_level4

BUDGET = {'refinements': [2, 4], 'digits': 18, 'max_operations': 100000, 'max_rows': 10000,
          'screen': {'max_seconds': 20, 'max_proposals': 40}, 'level2': {'max_seconds': 20, 'max_nodes': 100000},
          'level3': {'max_seconds': 30, 'max_nodes': 100000}, 'level4': {'max_seconds': 30, 'max_nodes': 100000}}


def airborne(deadline_a, deadline_b=3):
    """U1 has flown 1.5 km towards A with its full load; a 0.2 headwind covers x > 0."""
    p = base_payload('airborne', [('A', [2, 0], deadline_a), ('B', [2, 1], deadline_b)], [1, 1, 1], alpha=.2)
    p['incumbent'], p['reserve_paths'] = make_plan(p, {'U1': ['A', 'B'], 'U2': [], 'U3': []})
    route = p['incumbent']['routes']['U1']
    route['paths'][0] = [[1.5, 0], [2, 0]]
    load, route['loads'][0] = route['loads'][0], 0
    p['state']['fleet']['U1'].update(position_xy=[1.5, 0], mode='airborne', onboard=load, battery_wh=90)
    p['state']['depot_stock'] = 0
    p['reserve_paths']['U1']['initial'] = [[1.5, 0], [0, 0]]
    p['commitments'].update(S=['U1:1'], A=['A'])
    return Scenario(p)


def test_guard_admits_airborne_but_not_ground_residual_modes():
    scenario = airborne(.7)
    assert stationary_guard(scenario) is None and not depot_origin(scenario, 'U1') and depot_origin(scenario, 'U2')
    assert previous_premise(scenario)['accepted']


def test_level2_root_bound_starts_at_the_observed_position():
    scenario = airborne(.7)
    domain = SkeletonDomain(scenario)
    # A depot start would need 2.5 h to reach A; the airborne UAV needs about 0.625 h.
    lower = {('U1', (0, 0), (2, 0)): Fraction(5, 2), ('U1', (1.5, 0), (2, 0)): Fraction(5, 8)}
    assert prefix_exclusion(scenario, domain, [], lower) is None
    report = search_level2(scenario, max_seconds=20, max_nodes=20000)
    assert report['status'] == 'WITNESS' and replay_level2(scenario, report)['valid']
    forged = deepcopy(report)
    forged.update(status='EMPTY', witness=None, nodes=[dict(prefix=[], kind='resource', proof=dict(
        kind='prefix_resource_v1', uav='U1', rule='unvisited_deadline', value='5/2', limit='7/10', slot=1, task='A'))])
    assert not replay_level2(scenario, forged)['valid']


def test_retention_holds_when_the_airborne_leg_still_meets_its_deadline():
    scenario = airborne(.7)
    report = recover_continuous(scenario, max_seconds=20, max_proposals=20)
    assert report['full_domain']['minimum'] == 0 and verify_continuous_evidence(scenario, report)


def test_committed_destination_failure_excludes_every_level():
    scenario = airborne(.6)
    certificate = committed_prefix_certificate(scenario, ContinuousOracle(scenario))
    assert certificate['rule'] == 'deadline' and verify_committed_prefix_certificate(scenario, certificate)
    for key, value in (('value', '1'), ('uav', 'U2'), ('rule', 'battery'), ('lower', '1')):
        assert not verify_committed_prefix_certificate(scenario, {**certificate, key: value})
    assert not verify_committed_prefix_certificate(airborne(.7), certificate)
    report = recover_continuous(scenario, max_seconds=20, max_proposals=20)
    assert report['full_domain']['minimum'] == 'infinity' and verify_continuous_evidence(scenario, report)


def test_assignment_deadline_bound_uses_each_owners_origin():
    scenario = airborne(.7, 1.55)
    patch = next(p for p in scope_family(scenario, 3, ['U1']) if 'U2' in p.participants)
    table = {('U1', (1.5, 0), (2, 1)): Fraction(1), ('U2', (0, 0), (2, 1)): Fraction(27, 10)}
    near = _assignment_exclusions(scenario, ['U1', 'U1'], ['A', 'B'], patch, table)
    far = _assignment_exclusions(scenario, ['U1', 'U2'], ['A', 'B'], patch, table)
    assert not [p for p in near if p['kind'] == 'assignment_deadline_v1']
    assert [p['uav'] for p in far if p['kind'] == 'assignment_deadline_v1'] == ['U2']


def test_ladder_on_an_airborne_state_replays_every_stage():
    # B (deadline 1.55) is reachable only by U1 after its committed visit to A.
    scenario = airborne(.7, 1.55)
    result = certify_variant(scenario, BUDGET)
    assert result['bounds']['lower'] is None or result['bounds']['lower'] >= 1
    assert verify_continuous_evidence(scenario, result['stages']['screen'])
    for stage, replay in (('level2', replay_level2), ('level3', replay_level3), ('level4', replay_level4)):
        if result['stages'][stage] is not None:
            checked = replay(scenario, result['stages'][stage])
            assert checked['valid'] and checked['status'] == result['stages'][stage]['status']


@pytest.fixture(scope='module')
def parent():
    variants, ledger = base_mission(4, 4, 'uniform', 71001)
    return variants, ledger


def test_snapshot_is_reachable_conserving_and_deadline_independent(parent):
    variants, ledger = parent
    cell = ledger['cell_index']
    snaps = []
    for si in (0, 4):
        source = variants[variant_id(ledger['mission'], 1, si)]
        wind = source['wind']['received']['values'][cell][0]
        snap, record = build_snapshot(source, '1/2', received_wind=(cell, wind))
        scenario = Scenario(snap)
        assert conservation(source, snap) and previous_premise(scenario)['accepted']
        executed = deepcopy(source)
        executed['wind']['received'], executed['wind']['update_support'] = deepcopy(executed['wind']['previous']), []
        events = timeline(Scenario(executed))
        t = Fraction(record['snapshot'])
        for uid, items in events.items():
            assert phase(items, t)[0] in ('fly', 'idle')
            state = snap['state']['fleet'][uid]
            if state['mode'] == 'airborne':
                assert f'{uid}:1' in snap['commitments']['S']
                assert snap['mission']['vehicles'][int(uid[1:])-1]['slot_bound'] == \
                    source['mission']['vehicles'][int(uid[1:])-1]['slot_bound']-record['uavs'][uid]['completed']
        snaps.append((snap, record))
    (a, ra), (b, rb) = snaps
    assert ra == rb and a['state'] == b['state'] and a['incumbent'] == b['incumbent']
