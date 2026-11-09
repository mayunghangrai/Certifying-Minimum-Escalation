"""Tables, bootstrap intervals and figures for a P1 run directory.

The unit of inference is the base mission: every resample draws whole missions,
because all slack/strength variants of a mission share its geometry and update.
Unresolved minima stay a separate category; identification intervals show how
far they could move each share.
"""
import csv
from collections import Counter, defaultdict
from fractions import Fraction
import json
from pathlib import Path
import random

from env.local_scope import change_metrics
from env.scenario import Scenario
from .ladder import STAGES, witness_level
from .store import read_gzip_json

CATEGORIES = ('0', '1', '2', '3', '4', 'infinity', 'unresolved')
COLORS = {'0': '#86b6ef', '1': '#5598e7', '2': '#2a78d6', '3': '#1c5cab', '4': '#104281',
          'infinity': '#eb6834', 'unresolved': '#c3c2b7'}
LABELS = {'0': 'Level 0', '1': 'Level 1', '2': 'Level 2', '3': 'Level 3', '4': 'Level 4',
          'infinity': 'No continuation', 'unresolved': 'Unresolved'}
SERIES = ('#2a78d6', '#eb6834', '#1baf7a')
INK, MUTED, GRID, SURFACE = '#0b0b0b', '#52514e', '#e1e0d9', '#fcfcfb'


def category(b):
    if b['minimum'] is None:
        return 'unresolved'
    return 'infinity' if b['minimum'] == 'infinity' else str(b['minimum'])


def _order(value):
    return 5 if value == 'infinity' else int(value)


def load(run):
    run = Path(run)
    ledgers = {p.stem: json.loads(p.read_text(encoding='utf-8')) for p in sorted((run/'missions').glob('*.json'))}
    phases = {}
    for phase in ('pass1', 'pass2'):
        root = run/'records'/phase
        phases[phase] = {}
        if root.exists():
            for path in sorted(root.rglob('*.json.gz')):
                record = read_gzip_json(path)
                phases[phase][record['case_id']] = record
    return ledgers, phases


def _closing_time(result, offset):
    """Seconds from the variant's first pass start until its bounds closed."""
    excluded, upper = set(), None
    if result['transfer']:
        excluded |= set(range(result['transfer']['excluded_through']+1))
    if result['prior']:
        excluded |= set(result['prior']['excluded_levels'])
        upper = result['prior']['upper']

    def closed():
        lower = None if 4 in excluded else 1+max(excluded, default=-1)
        return lower is None or (upper is not None and upper == lower)
    if closed():
        return offset, offset
    for event in sorted(result['events'], key=lambda e: e['wall_s']):
        if event['kind'] == 'exclusion':
            excluded |= set(range(event['level']+1))
        else:
            upper = event['level'] if upper is None else min(upper, event['level'])
        if closed():
            cpu = event['cpu_s']
            if cpu is None:
                # Screen events carry wall time only; charge CPU through the end of that stage.
                cpu = sum(result['timing'][s]['cpu_s'] for s in STAGES[:STAGES.index(event['stage'])+1]
                          if s in result['timing'])
            return offset+event['wall_s'], offset+cpu
    total = result['timing']['total']
    return offset+total['wall_s'], offset+total['cpu_s']


def _best_change(scenario, result, u0):
    """Changed-plan counts for the lowest-level witness the variant holds."""
    best = None
    for stage in STAGES:
        report = result['stages'][stage]
        if report and report.get('witness'):
            w = report['witness']
            if stage == 'screen':
                level, change = w['validation']['level'], report['change']
            else:
                level = witness_level(scenario, w, u0)[0]
                exact = {':'.join(map(str, c)): v for c, v in zip(w['columns'], w['values'])}
                change = change_metrics(scenario, w['plan'], u0, exact_quantities=exact)
            if best is None or level < best[0]:
                best = (level, change)
    for item in result['revalidated']:
        if best is None or item['level'] < best[0]:
            w = item['witness']
            exact = ({':'.join(map(str, c)): v for c, v in zip(w['columns'], w['values'])}
                     if w.get('kind') == 'quantity_primal_v1' else None)
            best = (item['level'], change_metrics(scenario, w['plan'], u0, exact_quantities=exact))
    return best


