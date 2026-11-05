import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))

from escalation_study.analysis import _closing_time, bands, shares, stronger_wind_relief

SLACKS = ['1/10', '1/100', '1/1000']


def _row(mission, strength, si, category, lower, upper):
    return dict(mission=mission, strength=strength, slack=SLACKS[si], slack_index=si,
                strength_index=['1/5', '3/5'].index(strength), tasks_per_uav=2,
                category=category, lower=lower, upper=upper)


TABLE = [
    _row('A', '1/5', 0, '0', 0, 0), _row('A', '1/5', 1, '1', 1, 1), _row('A', '1/5', 2, 'unresolved', 2, ''),
    _row('B', '1/5', 0, '0', 0, 0), _row('B', '1/5', 1, '0', 0, 0), _row('B', '1/5', 2, '4', 4, 4),
    _row('A', '3/5', 0, '0', 0, 0), _row('A', '3/5', 1, '0', 0, 0), _row('A', '3/5', 2, '2', 2, 2),
]


def test_shares_keep_unresolved_and_bound_what_it_could_be():
    out = {(r['strength'], r['slack'], r['category']): r for r in shares(TABLE, ('strength', 'slack'), resamples=200)}
    tight = {k: out['1/5', '1/1000', k] for k in ('2', '3', '4', 'unresolved', 'infinity')}
    assert tight['unresolved']['share'] == .5 and tight['4']['share'] == .5
    assert tight['2']['identified_low'] == 0 and tight['2']['identified_high'] == .5
    assert tight['infinity']['identified_high'] == .5
    assert 0 <= tight['4']['ci_low'] <= .5 <= tight['4']['ci_high'] <= 1


def test_bands_use_certified_bounds_on_both_sides():
    row = next(b for b in bands(TABLE, SLACKS) if b['mission'] == 'A' and b['strength'] == '1/5')
    assert row['level0_suffices_through'] == '1/10' and row['level0_fails_from'] == '1/100'
    assert row['level1_suffices_through'] == '1/100' and row['level1_fails_from'] == '1/1000'
    assert row['level2_fails_from'] == '' and not row['level4_only_band']
    assert next(b for b in bands(TABLE, SLACKS) if b['mission'] == 'B')['level4_only_band']


def test_stronger_wind_relief_counts_only_certified_pairs():
    pairs, falls = stronger_wind_relief(TABLE)
    assert pairs == 2 and [f['slack'] for f in falls] == ['1/100']


def test_closing_time_follows_events_and_transfers():
    result = dict(transfer=dict(excluded_through=0), prior=None, timing=dict(total=dict(wall_s=9., cpu_s=8.),
                  screen=dict(wall_s=3., cpu_s=2.5)),
                  events=[dict(stage='screen', kind='exclusion', level=0, wall_s=.5, cpu_s=None),
                          dict(stage='screen', kind='witness', level=1, wall_s=2., cpu_s=None)])
    assert _closing_time(result, 0.) == (2., 2.5)
