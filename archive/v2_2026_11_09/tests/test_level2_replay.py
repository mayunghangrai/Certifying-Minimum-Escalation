"""Adversarial coverage checks independent of the Level-2 producer."""
from copy import deepcopy
import importlib
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from env.scenario import Scenario
from final_benchmark.controlled import base_payload, make_plan
from final_benchmark.controlled import controlled_case


def scene():
    p = base_payload('replay_domain', [('A', [1, 0], 4)], [1], alpha=.2)
    p['mission']['vehicles'][0]['slot_bound'] = 2
    p['incumbent'], p['reserve_paths'] = make_plan(p, {'U1': ['A']})
    return Scenario(p)


def open_report(s):
    return dict(version='level2_exhaustive_v1', scenario_hash=s.content_hash(),
                domain='all_admissible_continuous_polylines', digits=18,
                unsupported=None, affected=['U1'], leg_bounds=[],
                nodes=[dict(prefix=[], kind='open', reason='budget')], root=0,
                status='UNRESOLVED', witness=None, effort={}, budget={})


def full_tree(s):
    report = open_report(s)
    nodes = report['nodes']
    nodes[0] = dict(prefix=[], kind='branch', children=[])
    reasons = {(None, None): 'assignment_coverage',
               (None, 'DEPOT'): 'padding', (None, 'A'): 'padding',
               ('DEPOT', None): 'assignment_coverage',
               ('DEPOT', 'DEPOT'): 'assignment_coverage',
               ('DEPOT', 'A'): 'termination',
               ('A', None): 'termination', ('A', 'A'): 'termination'}
    for a in (None, 'DEPOT', 'A'):
        branch = len(nodes)
        nodes[0]['children'].append(branch)
        nodes.append(dict(prefix=[a], kind='branch', children=[]))
        for b in (None, 'DEPOT', 'A'):
            leaf = len(nodes)
            nodes[branch]['children'].append(leaf)
            reason = reasons.get((a, b))
            nodes.append(dict(prefix=[a, b], kind='structural', reason=reason)
                         if reason else dict(prefix=[a, b], kind='open', reason='geometry gap'))
    return report


def test_open_root_is_valid_unresolved_evidence():
    replay = importlib.import_module('level2.replay')
    s = scene()
    result = replay.replay_tree(s, open_report(s))
    assert result['valid']
    assert result['status'] == 'UNRESOLVED'
    assert not result['covered']


def test_full_raw_branching_preserves_nonpermutation_domain():
    replay = importlib.import_module('level2.replay')
    s = scene()
    report = full_tree(s)
    assert replay.verify_tree(s, report)
    assert replay.replay_tree(s, report)['leaf_counts']['structural'] == 8


def test_omitted_inactive_depot_and_repeated_visit_children_are_rejected():
    replay = importlib.import_module('level2.replay')
    s = scene()
    report = full_tree(s)
    for i in range(3):
        bad = deepcopy(report)
        bad['nodes'][0]['children'].pop(i)
        assert not replay.verify_tree(s, bad)
    bad = deepcopy(report)
    # Even a currently impossible repeat is part of the raw proof partition.
    bad['nodes'][9]['children'].pop()
    assert not replay.verify_tree(s, bad)


def test_shared_nodes_cycles_and_unreachable_nodes_are_rejected():
    replay = importlib.import_module('level2.replay')
    s = scene()
    report = full_tree(s)
    for children in ([1, 1, 9], [0, 5, 9]):
        bad = deepcopy(report)
        bad['nodes'][0]['children'] = children
        assert not replay.verify_tree(s, bad)
    bad = deepcopy(report)
    bad['nodes'].append(dict(prefix=[], kind='open', reason='hidden'))
    assert not replay.verify_tree(s, bad)


def test_unresolved_leaf_cannot_be_relabelled_as_complete_exclusion():
    replay = importlib.import_module('level2.replay')
    s = scene()
    report = full_tree(s)
    report['status'] = 'EMPTY'
    assert not replay.verify_tree(s, report)
    report['status'] = 'UNRESOLVED'
    report['nodes'][11] = dict(prefix=['A', 'DEPOT'], kind='structural', reason='termination')
    assert not replay.verify_tree(s, report)


