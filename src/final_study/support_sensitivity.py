"""Support sensitivity: the FS reference variants relabelled with updates from 1 to 15 of 16 cells.

docs/SUPPORT_SENSITIVITY_DESIGN_2026_10_21.md (decisions 1a, 2 and 3). Each of the 53 missions
of the 60 s arena third keeps its stored ``_r1_t0`` variant; only the received wind table and
``update_support`` change. The supports follow from grid positions alone (never the plan):

- S1 the seed cell (the stored update cell), r d;
- S2 the 2 x 2 block with the seed, extended toward the grid centre, r d;
- S3 the 3 x 3 block with the seed, starting at clamp(x-1, 0, 1), r d;
- S4 the seed (r d) and its Chebyshev neighbours (r d / 2);
- S5 every cell but the corner farthest from the seed (ties by cell id), r d.

Stages (each resumable unit by unit, as in the final study): build (payloads and diagnosis per
mission), label (CMI at the FS reference budget, replayed), arena (CMI, LR, GR-c, GR at the
short budget, replayed), replay (every stored label and arena record replayed again from its
proof file) and report.
"""
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from fractions import Fraction
import multiprocessing
from pathlib import Path
import statistics
import time
import traceback

from env.local_scope import affected_uavs, scope_family
from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update
from escalation_study.missions import _decimal_vector
from .arena import label, replay_saved, run_instance
from .store import Store

CONDITIONS = ('S1', 'S2', 'S3', 'S4', 'S5')
VARIANT = '_r1_t0'
ARMS = ('GR', 'GR-c', 'LR', 'CMI')
STAGES = ('build', 'label', 'arena', 'replay', 'report')
HALF = Fraction(1, 2)


# ---- conditions -------------------------------------------------------------------------
def grid_positions(cells):
    """(column, row) of every wind cell, from the lower-left corners of the polygons."""
    corners = [(min(Fraction(str(x)) for x, _ in c['polygon_xy']), min(Fraction(str(y)) for _, y in c['polygon_xy']))
               for c in cells]
    xs, ys = sorted({x for x, _ in corners}), sorted({y for _, y in corners})
    if len(xs) != 4 or len(ys) != 4 or len(cells) != 16:
        raise ValueError('the support rules are defined on the 4 x 4 grid')
    return [(xs.index(x), ys.index(y)) for x, y in corners]


def supports(cells, seed):
    """Condition -> {cell index: multiple of r d}, from the grid and the seed cell index only."""
    position = grid_positions(cells)
    index = {p: i for i, p in enumerate(position)}
    x, y = position[seed]
    pair = lambda v: (v, v+1) if v <= 1 else (v-1, v)
    start = lambda v: min(max(v-1, 0), 1)
    block = lambda xs, ys: {index[a, b]: Fraction(1) for a in xs for b in ys}
    bump = {index[a, b]: Fraction(1) if (a, b) == (x, y) else HALF
            for a in range(x-1, x+2) for b in range(y-1, y+2) if (a, b) in index}
    corners = [index[a, b] for a in (0, 3) for b in (0, 3)]
    far = min(corners, key=lambda i: (-((position[i][0]-x)**2+(position[i][1]-y)**2), cells[i]['id']))
    return dict(S1={seed: Fraction(1)}, S2=block(pair(x), pair(y)),
                S3=block(range(start(x), start(x)+3), range(start(y), start(y)+3)), S4=bump,
                S5={i: Fraction(1) for i in range(len(cells)) if i != far})


def condition_payload(source, ledger, code):
    """The payload of one condition: the stored reference variant with a new received wind.

    S1 is the stored variant itself (same benchmark id, same content hash)."""
    vid = source['benchmark_id']
    wind = source['wind']
    if len(wind['time_knots_h']) != 2:
        raise ValueError('the conditions assume one time bin')
    strength = Fraction(ledger['variants'][vid]['strength'])
    v_min = min(Fraction(str(u['airspeed_kmh'])) for u in source['mission']['vehicles'])
    direction = [Fraction(c) for c in ledger['direction']]
    support = supports(wind['cells'], ledger['cell_index'])[code]
    q = deepcopy(source)
    received = q['wind']['received']['values']
    for r, row in enumerate(wind['previous']['values']):
        received[r] = deepcopy(row)
    for c, factor in support.items():
        received[c][0] = _decimal_vector(tuple(factor*strength*v_min*d for d in direction))
    q['wind']['update_support'] = [[wind['cells'][c]['id'], 0] for c in sorted(support)]
    if code != 'S1':
        q['benchmark_id'] = f'{vid}_{code}'
    return Scenario(q).to_dict()


