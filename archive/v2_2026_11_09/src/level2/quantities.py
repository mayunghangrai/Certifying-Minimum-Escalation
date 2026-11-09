"""Exact quantity evidence for a fixed complete route skeleton.

The lower-duration problem is an optimistic relaxation and can exclude a
skeleton. The upper-duration problem can only produce a conservative mission
witness. Numerical LP solutions are proposals; every returned primal or Farkas
combination is checked over rational numbers before it becomes evidence.
"""
from fractions import Fraction

from continuous.binned import binned_guard, interval_provider
from continuous.physics import stationary_duration, stationary_guard
from env.plan import COMPONENTS, coordinates
from env.scenario import _thaw
from recovery.linear import LinearResult, rational, solve_linear, verify_exclusion
from recovery.local_search import digest
from recovery.transfers import BranchRejected, build_transfer_problem, materialize


def _validate_inputs(scenario, releases, digits):
    reason = (binned_guard if scenario.data['schema_version'] == 'wind-benchmark-v3' else stationary_guard)(scenario)
    if reason:
        raise ValueError(reason)
    if isinstance(digits, bool) or not isinstance(digits, int) or not 1 <= digits <= 60:
        raise ValueError('invalid quantity enclosure digits')
    old = coordinates(scenario.data)
    if not isinstance(releases, dict) or set(releases) != set(COMPONENTS):
        raise ValueError('release mask must contain A/S/P/L')
    for a in COMPONENTS:
        if (not isinstance(releases[a], (set, frozenset, list, tuple))
                or not set(releases[a]) <= set(old[a])
                or set(releases[a]) & set(scenario.data['commitments'][a])):
            raise ValueError('release mask contains an unknown or committed coordinate')


def _provider(scenario, digits, lower_durations):
    if lower_durations is not None:
        if (not isinstance(lower_durations, dict)
                or any(not isinstance(v, Fraction) or v < 0 for v in lower_durations.values())):
            raise ValueError('lower durations must be nonnegative rational Fractions')
        def lower(uid, path, time):
            return lower_durations.get((uid, tuple(path[0]), tuple(path[-1])), Fraction(0))
        return lower
    cache = {}
    def upper(uid, path, time):
        key = uid, tuple(tuple(p) for p in path)
        if key not in cache:
            cache[key] = stationary_duration(scenario, uid, path, digits)[1]
        return cache[key]
    return upper


def _flight_bounds(scenario, digits, lower_durations):
    """Compiler keyword: v3 upper problems use departure-aware binned intervals."""
    if lower_durations is None and scenario.data['schema_version'] == 'wind-benchmark-v3':
        return dict(interval_provider=interval_provider(scenario, digits))
    return dict(duration_provider=_provider(scenario, digits, lower_durations))


def _exact_solve(matrix, target, max_operations):
    """Repair a proposed LP basis with bounded rational Gaussian elimination."""
    rows = [list(map(Fraction, a))+[Fraction(b)] for a, b in zip(matrix, target)]
    n = len(matrix[0]) if matrix else 0
    pivot_rows, operations, top = {}, 0, 0
    for j in range(n):
        pivot = next((i for i in range(top, len(rows)) if rows[i][j]), None)
        if pivot is None:
            continue
        rows[top], rows[pivot] = rows[pivot], rows[top]
        operations += n+1-j
        if operations > max_operations:
            return None, operations
        scale = rows[top][j]
        rows[top] = [v/scale for v in rows[top]]
        for i, row in enumerate(rows):
            if i == top or not row[j]:
                continue
            operations += n+1-j
            if operations > max_operations:
                return None, operations
            scale = row[j]
            rows[i] = [a-scale*b for a, b in zip(row, rows[top])]
        pivot_rows[j] = top
        top += 1
    if any(not any(row[:n]) and row[n] for row in rows):
        return None, operations
    return tuple(rows[i][n] if j in pivot_rows else Fraction(0)
                 for j in range(n) for i in [pivot_rows.get(j, 0)]), operations


