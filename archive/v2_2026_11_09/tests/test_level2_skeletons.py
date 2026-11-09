"""Level-2 structure coverage against the common remaining-plan domain."""
from itertools import product

import pytest

from env.local_scope import scope_membership
from env.plan import coordinates, validate_plan
from env.scenario import Scenario
from final_benchmark.controlled import base_payload, make_plan


def scene(*, bound=4, tasks=('A',), outsiders=False):
    payload = base_payload('skeleton_coverage', [(t, [j+1, 0], None)
                           for j, t in enumerate(tasks)], [1, 1] if outsiders else [1])
    payload['mission']['vehicles'][0]['slot_bound'] = bound
    payload['incumbent'], payload['reserve_paths'] = make_plan(payload, {'U1': list(tasks)})
    return payload


def independent_plan(payload, stops):
    """Literal structural candidate used only by the independent domain oracle."""
    depot = payload['mission']['depot_xy']
    points = {t['id']: t['position_xy'] for t in payload['mission']['tasks']}
    plan = dict(assignment=dict(payload['incumbent']['assignment']), routes={})
    for uid, original in payload['incumbent']['routes'].items():
        if uid != 'U1':
            plan['routes'][uid] = original
            continue
        previous = payload['state']['fleet'][uid]['position_xy']
        paths = []
        for stop in stops:
            point = depot if stop in (None, 'DEPOT') else points[stop]
            paths.append([depot] if stop is None else [previous, point])
            previous = point
        route = dict(stops=list(stops), paths=paths,
                     deliveries=[0]*(len(stops)+1), loads=[0]*(len(stops)+1))
        for h in range(1, len(stops)+1):
            if f'{uid}:{h}' in payload['commitments']['P']:
                route['paths'][h-1] = original['paths'][h-1]
        for a, key in (('x', 'deliveries'), ('y', 'loads')):
            for h in range(len(stops)+1):
                if f'{uid}:{h}:{a}' in payload['commitments']['L']:
                    route[key][h] = original[key][h]
        plan['routes'][uid] = route
    return plan


def test_enumeration_covers_repeated_visits_depot_revisits_and_padding():
    from level2.skeletons import SkeletonDomain
    domain = SkeletonDomain(Scenario(scene()), u0={'U1'})
    assert set(domain.prefixes()) == {
        ('A', 'DEPOT', None, None),
        ('A', 'A', 'DEPOT', None), ('A', 'DEPOT', 'DEPOT', None),
        ('DEPOT', 'A', 'DEPOT', None),
        ('A', 'A', 'A', 'DEPOT'), ('A', 'A', 'DEPOT', 'DEPOT'),
        ('A', 'DEPOT', 'A', 'DEPOT'), ('A', 'DEPOT', 'DEPOT', 'DEPOT'),
        ('DEPOT', 'A', 'A', 'DEPOT'), ('DEPOT', 'A', 'DEPOT', 'DEPOT'),
        ('DEPOT', 'DEPOT', 'A', 'DEPOT'),
    }
    assert domain.children(()) == (None, 'DEPOT', 'A')
    assert domain.children(('A', 'DEPOT')) == (None, 'DEPOT', 'A')


@pytest.mark.parametrize('commitments', [
    {}, {'S': ['U1:1']}, {'P': ['U1:1']},
    {'L': ['U1:1:x']}, {'P': ['U1:4']}, {'L': ['U1:0:y']},
])
def test_complete_domain_matches_bruteforce_common_domain(commitments):
    from level2.skeletons import SkeletonDomain
    payload = scene(bound=5, tasks=('A', 'B'))
    payload['commitments'].update(commitments)
    scenario = Scenario(payload)
    domain = SkeletonDomain(scenario, u0={'U1'})
    expected = set()
    for stops in product((None, 'DEPOT', 'A', 'B'), repeat=5):
        plan = independent_plan(payload, stops)
        try:
            validate_plan(scenario.data, plan)
        except ValueError:
            continue
        expected.add(stops)
    assert set(domain.prefixes()) == expected
    for stops in expected:
        assert domain.reject(stops) is None
        assert domain.complete(stops)
        plan = domain.skeleton(stops)
        validate_plan(scenario.data, plan)
        assert scope_membership(scenario, coordinates(scenario.data, plan), 2, {'U1'})