def diagnosis(payload):
    """Update cells, affected UAVs and tasks, and whether Level 3 already releases the fleet."""
    s = Scenario(payload)
    d = diagnose_wind_update(s)
    u0 = affected_uavs(s, d)['uavs']
    fleet = set(s.data['state']['fleet'])
    return dict(support_cells=len(payload['wind']['update_support']), u0=u0, u0_count=len(u0),
                u0_share=len(u0)/len(fleet), fleet=len(fleet), local=len(u0) <= len(fleet)//2,
                affected_tasks=sorted(d.affected_tasks), affected_task_count=len(d.affected_tasks),
                level3_is_level4=all(set(p.participants) == fleet for p in scope_family(s, 3, u0)))


# ---- the run ----------------------------------------------------------------------------
def missions(fs_store):
    """The 53 missions of the 60 s arena third, as the final study drew them."""
    from .stages import fs_long_missions
    return sorted(fs_long_missions(fs_store, fs_store.manifest['config']))


def instance_id(mission, code):
    return f'{mission}{VARIANT}_{code}'


def _build(store_path, config, mission):
    store = Store(store_path, config, bind=False)
    if store.exists('ss', 'conditions', mission):
        return mission, 'exists'
    fs = Store(config['support_sensitivity']['source'], None, bind=False)
    item = fs.load('fs', 'missions', mission)
    ledger = item['ledger']
    vid = mission+VARIANT
    source = item['variants'][vid]
    out = {}
    for code in CONDITIONS:
        payload = condition_payload(source, ledger, code)
        out[code] = dict(instance=instance_id(mission, code), payload=payload,
                         input_hash=Scenario(payload).content_hash(), diagnosis=diagnosis(payload))
    if out['S1']['input_hash'] != ledger['variants'][vid]['scenario_hash'] or out['S1']['payload'] != source:
        raise ValueError('S1 differs from the stored reference variant')
    store.save(dict(version='support-sensitivity-conditions-v1', mission=mission, source_variant=vid,
                    cell_index=ledger['cell_index'], direction=ledger['direction'],
                    m=ledger['m'], k=ledger['k'], sigma=ledger['sigma'], beta=ledger['beta'],
                    family=ledger['family'], conditions=out), 'ss', 'conditions', mission)
    return mission, 'built'


def _label(store_path, config, unit):
    instance, payload = unit
    store = Store(store_path, config, bind=False)
    if store.exists('ss', 'labels', instance):
        return instance, 'exists'
    record = label(instance, payload, config['label_budget_s'], config['settings'])
    store.save(record, 'ss', 'labels', instance)
    return instance, str(record['result']['bounds']['minimum'])


def _arena(store_path, config, unit):
    instance, payload = unit
    ss = config['support_sensitivity']
    store = Store(store_path, config, bind=False)
    tag = f"arena_{ss['arena_budget_s']}s"
    if store.exists('ss', tag, instance):
        return instance, 'exists'
    record = run_instance(instance, payload, ss['arena_budget_s'], tuple(ss['arena_arms']), config['settings'])
    store.save(record, 'ss', tag, instance)
    return instance, 'done'


def _replay(store_path, config, unit):
    kind, instance, payload = unit
    store = Store(store_path, config, bind=False)
    if store.exists('ss', 'replay', kind, instance):
        return f'{kind}/{instance}', 'exists'
    record = store.load('ss', kind, instance)
    audits = replay_saved(payload, record, store.load_proofs(record))
    store.save(dict(version='support-sensitivity-replay-v1', instance=instance, record=kind,
                    source_record_hash=record['record_hash'], audits=audits), 'ss', 'replay', kind, instance)
    failed = [arm for arm, a in audits.items() if not a['ok']]
    return f'{kind}/{instance}', 'FAILED: replay of '+', '.join(failed) if failed else 'ok'


JOBS = dict(build=_build, label=_label, arena=_arena, replay=_replay)


