"""Adversarial independent coverage checks for global Level-4 escalation."""
from copy import deepcopy
import importlib
import json
from pathlib import Path
import subprocess
import sys

from env.local_scope import affected_uavs, scope_family
from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update
from final_benchmark.controlled import base_payload, controlled_case, make_plan
from test_level3_replay import complete_empty_report, witness_report


def scene():
    return controlled_case('C3').scenario


def global_patch(s):
    affected = affected_uavs(s, diagnose_wind_update(s))['uavs']
    return affected, scope_family(s, 4, affected)[0]


def open_report(s):
    affected, patch = global_patch(s)
    return dict(version='level4_certified_v1', scope_level=4, scenario_hash=s.content_hash(),
                domain='all_admissible_continuous_polylines', affected=affected,
                digits=18, unsupported=None, lower_bounds=[], witness=None, status='UNRESOLVED',
                tree=dict(patch=patch.to_dict(), tasks=sorted(s.data['incumbent']['assignment']),
                          nodes=[dict(prefix=[], kind='open', reason='budget')], root=0, status='UNRESOLVED'))


def checker():
    source = Path(__file__).resolve().parents[1]/'src'/'level4'/'replay.py'
    assert source.is_file(), 'global Level-4 independent replay is missing'
    return importlib.import_module('level4.replay')


def inner_report(s, assignment):
    affected, patch = global_patch(s)
    return dict(version='sequence_exhaustive_v1', scope_level=4, scenario_hash=s.content_hash(),
                domain='all_admissible_continuous_polylines', affected=affected,
                digits=18, unsupported=None, leg_bounds=[], witness=None, status='UNRESOLVED',
                assignment=deepcopy(assignment), patch=patch.to_dict(),
                nodes=[dict(prefix=[], kind='open', reason='quantity budget')], root=0)


def attach_path(s, report, assignment, inner=None):
    entry = report['tree']
    nodes, prefix, index = entry['nodes'], [], 0
    _, patch = global_patch(s)
    for task in entry['tasks']:
        choices = [None, 'U1', 'U2', 'U3'] if task in patch.releases['A'] else [s.data['incumbent']['assignment'][task]]
        nodes[index] = dict(prefix=list(prefix), kind='branch', children=[])
        selected = None
        for owner in choices:
            child = len(nodes)
            nodes[index]['children'].append(child)
            nodes.append(dict(prefix=[*prefix, owner], kind='open', reason='budget'))
            if owner == assignment[task]:
                selected = child
        index = selected
        prefix.append(assignment[task])
    if inner is not None:
        nodes[index] = dict(prefix=prefix, kind='sequence', assignment=deepcopy(assignment), proof=inner)
        entry['status'] = report['status'] = inner['status']
        report['witness'] = inner['witness']
    return index


def test_global_open_root_is_valid_unresolved_evidence():
    s = scene()
    answer = checker().replay_tree(s, open_report(s))
    assert answer['valid'] and answer['status'] == 'UNRESOLVED' and not answer['covered'], answer


def test_local_patch_cannot_masquerade_as_global_coverage():
    s = scene()
    report = open_report(s)
    affected, _ = global_patch(s)
    report['tree']['patch'] = scope_family(s, 3, affected)[0].to_dict()
    assert not checker().verify_tree(s, report)


def test_global_sequence_scope_and_original_identity_are_explicit():
    s = scene()
    _, patch = global_patch(s)
    assignment = {'C': 'U2', 'D': 'U3', 'E': 'U1'}
    inner = inner_report(s, assignment)
    replay = importlib.import_module('level2.replay')
    assert 'scope_level' in __import__('inspect').signature(replay.replay_sequence).parameters, 'explicit global sequence replay is missing'
    answer = replay.replay_sequence(s, inner, assignment, patch, scope_level=4)
    assert answer['valid'], answer
    assert not replay.verify_sequence(s, inner, assignment, patch)
    for key, value in (('scope_level', 3), ('scenario_hash', 'rebased')):
        bad = deepcopy(inner)
        bad[key] = value
        assert not replay.verify_sequence(s, bad, assignment, patch, scope_level=4)
    bad = deepcopy(inner)
    bad.pop('scope_level')
    assert not replay.verify_sequence(s, bad, assignment, patch, scope_level=4)


