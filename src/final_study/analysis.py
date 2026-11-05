"""Tables, figures and the report of the final study.

Scoring follows the comparison protocol: every arm is scored against the pooled
reference (the 600 s CMI label's proven lower bound, and the lowest level of any
plan from the label or any arm). Shares carry 95% intervals from a bootstrap over
missions. The required level is modelled by an interval-censored proportional-odds
regression on the six factors with errors clustered by mission.
"""
from collections import Counter, defaultdict
import csv
import json
import math
from pathlib import Path
import random
import statistics

from .stages import fs_long_missions

LEVELS = (0, 1, 2, 3, 4, 5)       # 5 = no continuation
NAMES = {0: '0', 1: '1', 2: '2', 3: '3', 4: '4', 5: 'none'}
BOOT = 2000


def _code(value):
    return 5 if value == 'infinity' else value


def _bracket(bounds):
    """(lower, upper) as level codes; upper None when no plan is known."""
    if bounds['minimum'] == 'infinity':
        return 5, 5
    lower = 5 if bounds['lower'] is None else bounds['lower']
    return lower, bounds['upper']


def _certificate_cpu(result):
    """CPU time at which the arm's bracket closed (a certified minimum or no continuation)."""
    excluded, upper = set(result.get('transferred', ())), None
    for e in result['events']:
        if e['kind'] == 'proof':
            excluded.update(range(e['level']+1))
        elif e['kind'] == 'plan' and e.get('cpu_s') is not None:
            upper = e['level'] if upper is None else min(upper, e['level'])
        else:
            continue
        lower = 1+max(excluded, default=-1)
        if lower == 5 or (upper is not None and upper == lower):
            return e['cpu_s']
    return None


def _first_plan_cpu(result):
    times = [e['cpu_s'] for e in result['events'] if e['kind'] == 'plan' and e.get('cpu_s') is not None]
    return min(times) if times else None


def _plan_at_level_cpu(result, level):
    times = [e['cpu_s'] for e in result['events'] if e['kind'] == 'plan' and e.get('level') == level
             and e.get('cpu_s') is not None]
    return min(times) if times else None


# ---- loading ---------------------------------------------------------------------------
def load(store):
    """Instances with their factors and labels, and arena rows per (group, budget)."""
    instances = {}
    screening = []
    for path in store.all('fs', 'missions'):
        item = store.load('fs', 'missions', path.name[:-len('.json.gz')])
        ledger = item['ledger']
        screening.append(dict(mission=item['mission'], m=ledger['m'], k=ledger['k'], sigma=ledger['sigma'],
                              beta=ledger['beta'], status=ledger['status'],
                              outcomes=Counter(a.get('outcome') for a in ledger['attempts'])))
        for vid, info in ledger.get('variants', {}).items():
            instances[vid] = dict(group='fs', instance=vid, mission=item['mission'], m=ledger['m'], k=ledger['k'],
                                  sigma=ledger['sigma'], beta=ledger['beta'], family=ledger['family'],
                                  strength=info['strength'], time=info['time'], u0=len(info['affected']))
    selection = store.load('ls', 'selection', 'selection')
    if selection is not None:
        for cls, names in list(selection['selection']['selected'].items())+[('hard', selection['selection']['hard'])]:
            for name in names:
                draw = store.load('ls', 'draws', name)['ledger']
                instances[name] = dict(group='ls', instance=name, mission=name, m=draw['fleet'], k=draw['k'],
                                       sigma=draw['sigma'], beta=draw['beta'], family=draw['family'],
                                       strength=draw['strength'], time=draw['time'], u0=len(draw.get('affected', [])),
                                       ls_class=cls, recipe=draw['recipe'], target=draw['target'])
    for group in ('fs', 'ls', 'p1', 'fs_d1'):
        for path in store.all(group, 'labels'):
            name = path.name[:-len('.json.gz')]
            record = store.load(group, 'labels', name)
            row = instances.setdefault(name, dict(group=group, instance=name, mission=name.rsplit('_r', 1)[0]))
            result = record['result']
            # LS labels pooled with their draw's construction witness use the pooled bounds.
            lower, upper = _bracket((record.get('pooled') or {}).get('bounds') or result['bounds'])
            row['label_pooled'] = record.get('pooled') is not None and (
                record['pooled']['bounds'] != result['bounds'])
            row.update(label_lower=lower, label_upper=upper, label_audit=record['audit']['ok'],
                       label_cpu=result['clock']['cpu_s'], label_certificate_cpu=_certificate_cpu(result),
                       label_plan_level=result['plan_level'],
                       label_depot_stops=(record.get('decisions') or {}).get('depot_stops_added'),
                       label_sequence_edits=(record.get('decisions') or {}).get('sequence_edits'))
    arenas = defaultdict(list)
    for group in ('fs', 'ls', 'p1', 'scaling', 'contention', 'variance'):
        root = store.path/group
        if not root.exists():
            continue
        for directory in sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith('arena_')):
            tag = directory.name[len('arena_'):]
            budget_text, _, seed_text = tag.partition('_seed')
            budget = float(budget_text.rstrip('s'))
            for path in sorted(directory.glob('*.json.gz')):
                record = store.load(group, directory.name, path.name[:-len('.json.gz')])
                for arm, entry in record['arms'].items():
                    row = _arena_row(record, arm, entry)
                    row['seed'] = int(seed_text) if seed_text else 0
                    arenas[group, budget].append(row)
    return instances, arenas, screening


def _arena_row(record, arm, entry):
    result = entry['result']
    lower, upper = _bracket(result['bounds'])
    row = dict(instance=record['instance'], arm=arm, budget=record['budget_s'], lower=lower, upper=upper,
               plan_level=result['plan_level'], certified=result['bounds']['minimum'] is not None,
               minimum=_code(result['bounds']['minimum']) if result['bounds']['minimum'] is not None else None,
               first_plan_cpu=_first_plan_cpu(result), certificate_cpu=_certificate_cpu(result),
               returned_plan_cpu=(result.get('plan') or {}).get('cpu_s'),
               cpu=result['clock']['cpu_s'], wall=result['clock']['wall_s'], overrun=result['clock']['overrun_s'],
               audit_ok=entry['audit']['ok'], audit_cpu=entry['audit']['cpu_s'],
               audit_error=entry['audit'].get('error'), events=result['events'],
               categories=result['clock']['categories'], order=record['order'].index(arm))
    if entry.get('decisions'):
        row.update({f'd_{k}': v for k, v in entry['decisions'].items() if not isinstance(v, dict)})
    return row


def pooled(instances, arenas):
    """Reference bracket per instance: label lower bound, lowest plan of the label or any arm.

    Only results that replay count: an arm's plan whose audit failed is ignored, and a label
    whose audit failed contributes neither bound."""
    best = {}
    for rows in arenas.values():
        for r in rows:
            if r['plan_level'] is not None and r['audit_ok']:
                best[r['instance']] = min(best.get(r['instance'], 9), r['plan_level'])
    out = {}
    for name, row in instances.items():
        if 'label_lower' not in row:
            continue
        lower, upper = (row['label_lower'], row['label_upper']) if row['label_audit'] else (0, None)
        if name in best:
            upper = best[name] if upper is None else min(upper, best[name])
        minimum = 5 if lower == 5 else lower if upper is not None and upper == lower else None
        out[name] = dict(lower=lower, upper=upper, minimum=minimum)
    return out


# ---- statistics ------------------------------------------------------------------------
def bootstrap(rows, statistic, cluster='mission', reps=BOOT, seed=1):
    """Percentile 95% interval of ``statistic(rows)`` resampling clusters with replacement."""
    groups = defaultdict(list)
    for r in rows:
        groups[r[cluster]].append(r)
    keys = sorted(groups)
    point = statistic(rows)
    if point is None or len(keys) < 2:
        return point, None, None
    rng = random.Random(seed)
    values = []
    for _ in range(reps):
        sample = [r for key in (rng.choice(keys) for _ in keys) for r in groups[key]]
        value = statistic(sample)
        if value is not None:
            values.append(value)
    if not values:
        return point, None, None
    values.sort()
    return point, values[int(.025*len(values))], values[min(len(values)-1, int(.975*len(values)))]


def share(predicate):
    def statistic(rows):
        return sum(1 for r in rows if predicate(r))/len(rows) if rows else None
    return statistic


def quantile(values, q):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    position = q*(len(values)-1)
    lo, hi = math.floor(position), math.ceil(position)
    return values[lo]+(values[hi]-values[lo])*(position-lo)


def fmt(value, digits=2):
    if value is None:
        return '-'
    if isinstance(value, float):
        return f'{value:.{digits}f}'
    return str(value)


def ci(point, lo, hi, percent=True):
    if point is None:
        return '-'
    if percent:
        text = f'{100*point:.1f}%'
        return text if lo is None else f'{text} [{100*lo:.1f}, {100*hi:.1f}]'
    text = f'{point:.2f}'
    return text if lo is None else f'{text} [{lo:.2f}, {hi:.2f}]'