def _dispatch(kind, store_path, config, unit):
    try:
        return JOBS[kind](store_path, config, unit)
    except Exception as error:      # the unit leaves no record, so a rerun retries it
        name = unit if isinstance(unit, str) else unit[-2] if kind == 'replay' else unit[0]
        return name, 'FAILED: '+''.join(traceback.format_exception_only(type(error), error)).strip()[:400]


def _pool(kind, store, units, workers, log):
    from .stages import _progress
    if not units:
        log(f'{kind}: nothing to do')
        return []
    start, out = time.time(), []
    context = multiprocessing.get_context('spawn')
    with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
        futures = [pool.submit(_dispatch, kind, str(store.path), store.config, u) for u in units]
        for i, future in enumerate(as_completed(futures), 1):
            out.append(future.result())
            _progress(log, kind, i, len(units), start, out[-1])
    failures = [o for o in out if str(o[1]).startswith('FAILED')]
    for name, message in failures:
        log(f'{kind}: unit {name} {message}')
    if failures:
        log(f'{kind}: {len(failures)} of {len(units)} units failed; a rerun retries them')
    return out


def conditions(store):
    """[(mission, conditions record)] of every built mission."""
    return [(p.name[:-len('.json.gz')], store.load('ss', 'conditions', p.name[:-len('.json.gz')]))
            for p in store.all('ss', 'conditions')]


def run(out, config, *, stages=STAGES, workers=6, log=print):
    """Bind the run once here; workers write under that binding (``Store(bind=False)``)."""
    store = Store(out, config, workers=workers)
    ss = config['support_sensitivity']
    fs = Store(ss['source'], None, bind=False)
    if fs.manifest['config'] != {k: v for k, v in config.items() if k != 'support_sensitivity'}:
        raise ValueError('the configuration differs from the one the final study ran with')
    names = missions(fs)
    if ss.get('limit'):
        names = names[:ss['limit']]
    tag = f"arena_{ss['arena_budget_s']}s"
    for name in stages:
        started = time.time()
        log(f'=== stage {name} ===')
        if name == 'build':
            _pool('build', store, [n for n in names if not store.exists('ss', 'conditions', n)], workers, log)
        elif name in ('label', 'arena'):
            group = 'labels' if name == 'label' else tag
            units = [(c['instance'], c['payload']) for _, item in conditions(store)
                     for c in item['conditions'].values() if not store.exists('ss', group, c['instance'])]
            _pool(name, store, units, workers, log)
        elif name == 'replay':
            units = [(kind, c['instance'], c['payload']) for _, item in conditions(store)
                     for c in item['conditions'].values() for kind in ('labels', tag)
                     if store.exists('ss', kind, c['instance']) and not store.exists('ss', 'replay', kind, c['instance'])]
            _pool('replay', store, units, workers, log)
        elif name == 'report':
            log('report written: '+str(write_report(store, config)))
        else:
            raise ValueError('unknown stage: '+name)
        log(f'=== stage {name} done in {(time.time()-started)/60:.1f} min ===')
    return store


