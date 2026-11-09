import json
from collections import defaultdict
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import pytest

from continuous.validation import previous_premise
from env.scenario import Scenario
from final_study import support_sensitivity as ss
from final_study.arena import label
from final_study.store import Store

ROOT = Path(__file__).resolve().parents[1]
FS_RUN = ROOT/'results'/'final_study_2026_10_17'
CONFIG = json.loads((ROOT/'configs'/'final_study'/'final.json').read_text(encoding='utf-8'))
pytestmark = pytest.mark.skipif(not (FS_RUN/'manifest.json').exists(), reason='stored final study not available')


@pytest.fixture(scope='module')
def sources():
    """(mission, stored _r1_t0 payload, ledger) for the 53 missions of the 60 s arena third."""
    fs = Store(FS_RUN, None, bind=False)
    out = []
    for name in ss.missions(fs):
        item = fs.load('fs', 'missions', name)
        out.append((name, item['variants'][name+ss.VARIANT], item['ledger']))
    return out


def test_the_mission_set_is_the_seeded_third(sources):
    assert len(sources) == 53
    assert len({ledger['m'] for _, _, ledger in sources}) == 3


def test_support_sizes_and_shapes(sources):
    cells = sources[0][1]['wind']['cells']
    grid = ss.grid_positions(cells)
    assert sorted(grid) == [(x, y) for x in range(4) for y in range(4)]
    for seed in range(16):
        x, y = grid[seed]
        s = ss.supports(cells, seed)
        assert s['S1'] == {seed: 1}
        assert len(s['S2']) == 4 and len(s['S3']) == 9 and len(s['S5']) == 15
        assert all(seed in s[c] for c in ss.CONDITIONS)
        assert all(v == 1 for c in ('S1', 'S2', 'S3', 'S5') for v in s[c].values())
        neighbours = {(a, b) for a in range(x-1, x+2) for b in range(y-1, y+2) if 0 <= a < 4 and 0 <= b < 4}
        assert set(s['S4']) == {grid.index(p) for p in neighbours} and len(s['S4']) in (4, 6, 9)
        assert s['S4'][seed] == 1 and all(v == Fraction(1, 2) for c, v in s['S4'].items() if c != seed)
        # S2 extends toward the centre; S3 starts at clamp(x-1, 0, 1); S5 drops the opposite corner.
        xs = (x, x+1) if x <= 1 else (x-1, x)
        ys = (y, y+1) if y <= 1 else (y-1, y)
        assert set(s['S2']) == {grid.index((a, b)) for a in xs for b in ys}
        x0, y0 = min(max(x-1, 0), 1), min(max(y-1, 0), 1)
        assert set(s['S3']) == {grid.index((a, b)) for a in range(x0, x0+3) for b in range(y0, y0+3)}
        (dropped,) = set(range(16))-set(s['S5'])
        assert grid[dropped] == (0 if x >= 2 else 3, 0 if y >= 2 else 3)


def test_the_rules_never_read_the_plan(sources):
    """The supports need only cell ids and polygons, and missions with the same seed cell
    get the same supports whatever their incumbent."""
    stub = [dict(id=c['id'], polygon_xy=c['polygon_xy']) for c in sources[0][1]['wind']['cells']]
    for seed in range(16):
        assert ss.supports(stub, seed) == ss.supports(sources[0][1]['wind']['cells'], seed)
    by_seed = defaultdict(set)
    for name, source, ledger in sources:
        for code in ss.CONDITIONS:
            q = ss.condition_payload(source, ledger, code)
            by_seed[ledger['cell_index'], code].add(json.dumps(q['wind']['update_support']))
            assert {c for c, _ in q['wind']['update_support']} == \
                {source['wind']['cells'][i]['id'] for i in ss.supports(stub, ledger['cell_index'])[code]}
    assert all(len(v) == 1 for v in by_seed.values())


def test_payloads_change_only_the_received_wind_and_support(sources):
    for name, source, ledger in sources:
        for code in ss.CONDITIONS:
            q = ss.condition_payload(source, ledger, code)
            a, b = deepcopy(q), deepcopy(source)
            for p in (a, b):
                del p['benchmark_id'], p['wind']['received']['values'], p['wind']['update_support']
            assert a == b
            assert q['benchmark_id'] == (source['benchmark_id'] if code == 'S1' else f"{source['benchmark_id']}_{code}")
            support = {c for c, _ in q['wind']['update_support']}
            for cell, before, after in zip(q['wind']['cells'], q['wind']['previous']['values'],
                                           q['wind']['received']['values']):
                assert (cell['id'] in support) == (before != after)


def test_values_are_the_designed_vectors_within_the_bound(sources):
    for name, source, ledger in sources:
        strength = Fraction(ledger['variants'][source['benchmark_id']]['strength'])
        v_min = min(Fraction(str(u['airspeed_kmh'])) for u in source['mission']['vehicles'])
        d = [Fraction(c) for c in ledger['direction']]
        bound = Fraction(str(source['wind']['speed_bound_kmh']))
        for code in ss.CONDITIONS:
            q = ss.condition_payload(source, ledger, code)
            for c, factor in ss.supports(q['wind']['cells'], ledger['cell_index'])[code].items():
                w = [Fraction(str(v)) for v in q['wind']['received']['values'][c][0]]
                assert w == [factor*strength*v_min*x for x in d]
                assert w[0]**2+w[1]**2 <= bound**2


def test_s1_is_the_stored_variant(sources):
    for name, source, ledger in sources:
        q = ss.condition_payload(source, ledger, 'S1')
        assert q == source
        assert Scenario(q).content_hash() == ledger['variants'][source['benchmark_id']]['scenario_hash']


def test_previous_premise_is_unchanged(sources):
    name, source, ledger = sources[0]
    for code in ss.CONDITIONS:
        q = ss.condition_payload(source, ledger, code)
        assert q['wind']['previous'] == source['wind']['previous']
        assert previous_premise(Scenario(q))['accepted']


def test_s1_diagnosis_matches_the_ledger(sources):
    for name, source, ledger in sources[:5]:
        d = ss.diagnosis(ss.condition_payload(source, ledger, 'S1'))
        assert d['u0'] == ledger['variants'][source['benchmark_id']]['affected'] and d['support_cells'] == 1
        assert d['local']


def test_s1_label_agrees_with_the_stored_fs_label():
    fs = Store(FS_RUN, None, bind=False)
    mission = 'FS_4x2_loose_ample_clustered_76018'       # a quick label (about 1 s CPU)
    item = fs.load('fs', 'missions', mission)
    vid = mission+ss.VARIANT
    payload = ss.condition_payload(item['variants'][vid], item['ledger'], 'S1')
    record = label(ss.instance_id(mission, 'S1'), payload, CONFIG['label_budget_s'], CONFIG['settings'])
    stored = fs.load('fs', 'labels', vid)
    assert record['audit']['ok']
    assert record['input_hash'] == stored['input_hash']
    assert record['result']['bounds'] == stored['result']['bounds']
    assert record['result']['plan_level'] == stored['result']['plan_level']