def ordinal_regression(rows, factors, reference, interactions=()):
    """Interval-censored proportional odds: P(L <= Y <= U) with Y in 0..5 (5 = none).

    ``factors`` = [(name, levels)], dummy-coded against ``reference[name]``; ``interactions``
    = [(name, name)] adds the products of their dummies, each pair tested jointly by a Wald
    test. Errors are clustered by mission (sandwich estimator from per-mission score
    contributions).
    """
    import numpy as np
    from scipy.optimize import minimize
    from scipy.stats import chi2
    dummies = {name: [(name, level) for level in levels if level != reference[name]] for name, levels in factors}
    columns = [(term,) for name, _ in factors for term in dummies[name]]
    columns += [(x, y) for a, b in interactions for x in dummies[a] for y in dummies[b]]
    X = np.array([[1. if all(str(r[name]) == str(level) for name, level in column) else 0. for column in columns]
                  for r in rows])
    L = np.array([r['y_lower'] for r in rows])
    U = np.array([r['y_upper'] for r in rows])
    clusters = [r['mission'] for r in rows]
    p, cuts = X.shape[1], 5

    def unpack(theta):
        beta = theta[:p]
        alpha = np.concatenate([[theta[p]], theta[p]+np.cumsum(np.exp(theta[p+1:]))])
        return beta, alpha

    def contributions(theta):
        beta, alpha = unpack(theta)
        eta = X@beta
        def cdf(k):
            out = np.ones_like(eta)
            mask = k < cuts
            index = np.clip(k, 0, cuts-1)
            value = 1/(1+np.exp(-(alpha[index]-eta)))
            return np.where(k < 0, 0., np.where(mask, value, 1.))
        probability = cdf(U)-cdf(L-1)
        return np.log(np.clip(probability, 1e-300, None))

    def objective(theta):
        return -contributions(theta).sum()

    def gradient(theta):
        """Exact gradient of ``objective`` (amended 19 October: with finite differences BFGS
        stopped at the optimum on a precision-loss warning and reported no convergence)."""
        beta, alpha = unpack(theta)
        eta = X@beta

        def at(k):
            index = np.clip(k, 0, cuts-1)
            finite = (k >= 0) & (k < cuts)
            value = np.where(k < 0, 0., np.where(k < cuts, 1/(1+np.exp(-(alpha[index]-eta))), 1.))
            return value, np.where(finite, value*(1-value), 0.), finite, index
        upper, f_upper, finite_upper, i_upper = at(U)
        lower, f_lower, finite_lower, i_lower = at(L-1)
        probability = np.clip(upper-lower, 1e-300, None)
        g_beta = X.T@((f_lower-f_upper)/probability)
        g_alpha = np.zeros(cuts)
        np.add.at(g_alpha, i_upper[finite_upper], (f_upper/probability)[finite_upper])
        np.add.at(g_alpha, i_lower[finite_lower], -(f_lower/probability)[finite_lower])
        # alpha_j = theta_p + sum of exp(theta_{p+m}) for m = 1..j
        g_cuts = np.array([g_alpha.sum()]+[np.exp(theta[p+m])*g_alpha[m:].sum() for m in range(1, cuts)])
        return -np.concatenate([g_beta, g_cuts])
    start = np.concatenate([np.zeros(p), [-1.], np.zeros(cuts-1)])
    fit = minimize(objective, start, jac=gradient, method='BFGS', options=dict(maxiter=2000))
    theta = fit.x
    # Numerical Hessian and per-observation scores for the clustered sandwich.
    h = 1e-5
    n_params = len(theta)
    scores = np.zeros((len(rows), n_params))
    for j in range(n_params):
        step = np.zeros(n_params)
        step[j] = h
        scores[:, j] = (contributions(theta+step)-contributions(theta-step))/(2*h)
    hessian = np.zeros((n_params, n_params))
    for j in range(n_params):
        step = np.zeros(n_params)
        step[j] = h
        hessian[:, j] = (scores_total(contributions, theta+step, h) - scores_total(contributions, theta-step, h))/(2*h)
    information = -hessian
    try:
        inverse = np.linalg.inv(information)
    except np.linalg.LinAlgError:
        inverse = np.linalg.pinv(information)
    meat = np.zeros((n_params, n_params))
    by_cluster = defaultdict(lambda: np.zeros(n_params))
    for c, s in zip(clusters, scores):
        by_cluster[c] += s
    for s in by_cluster.values():
        meat += np.outer(s, s)
    covariance = inverse@meat@inverse
    out = []
    for j, column in enumerate(columns):
        se = math.sqrt(max(covariance[j, j], 0.))
        out.append(dict(factor=' x '.join(name for name, _ in column), level=' x '.join(str(level) for _, level in column),
                        coef=float(theta[j]), se=se, odds_ratio=math.exp(theta[j]), z=float(theta[j])/se if se else None))
    tests = []
    for a, b in interactions:
        block = [j for j, column in enumerate(columns) if [name for name, _ in column] == [a, b]]
        coef = theta[block]
        statistic = float(coef@np.linalg.pinv(covariance[np.ix_(block, block)])@coef)
        tests.append(dict(factors=f'{a} x {b}', df=len(block), wald=statistic, p=float(chi2.sf(statistic, len(block)))))
    return dict(converged=bool(fit.success), max_gradient=float(np.max(np.abs(gradient(theta)))), n=len(rows),
                clusters=len(by_cluster), coefficients=out, interaction_tests=tests, log_likelihood=float(-fit.fun))


def scores_total(contributions, theta, h):
    import numpy as np
    n_params = len(theta)
    out = np.zeros(n_params)
    for j in range(n_params):
        step = np.zeros(n_params)
        step[j] = h
        out[j] = (contributions(theta+step).sum()-contributions(theta-step).sum())/(2*h)
    return out


def r1_strata(store, config):
    """R1 outcome of each scaling mission (``scaling.r1_source``): 'level k' (lowest witness) or
    'unresolved' (no witness within R1's 60 s), and whether the regenerated scenario is R1's
    (None if not generated here). Empty when no source is configured."""
    import gzip
    from env.scenario import Scenario
    source = config.get('scaling', {}).get('r1_source')
    if not source:
        return {}
    out = {}
    for path in sorted((Path(source)/'records').glob('*.json.gz')):
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            record = json.load(stream)
        if record['scenario'] is None:
            continue
        upper = record['screen']['full_domain']['upper']
        if record['level2'] and record['level2']['status'] == 'WITNESS':
            upper = 2 if upper is None else min(upper, 2)
        mine = store.load('scaling', 'missions', record['mission'])
        same = None
        if mine is not None and mine['payload'] is not None:
            same = Scenario(mine['payload']).content_hash() == Scenario(record['scenario']).content_hash()
        out[record['mission']] = dict(r1='unresolved' if upper is None else f'level {upper}', same_scenario=same)
    return out


# ---- report ------------------------------------------------------------------------------
FACTORS = (('m', 'Fleet size'), ('k', 'Tasks per UAV'), ('sigma', 'Slack level'), ('beta', 'Battery margin'),
           ('strength', 'Wind strength'), ('time', 'Update time'))
ORDER = dict(m=['4', '6', '8'], k=['2', '3', '4'], sigma=['tight', 'medium', 'loose'],
             beta=['tight', 'medium', 'ample'], strength=['2/5', '3/5', '4/5'], time=['0', '1/4', '1/2'])
CMI_ARMS = ('CMI', 'noAF', 'noER')


def _table(header, rows):
    lines = ['| '+' | '.join(header)+' |', '|'+'|'.join('---' if i == 0 else '---:' for i in range(len(header)))+'|']
    lines += ['| '+' | '.join(str(c) for c in row)+' |' for row in rows]
    return '\n'.join(lines)


def _level_name(code):
    return 'unresolved' if code is None else NAMES[code]


def _with_reference(instances, ref, group):
    rows = []
    for name, row in instances.items():
        if row.get('group') != group or name not in ref:
            continue
        r = dict(row)
        r.update(ref_lower=ref[name]['lower'], ref_upper=ref[name]['upper'], ref_min=ref[name]['minimum'])
        rows.append(r)
    return rows


def _five_metrics(rows):
    """The five reference metrics for a set of labelled instances."""
    n = len(rows)
    if not n:
        return None
    label_certified = [r for r in rows if r['label_lower'] == 5 or r['label_upper'] == r['label_lower']]
    pooled_certified = [r for r in rows if r['ref_min'] is not None]
    recoverable = [r for r in rows if r['ref_upper'] is not None and r['ref_upper'] <= 4]      # a plan replays
    with_plan = [r for r in rows if r.get('label_plan_level') is not None]
    return dict(n=n, certification=len(label_certified)/n, pooled_certification=len(pooled_certified)/n,
                unresolved=1-len(label_certified)/n,
                levels={_level_name(c): sum(1 for r in rows if r['ref_min'] == c)/n for c in (*LEVELS, None)},
                certificate_cpu_median=quantile([r['label_certificate_cpu'] for r in label_certified], .5),
                certificate_cpu_p90=quantile([r['label_certificate_cpu'] for r in label_certified], .9),
                recovery_all=len(with_plan)/n,
                recovery_recoverable=(sum(1 for r in recoverable if r.get('label_plan_level') is not None)/len(recoverable)
                                      if recoverable else None),
                unrecoverable=sum(1 for r in rows if r['ref_min'] == 5)/n)


def _arm_rows(arenas, group, budget, keep=None):
    rows = [r for r in arenas.get((group, float(budget)), []) if keep is None or r['instance'] in keep]
    by_arm = defaultdict(list)
    for r in rows:
        by_arm[r['arm']].append(r)
    return by_arm


