"""Executable provenance, closed model semantics and reproducible entry point."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from env.scenario import Scenario
from test_benchmark_contract import ROOT, FIXTURES, raw


def leaf_paths(value, path=()):
    if isinstance(value, dict) and value:
        for key, item in value.items():
            yield from leaf_paths(item, (*path, key))
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            yield from leaf_paths(item, (*path, str(index)))
    else:
        yield '/'+'/'.join(path)


def matches(rule, path):
    left,right=rule.split('/'),path.split('/')
    return len(left)==len(right) and all(a=='*' or a==b for a,b in zip(left,right))


def test_every_fixture_leaf_has_one_source_assumption_and_executed_test():
    trace=json.loads((ROOT/'docs/formulation/fixture_traceability.json').read_text())
    files={p.name:p.read_text(encoding='utf-8') for p in (ROOT/'docs/formulation/2026-09-17').glob('*.tex')}
    tests={f'{p.name}::{node.name}' for p in (ROOT/'tests').glob('test_*.py') for node in ast.walk(ast.parse(p.read_text())) if isinstance(node,ast.FunctionDef) and node.name.startswith('test_')}
    used=set()
    for fixture in sorted(FIXTURES.glob('*.json')):
        for path in leaf_paths(json.loads(fixture.read_text())):
            entries=[(i,e) for i,e in enumerate(trace['fields']) if matches(e['path'],path)]
            assert len(entries)==1, (fixture.name,path,entries)
            i,entry=entries[0]; used.add(i)
            assert '\\label{'+entry['anchor']+'}' in files[entry['source']]
            assert entry['assumption'] and entry['benchmark_choice']
            assert entry['tests'] and set(entry['tests'])<=tests
    assert used==set(range(len(trace['fields']))), 'unused provenance rules hide stale fields'


def test_formulation_sources_and_fixture_bytes_are_pinned():
    sources=json.loads((ROOT/'docs/formulation/2026-09-17/sources.json').read_text())
    for name,entry in sources.items():
        assert hashlib.sha256((ROOT/'docs/formulation/2026-09-17'/name).read_bytes()).hexdigest()==entry['sha256']
    manifest=json.loads((FIXTURES/'manifest.lock').read_text())
    assert set(manifest)=={p.name for p in FIXTURES.glob('*.json')}
    for name,entry in manifest.items():
        assert hashlib.sha256((FIXTURES/name).read_bytes()).hexdigest()==entry['file_sha256']
        assert Scenario.from_json(FIXTURES/name).content_hash()==entry['content_sha256']


def test_all_cases_share_exact_geometry_state_commitments_and_incumbent():
    shared=[]
    for fixture in sorted(FIXTURES.glob('*.json')):
        p=Scenario.from_json(fixture).to_dict()
        del p['benchmark_id']; del p['wind']['received']['values']; del p['wind']['update_support']
        shared.append(p)
    assert all(p==shared[0] for p in shared)


@pytest.mark.parametrize('object_path', [
    (), ('mission',), ('state',), ('operations',), ('wind',),
    ('mission','tasks',0), ('mission','vehicles',0), ('state','fleet','U1'),
    ('state','fleet','U2','residual_operation'), ('wind','cells',0),
    ('wind','previous'), ('wind','received'), ('incumbent',),
    ('incumbent','routes','U1'), ('commitments',), ('units',),
])
@pytest.mark.parametrize('field,value', [('commodities',['food','medicine']),('no_fly_zones',[])])
def test_old_semantics_are_rejected_at_every_record_boundary(object_path,field,value):
    p=raw(); target=p
    for key in object_path: target=target[key]
    target[field]=value
    with pytest.raises(ValueError): Scenario.from_dict(p)


def test_active_runtime_cannot_import_predecessor_model_or_methods():
    forbidden_modules=['airspace','environment','entities','params','robust_scenario_generator','simulator','objective','deprivation','diagnostics']
    assert all(importlib.util.find_spec('env.'+module) is None for module in forbidden_modules)
    forbidden={'N_COMMODITIES','COMMODITY_NAMES','NoFlyZone','HazardRegion','AirspaceRestriction','WeatherRegion','EnvironmentalPacket','WindForecastPacket','torch','stable_baselines3','gurobipy','pulp'}
    for file in [*(ROOT/'src').rglob('*.py'),*(ROOT/'scripts').glob('*.py')]:
        tree=ast.parse(file.read_text(encoding='utf-8'))
        symbols={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        symbols|={n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute)}
        symbols|={n.name for n in ast.walk(tree) if isinstance(n,(ast.alias,ast.FunctionDef,ast.ClassDef))}
        assert not symbols&forbidden, (file,symbols&forbidden)
    assert not list((ROOT/'src/agents').rglob('*.py'))
    assert not list((ROOT/'src/methods').rglob('*.py'))
    for file in (ROOT/'scenarios').rglob('*.json'):
        assert file.parent in {FIXTURES,ROOT/'scenarios/diagnostics',ROOT/'scenarios/worked'}
        Scenario.from_json(file)


def test_preserved_predecessor_is_exact_non_executable_archive():
    archive=ROOT/'archive/pre_2026_09_17'
    manifest=json.loads((archive/'manifest.json').read_text())
    with zipfile.ZipFile(archive/'runtime.zip') as snapshot:
        assert set(snapshot.namelist())==set(manifest)
        assert all(hashlib.sha256(snapshot.read(name)).hexdigest()==digest for name,digest in manifest.items())
    assert not list(archive.rglob('*.py'))


def test_benchmark_cli_runs_from_another_directory_and_is_reproducible(tmp_path):
    output=tmp_path/'results.json'
    command=[sys.executable,str(ROOT/'scripts/run_simulation_benchmark.py'),'--output',str(output)]
    first=subprocess.run(command,cwd=tmp_path,capture_output=True,text=True,check=True)
    payload=output.read_bytes()
    second=subprocess.run(command,cwd=tmp_path,capture_output=True,text=True,check=True)
    assert output.read_bytes()==payload and first.stdout==second.stdout
    result=json.loads(payload)
    by_name={c['benchmark_id']:c for c in result['cases']}
    assert set(by_name)=={'local_delay','benign_update','horizon_late'}
    assert all(c['previous']['status']=='feasible' for c in by_name.values())
    assert by_name['benign_update']['received']['status']=='feasible'
    assert by_name['local_delay']['received']['status']=='infeasible'
    assert not by_name['horizon_late']['received']['complete']
    for case in by_name.values():
        assert len(case['intervention_spaces']['release_counts'])==5
        assert case['intervention_spaces']['affected_tasks']==case['diagnostic']['affected_tasks']
        assert case['intervention_spaces']['release_counts'][3]==case['intervention_spaces']['release_counts'][4]