def test_scenario_identity_and_affected_mask_cannot_be_tampered_with():
    replay = importlib.import_module('level2.replay')
    s = scene()
    report = open_report(s)
    for key, value in (('affected', []), ('scenario_hash', 'other'), ('digits', True)):
        bad = deepcopy(report)
        bad[key] = value
        assert not replay.verify_tree(s, bad)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def uniformly_adverse_scene():
    p = scene().to_dict()
    p['mission']['tasks'][0]['deadline_h'] = 1.1
    p['wind']['previous']['values'][0] = [[-.2, 0]]
    p['wind']['received']['values'][0] = [[-.2, 0]]
    return Scenario(p)


def test_verified_leg_bounds_are_required_and_duplicate_keys_rejected():
    replay = importlib.import_module('level2.replay')
    oracle = importlib.import_module('continuous.oracle')
    s = scene()
    q = oracle.ContinuousOracle(s, refinements=(1,)).query('U1', [0, 0], [1, 0], bound=False)
    report = open_report(s)
    report['leg_bounds'] = [q]
    assert replay.verify_tree(s, report)
    bad = deepcopy(report)
    bad['leg_bounds'][0]['lower'] = '1'
    assert not replay.verify_tree(s, bad)
    bad = deepcopy(report)
    bad['leg_bounds'].append(q)
    assert not replay.verify_tree(s, bad)


def test_resource_proof_can_exclude_every_slot_structure_from_root():
    replay = importlib.import_module('level2.replay')
    oracle = importlib.import_module('continuous.oracle')
    s = uniformly_adverse_scene()
    report = open_report(s)
    report['leg_bounds'] = [oracle.ContinuousOracle(s, refinements=(1,)).query('U1', [0, 0], [1, 0])]
    proof = dict(kind='prefix_resource_v1', uav='U1', rule='unvisited_deadline',
                 value='5/4', limit='11/10', slot=1, task='A')
    report['nodes'] = [dict(prefix=[], kind='resource', proof=proof)]
    report['status'] = 'EMPTY'
    assert replay.verify_tree(s, report)
    assert replay.replay_tree(s, report)['covered']
    for key, value in (('value', '2'), ('limit', '1'), ('task', 'other'), ('slot', 2)):
        bad = deepcopy(report)
        bad['nodes'][0]['proof'][key] = value
        assert not replay.verify_tree(s, bad)


def test_exact_quantity_witness_is_independently_checked_and_bound_to_leaf():
    replay = importlib.import_module('level2.replay')
    transfers = importlib.import_module('recovery.transfers')
    physics = importlib.import_module('continuous.physics')
    scope = importlib.import_module('env.local_scope')
    s = scene()
    plan, reserves = s.to_dict()['incumbent'], s.to_dict()['reserve_paths']
    releases = scope.scope_family(s, 2, ['U1'])[0].releases
    compiled = transfers.build_transfer_problem(s, plan, reserves, releases, exact=True,
        duration_provider=lambda uid, path, time: physics.stationary_duration(s, uid, path, 18)[1])
    values = [str(plan['routes'][uid]['deliveries' if a == 'x' else 'loads'][h])
              for uid, h, a in compiled.columns]
    witness = dict(kind='quantity_primal_v1', scenario_hash=s.content_hash(),
                   plan=plan, reserve_paths=reserves, values=values,
                   columns=[list(c) for c in compiled.columns], digits=18,
                   candidate_hash=digest(plan), reserve_hash=digest(reserves))
    report = full_tree(s)
    report['nodes'][11] = dict(prefix=['A', 'DEPOT'], kind='witness', witness=witness)
    report['witness'], report['status'] = witness, 'WITNESS'
    assert replay.verify_tree(s, report)
    for key, value in (('values', ['0']*len(values)), ('columns', []), ('digits', 17)):
        bad = deepcopy(report)
        bad['nodes'][11]['witness'][key] = value
        bad['witness'] = bad['nodes'][11]['witness']
        assert not replay.verify_tree(s, bad)
    bad = deepcopy(report)
    bad['nodes'][11]['prefix'] = ['DEPOT', 'DEPOT']
    assert not replay.verify_tree(s, bad)


