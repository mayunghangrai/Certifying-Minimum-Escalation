import sys
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))

import pytest

from continuous.search import recover_continuous, verify_continuous_evidence
from continuous.validation import previous_premise
from continuous_benchmark.cases import controlled_cases
from env.local_scope import affected_uavs
from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update
from escalation_study.missions import base_mission, ledger_hash, variant_id


@pytest.fixture(scope='module')
def mission():
    return base_mission(4, 4, 'uniform', 71001)


def _normalized(payload):
    p = deepcopy(payload)
    p['benchmark_id'] = ''
    for t in p['mission']['tasks']:
        t['deadline_h'] = None
    p['wind']['received'] = p['wind']['previous']
    p['wind']['update_support'] = []
    return p


def test_variants_differ_only_in_deadlines_and_wind_strength(mission):
    variants, ledger = mission
    assert ledger['status'] == 'accepted' and len(variants) == 15
    assert ledger['selection_uses_recovery_labels'] is False
    reference = _normalized(next(iter(variants.values())))
    v_min = Fraction(ledger['v_min'])
    direction = [Fraction(v) for v in ledger['direction']]
    for name, payload in variants.items():
        info = ledger['variants'][name]
        assert _normalized(payload) == reference
        assert payload['wind']['update_support'] == [[ledger['cell'], 0]]
        wind = [Fraction(str(v)) for v in payload['wind']['received']['values'][ledger['cell_index']][0]]
        assert wind == [Fraction(info['strength'])*v_min*c for c in direction]
        scenario = Scenario(payload)
        assert scenario.content_hash() == info['scenario_hash']
        assert affected_uavs(scenario, diagnose_wind_update(scenario))['uavs'] == ledger['affected']
    assert 0 < len(ledger['affected']) <= 2


def test_deadlines_follow_previous_times_and_tighten_with_slack(mission):
    variants, ledger = mission
    tau = Fraction(ledger['tau'])
    for task, (lower, upper) in ledger['previous_delivery'].items():
        values = [Fraction(str(v)) for v in ledger['deadlines'][task]]
        assert values == sorted(values, reverse=True)
        for value, slack in zip(values, ledger['slacks']):
            assert Fraction(upper)+Fraction(slack)*tau <= value <= Fraction(upper)+Fraction(slack)*tau+Fraction(1, 10**10)
    tightest = Scenario(variants[variant_id(ledger['mission'], 2, 4)])
    assert previous_premise(tightest)['accepted']


def test_battery_covers_five_halves_of_previous_requirement(mission):
    _, ledger = mission
    battery = ledger['battery']
    reserve = Fraction(1)
    for uid, capacity in battery['capacities'].items():
        required = Fraction(battery['requirements'][uid])
        assert Fraction(capacity) >= reserve+Fraction(5, 2)*(required-reserve)


def test_generator_is_deterministic(mission):
    variants, ledger = mission
    again = base_mission(4, 4, 'uniform', 71001)
    assert ledger_hash(ledger, variants) == ledger_hash(again[1], again[0])


def test_failed_slot_keeps_its_ledger():
    variants, ledger = base_mission(4, 4, 'uniform', 71001, max_attempts=0)
    assert variants == {} and ledger['status'] == 'generation_failed' and ledger['attempts'] == []


def test_seeded_screen_reuses_verified_queries_without_changing_conclusions():
    case = next(c for c in controlled_cases() if c.name == 'C1')
    first = recover_continuous(case.scenario, max_seconds=30, max_proposals=40)
    second = recover_continuous(case.scenario, max_seconds=30, max_proposals=40, initial_bounds=first['paths'])
    assert first['full_domain'] == second['full_domain']
    assert verify_continuous_evidence(case.scenario, second)
    assert second['effort']['oracle']['cache_hits'] >= 1
    assert [e['kind'] for e in second['effort']['events']] == [e['kind'] for e in first['effort']['events']]
    forged = deepcopy(first['paths'][0])
    forged['lower'] = str(Fraction(forged['upper'])+1)
    with pytest.raises(ValueError):
        recover_continuous(case.scenario, max_seconds=30, max_proposals=40, initial_bounds=[forged])
