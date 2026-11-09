"""Stages of the final study, each resumable at the level of one unit of work.

Order (``STAGES``): FS generation and reference labels, the 10 s and 60 s arenas on
FS, the level suite and its arenas, P1 labels and arena (secondary), the XR reuse
study, scaling, the D1 sensitivity labels, the contention subset, and the report.
A unit is one mission, one instance or one chain; its record is written atomically,
so an interrupted run continues where it stopped.
"""
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from fractions import Fraction
import json
import multiprocessing
from pathlib import Path
import random
import re
import time
import traceback

from env.scenario import Scenario
from recovery.local_search import digest
from .arena import audit_chain, label, run_chain, run_instance
from .store import Store

STAGES = ('fs-generate', 'fs-label', 'fs-arena-short', 'fs-arena-long', 'ls-build', 'ls-arena-short',
          'ls-arena-long', 'p1-label', 'p1-arena', 'xr', 'scaling', 'fs-d1', 'contention', 'gr-seeds', 'report')


# ---- units of work (run in worker processes) --------------------------------------------
def _fs_generate(store_path, config, spec):
    from .generator import factorial_mission
    store = Store(store_path, config, create=False)
    m, k, sigma, beta, family, seed = spec
    name = f'FS_{m}x{k}_{sigma}_{beta}_{family}_{seed}'
    if store.exists('fs', 'missions', name):
        return name, 'exists'
    fs = config['fs']
    start = time.process_time()
    variants, ledger = factorial_mission(m, k, sigma, beta, family, seed, sigma_values=fs['sigma'],
                                         beta_values=fs['beta'], rule=fs['rule'], max_attempts=fs['max_attempts'])
    store.save(dict(version='final-study-fs-mission-v1', mission=name, ledger=ledger, variants=variants,
                    generation_cpu_s=time.process_time()-start), 'fs', 'missions', name)
    return name, ledger['status']


def _label(store_path, config, unit):
    group, instance, payload = unit
    store = Store(store_path, config, create=False)
    if store.exists(group, 'labels', instance):
        return instance, 'exists'
    record = label(instance, payload, config['label_budget_s'], config['settings'])
    store.save(record, group, 'labels', instance)
    return instance, str(record['result']['bounds']['minimum'])


def _arena(store_path, config, unit):
    group, tag, instance, payload, budget, arms = unit[:6]
    seed = unit[6] if len(unit) > 6 else 0
    store = Store(store_path, config, create=False)
    if store.exists(group, tag, instance):
        return instance, 'exists'
    record = run_instance(instance, payload, budget, arms, config['settings'], seed=seed)
    store.save(record, group, tag, instance)
    return instance, 'done'


def _ls_draw(store_path, config, unit):
    from .levelsuite import ls_draw
    target, fleet, index, name = unit
    store = Store(store_path, config, create=False)
    item = store.load('ls', 'draws', name)
    if item is None:
        fs = config['fs']
        payload, ledger = ls_draw(target, fleet, index, base_seed=config['ls']['seed'], sigma_values=fs['sigma'],
                                  beta_values=fs['beta'], rule=fs['rule'])
        item = store.save(dict(version='final-study-ls-draw-v1', draw=name, ledger=ledger, payload=payload),
                          'ls', 'draws', name)
    if item['payload'] is not None and not store.exists('ls', 'labels', name):
        record = label(name, item['payload'], config['label_budget_s'], config['settings'])
        construction = item['ledger'].get('construction') or {}
        if construction.get('witness'):
            from .level4 import pool
            record['pooled'] = pool(item['payload'], record, construction['witness'])
        store.save(record, 'ls', 'labels', name)
    return name, item['ledger']['status']


