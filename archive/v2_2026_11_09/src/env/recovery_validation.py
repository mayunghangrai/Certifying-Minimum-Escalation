"""One-sided validation of external recovery witnesses, without plan search."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .fixed_plan import evaluate_plan
from .intervention_scope import _level, release_sets
from .plan import COMPONENTS, coordinates
from .scenario import _thaw
from .wind_dependency import diagnose_wind_update


@dataclass(frozen=True)
class RecoveryReport:
    status: str
    requested_level: int
    scenario_hash: str
    candidate_hash: str | None
    structure: dict
    commitments: dict
    scope: dict
    mission: dict
    reserves: dict
    feasible_level_upper_bound: int | None
    minimum_certified: bool
    diagnostic: object

    def to_dict(self):
        return {**{key:getattr(self,key) for key in (
            'status','requested_level','scenario_hash','candidate_hash','structure','commitments',
            'scope','mission','reserves','feasible_level_upper_bound','minimum_certified')},
            'diagnostic':self.diagnostic.to_dict(),
            'claim': 'A validated candidate gives a feasible level upper bound; no lower level is excluded.',
            'numerical_model': 'Floating-point evaluation; resource/deadline tolerance 1e-9 in the declared units.'}


def validate_recovery_plan(scenario, candidate, level, *, reserve_paths):
    """Combine domain, commitments, automatic scope, mission and reserve checks.

    A failed candidate never proves an empty intervention space. Report the
    tightest membership level for this witness only when it also succeeds at
    the requested level. Invalid reserve input is rejected, while the mission
    is still evaluated with missing witnesses so known failures remain visible.
    """
    level = int(_level(level))
    diagnostic = diagnose_wind_update(scenario)
    structure = dict(valid=False, violations=[])
    commitments = dict(valid=None, violations=[])
    scope = dict(allowed=None, violations=[], memberships=[None]*5, release_counts=[])
    mission = dict(status='not_evaluated', violations=[], unresolved=[])
    reserves = dict(input_valid=None, errors=[], checks={})
    candidate_hash = None

    def report(status, upper=None):
        return RecoveryReport(status,level,scenario.content_hash(),candidate_hash,structure,
                              commitments,scope,mission,reserves,upper,False,diagnostic)

    try:
        candidate = scenario.validate_candidate(candidate, enforce_commitments=False)
    except ValueError as error:
        structure['violations'].append(str(error))
        return report('rejected')
    structure['valid'] = True
    candidate_hash = hashlib.sha256(json.dumps(_thaw(candidate),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    old, new = coordinates(scenario.data), coordinates(scenario.data,candidate)
    commitments['violations'] = [f'committed:{a}:{key}' for a in COMPONENTS
        for key in sorted(scenario.data['commitments'][a]) if old[a][key] != new[a][key]]
    commitments['valid'] = not commitments['violations']
    for k in range(5):
        released = release_sets(scenario,k,diagnostic.affected_tasks)
        violations = [f'fixed:{a}:{key}' for a in COMPONENTS for key in sorted(old[a])
                      if key not in released[a] and old[a][key] != new[a][key]]
        scope['memberships'][k] = not violations
        scope['release_counts'].append({a:len(released[a]) for a in COMPONENTS})
        if k == level:
            scope.update(allowed=not violations, violations=violations)
    try:
        witnesses = scenario.validate_reserve_paths(candidate,reserve_paths)
        reserves['input_valid'] = True
    except ValueError as error:
        witnesses = {}
        reserves.update(input_valid=False,errors=[str(error)])
    try:
        evaluation = evaluate_plan(scenario,candidate,reserve_paths=witnesses,enforce_commitments=False)
    except (ArithmeticError,ValueError) as error:
        mission.update(status='unresolved',complete=False,
                       unresolved=[f'numerical:evaluation unavailable: {error}'])
        return report('unresolved' if commitments['valid'] and scope['allowed'] and reserves['input_valid'] else 'rejected')
    mission.update(status=evaluation.status,complete=evaluation.complete,
                   violations=list(evaluation.violations),unresolved=list(evaluation.unresolved),
                   evaluation=evaluation.to_dict())
    reserves['checks'] = evaluation.reserve_checks
    if not commitments['valid'] or not scope['allowed'] or not reserves['input_valid'] or evaluation.violations:
        return report('rejected')
    if evaluation.status != 'feasible':
        return report('unresolved')
    return report('witness',scope['memberships'].index(True))