def _work(result):
    counters = Counter()
    for stage in STAGES:
        report = result['stages'][stage]
        if not report or report.get('unsupported'):
            continue
        effort = report['effort']
        if stage == 'screen':
            counters['proposals'] += effort['generated_proposals']
            counters['candidate_checks'] += effort['candidate_checks']
            for k in ('queries', 'cache_hits', 'conic_paths', 'potential_fields'):
                counters['oracle_'+k] += effort['oracle'][k]
        elif stage == 'level2':
            counters['level2_nodes'] += effort['visited']
            counters['farkas_or_ground_proofs'] += sum(n['kind'] == 'quantity' for n in report['nodes'])
            counters['primal_witnesses'] += sum(n['kind'] == 'witness' for n in report['nodes'])
            for k in ('queries', 'conic_paths', 'potential_fields'):
                counters['oracle_'+k] += effort['oracle'][k]
        else:
            counters[stage+'_assignment_nodes'] += effort['assignment_nodes']
            counters[stage+'_sequence_nodes'] += effort['sequence_nodes']
            entries = report['patches'] if stage == 'level3' else [report['tree']]
            for entry in entries:
                for node in entry['nodes']:
                    if node['kind'] == 'sequence':
                        counters['farkas_or_ground_proofs'] += sum(n['kind'] == 'quantity' for n in node['proof']['nodes'])
                        counters['primal_witnesses'] += sum(n['kind'] == 'witness' for n in node['proof']['nodes'])
            for k in ('queries', 'conic_paths', 'potential_fields'):
                counters['oracle_'+k] += effort['shared_cache'][k]
    return counters


def rows(run):
    ledgers, phases = load(run)
    table = []
    for mission, item in sorted(ledgers.items()):
        ledger = item['ledger']
        if ledger['status'] != 'accepted':
            continue
        for case, info in sorted(ledger['variants'].items()):
            first = phases['pass1'].get(case)
            if first is None:
                continue
            second = phases['pass2'].get(case)
            final = second or first
            result = final['result']
            scenario = Scenario(item['scenarios'][case])
            u0 = ledger['affected']
            offset = first['result']['timing']['total']['wall_s'] if second else 0.
            cpu_offset = first['result']['timing']['total']['cpu_s'] if second else 0.
            certified = result['bounds']['minimum'] is not None
            closing = _closing_time(result, 0.) if certified else (None, None)
            exposure = ledger['exposure'][info['strength']]
            change = _best_change(scenario, result, u0)
            stop = {s: v for s, v in result['stop'].items() if v != 'skipped'}
            row = dict(case=case, mission=mission, n=ledger['n'], m=ledger['m'], family=ledger['family'],
                       seed=ledger['seed'], tasks_per_uav=ledger['n']//ledger['m'],
                       update_fraction=ledger.get('update_fraction', '0'),
                       committed_failure=any(c.get('kind') == 'committed_prefix_lower_v1'
                                             for c in (result['stages']['screen'] or {}).get('exclusions', [])),
                       strength=info['strength'], slack=info['slack'], strength_index=info['strength_index'],
                       slack_index=info['slack_index'], category=category(result['bounds']),
                       lower='' if result['bounds']['lower'] is None else result['bounds']['lower'],
                       upper='' if result['bounds']['upper'] is None else result['bounds']['upper'],
                       final_phase=final['phase'], u0_count=len(u0),
                       affected_speed_ranks=';'.join(str(ledger['speed_ranks'][u]['rank']) for u in u0),
                       max_headwind_kmh=max([-e['along_track_kmh'] for e in exposure] or [0.]),
                       incumbent_delay_h=('' if 'incumbent_delay' not in ledger
                                          else float(Fraction(ledger['incumbent_delay'][info['strength']][0]))),
                       exposed_length_km=sum(e['length_km'] for e in exposure),
                       transferred=bool(result['transfer']), revalidated=bool(result['revalidated']),
                       changed_uavs='' if not change or change[1] is None else change[1]['changed_uav_count'],
                       outside_changed='' if not change or change[1] is None else change[1]['outside_changed'],
                       assignment_changes='' if not change or change[1] is None else change[1]['assignment_changes'],
                       wall_s=offset+result['timing']['total']['wall_s'],
                       cpu_s=cpu_offset+result['timing']['total']['cpu_s'],
                       certificate_wall_s='' if closing[0] is None else (offset if second else 0.)+closing[0],
                       certificate_cpu_s='' if closing[1] is None else (cpu_offset if second else 0.)+closing[1],
                       stops=';'.join(f'{k}:{v}' for k, v in stop.items()),
                       **_work(result))
            table.append(row)
    return table, ledgers


