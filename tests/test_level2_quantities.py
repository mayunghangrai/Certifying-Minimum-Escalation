"""Rational quantities must prove mission feasibility without decimal sums."""
from copy import deepcopy
from fractions import Fraction as F
import importlib

import pytest

from env.scenario import Scenario
from env.local_scope import scope_family
from final_benchmark.controlled import base_payload, make_plan
from recovery.local_search import digest


def api():
    try:
        return importlib.import_module('level2.quantities')
    except ModuleNotFoundError:
        pytest.fail('Level-2 exact quantity evaluator is missing')


def scene(*, repeated=False, deadline=None, mandatory=.3, payload=1):
    p = base_payload('quantity_exact', [('A', [1, 0], deadline)], [1], alpha=.2)
    p['mission']['vehicles'][0].update(slot_bound=4, payload_capacity_kg=payload)
    p['mission']['tasks'][0].update(demand=mandatory, mandatory=mandatory)
    p['state']['depot_stock'] = mandatory
    p['incumbent'], p['reserve_paths'] = make_plan(p, {'U1': ['A']})
    if repeated:
        p['incumbent']['routes']['U1'] = dict(stops=['A', 'DEPOT', 'A', 'DEPOT'],
            paths=[[[0, 0], [1, 0]], [[1, 0], [0, 0]]]*2,
            loads=[0, 0, 0, 0, 0], deliveries=[0, 0, 0, 0, 0])
        p['reserve_paths']['U1']['3'] = [[1, 0], [0, 0]]
    return Scenario(p)


def releases(s):
    return scope_family(s, 2, ['U1'])[0].releases


def lower(s):
    p = s.to_dict()
    return {('U1', tuple(path[0]), tuple(path[-1])): F(0)
            for path in [*p['incumbent']['routes']['U1']['paths'],
                         *p['reserve_paths']['U1'].values()]}


def evaluate(s, **kw):
    p = s.to_dict()
    return api().evaluate_quantities(s, p['incumbent'], p['reserve_paths'], releases(s), **kw)


def test_fractional_splits_replay_exactly_when_float_sum_exceeds_demand():
    s = scene(repeated=True, payload=.2)
    p = s.to_dict()
    p['incumbent']['routes']['U1']['deliveries'][1] = .1
    p['commitments']['L'] = ['U1:1:x']
    s = Scenario(p)
    r = evaluate(s)
    assert r['status'] == 'WITNESS'
    w = r['witness']
    assert w['plan']['routes']['U1']['deliveries'][1:4:2] == [.1, .2]
    assert api().verify_quantity_witness(s, w, releases(s))


def test_inactive_slots_remain_zero_and_do_not_become_quantity_columns():
    s = scene()
    r = evaluate(s)
    assert r['status'] == 'WITNESS'
    w = r['witness']
    assert w['columns'] == [['U1', 0, 'y'], ['U1', 1, 'x']]
    assert w['plan']['routes']['U1']['loads'][2:] == [0, 0, 0]
    assert w['plan']['routes']['U1']['deliveries'][2:] == [0, 0, 0]
    assert api().verify_quantity_witness(s, w, releases(s))


def test_repeated_late_visit_can_have_exactly_zero_delivery():
    s = scene(repeated=True, deadline=1.5, mandatory=.2, payload=.2)
    r = evaluate(s)
    assert r['status'] == 'WITNESS'
    assert r['witness']['plan']['routes']['U1']['deliveries'][3] == 0
    assert api().verify_quantity_witness(s, r['witness'], releases(s))


def test_lower_quantity_infeasibility_has_replayable_farkas_certificate():
    s = scene(mandatory=.3, payload=.2)
    durations = lower(s)
    r = evaluate(s, lower_durations=durations)
    assert r['status'] == 'EMPTY'
    assert r['proof']['kind'] == 'quantity_farkas_v1'
    p = s.to_dict()
    assert api().verify_quantity_exclusion(s, p['incumbent'], p['reserve_paths'],
                                          releases(s), durations, r['proof'])
    bad = deepcopy(r['proof'])
    bad['certificate']['multipliers'] = {'0': '-1'}
    assert not api().verify_quantity_exclusion(s, p['incumbent'], p['reserve_paths'],
                                              releases(s), durations, bad)


