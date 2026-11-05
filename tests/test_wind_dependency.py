import json

import pytest

from env.scenario import Scenario
from recovery_cases import diagnostic_cases


def diagnose(name, **kwargs):
    from env.wind_dependency import diagnose_wind_update
    return diagnose_wind_update(Scenario.from_dict(diagnostic_cases()[name]), **kwargs)


def test_irrelevant_atoms_are_isolated_and_do_not_seed_reassignment():
    r = diagnose('irrelevant_wind')
    assert len(r.changed_atoms) == 1
    assert not r.relevant_atoms and not r.structural_closure
    assert not r.affected_tasks and not r.neighborhood
    assert not r.operational_support


def test_structural_dependence_is_not_pruned_by_numerical_cancellation_or_tolerance():
    r = diagnose('unchanged_speed')
    assert r.structural_closure and r.material_support
    assert not r.operational_support
    assert r.affected_tasks == {'T1','T2'}  # Direct contact remains reportable.
    assert r.neighborhood == {'T1','T2','T3','T4'}
    wide = diagnose('downstream', tolerances={'time_h':100., 'energy_wh':100.})
    narrow = diagnose('downstream')
    assert wide.structural_closure == narrow.structural_closure
    assert wide.graph.edges == narrow.graph.edges


def test_downstream_leg_outside_changed_cells_is_affected_through_entering_state():
    r = diagnose('downstream')
    last = r.legs['U2:5']
    assert not last['direct'] and last['propagated'] and last['material'] and last['affected']
    assert {q[0] for q in last['query_support']} == {'L'}
    assert 'C' in r.affected_tasks


def test_union_contains_queries_only_used_after_time_bin_shift():
    r = diagnose('shifted_bins')
    first = r.legs['U1:1']
    assert ['east',1] not in first['nominal_queries_previous']
    assert ['east',1] in first['nominal_queries_received']
    assert ['east',1] in first['query_support']
    assert any(n.name == 'time_bin_selection' and n.previous != n.received
               for n in r.graph.nodes.values())


def test_reserve_only_contact_does_not_advance_or_modify_nominal_states():
    r = diagnose('reserve_only')
    assert r.previous.records == r.received.records
    assert r.received.status == 'unresolved'
    assert r.affected_tasks == {'T1'}
    assert r.legs['U1:1']['direct']
    assert not r.legs['U1:2']['propagated']
    check = r.received.reserve_checks['reserve:U1:1']
    assert check['flight_status'] == 'late' and check['margin_wh'] is None
    assert any(n.leg == 'U1:1' and n.role == 'reserve' and key in r.operational_support
               for key,n in r.graph.nodes.items())


def test_initial_reserve_contact_is_attributed_only_to_first_leg():
    from env.wind_dependency import diagnose_wind_update
    p = diagnostic_cases()['reserve_only']
    p['reserve_paths']['U1'] = {'initial':[[0,0],[-1,0],[0,0]], '1':[[1,0],[0,0]]}
    r = diagnose_wind_update(Scenario.from_dict(p))
    assert r.previous.records == r.received.records
    assert r.legs['U1:1']['direct'] and r.legs['U1:1']['material']
    assert not r.legs['U1:2']['direct'] and not r.legs['U1:2']['propagated']
    assert any(n.role == 'initial_reserve' and n.leg == 'U1:1'
               for key,n in r.graph.nodes.items() if key in r.operational_support)


def test_old_only_time_bin_queries_remain_in_contact_union():
    from env.wind_dependency import diagnose_wind_update
    p = diagnostic_cases()['shifted_bins']
    p['wind']['previous']['values'],p['wind']['received']['values'] = p['wind']['received']['values'],p['wind']['previous']['values']
    p['mission']['tasks'][0]['deadline_h'] = 3.
    r = diagnose_wind_update(Scenario.from_dict(p))
    first = r.legs['U1:1']
    assert ['east',1] in first['nominal_queries_previous']
    assert ['east',1] not in first['nominal_queries_received']
    assert ['east',1] in first['query_support'] and first['direct']


def test_late_ground_preserves_known_arrival_checks_and_inactive_predicates():
    from env.wind_dependency import diagnose_wind_update
    from recovery_cases import worked
    p = worked('B')
    p['operations']['service_duration_h'] = 1.6
    p['wind']['received']['values'][1][0] = [-.6,0.]
    for task in p['mission']['tasks']: task['deadline_h'] = 4.
    r = diagnose_wind_update(Scenario.from_dict(p))
    assert r.received.records['U1'][1]['arrival_h'] == 2.5
    assert r.received.records['U1'][1]['delivery_h'] is None
    checks = r.graph.nodes['U1:1:resources'].received
    assert checks['battery:U1:1:arrival'] == 'passed'
    assert checks['battery:U1:1:service'] == 'unavailable'
    assert checks['depot_arrival_reserve:U1:1'] == 'inactive'
    assert r.graph.nodes['U1:1:ground_guard'].received == 'late'
    assert r.graph.nodes['U1:2:ground_guard'].received is None


def test_late_suffix_retains_conservative_queries_and_explicit_undefined_values():
    r = diagnose('late_undefined')
    assert not r.received.complete
    assert r.legs['U1:4']['conservative_queries_received']
    assert r.legs['U1:4']['affected']
    assert any(n.name == 'horizon_guard' and n.previous != n.received
               for n in r.graph.nodes.values())
    assert any(n.received is None and n.previous is not None
               for key,n in r.graph.nodes.items() if key in r.material_support)
    json.dumps(r.to_dict(), allow_nan=False)


@pytest.mark.parametrize('name', list(diagnostic_cases()))
def test_dag_has_only_forward_edges_and_outside_closure_invariance(name):
    r = diagnose(name)
    seen = set()
    for key,n in r.graph.nodes.items():
        assert set(n.parents) <= seen
        seen.add(key)
        if key not in r.structural_closure and n.kind != 'change':
            assert n.previous == n.received, key
    for parent,child in r.graph.edges:
        a,b = r.graph.nodes[parent], r.graph.nodes[child]
        if a.kind == 'change': assert b.kind == 'wind'
        if a.leg and b.leg:
            assert a.leg.split(':')[0] == b.leg.split(':')[0]