def _groups(table, keys):
    groups = defaultdict(list)
    for row in table:
        groups[tuple(row[k] for k in keys)].append(row)
    return groups


def shares(table, keys, *, resamples=2000, seed=20261008):
    """Share of missions per category, with mission-cluster bootstrap and identification bounds."""
    rng = random.Random(seed)
    out = []
    for key, members in sorted(_groups(table, keys).items(), key=lambda kv: [_sort(v) for v in kv[0]]):
        by_mission = defaultdict(list)
        for row in members:
            by_mission[row['mission']].append(row)
        missions = sorted(by_mission)
        total = len(members)
        counts = Counter(r['category'] for r in members)
        draws = {c: [] for c in CATEGORIES}
        for _ in range(resamples):
            sample = [rng.choice(missions) for _ in missions]
            rows_ = [r for m in sample for r in by_mission[m]]
            c = Counter(r['category'] for r in rows_)
            for k in CATEGORIES:
                draws[k].append(c[k]/len(rows_))
        for k in CATEGORIES:
            values = sorted(draws[k])
            possible = 0 if k == 'unresolved' else sum(
                1 for r in members if r['category'] == 'unresolved' and _possible(r, k))
            out.append(dict(**dict(zip(keys, key)), category=k, missions=len(missions), variants=total,
                            count=counts[k], share=counts[k]/total,
                            ci_low=values[int(.025*resamples)], ci_high=values[int(.975*resamples)-1],
                            identified_low=counts[k]/total,
                            identified_high=(counts[k]+possible)/total if k != 'unresolved' else counts[k]/total))
    return out


def _possible(row, k):
    lower = 5 if row['lower'] == '' else row['lower']
    upper = 5 if row['upper'] == '' else row['upper']
    return lower <= _order(k) <= upper


def _sort(value):
    try:
        return float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError):
        return value


def bands(table, slacks):
    """Bracket each mission's level thresholds between adjacent slack values."""
    out = []
    for (mission, strength), members in sorted(_groups(table, ('mission', 'strength')).items()):
        members = sorted(members, key=lambda r: r['slack_index'])
        levels = [r['category'] for r in members]
        row = dict(mission=mission, strength=strength, tasks_per_uav=members[0]['tasks_per_uav'],
                   levels=';'.join(f"{r['slack']}:{r['category']}" for r in members),
                   complete_grid=len(members) == len(slacks), level4_only_band=any(c == '4' for c in levels),
                   any_unresolved=any(c == 'unresolved' for c in levels))
        for k in range(4):
            # A witness at level <= k shows the level suffices; a lower bound above k
            # shows it fails. A threshold is bracketed only when the grid shows both.
            inside = [r for r in members if r['upper'] != '' and r['upper'] <= k]
            outside = [r for r in members if r['lower'] == '' or r['lower'] > k]
            row[f'level{k}_suffices_through'] = inside[-1]['slack'] if inside else ''
            row[f'level{k}_fails_from'] = outside[0]['slack'] if outside else ''
        out.append(row)
    return out


def stronger_wind_relief(table):
    """Mission and slack pairs whose certified level falls as wind strength rises."""
    pairs, falls = 0, []
    for (mission, slack), members in sorted(_groups(table, ('mission', 'slack')).items()):
        members = sorted(members, key=lambda r: r['strength_index'])
        for a, b in zip(members, members[1:]):
            if 'unresolved' in (a['category'], b['category']):
                continue
            pairs += 1
            if _order(b['category']) < _order(a['category']):
                falls.append(dict(mission=mission, slack=slack, weaker=a['strength'], stronger=b['strength'],
                                  weaker_level=a['category'], stronger_level=b['category']))
    return pairs, falls


def certified_by_budget(table, budgets, field):
    out = []
    for tpu, members in sorted(_groups(table, ('tasks_per_uav',)).items()):
        for b in budgets:
            done = sum(1 for r in members if r[field] != '' and r[field] <= b)
            out.append(dict(tasks_per_uav=tpu[0], budget_s=b, certified=done, variants=len(members),
                            fraction=done/len(members)))
    return out


def _write_csv(path, rows_):
    if not rows_:
        path.write_text('', encoding='utf-8')
        return
    fields = list(rows_[0])
    for r in rows_:
        fields += [k for k in r if k not in fields]
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows_)


