"""End-to-end v2 checks on P1 variants: agreement with v1 labels, replay, soundness."""
import csv
import json
from pathlib import Path

import pytest

from certify_v2.accounting import Clock
from certify_v2.ladder import run_cmi, run_ph
from certify_v2.oracle import Evidence, RouteOracle
from certify_v2.replay import ReplayError, verify_run
from certify_v2.table import FlightTable
from env.scenario import Scenario

ROOT = Path(__file__).resolve().parents[1]
P1 = ROOT/'results'/'escalation_study_primary'
CASES = ('P1_4_4_clustered_72008_r0_s4', 'P1_12_4_clustered_72001_r0_s2', 'P1_12_4_clustered_72015_r1_s3')


def _labels():
    path = P1/'analysis'/'variants.csv'
    if not path.exists():
        pytest.skip('P1 primary records not available')
    return {r['case']: r for r in csv.DictReader(path.open(encoding='utf-8'))}


def _scenario(case, labels):
    mission = labels[case]['mission']
    item = json.loads((P1/'missions'/f'{mission}.json').read_text(encoding='utf-8'))
    return Scenario(item['scenarios'][case])


def _drive(gen):
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value


def test_cmi_agrees_with_v1_and_replays():
    labels = _labels()
    for case in CASES:
        scenario = _scenario(case, labels)
        result = json.loads(json.dumps(run_cmi(scenario, 30)))
        v1 = labels[case]
        b = result['bounds']
        if v1['category'] not in ('unresolved',):
            expected = v1['category'] if v1['category'] == 'infinity' else int(v1['category'])
            assert b['minimum'] == expected, (case, b)
        else:
            assert b['lower'] is None or b['lower'] >= int(v1['lower'])
        assert verify_run(scenario, result)['bounds'] == b
        tampered = json.loads(json.dumps(result))
        tampered['bounds']['lower'] = (b['lower'] or 0)+1
        with pytest.raises(ReplayError):
            verify_run(scenario, tampered)


def test_route_check_admits_every_accepted_plan():
    labels = _labels()
    for case in CASES:
        scenario = _scenario(case, labels)
        result = run_cmi(scenario, 30)
        if result['plan'] is None:
            continue
        plan = result['plan']['witness']['plan']
        oracle = RouteOracle(scenario, FlightTable(scenario), Evidence(), clock=Clock())
        for uid in plan['routes']:
            tasks = [t for t, o in plan['assignment'].items() if o == uid]
            assert _drive(oracle.relax(uid, tasks)) == ('feasible', None)


def test_ph_returns_only_checked_plans():
    labels = _labels()
    scenario = _scenario(CASES[1], labels)
    result = json.loads(json.dumps(run_ph(scenario, 10)))
    assert result['bounds']['excluded_levels'] == []
    verify_run(scenario, result)


def test_strict_ph_leaves_levels_without_proofs():
    labels = _labels()
    for case in CASES:
        scenario = _scenario(case, labels)
        result = json.loads(json.dumps(run_ph(scenario, 10, {'fixed_exclusions': False}, arm='PH-strict')))
        assert result['arm'] == 'PH-strict'
        assert result['bounds']['excluded_levels'] == []
        assert not any(isinstance(e['reason'], int) for e in result['events'] if e['kind'] == 'escalate')
        verify_run(scenario, result)


def test_guaranteed_share_gives_every_level_its_share():
    labels = _labels()
    scenario = _scenario(CASES[0], labels)
    shares = (0.05, 0.15, 0.2, 0.3, 0.3)
    result = run_ph(scenario, 10, {'fixed_exclusions': False}, shares=shares, guaranteed=True)
    start = result['clock']['categories']['setup']
    for e in result['events']:
        if e['kind'] == 'escalate' and e['reason'] == 'share spent':
            assert e['cpu_s']-start >= shares[e['level']]*10-1e-9
        start = e['cpu_s']
    verify_run(scenario, json.loads(json.dumps(result)))


def test_schedule_arms_return_checked_results():
    from final_study.arena import PH_SCHEDULES, run_arm
    labels = _labels()
    scenario = _scenario(CASES[0], labels)
    for arm in PH_SCHEDULES:
        result = json.loads(json.dumps(run_arm(arm, scenario.to_dict(), 10)))
        assert result['arm'] == arm and result['bounds']['excluded_levels'] == []
        assert not any(isinstance(e['reason'], int) for e in result['events'] if e['kind'] == 'escalate')
        verify_run(scenario, result)


FS = ROOT/'results'/'final_study_2026_10_17'


def _fs_scenario(vid):
    if not (FS/'manifest.json').exists():
        pytest.skip('final-study records not available')
    from final_study.store import Store
    store = Store(FS, None, bind=False)
    return Scenario(store.load('fs', 'missions', vid.rsplit('_r', 1)[0])['variants'][vid])


def test_mu_refinement_finds_and_proves_the_fewest_outside_uavs():
    """B1: the first instance has a Level-3 plan changing no UAV outside U0, the second has none;
    CMI's plan changed one outside UAV on both."""
    from final_study.arena import run_arm
    for vid, expected in (('FS_4x2_medium_medium_clustered_76010_r1_t2', 0),
                          ('FS_6x2_medium_medium_uniform_76063_r0_t2', 1)):
        scenario = _fs_scenario(vid)
        result = json.loads(json.dumps(run_arm('CMI-mu', scenario.to_dict(), 10)))
        assert result['arm'] == 'CMI-mu' and result['bounds']['minimum'] == 3
        assert result['mu_bounds'] == dict(lower=expected, upper=expected, minimum=expected)
        assert (list(result['mu_proofs']) == ['0']) == (expected == 1)
        assert verify_run(scenario, result)['mu_bounds'] == result['mu_bounds']
        tampered = json.loads(json.dumps(result))
        tampered['mu_bounds']['lower'] += 1
        with pytest.raises(ReplayError):
            verify_run(scenario, tampered)
        if expected == 1:
            tampered = dict(json.loads(json.dumps(result)), mu_proofs={})
            with pytest.raises(ReplayError):
                verify_run(scenario, tampered)