def test_global_commitments_cannot_be_released_by_proof_metadata():
    payload = scene().to_dict()
    payload['commitments']['A'] = ['C']
    payload['commitments']['S'] = ['U1:1']
    s = Scenario(payload)
    report = open_report(s)
    replay = checker()
    assert replay.verify_tree(s, report)
    for component, coordinate in (('A', 'C'), ('S', 'U1:1')):
        bad = deepcopy(report)
        bad['tree']['patch']['releases'][component].append(coordinate)
        assert not replay.verify_tree(s, bad)


def test_global_assignment_children_cover_none_and_every_owner():
    s = scene()
    report = open_report(s)
    attach_path(s, report, {'C': 'U2', 'D': 'U3', 'E': 'U1'})
    replay = checker()
    assert replay.verify_tree(s, report)
    for index in (0, 3):
        bad = deepcopy(report)
        bad['tree']['nodes'][0]['children'].pop(index)
        assert not replay.verify_tree(s, bad)
    bad = deepcopy(report)
    bad['tree']['nodes'][0]['children'][3] = bad['tree']['nodes'][0]['children'][2]
    assert not replay.verify_tree(s, bad)


def test_global_exact_witness_is_attached_and_other_sequences_are_still_checked():
    s = scene()
    assignment = {'C': 'U2', 'D': 'U3', 'E': 'U1'}
    inner = witness_report(s, assignment, global_patch(s)[1])
    inner['scope_level'] = 4
    report = open_report(s)
    leaf = attach_path(s, report, assignment, inner)
    replay = checker()
    answer = replay.replay_tree(s, report)
    assert answer['valid'] and answer['status'] == 'WITNESS', answer
    bad = deepcopy(report)
    bad['tree']['nodes'][leaf]['proof']['scope_level'] = 3
    assert not replay.verify_tree(s, bad)
    bad = deepcopy(report)
    bad['witness'] = dict(inner['witness'], candidate_hash='arbitrary witness')
    assert not replay.verify_tree(s, bad)
    # Attach a second complete assignment in the winning C=U2 branch.
    bad = deepcopy(report)
    nodes = bad['tree']['nodes']
    alternative = {'C': 'U2', 'D': 'U3', 'E': 'U2'}
    alternate_index = next(i for i, n in enumerate(nodes) if n['prefix'] == ['U2', 'U3', 'U2'])
    nodes[alternate_index] = dict(prefix=['U2', 'U3', 'U2'], kind='sequence', assignment=alternative,
                                  proof=inner_report(s, alternative))
    nodes[alternate_index]['proof']['scenario_hash'] = 'wrong'
    assert not replay.verify_tree(s, bad)


def test_unfinished_inner_proof_keeps_global_exclusion_unresolved():
    s = scene()
    report = open_report(s)
    assignment = {'C': 'U2', 'D': 'U3', 'E': 'U1'}
    attach_path(s, report, assignment, inner_report(s, assignment))
    replay = checker()
    assert replay.verify_tree(s, report)
    bad = deepcopy(report)
    bad['tree']['status'] = bad['status'] = 'EMPTY'
    assert not replay.verify_tree(s, bad)


def test_global_exclusion_is_recomputed_and_never_accepts_heuristic_failure():
    s = scene()
    report = open_report(s)
    nodes = report['tree']['nodes']
    nodes[0] = dict(prefix=[], kind='branch', children=[1, 2, 3, 4])
    nodes.extend(dict(prefix=[owner], kind='open') for owner in (None, 'U1', 'U2', 'U3'))
    nodes[1] = dict(prefix=[None], kind='assignment_prune', proof=dict(kind='assignment_mandatory_v1',
                    task='C', mandatory='1', cumulative='0'))
    replay = checker()
    assert replay.verify_tree(s, report)
    for proof in (dict(kind='assignment_mandatory_v1', task='C', mandatory='1', cumulative='1'),
                  dict(kind='heuristic_failed_v1', reason='no routes found')):
        bad = deepcopy(report)
        bad['tree']['nodes'][1]['proof'] = proof
        assert not replay.verify_tree(s, bad)


