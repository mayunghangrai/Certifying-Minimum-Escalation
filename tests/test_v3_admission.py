"""A8: admission by the exact checker alone, Latin schedule, draw loop."""
from collections import Counter

import pytest

from env.scenario import Scenario
from study_v3.admission import certain_violations
from study_v3.generate import fill_slot, ms_cells, ms_slots, sc_slots, variants
from test_v3_generator import COEFFICIENTS
from test_v3_units import v3_case


def test_latin_schedule_balances_block_size():
    cells = ms_cells()
    assert len(cells) == 81 and len(ms_slots()) == 324 and len(sc_slots()) == 120
    assert Counter(c['size'] for c in cells) == {1: 27, 4: 27, 9: 27}
    for key in {c['key'] for c, _, _ in sc_slots()}:
        assert Counter(c['size'] for c, _, _ in sc_slots() if c['key'] == key) == {1: 5, 4: 5, 9: 5}
    for factor in ('m', 'slack', 'beta'):
        for level in {c[factor] for c in cells}:
            assert Counter(c['size'] for c in cells if c[factor] == level) == {1: 9, 4: 9, 9: 9}


def test_certain_violation_on_the_hand_checked_case():
    # U1 delivers T1 at exactly 400 s under the received wind (-7.5 m/s).
    assert certain_violations(Scenario(v3_case())) == []
    p = v3_case()
    p['mission']['tasks'][0]['deadline_s'] = 399
    assert certain_violations(Scenario(p)) == ['deadline:U1:1:T1']
    p = v3_case()
    p['mission']['vehicles'][0]['battery_capacity_wh'] = 100   # usable 50 Wh < about 49 + 6.9 Wh
    p['state']['fleet']['U1']['battery_wh'] = 100
    assert 'depot_arrival_reserve:U1:2' in certain_violations(Scenario(p))


@pytest.fixture(scope='module')
def slot():
    cell = dict(m=3, n=6, slack='tight', beta='tight', size=4, admission_r=0.8, key='TEST')
    return fill_slot(81001, cell, 0, 'uniform', COEFFICIENTS, iterations=50, max_draws=12)


def test_draw_loop_logs_every_draw(slot):
    log = slot['log']
    assert [e['draw'] for e in log] == list(range(len(log)))
    assert all('reason' in e and 'admitted' in e for e in log)
    assert len({e['geometry_seed'] for e in log}) == 1            # one geometry per 12 draws
    assert sum(e['admitted'] for e in log) == (slot['mission'] is not None)


def test_admitted_mission_is_certainly_broken_and_has_nine_variants(slot):
    if slot['mission'] is None:
        pytest.skip('no admission within 12 draws: ' + str(Counter(e['reason'] for e in slot['log'])))
    entry = slot['log'][-1]
    assert entry['violations'] and 1 <= len(entry['u0']) <= 1
    out = variants(slot['mission'], slot['block'])
    assert len(out) == 9 and {v['r'] for v in out} == {0.4, 0.6, 0.8}
    for v in out:
        Scenario(v['payload'])