def _attach(rows, instances, ref):
    out = []
    for r in rows:
        x = _within_budget(r)
        inst = instances.get(r['instance'], {})
        x['mission'] = inst.get('mission', r['instance'])
        for key in ('m', 'k', 'sigma', 'beta', 'strength', 'time', 'u0', 'ls_class'):
            x[key] = inst.get(key)
        rr = ref.get(r['instance'])
        x['ref_lower'] = rr['lower'] if rr else None
        x['ref_upper'] = rr['upper'] if rr else None
        x['ref_min'] = rr['minimum'] if rr else None
        x['at_min'] = (x['plan_level'] is not None and x['ref_min'] is not None and x['plan_level'] == x['ref_min'])
        out.append(x)
    return out


def _within_budget(row):
    """Score an arena run at the inclusive CPU cutoff from the plan it returned.

    Only the returned plan is stored and replayed, so the run has a plan by the cutoff
    only if that plan replays and was returned at cpu_s <= budget. Plan events below its
    level (found but not returned), and every plan event of a run without one, are
    dropped and counted in ``unreturned_better_plan``; proofs count at the cutoff. Edit
    counts describe the returned plan and are dropped with it.
    """
    returned = (row['audit_ok'] and row['plan_level'] is not None and row.get('returned_plan_cpu') is not None
                and row['returned_plan_cpu'] <= row['budget'])
    timely = [e for e in row['events'] if row['audit_ok'] and e.get('cpu_s') is not None
              and e['cpu_s'] <= row['budget']]
    events = [e for e in timely if e['kind'] != 'plan' or (returned and e['level'] >= row['plan_level'])]
    lower = max((e['level']+1 for e in events if e['kind'] == 'proof'), default=0)
    upper = row['plan_level'] if returned else None
    minimum = 5 if lower == 5 else lower if upper == lower else None
    out = dict(row, events=events, lower=lower, upper=upper, minimum=minimum,
               plan_level=upper, certified=minimum is not None,
               first_plan_cpu=_first_plan_cpu(dict(events=events)),
               certificate_cpu=_certificate_cpu(dict(events=events)),
               unreturned_better_plan=int(any(e['kind'] == 'plan' and (upper is None or e['level'] < upper)
                                              for e in timely)),
               late_plan_events=sum(e['kind'] == 'plan' and e.get('cpu_s') is not None
                                    and e['cpu_s'] > row['budget'] for e in row['events']),
               late_certificates=int(row['certificate_cpu'] is not None
                                     and row['certificate_cpu'] > row['budget']))
    if not returned:
        out = {k: v for k, v in out.items() if not k.startswith('d_')}
    return out


def _arm_summary(rows):
    n = len(rows)
    known = [r for r in rows if r['ref_min'] is not None and r['ref_min'] <= 4]
    recoverable = [r for r in rows if r['ref_upper'] is not None and r['ref_upper'] <= 4]
    plans = [r for r in rows if r['plan_level'] is not None]
    above = [r['plan_level']-r['ref_min'] for r in plans if r['ref_min'] is not None and r['ref_min'] <= 4]
    certified = [r for r in rows if r['certified']]
    return dict(
        n=n, plan=len(plans)/n if n else None,
        plan_recoverable=(sum(1 for r in recoverable if r['plan_level'] is not None)/len(recoverable))
        if recoverable else None,
        at_min=sum(r['at_min'] for r in rows)/n if n else None,
        at_min_count=sum(r['at_min'] for r in rows), known_n=len(known),
        at_min_known=sum(r['at_min'] for r in known)/len(known) if known else None,
        above_min=statistics.mean(above) if above else None,
        certified=len(certified)/n if n else None,
        certified_level0=sum(r['minimum'] == 0 for r in certified)/n if n else None,
        certified_positive_or_none=sum(r['minimum'] > 0 for r in certified)/n if n else None,
        first_plan_median=quantile([r['first_plan_cpu'] for r in plans], .5),
        first_plan_p90=quantile([r['first_plan_cpu'] for r in plans], .9),
        cert_median=quantile([r['certificate_cpu'] for r in certified], .5),
        cert_p90=quantile([r['certificate_cpu'] for r in certified], .9),
        cpu_median=quantile([r['cpu'] for r in rows], .5),
        wall_median=quantile([r['wall'] for r in rows], .5),
        audit_ok=sum(1 for r in rows if r['audit_ok'])/n if n else None,
        overrun_count=sum(r['overrun'] > 0 for r in rows),
        overrun_max=max((r['overrun'] for r in rows), default=None),
        late_plan_events=sum(r['late_plan_events'] for r in rows),
        late_certificates=sum(r['late_certificates'] for r in rows))


def _decision_summary(rows):
    plans = [r for r in rows if r['plan_level'] is not None]
    keys = ('d_uavs_changed', 'd_uavs_changed_outside_u0', 'd_tasks_reassigned', 'd_sequence_edits',
            'd_legs_rerouted', 'd_legs_new', 'd_deliveries_changed', 'd_depot_stops_added')
    return {k[2:]: (statistics.mean(r[k] for r in plans if k in r) if any(k in r for r in plans) else None)
            for k in keys}


def _paired(by_arm, arm, key, reference='CMI'):
    """CMI minus arm on instances where both have a plan, with a bootstrap interval."""
    a = {r['instance']: r for r in by_arm.get(reference, []) if r['plan_level'] is not None and key in r}
    b = {r['instance']: r for r in by_arm.get(arm, []) if r['plan_level'] is not None and key in r}
    rows = [dict(mission=a[i]['mission'], value=a[i][key]-b[i][key]) for i in sorted(set(a) & set(b))]
    if not rows:
        return None, None, None, 0
    point, lo, hi = bootstrap(rows, lambda rs: statistics.mean(r['value'] for r in rs) if rs else None)
    return point, lo, hi, len(rows)


def _paired_all(by_arm, arm, value, statistic=statistics.mean, reference='CMI', keep=lambda a, b: True):
    """``statistic`` of value(CMI row, arm row) over instances both arms ran, with a bootstrap
    interval over missions."""
    a = {r['instance']: r for r in by_arm.get(reference, [])}
    b = {r['instance']: r for r in by_arm.get(arm, [])}
    rows = [dict(mission=a[i]['mission'], value=value(a[i], b[i])) for i in sorted(set(a) & set(b)) if keep(a[i], b[i])]
    if not rows:
        return None, None, None, 0
    point, lo, hi = bootstrap(rows, lambda rs: statistic([r['value'] for r in rs]) if rs else None)
    return point, lo, hi, len(rows)


def _paired_rates(left, right, key):
    """Rates and left-minus-right interval on common instances, clustered by mission."""
    a = {r['instance']: r for r in left}
    b = {r['instance']: r for r in right}
    names = sorted(a.keys() & b.keys())
    point, lo, hi, n = _paired_all({'left': left, 'right': right}, 'right',
                                  lambda x, y: int(x[key])-int(y[key]), reference='left')
    lc, rc = sum(a[i][key] for i in names), sum(b[i][key] for i in names)
    return dict(n=n, missions=len({a[i]['mission'] for i in names}), left_count=lc, right_count=rc,
                left_rate=lc/n if n else None, right_rate=rc/n if n else None,
                difference=point, lo=lo, hi=hi)


def _certificate_vs_first_plan(cmi, ph):
    """H3 on the same instances: median CMI CPU to certificate over median PH CPU to its first
    plan, on instances where CMI certified and PH found a plan; with coverage and timeouts."""
    ph = {r['instance']: r for r in ph}
    both = [ph[r['instance']] for r in cmi if r['instance'] in ph]
    rows = [dict(mission=r['mission'], cert=r['certificate_cpu'], first=ph[r['instance']]['first_plan_cpu'])
            for r in cmi if r['instance'] in ph and r['certified'] and r['certificate_cpu'] is not None
            and ph[r['instance']]['first_plan_cpu'] is not None]

    def ratio(rs):
        first = quantile([r['first'] for r in rs], .5)
        return quantile([r['cert'] for r in rs], .5)/first if rs and first else None
    point, lo, hi = bootstrap(rows, ratio)
    return dict(point=point, lo=lo, hi=hi, n=len(rows), instances=len(both),
                cmi_uncertified=sum(1 for r in cmi if r['instance'] in ph and not r['certified']),
                ph_no_plan=sum(1 for r in both if r['first_plan_cpu'] is None),
                cert_median=quantile([r['cert'] for r in rows], .5), first_median=quantile([r['first'] for r in rows], .5))


def _h3_text(h):
    return (f"median CMI CPU to certificate {fmt(h['cert_median'])} s over median PH CPU to its first plan "
            f"{fmt(h['first_median'])} s on the same {h['n']} of {h['instances']} instances (CMI certified and PH "
            f"found a plan): {ci(h['point'], h['lo'], h['hi'], percent=False)}x; CMI did not certify "
            f"{h['cmi_uncertified']}, PH found no plan on {h['ph_no_plan']}")


def _anytime(rows_by_arm, budget, key):
    grid = [budget*i/50 for i in range(51)]
    curves = {}
    for arm, rows in rows_by_arm.items():
        n = len(rows)
        if not n:
            continue
        if key == 'at_min':
            times = [_plan_at_level_cpu(dict(events=r['events']), r['ref_min']) if r['ref_min'] is not None else None
                     for r in rows]
        else:
            times = [r['certificate_cpu'] for r in rows]
        curves[arm] = [sum(1 for t in times if t is not None and t <= g)/n for g in grid]
    return grid, curves


