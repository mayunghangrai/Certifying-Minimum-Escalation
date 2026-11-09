from copy import deepcopy
from fractions import Fraction

import pytest

from recovery_cases import worked
from env.scenario import Scenario
from env.plan import coordinates
from env.local_scope import scope_family, scope_membership, affected_uavs, change_metrics
from env.wind_dependency import diagnose_wind_update


def revised():
    p = worked('B')
    p.update(schema_version='wind-benchmark-v2', formulation_date='2026-09-30',
             hierarchy={'helper_budget': 1, 'affected_set_rule': 'directed_incumbent_union'})
    n = len(p['wind']['time_knots_h'])-1
    for projection in ('previous', 'received'):
        p['wind'][projection]['admissible'] = [[True]*n for _ in p['wind']['cells']]
        p['wind'][projection]['coverage'] = ['forecast']*n
    return p


def test_versioned_contract_requires_explicit_policy():
    p = revised()
    assert Scenario(p).to_dict() == p
    del p['hierarchy']
    with pytest.raises(ValueError):
        Scenario(p)


def test_local_paths_and_quantities_keep_outsiders_and_assignments_fixed():
    s = Scenario(revised())
    p1, = scope_family(s, 1, {'U1'})
    p2, = scope_family(s, 2, {'U1'})
    assert p1.participants == ('U1',)
    assert p1.releases['P'] and not p1.releases['S'] and not p1.releases['L']
    assert not p2.releases['A']
    assert all(k.startswith('U1:') for a in 'SPL' for k in p2.releases[a])
    old = coordinates(s.data)
    candidate = deepcopy(old)
    candidate['A']['T1'] = 'U2'
    assert not scope_membership(s, candidate, 2, {'U1'})


def test_helper_union_is_not_a_fleet_release_mask():
    s = Scenario(revised())
    family = scope_family(s, 3, {'U1'})
    fleet = set(s.data['state']['fleet'])
    assert {frozenset(p.participants) for p in family} == {
        frozenset({'U1', u}) for u in fleet-{'U1'}}
    for patch in family:
        assert len(patch.participants) == 2
        assert all(k.split(':')[0] in patch.participants for k in patch.releases['L'])
    p = revised()
    p['hierarchy']['helper_budget'] = 0
    assert len(scope_family(Scenario(p), 3, {'U1'})[0].participants) == 1


def test_u0_uses_owned_directed_nodes_not_shared_constraint_closure():
    s = Scenario(revised())
    d = diagnose_wind_update(s)
    info = affected_uavs(s, d)
    expected = {d.graph.nodes[k].leg.split(':')[0] for k in d.structural_closure
                if d.graph.nodes[k].leg is not None}
    assert set(info['uavs']) == expected
    assert info['fraction'] == len(expected)/len(s.data['state']['fleet'])
    for uid, trace in info['traces'].items():
        assert trace[0] in d.changed_atoms
        assert d.graph.nodes[trace[-1]].leg.startswith(uid+':')
        assert all(a in d.graph.nodes[b].parents for a,b in zip(trace,trace[1:]))


def test_actual_changes_do_not_count_auxiliary_reserve_paths():
    s = Scenario(revised())
    metrics = change_metrics(s, s.data['incumbent'], {'U1'})
    assert metrics['changed_uavs'] == []
    assert metrics['preserved_uavs'] == len(s.data['state']['fleet'])
    assert metrics['outside_changed'] == 0


def test_shared_inventory_does_not_release_an_outside_uav():
    s = Scenario(revised())
    patch, = scope_family(s, 2, {'U1'})
    assert 'U2:0:y' not in patch.releases['L']
    assert 'U2:1' not in patch.releases['P']


def test_invalid_helper_budget_and_unknown_participant_rejected():
    p = revised()
    p['hierarchy']['helper_budget'] = -1
    with pytest.raises(ValueError): Scenario(p)
    with pytest.raises(ValueError): scope_family(Scenario(revised()), 3, {'ghost'})


def test_exact_membership_compares_decimal_quantities_as_rationals():
    p = revised()
    p['incumbent']['routes']['U1']['loads'][0] = .1
    s = Scenario(p)
    point = coordinates(s.data)
    point['L']['U1:0:y'] = Fraction(1,10)
    assert scope_membership(s,point,0,{'U1'})


def test_fully_committed_plan_is_held_fixed_even_at_full_release():
    from env.local_scope import preservation_metrics
    p = revised()
    c = coordinates(Scenario(p).data)
    for a in 'SPL': p['commitments'][a] = sorted(set(p['commitments'][a]) | {k for k in c[a] if k.startswith('U2:')})
    s = Scenario(p)
    metric = preservation_metrics(s,s.data['incumbent'],4,{'U1'})
    assert 'U2' in metric['held_fixed_uavs']
    assert metric['held_fixed_count'] >= 1