def _dual_proposal(problem, max_operations):
    """Find a nonnegative dual ray, then verify or reconstruct it exactly."""
    try:
        from scipy.optimize import linprog
        rows = problem.rows
        if not rows:
            return None, 0
        matrix = [[r.coefficients[j] for r in rows] for j in range(len(problem.variables))]
        matrix.append([r.bound for r in rows])
        target = [0]*len(problem.variables)+[-1]
        proposed = linprog([0.]*len(rows), A_eq=[list(map(float, a)) for a in matrix],
                           b_eq=target, bounds=(0, None), method='highs-ds',
                           options={'maxiter':10000, 'primal_feasibility_tolerance':1e-9,
                                    'dual_feasibility_tolerance':1e-9})
        if proposed.status != 0 or proposed.x is None:
            return None, 0
        weights = [Fraction(str(v)).limit_denominator(10**12) for v in proposed.x]
        def certificate(values):
            return dict(kind='farkas', multipliers={str(i):str(v) for i, v in enumerate(values) if v})
        proof = certificate(weights)
        if verify_exclusion(problem, proof):
            return proof, 0
        support = [i for i, v in enumerate(proposed.x) if v > 0]
        repaired, operations = _exact_solve([[row[i] for i in support] for row in matrix],
                                             target, max_operations)
        if repaired is None:
            return None, operations
        weights = [Fraction(0)]*len(rows)
        for i, v in zip(support, repaired):
            weights[i] = v
        proof = certificate(weights)
        return (proof if verify_exclusion(problem, proof) else None), operations
    except (ImportError, ValueError, TypeError, ArithmeticError):
        return None, 0


def _solve(problem, max_operations, max_rows, *, exclusion):
    # Check zero-dimensional contradictions before any LP or elimination work.
    for i, row in enumerate(problem.rows):
        if not any(row.coefficients) and row.bound < 0:
            return LinearResult('EMPTY', certificate=dict(kind='farkas',
                                multipliers={str(i):'1'}), exact=True)
    # Rationalize numerical primal proposals first, avoiding large FM systems.
    try:
        proposed = solve_linear(problem, max_operations=0, max_rows=0)
    except (ImportError, ValueError, TypeError, ArithmeticError) as error:
        proposed = LinearResult('UNRESOLVED', reason='numerical proposal unavailable: '+str(error))
    if proposed.status == 'WITNESS' and proposed.exact and problem.accepts(proposed.values):
        return proposed
    operations = 0
    if exclusion:
        certificate, operations = _dual_proposal(problem, max_operations)
        if certificate is not None:
            return LinearResult('EMPTY', certificate=certificate, exact=True, operations=operations)
    result = solve_linear(problem, max_operations=max(0, max_operations-operations),
                          max_rows=max_rows, numerical=False)
    if result.status == 'UNRESOLVED' and proposed.reason:
        return LinearResult('UNRESOLVED', reason=result.reason+'; '+proposed.reason,
                            operations=result.operations+operations)
    return result