def global_empty_report():
    s, local = complete_empty_report()
    report = open_report(s)
    report['lower_bounds'] = deepcopy(local['lower_bounds'])
    report['tree']['nodes'] = deepcopy(local['patches'][0]['nodes'])
    report['tree']['status'] = report['status'] = 'EMPTY'
    return s, report


def test_global_empty_requires_all_owner_regions_certifiably_closed():
    s, report = global_empty_report()
    replay = checker()
    answer = replay.replay_tree(s, report)
    assert answer['valid'] and answer['status'] == 'EMPTY' and answer['covered'], answer
    bad = deepcopy(report)
    bad['tree']['nodes'][4] = dict(prefix=['U3'], kind='open', reason='remaining assignments')
    assert not replay.verify_tree(s, bad)
    bad['status'] = bad['tree']['status'] = 'UNRESOLVED'
    answer = replay.replay_tree(s, bad)
    assert answer['valid'] and answer['status'] == 'UNRESOLVED' and not answer['covered'], answer


def test_global_lower_bounds_are_reverified_and_cannot_be_forged_or_relabelled():
    s, report = global_empty_report()
    replay = checker()
    for key, value in (('lower', '2'), ('uid', 'U2'), ('lower_certificate', None), ('goal', [2, 0])):
        bad = deepcopy(report)
        bad['lower_bounds'][0][key] = value
        assert not replay.verify_tree(s, bad)
    bad = deepcopy(report)
    bad['lower_bounds'].append(deepcopy(bad['lower_bounds'][0]))
    assert not replay.verify_tree(s, bad)


def test_unsupported_global_model_can_only_replay_open_evidence():
    payload = scene().to_dict()
    payload['operations']['depot_bays'] = 1
    s = Scenario(payload)
    report = open_report(s)
    report['unsupported'] = 'coupled depot preparation'
    replay = checker()
    assert replay.verify_tree(s, report)
    bad = deepcopy(report)
    bad['unsupported'] = None
    assert not replay.verify_tree(s, bad)
    bad = deepcopy(report)
    bad['tree']['nodes'][0] = dict(prefix=[], kind='assignment_prune', proof=dict(
        kind='heuristic_failed_v1', reason='no plan'))
    assert not replay.verify_tree(s, bad)


def test_global_replay_never_calls_search_cache_or_numerical_solver(monkeypatch):
    s, empty = global_empty_report()
    witness_scene = scene()
    assignment = {'C': 'U2', 'D': 'U3', 'E': 'U1'}
    inner = witness_report(witness_scene, assignment, global_patch(witness_scene)[1])
    inner['scope_level'] = 4
    report = open_report(witness_scene)
    attach_path(witness_scene, report, assignment, inner)

    def forbidden(*args, **kwargs):
        raise AssertionError('independent replay called a proposal or optimization routine')

    sequence_search = importlib.import_module('level2.search')
    assignment_search = importlib.import_module('level3.search')
    monkeypatch.setattr(sequence_search, 'search_sequence', forbidden)
    monkeypatch.setattr(assignment_search, 'search_level3', forbidden)
    monkeypatch.setattr(importlib.import_module('level3.cache').SharedContinuousCache, 'lower', forbidden)
    monkeypatch.setattr(importlib.import_module('continuous.oracle').ContinuousOracle, 'query', forbidden)
    monkeypatch.setattr(importlib.import_module('continuous.conic'), 'solve', forbidden)
    monkeypatch.setattr(importlib.import_module('recovery.linear'), 'solve_linear', forbidden)
    monkeypatch.setattr(importlib.import_module('scipy.optimize'), 'linprog', forbidden)
    assert checker().verify_tree(s, empty)
    assert checker().verify_tree(witness_scene, report)