def test_quantity_farkas_certificate_is_rebuilt_from_scenario_not_report_rows():
    replay = importlib.import_module('level2.replay')
    transfers = importlib.import_module('recovery.transfers')
    linear = importlib.import_module('recovery.linear')
    scope = importlib.import_module('env.local_scope')
    oracle = importlib.import_module('continuous.oracle')
    s = uniformly_adverse_scene()
    q = oracle.ContinuousOracle(s, refinements=(1,)).query('U1', [0, 0], [1, 0])
    plan, reserves = s.to_dict()['incumbent'], s.to_dict()['reserve_paths']
    compiled = transfers.build_transfer_problem(s, plan, reserves,
        scope.scope_family(s, 2, ['U1'])[0].releases, exact=True,
        duration_provider=lambda uid, path, time: linear.rational(q['lower'])
        if path[0] == q['start'] and path[-1] == q['goal'] else 0)
    exclusion = linear.solve_linear(compiled.problem, numerical=False)
    assert exclusion.status == 'EMPTY'
    proof = dict(kind='quantity_farkas_v1', scenario_hash=s.content_hash(),
                 candidate_hash=digest(plan), reserve_hash=digest(reserves),
                 certificate=exclusion.certificate)
    report = full_tree(s)
    report['leg_bounds'] = [q]
    report['nodes'][11] = dict(prefix=['A', 'DEPOT'], kind='quantity', plan=plan,
                               reserve_paths=reserves, proof=proof)
    report['status'] = 'EMPTY'
    assert replay.verify_tree(s, report)
    bad = deepcopy(report)
    bad['nodes'][11]['proof']['certificate']['multipliers'] = {'0': '1'}
    assert not replay.verify_tree(s, bad)
    bad = deepcopy(report)
    bad['nodes'][11]['proof']['candidate_hash'] = 'not-the-plan'
    assert not replay.verify_tree(s, bad)


def test_depot_arrival_battery_is_checked_before_optimistic_recharge():
    replay = importlib.import_module('level2.replay')
    p = scene().to_dict()
    p['wind']['received']['values'][1] = [[.8, 0]]
    p['mission']['vehicles'][0]['battery_capacity_wh'] = 4
    p['state']['fleet']['U1']['battery_wh'] = 4
    p['commitments']['P'] = ['U1:2']
    s = Scenario(p)
    report = full_tree(s)
    report['nodes'][11] = dict(prefix=['A', 'DEPOT'], kind='resource', proof=dict(
        kind='prefix_resource_v1', uav='U1', rule='battery', value='-1', limit='0', slot=2, task='DEPOT'))
    report['status'] = 'EMPTY'
    assert replay.verify_tree(s, report)


def test_standalone_replay_command_returns_nonzero_for_altered_coverage(tmp_path):
    s = scene()
    path = tmp_path/'record.json'
    path.write_text(json.dumps(dict(case_id='test', scenario=s.to_dict(), result=full_tree(s))), encoding='utf-8')
    script = Path(__file__).resolve().parents[1]/'scripts'/'replay_level2.py'
    command = [sys.executable, str(script), str(path)]
    answer = subprocess.run(command, text=True, capture_output=True)
    assert answer.returncode == 0, answer.stderr
    assert json.loads(answer.stdout)['valid']
    record = json.loads(path.read_text(encoding='utf-8'))
    record['result']['nodes'][0]['children'].pop()
    path.write_text(json.dumps(record), encoding='utf-8')
    answer = subprocess.run(command, text=True, capture_output=True)
    assert answer.returncode == 1
    assert not json.loads(answer.stdout)['valid']


def test_replay_never_calls_producer_or_numerical_optimizer(monkeypatch):
    search = importlib.import_module('level2.search')
    replay = importlib.import_module('level2.replay')
    cases = [controlled_case(k).scenario for k in ('C2', 'C3')]
    reports = [search.search_level2(s, max_seconds=20, refinements=(1,)) for s in cases]

    def forbidden(*args, **kwargs):
        raise AssertionError('the separate checker invoked search or an optimizer')

    monkeypatch.setattr(search, 'search_level2', forbidden)
    monkeypatch.setattr(importlib.import_module('level2.quantities'), 'evaluate_quantities', forbidden)
    monkeypatch.setattr(importlib.import_module('level2.bounds'), 'prefix_exclusion', forbidden)
    monkeypatch.setattr(importlib.import_module('level2.skeletons'), 'SkeletonDomain', forbidden)
    monkeypatch.setattr(importlib.import_module('continuous.oracle').ContinuousOracle, 'query', forbidden)
    monkeypatch.setattr(importlib.import_module('continuous.conic'), 'solve', forbidden)
    monkeypatch.setattr(importlib.import_module('recovery.linear'), 'solve_linear', forbidden)
    monkeypatch.setattr(importlib.import_module('scipy.optimize'), 'linprog', forbidden)
    assert all(replay.verify_tree(s, r) for s, r in zip(cases, reports))

