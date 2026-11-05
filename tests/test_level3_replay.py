"""Adversarial replay of reassignment trees and explicitly scoped sequences."""
from copy import deepcopy
import importlib
import json
from pathlib import Path
import subprocess
import sys

from env.scenario import Scenario
from env.local_scope import affected_uavs, scope_family
from env.wind_dependency import diagnose_wind_update
from final_benchmark.controlled import controlled_case, make_plan


def scene():
    return controlled_case('C3').scenario


def patches(s):
    affected = affected_uavs(s, diagnose_wind_update(s))['uavs']
    return affected, scope_family(s, 3, affected)


def sequence_report(s, assignment, patch):
    affected, _ = patches(s)
    return dict(version='sequence_exhaustive_v1', scenario_hash=s.content_hash(),
                domain='all_admissible_continuous_polylines', digits=18,
                unsupported=None, affected=affected, assignment=deepcopy(assignment),
                patch=patch.to_dict(), leg_bounds=[], root=0,
                nodes=[dict(prefix=[], kind='open', reason='budget')],
                status='UNRESOLVED', witness=None, effort={}, budget={})


def sequence_checker():
    module = importlib.import_module('level2.replay')
    # Missing explicit replay must fail as an assertion, not an import error.
    assert hasattr(module, 'replay_sequence'), 'explicit original-scenario sequence replay is missing'
    return module


def test_sequence_replay_accepts_candidate_assignment_without_rebasing_scenario():
    s = scene()
    _, family = patches(s)
    patch = family[0]
    assignment = {'C': 'U2', 'E': 'U1', 'D': 'U3'}
    report = sequence_report(s, assignment, patch)
    original_hash = s.content_hash()
    answer = sequence_checker().replay_sequence(s, report, assignment, patch)
    assert answer['valid'], answer
    assert answer['status'] == 'UNRESOLVED' and not answer['covered']
    assert s.content_hash() == original_hash


def test_sequence_replay_rejects_assignment_patch_hash_and_commitment_tampering():
    s = scene()
    _, family = patches(s)
    patch = family[0]
    assignment = {'C': 'U2', 'E': 'U1', 'D': 'U3'}
    report = sequence_report(s, assignment, patch)
    replay = sequence_checker()
    bad = deepcopy(report)
    bad['assignment']['C'] = 'U1'
    assert not replay.verify_sequence(s, bad, assignment, patch)
    bad = deepcopy(report)
    bad['patch']['releases']['A'].append('D')
    assert not replay.verify_sequence(s, bad, assignment, patch)
    bad = deepcopy(report)
    bad['scenario_hash'] = 'candidate-rebased-scenario'
    assert not replay.verify_sequence(s, bad, assignment, patch)
    illegal = dict(assignment, D='U2')
    assert not replay.verify_sequence(s, sequence_report(s, illegal, patch), illegal, patch)
    payload = s.to_dict()
    payload['commitments']['A'] = ['C']
    committed = Scenario(payload)
    _, committed_family = patches(committed)
    assert not replay.verify_sequence(committed, sequence_report(committed, assignment, committed_family[0]),
                                      assignment, committed_family[0])


