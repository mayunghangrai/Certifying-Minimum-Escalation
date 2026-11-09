from copy import deepcopy
from fractions import Fraction

import pytest

from env.scenario import Scenario
from final_benchmark.controlled import controlled_case
from recovery.local_search import previous_premise, verify_local_witness
from recovery.representation import PathLibrary


def test_static_path_screen_finds_a_detour_and_certifies_only_the_representation():
    from recovery.static_paths import static_path_screen, verify_static_certificate
    c = controlled_case('C1')
    zero = static_path_screen(c.scenario, c.library, 0)
    assert zero['status'] == 'EMPTY'
    assert zero['certificate']['domain'] == 'represented'
    assert verify_static_certificate(c.scenario, c.library, zero['certificate'])
    one = static_path_screen(c.scenario, c.library, 1)
    assert one['status'] == 'WITNESS'
    check = verify_local_witness(c.scenario, c.library, one['plan'], one['reserves'], 1)
    assert check['accepted'] and check['exact'] and check['level'] == 1
    bad = deepcopy(zero['certificate']); bad['level'] = 1
    assert not verify_static_certificate(c.scenario, c.library, bad)


def test_static_path_screen_guards_time_variation_and_bay_coupling():
    from recovery.static_paths import static_path_screen
    p = controlled_case('C0').scenario.to_dict()
    p['operations']['depot_bays'] = 1
    s = Scenario(p)
    assert static_path_screen(s, PathLibrary.build(s), 1)['status'] == 'UNRESOLVED'
    p['operations']['depot_bays'] = None
    p['wind']['time_knots_h'] = [0, 10, 20]
    for projection in ('previous', 'received'):
        for field in ('values', 'admissible'):
            p['wind'][projection][field] = [row * 2 for row in p['wind'][projection][field]]
        p['wind'][projection]['coverage'] = ['forecast'] * 2
    p['wind']['received']['values'][1][1] = [0, 0]
    s = Scenario(p)
    assert static_path_screen(s, PathLibrary.build(s), 1)['status'] == 'UNRESOLVED'


@pytest.mark.parametrize('family', ['uniform', 'clustered'])
def test_near_boundary_pairs_are_exact_reproducible_and_conditioned_on_local_exposure(family):
    from final_benchmark.near_boundary import near_boundary_pair
    from recovery.physical_proofs import physical_certificate
    from env.local_scope import affected_uavs
    from env.wind_dependency import diagnose_wind_update
    a, meta = near_boundary_pair(6, 3, family, 31001)
    b, repeated = near_boundary_pair(6, 3, family, 31001)
    assert [c.scenario.content_hash() for c in a] == [c.scenario.content_hash() for c in b]
    assert meta == repeated
    assert len(a) == 2 and meta['attempts']
    assert meta['selection_uses_recovery_labels'] is False
    assert meta['boundary_type'] == 'incumbent_deadline'
    lower, upper = a
    for c in a:
        assert previous_premise(c.scenario)['exact_feasible']
        assert 0 < affected_uavs(c.scenario, diagnose_wind_update(c.scenario))['count'] <= 1
    assert physical_certificate(lower.scenario, 0) is not None
    up = upper.scenario.to_dict()
    check = verify_local_witness(upper.scenario, upper.library, up['incumbent'], up['reserve_paths'], 0)
    assert check['accepted'] and check['exact']
    t0, t1 = Fraction(meta['previous_delivery']), Fraction(meta['updated_delivery'])
    deadline = lambda c: Fraction(str(next(t['deadline_h'] for t in c.scenario.data['mission']['tasks'] if t['id'] == meta['critical_task'])))
    assert t0 < deadline(lower) < t1 < deadline(upper)
    lp, hp = lower.scenario.to_dict(), upper.scenario.to_dict()
    lp['benchmark_id'] = hp['benchmark_id']
    next(t for t in lp['mission']['tasks'] if t['id'] == meta['critical_task'])['deadline_h'] = float(deadline(upper))
    assert lp == hp


