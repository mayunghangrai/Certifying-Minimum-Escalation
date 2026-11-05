from copy import deepcopy
import json
from pathlib import Path

import pytest

from experiments.instances import build_instances


def test_recorder_runs_paired_equal_budgets_and_preserves_replayable_evidence(tmp_path):
    from experiments.runner import run_benchmark, default_protocol, verify_run
    root = Path(__file__).resolve().parents[1]
    cases = build_instances(root)[-4:-2]
    protocol = default_protocol()
    protocol['repeats'] = 2
    protocol['budgets'] = {'test': dict(total_nodes=64, total_branches=4)}
    out = tmp_path/'run'
    summary = run_benchmark(root, out, instances=cases, protocol=protocol, progress=lambda _: None)
    assert summary['configuration_count'] == 2
    assert summary['comparison_count'] == 4
    assert summary['measurement_count'] == 8
    rows = [json.loads(line) for line in (out/'measurements.jsonl').read_text().splitlines()]
    assert all(row['elapsed_seconds'] >= 0 for row in rows)
    for case in cases:
        first = [r for r in rows if r['case_id'] == case['id'] and r['order'] == 0]
        assert {r['strategy'] for r in first} == {'ascending', 'level4'}
    reports = [json.loads(line) for line in (out/'search_reports.jsonl').read_text().splitlines()]
    for record in reports:
        r = record['report']
        assert r['total_node_budget'] == 64 and r['total_branch_budget'] == 4
        assert r['nodes_used'] <= 64 and r['branches_used'] <= 4
        assert r['scenario_hash'] == next(c for c in cases if c['id'] == record['case_id'])['representation']['scenario_hash']
    assert verify_run(out)['verified_reports'] == 6
    from experiments.runner import _audit_grid
    references = [json.loads(line) for line in (out/'reference_reports.jsonl').read_text().splitlines()]
    with pytest.raises(ValueError, match='timing repetition grid'):
        _audit_grid(cases, reports, rows[:-1], references, protocol)
    with pytest.raises(ValueError, match='comparison grid'):
        _audit_grid(cases, reports+[reports[0]], rows, references, protocol)
    wrong_hash = [{**rows[0], 'report_hash':'wrong'}, *rows[1:]]
    with pytest.raises(ValueError, match='deterministic replay'):
        _audit_grid(cases, reports, wrong_hash, references, protocol)
    with pytest.raises(ValueError, match='reference'):
        _audit_grid(cases, reports, rows, [r for r in reports if r['strategy']=='ascending'], protocol)
    with pytest.raises(FileExistsError):
        run_benchmark(root, out, instances=cases, protocol=protocol)
    # Persisted results must not be trusted after corruption.
    reports[0]['report']['upper_bound'] = 99
    (out/'search_reports.jsonl').write_text('\n'.join(json.dumps(r) for r in reports), encoding='utf-8')
    with pytest.raises(ValueError):
        verify_run(out)


def test_summary_uses_conditions_not_timing_repetitions_as_recovery_denominator():
    from experiments.runner import summarize
    cases = [dict(id='a', family='x', factor='wind', value=0, scenario={}, representation={})]
    reports = [dict(case_id='a', budget='test', strategy='ascending', report=dict(
        status='MINIMUM_CERTIFIED_R', upper_bound=0, lower_bound=0, nodes_used=5, branches_used=1))]
    timings = [dict(case_id='a', budget='test', strategy='ascending', elapsed_seconds=t) for t in (1,2,9)]
    references = [dict(case_id='a', report=deepcopy(reports[0]['report']))]
    result = summarize(cases, reports, timings, references)
    row = result['by_budget_strategy'][0]
    assert row['conditions'] == row['exact_recoveries'] == row['minimum_certificates'] == 1
    assert row['runtime_median_seconds'] == 2
    assert result['measurement_count'] == 3


def test_uncertified_reference_upper_bound_is_not_reported_as_a_minimum():
    from experiments.runner import summarize
    refs = [dict(case_id='a', report=dict(status='WITNESS_WITH_GAP_R',lower_bound=0,upper_bound=3))]
    result = summarize([], [], [], refs)
    assert result['reference_minima'] == {}
    assert result['reference_upper_bounds'] == {'3': 1}


def test_cached_proof_does_not_skip_each_record_input_or_strategy_binding():
    from experiments.runner import _audit_records, default_protocol, digest
    from env.scenario import Scenario
    from recovery.representation import PathLibrary
    from recovery.search import recover
    root = Path(__file__).resolve().parents[1]
    cases = build_instances(root)[-4:-2]
    s = Scenario.from_dict(cases[0]['scenario'])
    lib = PathLibrary.from_dict(s, cases[0]['representation'])
    report = recover(s, lib, strategy='level4',total_nodes=64,total_branches=4,numerical=False,
                     max_nodes=64,max_branches=4,max_iterations=0)
    record = dict(case_id=cases[0]['id'],budget='low',strategy='level4',report=report,report_hash=digest(report))
    # Identical content under a different library must not reuse the audit.
    wrong_case = {**record, 'case_id':cases[1]['id']}
    with pytest.raises(ValueError):
        _audit_records(cases, [record, wrong_case], default_protocol())
    with pytest.raises(ValueError):
        _audit_records(cases, [{**record, 'strategy':'ascending'}], default_protocol())


def test_audit_replays_fractional_witness_in_its_original_searched_scope():
    from experiments.runner import _audit_report
    from env.scenario import Scenario
    from recovery.representation import PathLibrary
    from recovery.search import recover
    cases = build_instances(Path(__file__).resolve().parents[1])
    case = next(c for c in cases if c['id']=='divisible/wind_magnitude/0')
    s = Scenario.from_dict(case['scenario'])
    r = recover(s,PathLibrary.from_dict(s,case['representation']),total_branches=128,numerical=False)
    assert r['lower_bound'] == r['upper_bound'] == 0
    assert r['witness']['exact_transfers'] == {}  # Fixed quantities are not LP variables at Level 0.
    _audit_report(case,r)