def witness_report(s, assignment, patch):
    from continuous.physics import stationary_duration
    from recovery.transfers import build_transfer_problem
    from level2.replay import _digest
    plan, reserves = make_plan(s.to_dict(), {'U1': ['E'], 'U2': ['C'], 'U3': ['D']})
    compiled = build_transfer_problem(s, plan, reserves, patch.releases, exact=True,
        duration_provider=lambda uid, path, time: stationary_duration(s, uid, path, 18)[1])
    witness = dict(kind='quantity_primal_v1', scenario_hash=s.content_hash(), plan=plan,
                   reserve_paths=reserves, digits=18, candidate_hash=_digest(plan),
                   reserve_hash=_digest(reserves), columns=[list(c) for c in compiled.columns],
                   values=[str(plan['routes'][uid]['deliveries' if a == 'x' else 'loads'][h])
                           for uid, h, a in compiled.columns])
    report = sequence_report(s, assignment, patch)
    fleet = {u['id']: u for u in s.data['mission']['vehicles']}
    slots = [(uid, h) for uid in sorted(fleet) for h in range(1, fleet[uid]['slot_bound']+1)]
    selected = [plan['routes'][uid]['stops'][h-1] for uid, h in slots]
    nodes = report['nodes']
    index = 0
    for j, (uid, h) in enumerate(slots):
        choices = ((None, 'DEPOT', *sorted(i for i, owner in assignment.items() if owner == uid))
                   if f'{uid}:{h}' in patch.releases['S']
                   else (s.data['incumbent']['routes'][uid]['stops'][h-1],))
        nodes[index] = dict(prefix=selected[:j], kind='branch', children=[])
        next_index = None
        for stop in choices:
            child = len(nodes)
            nodes[index]['children'].append(child)
            nodes.append(dict(prefix=[*selected[:j], stop], kind='open', reason='not searched'))
            if stop == selected[j]:
                next_index = child
        index = next_index
    nodes[index] = dict(prefix=selected, kind='witness', witness=witness)
    report.update(witness=witness, status='WITNESS')
    return report


def test_sequence_exact_witness_uses_supplied_assignment_and_original_mask():
    s = scene()
    _, family = patches(s)
    assignment = {'C': 'U2', 'E': 'U1', 'D': 'U3'}
    report = witness_report(s, assignment, family[0])
    replay = sequence_checker()
    answer = replay.replay_sequence(s, report, assignment, family[0])
    assert answer['valid'], answer
    assert answer['status'] == 'WITNESS'
    bad = deepcopy(report)
    leaf = next(n for n in bad['nodes'] if n['kind'] == 'witness')
    leaf['witness']['plan']['assignment'] = s.to_dict()['incumbent']['assignment']
    bad['witness'] = leaf['witness']
    assert not replay.verify_sequence(s, bad, assignment, family[0])


def test_sequence_fixed_task_slot_can_certify_reassigned_owner_conflict():
    payload = scene().to_dict()
    payload['commitments']['S'] = ['U1:1']
    s = Scenario(payload)
    patch = patches(s)[1][0]
    assignment = {'C': 'U2', 'E': 'U1', 'D': 'U3'}
    report = sequence_report(s, assignment, patch)
    report.update(status='EMPTY', nodes=[dict(prefix=[], kind='branch', children=[1]),
        dict(prefix=['C'], kind='structural', reason='assignment_visit_owner')])
    answer = sequence_checker().replay_sequence(s, report, assignment, patch)
    assert answer['valid'] and answer['status'] == 'EMPTY' and answer['covered'], answer


def outer_report(s):
    affected, family = patches(s)
    return dict(version='level3_certified_v1', scenario_hash=s.content_hash(),
                domain='all_admissible_continuous_polylines', affected=affected,
                digits=18, unsupported=None, lower_bounds=[], witness=None,
                status='UNRESOLVED', patches=[dict(patch=p.to_dict(), tasks=sorted(s.data['incumbent']['assignment']),
                    nodes=[dict(prefix=[], kind='open', reason='budget')], root=0, status='UNRESOLVED')
                    for p in family])


def outer_checker():
    source = Path(__file__).resolve().parents[1]/'src'/'level3'/'replay.py'
    assert source.is_file(), 'independent Level-3 assignment replay is missing'
    return importlib.import_module('level3.replay')