def test_standalone_global_replay_handles_records_and_rejects_altered_coverage(tmp_path):
    s, report = global_empty_report()
    path = tmp_path/'record.json'
    path.write_text(json.dumps(dict(case_id='global', scenario=s.to_dict(), result=report)), encoding='utf-8')
    script = Path(__file__).resolve().parents[1]/'scripts'/'replay_level4.py'
    assert script.is_file(), 'standalone Level-4 independent replay is missing'
    command = [sys.executable, str(script), str(path)]
    answer = subprocess.run(command, text=True, capture_output=True)
    assert answer.returncode == 0, answer.stderr
    assert json.loads(answer.stdout)['status'] == 'EMPTY'
    report['tree']['nodes'][0]['children'].pop()
    path.write_text(json.dumps(dict(scenario=s.to_dict(), result=report)), encoding='utf-8')
    answer = subprocess.run(command, text=True, capture_output=True)
    assert answer.returncode == 1
    assert not json.loads(answer.stdout)['valid']


def completion_scene(*, deadline=5.8, mandatory=1, speeds=(1, 1, 1), committed=False):
    payload = base_payload('completion_bound', [('C', [1, 0], deadline)], list(speeds),
                           alpha=.2, operation_time=.1)
    payload['wind']['previous']['values'][0] = [[-.2, 0]]
    payload['wind']['previous']['values'][1] = [[.2, 0]]
    payload['wind']['received']['values'][0] = [[-.2, 0]]
    payload['mission']['tasks'][0]['mandatory'] = mandatory
    for vehicle in payload['mission']['vehicles']:
        vehicle['payload_capacity_kg'] = .4
        vehicle['slot_bound'] = 6
    if committed:
        payload['commitments']['A'] = ['C']
    payload['incumbent'], payload['reserve_paths'] = make_plan(payload, {'U1': ['C']})
    route = payload['incumbent']['routes']['U1']
    route.update(stops=['C', 'DEPOT']*3, paths=route['paths'][:2]*3,
                 deliveries=[0, .4, 0, .4, 0, .2, 0], loads=[.4, 0, .4, 0, .2, 0, 0])
    payload['reserve_paths']['U1'] = {'initial':[[0, 0]],
                                     **{str(h):[[1, 0], [0, 0]] for h in (1, 3, 5)}}
    return Scenario(payload)


def completion_report(s):
    from continuous.potential import uniform_certificate
    report = open_report(s)
    for uid in ('U1', 'U2', 'U3'):
        for start, goal in (([0, 0], [1, 0]), ([1, 0], [0, 0])):
            certificate = uniform_certificate(s, uid, start, goal, 18)
            report['lower_bounds'].append(dict(kind='global_leg_lower_v1', uid=uid,
                start=start, goal=goal, lower=certificate['lower'], lower_certificate=certificate))
    owners = ('U1',) if 'C' in s.data['commitments']['A'] else ('U1', 'U2', 'U3')
    proof = dict(kind='assignment_completion_deadline_v1', task='C',
                 candidates=[dict(uav=uid, sorties=3, earliest='361/60') for uid in owners],
                 earliest='361/60', limit='29/5')
    report['tree']['nodes'] = [dict(prefix=[], kind='assignment_prune', proof=proof)]
    report['tree']['status'] = report['status'] = 'EMPTY'
    return report


def test_completion_root_bound_checks_all_owners_and_exact_multiple_sorties():
    s = completion_scene()
    answer = checker().replay_tree(s, completion_report(s))
    assert answer['valid'] and answer['status'] == 'EMPTY' and answer['covered'], answer


def test_completion_bound_rejects_missing_owner_wrong_ceil_and_rational_values():
    s = completion_scene()
    report = completion_report(s)
    replay = checker()
    assert replay.verify_tree(s, report)
    bad = deepcopy(report)
    bad['tree']['nodes'][0]['proof']['candidates'].pop()
    assert not replay.verify_tree(s, bad)
    bad = deepcopy(report)
    bad['tree']['nodes'][0]['proof']['candidates'].reverse()
    assert not replay.verify_tree(s, bad)
    for key, value in (('sorties', 2), ('earliest', '6')):
        bad = deepcopy(report)
        bad['tree']['nodes'][0]['proof']['candidates'][0][key] = value
        assert not replay.verify_tree(s, bad)
    for key, value in (('earliest', '6'), ('limit', '4'), ('task', 'missing')):
        bad = deepcopy(report)
        bad['tree']['nodes'][0]['proof'][key] = value
        assert not replay.verify_tree(s, bad)


