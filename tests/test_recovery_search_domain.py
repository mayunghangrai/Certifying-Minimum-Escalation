import copy
import json

import pytest

from env.scenario import Scenario
from env.intervention_scope import release_sets
from env.wind_dependency import diagnose_wind_update
from recovery_cases import worked
from recovery.representation import PathLibrary
from recovery.enumeration import enumerate_events


def branches(s, library, level):
    releases = release_sets(s, level, diagnose_wind_update(s).affected_tasks)
    return [event for event in enumerate_events(s, library, releases) if event is not None]


def test_manifest_is_canonical_frozen_and_bound_to_scenario():
    s = Scenario.from_dict(worked('B'))
    library = PathLibrary.build(s, nominal_paths=[[[0, 0], [.5, 0], [1, 0]]])
    assert library.to_dict() == PathLibrary.build(s).to_dict()
    restored = PathLibrary.from_dict(s, json.loads(json.dumps(library.to_dict())))
    assert restored.content_hash() == library.content_hash()
    changed = worked('B'); changed['benchmark_id'] = 'other'
    with pytest.raises(ValueError, match='scenario'):
        PathLibrary.from_dict(Scenario.from_dict(changed), library.to_dict())
    payload = library.to_dict(); payload['nominal_paths'].clear()
    assert library.to_dict()['nominal_paths']


@pytest.mark.parametrize('case,counts', [('A',[1,1,1,2,4]), ('B',[1,1,1,24,24])])
def test_enumeration_matches_worked_structural_counts(case, counts):
    s = Scenario.from_dict(worked(case)); before = s.content_hash()
    lib = PathLibrary.build(s)
    assert [len(branches(s, lib, k)) for k in range(5)] == counts
    assert s.content_hash() == before


def test_library_keeps_incumbent_curves_and_previous_return_witnesses():
    p = worked('B')
    p['reserve_paths']['U1']['1'] = [[1,0],[-1,0],[0,0]]
    s = Scenario.from_dict(p)
    lib = PathLibrary.build(s, direct=False)
    assert ((1,0),(-1,0),(0,0)) in lib.paths((1,0),(0,0), reserve=True)
    broken = lib.to_dict(); broken['return_paths'] = [[[0,0]]]
    with pytest.raises(ValueError, match='witness'):
        PathLibrary.from_dict(s, broken)


def test_declared_extra_paths_are_enumerated_at_path_level_only():
    s = Scenario.from_dict(worked('B'))
    lib = PathLibrary.build(s, nominal_paths=[[[0,0],[0,.25],[1,0]]])
    assert len(branches(s,lib,0)) == 1
    assert len(branches(s,lib,1)) == 4  # two east-going UAVs choose independently


def test_library_rejects_nonfinite_and_outside_paths():
    s = Scenario.from_dict(worked())
    for path in ([[0,0],[2,0],[1,0]], [[0,0],[float('nan'),0],[1,0]]):
        with pytest.raises(ValueError):
            PathLibrary.build(s, nominal_paths=[path])


def test_padding_belongs_to_manifest_even_without_direct_path_generation():
    s = Scenario.from_dict(worked('B'))
    lib = PathLibrary.build(s,direct=False)
    assert ((0,0),) in lib.nominal