def assignment_path(s, report, patch_index, assignment, inner=None):
    patch_record = report['patches'][patch_index]
    patch = patches(s)[1][patch_index]
    tasks, nodes, prefix = patch_record['tasks'], patch_record['nodes'], []
    index = 0
    for task in tasks:
        choices = [None, *sorted(s.data['state']['fleet'])] if task in patch.releases['A'] else [s.data['incumbent']['assignment'][task]]
        nodes[index] = dict(prefix=list(prefix), kind='branch', children=[])
        next_index = None
        for owner in choices:
            child = len(nodes)
            nodes[index]['children'].append(child)
            nodes.append(dict(prefix=[*prefix, owner], kind='open', reason='not searched'))
            if owner == assignment[task]:
                next_index = child
        prefix.append(assignment[task])
        index = next_index
    if inner is not None:
        nodes[index] = dict(prefix=prefix, kind='sequence', assignment=deepcopy(assignment), proof=inner)
        patch_record['status'] = inner['status']
        report['status'] = inner['status']
        report['witness'] = inner['witness']
    return index


def test_outer_unvisited_patches_are_explicit_unresolved_roots():
    s = scene()
    report = outer_report(s)
    answer = outer_checker().replay_tree(s, report)
    assert answer['valid'], answer
    assert answer['status'] == 'UNRESOLVED' and not answer['covered']
    for bad in (dict(report, patches=report['patches'][:1]),
                dict(report, patches=[report['patches'][0], report['patches'][0]]),
                dict(report, status='EMPTY')):
        assert not outer_checker().verify_tree(s, bad)


def test_outer_raw_assignment_branch_covers_none_and_every_fleet_owner():
    s = scene()
    report = outer_report(s)
    assignment_path(s, report, 0, {'C': 'U2', 'D': 'U3', 'E': 'U1'})
    replay = outer_checker()
    assert replay.verify_tree(s, report)
    for j in (0, 3):
        bad = deepcopy(report)
        bad['patches'][0]['nodes'][0]['children'].pop(j)
        assert not replay.verify_tree(s, bad)
    bad = deepcopy(report)
    bad['patches'][0]['tasks'] = ['C', 'E']
    assert not replay.verify_tree(s, bad)
    bad = deepcopy(report)
    bad['patches'][0]['nodes'].append(dict(prefix=[], kind='open'))
    assert not replay.verify_tree(s, bad)


def test_outer_replays_every_attached_sequence_even_after_a_witness():
    s = scene()
    report = outer_report(s)
    assignment = {'C': 'U2', 'D': 'U3', 'E': 'U1'}
    patch = patches(s)[1][0]
    inner = witness_report(s, assignment, patch)
    leaf_index = assignment_path(s, report, 0, assignment, inner)
    replay = outer_checker()
    assert replay.verify_tree(s, report)
    bad = deepcopy(report)
    bad['patches'][0]['nodes'][leaf_index]['proof']['patch']['releases']['A'].append('D')
    assert not replay.verify_tree(s, bad)
    bad = deepcopy(report)
    second_assignment = s.to_dict()['incumbent']['assignment']
    wrong_inner = sequence_report(s, second_assignment, patches(s)[1][1])
    wrong_inner['scenario_hash'] = 'wrong'
    assignment_path(s, bad, 1, second_assignment, wrong_inner)
    bad['status'], bad['witness'] = 'WITNESS', inner['witness']
    assert not replay.verify_tree(s, bad)
    bad = deepcopy(report)
    bad['witness']['candidate_hash'] = 'arbitrary top-level witness'
    assert not replay.verify_tree(s, bad)


def test_outer_inner_unresolved_cannot_close_assignment_branch():
    s = scene()
    report = outer_report(s)
    assignment = {'C': 'U2', 'D': 'U3', 'E': 'U1'}
    inner = sequence_report(s, assignment, patches(s)[1][0])
    assignment_path(s, report, 0, assignment, inner)
    replay = outer_checker()
    assert replay.verify_tree(s, report)
    bad = deepcopy(report)
    bad['patches'][0]['status'] = 'EMPTY'
    assert not replay.verify_tree(s, bad)