def test_generation_failure_is_explicit_and_has_an_attempt_ledger():
    from final_benchmark.near_boundary import near_boundary_pair
    cases, meta = near_boundary_pair(3, 3, 'uniform', 31001, max_attempts=0)
    assert cases == ()
    assert meta['status'] == 'generation_failed'
    assert meta['attempts'] == []


def test_unsupported_alternative_prevents_static_exclusion():
    from recovery.static_paths import static_path_screen
    c = controlled_case('C2')
    # An irrational detour length has no exact ordering against the other paths.
    library = PathLibrary.build(c.scenario, nominal_paths=[[[0, 0], [.1, .3], [1, 0]]])
    assert static_path_screen(c.scenario, library, 1)['status'] == 'UNRESOLVED'


def test_static_screen_respects_committed_paths():
    from recovery.static_paths import static_path_screen
    p = controlled_case('C1').scenario.to_dict()
    p['commitments']['P'] = ['U1:1']
    s = Scenario(p)
    library = PathLibrary.build(s, nominal_paths=[[[0, 0], [0, .5], [2, .5], [2, 0]]])
    assert static_path_screen(s, library, 1)['status'] == 'EMPTY'


@pytest.mark.parametrize('case_name,level', [('C0', 0), ('C1', 1), ('C2', 2), ('C3', 3), ('C4', 4)])
def test_generic_near_search_replays_certificates_without_supplied_witnesses(case_name, level):
    from final_benchmark.near_search import recover_near_boundary
    from recovery.local_search import verify_local_evidence
    c = controlled_case(case_name)
    result = recover_near_boundary(c.scenario, c.library, max_seconds=15, max_proposals=300)
    assert result['represented']['minimum'] == level
    assert result['full_domain']['minimum'] == level
    assert verify_local_evidence(c.scenario, c.library, result)
    if result['witness']:
        assert result['witness']['source'] != 'supplied_and_independently_checked'


def test_zero_proposals_and_represented_exclusion_cannot_prove_full_infeasibility():
    from final_benchmark.near_search import recover_near_boundary
    from recovery.local_search import verify_local_evidence
    c = controlled_case('C1', include_bypass=False)
    r = recover_near_boundary(c.scenario, c.library, max_proposals=0, max_seconds=0)
    assert r['represented']['minimum'] == 'infinity'
    assert r['full_domain']['minimum'] is None
    assert r['represented']['excluded_levels'] == [0, 1, 2, 3, 4]
    assert r['full_domain']['excluded_levels'] == [0]
    assert verify_local_evidence(c.scenario, c.library, r)
    r['static_certificates'][0]['failure'] = {}
    assert not verify_local_evidence(c.scenario, c.library, r)


def test_heuristic_exhaustion_alone_is_not_an_exclusion():
    from final_benchmark.near_search import recover_near_boundary
    c = controlled_case('C2')
    r = recover_near_boundary(c.scenario, c.library, max_seconds=0, max_proposals=0)
    assert r['represented']['minimum'] is None and r['represented']['upper'] is None
    assert r['represented']['excluded_levels'] == [0, 1]
    assert r['witness'] is None