def _figure_shares(table, strengths, slacks, path, title='Wind strength {} of slowest airspeed'):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    tpus = sorted({r['tasks_per_uav'] for r in table})
    fig, axes = plt.subplots(len(tpus), len(strengths), figsize=(3.0*len(strengths)+0.6, 2.3*len(tpus)+0.9),
                             sharex=True, sharey=True, squeeze=False)
    fig.patch.set_facecolor(SURFACE)
    groups = _groups(table, ('tasks_per_uav', 'strength', 'slack'))
    for i, tpu in enumerate(tpus):
        for j, strength in enumerate(strengths):
            ax = axes[i][j]
            ax.set_facecolor(SURFACE)
            for x, slack in enumerate(slacks):
                members = groups.get((tpu, strength, slack), [])
                bottom = 0.
                for k in CATEGORIES:
                    share = sum(r['category'] == k for r in members)/len(members) if members else 0.
                    if share:
                        ax.bar(x, share, bottom=bottom, width=.78, color=COLORS[k], edgecolor=SURFACE,
                               linewidth=1.0, hatch='////' if k == 'unresolved' else None)
                    bottom += share
            ax.set_ylim(0, 1)
            ax.set_xticks(range(len(slacks)))
            ax.set_xticklabels(slacks, fontsize=7, color=MUTED, rotation=45)
            ax.tick_params(axis='y', labelsize=7, colors=MUTED)
            ax.grid(axis='y', color=GRID, linewidth=.6)
            ax.set_axisbelow(True)
            for side in ('top', 'right'):
                ax.spines[side].set_visible(False)
            for side in ('left', 'bottom'):
                ax.spines[side].set_color('#c3c2b7')
            if i == 0:
                ax.set_title(title.format(strength), fontsize=8, color=INK)
            if j == 0:
                ax.set_ylabel(f'{tpu} task{"s" if tpu > 1 else ""} per UAV\nshare of missions', fontsize=8, color=INK)
            if i == len(tpus)-1:
                ax.set_xlabel('Deadline slack (fraction of makespan)', fontsize=7, color=MUTED)
    handles = [Patch(facecolor=COLORS[k], edgecolor=SURFACE, hatch='////' if k == 'unresolved' else None,
                     label=LABELS[k]) for k in CATEGORIES]
    ncol = len(CATEGORIES) if len(strengths) >= 3 else 4
    fig.legend(handles=handles, loc='upper center', ncol=ncol, fontsize=7, frameon=False,
               bbox_to_anchor=(.5, 1.0))
    fig.tight_layout(rect=(0, 0, 1, .95 if ncol == len(CATEGORIES) else .91))
    for suffix in ('.png', '.pdf'):
        fig.savefig(path.with_suffix(suffix), dpi=200, facecolor=SURFACE)
    plt.close(fig)


def _figure_budget(curve, field, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(4.6, 3.0))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for color, (tpu, members) in zip(SERIES, sorted(_groups(curve, ('tasks_per_uav',)).items())):
        members = sorted(members, key=lambda r: r['budget_s'])
        xs, ys = [r['budget_s'] for r in members], [r['fraction'] for r in members]
        ax.plot(xs, ys, color=color, linewidth=2, label=f'{tpu[0]} task{"s" if tpu[0] > 1 else ""} per UAV')
    # The curves meet at 1, so end labels would collide; the lower right stays empty.
    ax.legend(loc='lower right', fontsize=7, frameon=False, labelcolor=INK)
    ax.set_xscale('log')
    ax.set_ylim(0, 1)
    ax.set_xlabel(f'Budget ({field.replace("certificate_", "").replace("_s", "")} seconds, log scale)',
                  fontsize=8, color=MUTED)
    ax.set_ylabel('Fraction of variants certified', fontsize=8, color=INK)
    ax.tick_params(labelsize=7, colors=MUTED)
    ax.grid(color=GRID, linewidth=.6)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    for suffix in ('.png', '.pdf'):
        fig.savefig(path.with_suffix(suffix), dpi=200, facecolor=SURFACE)
    plt.close(fig)