def test_outside_uavs_and_committed_coordinates_remain_fixed():
    from level2.skeletons import SkeletonDomain
    payload = scene(outsiders=True)
    payload['commitments']['S'] = ['U1:1']
    payload['commitments']['P'] = ['U1:1']
    payload['commitments']['L'] = ['U1:1:x']
    scenario = Scenario(payload)
    domain = SkeletonDomain(scenario, u0={'U1'})
    assert domain.slots == (('U1', 1), ('U1', 2), ('U1', 3), ('U1', 4),
                            ('U2', 1), ('U2', 2), ('U2', 3))
    assert domain.children(()) == ('A',)
    for prefix in domain.prefixes():
        plan = domain.skeleton(prefix)
        assert plan['assignment'] == payload['incumbent']['assignment']
        assert plan['routes']['U2'] == payload['incumbent']['routes']['U2']
        assert plan['routes']['U1']['paths'][0] == payload['incumbent']['routes']['U1']['paths'][0]
        assert plan['routes']['U1']['deliveries'][1] == 1


def test_unassigned_tasks_have_no_route_choice():
    from level2.skeletons import SkeletonDomain
    payload = scene(tasks=('A', 'B'))
    payload['incumbent'], payload['reserve_paths'] = make_plan(payload, {'U1': ['A']})
    domain = SkeletonDomain(Scenario(payload), u0={'U1'})
    assert domain.assigned == {'U1': ('A',)}
    assert 'B' not in domain.children(())
    assert all('B' not in stops for stops in domain.prefixes())


def test_prefix_rejections_are_safe_structural_exclusions():
    from level2.skeletons import SkeletonDomain
    domain = SkeletonDomain(Scenario(scene(bound=4, tasks=('A', 'B'))), u0={'U1'})
    assert domain.reject(('A', None)) is not None
    assert domain.reject((None, 'A')) is not None
    assert domain.reject(('DEPOT', 'DEPOT')) is not None
    assert domain.reject(('A', 'B', 'DEPOT', 'A')) is not None
    assert domain.reject(('A', 'B')) is None
    assert domain.reject(('A', 'DEPOT', 'B')) is None


def test_nonconvex_direct_chord_is_kept_for_continuous_repair():
    from level2.skeletons import SkeletonDomain
    from test_continuous_recovery import nonconvex_scene
    scenario = nonconvex_scene()
    domain = SkeletonDomain(scenario, u0={'U1'})
    prefix = ('A', 'DEPOT', None, None, None, None, None, None, None)
    assert domain.reject(prefix) is None
    plan = domain.skeleton(prefix)
    with pytest.raises(ValueError, match='path leaves'):
        scenario.validate_candidate(plan)


def test_nonidle_vehicle_cannot_use_zero_slot_route():
    from level2.skeletons import SkeletonDomain
    payload = scene()
    payload['state']['fleet']['U1'].update(mode='airborne', onboard=1)
    payload['incumbent']['routes']['U1']['loads'][0] = 0
    domain = SkeletonDomain(Scenario(payload), u0={'U1'})
    assert domain.reject((None,)) is not None


def test_fixed_positive_loading_requires_nonterminal_depot_visit():
    from level2.skeletons import SkeletonDomain
    payload = scene()
    route = payload['incumbent']['routes']['U1']
    route.update(stops=['A', 'DEPOT', 'A', 'DEPOT'],
                 paths=[[[0, 0], [1, 0]], [[1, 0], [0, 0]],
                        [[0, 0], [1, 0]], [[1, 0], [0, 0]]],
                 deliveries=[0, .5, 0, .5, 0], loads=[.5, 0, .5, 0, 0])
    payload['reserve_paths']['U1']['3'] = [[1, 0], [0, 0]]
    payload['commitments']['L'] = ['U1:2:y']
    domain = SkeletonDomain(Scenario(payload), u0={'U1'})
    assert domain.reject(('A', 'A')) is not None
    assert domain.reject(('A', 'DEPOT', None)) is not None
    assert domain.reject(('A', 'DEPOT', 'A', 'DEPOT')) is None


def test_children_and_materialization_handle_complete_prefixes():
    from level2.skeletons import SkeletonDomain
    domain = SkeletonDomain(Scenario(scene()), u0={'U1'})
    prefix = ('A', 'DEPOT', None, None)
    assert domain.children(prefix) == ()
    assert not domain.complete(prefix[:-1])
    with pytest.raises(ValueError):
        domain.skeleton(prefix[:-1])
    with pytest.raises(ValueError):
        domain.children(prefix+(None,))
