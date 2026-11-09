"""A0.6: exact binned flight-time enclosures (design 5.6 two-bin control)."""
import math
from copy import deepcopy
from fractions import Fraction as F

import pytest

from continuous.binned import (BeyondHorizon, binned_duration, binned_guard,
                               binned_interval, position_at)
from continuous.physics import stationary_duration
from env.scenario import Scenario
from v2_fixtures import revised
from test_v3_units import v3_case

# The 12 rational unit directions: 4 axes and the 8 (3/5, 4/5) turns.
DIRECTIONS = [(1, 0), (0, 1), (-1, 0), (0, -1)] + [
    (sx*a, sy*b) for a, b in ((F(3, 5), F(4, 5)), (F(4, 5), F(3, 5))) for sx in (1, -1) for sy in (1, -1)]
STRENGTHS = [2, 4, 6, 8]
KNOT = 40


def two_bin_case(w1, w2):
    """Uniform wind w1 on [0, 40 s), w2 on [40 s, 14400 s), in both cells."""
    p = v3_case()
    w = p['wind']
    w['time_knots_s'] = [0, KNOT, 14400]
    values = [[[str(F(x)) if F(x).denominator > 1 else int(x) for x in w1],
               [str(F(x)) if F(x).denominator > 1 else int(x) for x in w2]]]*2
    for projection in ('previous', 'received'):
        w[projection]['values'] = [list(map(list, row)) for row in values]
        w[projection]['admissible'] = [[True, True], [True, True]]
        w[projection]['coverage'] = ['forecast', 'forecast']
    w['update_support'] = []
    return Scenario(p)


def closed_form(speed, length, direction, w1, w2):
    def ground(w):
        along = float(w[0]*direction[0] + w[1]*direction[1])
        across = float(-w[0]*direction[1] + w[1]*direction[0])
        return along + math.sqrt(speed**2 - across**2)
    g1 = ground(w1)
    if g1*KNOT >= length:
        return length/g1
    return KNOT + (length - g1*KNOT)/ground(w2)


def test_one_bin_equals_the_stationary_checker():
    s = Scenario(revised())        # v2, one bin, received wind -0.5 km/h in the east
    for uid, path in (('U1', [[0, 0], [1, 0]]), ('U2', [[0, 0], [1, 0], [0, 0]]),
                      ('U3', [[0, 0], [-1, 0]]), ('U1', [[0, 0], [F(1, 3), F(1, 2)], [1, 0]])):
        path = [[float(x) for x in p] for p in path]
        assert binned_duration(s, uid, path, 0) == stationary_duration(s, uid, path)


@pytest.mark.parametrize('k', range(12))
@pytest.mark.parametrize('strength', STRENGTHS)
def test_two_bin_analytic_control(k, strength):
    d1, d2 = DIRECTIONS[k], DIRECTIONS[(k + 5) % 12]
    w1 = (strength*d1[0], strength*d1[1])
    w2 = (strength*d2[0], strength*d2[1])
    s = two_bin_case(w1, w2)
    heading = DIRECTIONS[(k + 2) % 12]
    length = 800
    end = [float(length*heading[0]), float(length*heading[1])]
    lo, hi = binned_duration(s, 'U1', [[0, 0], end], 0)
    exact = closed_form(10, length, heading, w1, w2)
    assert lo <= hi and hi - lo < F(1, 10**12)
    assert float(lo) - 1e-9 <= exact <= float(hi) + 1e-9
    behind, ahead = position_at(s, 'U1', [[0, 0], end], 0, 0, KNOT)
    assert all(abs(float(a) - float(b)) < 1e-9 for a, b in zip(behind, ahead))


def test_arrival_is_monotone_and_interval_is_ordered():
    s = two_bin_case((-8, 0), (8, 0))     # head wind, then tail wind, along +x
    path = [[0, 0], [800, 0]]
    previous = None
    for departure in range(0, 80, 5):
        lo, hi = binned_interval(s, 'U1', path, departure, departure)
        assert lo <= hi
        if previous is not None:
            assert lo >= previous      # FIFO: a later departure never arrives earlier
        previous = lo
    lo, hi = binned_interval(s, 'U1', path, 10, 30)
    assert lo == binned_interval(s, 'U1', path, 10, 10)[0]
    assert hi == binned_interval(s, 'U1', path, 30, 30)[1]


def test_beyond_horizon_is_reported():
    s = two_bin_case((0, 0), (0, 0))
    with pytest.raises(BeyondHorizon):
        binned_duration(s, 'U1', [[0, 0], [800, 0]], 14390)
    assert binned_interval(s, 'U1', [[0, 0], [800, 0]], 0, 14390) == (80, None)


def test_guard():
    assert binned_guard(Scenario(v3_case())) is None
    assert binned_guard(Scenario(revised())) == 'requires wind-benchmark-v3'
    p = v3_case()
    p['operations']['depot_bays'] = 1
    assert binned_guard(Scenario(p)) == 'coupled depot preparation'


# A0.7: exact witness checks dispatch to the binned checker for v3.

def test_v3_incumbent_premise_and_binned_witness():
    from continuous.validation import certify_witness, previous_premise
    s = Scenario(v3_case())
    premise = previous_premise(s)
    assert premise['accepted'] and premise['kind'] == 'binned_interval_witness_v3'
    p = s.to_dict()
    result = certify_witness(s, p['incumbent'], p['reserve_paths'], 0)
    assert result['accepted'], result


def test_v3_witness_rejects_a_missed_deadline():
    from continuous.validation import certify_witness
    p = v3_case()
    p['mission']['tasks'][0]['deadline_s'] = 399     # U1 delivers T1 at 400 s
    s = Scenario(p)
    result = certify_witness(s, p['incumbent'], p['reserve_paths'], 0)
    assert not result['accepted'] and 'deadline:U1:1:T1' in result['reason']


def test_v3_quantity_witness_round_trip_and_tamper():
    from env.intervention_scope import release_sets
    from level2.quantities import evaluate_quantities, verify_quantity_witness
    s = Scenario(v3_case())
    p = s.to_dict()
    releases = release_sets(s, 2, {'T1'})
    report = evaluate_quantities(s, p['incumbent'], p['reserve_paths'], releases)
    assert report['status'] == 'WITNESS' and report['witness'] is not None, report
    witness = report['witness']
    assert verify_quantity_witness(s, witness, releases)
    # Every quantity is committed in this fixture, so tamper with the plan itself.
    assert witness['columns'] == []
    plan = deepcopy(witness['plan'])
    plan['routes']['U1']['deliveries'][1] = 0.
    assert not verify_quantity_witness(s, dict(witness, plan=plan), releases)


def test_energy_is_charged_over_the_whole_departure_window():
    """In interval mode a flight is charged from the earliest possible departure."""
    from env.intervention_scope import release_sets
    from recovery.transfers import build_transfer_problem
    s = Scenario(v3_case())
    p = s.to_dict()
    calls = []

    def provider(uid, path, lo, hi):
        calls.append((uid, lo, hi))
        return (lo + 100, hi + 100) if uid == 'U1' and lo == 0 else (lo + 101, hi + 103)
    c = build_transfer_problem(s, p['incumbent'], p['reserve_paths'], release_sets(s, 0),
                               exact=True, interval_provider=provider)
    u1 = [call for call in calls if call[0] == 'U1']
    # First leg exact from 0; the return starts at upper 100 with a known lag 0,
    # then the next call carries the lag of the earlier window.
    assert u1[0][1:] == (0, 0)
    times = {(t['uav'], t['slot']): t for t in c.times}
    assert times['U1', 2]['arrival'] == 203
