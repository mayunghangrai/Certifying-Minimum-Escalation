import gzip
import json
from fractions import Fraction
from pathlib import Path

import pytest

from continuous.validation import previous_premise
from env.scenario import Scenario
from final_study import physical_case as pc

SOURCE = Path(__file__).resolve().parents[1]/'results'/'final_study_2026_10_17'/'fs'/'missions'/f'{pc.SOURCE}.json.gz'
pytestmark = pytest.mark.skipif(not SOURCE.exists(), reason='stored FS mission not available')


@pytest.fixture(scope='module')
def nominal():
    with gzip.open(SOURCE, 'rt', encoding='utf-8') as f:
        source = json.load(f)
    return source, pc.with_deadlines(pc.nominal_mission(source['variants'][pc.SOURCE_VARIANT]),
                                     source['ledger']['classes'])


def test_nominal_keeps_the_mission_and_is_feasible(nominal):
    source, p = nominal
    original = source['variants'][pc.SOURCE_VARIANT]
    assert p['incumbent'] == original['incumbent'] and p['reserve_paths'] == original['reserve_paths']
    assert [(t['id'], t['position_xy'], t['demand']) for t in p['mission']['tasks']] == \
        [(t['id'], t['position_xy'], t['demand']) for t in original['mission']['tasks']]
    assert p['state']['depot_stock'] == original['state']['depot_stock']
    assert all(u['airspeed_kmh'] == 54 for u in p['mission']['vehicles'])
    assert previous_premise(Scenario(p))['accepted']


def test_conditions_change_only_the_received_wind_on_their_cells(nominal):
    _, p = nominal
    assert len(pc.conditions()) == 36
    for coverage, direction, strength in pc.conditions():
        q = pc.apply_update(p, coverage, direction, strength)
        cells = set(pc.COVERAGE[coverage])
        assert q['wind']['update_support'] == [[q['wind']['cells'][c]['id'], 0] for c in pc.COVERAGE[coverage]]
        for r, row in enumerate(q['wind']['received']['values']):
            expected = [strength*3.6*c for c in pc.DIRECTIONS[direction]] if r in cells else [0, 0]
            assert row[0] == pytest.approx(expected)
            assert Fraction(str(row[0][0]))**2+Fraction(str(row[0][1]))**2 <= Fraction('43.2')**2
        rest = {k: v for k, v in q.items() if k not in ('wind', 'benchmark_id')}
        assert rest == {k: v for k, v in Scenario(p).to_dict().items() if k not in ('wind', 'benchmark_id')}


def test_energy_fit_never_underestimates_documented_consumption():
    for row in pc.energy_fit().values():
        assert row['model_wh_per_km'] >= row['documented_wh_per_km']
