"""The follow-up consumes the 13 frozen unresolved inputs only."""
from pathlib import Path
import importlib
import json
import pytest


def test_target_selection_is_exactly_the_frozen_twelve_plus_one():
    mod = importlib.import_module('level2.targets')
    root = Path(__file__).resolve().parents[1]/'results/continuous_paths_2026_10_05/primary'
    targets = mod.select_targets(root)
    assert len(targets) == 13
    assert sum(t['stage'] == 'cohort' for t in targets) == 12
    assert sum(t['stage'] == 'paired' for t in targets) == 1
    assert all(t['record']['result']['full_domain']['lower'] == 2 for t in targets)
    assert all(t['record']['result']['full_domain']['minimum'] is None for t in targets)


def test_level2_exclusion_and_stored_level3_witness_close_the_gap():
    mod = importlib.import_module('level2.targets')
    baseline = {'excluded_levels': [0, 1], 'upper': 3}
    result = {'status': 'EMPTY'}
    b = mod.combine_bounds(baseline, result)
    assert b['minimum'] == 3
    assert b['lower'] == b['upper'] == 3


def test_level2_exclusion_without_recovery_keeps_higher_minimum_unknown():
    mod = importlib.import_module('level2.targets')
    b = mod.combine_bounds({'excluded_levels': [0, 1], 'upper': None}, {'status': 'EMPTY'})
    assert b['minimum'] is None
    assert b['lower'] == 3
    assert b['upper'] is None


def test_selector_rejects_case_substituted_from_another_frozen_run(tmp_path):
    mod = importlib.import_module('level2.targets')
    root = Path(__file__).resolve().parents[1]/'results/continuous_paths_2026_10_05/primary'
    targets = mod.select_targets(root)
    for stage in ('cohort', 'paired'):
        (tmp_path/stage/'records').mkdir(parents=True)
        (tmp_path/stage/'manifest.json').write_bytes((root/stage/'manifest.json').read_bytes())
    for t in targets:
        (tmp_path/t['stage']/'records'/t['path'].name).write_bytes(t['path'].read_bytes())
    t = targets[0]
    path = tmp_path/t['stage']/'records'/t['path'].name
    r = json.loads(path.read_text())
    r['run_hash'] = 'a different frozen run'
    path.write_text(json.dumps(r))
    with pytest.raises(ValueError, match='frozen run'):
        mod.select_targets(tmp_path)
