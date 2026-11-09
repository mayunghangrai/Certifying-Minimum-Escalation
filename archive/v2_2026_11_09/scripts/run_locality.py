"""B4: locality sweep, Q1-Q3 against the affected share |U0|/M (design doc, Section 18).

Missions: the FS generator (``final_study.generator.factorial_mission``) with 8 UAVs x 3 tasks,
medium slack and battery, both layouts, new seeds. Its admission (one cell, 1 <= |U0| <= 4,
Level 0 infeasible) is kept as the mission filter. The reference variant (strength 3/5, t = 0)
keeps its 4 x 4 wind grid. (An 8 x 8 grid made path construction about 5 times slower on the
same wind, so CMI and PH found nothing at 10 s; design doc, Section 18.)

Bands: |U0| in {1, 2, 3, 4, 6, 8} of 8. The update keeps the generator's wind vector. It starts
at the cell that affects the fewest UAVs (at least one; ties: the generator's cell, then index)
and grows one 4-neighbour cell at a time. The next cell is the neighbour adding the most new
affected UAVs without passing the next band; if none fits, the one adding the fewest (at least
one); cells adding none only when no neighbour adds any (ties: index). The supports are nested;
a band takes the first support whose U0 has exactly that size. A band is admitted if it is
reached, its diagnosed |U0| is the target, the previous plan is still valid and Level 0 is
certified infeasible (the FS screen); otherwise it is refused and the reason is kept in the
mission record.

Runs: label CMI-mu at the label budget; arena at 10 s, every arm in the config. Both through
``final_study.arena.run_instance`` and replayed there.

    python scripts/run_locality.py --stage smoke --out results/locality_smoke --workers 6
    python scripts/run_locality.py --stage run --out results/locality_2026_11_01 --workers 6
    python scripts/run_locality.py --stage report --out results/locality_2026_11_01
"""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import json
import multiprocessing
import os
from pathlib import Path
import statistics
import sys
import time

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
os.chdir(ROOT)

from continuous.validation import previous_premise                    # noqa: E402
from env.local_scope import affected_uavs                              # noqa: E402
from env.scenario import Scenario                                      # noqa: E402
from env.wind_dependency import diagnose_wind_update                   # noqa: E402
from final_study.analysis import _certificate_cpu, _code, _first_plan_cpu, bootstrap, quantile  # noqa: E402
from final_study.generator import factorial_mission, level0_screen     # noqa: E402
from final_study.stages import _pool                                   # noqa: E402
from final_study.store import Store                                    # noqa: E402

CONFIG = ROOT/'configs'/'final_study'/'locality.json'
CELLS = 16


def with_support(v, wind, support):
    """The variant with ``wind`` on the ``support`` cells and the previous (calm) wind elsewhere."""
    q = deepcopy(v)
    w = q['wind']
    w['received']['values'] = deepcopy(w['previous']['values'])
    for c in support:
        w['received']['values'][c] = [list(wind)]
    w['update_support'] = [[w['cells'][c]['id'], 0] for c in sorted(support)]
    return Scenario(q).to_dict()


def affected(payload):
    s = Scenario(payload)
    return set(affected_uavs(s, diagnose_wind_update(s))['uavs'])


def grow(per, start, fleet, targets):
    """Nested greedy growth: (path of (cell, |U0|), {|U0|: first support reaching it})."""
    support, current = [start], set(per[start])
    path, first = [(start, len(current))], {len(current): [start]}
    while len(current) < fleet and len(support) < CELLS-1:
        near = {(x+dx)*4+y+dy for c in support for x, y in [divmod(c, 4)]
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)) if 0 <= x+dx < 4 and 0 <= y+dy < 4}-set(support)
        gap = min([t for t in targets if t > len(current)], default=fleet)-len(current)
        new = {c: len(per[c]-current) for c in near}
        fit = [c for c in near if 1 <= new[c] <= gap]
        if fit:
            c = min(fit, key=lambda c: (-new[c], c))
        else:
            c = min([c for c in near if new[c] > 0] or near, key=lambda c: (new[c], c))
        support.append(c)
        current |= per[c]
        path.append((c, len(current)))
        first.setdefault(len(current), list(support))
    return path, first


