"""Scope, auxiliary reserves, and sound continuous-domain conclusions."""
from copy import deepcopy
import importlib

from env.scenario import Scenario
from final_benchmark.controlled import base_payload, controlled_case, make_plan


def reserve_case():
    p = base_payload('reserve_only', [('A', [1, 0], 3)], [1, 1, 1], alpha=.2)
    p['incumbent'], p['reserve_paths'] = make_plan(p, {'U1': ['A']})
    p['reserve_paths']['U1']['1'] = [[1, 0], [2, 0], [1, 0], [0, 0]]
    for u in p['mission']['vehicles']:
        u['battery_capacity_wh'] = 6
        p['state']['fleet'][u['id']]['battery_wh'] = 6
    return Scenario(p)


def nonconvex_scene(alpha=.2):
    p = base_payload('nonconvex', [('A', [.5, 2.5], 10)], [1, 1, 1], alpha=alpha)
    depot = [2.5, .5]
    p['mission']['depot_xy'] = depot
    p['mission']['operating_region_xy'] = [[0, 0], [3, 0], [3, 1], [1, 1], [1, 3], [0, 3]]
    p['wind']['cells'] = [dict(id='BOTTOM', polygon_xy=[[0, 0], [3, 0], [3, 1], [0, 1]]),
                          dict(id='TOP', polygon_xy=[[0, 1], [1, 1], [1, 3], [0, 3]])]
    p['wind']['received']['values'] = [[[0, 0]], [[0, -alpha]]]
    p['wind']['update_support'] = [['TOP', 0]] if alpha else []
    for u in p['mission']['vehicles']:
        u['battery_capacity_wh'] = 13.2
        p['state']['fleet'][u['id']].update(position_xy=depot, battery_wh=13.2)
    p['incumbent'], p['reserve_paths'] = make_plan(p, {'U1': ['A']})
    curve = [depot, [.5, .5], [.5, 2.5]]
    p['incumbent']['routes']['U1']['paths'][:2] = [curve, list(reversed(curve))]
    p['reserve_paths']['U1']['1'] = list(reversed(curve))
    return Scenario(p)


def test_continuous_repair_can_certify_minimum_one_without_library_bypass():
    mod = importlib.import_module('continuous.search')
    s = controlled_case('C1', include_bypass=False).scenario
    r = mod.recover_continuous(s, max_seconds=10, max_proposals=0, refinements=(1,))
    assert r['full_domain']['minimum'] == 1
    assert mod.verify_continuous_evidence(s, r)
    bad = deepcopy(r)
    bad['witness']['plan']['routes']['U1']['paths'][0] = [[0, 0], [2, 0]]
    assert not mod.verify_continuous_evidence(s, bad)


def test_reserve_repair_is_level_zero_and_keeps_all_nominal_coordinates():
    mod = importlib.import_module('continuous.search')
    s = reserve_case()
    r = mod.recover_continuous(s, max_seconds=10, max_proposals=0, refinements=(1,))
    assert r['full_domain']['minimum'] == 0
    assert r['witness']['plan'] == s.to_dict()['incumbent']
    assert r['witness']['reserve_paths']['U1']['1'] != s.to_dict()['reserve_paths']['U1']['1']
    assert mod.verify_continuous_evidence(s, r)


def test_nominal_path_commitment_blocks_continuous_repair():
    check = importlib.import_module('continuous.validation').certify_witness
    p = controlled_case('C1', include_bypass=False).scenario.to_dict()
    p['commitments']['P'] = ['U1:1']
    s = Scenario(p)
    plan = deepcopy(p['incumbent'])
    plan['routes']['U1']['paths'][0] = [[0, 0], [0, .5], [2, .5], [2, 0]]
    assert not check(s, plan, p['reserve_paths'], 1)['accepted']


def test_global_level_one_exclusion_is_independently_replayed():
    mod = importlib.import_module('continuous.search')
    s = controlled_case('Cinf').scenario
    r = mod.recover_continuous(s, max_seconds=10, max_proposals=0, refinements=(1,))
    assert 1 in r['full_domain']['excluded_levels']
    assert mod.verify_continuous_evidence(s, r)
    bad = deepcopy(r)
    bad['exclusions'][0]['earliest'] = '1000'
    assert not mod.verify_continuous_evidence(s, bad)


def test_exhausted_proposals_leave_an_unproved_level_unresolved():
    mod = importlib.import_module('continuous.search')
    s = controlled_case('C2').scenario
    r = mod.recover_continuous(s, max_seconds=10, max_proposals=0, refinements=(1,))
    assert r['full_domain']['minimum'] is None
    assert r['full_domain']['upper'] is None
    assert 2 not in r['full_domain']['excluded_levels']
    assert mod.verify_continuous_evidence(s, r)