def write_report(run):
    run = Path(run)
    out = run/'analysis'
    out.mkdir(exist_ok=True)
    table, ledgers = rows(run)
    config = json.loads((run/'manifest.json').read_text(encoding='utf-8'))['config']
    slacks = [str(Fraction(x)) for x in config['slacks']]
    strengths = sorted({r['strength'] for r in table}, key=Fraction)
    _write_csv(out/'variants.csv', table)
    by_cell = shares(table, ('tasks_per_uav', 'strength', 'slack'))
    pooled = shares(table, ('strength', 'slack'))
    _write_csv(out/'shares_by_tasks.csv', by_cell)
    _write_csv(out/'shares_pooled.csv', pooled)
    band_rows = bands(table, slacks)
    _write_csv(out/'bands.csv', band_rows)
    pairs, falls = stronger_wind_relief(table)
    _write_csv(out/'stronger_wind_relief.csv', falls)
    budgets = [0.25, 0.5, 1, 2, 4, 8, 15, 30, 60, 120, 240]
    wall = certified_by_budget(table, budgets, 'certificate_wall_s')
    cpu = certified_by_budget(table, budgets, 'certificate_cpu_s')
    _write_csv(out/'certified_by_wall_budget.csv', wall)
    _write_csv(out/'certified_by_cpu_budget.csv', cpu)
    if table:
        _figure_shares(table, strengths, slacks, out/'level_shares')
        _figure_budget(wall, 'certificate_wall_s', out/'certified_by_wall_budget')
    attempts = Counter(a['outcome'] for item in ledgers.values() for a in item['ledger']['attempts'])
    summary = dict(run_hash=json.loads((run/'manifest.json').read_text(encoding='utf-8'))['run_hash'],
                   missions_requested=len(ledgers),
                   missions_admitted=sum(item['ledger']['status'] == 'accepted' for item in ledgers.values()),
                   admission_attempts=dict(attempts), variants=len(table),
                   categories=dict(Counter(r['category'] for r in table)),
                   pass2_variants=sum(r['final_phase'] == 'pass2' for r in table),
                   level4_only_band_missions=sum(b['level4_only_band'] for b in band_rows),
                   strength_pairs_compared=pairs, stronger_wind_lower_level=len(falls),
                   total_wall_s=sum(r['wall_s'] for r in table), total_cpu_s=sum(r['cpu_s'] for r in table),
                   inference_note='Shares count variants per group; bootstrap resamples whole missions '
                                  '(2000 draws). Identification bounds place each unresolved variant in '
                                  'every category its certified bounds allow.')
    (out/'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    return summary


def _figure_update_times(table, slacks, path, strength):
    """Level shares by update time (columns) and tasks per UAV (rows)."""
    times = sorted({r['update_fraction'] for r in table}, key=Fraction)
    relabeled = [dict(r, strength=r['update_fraction']) for r in table]
    _figure_shares(relabeled, times, slacks, path,
                   title='Update at t = {} × makespan, wind strength '+strength)


def write_e1_report(p1_run, e1_run, out):
    """Combine P1 at the E1 strength (update at t=0) with the in-flight runs."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    config = json.loads((Path(e1_run)/'manifest.json').read_text(encoding='utf-8'))['config']
    strength = str(Fraction(config['e1_strength']))
    slacks = [str(Fraction(x)) for x in config['slacks']]
    base = [r for r in rows(p1_run)[0] if r['strength'] == strength and r['slack'] in slacks]
    inflight, ledgers = rows(e1_run)
    table = base+inflight
    _write_csv(out/'variants_by_update_time.csv', table)
    _write_csv(out/'shares_by_update_time.csv', shares(table, ('update_fraction', 'tasks_per_uav', 'slack')))
    _write_csv(out/'shares_by_update_time_pooled.csv', shares(table, ('update_fraction', 'slack')))
    if table:
        _figure_update_times(table, slacks, out/'level_shares_by_update_time', strength)
    attempts = Counter(a['outcome'] for item in ledgers.values() for a in item['ledger']['attempts'])
    summary = dict(strength=strength, update_fractions=config['update_fractions'],
                   snapshots_requested=len(ledgers),
                   snapshots_admitted=sum(item['ledger']['status'] == 'accepted' for item in ledgers.values()),
                   snapshot_outcomes=dict(attempts),
                   categories_by_update_time={t: dict(Counter(r['category'] for r in table if r['update_fraction'] == t))
                                              for t in sorted({r['update_fraction'] for r in table}, key=Fraction)},
                   committed_prefix_failures=sum(r['committed_failure'] for r in inflight),
                   empty_affected_set=sum(r['u0_count'] == 0 for r in inflight))
    (out/'summary_by_update_time.json').write_text(json.dumps(summary, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    return summary
