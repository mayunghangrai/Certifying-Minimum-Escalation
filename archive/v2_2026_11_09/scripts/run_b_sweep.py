"""B1: certified minimum outside participation mu* by a sweep of the helper allowance b.

mu(plan) = UAVs outside U0 whose stops, paths or quantities change (``uavs_changed_outside_u0``).
When Level 4 is feasible, Level 3 at allowance b is feasible exactly when mu* <= b
(docs/EXPERIMENT_REDESIGN_RAL_2026_10_30.md). So a Level-3 exclusion at b proves mu* >= b+1,
and every replayed plan proves mu* <= its mu. The frozen run has b = 1 everywhere:

- reference minimum 3: mu* <= best stored plan mu (0 or 1); a b = 0 label settles a 1;
- reference minimum 4: mu* >= 2 (Level 3 excluded at b = 1); labels at b = 2 .. c-1 for a best
  stored plan mu c >= 3.

Labels are the frozen 600 s CMI labels (``final_study.stages`` label job) on copies of the
frozen instances with ``hierarchy.helper_budget`` set to b. Stored plans whose mu differs from
the frozen b are re-checked under the scenario with b = mu (``within_level3``: scope membership
and the exact quantity constraints). The frozen run is only read.

    python scripts/run_b_sweep.py --stage smoke --out results/b_sweep_smoke --workers 6
    python scripts/run_b_sweep.py --stage run --out results/b_sweep_2026_10_31 --workers 6
    python scripts/run_b_sweep.py --stage report --out results/b_sweep_2026_10_31
"""
import argparse
from collections import Counter
from copy import deepcopy
import json
import os
from pathlib import Path
import random
import sys
import time

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
os.chdir(ROOT)

from env.local_scope import patch_contains, scope_family                 # noqa: E402
from env.scenario import Scenario                                       # noqa: E402
from escalation_study.ladder import witness_level                        # noqa: E402
from level2.quantities import _provider, verify_quantity_witness         # noqa: E402
from recovery.transfers import BranchRejected, build_transfer_problem    # noqa: E402
from final_study.analysis import _attach, _paired_rates, bootstrap, load, pooled, share  # noqa: E402
from final_study.stages import _pool, fs_instances, ls_instances         # noqa: E402
from final_study.store import Store                                      # noqa: E402

CONFIG = ROOT/'configs'/'final_study'/'b_sweep.json'
MU = 'uavs_changed_outside_u0'


def with_budget(payload, b):
    payload = deepcopy(payload)
    payload['hierarchy']['helper_budget'] = b
    return payload


def population(source):
    """Instances with reference minimum 3 or 4: payload, frozen b, bracket on mu*, best stored plan."""
    instances, arenas, _ = load(source)
    ref = pooled(instances, arenas)
    best = {}

    def take(name, mu, where):
        if name not in best or mu < best[name][0]:
            best[name] = (mu, where)
    for (group, budget), rows in arenas.items():
        if group in ('fs', 'ls'):
            for r in rows:
                if r['audit_ok'] and r['plan_level'] is not None and f'd_{MU}' in r:
                    take(r['instance'], r[f'd_{MU}'], (group, f'arena_{budget:g}s', r['arm']))
    for group in ('fs', 'ls'):
        for path in source.all(group, 'labels'):
            record = source.load(group, 'labels', path.name[:-len('.json.gz')])
            if record['audit']['ok'] and record.get('decisions'):
                take(record['instance'], record['decisions'][MU], (group, 'labels', 'CMI'))
    payloads = {vid: p for vid, p, _ in fs_instances(source)}
    payloads.update(dict(ls_instances(source)))
    out = {}
    for name, r in ref.items():
        if name in payloads and r['minimum'] in (3, 4) and name in best:
            b0 = payloads[name]['hierarchy']['helper_budget']
            out[name] = dict(group=instances[name]['group'], mission=instances[name]['mission'], level=r['minimum'],
                             payload=payloads[name], b0=b0, lower=0 if r['minimum'] == 3 else b0+1,
                             upper=best[name][0], where=best[name][1])
    return out, instances, arenas, ref


def units(pop):
    return [(p['group'], f'{name}_b{b}', with_budget(p['payload'], b))
            for name, p in sorted(pop.items()) for b in range(p['lower'], p['upper'])]


def stored_witness(source, name, where):
    group, tag, arm = where
    record = source.load(group, tag, name)
    result = record['result'] if tag == 'labels' else record['arms'][arm]['result']
    return result['plan']['witness'], result['affected']