# ---- report -----------------------------------------------------------------------------
def _rows(store, config):
    """Per instance: diagnosis, label, FS label of the source variant, arena rows and replays."""
    from .analysis import _arena_row, _bracket, _certificate_cpu, _code, _within_budget
    ss = config['support_sensitivity']
    fs = Store(ss['source'], None, bind=False)
    tag = f"arena_{ss['arena_budget_s']}s"
    rows, arena = [], []
    for mission, item in conditions(store):
        for code, c in item['conditions'].items():
            record = store.load('ss', 'labels', c['instance'])
            if record is None:
                continue
            result = record['result']
            lower, upper = _bracket(result['bounds'])
            row = dict(mission=mission, instance=c['instance'], code=code, m=item['m'], **c['diagnosis'],
                       label_lower=lower, label_upper=upper, label_audit=record['audit']['ok'],
                       label_minimum=_code(result['bounds']['minimum']) if result['bounds']['minimum'] is not None else None,
                       label_status=result['bounds']['status'], label_cpu=result['clock']['cpu_s'],
                       certificate_cpu=_certificate_cpu(result), level0_excluded=0 in result['bounds']['excluded_levels'],
                       label_plan_level=result['plan_level'], mask_matches=result['mask_u0'] == c['diagnosis']['u0'],
                       input_hash=record['input_hash'])
            replay = store.load('ss', 'replay', 'labels', c['instance'])
            row['label_replay'] = None if replay is None else all(a['ok'] for a in replay['audits'].values())
            if code == 'S1':
                stored = fs.load('fs', 'labels', item['source_variant'])
                row['fs_bounds'] = stored['result']['bounds']
                row['fs_input_hash'] = stored['input_hash']
                row['fs_agrees'] = stored['result']['bounds'] == result['bounds']
            rows.append(row)
            record = store.load('ss', tag, c['instance'])
            if record is None:
                continue
            replay = store.load('ss', 'replay', tag, c['instance'])
            for arm, entry in record['arms'].items():
                r = _within_budget(_arena_row(record, arm, entry))
                r.update(mission=mission, code=code,
                         replay_ok=None if replay is None else replay['audits'][arm]['ok'])
                arena.append(r)
    # Reference: the label bracket pooled with every replayed arena plan (as in the final study).
    best = {}
    for r in arena:
        if r['audit_ok'] and r['replay_ok'] is not False and r['plan_level'] is not None:
            best[r['instance']] = min(best.get(r['instance'], 9), r['plan_level'])
    for row in rows:
        lower, upper = (row['label_lower'], row['label_upper']) if row['label_audit'] else (0, None)
        if row['instance'] in best:
            upper = best[row['instance']] if upper is None else min(upper, best[row['instance']])
        row.update(ref_lower=lower, ref_upper=upper, ref_min=5 if lower == 5 else lower if upper == lower else None)
    ref = {row['instance']: row for row in rows}
    for r in arena:
        r['ref_min'] = ref[r['instance']]['ref_min'] if r['instance'] in ref else None
        r['at_min'] = r['plan_level'] is not None and r['ref_min'] is not None and r['plan_level'] == r['ref_min']
    return rows, arena


def _mean(key):
    return lambda rs: statistics.mean(r[key] for r in rs) if rs else None


def _q(key, q):
    from .analysis import quantile
    return lambda rs: quantile([r[key] for r in rs], q)


def _num(point, lo, hi, digits=2):
    if point is None:
        return '-'
    return f'{point:.{digits}f}' if lo is None else f'{point:.{digits}f} [{lo:.{digits}f}, {hi:.{digits}f}]'