def build_mission(store_path, config, spec):
    """One mission: generator, bands, admission. Runs in a worker process."""
    family, seed = spec
    store = Store(store_path, config, create=False)
    start_cpu = time.process_time()
    variants, ledger = factorial_mission(8, 3, config['sigma'], config['beta'], family, seed, prefix='LOC',
                                         times=('0',), max_attempts=config['max_attempts'])
    name = ledger['mission']
    if store.exists('loc', 'missions', name):
        return name, 'exists'
    record = dict(version='locality-mission-v1', mission=name, generator=ledger, bands={}, payloads={})
    if ledger['status'] == 'accepted':
        v = variants[name+'_r1_t0']
        wind = v['wind']['received']['values'][ledger['cell_index']][0]
        per = {c: affected(with_support(v, wind, [c])) for c in range(CELLS)}
        start = min((c for c in per if per[c]), key=lambda c: (len(per[c]), c != ledger['cell_index'], c))
        path, first = grow(per, start, len(v['state']['fleet']), config['targets'])
        record.update(start=start, path=path, single_cell={str(c): sorted(u) for c, u in per.items()})
        for target in config['targets']:
            band = dict(target=target)
            if target not in first:
                band['outcome'] = 'not_reached'
            else:
                q = with_support(v, wind, first[target])
                q['benchmark_id'] = f'{name}_u{target}'
                q = Scenario(q).to_dict()
                u0 = affected(q)
                band.update(support=[q['wind']['cells'][c]['id'] for c in first[target]], u0=sorted(u0))
                if len(u0) != target:
                    band['outcome'] = 'u0_mismatch'
                elif not previous_premise(Scenario(q))['accepted']:
                    band['outcome'] = 'previous_premise_failed'
                else:
                    screen = level0_screen(Scenario(q), config['admission_s'])
                    band['outcome'] = 'admitted' if screen == 'disrupted' else screen
                if band['outcome'] == 'admitted':
                    record['payloads'][q['benchmark_id']] = q
            record['bands'][str(target)] = band
    record['cpu_s'] = time.process_time()-start_cpu
    store.save(record, 'loc', 'missions', name)
    return name, f"{ledger['status']}, {len(record['payloads'])} bands admitted"


def build_pool(store, config, specs, workers, log):
    todo = list(specs)
    if not todo:
        return
    start = time.time()
    context = multiprocessing.get_context('spawn')
    with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
        futures = {pool.submit(build_mission, str(store.path), config, s): s for s in todo}
        for i, future in enumerate(as_completed(futures), 1):
            try:
                name, message = future.result()
            except Exception as error:      # the mission leaves no record, so a rerun retries it
                name, message = str(futures[future]), f'FAILED: {type(error).__name__}: {error}'[:400]
            log(f'build: {i}/{len(todo)} ({name}: {message}), elapsed {(time.time()-start)/60:.1f} min')


def missions(store):
    return [store.load('loc', 'missions', p.name[:-len('.json.gz')]) for p in store.all('loc', 'missions')]


# ---- report -------------------------------------------------------------------------------
def fmt(p):
    point, lo, hi = p
    if point is None:
        return '-'
    return f'{point:+.2f}' if lo is None else f'{point:+.2f} [{lo:+.2f}, {hi:+.2f}]'