def test_near_records_are_immutable_and_summaries_separate_constructed_controls(tmp_path):
    from final_benchmark.cli import run_near
    from final_benchmark.records import RunStore
    from final_benchmark.near_boundary import summarize_near
    from final_benchmark.analysis import load_records
    config = dict(study='near_boundary', phase='development', sizes=[[3, 3]], families=['uniform'],
                  seeds=[31001], offset='1/10', max_attempts=48,
                  budget=dict(max_seconds=0, max_proposals=0))
    store = RunStore(tmp_path, config)
    run_near(store, config)
    before = {p.name: p.read_bytes() for p in (tmp_path/'records').glob('*.json')}
    run_near(store, config)
    assert before == {p.name: p.read_bytes() for p in (tmp_path/'records').glob('*.json')}
    summary = summarize_near(tmp_path)
    assert summary['sampling']['requested_bases'] == 1
    assert summary['sampling']['accepted_bases'] == 1
    assert summary['above']['represented']['certified']['0'] == 1
    assert summary['below']['represented']['certified']['0'] == 0
    assert len(load_records(tmp_path)) == 2
    # Seeded strata share random draws: report finite-panel counts and
    # identification bounds, without an independence-based sampling CI.
    assert 'represented_certified_frequency_cluster_bootstrap_95' not in summary['below']
    assert 'represented_proof_s' in summary['below']['effort_components_s']
    from final_benchmark.cli import main
    main(['summarize', '--output', str(tmp_path)])
    import json
    saved = json.loads((tmp_path/'summary.json').read_text())
    assert saved['population'] == summary['population']


def test_fixed_sequence_anchor_brackets_the_represented_path_repair_boundary():
    from final_benchmark.near_boundary import near_boundary_pair
    from recovery.static_paths import static_path_screen
    cases, meta = near_boundary_pair(6, 3, 'uniform', 31001, anchor='fixed_sequence')
    assert len(cases) == 2
    assert meta['boundary_type'] == 'represented_fixed_sequence_deadline'
    assert Fraction(meta['boundary_delivery']) <= Fraction(meta['updated_delivery'])
    assert static_path_screen(cases[0].scenario, cases[0].library, 1)['status'] == 'EMPTY'
    assert static_path_screen(cases[1].scenario, cases[1].library, 1)['status'] == 'WITNESS'
    assert all(previous_premise(c.scenario)['exact_feasible'] for c in cases)


def test_represented_route_relaxation_can_certify_assignment_change_is_needed():
    from recovery.represented_proofs import represented_deadline_certificate, verify_represented_certificate
    c = controlled_case('C3')
    cert = represented_deadline_certificate(c.scenario, c.library, 2)
    assert cert is not None and cert['domain'] == 'represented'
    assert verify_represented_certificate(c.scenario, c.library, cert)
    assert represented_deadline_certificate(c.scenario, c.library, 3) is None
    # A represented exclusion is never silently promoted to the full domain.
    cert['domain'] = 'full_domain'
    assert not verify_represented_certificate(c.scenario, c.library, cert)


def test_route_relaxation_includes_concatenated_paths_through_other_task_locations():
    from recovery.represented_proofs import represented_deadline_certificate
    p = controlled_case('C1', include_bypass=False).scenario.to_dict()
    for name, point in [('B', [0, .5]), ('D', [2, .5])]:
        p['mission']['tasks'].append(dict(id=name,position_xy=point,demand=1,mandatory=0,deadline_h=None))
        p['state']['cumulative_delivered'][name] = 0
        p['incumbent']['assignment'][name] = None
    # The single depot-C edge misses the deadline, but depot-B-D-C meets it.
    # Intermediate visits to unassigned B/D are allowed by the relaxation.
    s = Scenario(p)
    library = PathLibrary.build(s, nominal_paths=[[[0, 0], [0, .5]], [[0, .5], [2, .5]], [[2, .5], [2, 0]]], direct=False)
    assert represented_deadline_certificate(s, library, 2) is None


def test_later_physical_proof_preserves_the_first_certificate_time():
    from time import perf_counter
    from final_benchmark.controlled import controlled_record, add_physical_certificate
    from recovery.physical_proofs import physical_certificate
    c = controlled_case('C3')
    report = controlled_record(c)
    original = {key:report['effort'][key] for key in ('represented_certificate_s','full_domain_certificate_s')}
    add_physical_certificate(report, c.scenario, physical_certificate(c.scenario,2), clock_start=perf_counter())
    assert {key:report['effort'][key] for key in original} == original