def test_outer_mandatory_fixed_owner_and_slot_prunes_are_recomputed():
    s = scene()
    report = outer_report(s)
    assignment_path(s, report, 0, {'C': 'U2', 'D': 'U3', 'E': 'U1'})
    nodes = report['patches'][0]['nodes']
    nodes[1] = dict(prefix=[None], kind='assignment_prune', proof=dict(
        kind='assignment_mandatory_v1', task='C', mandatory='1', cumulative='0'))
    nodes[4] = dict(prefix=['U3'], kind='assignment_prune', proof=dict(
        kind='assignment_fixed_owner_v1', task='C', uav='U3'))
    replay = outer_checker()
    assert replay.verify_tree(s, report)
    for key, value in (('mandatory', '2'), ('task', 'E')):
        bad = deepcopy(report)
        bad['patches'][0]['nodes'][1]['proof'][key] = value
        assert not replay.verify_tree(s, bad)
    bad = deepcopy(report)
    bad['patches'][0]['nodes'][4]['proof']['uav'] = 'U2'
    assert not replay.verify_tree(s, bad)


def test_outer_global_lower_certificate_and_deadline_prune_are_independent():
    from continuous.potential import uniform_certificate
    payload = scene().to_dict()
    payload['wind']['previous']['values'][0] = [[-.3, 0]]
    payload['wind']['received']['values'][0] = [[-.3, 0]]
    s = Scenario(payload)
    report = outer_report(s)
    assignment_path(s, report, 0, {'C': 'U2', 'D': 'U3', 'E': 'U1'})
    cert = uniform_certificate(s, 'U1', [0, 0], [1, 0], 18)
    report['lower_bounds'] = [dict(kind='global_leg_lower_v1', uid='U1', start=[0, 0], goal=[1, 0],
                                   lower=cert['lower'], lower_certificate=cert)]
    report['patches'][0]['nodes'][2] = dict(prefix=['U1'], kind='assignment_prune', proof=dict(
        kind='assignment_deadline_v1', task='C', uav='U1', earliest='10/7', limit='11/10'))
    replay = outer_checker()
    assert replay.verify_tree(s, report)
    for lower in ('2', '0'):
        bad = deepcopy(report)
        bad['lower_bounds'][0]['lower'] = lower
        assert not replay.verify_tree(s, bad)
    bad = deepcopy(report)
    bad['lower_bounds'][0]['uid'] = 'U2'
    assert not replay.verify_tree(s, bad)
    bad = deepcopy(report)
    bad['lower_bounds'] = []
    assert not replay.verify_tree(s, bad)
    bad = deepcopy(report)
    bad['lower_bounds'][0]['lower_certificate'] = None
    assert not replay.verify_tree(s, bad)


def test_outer_commitment_exclusion_uses_original_fixed_slot():
    payload = scene().to_dict()
    payload['commitments']['S'] = ['U1:1']
    s = Scenario(payload)
    report = outer_report(s)
    nodes = report['patches'][0]['nodes']
    nodes[0] = dict(prefix=[], kind='branch', children=[1, 2, 3, 4])
    nodes.extend(dict(prefix=[owner], kind='open') for owner in (None, 'U1', 'U2', 'U3'))
    nodes[3] = dict(prefix=['U2'], kind='assignment_prune', proof=dict(
        kind='assignment_commitment_v1', task='C', uav='U1', slot=1))
    replay = outer_checker()
    assert replay.verify_tree(s, report)
    for key, value in (('slot', 2), ('uav', 'U2'), ('task', 'D')):
        bad = deepcopy(report)
        bad['patches'][0]['nodes'][3]['proof'][key] = value
        assert not replay.verify_tree(s, bad)