def report(out, config):
    store = Store(out, None, bind=False)
    records = missions(store)
    targets = config['targets']
    fleet = 8
    lines = ['# B4: locality sweep', '', f'Run `{out}`. Bands are |U0| of {fleet} UAVs; supports are nested within a '
             'mission. Differences are CMI-mu minus the arm on instances where both returned a plan (95% interval over '
             'missions).', '', f"Missions: {len(records)} generated, "
             f"{sum(r['generator']['status'] == 'accepted' for r in records)} accepted by the FS generator.", '',
             '| band | share | reached | admitted | refusals | support cells, median |', '|---:|---:|---:|---:|---|---:|']
    for t in targets:
        bands = [r['bands'][str(t)] for r in records if str(t) in r['bands']]
        refusals = Counter(b['outcome'] for b in bands if b['outcome'] != 'admitted')
        sizes = [len(b['support']) for b in bands if b['outcome'] == 'admitted']
        lines.append(f"| {t} | {t/fleet:.3f} | {sum(b['outcome'] != 'not_reached' for b in bands)} | "
                     f"{len(sizes)} | " + ('; '.join(f'{k} {n}' for k, n in refusals.most_common()) or '-')
                     + f" | {quantile(sizes, .5) or 0:.0f} |")
    band_of = {vid: int(vid.rsplit('_u', 1)[1]) for r in records for vid in r['payloads']}
    mission_of = {vid: r['mission'] for r in records for vid in r['payloads']}
    label_tag = f"labels_{config['label_budget_s']:g}s"
    for tag in (label_tag, 'arena_10s'):
        rows = []
        for p in store.all('loc', tag):
            record = store.load('loc', tag, p.name[:-len('.json.gz')])
            for arm, e in record['arms'].items():
                res, dec = e['result'], e['decisions'] or {}
                rows.append(dict(instance=record['instance'], mission=mission_of[record['instance']],
                                 band=band_of[record['instance']], arm=arm, ok=e['audit']['ok'],
                                 plan=res['plan_level'] is not None, plan_level=res['plan_level'],
                                 minimum=None if res['bounds']['minimum'] is None else _code(res['bounds']['minimum']),
                                 certificate_cpu=_certificate_cpu(res), first_plan_cpu=_first_plan_cpu(res),
                                 mu=(res.get('mu_bounds') or {}).get('minimum'), **dec))
        if not rows:
            continue
        arms = sorted({r['arm'] for r in rows})
        lines += ['', f'## {tag}', '', f'Replays: {sum(r["ok"] for r in rows)}/{len(rows)}.', '',
                  '| band | arm | n | plan | certified | certified minimum 0/1/2/3/4/none | certificate CPU median / p90 (s) | '
                  'UAVs changed, mean | outside U0, mean |', '|---:|---|---:|---:|---:|---|---:|---:|---:|']
        for t in targets:
            for arm in arms:
                rs = [r for r in rows if r['band'] == t and r['arm'] == arm]
                if not rs:
                    continue
                cert = [r for r in rs if r['minimum'] is not None]
                cpu = [r['certificate_cpu'] for r in cert]
                mins = Counter(r['minimum'] for r in cert)
                mean = lambda k: statistics.mean([r[k] for r in rs if k in r]) if any(k in r for r in rs) else None
                lines.append(f"| {t} | {arm} | {len(rs)} | {sum(r['plan'] for r in rs)} | {len(cert)} | "
                             + '/'.join(str(mins.get(k, 0)) for k in range(6)) +
                             f" | {quantile(cpu, .5) or 0:.2f} / {quantile(cpu, .9) or 0:.2f} | "
                             + ' | '.join('-' if mean(k) is None else f'{mean(k):.2f}'
                                          for k in ('uavs_changed', 'uavs_changed_outside_u0')) + ' |')
        mu = Counter((r['band'], r['mu']) for r in rows if r['arm'] == 'CMI-mu' and r['mu'] is not None)
        if mu:
            lines += ['', 'CMI-mu certified mu* (fewest UAVs changed outside U0) by band: '
                      + ', '.join(f'band {b}: mu*={m} x{n}' for (b, m), n in sorted(mu.items()))]
        if tag != 'arena_10s' or 'CMI-mu' not in arms:
            continue
        others = [a for a in config['comparators'] if a in arms]
        lines += ['', 'Paired, CMI-mu minus arm:', '', '| band | arm | n | UAVs changed | outside U0 | '
                  'plan returned (share, CMI-mu minus arm) |', '|---:|---|---:|---:|---:|---:|']
        by = {(r['instance'], r['arm']): r for r in rows}
        for t in targets:
            for arm in others:
                pairs = [(by[i, 'CMI-mu'], by[i, arm]) for i, a in by if a == arm and band_of[i] == t and (i, 'CMI-mu') in by]
                both = [(a, b) for a, b in pairs if a['plan'] and b['plan']]
                diff = lambda key: bootstrap([dict(mission=a['mission'], v=a[key]-b[key]) for a, b in both],
                                             lambda rs: statistics.mean([r['v'] for r in rs]) if rs else None)
                success = bootstrap([dict(mission=a['mission'], v=int(a['plan'])-int(b['plan'])) for a, b in pairs],
                                    lambda rs: statistics.mean([r['v'] for r in rs]) if rs else None)
                lines.append(f"| {t} | {arm} | {len(both)} | {fmt(diff('uavs_changed'))} | "
                             f"{fmt(diff('uavs_changed_outside_u0'))} | {fmt(success)} |")
        lines += ['', 'Cost against the proof-free hierarchy: median CMI-mu certificate CPU over median PH-strict '
                  'first-plan CPU, within the band:', '']
        for t in targets:
            c = quantile([r['certificate_cpu'] for r in rows if r['band'] == t and r['arm'] == 'CMI-mu'], .5)
            f = quantile([r['first_plan_cpu'] for r in rows if r['band'] == t and r['arm'] == 'PH-strict'], .5)
            lines.append(f'- band {t}: ' + ('-' if not c or not f else f'{c:.2f} s / {f:.2f} s = {c/f:.2f}x'))
    Path(out, 'REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('\n'.join(lines))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=('smoke', 'run', 'report'), required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--config', default=str(CONFIG))
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    if args.stage == 'smoke':
        config = {**config, **config['smoke']}
    if args.stage == 'report':
        report(args.out, {**config, **json.loads(Path(args.out, 'manifest.json').read_text(encoding='utf-8'))['config']})
        return
    store = Store(args.out, config, workers=args.workers)
    log_path = Path(args.out)/'run.log'

    def log(message):
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
        print(line, flush=True)
        with log_path.open('a', encoding='utf-8') as stream:
            stream.write(line+'\n')
    specs = [(family, config['seed']+2*i+j) for i in range(config['missions_per_family'])
             for j, family in enumerate(config['families'])]
    done = {r['generator']['seed'] for r in missions(store)}
    build_pool(store, config, [s for s in specs if s[1] not in done], args.workers, log)
    label_tag = f"labels_{config['label_budget_s']:g}s"
    units = []
    for record in missions(store):
        for vid, payload in sorted(record['payloads'].items()):
            for tag, budget, arms in ((label_tag, config['label_budget_s'], config['label_arms']),
                                      ('arena_10s', 10, config['arena_arms'])):
                if not store.exists('loc', tag, vid):
                    units.append(('loc', tag, vid, payload, budget, arms))
    log(f'{args.stage}: {len(units)} label and arena units')
    _pool('arena', store.path, config, units, args.workers, log, args.stage)
    report(args.out, config)


if __name__ == '__main__':
    main()
