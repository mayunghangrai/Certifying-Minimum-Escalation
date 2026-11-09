"""Independent analytic expectations and continuous-domain proof checks."""
from copy import deepcopy
from fractions import Fraction
import importlib

from env.scenario import Scenario
from final_benchmark.controlled import controlled_case
from test_continuous_physics import scene


def test_oracle_accepts_diagonal_outside_axis_path_library():
    oracle = importlib.import_module('continuous.oracle').ContinuousOracle(scene(), refinements=(1,))
    r = oracle.query('U1', [0, 0], [1, 1])
    assert r['path'] == [[0, 0], [1, 1]]
    assert Fraction(r['lower'])**2 < 2 < Fraction(r['upper'])**2
    assert Fraction(r['upper'])-Fraction(r['lower']) < Fraction(1, 10**14)


def test_constant_wind_bound_matches_analytic_headwind_time():
    p = scene(.6).to_dict()
    p['wind']['previous']['values'] = [[[-.6, 0]], [[-.6, 0]]]
    p['wind']['received']['values'] = [[[-.6, 0]], [[-.6, 0]]]
    p['wind']['update_support'] = []
    s = Scenario(p)
    r = importlib.import_module('continuous.oracle').ContinuousOracle(s).query('U1', [0, 0], [1, 0])
    assert Fraction(r['lower']) == Fraction(r['upper']) == Fraction(5, 2)


def test_generated_detour_meets_deadline_without_stored_bypass():
    case = controlled_case('C1', include_bypass=False)
    r = importlib.import_module('continuous.oracle').ContinuousOracle(case.scenario, refinements=(2,)).query('U1', [0, 0], [2, 0])
    assert Fraction(r['upper']) < Fraction(3, 4)
    assert any(point[1] > .25 for point in r['path'])
    assert len(r['path']) > 2


def test_optimized_interface_detour_uses_its_actual_wind_cell():
    case = controlled_case('C1', include_bypass=False)
    oracle = importlib.import_module('continuous.oracle').ContinuousOracle(case.scenario, refinements=(1,))
    path = oracle._optimize('U1', [[0, 0], [0, .2504], [2, .2504], [2, 0]])
    assert oracle._duration('U1', path)[1] < Fraction(3, 4)
    assert any(0 < p[0] < .1 for p in path)


def test_potential_bound_is_global_and_rejects_altered_values():
    potential = importlib.import_module('continuous.potential')
    s = scene(.6)
    r = potential.propose_potential(s, 'U1', [0, 0], [1, 0], refinement=2)
    assert potential.verify_potential(s, 'U1', r)
    assert 1 <= Fraction(r['lower']) <= Fraction(5, 2)
    bad = deepcopy(r)
    bad['values'] = [str(2*Fraction(v)) for v in bad['values']]
    bad['lower'] = str(2*Fraction(bad['lower']))
    assert not potential.verify_potential(s, 'U1', bad)


def test_potential_is_bound_to_wind_and_vehicle_speed():
    potential = importlib.import_module('continuous.potential')
    r = potential.propose_potential(scene(.6), 'U1', [0, 0], [1, 0], refinement=1)
    assert not potential.verify_potential(scene(.3), 'U1', r)
    p = scene(.6).to_dict()
    p['mission']['vehicles'][0]['airspeed_kmh'] = 1.2
    assert not potential.verify_potential(Scenario(p), 'U1', r)


def test_potential_mesh_cannot_omit_part_of_operating_region():
    potential = importlib.import_module('continuous.potential')
    s = scene(.6)
    r = potential.propose_potential(s, 'U1', [0, 0], [1, 0], refinement=1)
    bad = deepcopy(r)
    bad['values'].pop()
    assert not potential.verify_potential(s, 'U1', bad)


def test_uniform_wind_bound_does_not_require_an_admissible_straight_chord():
    from test_continuous_recovery import nonconvex_scene
    oracle = importlib.import_module('continuous.oracle')
    s = nonconvex_scene(0)
    path = s.to_dict()['incumbent']['routes']['U1']['paths'][0]
    r = oracle.ContinuousOracle(s).query('U1', path[0], path[-1], [path])
    assert Fraction(r['lower'])**2 < 8 < (Fraction(r['lower'])+Fraction(1, 10**17))**2
    assert Fraction(r['upper']) == 4
    assert oracle.verify_query(s, r)


def test_feasibility_proposal_avoids_detour_optimization_on_zero_wind_chord(monkeypatch):
    conic = importlib.import_module('continuous.conic')
    def unexpected(*args, **kwargs):
        raise AssertionError('zero-wind feasibility proposal needs no detour optimization')
    monkeypatch.setattr(conic, 'solve', unexpected)
    oracle = importlib.import_module('continuous.oracle')
    s = scene(.6)
    q = oracle.ContinuousOracle(s).query('U1', [-1, 0], [0, 0], bound=False)
    assert q['path'] == [[-1, 0], [0, 0]]
    assert oracle.verify_query(s, q)
