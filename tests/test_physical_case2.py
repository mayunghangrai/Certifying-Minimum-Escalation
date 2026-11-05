import gzip
import json
import math
from fractions import Fraction
from pathlib import Path

import pytest

from continuous.validation import previous_premise
from env.scenario import Scenario
from escalation_study.missions import delivery_times
from final_study import physical_case2 as c2

SOURCE = Path(__file__).resolve().parents[1]/'results'/'final_study_2026_10_17'/'fs'/'missions'/f'{c2.SOURCE}.json.gz'
pytestmark = pytest.mark.skipif(not SOURCE.exists(), reason='stored FS mission not available')


@pytest.fixture(scope='module')
def mission():
    with gzip.open(SOURCE, 'rt', encoding='utf-8') as f:
        source = json.load(f)
    classes = source['ledger']['classes']
    return source, classes, c2.nominal_mission(source['variants'][c2.SOURCE_VARIANT], classes)


def test_sectors_are_contiguous_blocks_of_four(mission):
    _, _, p = mission
    blocks = c2.sectors(p['mission']['tasks'], 6)
    assert [len(b) for b in blocks] == [4]*6
    dx, dy = c2.DEPOT_XY
    bearing = [round(math.atan2(t['position_xy'][1]-dy, t['position_xy'][0]-dx), 12) for b in blocks for t in b]
    assert bearing == sorted(bearing)
    for uid, block in zip(sorted(p['incumbent']['routes']), blocks):
        assert {p['incumbent']['assignment'][t['id']] for t in block} == {uid}


def test_sorties_respect_payload_and_loads_balance_deliveries(mission):
    _, classes, p = mission
    rank = {c: i for i, c in enumerate(c2.CLASS_ORDER)}
    for route in p['incumbent']['routes'].values():
        stops = [s for s in route['stops'] if s is not None]
        assert stops[-1] == 'DEPOT'
        onboard = Fraction(str(route['loads'][0]))
        assert onboard <= 3
        for h, s in enumerate(stops, 1):
            if s == 'DEPOT':
                assert onboard == 0
                onboard = Fraction(str(route['loads'][h]))
                assert onboard <= 3
            else:
                onboard -= Fraction(str(route['deliveries'][h]))
        assert onboard == 0
        tasks = [s for s in stops if s != 'DEPOT']
        assert [rank[classes[t]] for t in tasks] == sorted(rank[classes[t]] for t in tasks)


def test_profiles_keep_targets_unless_unreachable(mission):
    _, classes, p = mission
    arrival = delivery_times(Scenario(p))
    for profile in c2.PROFILES:
        q, fallbacks = c2.with_profile(p, classes, profile)
        assert previous_premise(Scenario(q))['accepted']
        for t in q['mission']['tasks']:
            target = Fraction(c2.PROFILES[profile][classes[t['id']]], 60)
            hi = arrival[t['id']][1]
            due = Fraction(str(t['deadline_h']))
            if t['id'] in fallbacks:
                assert hi+Fraction(1, 60) > target
                assert abs(due-(math.ceil(hi*60)+1)/Fraction(60)) < Fraction(1, 10**9)
            else:
                assert hi+Fraction(1, 60) <= target and abs(due-target) < Fraction(1, 10**9)


def test_conditions_change_only_the_received_wind(mission):
    _, classes, p = mission
    q, _ = c2.with_profile(p, classes, 'P15')
    assert len(c2.conditions()) == 144
    assert c2.coverage_cells('A2', 'K3') == (0, 1, 2, 4, 5, 6, 8, 9, 10)
    for _, anchor, coverage, direction, strength in c2.conditions()[:72]:
        r = c2.apply_update(q, anchor, coverage, direction, strength, profile='P15')
        cells = set(c2.coverage_cells(anchor, coverage))
        for i, row in enumerate(r['wind']['received']['values']):
            assert (row[0] != [0, 0]) == (i in cells)
        assert {k: v for k, v in r.items() if k not in ('wind', 'benchmark_id')} == \
            {k: v for k, v in Scenario(q).to_dict().items() if k not in ('wind', 'benchmark_id')}
