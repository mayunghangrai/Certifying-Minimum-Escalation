"""Reporting contracts: denominators, event cutoffs and paired populations."""
from copy import deepcopy

from final_study.analysis import _anytime, _arm_summary, _attach, _decision_summary, _paired_all


def _row(name, events, plan_level, minimum=None, returned_plan_cpu=None, arm='CMI'):
    return dict(instance=name, arm=arm, budget=10., events=events, plan_level=plan_level,
                minimum=minimum, certified=minimum is not None, lower=minimum or 0,
                upper=plan_level, first_plan_cpu=min((e['cpu_s'] for e in events if e['kind'] == 'plan'),
                                                   default=None),
                certificate_cpu=events[-1]['cpu_s'] if minimum is not None else None,
                returned_plan_cpu=returned_plan_cpu, cpu=12., wall=13., overrun=2.,
                audit_ok=True, audit_cpu=.1, categories={}, d_uavs_changed=1)


def test_report_tables_and_curves_keep_all_instances_in_the_primary_denominator():
    # A success, a failed search on a known minimum, an unrecoverable case, and an
    # unresolved reference. Dropping the last two would double the primary rate.
    raw = [_row('success', [dict(kind='plan', level=0, cpu_s=2.)], 0, 0, 2., arm='PH'),
           _row('failed', [], None), _row('none', [], None), _row('open', [], None)]
    refs = {'success': dict(lower=0, upper=0, minimum=0),
            'failed': dict(lower=1, upper=1, minimum=1),
            'none': dict(lower=5, upper=5, minimum=5),
            'open': dict(lower=1, upper=3, minimum=None)}
    rows = _attach(raw, {}, refs)
    summary = _arm_summary(rows)
    assert summary['at_min'] == .25
    assert summary['at_min_known'] == .5
    assert summary['known_n'] == 2 and summary['at_min_count'] == 1
    assert summary['certified'] == .25 and summary['certified_level0'] == .25
    _, curves = _anytime({'PH': rows}, 10., 'at_min')
    assert curves['PH'][-1] == .25


def test_report_uses_inclusive_budget_events_and_scores_only_the_returned_plan():
    raw = [
        _row('on_time', [dict(kind='proof', level=0, cpu_s=1.),
                         dict(kind='plan', level=1, cpu_s=10.)], 1, 1, 10.),
        _row('late_proof', [dict(kind='proof', level=4, cpu_s=10.01)], None, 5),
        _row('late_better_plan', [dict(kind='proof', level=1, cpu_s=1.),
                                  dict(kind='plan', level=3, cpu_s=5.),
                                  dict(kind='plan', level=2, cpu_s=12.)], 2, 2, 12.),
        _row('late_first_plan', [dict(kind='plan', level=0, cpu_s=10.01)], 0, 0, 10.01),
    ]
    before = deepcopy(raw)
    refs = {name: dict(lower=level, upper=level, minimum=level)
            for name, level in [('on_time', 1), ('late_proof', 5), ('late_better_plan', 2),
                                ('late_first_plan', 0)]}
    rows = _attach(raw, {}, refs)
    on_time, late_proof, late_return, late_first = rows
    assert on_time['certified'] and on_time['certificate_cpu'] == 10.
    assert not late_proof['certified'] and late_proof['lower'] == 0
    # The plan returned after the cutoff is the only stored witness; the earlier
    # Level-3 plan was not returned or replayed, so the run has no plan by the cutoff.
    assert late_return['plan_level'] is None and late_return['upper'] is None
    assert late_return['lower'] == 2 and not late_return['certified']
    assert late_return['first_plan_cpu'] is None and late_return['unreturned_better_plan'] == 1
    assert late_first['plan_level'] is None and late_first['first_plan_cpu'] is None
    assert _decision_summary([late_return])['uavs_changed'] is None
    summary = _arm_summary(rows)
    assert summary['plan'] == .25 and summary['certified'] == .25
    assert summary['overrun_count'] == 4 and summary['overrun_max'] == 2.
    assert summary['late_plan_events'] == 2 and summary['late_certificates'] == 3
    for key, expected in [('at_min', .25), ('certified', .25)]:
        _, curves = _anytime({'CMI': rows}, 10., key)
        assert curves['CMI'][-1] == expected
    assert raw == before


def test_a_better_plan_found_but_not_returned_is_not_credited():
    # As in GR: a Level-0 plan is logged at 2 s, then a Level-1 plan is returned at 6 s.
    row = _row('discarded', [dict(kind='plan', level=0, cpu_s=2.), dict(kind='plan', level=1, cpu_s=6.)],
               1, None, 6., arm='GR')
    rows = _attach([row], {}, {'discarded': dict(lower=0, upper=0, minimum=0)})
    scored = rows[0]
    assert scored['plan_level'] == 1 and not scored['at_min'] and not scored['certified']
    assert scored['first_plan_cpu'] == 6. and scored['unreturned_better_plan'] == 1
    assert _decision_summary(rows)['uavs_changed'] == 1
    summary = _arm_summary(rows)
    assert summary['at_min'] == 0. and summary['certified_level0'] == 0.
    for key in ('at_min', 'certified'):
        assert _anytime({'GR': rows}, 10., key)[1]['GR'][-1] == 0.


def test_unreplayed_events_do_not_count_as_budget_success():
    row = _row('bad', [dict(kind='plan', level=0, cpu_s=1.)], 0, 0, 1.)
    row['audit_ok'] = False
    rows = _attach([row], {}, {'bad': dict(lower=0, upper=0, minimum=0)})
    summary = _arm_summary(rows)
    assert summary['at_min'] == 0. and summary['certified'] == 0. and summary['plan'] == 0.
    assert _anytime({'CMI': rows}, 10., 'at_min')[1]['CMI'][-1] == 0.


def test_paired_rate_uses_shared_instances_and_resamples_whole_missions():
    # One mission has three improvements; the other has one loss. The bootstrap
    # must preserve those clusters instead of resampling four independent rows.
    short = [dict(instance=n, mission=m, certified=value)
             for n, m, value in [('a', 'm1', False), ('b', 'm1', False),
                                  ('c', 'm1', False), ('d', 'm2', True),
                                  ('short_only', 'm3', True)]]
    long = [dict(instance=n, mission=m, certified=value)
            for n, m, value in [('a', 'm1', True), ('b', 'm1', True),
                                 ('c', 'm1', True), ('d', 'm2', False),
                                 ('long_only', 'm4', False)]]
    point, lo, hi, n = _paired_all({'CMI': long, 'short': short}, 'short',
                                  lambda x, y: int(x['certified'])-int(y['certified']))
    assert (point, lo, hi, n) == (.5, -1., 1., 4)
    from final_study.analysis import _paired_rates
    result = _paired_rates(long, short, 'certified')
    assert result == dict(n=4, missions=2, left_count=3, right_count=1,
                         left_rate=.75, right_rate=.25, difference=.5, lo=-1., hi=1.)


def test_report_with_no_known_finite_minima_has_zero_primary_and_no_conditional_rate():
    rows = _attach([_row('open', [], None)], {}, {'open': dict(lower=1, upper=None, minimum=None)})
    summary = _arm_summary(rows)
    assert summary['at_min'] == 0.
    assert summary['at_min_known'] is None and summary['known_n'] == 0