def write_report(store, config):
    from .analysis import _level_name, _table, bootstrap, ci, share
    import json
    ss = config['support_sensitivity']
    rows, arena = _rows(store, config)
    out = store.path/'analysis'
    out.mkdir(parents=True, exist_ok=True)
    by = {code: [r for r in rows if r['code'] == code] for code in CONDITIONS}
    certified = lambda r: r['label_minimum'] is not None
    summary = dict(run_hash=store.run_hash, missions=len({r['mission'] for r in rows}), instances=len(rows),
                   arena_rows=len(arena), conditions={})
    lines = ['# Support sensitivity: results', '',
             f"Run `{store.path.as_posix()}`, run hash `{store.run_hash[:16]}`; source `{ss['source']}` (read-only). "
             f"{summary['missions']} missions x {len(CONDITIONS)} conditions = {len(rows)} labelled instances. "
             f"Labels: CMI, {config['label_budget_s']:g} s CPU, one pass. Arena: {', '.join(ss['arena_arms'])} at "
             f"{ss['arena_budget_s']:g} s. Intervals: 95% percentile bootstrap over missions (2000 resamples, seed 1).", '']
    # Integrity.
    s1 = by['S1']
    labels_ok = sum(r['label_audit'] for r in rows)
    replays = [r['label_replay'] for r in rows]+[r['replay_ok'] for r in arena]
    lines += ['## Integrity', '',
              _table(['check', 'result'], [
                  ['S1 payload hash = stored `_r1_t0` hash', f"{sum(r['input_hash'] == r['fs_input_hash'] for r in s1)}/{len(s1)}"],
                  ['S1 label bounds = stored FS label bounds', f"{sum(r['fs_agrees'] for r in s1)}/{len(s1)}"],
                  ['labels replayed in-run (audit ok)', f'{labels_ok}/{len(rows)}'],
                  ['arena results replayed in-run (audit ok)', f"{sum(r['audit_ok'] for r in arena)}/{len(arena)}"],
                  ['stored records replayed again from proof files', f"{sum(v is True for v in replays)}/{len(replays)} ok, "
                                                                     f"{sum(v is False for v in replays)} failed, {sum(v is None for v in replays)} not replayed"],
                  ['CMI affected set = diagnosed U0', f"{sum(r['mask_matches'] for r in rows)}/{len(rows)}"]]), '']
    disagree = [r for r in s1 if not r['fs_agrees']]
    if disagree:
        lines += ['S1 labels that differ from the stored FS label:', '',
                  _table(['instance', 'FS bounds', 'this run'], [
                      [r['instance'], json.dumps(r['fs_bounds']), f"lower {r['label_lower']}, upper {r['label_upper']}, {r['label_status']}"]
                      for r in disagree]), '']
    # Diagnosis.
    table = []
    for code in CONDITIONS:
        rs = by[code]
        if not rs:
            continue
        table.append([code, len(rs), _num(*bootstrap(rs, _mean('support_cells'))), _num(*bootstrap(rs, _mean('u0_count'))),
                      ci(*bootstrap(rs, _mean('u0_share'))), _num(*bootstrap(rs, _mean('affected_task_count'))),
                      ci(*bootstrap(rs, share(lambda r: r['local']))), ci(*bootstrap(rs, share(lambda r: r['level3_is_level4']))),
                      ci(*bootstrap(rs, share(lambda r: r['level0_excluded'])))])
    lines += ['## Diagnosis', '', 'Means per instance. "local": |U0| <= m/2 (the FS admission limit, not re-screened). '
              '"L3 = L4": the Level-3 release (U0 plus the helper budget) already covers the fleet. '
              '"disrupted": the label proved Level 0 infeasible.', '',
              _table(['condition', 'n', '|B_Δ|', '|U0|', '|U0|/m', '|V^aff|', 'local', 'L3 = L4', 'disrupted'], table), '']
    # Labels.
    table, dist = [], []
    for code in CONDITIONS:
        rs = by[code]
        if not rs:
            continue
        cert = [r for r in rs if certified(r)]
        table.append([code, ci(*bootstrap(rs, share(certified))),
                      _num(*bootstrap(cert, _q('certificate_cpu', .5))), _num(*bootstrap(cert, _q('certificate_cpu', .9))),
                      _num(*bootstrap(rs, _q('label_cpu', .5))), _num(*bootstrap(rs, _q('label_cpu', .9)))])
        brackets = sorted({(r['label_lower'], r['label_upper']) for r in rs if not certified(r)}, key=str)
        dist.append([code, *[ci(*bootstrap(rs, share(lambda r, c=c: r['label_minimum'] == c))) for c in range(6)],
                     ci(*bootstrap(rs, share(lambda r: not certified(r)))),
                     '; '.join(f"[{_level_name(lo)}, {_level_name(hi) if hi is not None else 'no plan'}] x"
                               f"{sum(1 for r in rs if not certified(r) and (r['label_lower'], r['label_upper']) == (lo, hi))}"
                               for lo, hi in brackets) or '-'])
        summary['conditions'][code] = dict(
            n=len(rs), certification=len(cert)/len(rs),
            minimum={_level_name(c): sum(r['label_minimum'] == c for r in rs) for c in range(6)},
            unresolved=len(rs)-len(cert))
    lines += ['## Labels', '', 'Certified minimum level of the label (share of instances; "none" = no continuation is '
              'certified). Unresolved instances are listed with their bracket [lower, upper].', '',
              _table(['condition', '0', '1', '2', '3', '4', 'none', 'unresolved', 'brackets'], dist), '',
              'Certification rate and CPU seconds (process time). CPU to certificate is over certified instances; '
              'label CPU is the whole run, over all instances.', '',
              _table(['condition', 'certified', 'CPU to certificate, median', 'p90', 'label CPU, median', 'p90'], table), '']
    # Pairing.
    s1_min = {r['mission']: r['label_minimum'] for r in by['S1']}
    table = []
    for code in CONDITIONS[1:]:
        pairs = [dict(mission=r['mission'], a=s1_min.get(r['mission']), b=r['label_minimum']) for r in by[code]
                 if r['mission'] in s1_min]
        both = [p for p in pairs if p['a'] is not None and p['b'] is not None]
        if not pairs:
            continue
        table.append([f'S1 -> {code}', len(both), ci(*bootstrap(both, share(lambda p: p['b'] > p['a']))),
                      ci(*bootstrap(both, share(lambda p: p['b'] == p['a']))),
                      ci(*bootstrap(both, share(lambda p: p['b'] < p['a']))), len(pairs)-len(both)])
        summary['conditions'][code]['transition'] = dict(
            higher=sum(p['b'] > p['a'] for p in both), equal=sum(p['b'] == p['a'] for p in both),
            lower=sum(p['b'] < p['a'] for p in both), unpaired=len(pairs)-len(both))
    lines += ['## Pairing with S1', '', 'Missions where both labels certified a minimum ("none" counts as above Level 4). '
              '"Unpaired": either label unresolved.', '',
              _table(['transition', 'pairs', 'higher', 'equal', 'lower', 'unpaired'], table), '']
    lines += ['Transition counts (rows S1 minimum, columns the other condition):', '']
    for code in CONDITIONS[1:]:
        if not by[code]:
            continue
        other = {r['mission']: r['label_minimum'] for r in by[code]}
        keys = [0, 1, 2, 3, 4, 5, None]
        grid = [[_level_name(a)]+[sum(1 for m in s1_min if s1_min[m] == a and other.get(m) == b) for b in keys]
                for a in keys if any(s1_min[m] == a for m in s1_min)]
        lines += [f'S1 -> {code}:', '', _table(['S1 \\ '+code]+[_level_name(b) for b in keys], grid), '']
    # Arena.
    if arena:
        table, diff = [], []
        for code in CONDITIONS:
            for arm in ss['arena_arms']:
                rs = [r for r in arena if r['code'] == code and r['arm'] == arm]
                if not rs:
                    continue
                plans = [r for r in rs if r['plan_level'] is not None and 'd_uavs_changed' in r]
                table.append([code, arm, len(rs), ci(*bootstrap(rs, share(lambda r: r['at_min']))),
                              ci(*bootstrap(rs, share(lambda r: r['plan_level'] is not None))),
                              _num(*bootstrap(plans, _mean('d_uavs_changed'))),
                              ci(*bootstrap(rs, share(lambda r: r['certified'])))])
            cmi = {r['instance']: r for r in arena if r['code'] == code and r['arm'] == 'CMI'}
            for arm in [a for a in ss['arena_arms'] if a != 'CMI']:
                other = {r['instance']: r for r in arena if r['code'] == code and r['arm'] == arm}
                common = sorted(cmi.keys() & other.keys())
                if not common:
                    continue
                at = [dict(mission=cmi[i]['mission'], v=int(cmi[i]['at_min'])-int(other[i]['at_min'])) for i in common]
                ok = [dict(mission=cmi[i]['mission'], v=int(cmi[i]['plan_level'] is not None)-int(other[i]['plan_level'] is not None))
                      for i in common]
                ch = [dict(mission=cmi[i]['mission'], v=cmi[i]['d_uavs_changed']-other[i]['d_uavs_changed']) for i in common
                      if 'd_uavs_changed' in cmi[i] and 'd_uavs_changed' in other[i]]
                diff.append([code, f'CMI - {arm}', len(common), _num(*bootstrap(at, _mean('v')), digits=3),
                             _num(*bootstrap(ok, _mean('v')), digits=3), _num(*bootstrap(ch, _mean('v'))), len(ch)])
        lines += [f"## Arena ({ss['arena_budget_s']:g} s)", '',
                  'Each arm is scored on the plan it returned within the budget (replayed), as in the final study. '
                  '"At reference minimum": the returned plan is at the pooled reference minimum (label bracket closed '
                  'with every replayed arena plan); denominator all instances. "UAVs changed": mean over returned plans.', '',
                  _table(['condition', 'arm', 'n', 'plan at reference minimum', 'recovery success', 'UAVs changed',
                          'certified'], table), '',
                  'Paired differences, CMI minus each arm (instances both ran; UAVs changed on instances where both '
                  'returned a plan, count in the last column):', '',
                  _table(['condition', 'difference', 'n', 'at reference minimum', 'recovery success', 'UAVs changed',
                          'pairs with plans'], diff), '']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    (out/'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    return out/'REPORT.md'