def test_outer_slot_relaxation_counts_distinct_prefix_tasks_and_final_depot():
    payload = scene().to_dict()
    payload['mission']['vehicles'][0]['slot_bound'] = 2
    route = payload['incumbent']['routes']['U1']
    for key in ('stops', 'paths', 'loads', 'deliveries'):
        route[key].pop()
    s = Scenario(payload)
    report = outer_report(s)
    leaf = assignment_path(s, report, 0, {'C': 'U1', 'D': 'U3', 'E': 'U1'})
    report['patches'][0]['nodes'][leaf] = dict(prefix=['U1', 'U3', 'U1'], kind='assignment_prune',
        proof=dict(kind='assignment_slots_v1', uav='U1', tasks=['C', 'E'], available_slots=1))
    replay = outer_checker()
    assert replay.verify_tree(s, report)
    for key, value in (('tasks', ['C']), ('available_slots', 0), ('uav', 'U2')):
        bad = deepcopy(report)
        bad['patches'][0]['nodes'][leaf]['proof'][key] = value
        assert not replay.verify_tree(s, bad)


def complete_empty_report():
    from continuous.potential import uniform_certificate
    payload = controlled_case('Cinf').scenario.to_dict()
    payload['wind']['previous']['values'][0] = [[-.2, 0]]
    payload['wind']['received']['values'][0] = [[-.2, 0]]
    s = Scenario(payload)
    report = outer_report(s)
    for uid in ('U1', 'U2', 'U3'):
        cert = uniform_certificate(s, uid, [0, 0], [1, 0], 18)
        report['lower_bounds'].append(dict(kind='global_leg_lower_v1', uid=uid,
            start=[0, 0], goal=[1, 0], lower=cert['lower'], lower_certificate=cert))
    for patch in report['patches']:
        patch['nodes'] = [dict(prefix=[], kind='branch', children=[1, 2, 3, 4]),
            dict(prefix=[None], kind='assignment_prune', proof=dict(
                kind='assignment_mandatory_v1', task='C', mandatory='1', cumulative='0')),
            *[dict(prefix=[uid], kind='assignment_prune', proof=dict(kind='assignment_deadline_v1',
                task='C', uav=uid, earliest='5/4', limit='11/10')) for uid in ('U1', 'U2', 'U3')]]
        patch['status'] = 'EMPTY'
    report['status'] = 'EMPTY'
    return s, report


def test_outer_empty_requires_all_patch_regions_closed_by_verified_proofs():
    s, report = complete_empty_report()
    replay = outer_checker()
    answer = replay.replay_tree(s, report)
    assert answer['valid'] and answer['status'] == 'EMPTY' and answer['covered'], answer
    bad = deepcopy(report)
    bad['patches'][1]['nodes'][4] = dict(prefix=['U3'], kind='open')
    assert not replay.verify_tree(s, bad)
    bad['patches'][1]['status'] = 'UNRESOLVED'
    bad['status'] = 'UNRESOLVED'
    answer = replay.replay_tree(s, bad)
    assert answer['valid'] and not answer['covered'] and answer['status'] == 'UNRESOLVED'


def test_standalone_outer_replay_returns_nonzero_for_altered_owner_coverage(tmp_path):
    s, report = complete_empty_report()
    path = tmp_path/'record.json'
    path.write_text(json.dumps(dict(case_id='test', scenario=s.to_dict(), result=report)), encoding='utf-8')
    script = Path(__file__).resolve().parents[1]/'scripts'/'replay_level3.py'
    assert script.is_file(), 'standalone Level-3 replay is missing'
    command = [sys.executable, str(script), str(path)]
    answer = subprocess.run(command, text=True, capture_output=True)
    assert answer.returncode == 0, answer.stderr
    assert json.loads(answer.stdout)['valid']
    report['patches'][0]['nodes'][0]['children'].pop()
    path.write_text(json.dumps(dict(scenario=s.to_dict(), result=report)), encoding='utf-8')
    answer = subprocess.run(command, text=True, capture_output=True)
    assert answer.returncode == 1
    assert not json.loads(answer.stdout)['valid']
