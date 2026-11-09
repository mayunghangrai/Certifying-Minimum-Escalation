from fractions import Fraction
from itertools import permutations

import pytest

from env.scenario import Scenario
from env.fixed_plan import evaluate_plan
from env.intervention_scope import check_scope, release_sets, constraint_task_supports
from env.wind_dependency import diagnose_wind_update
from recovery_cases import worked, permutation


@pytest.mark.parametrize('case,expected', [('A',{'T1','T2'}),('B',{'T1','T2','T3','T4'})])
def test_manuscript_locality_and_global_collapse_are_derived(case,expected):
    s = Scenario.from_dict(worked(case))
    d = diagnose_wind_update(s)
    assert d.affected_tasks == {'T1','T2'}
    assert d.neighborhood == expected
    supports = constraint_task_supports(s)
    assert not supports['inventory']  # Every load is committed.
    releases = [release_sets(s,k,d.affected_tasks) for k in range(5)]
    assert (releases[3] == releases[4]) == (case == 'B')


@pytest.mark.parametrize('case,structural,feasible,pre_count',[
    ('A',[1,1,1,2,4],[0,0,0,1,2],4), ('B',[1,1,1,24,24],[0,0,0,6,6],24)])
def test_finite_worked_permutations_match_manuscript_counts(case,structural,feasible,pre_count):
    p = worked(case); s = Scenario.from_dict(p); d = diagnose_wind_update(s)
    observed_structure, observed_feasible, previous = [0]*5,[0]*5,0
    for order in permutations(range(1,5)):
        candidate,paths = permutation(p,order)
        try: s.validate_candidate(candidate)
        except ValueError: continue
        previous += evaluate_plan(s,candidate,projection='previous',reserve_paths=paths).status == 'feasible'
        good = evaluate_plan(s,candidate,reserve_paths=paths).status == 'feasible'
        for k in range(5):
            if check_scope(s,candidate,k,affected_tasks=d.affected_tasks).allowed:
                observed_structure[k] += 1
                observed_feasible[k] += good
    assert observed_structure == structural
    assert observed_feasible == feasible and previous == pre_count


def test_imported_east_exchange_matches_exact_delivery_return_energy_records():
    p = worked('A'); s = Scenario.from_dict(p); candidate,paths = permutation(p,[2,1,3,4])
    r = evaluate_plan(s,candidate,reserve_paths=paths)
    assert r.status == 'feasible'
    for u,delivery,end,energy in [('U1','2','8/3','7/15'),('U2','2/3','16/15','26/75'),
                                  ('U3','1','2','3/10'),('U4','1','2','3/10')]:
        assert r.records[u][1]['delivery_h'] == pytest.approx(float(Fraction(delivery)))
        assert r.final_states[u]['time_h'] == pytest.approx(float(Fraction(end)))
        assert 10-r.final_states[u]['battery_wh'] == pytest.approx(float(Fraction(energy)))


def test_uncommitted_load_preserves_genuine_inventory_coupling():
    p = worked('A')
    p['commitments']['L'] = [k for k in p['commitments']['L'] if not k.endswith(':0:y')]
    s = Scenario.from_dict(p)
    assert constraint_task_supports(s)['inventory'] == {'T1','T2','T3','T4'}
    assert diagnose_wind_update(s).neighborhood == {'T1','T2','T3','T4'}
