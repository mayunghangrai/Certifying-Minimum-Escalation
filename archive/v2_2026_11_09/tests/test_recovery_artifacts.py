import hashlib
import json
from pathlib import Path
import subprocess
import sys

from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update
from env.recovery_validation import validate_recovery_plan
from test_benchmark_contract import ROOT


def test_imported_sources_and_validation_examples_are_pinned_and_executable():
    provenance = json.loads((ROOT/'docs/formulation/recovery_fixture_provenance.json').read_text())
    for section in ('source_files','scenarios','candidates'):
        for path,entry in provenance[section].items():
            assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == entry.get('sha256',entry.get('file_sha256'))
            if section == 'scenarios':
                s = Scenario.from_json(ROOT/path)
                assert s.content_hash() == entry['content_sha256']
                assert diagnose_wind_update(s).previous.status == 'feasible'
    for case in ('a','b'):
        s = Scenario.from_json(ROOT/f'scenarios/worked/four_uav_case_{case}.json')
        request = json.loads((ROOT/f'examples/recovery/case_{case}_east_exchange.json').read_text())
        report = validate_recovery_plan(s,request['plan'],request['level'],reserve_paths=request['reserve_paths'])
        assert report.status == 'witness' and report.feasible_level_upper_bound == 3


def test_recovery_cli_accepts_external_candidate_and_replays_from_other_directory(tmp_path):
    output = tmp_path/'report.json'
    command = [sys.executable,str(ROOT/'scripts/validate_recovery_plan.py'),
               '--scenario',str(ROOT/'scenarios/worked/four_uav_case_a.json'),
               '--candidate',str(ROOT/'examples/recovery/case_a_east_exchange.json'),
               '--output',str(output)]
    first = subprocess.run(command,cwd=tmp_path,capture_output=True,text=True)
    assert first.returncode == 0, first.stderr
    content = output.read_bytes()
    second = subprocess.run(command,cwd=tmp_path,capture_output=True,text=True)
    assert second.returncode == 0 and first.stdout == second.stdout and output.read_bytes() == content
    report = json.loads(content)
    assert report['status'] == 'witness' and report['feasible_level_upper_bound'] == 3
    assert not report['minimum_certified']


def test_recovery_cli_rejects_malformed_input_and_never_overwrites_inputs(tmp_path):
    candidate = tmp_path/'bad.json'
    candidate.write_text('{"plan":{},"level":3,"reserve_paths":{}}')
    output = tmp_path/'report.json'
    command = [sys.executable,str(ROOT/'scripts/validate_recovery_plan.py'),
               '--scenario',str(ROOT/'scenarios/worked/four_uav_case_a.json'),
               '--candidate',str(candidate)]
    result = subprocess.run(command+['--output',str(output)],capture_output=True,text=True)
    assert result.returncode == 1 and json.loads(output.read_text())['status'] == 'rejected'
    original = candidate.read_bytes()
    result = subprocess.run(command+['--output',str(candidate)],capture_output=True,text=True)
    assert result.returncode == 2 and candidate.read_bytes() == original


def test_benchmark_cli_uses_empty_automatic_seed_for_irrelevant_wind(tmp_path):
    output = tmp_path/'result.json'
    command = [sys.executable,str(ROOT/'scripts/run_simulation_benchmark.py'),'--scenario',
               str(ROOT/'scenarios/diagnostics/irrelevant_wind.json'),'--output',str(output)]
    result = subprocess.run(command,cwd=tmp_path,capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    case = json.loads(output.read_text())['cases'][0]
    assert case['diagnostic']['affected_tasks'] == []
    assert case['intervention_spaces']['release_counts'][3]['A'] == 0
    assert case['intervention_spaces']['release_counts'][4]['A'] == 4
