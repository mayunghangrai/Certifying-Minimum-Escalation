"""The escalation follow-up consumes exactly eight immutable Level-2 targets."""
import importlib
import json
from pathlib import Path

import pytest


def test_exact_eight_selection_excludes_already_resolved_and_level2_open_cases():
    mod = importlib.import_module('level3.targets')
    root = Path(__file__).resolve().parents[1]/'results/level2_exhaustive_2026_10_05/v1'
    cases = mod.select_targets(root)
    assert len(cases) == 8
    assert {r['record']['case_id'] for r in cases} == {
        'CB_12_4_uniform_61004_below',
        'CB_3_3_clustered_61001_below', 'CB_3_3_clustered_61002_below', 'CB_3_3_clustered_61004_below',
        'CB_3_3_uniform_61001_below', 'CB_3_3_uniform_61002_below',
        'CB_3_3_uniform_61003_below', 'CB_3_3_uniform_61004_below',
    }


def test_level3_witness_certifies_three_but_exclusion_only_raises_lower_bound():
    mod = importlib.import_module('level3.targets')
    prior = {'excluded_levels': [0, 1, 2], 'upper': None}
    assert mod.combine_bounds(prior, {'status': 'WITNESS'})['minimum'] == 3
    excluded = mod.combine_bounds(prior, {'status': 'EMPTY'})
    assert excluded['lower'] == 4 and excluded['upper'] is None and excluded['minimum'] is None
    assert mod.combine_bounds(prior, {'status': 'UNRESOLVED'})['lower'] == 3


def test_target_selection_checks_original_run_identity(tmp_path):
    mod = importlib.import_module('level3.targets')
    root = Path(__file__).resolve().parents[1]/'results/level2_exhaustive_2026_10_05/v1'
    (tmp_path/'records').mkdir()
    (tmp_path/'manifest.json').write_bytes((root/'manifest.json').read_bytes())
    for t in mod.select_targets(root):
        r = dict(t['record'])
        if r['case_id'] == 'CB_12_4_uniform_61004_below':
            r['run_hash'] = 'substituted run'
        (tmp_path/'records'/t['path'].name).write_text(json.dumps(r))
    with pytest.raises(ValueError, match='run'):
        mod.select_targets(tmp_path)
