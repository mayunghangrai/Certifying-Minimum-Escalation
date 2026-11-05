"""Continuous feasibility with independently checked rational proof objects.

Fourier--Motzkin is deliberately bounded: it is a tiny-instance reference,
not a scalable LP implementation. Numerical HiGHS results are proposals only.
"""
from dataclasses import dataclass
from fractions import Fraction
import math


def rational(value):
    """Interpret the scenario's normalized JSON decimal, not binary float bits."""
    return Fraction(str(value))


@dataclass(frozen=True)
class Row:
    coefficients: tuple
    bound: object
    label: str


@dataclass(frozen=True)
class LinearProblem:
    variables: tuple
    rows: tuple
    exact: bool

    def accepts(self, values, *, tolerance=0):
        return (len(values) == len(self.variables)
                and all(math.isfinite(v) for v in values)
                and all(sum(a*x for a,x in zip(row.coefficients,values)) <= row.bound+tolerance
                        for row in self.rows))

    def to_dict(self):
        encode = str if self.exact else float
        return dict(variables=list(self.variables),exact=self.exact,rows=[
            dict(coefficients=list(map(encode,row.coefficients)),bound=encode(row.bound),label=row.label)
            for row in self.rows])


@dataclass(frozen=True)
class LinearResult:
    status: str
    values: tuple | None = None
    certificate: dict | None = None
    exact: bool = False
    reason: str | None = None
    operations: int = 0


def verify_exclusion(problem, certificate):
    """Check a nonnegative combination giving 0 <= a strictly negative RHS."""
    if (not problem.exact or not isinstance(certificate,dict) or certificate.get('kind') != 'farkas'
        or not isinstance(certificate.get('multipliers'),dict)):
        return False
    try:
        weights = {int(i):Fraction(v) for i,v in certificate['multipliers'].items()}
        if not weights or any(i < 0 or i >= len(problem.rows) or v < 0 for i,v in weights.items()):
            return False
        coefficients = [sum(w*problem.rows[i].coefficients[j] for i,w in weights.items())
                        for j in range(len(problem.variables))]
        bound = sum(w*problem.rows[i].bound for i,w in weights.items())
        return not any(coefficients) and bound < 0
    except (ValueError,TypeError,KeyError,ZeroDivisionError):
        return False


def _eliminate(problem, max_operations, max_rows):
    rows = [(tuple(map(Fraction,r.coefficients)),Fraction(r.bound),{i:Fraction(1)})
            for i,r in enumerate(problem.rows)]
    remaining = set(range(len(problem.variables)))
    history, operations = [], 0
    while True:
        # Keep the tightest parallel inequality; preserve its original-row proof.
        unique = {}
        for a,b,w in rows:
            if not any(a):
                if b < 0:
                    certificate = dict(kind='farkas',multipliers={str(i):str(v) for i,v in sorted(w.items()) if v})
                    if not verify_exclusion(problem,certificate):
                        return LinearResult('UNRESOLVED',reason='invalid exclusion certificate',operations=operations)
                    return LinearResult('EMPTY',certificate=certificate,exact=True,operations=operations)
                continue
            scale = abs(next(v for v in a if v))
            key = tuple(v/scale for v in a)
            if key not in unique or b/scale < unique[key][0]:
                unique[key] = (b/scale,{i:v/scale for i,v in w.items()})
        rows = [(a,b,w) for a,(b,w) in unique.items()]
        if not remaining:
            break
        if len(rows) > max_rows:
            return LinearResult('UNRESOLVED',reason='exact row budget',operations=operations)
        j = min(remaining,key=lambda j:(sum(a[j]>0 for a,_,_ in rows)*sum(a[j]<0 for a,_,_ in rows),j))
        history.append((j,rows))
        positive = [row for row in rows if row[0][j] > 0]
        negative = [row for row in rows if row[0][j] < 0]
        new = [row for row in rows if row[0][j] == 0]
        if operations+len(positive)*len(negative) > max_operations or len(new)+len(positive)*len(negative) > max_rows:
            return LinearResult('UNRESOLVED',reason='exact elimination budget',operations=operations)
        for a,b,w in positive:
            for c,d,v in negative:
                operations += 1
                left,right = -c[j],a[j]
                weights = {i:left*w.get(i,0)+right*v.get(i,0) for i in w.keys() | v.keys()}
                new.append((tuple(left*x+right*y for x,y in zip(a,c)),left*b+right*d,weights))
        rows = new
        remaining.remove(j)
    point = [Fraction(0)]*len(problem.variables)
    for j,rows in reversed(history):
        lower,upper = [],[]
        for a,b,_ in rows:
            if a[j]:
                bound = (b-sum(a[i]*point[i] for i in range(len(point)) if i != j))/a[j]
                (upper if a[j]>0 else lower).append(bound)
        lo,hi = max(lower,default=None),min(upper,default=None)
        point[j] = lo if lo is not None else min(Fraction(0),hi) if hi is not None else Fraction(0)
    if not problem.accepts(point):
        return LinearResult('UNRESOLVED',reason='exact primal verification failed',operations=operations)
    return LinearResult('WITNESS',tuple(point),dict(kind='rational_primal',values=list(map(str,point))),True,operations=operations)


def solve_linear(problem, *, max_operations=10000, max_rows=2000, numerical=True, max_iterations=10000):
    for value in (max_operations,max_rows,max_iterations):
        if isinstance(value,bool) or not isinstance(value,int) or value < 0:
            raise ValueError('linear budgets must be nonnegative integers')
    if problem.exact:
        result = _eliminate(problem,max_operations,max_rows)
        if result.status != 'UNRESOLVED' or not numerical:
            return result
    else:
        result = LinearResult('UNRESOLVED',reason='non-rational physics')
    if not numerical or max_iterations == 0:
        return result
    if not problem.variables:
        return (LinearResult('WITNESS',(),exact=False,reason='numerical feasibility only')
                if problem.accepts((),tolerance=1e-9) else result)
    from scipy.optimize import linprog
    try:
        answer = linprog([0.]*len(problem.variables),
            A_ub=[list(map(float,r.coefficients)) for r in problem.rows] or None,
            b_ub=[float(r.bound) for r in problem.rows] or None,
            bounds=[(None,None)]*len(problem.variables),method='highs-ds',
            options={'maxiter':max_iterations,'primal_feasibility_tolerance':1e-9,'dual_feasibility_tolerance':1e-9})
    except (ValueError,OverflowError,ArithmeticError) as error:
        return LinearResult('UNRESOLVED',reason=f'numerical LP unavailable: {error}',operations=result.operations)
    if answer.status != 0 or answer.x is None:
        return LinearResult('UNRESOLVED',reason=f'numerical LP status {answer.status}; no exclusion certificate',operations=result.operations)
    if problem.exact:
        point = tuple(Fraction(str(v)).limit_denominator(10**9) for v in answer.x)
        if problem.accepts(point):
            return LinearResult('WITNESS',point,dict(kind='rational_primal',values=list(map(str,point))),True,operations=result.operations)
    point = tuple(float(v) for v in answer.x)
    if problem.accepts(point,tolerance=1e-9):
        return LinearResult('WITNESS',point,exact=False,reason='numerical feasibility only',operations=result.operations)
    return LinearResult('UNRESOLVED',reason='numerical primal verification failed',operations=result.operations)