def within_level3(scenario, witness, u0):
    """Is a stored plan in F3 of ``scenario``? Scope membership, then the exact quantity check.

    A witness lists the quantity columns of the patch it was found in; a smaller allowance frees
    fewer columns, so the witness is rebuilt on each candidate patch's own columns (values from the
    stored point; a column the stored point lacks rejects). The compiler holds the dropped columns
    at their incumbent values, and ``verify_quantity_witness`` checks the exact point."""
    level, point = witness_level(scenario, witness, u0)
    if level is None or level > 3:
        return dict(accepted=False, level=level, reason='outside the Level-3 scope union')
    values = {tuple(c): v for c, v in zip(witness['columns'], witness['values'])}
    reasons = []
    for k in range(level, 4):
        for patch in scope_family(scenario, k, u0):
            if not patch_contains(scenario, point, patch):
                continue
            try:
                compiled = build_transfer_problem(scenario, witness['plan'], witness['reserve_paths'], patch.releases,
                                                  exact=True, duration_provider=_provider(scenario, witness['digits'], None))
            except BranchRejected as error:
                reasons.append(str(error))
                continue
            columns = [list(c) for c in compiled.columns]
            if any(tuple(c) not in values for c in columns):
                reasons.append('column outside the stored point')
                continue
            moved = dict(witness, scenario_hash=scenario.content_hash(), columns=columns,
                         values=[values[tuple(c)] for c in columns])
            if verify_quantity_witness(scenario, moved, patch.releases):
                return dict(accepted=True, level=k)
            reasons.append('exact quantity constraints fail')
    return dict(accepted=False, level=level, reason='; '.join(sorted(set(reasons))))


def recheck(source, store, pop, names, log):
    """Stored best plans with mu != b0, under the scenario with b = mu: expect Level <= 3."""
    for name in names:
        p = pop[name]
        if p['upper'] == p['b0'] or store.exists('recheck', name):
            continue
        witness, u0 = stored_witness(source, name, p['where'])
        start = time.process_time()
        check = within_level3(Scenario(with_budget(p['payload'], p['upper'])), witness, u0)
        store.save(dict(instance=name, b=p['upper'], where=list(p['where']), check=check,
                        cpu_s=time.process_time()-start), 'recheck', name)
    log(f'recheck: {sum(store.exists("recheck", n) for n in names)} stored plans re-checked')


def resolve(pop, store):
    """mu* bracket per instance from the stored bracket and the b-sweep labels found in ``store``."""
    out = {}
    for name, p in pop.items():
        lower, upper, runs = p['lower'], p['upper'], []
        for b in range(p['lower'], p['upper']):
            record = store.load(p['group'], 'labels', f'{name}_b{b}')
            if record is None:
                runs.append((b, 'missing'))
                continue
            if not record['audit']['ok']:
                runs.append((b, 'audit failed'))
                continue
            bounds = record['result']['bounds']
            if 3 in bounds['excluded_levels']:
                lower = max(lower, b+1)
                runs.append((b, 'excluded'))
            elif record['result']['plan_level'] is not None and record['result']['plan_level'] <= 3:
                upper = min(upper, b, record['decisions'][MU])
                runs.append((b, 'plan'))
            else:
                runs.append((b, 'open'))
        check = store.load('recheck', name)
        out[name] = dict(lower=lower, upper=upper, mu=lower if lower == upper else None, runs=runs,
                         recheck=None if check is None else (check['check']['accepted'] and
                                                             check['check'].get('level', 9) <= 3))
    return out


def pp(p):
    if p['lo'] is None:
        return f"{100*(p['difference'] or 0):+.1f}"
    return f"{100*p['difference']:+.1f} [{100*p['lo']:+.1f}, {100*p['hi']:+.1f}]"