def test_upper_path_infeasibility_never_excludes_continuous_path_domain():
    s = scene(deadline=.5)
    r = evaluate(s)
    assert r['status'] == 'UNRESOLVED'
    assert r['proof'] is None
    optimistic = evaluate(s, lower_durations=lower(s))
    assert optimistic['status'] == 'WITNESS'
    assert optimistic['relaxation'] and optimistic['witness'] is None


def test_lower_ground_horizon_rejection_has_exact_replay():
    s = scene(repeated=True)
    p = s.to_dict()
    p['mission']['horizon_h'] = 1
    p['wind']['time_knots_h'] = [0, 1]
    p['operations']['service_duration_h'] = .6
    s = Scenario(p)
    durations = lower(s)
    r = evaluate(s, lower_durations=durations)
    assert r['status'] == 'EMPTY'
    assert r['proof']['kind'] == 'quantity_ground_rejection_v1'
    assert api().verify_quantity_exclusion(s, p['incumbent'], p['reserve_paths'],
                                          releases(s), durations, r['proof'])
    bad = deepcopy(r['proof'])
    bad['reason'] = 'depot_bays'
    assert not api().verify_quantity_exclusion(s, p['incumbent'], p['reserve_paths'],
                                              releases(s), durations, bad)


@pytest.mark.parametrize('mutation', ['value', 'projection', 'unreleased', 'digits', 'columns'])
def test_forged_quantity_witness_is_rejected(mutation):
    s = scene()
    p = s.to_dict()
    p['commitments']['L'] = ['U1:1:x']
    s = Scenario(p)
    r = evaluate(s)
    assert r['status'] == 'WITNESS'
    w = deepcopy(r['witness'])
    if mutation == 'value': w['values'][0] = '0'
    elif mutation == 'projection': w['plan']['routes']['U1']['loads'][0] = .4
    elif mutation == 'unreleased': w['plan']['routes']['U1']['deliveries'][1] = .2
    elif mutation == 'digits': w['digits'] = True
    else: w['columns'].append(['U1', 3, 'x'])
    w['candidate_hash'] = digest(w['plan'])
    assert not api().verify_quantity_witness(s, w, releases(s))


@pytest.mark.parametrize('duration', [-F(1), .1, '1/10'])
def test_lower_duration_input_must_be_nonnegative_exact_rational(duration):
    s = scene()
    durations = lower(s)
    durations['U1', (0, 0), (1, 0)] = duration
    r = evaluate(s, lower_durations=durations)
    assert r['status'] == 'UNRESOLVED' and r['proof'] is None


def test_unsupported_coupled_depot_retains_unresolved_status():
    s = scene()
    p = s.to_dict()
    p['operations']['depot_bays'] = 1
    r = evaluate(Scenario(p), lower_durations=lower(s))
    assert r['status'] == 'UNRESOLVED' and r['proof'] is None


def test_numerical_dual_can_be_rationally_verified_without_elimination_budget():
    s = scene(mandatory=.3, payload=.2)
    r = evaluate(s, lower_durations=lower(s), max_operations=0, max_rows=0)
    assert r['status'] == 'EMPTY'
    p = s.to_dict()
    assert api().verify_quantity_exclusion(s, p['incumbent'], p['reserve_paths'],
                                          releases(s), lower(s), r['proof'])


def test_absent_leg_bounds_use_safe_zero_without_losing_resource_exclusions():
    s = scene(mandatory=.3, payload=.2)
    r = evaluate(s, lower_durations={})
    assert r['status'] == 'EMPTY'
    p = s.to_dict()
    assert api().verify_quantity_exclusion(s, p['incumbent'], p['reserve_paths'],
                                          releases(s), {}, r['proof'])