def test_completion_bound_uses_directed_return_lower_and_missing_bounds_as_zero():
    s = completion_scene(deadline=6.4)
    report = completion_report(s)
    proof = report['tree']['nodes'][0]['proof']
    # Reusing the 5/4 outbound duration for both directions would give 137/20,
    # whereas the correct optimistic completion is 361/60, below this deadline.
    for candidate in proof['candidates']:
        candidate['earliest'] = '137/20'
    proof.update(earliest='137/20', limit='32/5')
    assert not checker().verify_tree(s, report)
    s = completion_scene()
    report = completion_report(s)
    report['lower_bounds'] = [q for q in report['lower_bounds'] if q['start'] == [0, 0]]
    assert not checker().verify_tree(s, report)


def test_completion_bound_cannot_exclude_root_when_one_owner_is_optimistically_feasible():
    s = completion_scene(speeds=(1, 1, 2))
    report = completion_report(s)
    proof = report['tree']['nodes'][0]['proof']
    proof['candidates'][2]['earliest'] = '524/165'
    proof['earliest'] = '524/165'
    assert not checker().verify_tree(s, report)


def test_completion_bound_rejects_optional_task_or_extra_owners_after_selection():
    s = completion_scene(mandatory=0)
    assert not checker().verify_tree(s, completion_report(s))
    s = completion_scene()
    report = completion_report(s)
    proof = report['tree']['nodes'][0]['proof']
    report['tree']['nodes'] = [dict(prefix=[], kind='branch', children=[1, 2, 3, 4]),
        dict(prefix=[None], kind='open'), dict(prefix=['U1'], kind='assignment_prune', proof=proof),
        dict(prefix=['U2'], kind='open'), dict(prefix=['U3'], kind='open')]
    report['tree']['status'] = report['status'] = 'UNRESOLVED'
    assert not checker().verify_tree(s, report)


def test_completion_bound_prunes_selected_owner_only_with_matching_single_candidate():
    s = completion_scene()
    report = completion_report(s)
    proof = report['tree']['nodes'][0]['proof']
    proof['candidates'] = [proof['candidates'][0]]
    report['tree']['nodes'] = [dict(prefix=[], kind='branch', children=[1, 2, 3, 4]),
        dict(prefix=[None], kind='open'), dict(prefix=['U1'], kind='assignment_prune', proof=proof),
        dict(prefix=['U2'], kind='open'), dict(prefix=['U3'], kind='open')]
    report['tree']['status'] = report['status'] = 'UNRESOLVED'
    replay = checker()
    answer = replay.replay_tree(s, report)
    assert answer['valid'] and answer['status'] == 'UNRESOLVED', answer
    assert answer['leaf_counts']['assignment_prune'] == 1
    bad = deepcopy(report)
    bad['tree']['nodes'][2]['proof']['candidates'][0]['uav'] = 'U2'
    assert not replay.verify_tree(s, bad)


def test_completion_bound_respects_fixed_original_owner_and_is_level4_only():
    s = completion_scene(committed=True)
    report = completion_report(s)
    answer = checker().replay_tree(s, report)
    assert answer['valid'] and answer['status'] == 'EMPTY', answer
    bad = deepcopy(report)
    bad['tree']['nodes'][0]['proof']['candidates'].append(dict(uav='U2', sorties=3, earliest='361/60'))
    assert not checker().verify_tree(s, bad)
    affected, _ = global_patch(s)
    local = dict(report)
    local.update(version='level3_certified_v1', patches=[])
    local.pop('scope_level')
    local.pop('tree')
    for patch in scope_family(s, 3, affected):
        tree = deepcopy(report['tree'])
        tree['patch'] = patch.to_dict()
        local['patches'].append(tree)
    assert not importlib.import_module('level3.replay').verify_tree(s, local)