def _chain(store_path, config, unit):
    name, cases = unit
    store = Store(store_path, config, create=False)
    if store.exists('xr', 'chains', name):
        return name, 'exists'
    budget = config['xr']['budget_s']
    results = run_chain(cases, budget, config['settings'])
    audits = audit_chain(results)
    from .arena import detach
    xr, independent, proofs = {}, {}, {}
    for (case, _, r), a in zip(results, audits):
        result, proof = detach(r)
        xr[case] = dict(result=result, audit=a)
        if proof is not None:
            proofs['xr/'+case] = proof
    for case, payload in cases:
        record = run_instance(case, payload, budget, ('CMI',), config['settings'])
        independent[case] = record['arms']['CMI']
        if 'CMI' in record['proofs']:
            proofs['independent/'+case] = record['proofs']['CMI']
    store.save(dict(version='final-study-xr-chain-v1', chain=name, xr=xr, independent=independent, proofs=proofs),
               'xr', 'chains', name)
    return name, 'done'


def _scaling(store_path, config, unit):
    n, m, family, seed = unit
    from escalation_study.missions import base_mission, mission_id, variant_id
    store = Store(store_path, config, create=False)
    sc = config['scaling']
    name = mission_id(n, m, family, seed)
    item = store.load('scaling', 'missions', name)
    if item is None:
        scenarios, ledger = base_mission(n, m, family, seed, max_attempts=sc['max_attempts'],
                                         strengths=(sc['strength'],), slacks=(sc['slack'],))
        payload = scenarios.get(variant_id(ledger['mission'], 0, 0)) if scenarios else None
        item = store.save(dict(version='final-study-scaling-mission-v1', mission=name, ledger=ledger,
                               payload=payload), 'scaling', 'missions', name)
    if item['payload'] is None:
        return name, 'generation_failed'
    for budget in sc['budgets']:
        tag = f'arena_{budget}s'
        if not store.exists('scaling', tag, name):
            record = run_instance(name, item['payload'], budget, sc['arms'], config['settings'])
            store.save(record, 'scaling', tag, name)
    return name, 'done'


def _fs_d1(store_path, config, unit):
    instance, mission, vid = unit
    from escalation_study.snapshots import build_snapshot
    store = Store(store_path, config, create=False)
    if store.exists('fs_d1', 'labels', instance):
        return instance, 'exists'
    item = store.load('fs', 'missions', mission)
    ledger = item['ledger']
    base = item['variants'][vid.rsplit('_t', 1)[0]+'_t0']
    cell = ledger['cell_index']
    wind = base['wind']['received']['values'][cell][0]
    snap, _ = build_snapshot(base, ledger['variants'][vid]['time'], received_wind=(cell, wind), rule='D1')
    snap['benchmark_id'] = instance
    record = label(instance, Scenario(snap).to_dict(), config['label_budget_s'], config['settings'])
    store.save(record, 'fs_d1', 'labels', instance)
    return instance, str(record['result']['bounds']['minimum'])


JOBS = dict(fs_generate=_fs_generate, label=_label, arena=_arena, ls_draw=_ls_draw, chain=_chain,
            scaling=_scaling, fs_d1=_fs_d1)


def _dispatch(kind, store_path, config, unit):
    """Run one unit; a failure is returned (and logged by the parent), never fatal to the stage."""
    import traceback
    try:
        return JOBS[kind](store_path, config, unit)
    except Exception as error:      # the unit leaves no record, so a rerun retries it
        name = unit[0] if isinstance(unit, (list, tuple)) and unit and isinstance(unit[0], str) else str(unit)[:80]
        if kind == 'arena':
            name = unit[2]
        elif kind == 'label':
            name = unit[1]
        elif kind == 'ls_draw':
            name = unit[3]
        return name, 'FAILED: '+''.join(traceback.format_exception_only(type(error), error)).strip()[:400]


def _pool(kind, store_path, config, units, workers, log, label_text):
    total = len(units)
    if not total:
        log(f'{label_text}: nothing to do')
        return []
    failures = []
    start = time.time()
    out = []
    if workers <= 1:
        for i, unit in enumerate(units, 1):
            out.append(_dispatch(kind, str(store_path), config, unit))
            _progress(log, label_text, i, total, start, out[-1])
    else:
        context = multiprocessing.get_context('spawn')
        with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
            futures = [pool.submit(_dispatch, kind, str(store_path), config, unit) for unit in units]
            for i, future in enumerate(as_completed(futures), 1):
                out.append(future.result())
                _progress(log, label_text, i, total, start, out[-1])
    failures = [o for o in out if str(o[1]).startswith('FAILED')]
    for name, message in out:
        _note(store_path, label_text, name, message if str(message).startswith('FAILED') else None)
    for name, message in failures:
        log(f'{label_text}: unit {name} {message}')
    if failures:
        log(f'{label_text}: {len(failures)} of {total} units failed and will be retried by the next run')
    return out


