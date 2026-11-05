"""Small numerical SOCP proposal backend; its statuses are never proofs."""
import numpy as np
from scipy import sparse


def solve(q, rows, rhs, cone_sizes):
    import clarabel
    ii, jj, vv = [], [], []
    for i, row in enumerate(rows):
        for j, value in row.items():
            if value:
                ii.append(i); jj.append(j); vv.append(float(value))
    n = len(q)
    matrix = sparse.csc_matrix((vv, (ii, jj)), shape=(len(rows), n))
    cones = [clarabel.SecondOrderConeT(size) if kind == 'soc' else clarabel.NonnegativeConeT(size)
             for kind, size in cone_sizes]
    settings = clarabel.DefaultSettings()
    settings.verbose = False
    settings.max_threads = 1
    settings.max_iter = 150
    settings.tol_gap_abs = settings.tol_gap_rel = settings.tol_feas = 1e-9
    result = clarabel.DefaultSolver(sparse.csc_matrix((n, n)), np.asarray(q, dtype=float),
        matrix, np.asarray(rhs, dtype=float), cones, settings).solve()
    if str(result.status) not in ('Solved', 'AlmostSolved') or not np.all(np.isfinite(result.x)):
        raise ArithmeticError(f'conic proposal unavailable: {result.status}')
    return result.x