def evaluate_quantities(scenario, plan, reserves, releases, *, lower_durations=None,
                        digits=18, max_operations=100000, max_rows=10000):
    """Return an exact exclusion, conservative witness, or unresolved result.

    A feasible lower problem is reported as WITNESS with ``relaxation=True``
    and no mission witness. Its feasibility cannot certify actual flight paths.
    Callers must independently establish that each supplied lower duration is
    valid over the entire admissible path domain for its pair of endpoints.
    """
    relaxation = lower_durations is not None
    report = dict(status='UNRESOLVED', proof=None, witness=None, reason=None,
                  relaxation=relaxation, operations=0)
    try:
        _validate_inputs(scenario, releases, digits)
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0
               for v in (max_operations, max_rows)):
            raise ValueError('quantity budgets must be nonnegative integers')
        binding = dict(scenario_hash=scenario.content_hash(), candidate_hash=digest(_thaw(plan)),
                       reserve_hash=digest(_thaw(reserves)))
        compiled = build_transfer_problem(scenario, plan, reserves, releases, exact=True,
                       **_flight_bounds(scenario, digits, lower_durations))
        result = _solve(compiled.problem, max_operations, max_rows, exclusion=relaxation)
        report['operations'] = result.operations
        if result.status == 'EMPTY':
            if relaxation and result.exact and verify_exclusion(compiled.problem, result.certificate):
                report.update(status='EMPTY', proof=dict(kind='quantity_farkas_v1', **binding,
                                                        certificate=result.certificate))
            else:
                report['reason'] = 'upper quantity problem infeasible; continuous paths remain unresolved'
        elif result.status == 'WITNESS' and result.exact and compiled.problem.accepts(result.values):
            report['status'] = 'WITNESS'
            report['values'], report['columns'] = list(map(str, result.values)), list(map(list, compiled.columns))
            if not relaxation:
                projected = materialize(compiled, result.values)
                witness = dict(kind='quantity_primal_v1', scenario_hash=scenario.content_hash(),
                               plan=projected, reserve_paths=_thaw(reserves), values=report['values'],
                               columns=report['columns'], digits=digits, candidate_hash=digest(projected),
                               reserve_hash=digest(_thaw(reserves)))
                if verify_quantity_witness(scenario, witness, releases):
                    report['witness'] = witness
                else:
                    report.update(status='UNRESOLVED', reason='quantity witness failed exact replay')
        else:
            report['reason'] = result.reason or 'no exact quantity evidence'
    except BranchRejected as error:
        if relaxation and error.exact:
            report.update(status='EMPTY', proof=dict(kind='quantity_ground_rejection_v1',
                                                    **binding, reason=str(error)))
        else:
            report['reason'] = 'upper quantity problem rejected: '+str(error)
    except (ValueError, TypeError, KeyError, ArithmeticError, ImportError, StopIteration) as error:
        report['reason'] = str(error)
    return report


def verify_quantity_witness(scenario, witness, releases):
    """Rebuild upper-enclosure constraints and check the exact rational point."""
    try:
        if (witness['kind'] != 'quantity_primal_v1'
                or witness['scenario_hash'] != scenario.content_hash()
                or witness['candidate_hash'] != digest(witness['plan'])
                or witness['reserve_hash'] != digest(witness['reserve_paths'])):
            return False
        digits = witness['digits']
        _validate_inputs(scenario, releases, digits)
        compiled = build_transfer_problem(scenario, witness['plan'], witness['reserve_paths'], releases,
                            exact=True, **_flight_bounds(scenario, digits, None))
        if witness['columns'] != list(map(list, compiled.columns)):
            return False
        if not isinstance(witness['values'], list) or not all(isinstance(v, str) for v in witness['values']):
            return False
        point = tuple(map(Fraction, witness['values']))
        if not compiled.problem.accepts(point):
            return False
        for (uid, h, a), value in zip(compiled.columns, point):
            projected = witness['plan']['routes'][uid]['deliveries' if a == 'x' else 'loads'][h]
            if isinstance(projected, bool) or projected != float(value):
                return False
        # The compiler checks unreleased coordinates against incumbent values;
        # domain validation checks inactive and ineligible transfers are zero.
        return True
    except (ValueError, TypeError, KeyError, ArithmeticError, IndexError, StopIteration):
        return False


def verify_quantity_exclusion(scenario, plan, reserves, releases, lower_durations, proof):
    """Replay a local quantity exclusion; lower-bound validity is external."""
    try:
        _validate_inputs(scenario, releases, 18)
        if (lower_durations is None or proof['scenario_hash'] != scenario.content_hash()
                or proof['candidate_hash'] != digest(_thaw(plan))
                or proof['reserve_hash'] != digest(_thaw(reserves))):
            return False
        try:
            compiled = build_transfer_problem(scenario, plan, reserves, releases, exact=True,
                        **_flight_bounds(scenario, 18, lower_durations))
        except BranchRejected as error:
            return (error.exact and proof['kind'] == 'quantity_ground_rejection_v1'
                    and proof['reason'] == str(error))
        return (proof['kind'] == 'quantity_farkas_v1'
                and verify_exclusion(compiled.problem, proof['certificate']))
    except (ValueError, TypeError, KeyError, ArithmeticError, IndexError, StopIteration):
        return False
