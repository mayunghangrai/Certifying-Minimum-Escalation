import copy
import itertools
import pytest
from env.scenario import Scenario
from test_benchmark_contract import raw


def setup():
    return Scenario.from_dict(raw())


def test_release_table_includes_quantities_at_level_two_and_preserves_commitments():
    from env.intervention_scope import release_sets
    from env.plan import coordinates
    s=setup(); coords=coordinates(s.data)
    mutable={a:set(coords[a])-set(s.data['commitments'][a]) for a in coords}
    releases=[release_sets(s,k,{'A'},{'coupling':{'A','C'}}) for k in range(5)]
    assert releases[0]=={a:frozenset() for a in coords}
    assert releases[1]=={'A':frozenset(),'S':frozenset(),'P':mutable['P'],'L':frozenset()}
    assert releases[2]=={'A':frozenset(),'S':mutable['S'],'P':mutable['P'],'L':mutable['L']}
    assert releases[3]['A']=={'A'}
    assert releases[4]==mutable
    for low,high in zip(releases,releases[1:]):
        assert all(low[a]<=high[a] for a in coords)
    for r in releases:
        assert all(not r[a]&set(s.data['commitments'][a]) for a in coords)


def test_path_release_uses_curve_identity_and_release_does_not_require_change():
    from env.intervention_scope import check_scope
    s=setup(); p=s.to_dict()['incumbent']
    p['routes']['U1']['paths'][0]=[[1,1],[5,1],[9,1]]
    assert check_scope(s,p,0).allowed
    p['routes']['U1']['paths'][0]=[[1,1],[5,2],[9,1]]
    assert not check_scope(s,p,0).allowed
    assert check_scope(s,p,1).allowed  # First destination is committed, path is not.
    assert all(check_scope(s,s.data['incumbent'],k).allowed for k in range(5))


def test_quantity_change_needs_level_two_even_without_resequencing():
    from env.intervention_scope import check_scope
    s=setup(); p=s.to_dict()['incumbent']
    p['routes']['U1']['loads'][0]+=0.25
    assert not check_scope(s,p,1).allowed
    assert check_scope(s,p,2).allowed


def test_resequence_and_padding_changes_are_fixed_coordinate_decisions():
    from env.intervention_scope import check_scope
    p=raw(); p['commitments']['S'].remove('U1:1'); s=Scenario.from_dict(p)
    candidate=copy.deepcopy(p['incumbent'])
    candidate['routes']['U1']={'stops':['A','DEPOT',None,None,None],
        'paths':[[[1,1],[9,1]],[[9,1],[1,1]],[[1,1]],[[1,1]],[[1,1]]],
        'deliveries':[0.,3.,0.,0.,0.,0.], 'loads':[3.,0.,0.,0.,0.,0.]}
    assert not check_scope(s,candidate,1).allowed
    assert check_scope(s,candidate,2).allowed


def test_level_three_assignment_is_neighborhood_only_and_level_four_is_not_override():
    from env.intervention_scope import check_scope
    s=setup(); p=s.to_dict()['incumbent']
    # Removing B's visit/nulling assignment is structural but fails mandatory service.
    p['assignment']['B']=None
    p['routes']['U2']['stops'][2]='C'
    p['routes']['U2']['paths'][2]=[[1,1],[3,5]]
    p['routes']['U2']['paths'][3]=[[3,5]]
    assert not check_scope(s,p,2).allowed
    assert not check_scope(s,p,3,affected_tasks={'A'},task_supports={}).allowed
    assert check_scope(s,p,3,affected_tasks={'B'},task_supports={}).allowed
    assert check_scope(s,p,4).allowed
    p['routes']['U2']['deliveries'][1]=.4
    assert not check_scope(s,p,4).allowed


def test_task_closure_keeps_committed_bridge_until_after_closure():
    from env.intervention_scope import task_closure, reassignment_neighborhood
    tasks={'a','bridge','b','isolated'}
    supports={'g1':{'a','bridge'},'g2':{'bridge','b'}}
    assert task_closure(tasks,{'a'},supports)=={'a','bridge','b'}
    assert reassignment_neighborhood(tasks,{'a'},supports,{'a','b','isolated'})=={'a','b'}
    assert task_closure(tasks,{'isolated'},supports)=={'isolated'}
    assert task_closure(tasks,set(),supports)==set()


def test_exhaustive_small_graph_closure_is_least_closed_superset():
    from env.intervention_scope import task_closure
    tasks={'a','b','c'}
    subsets=[set(c) for n in range(4) for c in itertools.combinations(sorted(tasks),n)]
    for left,right,seeds in itertools.product(subsets,repeat=3):
        supports={'g1':left,'g2':right}
        closure=task_closure(tasks,seeds,supports)
        closed_supersets=[s for s in subsets if seeds<=s and all(not s&t or t<=s for t in supports.values())]
        assert closure==set.intersection(*closed_supersets)


def test_conservative_domain_supports_allow_adjacent_equalities():
    from env.intervention_scope import constraint_task_supports, release_sets
    s=setup(); supports=constraint_task_supports(s)
    assert supports['inventory']=={'A','B','C'}
    assert 'depot_bays' in supports
    assert release_sets(s,3,{'A'})==release_sets(s,4)
    assert release_sets(s,3,set())==release_sets(s,2)


@pytest.mark.parametrize('level',[True,1.5,'1',-1,5])
def test_scope_requires_one_of_five_integer_levels(level):
    from env.intervention_scope import release_sets
    with pytest.raises(ValueError): release_sets(setup(),level)


def test_unknown_seed_support_or_mutable_coordinate_cannot_silently_change_closure():
    from env.intervention_scope import task_closure, reassignment_neighborhood
    with pytest.raises(ValueError): task_closure({'A'},{'missing'},{})
    with pytest.raises(ValueError): task_closure({'A'},{'A'},{'g':{'missing'}})
    with pytest.raises(ValueError): reassignment_neighborhood({'A'},{'A'},{},{'missing'})


def test_json_integral_slot_bound_remains_usable_in_scope_construction():
    from env.intervention_scope import release_sets
    p=raw(); p['mission']['vehicles'][0]['slot_bound']=5.0
    assert release_sets(Scenario.from_dict(p),2)==release_sets(setup(),2)
