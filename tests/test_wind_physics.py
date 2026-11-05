import copy
import math
import pytest

from env.scenario import Scenario
from test_benchmark_contract import raw


def uniform(w):
    p=raw()
    for key in ('previous','received'):
        p['wind'][key]['values']=[[list(w) for _ in range(3)] for _ in range(2)]
    p['wind']['update_support']=[]
    return Scenario.from_dict(p)


@pytest.mark.parametrize('wind,duration,energy', [
    ((0,0),.8,24.), ((2,0),2/3,20.), ((-2,0),1.,30.), ((0,6),1.,30.),
])
def test_directed_constant_airspeed_and_scalar_mass(wind,duration,energy):
    from env.route_evaluator import evaluate_path
    result=evaluate_path(uniform(wind),'U1',[[1,1],[9,1]],1.1,2.)
    assert result.status=='complete'
    assert result.duration_h==pytest.approx(duration)
    assert result.energy_wh==pytest.approx(energy)
    assert result.arrival_h==pytest.approx(1.1+duration)


def test_cell_and_time_boundaries_are_integrated_exactly():
    from env.route_evaluator import evaluate_path
    r=evaluate_path(Scenario.from_dict(raw()),'U1',[[1,1],[11,1]],1.5,2.)
    assert r.arrival_h==pytest.approx(3.1)
    assert r.energy_wh==pytest.approx(48.)
    assert [(s.cell_id,s.bin_index) for s in r.slices]==[('L',0),('R',1),('R',2)]
    assert [s.distance_km for s in r.slices]==pytest.approx([5.,4.,1.])


def test_boundary_aligned_segment_uses_lowest_cell_id_and_last_time_bin():
    from env.route_evaluator import evaluate_path
    from env.wind import WindField
    p=uniform((0,0)).to_dict()
    for key in ('previous','received'):
        p['wind'][key]['values'][0]=[[0.,2.]]*3
        p['wind'][key]['values'][1]=[[0.,-2.]]*3
    s=Scenario.from_dict(p)
    result=evaluate_path(s,'U1',[[6,1],[6,7]],3.,0.)
    assert result.duration_h==pytest.approx(.5)
    assert {r.cell_id for r in result.slices}=={'L'}
    field=WindField(s,'received')
    assert field.time_bin(2.)==1
    assert field.time_bin(8.)==2
    assert field.cell_index([6,8])==0
    with pytest.raises(ValueError): field.time_bin(8.01)


def test_horizon_equality_zero_length_and_late_unavailable_results():
    from env.route_evaluator import evaluate_path
    s=uniform((0,0))
    exact=evaluate_path(s,'U1',[[1,1],[6,1]],7.5,0.)
    assert exact.status=='complete' and exact.arrival_h==8.
    late=evaluate_path(s,'U1',[[1,1],[6,1]],7.5001,0.)
    assert late.status=='late'
    assert late.arrival_h is late.duration_h is late.energy_wh is None
    zero=evaluate_path(s,'U1',[[1,1],[1,1]],8.,0.)
    assert zero.duration_h==zero.energy_wh==0.
    assert evaluate_path(s,'U1',[[1,1]],8.01,0.).status=='late'


def test_wind_direction_and_carried_mass_change_energy_without_changing_geometry():
    from env.route_evaluator import evaluate_path
    s=uniform((2,0))
    out=evaluate_path(s,'U1',[[1,1],[9,1]],1.,2.)
    back=evaluate_path(s,'U1',[[9,1],[1,1]],1.,2.)
    empty=evaluate_path(s,'U1',[[1,1],[9,1]],1.,0.)
    assert back.duration_h==pytest.approx(1.)
    assert back.energy_wh>out.energy_wh
    assert out.energy_wh==pytest.approx(3*empty.energy_wh)


def test_polyline_turns_and_redundant_vertices_preserve_the_represented_curve():
    from env.route_evaluator import evaluate_path
    s=uniform((0,0))
    r=evaluate_path(s,'U1',[[1,1],[3,1],[3,1],[9,1],[9,5]],1.,0.)
    assert r.duration_h==pytest.approx(1.2)
    assert r.energy_wh==pytest.approx(12.)
    assert evaluate_path(s,'U1',[[1,1],[9,1],[9,5]],1.,0.).duration_h==r.duration_h


@pytest.mark.parametrize('path,start,load', [
    ([[1,1],[-1,1]],1.,0.), ([[1,1]],.9,0.), ([[1,1]],1.,[0.]),
    ([[1,1]],1.,-1.), ([[1,1]],float('inf'),0.), ([],1.,0.),
])
def test_physics_rejects_invalid_input(path,start,load):
    from env.route_evaluator import evaluate_path
    with pytest.raises(ValueError):
        evaluate_path(uniform((0,0)),'U1',path,start,load)


def test_oblique_shared_edge_uses_declared_owner_despite_midpoint_rounding():
    from env.route_evaluator import evaluate_path
    p=uniform((0,0)).to_dict()
    p['wind']['cells'][0]['polygon_xy']=[[0,0],[3.1,0],[9.2,8],[0,8]]
    p['wind']['cells'][1]['polygon_xy']=[[3.1,0],[12,0],[12,8],[9.2,8]]
    for key in ('previous','received'):
        p['wind'][key]['values'][1]=[[0.,-6.]]*3
    r=evaluate_path(Scenario.from_dict(p),'U1',[[3.1,0],[9.2,8]],1.,0.)
    assert {s.cell_id for s in r.slices}=={'L'}
    assert r.duration_h==pytest.approx(math.hypot(6.1,8)/10)
