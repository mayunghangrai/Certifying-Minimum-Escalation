"""Only the six frozen exclusions through Level 3 enter global search."""
import importlib
import json
from pathlib import Path

import pytest

from final_benchmark.records import record_hash


def test_exact_six_selection_omits_level3_witness_and_open_case():
    mod = importlib.import_module('level4.targets')
    root = Path(__file__).resolve().parents[1]/'results/level3_certified_2026_10_05/v1'
    cases = mod.select_targets(root)
    assert {x['record']['case_id'] for x in cases} == {
        'CB_12_4_uniform_61004_below', 'CB_3_3_clustered_61001_below',
        'CB_3_3_clustered_61004_below', 'CB_3_3_uniform_61001_below',
        'CB_3_3_uniform_61002_below', 'CB_3_3_uniform_61003_below',
    }
    assert len(cases) == 6


def test_global_three_valued_semantics_include_modeled_infinity():
    mod = importlib.import_module('level4.targets')
    prior = {'excluded_levels':[0,1,2,3], 'upper':None}
    assert mod.combine_bounds(prior, {'status':'WITNESS'})['minimum'] == 4
    empty = mod.combine_bounds(prior, {'status':'EMPTY'})
    assert empty['minimum'] == 'infinity' and empty['status'] == 'infeasible'
    assert empty['excluded_levels'] == [0,1,2,3,4]
    open_result = mod.combine_bounds(prior, {'status':'UNRESOLVED'})
    assert open_result['lower'] == 4 and open_result['minimum'] is None and open_result['upper'] is None


def test_global_combination_requires_prior_exclusions_through_three():
    mod = importlib.import_module('level4.targets')
    with pytest.raises(ValueError, match='prior'):
        mod.combine_bounds({'excluded_levels':[0,1,2], 'upper':None}, {'status':'WITNESS'})
    with pytest.raises(ValueError, match='status'):
        mod.combine_bounds({'excluded_levels':[0,1,2,3], 'upper':None}, {'status':'HEURISTIC_FAILED'})


def test_six_selection_rejects_substituted_original_run(tmp_path):
    mod = importlib.import_module('level4.targets')
    root = Path(__file__).resolve().parents[1]/'results/level3_certified_2026_10_05/v1'
    (tmp_path/'records').mkdir()
    (tmp_path/'manifest.json').write_bytes((root/'manifest.json').read_bytes())
    for x in mod.select_targets(root):
        r = dict(x['record'])
        if r['case_id'] == 'CB_12_4_uniform_61004_below':
            r['run_hash'] = 'substituted run'
        (tmp_path/'records'/x['path'].name).write_text(json.dumps(r))
    with pytest.raises(ValueError, match='run'):
        mod.select_targets(tmp_path)


def test_six_selection_rejects_rehashed_changes_to_frozen_outputs(tmp_path):
    mod = importlib.import_module('level4.targets')
    root = Path(__file__).resolve().parents[1]/'results/level3_certified_2026_10_05/v1'
    (tmp_path/'records').mkdir()
    (tmp_path/'manifest.json').write_bytes((root/'manifest.json').read_bytes())
    for x in mod.select_targets(root):
        if x['record']['case_id'] == 'CB_3_3_uniform_61001_below':
            r = x['record']
            r['timing']['solve_s'] += 123
            r['record_hash'] = record_hash(r)
            (tmp_path/'records'/x['path'].name).write_text(json.dumps(r))
        else:
            (tmp_path/'records'/x['path'].name).write_bytes(x['path'].read_bytes())
    with pytest.raises(ValueError, match='frozen'):
        mod.select_targets(tmp_path)


def test_audit_reconstructs_frozen_inputs_instead_of_trusting_rehashed_manifest(tmp_path):
    mod = importlib.import_module('level4.targets')
    from recovery.local_search import digest
    prior = mod.PRIOR_ROOTS[-1]
    targets = mod.select_targets(prior)
    inputs = {x['record']['case_id']:{'file_hash':x['file_hash'], 'record_hash':x['record']['record_hash']}
              for x in targets}
    inputs['CB_3_3_uniform_61001_below']['file_hash'] = 'substituted baseline bytes'
    files = mod.source_files()
    binding = dict(budget={}, inputs=inputs, source_hash=digest(files),
                   prior_byte_hashes=mod.prior_byte_hashes(), prior_run_hash=targets[0]['record']['run_hash'],
                   prior_manifest_hash=mod.FROZEN_MANIFEST_HASH)
    manifest = dict(version='level4_target_run_v1', run_hash=digest(binding), source_files=files, **binding)
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='frozen input'):
        mod.audit_run(tmp_path)


def test_request_binding_rejects_report_from_a_different_cap():
    mod = importlib.import_module('level4.targets')
    x = mod.select_targets(mod.PRIOR_ROOTS[-1])[0]
    budget = dict(max_seconds=60, max_nodes=100000, refinements=[2,4], digits=18,
                  max_operations=100000, max_rows=10000)
    r = dict(case_id=x['record']['case_id'], baseline=x['record'],
             result={'digits':18, 'budget':{k:v for k,v in budget.items() if k != 'digits'}})
    assert mod._check_request(r, x, budget) is None
    r['result']['budget']['max_seconds'] = 120
    with pytest.raises(ValueError, match='budget'):
        mod._check_request(r, x, budget)
