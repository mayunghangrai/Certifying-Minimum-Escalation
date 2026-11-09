"""CMI-mu: CMI, then the fewest UAVs outside U0 in the remaining budget (design doc, Section 14).

Runs the CMI-mu arm alone on the frozen final-study instances through
``final_study.arena.run_instance`` (CPU budget, replay) and compares it with the frozen CMI arm
on the same instances, scored against the certified mu* of the B1 b-sweep.

    python scripts/run_cmi_mu.py --stage smoke --out results/cmi_mu_smoke --workers 6
    python scripts/run_cmi_mu.py --stage run --out results/cmi_mu_2026_11_01 --workers 6
    python scripts/run_cmi_mu.py --stage report --out results/cmi_mu_2026_11_01
"""
import argparse
from collections import Counter
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
sys.path.append(str(ROOT/'scripts'))
os.chdir(ROOT)

from final_study.analysis import _attach, _paired_rates, load, pooled, quantile  # noqa: E402
from final_study.stages import _pool, fs_instances, fs_long_missions, ls_instances  # noqa: E402
from final_study.store import Store                                               # noqa: E402
from run_b_sweep import MU, population, pp, resolve                               # noqa: E402

CONFIG = ROOT/'configs'/'final_study'/'cmi_mu.json'


def units(source, config, pop, stage):
    fs = [(vid, p) for vid, p, _ in fs_instances(source)]
    ls = ls_instances(source)
    third = fs_long_missions(source, source.manifest['config'])
    mission = {vid: ledger['mission'] for vid, _, ledger in fs_instances(source)}
    sets = {('fs', config['budget_short']): fs, ('fs', config['budget_long']): [i for i in fs if mission[i[0]] in third],
            ('ls', config['budget_short']): ls, ('ls', config['budget_long']): ls}
    if stage == 'smoke':
        smoke = config['smoke']
        rng = random.Random(smoke['seed'])
        names = set(rng.sample(sorted(pop), smoke['population']))
        names |= set(rng.sample([vid for vid, _ in fs if vid not in pop], smoke['others']))
        sets = {k: [i for i in v if i[0] in names] for k, v in sets.items()}
    return [(group, f'arena_{budget}s', name, payload, budget, config['arms'])
            for (group, budget), items in sorted(sets.items()) for name, payload in items]


def report(source, out, pop, instances, arenas, b_sweep):
    store = Store(out, None, bind=False)
    _, new, _ = load(store)
    merged = {k: v+new.get(k, []) for k, v in arenas.items()}
    ref = pooled(instances, merged)
    res = resolve(pop, Store(b_sweep, None, bind=False))
    lines = ['# CMI-mu', '', f'Run `{out}`; frozen run `{source.path}`; mu* from the B1 b-sweep '
             f'(`{b_sweep}`). Scoring as in the final-study report. CMI is the frozen arm.', '']
    for (group, budget), raw in sorted(new.items()):
        tag = f'arena_{budget:g}s'
        for r in raw:
            r['mu_bounds'] = store.load(group, tag, r['instance'])['arms']['CMI-mu']['result'].get('mu_bounds')
        rows = _attach(raw, instances, ref)
        names = {r['instance'] for r in rows}
        frozen = _attach([r for r in arenas.get((group, budget), []) if r['arm'] == 'CMI' and r['instance'] in names],
                         instances, ref)
        old = {r['instance']: r for r in frozen}
        raw_old = {r['instance']: r for r in arenas.get((group, budget), []) if r['arm'] == 'CMI'}
        lines += [f'## {group.upper()} at {budget:g} s', '',
                  '| arm | n | replays | plan at minimum | certified | certificate CPU, median (s) |',
                  '|---|---:|---:|---:|---:|---:|']
        for arm, rs in (('CMI', frozen), ('CMI-mu', rows)):
            lines.append(f"| {arm} | {len(rs)} | {sum(r['audit_ok'] for r in rs)} | {sum(r['at_min'] for r in rs)} | "
                         f"{sum(r['certified'] for r in rs)} | "
                         f"{quantile([r['certificate_cpu'] for r in rs if r['certified']], .5) or 0:.2f} |")
        same = sum((r['lower'], r['upper']) == (raw_old[r['instance']]['lower'], raw_old[r['instance']]['upper'])
                   for r in raw if r['instance'] in raw_old)
        steps = Counter(e['kind'] for r in raw for e in r['events'] if e['kind'].startswith('mu_'))
        mu_rows = [r for r in raw if r.get('mu_bounds')]
        lines += ['', f'Level bracket (lower, upper) equal to frozen CMI: {same} of {len(raw)}.',
                  f"Refinement ran on {len(mu_rows)} certified Level-3/4 instances: "
                  + ', '.join(f'{k} {v}' for k, v in sorted(steps.items())) + '; mu bracket closed on '
                  f"{sum(r['mu_bounds']['minimum'] is not None for r in mu_rows)}.",
                  'mu bracket against B1 mu* (contradictions must be 0): '
                  f"{sum(1 for r in mu_rows if r['instance'] in res and res[r['instance']]['mu'] is not None and not r['mu_bounds']['lower'] <= res[r['instance']]['mu'] <= r['mu_bounds']['upper'])}.",
                  '']
        settled = {n for n, r in res.items() if r['mu'] is not None}
        both = []
        for rs in (frozen, rows):
            for r in rs:
                r['zero'] = r['instance'] in settled and f'd_{MU}' in r and r[f'd_{MU}'] == res[r['instance']]['mu']
            both.append([r for r in rs if r['instance'] in settled])
        plans = {r['instance'] for r in both[0] if f'd_{MU}' in r} & {r['instance'] for r in both[1] if f'd_{MU}' in r}
        lines += ['Zero-excess plans (mu = mu*), CMI-mu minus CMI on the same instances with settled mu* '
                  '(95% interval over missions):', '', '| instances | n | CMI | CMI-mu | difference (pp) |',
                  '|---|---:|---:|---:|---:|']
        for label, keep in (('all', None), ('both returned a plan', plans)):
            left = [r for r in both[1] if keep is None or r['instance'] in keep]
            right = [r for r in both[0] if keep is None or r['instance'] in keep]
            p = _paired_rates(left, right, 'zero')
            lines.append(f"| {label} | {p['n']} | {p['right_count']} | {p['left_count']} | {pp(p)} |")
        lines.append('')
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
    pop, instances, arenas, _ = population(source)
    if args.stage == 'report':
        report(source, args.out, pop, instances, arenas, config["b_sweep_run"])
        return
    store = Store(args.out, config, workers=args.workers)
    log_path = Path(args.out)/'run.log'

    def log(message):
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
        print(line, flush=True)
        with log_path.open('a', encoding='utf-8') as stream:
            stream.write(line+'\n')
    todo = [u for u in units(source, config, pop, args.stage) if not store.exists(u[0], u[1], u[2])]
    log(f'{args.stage}: {len(todo)} units, arms {config["arms"]}, {args.workers} workers')
    _pool('arena', store.path, config, todo, args.workers, log, args.stage)
    report(source, args.out, pop, instances, arenas, config["b_sweep_run"])


if __name__ == '__main__':
    main()