def report(source, out, pop, instances, arenas, ref):
    store = Store(out, None, bind=False)
    res = resolve(pop, store)
    lines = ['# B1: certified minimum outside participation', '',
             f'Run `{out}`; frozen run `{source.path}` (helper allowance b = 1). mu* = fewest UAVs outside U0 whose '
             'stops, paths or quantities change in any feasible plan. Lower bounds: a Level-3 exclusion at b proves '
             'mu* >= b+1 (b = 1 from the frozen labels). Upper bounds: the mu of any replayed plan.', '',
             '| group | reference minimum | n | ' + ' | '.join(f'mu* = {k}' for k in range(5)) +
             ' | bracket | b-sweep labels done / needed |', '|---|---:|---:|' + '---:|'*5 + '---:|---:|']
    for group in ('fs', 'ls'):
        for level in (3, 4):
            names = [n for n, p in pop.items() if p['group'] == group and p['level'] == level]
            mus = Counter(res[n]['mu'] for n in names)
            runs = [s for n in names for _, s in res[n]['runs']]
            lines.append(f"| {group.upper()} | {level} | {len(names)} | " +
                         ' | '.join(str(mus.get(k, 0)) for k in range(5)) +
                         f" | {mus.get(None, 0)} | {sum(s != 'missing' for s in runs)} / {len(runs)} |")
    outcomes = Counter(s for r in res.values() for _, s in r['runs'])
    checks = Counter(r['recheck'] for n, r in res.items() if pop[n]['upper'] != pop[n]['b0'])
    brackets = Counter((r['lower'], r['upper']) for r in res.values() if r['mu'] is None)
    lines += ['', 'b-sweep label outcomes: ' + ', '.join(f'{k} {v}' for k, v in sorted(outcomes.items())),
              'Stored best plans with mu != 1 re-checked at b = mu (Level <= 3 accepted / rejected / not yet): '
              f"{checks.get(True, 0)} / {checks.get(False, 0)} / {checks.get(None, 0)}",
              'Open brackets (lower, upper): ' + (', '.join(f'{k} x{v}' for k, v in sorted(brackets.items())) or '-'),
              '']
    settled = {n for n, r in res.items() if r['mu'] is not None}
    lines += ['Excess outside participation (plan mu minus mu*) on instances with a settled mu*; returned plans '
              'scored as in the final-study report (returned by the budget, replayed). Zero-excess share counts '
              'instances without a plan as failures; 95% interval over missions.', '',
              '| arena | arm | n | plans | zero excess | zero-excess share | mean excess of plans | max |',
              '|---|---|---:|---:|---:|---:|---:|---:|']
    negative, paired = 0, []
    for (group, budget), raw in sorted(arenas.items()):
        if group not in ('fs', 'ls'):
            continue
        rows = [r for r in _attach(raw, instances, ref) if r['instance'] in settled]
        by_arm = {}
        for r in rows:
            r['excess'] = r[f'd_{MU}']-res[r['instance']]['mu'] if f'd_{MU}' in r else None
            r['zero'] = r['excess'] == 0
            negative += r['excess'] is not None and r['excess'] < 0
            by_arm.setdefault(r['arm'], []).append(r)
        for arm in ('GR-c', 'GR', 'LR', 'PH'):
            if arm not in by_arm:
                continue
            both = ({r['instance'] for r in by_arm['CMI'] if r['excess'] is not None}
                    & {r['instance'] for r in by_arm[arm] if r['excess'] is not None})
            for label, keep in (('all instances', None), ('both returned a plan', both)):
                left = [r for r in by_arm['CMI'] if keep is None or r['instance'] in keep]
                right = [r for r in by_arm[arm] if keep is None or r['instance'] in keep]
                p = _paired_rates(left, right, 'zero')
                paired.append(f"| {group.upper()} {budget:g} s | {arm} | {label} | {p['n']} | {p['left_count']} | "
                              f"{p['right_count']} | {pp(p)} |")
        for arm, rs in sorted(by_arm.items()):
            ex = [r['excess'] for r in rs if r['excess'] is not None]
            point, lo, hi = bootstrap(rs, share(lambda r: r['excess'] == 0))
            interval = '' if lo is None else f' [{100*lo:.0f}, {100*hi:.0f}]'
            lines.append(f"| {group.upper()} {budget:g} s | {arm} | {len(rs)} | {len(ex)} | {ex.count(0)} | "
                         f"{100*(point or 0):.0f}%{interval} | {sum(ex)/len(ex) if ex else 0:.2f} | "
                         f"{max(ex, default=0)} |")
    lines += ['', 'Paired zero-excess rates, CMI minus the arm on the same instances (95% interval over missions):', '',
              '| arena | arm | instances | n | CMI | arm | difference (pp) |', '|---|---|---|---:|---:|---:|---:|',
              *paired]
    lines += ['', f'Plans with mu below the certified mu* (would contradict a certificate): {negative}', '']
    Path(out, 'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=('smoke', 'run', 'report'), required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--config', default=str(CONFIG))
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    source = Store(config['source_run'], None, bind=False)
    pop, instances, arenas, ref = population(source)
    if args.stage == 'report':
        report(source, args.out, pop, instances, arenas, ref)
        return
    todo, names = units(pop), sorted(pop)
    if args.stage == 'smoke':
        smoke = config['smoke']
        rng = random.Random(smoke['seed'])
        level4 = [u for u in todo if pop[u[1].rsplit('_b', 1)[0]]['level'] == 4]
        level3 = [u for u in todo if u not in level4]
        todo = rng.sample(level3, smoke['units']*2//3)+rng.sample(level4, smoke['units']-smoke['units']*2//3)
        names = sorted({u[1].rsplit('_b', 1)[0] for u in todo} | set(rng.sample(names, smoke['units'])))
        config = dict(config, label_budget_s=smoke['label_budget_s'])
    store = Store(args.out, config, workers=args.workers)
    log_path = Path(args.out)/'run.log'

    def log(message):
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
        print(line, flush=True)
        with log_path.open('a', encoding='utf-8') as stream:
            stream.write(line+'\n')
    log(f"{args.stage}: {len(pop)} instances, {len(todo)} b-sweep labels at {config['label_budget_s']} s, "
        f"{args.workers} workers")
    recheck(source, store, pop, names, log)
    todo = [u for u in todo if not store.exists(u[0], 'labels', u[1])]
    _pool('label', store.path, config, todo, args.workers, log, args.stage)
    report(source, args.out, pop, instances, arenas, ref)


if __name__ == '__main__':
    main()