def _note(store_path, group, name, message):
    """One file per failed unit or stage under ``failures/``, removed when it later succeeds;
    the report lists what is left."""
    safe = lambda text: re.sub(r'[^A-Za-z0-9_.=-]', '_', str(text))[:120]
    path = Path(store_path)/'failures'/safe(group)/(safe(name)+'.txt')
    if message is None:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(message)+'\n', encoding='utf-8')


def _progress(log, label_text, i, total, start, outcome):
    elapsed = time.time()-start
    eta = elapsed/i*(total-i)
    if i == total or i % max(1, total//50) == 0 or total <= 60 or str(outcome[1]).startswith('FAILED'):
        log(f'{label_text}: {i}/{total} ({outcome[0]}: {outcome[1]}), elapsed {elapsed/60:.1f} min, '
            f'about {eta/60:.0f} min left')


# ---- instance sets ------------------------------------------------------------------------
L9 = ((0, 0, 0, 0), (0, 1, 1, 1), (0, 2, 2, 2), (1, 0, 1, 2), (1, 1, 2, 0), (1, 2, 0, 1),
      (2, 0, 2, 1), (2, 1, 0, 2), (2, 2, 1, 0))


def fs_specs(config):
    """All factor combinations, or (pilot) the L9 orthogonal array over the four mission factors."""
    fs = config['fs']
    levels = [fs['fleets'], fs['tasks_per_uav'], list(fs['sigma']), list(fs['beta'])]
    if fs.get('design', 'full') == 'L9':
        combos = [tuple(levels[j][row[j]] for j in range(4)) for row in L9]
    else:
        combos = [(m, k, sigma, beta) for m in levels[0] for k in levels[1] for sigma in levels[2] for beta in levels[3]]
    specs, index = [], 0
    for m, k, sigma, beta in combos:
        for family in fs['families']:
            specs.append((m, k, sigma, beta, family, fs['seed']+index))
            index += 1
    return specs


def fs_instances(store):
    out = []
    for path in store.all('fs', 'missions'):
        item = store.load('fs', 'missions', path.name[:-len('.json.gz')])
        for vid, payload in sorted(item['variants'].items()):
            out.append((vid, payload, item['ledger']))
    return out


def fs_long_missions(store, config):
    """A random third of the FS missions (seeded) for the long-budget arena."""
    names = sorted(p.name[:-len('.json.gz')] for p in store.all('fs', 'missions'))
    accepted = [n for n in names if store.load('fs', 'missions', n)['ledger']['status'] == 'accepted']
    rng = random.Random(config['arena']['third_seed'])
    return set(rng.sample(accepted, len(accepted)//3))


def ls_instances(store):
    selection = store.load('ls', 'selection', 'selection')
    if selection is None:
        return []
    names = sorted({n for names in selection['selection']['selected'].values() for n in names}
                   | set(selection['selection']['hard']))
    return [(n, store.load('ls', 'draws', n)['payload']) for n in names]


def p1_cases(config, *, lower_at_least=1):
    root = Path(config['p1']['source'])
    rows = list(csv.DictReader((root/'analysis'/'variants.csv').open(encoding='utf-8')))
    seen, out = set(), []
    for r in rows:
        if r['case'] in seen:
            continue
        seen.add(r['case'])
        lower = 0 if r['category'] == '0' else 1
        if lower >= lower_at_least:
            out.append((r['case'], r['mission']))
    return out


def _limit(items, limit, seed):
    if not limit or limit >= len(items):
        return items
    rng = random.Random(seed)
    return sorted(rng.sample(items, limit))


def p1_payloads(config, cases):
    root = Path(config['p1']['source'])
    cache, out = {}, []
    for case, mission in cases:
        if mission not in cache:
            cache = {mission: json.loads((root/'missions'/f'{mission}.json').read_text(encoding='utf-8'))['scenarios']}
        out.append((case, cache[mission][case]))
    return out


# ---- stage drivers ------------------------------------------------------------------------
def stage(name, store, config, workers, log):
    path = store.path
    arena = config['arena']
    if name == 'fs-generate':
        _pool('fs_generate', path, config, fs_specs(config), workers, log, name)
    elif name == 'fs-label':
        units = [('fs', vid, payload) for vid, payload, _ in fs_instances(store) if not store.exists('fs', 'labels', vid)]
        _pool('label', path, config, units, workers, log, name)
    elif name in ('fs-arena-short', 'fs-arena-long'):
        short = name.endswith('short')
        budget = arena['budget_short'] if short else arena['budget_long']
        arms = arena['arms_short'] if short else arena['arms_long']
        tag = f'arena_{budget}s'
        keep = None if short else fs_long_missions(store, config)
        units = [('fs', tag, vid, payload, budget, arms) for vid, payload, ledger in fs_instances(store)
                 if (keep is None or ledger['mission'] in keep) and not store.exists('fs', tag, vid)]
        _pool('arena', path, config, units, workers, log, name)
    elif name == 'ls-build':
        ls_build(store, config, workers, log)
    elif name in ('ls-arena-short', 'ls-arena-long'):
        short = name.endswith('short')
        budget = arena['budget_short'] if short else arena['budget_long']
        arms = arena['arms_short'] if short else arena['arms_long']
        tag = f'arena_{budget}s'
        units = [('ls', tag, n, payload, budget, arms) for n, payload in ls_instances(store)
                 if not store.exists('ls', tag, n)]
        _pool('arena', path, config, units, workers, log, name)
    elif name == 'p1-label':
        cases = p1_payloads(config, _limit(p1_cases(config), config['p1'].get('limit'), config['p1'].get('seed', 0)))
        units = [('p1', c, payload) for c, payload in cases if not store.exists('p1', 'labels', c)]
        _pool('label', path, config, units, workers, log, name)
    elif name == 'p1-arena':
        p1 = config['p1']
        tag = f"arena_{p1['budget_s']}s"
        cases = p1_payloads(config, _limit(p1_cases(config), p1.get('limit'), p1.get('seed', 0)))
        units = [('p1', tag, c, payload, p1['budget_s'], p1['arms']) for c, payload in cases
                 if not store.exists('p1', tag, c)]
        _pool('arena', path, config, units, workers, log, name)
    elif name == 'xr':
        cases = p1_payloads(config, p1_cases(config, lower_at_least=0))
        chains = {}
        for case, payload in cases:
            mission, strength, slack = case.rsplit('_', 2)
            chains.setdefault(f'{mission}_{strength}', []).append((int(slack[1:]), case, payload))
        names = _limit(sorted(chains), config['xr'].get('limit'), config['xr'].get('seed', 0))
        units = [(name_, [(c, p) for _, c, p in sorted(chains[name_])]) for name_ in names
                 if not store.exists('xr', 'chains', name_)]
        _pool('chain', path, config, units, workers, log, name)
    elif name == 'scaling':
        from escalation_study.missions import mission_id
        sc = config['scaling']
        units = [(n, m, family, seed) for n, m in sc['sizes'] for family in sc['families'] for seed in sc['seeds']]
        if sc.get('missions'):          # a chosen subset of the cohort (e.g. a pilot of the hard cases)
            units = [u for u in units if mission_id(*u) in sc['missions']]
        _pool('scaling', path, config, units, workers, log, name)
    elif name == 'fs-d1':
        units = d1_units(store, config)
        _pool('fs_d1', path, config, units, workers, log, name)
    elif name == 'contention':
        contention(store, config, log)
    elif name == 'gr-seeds':
        variance(store, config, workers, log)
    elif name == 'report':
        from .analysis import write_report
        summary = write_report(store, config)
        log('report written: '+str(summary['report']))
    else:
        raise ValueError('unknown stage: '+name)


def d1_units(store, config):
    """In-flight FS variants, to be rebuilt under D1 (the destination of an airborne UAV committed)."""
    units = []
    for path in store.all('fs', 'missions'):
        mission = path.name[:-len('.json.gz')]
        ledger = store.load('fs', 'missions', mission)['ledger']
        if ledger['status'] != 'accepted':
            continue
        for vid, info in sorted(ledger['variants'].items()):
            if info['time_index'] != 0 and not store.exists('fs_d1', 'labels', vid+'_D1'):
                units.append((vid+'_D1', mission, vid))
    return units


def ls_build(store, config, workers, log):
    """Draw in batches toward unfilled (class, fleet) cells; select in draw order."""
    from .levelsuite import CLASS_NAMES, draw_id, select
    ls = config['ls']
    used = {(c, f): 0 for c in CLASS_NAMES for f in ls['fleets']}
    order = []
    while True:
        draws = []
        for name in order:
            item = store.load('ls', 'draws', name)
            if item is None:        # the draw failed (logged); the next run retries it
                continue
            lab = store.load('ls', 'labels', name)
            draws.append((name, item['ledger'], lab))
        selection = select(draws, ls)
        open_cells = []
        for key, full in selection['full'].items():
            c, f = key.split('|')
            if not full and used[c, int(f)] < ls['max_draws_per_cell']:
                open_cells.append((c, int(f)))
        log(f"ls-build: {len(order)} draws, filled {sum(selection['full'].values())}/{len(selection['full'])} cells, "
            f"residue pool {selection['residue_pool']}")
        if not open_cells:
            break
        batch = []
        while len(batch) < ls['batch']:
            progressed = False
            for c, f in open_cells:
                if used[c, f] < ls['max_draws_per_cell'] and len(batch) < ls['batch']:
                    batch.append((c, f, used[c, f], draw_id(c, f, used[c, f])))
                    used[c, f] += 1
                    progressed = True
            if not progressed:
                break
        if not batch:
            break
        _pool('ls_draw', store.path, config, batch, workers, log, 'ls-draws')
        order += [b[3] for b in batch]
    store.save(dict(version='final-study-ls-selection-v1', order=order, selection=selection), 'ls', 'selection',
               'selection')


def contention(store, config, log):
    """Rerun a seeded subset of FS instances on one worker to measure the contention factor."""
    c = config['contention']
    instances = fs_instances(store)
    if not instances:
        return
    rng = random.Random(c['seed'])
    chosen = sorted(rng.sample(range(len(instances)), min(c['instances'], len(instances))))
    budget = config['arena']['budget_short']
    units = [('contention', f'arena_{budget}s', instances[i][0], instances[i][1], budget, c['arms'])
             for i in chosen if not store.exists('contention', f'arena_{budget}s', instances[i][0])]
    _pool('arena', store.path, config, units, 1, log, 'contention (one worker)')


def variance(store, config, workers, log):
    """The randomized arms (GR, GR-c) with other seeds on a seeded subset of FS instances."""
    v = config.get('variance', dict(instances=30, seeds=[1, 2], seed=76004, arms=['GR', 'GR-c']))
    instances = fs_instances(store)
    if not instances:
        return
    rng = random.Random(v['seed'])
    chosen = sorted(rng.sample(range(len(instances)), min(v['instances'], len(instances))))
    budget = config['arena']['budget_short']
    units = []
    for seed in v['seeds']:
        tag = f'arena_{budget}s_seed{seed}'
        units += [('variance', tag, instances[i][0], instances[i][1], budget, v['arms'], seed)
                  for i in chosen if not store.exists('variance', tag, instances[i][0])]
    _pool('arena', store.path, config, units, workers, log, 'gr-seeds')


def run(out, config, *, stages=STAGES, workers=1, log=print):
    store = Store(out, config, workers=workers)
    for name in stages:
        started = time.time()
        log(f'=== stage {name} ===')
        try:
            stage(name, store, config, workers, log)
        except Exception as error:      # logged and listed in the report; the later stages still run
            message = f'FAILED: {type(error).__name__}: {error}'
            log(f'=== stage {name} {message} ===')
            log(traceback.format_exc().rstrip())
            _note(store.path, 'stages', name, message)
            continue
        _note(store.path, 'stages', name, None)
        log(f'=== stage {name} done in {(time.time()-started)/60:.1f} min ===')
    return store
