import copy
import pytest
from env.scenario import Scenario
from test_benchmark_contract import raw


@pytest.mark.parametrize('mutation', [
    lambda p: p['incumbent']['routes']['U1']['stops'].__setitem__(4, 'A'),
    lambda p: p['incumbent']['routes']['U1']['loads'].__setitem__(4, 1.),
    lambda p: p['incumbent']['routes']['U1']['deliveries'].__setitem__(0, .5),
    lambda p: p['incumbent']['routes']['U1']['paths'].__setitem__(0, [[1,1],[8,1]]),
    lambda p: p['incumbent']['assignment'].update(A='U2'),
    lambda p: p['incumbent']['assignment'].update(A=None),
    lambda p: p['commitments']['P'].append('U1:99'),
    lambda p: p['incumbent']['routes']['U1']['paths'].__setitem__(4, [[2,2]]),
    lambda p: p['incumbent']['routes']['U2']['deliveries'].__setitem__(1, .4),
    lambda p: p['commitments']['L'].remove('U2:1:x'),
    lambda p: p['state']['fleet']['U2'].update(mode='idle'),
])
def test_common_domain_rejects_inconsistent_slots_assignments_and_residuals(mutation):
    p=raw(); mutation(p)
    with pytest.raises(ValueError):
        Scenario.from_dict(p)


def test_repeated_visits_and_canonical_padding_are_structural_not_resource_checks():
    p=raw()
    # Overservice is a hard-constraint failure, not a structural-domain failure.
    p['incumbent']['routes']['U1']['deliveries'][1]=9.
    assert Scenario.from_dict(p).to_dict() == p