def test_unsupported_depot_coupling_cannot_certify_global_infeasibility():
    mod = importlib.import_module('continuous.search')
    p = controlled_case('Cinf').scenario.to_dict()
    p['operations']['depot_bays'] = 1
    s = Scenario(p)
    r = mod.recover_continuous(s, max_seconds=10, max_proposals=0)
    assert r['full_domain']['status'] == 'unresolved'
    assert r['unsupported'] == 'coupled depot preparation'
    assert r['full_domain']['excluded_levels'] == []


def test_sequence_proposals_can_certify_a_level_two_witness():
    mod = importlib.import_module('continuous.search')
    s = controlled_case('C2').scenario
    r = mod.recover_continuous(s, max_seconds=10, max_proposals=30, refinements=(1,))
    assert r['full_domain']['minimum'] == 2
    assert mod.verify_continuous_evidence(s, r)


def test_already_feasible_incumbent_needs_no_path_optimization(monkeypatch):
    mod = importlib.import_module('continuous.search')
    def unexpected(*args, **kwargs):
        raise AssertionError('a validated existing witness needs no geometry search')
    monkeypatch.setattr(mod.ContinuousOracle, 'query', unexpected)
    s = controlled_case('C0').scenario
    r = mod.recover_continuous(s, max_seconds=10)
    assert r['full_domain']['minimum'] == 0
    assert r['effort']['oracle']['queries'] == 0


def test_nonconvex_region_retains_unresolved_evidence_without_aborting():
    mod = importlib.import_module('continuous.search')
    s = nonconvex_scene()
    r = mod.recover_continuous(s, max_seconds=10, max_proposals=0)
    assert r['full_domain']['status'] == 'unresolved'
    assert mod.verify_continuous_evidence(s, r)


def test_feasible_assignment_candidate_is_checked_before_geometry_search(monkeypatch):
    mod = importlib.import_module('continuous.search')
    original = mod.continuous_plan
    def checked(scenario, oracle, plan, released, **kwargs):
        seq = {uid: [i for i in r['stops'] if i not in (None, 'DEPOT')] for uid, r in plan['routes'].items()}
        _, reserves = make_plan(scenario.to_dict(), seq)
        feasible = importlib.import_module('continuous.validation').certify_witness(scenario, plan, reserves, 4)['accepted']
        if plan['assignment'] != scenario.to_dict()['incumbent']['assignment'] and feasible:
            raise AssertionError('a feasible direct assignment candidate needs no path search')
        return original(scenario, oracle, plan, released, **kwargs)
    monkeypatch.setattr(mod, 'continuous_plan', checked)
    s = controlled_case('C3').scenario
    r = mod.recover_continuous(s, max_seconds=10, max_proposals=120, refinements=(1,))
    assert r['full_domain']['minimum'] == 3


def test_deadline_proof_skips_vehicles_with_no_deadline_and_feasible_horizon(monkeypatch):
    mod = importlib.import_module('continuous.search')
    p = base_payload('critical_prefix', [('A', [1, 1], None), ('B', [1, 0], 1.1)], [1, 1, 1], alpha=.2)
    p['incumbent'], p['reserve_paths'] = make_plan(p, {'U1': ['A'], 'U2': ['B']})
    s = Scenario(p)
    oracle = mod.ContinuousOracle(s, refinements=(1,))
    original = oracle.query
    def critical(uid, *args, **kwargs):
        assert uid == 'U2', 'irrelevant vehicle exhausted the critical proof budget'
        return original(uid, *args, **kwargs)
    monkeypatch.setattr(oracle, 'query', critical)
    cert = mod.deadline_certificate(s, 1, oracle)
    assert cert['uav'] == 'U2'
    assert mod.verify_deadline_certificate(s, cert)


def test_capacity_impossible_candidate_is_skipped_before_path_optimization(monkeypatch):
    mod = importlib.import_module('continuous.search')
    p = controlled_case('C3').scenario.to_dict()
    p['mission']['vehicles'][1]['payload_capacity_kg'] = 1.5
    s = Scenario(p)
    original = mod.continuous_plan
    def possible(scenario, oracle, plan, released, **kwargs):
        assert plan['routes']['U2']['loads'][0] <= 1.5, 'geometry cannot repair a fixed excess loading'
        return original(scenario, oracle, plan, released, **kwargs)
    monkeypatch.setattr(mod, 'continuous_plan', possible)
    r = mod.recover_continuous(s, max_seconds=10, max_proposals=120, refinements=(1,))
    assert r['full_domain']['minimum'] == 3