def _figures(out, fs_rows, arm_sets, ls_rows):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    made = []
    colours = ['#4c72b0', '#55a868', '#c44e52', '#8172b2', '#ccb974', '#64b5cd', '#999999']
    if fs_rows:
        fig, axes = plt.subplots(2, 3, figsize=(13, 7))
        for ax, (key, title) in zip(axes.flat, FACTORS):
            levels = ORDER[key]
            bottoms = [0.]*len(levels)
            for c, colour in zip((*LEVELS, None), colours):
                values = []
                for level in levels:
                    rows = [r for r in fs_rows if str(r[key]) == level]
                    values.append(sum(1 for r in rows if r['ref_min'] == c)/len(rows) if rows else 0)
                ax.bar(levels, values, bottom=bottoms, color=colour, label=_level_name(c))
                bottoms = [a+b for a, b in zip(bottoms, values)]
            ax.set_title(title)
            ax.set_ylim(0, 1)
        axes.flat[0].legend(title='required level', fontsize=8)
        fig.suptitle('FS: required intervention level by factor (reference labels)')
        fig.tight_layout()
        fig.savefig(out/'fs_levels_by_factor.png', dpi=130)
        plt.close(fig)
        made.append('fs_levels_by_factor.png')
    for (name, budget, by_arm) in arm_sets:
        if not by_arm:
            continue
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
        for (key, ax, title) in (('at_min', axes[0], 'plan at the reference minimum'),
                                 ('certified', axes[1], 'certified (includes Level 0)')):
            grid, curves = _anytime(by_arm, budget, key)
            for (arm, values), colour in zip(sorted(curves.items()), colours):
                ax.plot(grid, values, label=arm, color=colour)
            ax.set_xlabel('CPU seconds')
            ax.set_ylabel('share of all instances')
            ax.set_title(title)
            ax.set_ylim(0, 1)
            ax.legend(fontsize=8)
        fig.suptitle(f'{name}: anytime curves at {budget:g} s')
        fig.tight_layout()
        file = f"anytime_{name.lower().replace(' ', '_')}_{int(budget)}s.png"
        fig.savefig(out/file, dpi=130)
        plt.close(fig)
        made.append(file)
    return made


def write_report(store, config):
    out = store.path/'analysis'
    out.mkdir(parents=True, exist_ok=True)
    instances, arenas, screening = load(store)
    ref = pooled(instances, arenas)
    lines = ['# Final study report', '',
             f"Run `{store.path}`; configuration `{config.get('study')}`; run hash `{store.run_hash[:16]}`.",
             f"Machine: {store.manifest['runtime']['platform']}, {store.manifest['runtime']['logical_cpus']} logical CPUs, "
             f"Python {store.manifest['runtime']['python']}, {store.manifest['runtime']['worker_processes']} workers.",
             '', 'Times are CPU seconds (process time) unless stated; shares carry 95% intervals from a bootstrap '
             f"over missions. The reference is the {config['label_budget_s']:g} s CMI label pooled with every plan "
             'any arm found. Arena outcome tables and curves score the plan each arm returned (stored and '
             'replayed) if it was returned with CPU time <= the stated budget, and proofs logged by then; '
             'plans found but not returned are not credited (Section 9c). Q1 uses all instances, including '
             'unrecoverable and unresolved ones; the known-minimum rate is a conditional secondary metric. '
             'Events after the cutoff remain in the stored records and reference evidence.', '']
    summary = dict(report=str(out/'REPORT.md'), reporting=dict(
        version='2026-10-19-review-returned-plan', outcome_cutoff='event cpu_s <= budget_s',
        outcome_plan='returned plan, replayed, returned at cpu_s <= budget_s',
        at_min_denominator='all instances', at_min_known_denominator='known reference minimum in Levels 0-4',
        bootstrap_reps=BOOT, bootstrap_seed=1))
    # Screening.
    if screening:
        accepted = [s for s in screening if s['status'] == 'accepted']
        attempts = Counter()
        for s in screening:
            attempts.update(s['outcomes'])
        total = sum(attempts.values())
        lines += ['## 1. Screening (FS generation)', '',
                  f'{len(accepted)} of {len(screening)} missions admitted after {total} update draws. '
                  'Draw outcomes (a draw is rejected unless the update breaks the plan, stays local and keeps the '
                  'previous plan feasible):', '',
                  _table(['outcome', 'draws', 'share'], [[k, v, f'{100*v/total:.1f}%'] for k, v in attempts.most_common()]), '']
        per = []
        for key, title in (('m', 'fleet size'), ('k', 'tasks per UAV'), ('sigma', 'slack'), ('beta', 'battery')):
            for value in sorted({str(x[key]) for x in screening}, key=lambda v: (len(v), v)):
                rows = [x for x in screening if str(x[key]) == value]
                draws = sum(sum(x['outcomes'].values()) for x in rows)
                ok = sum(x['status'] == 'accepted' for x in rows)
                per.append([title, value, len(rows), ok, draws, f'{100*ok/draws:.1f}%' if draws else '-'])
        lines += ['Screening by design factor (accepted missions per update draw):', '',
                  _table(['factor', 'level', 'missions', 'accepted', 'draws', 'acceptance per draw'], per), '']
        summary['screening'] = dict(missions=len(screening), accepted=len(accepted), draws=dict(attempts))
    # FS reference metrics.
    fs_rows = _with_reference(instances, ref, 'fs')
    for r in fs_rows:
        for key in ('m', 'k'):
            r[key] = str(r[key])
    if fs_rows:
        overall = _five_metrics(fs_rows)
        summary['fs'] = overall
        lines += [f"## 2. Factorial study: the five metrics ({config['label_budget_s']:g} s reference)", '',
                  f"{overall['n']} variants from {len({r['mission'] for r in fs_rows})} missions.", '',
                  _table(['metric', 'value'], [
                      ['certification rate', ci(*bootstrap(fs_rows, share(lambda r: r['label_lower'] == 5 or r['label_upper'] == r['label_lower'])))],
                      ['unresolved rate', ci(*bootstrap(fs_rows, share(lambda r: not (r['label_lower'] == 5 or r['label_upper'] == r['label_lower']))))],
                      ['certified with pooled plans', ci(*bootstrap(fs_rows, share(lambda r: r['ref_min'] is not None)))],
                      ['CPU to certificate, median / p90 (s)', f"{fmt(overall['certificate_cpu_median'])} / {fmt(overall['certificate_cpu_p90'])}"],
                      ['recovery success, all variants', ci(*bootstrap(fs_rows, share(lambda r: r.get('label_plan_level') is not None)))],
                      ['recovery success, recoverable variants', ci(overall['recovery_recoverable'], None, None)],
                      ['certified unrecoverable (no continuation)', ci(*bootstrap(fs_rows, share(lambda r: r['ref_min'] == 5)))]]), '',
                  'Required intervention level (pooled reference):', '',
                  _table(['level', 'share', 'variants', 'missions'],
                         [[_level_name(c), ci(*bootstrap(fs_rows, share(lambda r, c=c: r['ref_min'] == c))),
                           sum(1 for r in fs_rows if r['ref_min'] == c),
                           len({r['mission'] for r in fs_rows if r['ref_min'] == c})] for c in (*LEVELS, None)]), '']
        for key, title in FACTORS:
            table = []
            for level in ORDER[key]:
                rows = [r for r in fs_rows if str(r[key]) == level]
                if not rows:
                    continue
                m = _five_metrics(rows)
                table.append([level, m['n'], f"{100*m['certification']:.1f}%", f"{100*m['unresolved']:.1f}%",
                              ' / '.join(f"{100*m['levels'][_level_name(c)]:.0f}" for c in (*LEVELS, None)),
                              fmt(m['certificate_cpu_median']), f"{100*m['recovery_all']:.1f}%"])
            lines += [f'### By {title.lower()}', '',
                      _table([title, 'n', 'certified', 'unresolved', 'level 0/1/2/3/4/none/unres. (%)',
                              'median CPU to certificate (s)', 'recovery'], table), '']
        reg_rows = []
        for r in fs_rows:
            lower = r['ref_lower']
            upper = r['ref_upper'] if r['ref_upper'] is not None else 5
            if r['ref_min'] is not None:
                lower = upper = r['ref_min']
            reg_rows.append(dict(r, y_lower=lower, y_upper=upper))
        try:
            reg = ordinal_regression(reg_rows, [(k, ORDER[k]) for k, _ in FACTORS],
                                     dict(m='4', k='2', sigma='tight', beta='tight', strength='2/5', time='0'))
            summary['ordinal_regression'] = reg
            lines += ['### Ordinal regression of the required level', '',
                      'Interval-censored proportional odds (unresolved variants enter through their bracket); '
                      f"errors clustered by mission ({reg['clusters']} clusters, n = {reg['n']}, converged: {reg['converged']}, "
                      f"largest gradient {reg['max_gradient']:.1e}). "
                      'Odds ratios above 1 mean a higher required level.', '',
                      _table(['factor', 'level', 'odds ratio', 'coef', 'SE', 'z'],
                             [[c['factor'], c['level'], f"{c['odds_ratio']:.2f}", f"{c['coef']:.2f}", f"{c['se']:.2f}",
                               fmt(c['z'])] for c in reg['coefficients']]), '']
        except Exception as error:      # reported, never hidden
            lines += [f'Ordinal regression failed: {error}', '']
        try:
            pairs = [(a, b) for a in ('m', 'k', 'sigma', 'beta') for b in ('strength', 'time')]
            inter = ordinal_regression(reg_rows, [(k, ORDER[k]) for k, _ in FACTORS],
                                       dict(m='4', k='2', sigma='tight', beta='tight', strength='2/5', time='0'),
                                       interactions=pairs)
            summary['ordinal_regression_interactions'] = inter
            lines += ['### Interactions of the mission factors with strength and update time', '',
                      'The same model with every mission factor x strength and x update time term (four dummy '
                      f"products per pair); joint clustered Wald test per pair (n = {inter['n']}, "
                      f"converged: {inter['converged']}, largest gradient {inter['max_gradient']:.1e}). "
                      'No correction for the eight tests.', '',
                      _table(['interaction', 'df', 'Wald chi2', 'p'],
                             [[t['factors'], t['df'], f"{t['wald']:.2f}", f"{t['p']:.3f}"]
                              for t in inter['interaction_tests']]), '']
        except Exception as error:      # reported, never hidden
            lines += [f'Ordinal regression with interactions failed: {error}', '']
        # Targets set in advance.
        n = len(fs_rows)
        targets = []
        for c in (1, 2, 3, 4):
            count = sum(1 for r in fs_rows if r['ref_min'] == c)
            missions = len({r['mission'] for r in fs_rows if r['ref_min'] == c})
            need = 20 if c == 2 else 10
            ok = count >= .03*n and missions >= need
            targets.append([f'Level {c} >= 3% of variants and >= {need} missions', f'{100*count/n:.1f}%, {missions} missions',
                            'met' if ok else 'missed'])
        unresolved = sum(1 for r in fs_rows if not (r['label_lower'] == 5 or r['label_upper'] == r['label_lower']))/n
        targets.append([f"unresolved <= 5% at the {config['label_budget_s']:g} s reference", f'{100*unresolved:.1f}%',
                        'met' if unresolved <= .05 else 'missed'])
        lines += ['### Targets set in advance (scenario design, Section 7)', '', _table(['target', 'observed', 'verdict'], targets), '']
    # Comparison.
    long_keep = fs_long_missions(store, config) if store.all('fs', 'missions') else set()
    arena = config['arena']
    arm_sets = []
    for group, title in (('fs', 'FS'), ('ls', 'LS')):
        for budget in (arena['budget_short'], arena['budget_long']):
            by_arm = _arm_rows(arenas, group, budget)
            if not by_arm:
                continue
            by_arm = {a: _attach(rows, instances, ref) for a, rows in by_arm.items()}
            arm_sets.append((title, float(budget), by_arm))
    if arm_sets:
        lines += ['## 3. Equal-resource comparison', '']
    for title, budget, by_arm in arm_sets:
        arms = [a for a in ('GR', 'GR-c', 'LR', 'PH', 'CMI', 'noAF', 'noER') if a in by_arm]
        rows = []
        for a in arms:
            s = _arm_summary(by_arm[a])
            cmi_arm = a in CMI_ARMS
            rows.append([a, s['n'], f"{100*s['certified']:.1f}%",
                         f"{100*s['certified_level0']:.1f}%", f"{100*s['certified_positive_or_none']:.1f}%",
                         f"{100*(1-s['certified']):.1f}%" if cmi_arm else 'n/a',
                         fmt(s['at_min'] and 100*s['at_min'], 1),
                         fmt(s['at_min_known'] and 100*s['at_min_known'], 1), s['known_n'], fmt(s['above_min']),
                         f"{fmt(s['first_plan_median'])} / {fmt(s['first_plan_p90'])}",
                         f"{fmt(s['cert_median'])} / {fmt(s['cert_p90'])}",
                         f"{100*s['plan']:.1f}%", fmt(s['plan_recoverable'] and 100*s['plan_recoverable'], 1),
                         fmt(s['cpu_median']), f"{100*s['audit_ok']:.1f}%"])
        lines += [f'### {title} at {budget:g} s', '',
                  'Certification includes Level 0 for every arm: an accepted Level-0 plan needs no lower-level '
                  'exclusion. Only the CMI arms can certify positive intervention minima or no continuation. '
                  'The primary minimum-level rate uses all n instances; the conditional rate uses only the '
                  'listed known finite minima. An unresolved minimum is not a verified success, rather than '
                  'evidence that a plan is nonminimal. Outcome rates and level gaps use the returned plan if it '
                  'replays and was returned by the cutoff. Recovery success uses all instances or all reference '
                  'recoverable instances, respectively.', '',
                  _table(['arm', 'n', 'certification rate', 'Level-0 certified', 'positive/none certified',
                          'unresolved rate (CMI)', 'plan at minimum, all (%)', 'plan at minimum, known (%)', 'known n',
                          'levels above minimum', 'CPU to first plan, median / p90 (s)',
                          'CPU to certificate, median / p90 (s)', 'recovery success', 'recovery, recoverable (%)',
                          'CPU used, median (s)', 'replays'], rows), '']
        times = []
        for a in arms:
            cells = [a]
            for t in ('0', '1/4', '1/2'):
                rs = [r for r in by_arm[a] if r.get('time') == t]
                at = f"{100*sum(r['at_min'] for r in rs)/len(rs):.0f}%" if rs else '-'
                cert = f"{100*sum(r['certified'] for r in rs)/len(rs):.0f}%" if rs else ''
                cells.append(at+(' / '+cert if cert else ''))
            times.append(cells)
        lines += ['By update time: plan at the minimum / certified (all instances in each time group):', '',
                  _table(['arm', 't = 0', 't = 1/4 makespan', 't = 1/2 makespan'], times), '']
        dec = []
        for a in arms:
            d = _decision_summary(by_arm[a])
            dec.append([a]+[fmt(d[k]) for k in ('uavs_changed', 'uavs_changed_outside_u0', 'tasks_reassigned',
                                               'sequence_edits', 'legs_rerouted', 'legs_new', 'deliveries_changed',
                                               'depot_stops_added')])
        lines += ['Decisions changed per plan returned by the cutoff (Q1, means):', '',
                  _table(['arm', 'UAVs changed', 'outside U0', 'tasks reassigned', 'sequence edits', 'legs re-routed',
                          'new legs', 'deliveries changed', 'depot stops added'], dec), '']
        if 'CMI' in by_arm:
            diffs = []
            for a in arms:
                if a == 'CMI':
                    continue
                cells = []
                for key in ('d_uavs_changed', 'd_tasks_reassigned', 'd_sequence_edits'):
                    point, lo, hi, n = _paired(by_arm, a, key)
                    cells.append('-' if point is None else f'{point:+.2f} [{lo:+.2f}, {hi:+.2f}] (n={n})' if lo is not None else f'{point:+.2f} (n={n})')
                diffs.append([a]+cells)
            lines += ['Paired differences, CMI minus arm, on instances where both have a plan:', '',
                      _table(['arm', 'UAVs changed', 'tasks reassigned', 'sequence edits'], diffs), '']
            # Q2 extras.
            cmi = by_arm['CMI']
            undecided = [r for r in cmi if not r['certified'] and r['upper'] is not None]
            raw_rows = arenas[title.lower(), budget]
            violations = sum(1 for r in raw_rows for e in r['events'] if e['kind'] == 'plan'
                             and r['instance'] in ref and e['level'] < ref[r['instance']]['lower'])
            proof_conflicts = sum(1 for r in raw_rows if r['arm'] in CMI_ARMS and r['instance'] in ref
                                  and ref[r['instance']]['upper'] is not None
                                  and r['lower'] > ref[r['instance']]['upper'])
            above_minimum = {a: sum(1 for r in by_arm[a] if r['plan_level'] is not None and r['ref_min'] is not None
                                   and r['plan_level'] > r['ref_min']) for a in arms}
            missed = {a: sum(1 for r in by_arm[a] if r['plan_level'] is None and r['ref_upper'] is not None
                             and r['ref_upper'] <= 4) for a in arms}
            lines += ['Certification checks (Q2):', '',
                      f"- CMI certified {100*sum(r['certified'] for r in cmi)/len(cmi):.1f}% within {budget:g} s; "
                      f"undecided with a plan: {len(undecided)} (mean bracket width "
                      f"{fmt(statistics.mean(r['upper']-r['lower'] for r in undecided) if undecided else None)}).",
                      f"- Cross-check violations (all stored events, including overruns; a plan below a proven lower bound, or a proof above a known plan): "
                      f"{violations+proof_conflicts} (target 0).",
                      '- Returned plans above the reference minimum (baselines do not claim optimality): '
                      + ', '.join(f'{a} {above_minimum[a]}' for a in arms)+'.',
                      '- No plan although the reference has one: '+', '.join(f'{a} {missed[a]}' for a in arms)+'.', '']
            # Q3 extras.
            ratios = [r['certificate_cpu'] for r in cmi if r['certified'] and r['certificate_cpu'] is not None]
            overhead = []
            for r in cmi:
                if r['certified'] and r['minimum'] is not None and r['minimum'] <= 4 and r['certificate_cpu'] is not None:
                    t = _plan_at_level_cpu(r, r['minimum'])
                    if t is not None:
                        overhead.append(r['certificate_cpu']-t)
            cats = defaultdict(list)
            for r in cmi:
                total = sum(r['categories'].values()) or 1
                for key, value in r['categories'].items():
                    cats[key].append(value/total)
            lines += ['Cost of the certificate (Q3):', '',
                      f"- CMI CPU to certificate: median {fmt(quantile(ratios, .5))} s, p90 {fmt(quantile(ratios, .9))} s.",
                      (f"- Paired with PH: {_h3_text(_certificate_vs_first_plan(cmi, by_arm['PH']))}."
                       if 'PH' in by_arm else '- PH did not run.'),
                      f"- Additional delay after the certified-level plan (the protocol's former 'proof overhead' "
                      f"statistic, unchanged): median {fmt(quantile(overhead, .5))} s, "
                      f"p90 {fmt(quantile(overhead, .9))} s. This excludes proof work before the plan and is "
                      'not the total or incremental CPU cost of proofs.',
                      '- CMI CPU by part (mean share): '+', '.join(f'{k} {100*statistics.mean(v):.0f}%' for k, v in sorted(cats.items()))+'.',
                      f"- Independent replay of a CMI result: median {fmt(quantile([r['audit_cpu'] for r in cmi], .5))} s CPU.", '']
            groups = []
            for key, label in (('m', 'fleet size'), ('k', 'tasks per UAV'), ('ref_min', 'reference minimum')):
                values = sorted({r[key] for r in cmi if r.get(key) is not None}, key=str)
                for value in values:
                    rs = [r for r in cmi if r.get(key) == value]
                    times = [r['certificate_cpu'] for r in rs if r['certified']]
                    groups.append([label, _level_name(value) if key == 'ref_min' else value, len(rs),
                                   f"{100*len(times)/len(rs):.0f}%", fmt(quantile(times, .5)), fmt(quantile(times, .9)),
                                   fmt(quantile([r['wall'] for r in rs], .5))])
            lines += ['CMI by group (Q3):', '',
                      _table(['grouping', 'value', 'instances', 'certified', 'CPU to certificate median (s)',
                              'p90 (s)', 'wall median (s)'], groups), '']
            by_time = []
            for a in arms:
                if a == 'CMI':
                    continue
                cells = [a]
                for t in ('0', '1/4', '1/2'):
                    sub = {x: [r for r in by_arm[x] if r.get('time') == t] for x in ('CMI', a)}
                    point, lo, hi, n = _paired(sub, a, 'd_uavs_changed')
                    cells.append('-' if point is None else f'{point:+.2f} (n={n})')
                by_time.append(cells)
            lines += ['UAVs changed, CMI minus arm, by update time (Q1):', '',
                      _table(['arm', 't = 0', 't = 1/4 makespan', 't = 1/2 makespan'], by_time), '']
            summary.setdefault('comparison', {})[f'{title}_{budget:g}'] = {a: _arm_summary(by_arm[a]) for a in arms}
    # Primary endpoints.
    fs_short = next((b for t, bud, b in arm_sets if t == 'FS' and bud == float(arena['budget_short'])), None)
    fs_long = next((b for t, bud, b in arm_sets if t == 'FS' and bud == float(arena['budget_long'])), None)
    if fs_short:
        lines += ['### Primary endpoints', '',
                  'Q1 uses all FS variants, matching the protocol and anytime curves. The conditional '
                  'known-minimum rate is shown separately; previous reports used it as Q1. Q2 includes '
                  'Level-0 certificates for every arm.', '']
        rows = []
        primary = {}
        for a in sorted(fs_short):
            known = [r for r in fs_short[a] if r['ref_min'] is not None and r['ref_min'] <= 4]
            all_ci = bootstrap(fs_short[a], share(lambda r: r['at_min']))
            known_ci = bootstrap(known, share(lambda r: r['at_min'])) if known else (None, None, None)
            cert_ci = bootstrap(fs_short[a], share(lambda r: r['certified']))
            primary[a] = dict(n=len(fs_short[a]), known_n=len(known), at_min=all_ci,
                              at_min_known=known_ci, certified=cert_ci)
            rows.append([a, len(fs_short[a]), ci(*all_ci), len(known), ci(*known_ci), ci(*cert_ci)])
        summary['primary_endpoints'] = primary
        lines += [_table(['arm', 'all n', f"Q1: plan at minimum, all ({arena['budget_short']} s)",
                          'known n', 'plan at minimum, known (secondary)',
                          f"Q2: certified ({arena['budget_short']} s)"], rows), '']
        if fs_long and 'CMI' in fs_long:
            lines += [f"Q2 on the random third at {arena['budget_long']} s: CMI certified "
                      f"{ci(*bootstrap(fs_long['CMI'], share(lambda r: r['certified'])))}.", '']
            matched = _paired_rates(fs_long['CMI'], fs_short.get('CMI', []), 'certified')
            summary['matched_budget_certification'] = matched
            if matched['n']:
                lines += [f"On the same {matched['n']} instances from {matched['missions']} missions, CMI "
                          f"certified {matched['right_count']}/{matched['n']} ({100*matched['right_rate']:.1f}%) "
                          f"at {arena['budget_short']} s and {matched['left_count']}/{matched['n']} "
                          f"({100*matched['left_rate']:.1f}%) at {arena['budget_long']} s. Paired increase: "
                          f"{ci(matched['difference'], matched['lo'], matched['hi']).replace('%', '')} "
                          'percentage points.', '']
            if 'PH' in fs_long:
                paired = {}
                rows = []
                for name, keep in [('all', lambda r: True),
                                   ('known', lambda r: r['ref_min'] is not None and r['ref_min'] <= 4)]:
                    result = _paired_rates([r for r in fs_long['CMI'] if keep(r)],
                                           [r for r in fs_long['PH'] if keep(r)], 'at_min')
                    paired[name] = result
                    rows.append([name, result['n'], result['missions'], result['left_count'],
                                 result['right_count'], ci(result['difference'], result['lo'], result['hi']).replace('%', '')])
                summary['paired_60s_cmi_ph'] = paired
                lines += [f"Paired CMI minus PH at {arena['budget_long']} s (exploratory comparison added "
                          'on 19 October; mission-cluster bootstrap, rate differences in percentage points):', '',
                          _table(['denominator', 'n', 'missions', 'CMI at minimum', 'PH at minimum',
                                  'difference, 95% interval'], rows), '',
                          'An interval including zero does not establish superiority. This comparison is '
                          'separate from the prespecified short-budget H1 test.', '']
    hyp = config.get('hypotheses')
    if fs_short and hyp:
        cmi = fs_short.get('CMI', [])
        verdicts = []
        def at_min(a):
            rows = fs_short.get(a, [])
            return sum(r['at_min'] for r in rows)/len(rows) if rows else None
        if 'GR' in fs_short:
            point, lo, hi, n = _paired(fs_short, 'GR', 'd_uavs_changed')
            verdicts.append(['H1', 'GR changes more UAVs than CMI (CMI minus GR < 0)',
                             '-' if point is None else f'{point:+.2f} [{fmt(lo)}, {fmt(hi)}]',
                             'supported' if hi is not None and hi < 0 else 'not supported'])
        for a in ('LR', 'PH'):
            if a in fs_short and at_min('CMI') is not None and at_min(a) is not None:
                point, lo, hi, n = _paired_all(fs_short, a, lambda x, y: int(x['at_min'])-int(y['at_min']))
                verdicts.append(['H1', f'{a} reaches the minimum less often than CMI (paired difference > 0)',
                                 f"CMI {100*at_min('CMI'):.1f}% vs {a} {100*at_min(a):.1f}%; "
                                 f"difference {ci(point, lo, hi)} (n={n})",
                                 'supported' if lo is not None and lo > 0 else 'not supported'])
        if cmi:
            certified = sum(r['certified'] for r in cmi)/len(cmi)
            replays = sum(r['audit_ok'] for rows in fs_short.values() for r in rows)/sum(len(v) for v in fs_short.values())
            point, lo, hi = bootstrap(cmi, share(lambda r: r['certified']))
            verdicts.append(['H2', f"CMI's observed certification rate meets the {100*hyp['h2_min_certified']:.0f}% "
                             'target (point estimate)', ci(point, lo, hi),
                             'target met' if certified >= hyp['h2_min_certified'] else 'target missed'])
            verdicts.append(['H2', f"the underlying certification rate exceeds {100*hyp['h2_min_certified']:.0f}% "
                             '(lower 95% bound above it)', ci(point, lo, hi),
                             'supported' if lo is not None and lo > hyp['h2_min_certified'] else 'not established'])
            verdicts.append(['H2', 'every certificate replays and no plan contradicts a proof', f'replays {100*replays:.1f}%',
                             'supported' if replays == 1 else 'not supported'])
            h3 = _certificate_vs_first_plan(cmi, fs_short.get('PH', []))
            if h3['point'] is not None:
                verdicts.append(['H3', f"certificate within {hyp['h3_max_ratio']}x PH's time to its first plan "
                                 '(medians on the same instances; upper 95% bound within it)', _h3_text(h3),
                                 'supported' if h3['hi'] is not None and h3['hi'] <= hyp['h3_max_ratio']
                                 else 'not supported'])
            for a in ('noAF', 'noER'):
                rs = fs_short.get(a, [])
                if rs:
                    rate = sum(r['certified'] for r in rs)/len(rs)
                    dc, dc_lo, dc_hi, n = _paired_all(fs_short, a, lambda x, y: int(x['certified'])-int(y['certified']))
                    dt, dt_lo, dt_hi, m = _paired_all(
                        fs_short, a, lambda x, y: y['certificate_cpu']-x['certificate_cpu'], lambda v: quantile(v, .5),
                        keep=lambda x, y: x['certified'] and y['certified'] and x['certificate_cpu'] is not None
                        and y['certificate_cpu'] is not None)
                    verdicts.append(['H3', f'{a} costs more than CMI (fewer certificates, or a longer paired CPU to '
                                     'certificate)',
                                     f"certified {100*rate:.1f}% vs {100*certified:.1f}%, CMI minus {a} "
                                     f"{ci(dc, dc_lo, dc_hi)} (n={n}); median paired extra CPU "
                                     f"{ci(dt, dt_lo, dt_hi, percent=False)} s (n={m})",
                                     'supported' if (dc_lo is not None and dc_lo > 0) or (dt_lo is not None and dt_lo > 0)
                                     else 'not supported'])
        lines += ['### Hypotheses (directions fixed in advance; thresholds set after the pilot)', '',
                  'Comparisons between arms are paired by instance; "supported" needs the 95% bootstrap interval '
                  '(over missions) to exclude zero, or the threshold, in the stated direction.', '',
                  _table(['hypothesis', 'statement', 'observed', 'verdict'], verdicts), '']
    if arm_sets:
        figures = _figures(out, fs_rows, [(t, b, by) for t, b, by in arm_sets], None)
        if figures:
            lines += ['Figures: '+', '.join(f'`analysis/{f}`' for f in figures), '']
    # LS by class.
    ls_rows = _with_reference(instances, ref, 'ls')
    if ls_rows:
        lines += ['## 4. Level suite', '']
        table = []
        for cls in ('1', '2', '3', '4', 'infinity', 'hard'):
            rows = [r for r in ls_rows if r.get('ls_class') == cls]
            if not rows:
                continue
            table.append([cls, len(rows), len({r['mission'] for r in rows}),
                          ' '.join(f"{m}:{sum(1 for r in rows if r['m'] == m)}" for m in (4, 6, 8)),
                          ' '.join(f"{t}:{sum(1 for r in rows if r['time'] == t)}" for t in ('0', '1/4', '1/2')),
                          ' '.join(f'{k}:{v}' for k, v in Counter(r['recipe'] for r in rows).most_common()),
                          fmt(statistics.mean(r['u0'] for r in rows))])
        lines += [_table(['class', 'instances', 'base missions', 'by fleet', 'by update time', 'recipes', 'mean |U0|'], table), '']
        pooled_rows = [r for r in ls_rows if r.get('label_pooled')]
        if pooled_rows:
            lines += [f"Pooled with the construction's witness (its Level-4 plan with the label's exclusions): "
                      f"{len(pooled_rows)} instance(s), " + ', '.join(f"{r['instance']} ({r.get('ls_class')})" for r in pooled_rows)
                      + '.', '']
        level2 = [r for r in ls_rows if r.get('ls_class') == '2']
        if level2:
            depot = sum(1 for r in level2 if (r.get('label_depot_stops') or 0) > 0)
            lines += [f'Level-2 mechanism (from the reference plan): {depot} add a depot stop (recharge or reload), '
                      f'{len(level2)-depot} only reorder.', '']
        for title, budget, by_arm in arm_sets:
            if title != 'LS':
                continue
            rows = []
            for cls in ('1', '2', '3', '4', 'infinity', 'hard'):
                cells = [cls]
                for a in ('GR', 'GR-c', 'LR', 'PH', 'CMI', 'noAF', 'noER'):
                    rs = [r for r in by_arm.get(a, []) if r.get('ls_class') == cls]
                    if not rs:
                        cells.append('-')
                        continue
                    at = sum(1 for r in rs if r['at_min'])/len(rs)
                    cert = sum(1 for r in rs if r['certified'])/len(rs)
                    cells.append(f"{100*at:.0f}% / {100*cert:.0f}%")
                rows.append(cells)
            lines += [f'LS at {budget:g} s: plan at the minimum / certified, by class', '',
                      _table(['class', 'GR', 'GR-c', 'LR', 'PH', 'CMI', 'noAF', 'noER'], rows), '']
        selection = store.load('ls', 'selection', 'selection')
        if selection:
            draws = len(selection['order'])
            labelled = [n for n in selection['order'] if store.exists('ls', 'labels', n)]
            undecided = sum(1 for n in labelled for record in [store.load('ls', 'labels', n)]
                            if ((record.get('pooled') or {}).get('bounds') or record['result']['bounds'])['minimum'] is None)
            lines += [f"{draws} draws, {len(labelled)} admitted and labelled; {undecided} left undecided at the reference "
                      f"budget ({100*undecided/max(1, len(labelled)):.1f}%). Cells filled: "
                      f"{sum(selection['selection']['full'].values())}/{len(selection['selection']['full'])}.", '']
    # P1 secondary.
    p1_rows = _with_reference(instances, ref, 'p1')
    if p1_rows:
        lines += ['## 5. P1 (secondary)', '']
        v1 = {}
        path = Path(config['p1']['source'])/'analysis'/'variants.csv'
        if path.exists():
            for r in csv.DictReader(path.open(encoding='utf-8')):
                v1.setdefault(r['case'], r)
        disagreements = []
        for r in p1_rows:
            old = v1.get(r['instance'])
            if not old or old['category'] == 'unresolved':
                continue
            expected = 5 if old['category'] == 'infinity' else int(old['category'])
            if r['ref_min'] is not None and r['ref_min'] != expected:
                disagreements.append(r['instance'])
            if r['ref_lower'] is not None and r['ref_lower'] > expected:
                disagreements.append(r['instance'])
        certified = sum(1 for r in p1_rows if r['label_lower'] == 5 or r['label_upper'] == r['label_lower'])
        open_v1 = [r for r in p1_rows if v1.get(r['instance'], {}).get('category') == 'unresolved']
        lines += [f"v2 reference labels on {len(p1_rows)} P1 variants with v1 lower bound >= 1: {certified} certified. "
                  f"Disagreements with a v1 certificate: {len(set(disagreements))} (target 0). "
                  f"Of the {len(open_v1)} variants v1 left open, v2 certifies "
                  f"{sum(1 for r in open_v1 if r['ref_min'] is not None)}.", '']
        by_arm = _arm_rows(arenas, 'p1', config['p1']['budget_s'])
        if by_arm:
            by_arm = {a: _attach(rows, instances, ref) for a, rows in by_arm.items()}
            rows = []
            for a in sorted(by_arm):
                s = _arm_summary(by_arm[a])
                rows.append([a, s['n'], f"{100*s['plan']:.1f}%", fmt(s['at_min'] and 100*s['at_min'], 1),
                             fmt(s['at_min_known'] and 100*s['at_min_known'], 1), s['known_n'],
                             f"{100*s['certified']:.1f}%", fmt(s['first_plan_median']), fmt(s['cert_median'])])
            lines += [_table(['arm', 'n', 'any plan', 'plan at minimum, all (%)', 'plan at minimum, known (%)',
                              'known n', 'certified', 'first plan median (s)',
                              'certificate median (s)'], rows), '']
            cmi = by_arm.get('CMI', [])
            if cmi:
                decided = sum(r['certified'] for r in cmi)/len(cmi)
                lines += [f"Method criterion: v2 decides at least 90% of these variants at {config['p1']['budget_s']} s: "
                          f"{100*decided:.1f}% ({'met' if decided >= .9 else 'missed'}).", '']
    # XR.
    chains = store.all('xr', 'chains')
    if chains:
        xr_rows, ind_rows, audits = [], [], []
        for path in chains:
            record = store.load('xr', 'chains', path.name[:-len('.json.gz')])
            for case, item in record['xr'].items():
                xr_rows.append(dict(case=case, certified=item['result']['bounds']['minimum'] is not None,
                                    cpu=item['result']['clock']['cpu_s']))
                audits.append(item['audit']['ok'])
            for case, entry in record['independent'].items():
                ind_rows.append(dict(case=case, certified=entry['result']['bounds']['minimum'] is not None,
                                     cpu=entry['result']['clock']['cpu_s']))
        lines += ['## 6. Reuse across instances (XR, P1)', '',
                  _table(['method', 'variants', 'certified', 'median CPU per variant (s)', 'total CPU (h)'],
                         [['XR (chain reuse)', len(xr_rows), f"{100*sum(r['certified'] for r in xr_rows)/len(xr_rows):.1f}%",
                           fmt(quantile([r['cpu'] for r in xr_rows], .5)), fmt(sum(r['cpu'] for r in xr_rows)/3600)],
                          ['CMI, each variant alone', len(ind_rows), f"{100*sum(r['certified'] for r in ind_rows)/len(ind_rows):.1f}%",
                           fmt(quantile([r['cpu'] for r in ind_rows], .5)), fmt(sum(r['cpu'] for r in ind_rows)/3600)]]),
                  '', f'XR chain replays: {sum(audits)}/{len(audits)} variants.', '']
    # Scaling.
    scaling = [(b, rows) for (g, b), rows in arenas.items() if g == 'scaling']
    if scaling:
        lines += ['## 7. Scaling (larger missions)', '']
        strata = r1_strata(store, config)
        if strata:
            mismatched = sorted(n for n, x in strata.items() if x['same_scenario'] is False)
            counts = Counter(x['r1'] for x in strata.values())
            lines += [f"The cohort is the {len(strata)} larger missions of R1 ({config['scaling']['r1_source']}). "
                      'R1 outcome (witness search at 60 s): '+', '.join(f'{k} {v}' for k, v in sorted(counts.items()))
                      + f". Regenerated scenarios that differ from R1's: {len(mismatched) or 'none'}"
                      + (' ('+', '.join(mismatched)+')' if mismatched else '')+'.', '']
        for budget, rows in sorted(scaling):
            rows = [_within_budget(r) for r in rows]
            groups = [('all missions', rows)]
            if strata:
                groups += [('disrupted in R1 (not Level 0)',
                            [r for r in rows if strata.get(r['instance'], {}).get('r1') not in (None, 'level 0')]),
                           ('unresolved in R1 (no witness)',
                            [r for r in rows if strata.get(r['instance'], {}).get('r1') == 'unresolved'])]
            for title, group in groups:
                by = defaultdict(list)
                for r in group:
                    by[r['arm']].append(r)
                table = []
                for a in sorted(by):
                    rs = by[a]
                    table.append([a, len(rs), f"{100*sum(r['plan_level'] is not None for r in rs)/len(rs):.0f}%",
                                  f"{100*sum(r['certified'] for r in rs)/len(rs):.0f}%",
                                  fmt(quantile([r['first_plan_cpu'] for r in rs if r['first_plan_cpu'] is not None], .5)),
                                  fmt(statistics.mean(r['plan_level'] for r in rs if r['plan_level'] is not None)
                                      if any(r['plan_level'] is not None for r in rs) else None)])
                lines += [f'At {budget:g} s, {title}:', '',
                          _table(['arm', 'missions', 'plan', 'certified', 'first plan median (s)', 'mean plan level'],
                                 table), '']
                cmi = by.get('CMI', [])
                if cmi and budget == 60:
                    decided = sum(r['certified'] for r in cmi)/len(cmi)
                    lines += [f"Method criterion: at least 75% of the larger missions ({title}) decided within "
                              f"60 s: {100*decided:.0f}% ({'met' if decided >= .75 else 'missed'}).", '']
    # D1 sensitivity.
    d1 = [r for r in instances.values() if r.get('group') == 'fs_d1' and 'label_lower' in r]
    if d1:
        pairs = []
        for r in d1:
            base = ref.get(r['instance'][:-3])
            if base is None:
                continue
            mine = r['label_lower'] if (r['label_lower'] == 5 or r['label_upper'] == r['label_lower']) else None
            pairs.append((base['minimum'], mine))
        table = [[_level_name(a), _level_name(b), n] for (a, b), n in sorted(Counter(pairs).items(), key=lambda x: str(x))]
        lines += ['## 8. In-flight rule: D1 against D1\' (sensitivity)', '',
                  f'{len(pairs)} in-flight FS variants labelled under both rules.', '',
                  _table(["D1' (primary)", 'D1 (destination committed)', 'variants'], table), '']
    # Contention.
    cont = arenas.get(('contention', float(arena['budget_short'])), [])
    base = {(r['instance'], r['arm']): r for r in arenas.get(('fs', float(arena['budget_short'])), [])}
    if cont:
        ratios = [base[(r['instance'], r['arm'])]['wall']/r['wall'] for r in cont
                  if (r['instance'], r['arm']) in base and r['wall'] > 0]
        cpu = [base[(r['instance'], r['arm'])]['cpu']/r['cpu'] for r in cont
               if (r['instance'], r['arm']) in base and r['cpu'] > 0]
        lines += ['## 9. Contention', '',
                  f"{len(cont)} arm runs repeated on one worker: wall-time ratio (all workers / one worker) median "
                  f"{fmt(quantile(ratios, .5))}; CPU-time ratio median {fmt(quantile(cpu, .5))}.", '']
    # Seed variance of the randomized arms.
    var = arenas.get(('variance', float(arena['budget_short'])), [])
    if var:
        base = arenas.get(('fs', float(arena['budget_short'])), [])
        rows = []
        for a in sorted({r['arm'] for r in var}):
            names = {r['instance'] for r in var if r['arm'] == a}
            by_seed = defaultdict(list)
            for r in [x for x in base if x['arm'] == a and x['instance'] in names]+[x for x in var if x['arm'] == a]:
                by_seed[r['seed']].append(_attach([r], instances, ref)[0])
            for seed, rs in sorted(by_seed.items()):
                s_ = _arm_summary(rs)
                rows.append([a, seed, s_['n'], f"{100*s_['plan']:.0f}%", fmt(s_['at_min'] and 100*s_['at_min'], 0),
                             fmt(s_['first_plan_median'])])
        lines += ['## 9b. Seed variance of GR and GR-c', '',
                  _table(['arm', 'seed', 'instances', 'any plan', 'plan at minimum, all (%)', 'first plan median (s)'], rows), '']
    # Operation overruns are execution costs, not extra time for scored outcomes.
    overruns = []
    for (group, budget), raw_rows in sorted(arenas.items()):
        for arm in sorted({r['arm'] for r in raw_rows}):
            rs = [r for r in raw_rows if r['arm'] == arm]
            scored = [_within_budget(r) for r in rs]
            overruns.append(dict(group=group, budget=budget, arm=arm, n=len(rs),
                                 runs_over=sum(r['overrun'] > 0 for r in rs),
                                 max_overrun=max(r['overrun'] for r in rs),
                                 late_plan_events=sum(r['late_plan_events'] for r in scored),
                                 late_certificates=sum(r['late_certificates'] for r in scored),
                                 unreturned_better_plans=sum(r['unreturned_better_plan'] for r in scored)))
    if overruns:
        summary['overruns'] = overruns
        lines += ['## 9c. Operation overruns and outcome cutoffs', '',
                  'The last operation may overrun the nominal CPU budget. Runtime includes that work; '
                  'arena success rates and curves exclude events after the inclusive cutoff. Late plan '
                  'counts are events, not necessarily distinct instances. Raw records and evidence are retained. '
                  'Runs with an unreturned better plan logged, by the cutoff, a plan at a lower level than the '
                  'plan they returned (or any plan, when they returned none by then); such plans are not '
                  'stored or replayed and are not credited.', '',
                  _table(['set', 'budget (s)', 'arm', 'runs', 'runs over budget', 'maximum overrun (s)',
                          'late plan events', 'late certificates', 'runs with an unreturned better plan'],
                         [[r['group'], r['budget'], r['arm'], r['n'], r['runs_over'],
                           fmt(r['max_overrun'], 3), r['late_plan_events'], r['late_certificates'],
                           r['unreturned_better_plans']]
                          for r in overruns]), '']
    # Audit.
    total = sum(len(rows) for rows in arenas.values())
    failed = [(g, b, r['instance'], r['arm'], r['audit_error']) for (g, b), rows in arenas.items() for r in rows
              if not r['audit_ok']]
    labels = [r for r in instances.values() if 'label_audit' in r]
    lines += ['## 10. Independent replay', '',
              f"{total-len(failed)}/{total} arena results and {sum(r['label_audit'] for r in labels)}/{len(labels)} "
              'reference labels replay without optimizers (certificates, route proofs, stop-sequence trees, assignment '
              'trees, Farkas combinations and exact plan checks).', '']
    if failed:
        lines += _table(['set', 'budget', 'instance', 'arm', 'error'], [list(f) for f in failed[:50]]).split('\n')+['']
    unit_failures = sorted((p.parent.name, p.name[:-len('.txt')], p.read_text(encoding='utf-8').strip())
                           for p in (store.path/'failures').glob('*/*.txt'))
    lines += ['Units and stages that failed and left no result (a rerun of the command retries them): '
              f'{len(unit_failures) or "none"}.', '']
    if unit_failures:
        lines += _table(['stage', 'unit', 'error'], [list(f) for f in unit_failures[:50]]).split('\n')+['']
    summary['audit'] = dict(arena_results=total, failed=len(failed), labels=len(labels),
                            labels_failed=sum(1 for r in labels if not r['label_audit']),
                            unit_failures=len(unit_failures))
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    _write_csv(out/'instances.csv', [dict(r, **{f'ref_{k}': v for k, v in ref.get(r['instance'], {}).items()})
                                     for r in instances.values()])
    for (group, budget), rows in arenas.items():
        exported = []
        for r in rows:
            scored = _within_budget(r)
            raw = {k: v for k, v in r.items() if k not in ('events', 'categories')}
            raw.update({f'within_budget_{k}': scored[k] for k in
                        ('plan_level', 'certified', 'minimum', 'lower', 'upper', 'first_plan_cpu', 'certificate_cpu')})
            raw.update({k: scored[k] for k in ('late_plan_events', 'late_certificates', 'unreturned_better_plan')})
            raw['decision_counts_within_budget'] = any(k.startswith('d_') for k in scored)
            exported.append(raw)
        _write_csv(out/f'arena_{group}_{budget:g}s.csv', exported)
    (out/'summary.json').write_text(json.dumps(summary, indent=2, default=str), encoding='utf-8')
    return summary


def _write_csv(path, rows):
    if not rows:
        return
    keys = sorted({k for r in rows for k in r})
    with Path(path).open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in r.items()})
