"""A1 and A3 of docs/EXPERIMENT_REDESIGN_RAL_2026_10_30.md: Q1 by stratum and the Q3 cost profile.

Read-only re-analysis. Scoring is the final-study report's own (``analysis.load``, ``pooled``
and ``_attach``: returned plan, events at cpu_s <= budget, pooled reference). PH-strict (Section
11) comes from the strict-PH rerun on FS; its reference pools the frozen and rerun plans.

A1: per arm, paired with CMI on instances where both returned a plan, the mean difference
    (arm minus CMI) in UAVs changed, UAVs outside U0, tasks reassigned and sequence edits,
    split by the reference minimum; and plans above the reference minimum.
A3: CMI by its certified level: CPU to certificate; the H3 ratio (median CMI certificate CPU
    over median PH first-plan CPU) inside the level against PH-strict and PH; replay CPU
    against production CPU; certificate size; CPU split by component; uncertified runs.

Usage: PYTHONPATH=src python -P scripts/analyze_strata.py --run results/final_study_2026_10_17
       --strict results/strict_ph_2026_10_30 --out results/a1_a3_strata_2026_11_01
With ``--method results/cmi_mu_2026_11_01`` CMI-mu is the method and frozen CMI one of the arms.
"""
import argparse
from collections import Counter, defaultdict
import statistics
from pathlib import Path

from final_study.analysis import _attach, _certificate_vs_first_plan, _paired_all, load, pooled, quantile
from final_study.store import Store

SETS = (('fs', 10.0), ('fs', 60.0), ('ls', 10.0), ('ls', 60.0))
ARMS = ('PH-strict', 'PH', 'LR', 'GR-c', 'GR', 'noAF', 'noER')
METRICS = (('uavs_changed', 'UAVs'), ('uavs_changed_outside_u0', 'outside U0'), ('tasks_reassigned', 'tasks reassigned'),
           ('sequence_edits', 'sequence edits'))
NAMES = {0: '0', 1: '1', 2: '2', 3: '3', 4: '4', 5: 'none'}
CATEGORIES = ('setup', 'bounds', 'paths', 'route', 'search', 'exact', 'other')


def fmt(p):
    point, lo, hi, n = p
    if point is None:
        return '-'
    return f'{point:+.2f}' if lo is None else f'{point:+.2f} [{lo:+.2f}, {hi:+.2f}]'


def a1(by_arm, lines, method='CMI'):
    lines += ['| arm | reference minimum | paired plans | ' + ' | '.join(f'{label}, arm - {method}' for _, label in METRICS)
              + ' | arm plans above minimum (mean gap) |', '|---|---:|---:|' + '---:|'*(len(METRICS)+1)]
    for arm in (('CMI',) if method != 'CMI' else ())+ARMS:
        if arm not in by_arm:
            continue
        for level in (0, 1, 2, 3, 4):
            stratum = {a: [r for r in rs if r['ref_min'] == level] for a, rs in by_arm.items()}
            cells, n = [], 0
            for key, _ in METRICS:
                p = _paired_all(stratum, arm, lambda a, b, k=key: b[f'd_{k}']-a[f'd_{k}'], reference=method,
                                keep=lambda a, b, k=key: f'd_{k}' in a and f'd_{k}' in b)
                cells.append(fmt(p))
                n = max(n, p[3])
            above = [r['plan_level']-level for r in stratum[arm] if r['plan_level'] is not None and r['plan_level'] > level]
            lines.append(f"| {arm} | {level} | {n} | " + ' | '.join(cells) +
                         f" | {len(above)} ({statistics.mean(above) if above else 0:.2f}) |")
    lines.append('')


def a3(by_arm, sizes, lines, method='CMI'):
    cmi = by_arm[method]
    lines += [f'| {method} certified level | n | certificate CPU median / p90 (s) | H3 vs PH-strict | H3 vs PH | '
              'replay / production CPU, median | certificates / route proofs / level records, median |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for level in (0, 1, 2, 3, 4, 5):
        rows = [r for r in cmi if r['certified'] and r['minimum'] == level]
        if not rows:
            continue
        cpu = [r['certificate_cpu'] for r in rows]
        ratios = []
        for arm in ('PH-strict', 'PH'):
            if arm not in by_arm or level == 5:
                ratios.append('-')
                continue
            h = _certificate_vs_first_plan(rows, by_arm[arm])
            ratios.append('-' if h['point'] is None else
                          f"{h['point']:.2f}x [{h['lo'] or 0:.2f}, {h['hi'] or 0:.2f}], n = {h['n']}")
        replay = [r['audit_cpu']/r['cpu'] for r in rows if r['cpu']]
        size = [sizes[r['instance']] for r in rows if sizes.get(r['instance'])]
        med = lambda k: quantile([s[k] for s in size], .5) or 0
        lines.append(f"| {NAMES[level]} | {len(rows)} | {quantile(cpu, .5):.2f} / {quantile(cpu, .9):.2f} | "
                     f"{ratios[0]} | {ratios[1]} | {quantile(replay, .5) or 0:.2f} | "
                     f"{med('certificates'):.0f} / {med('proofs'):.0f} / {med('level_records'):.0f} |")
    unc = Counter(NAMES.get(r['ref_min'], 'unresolved') if r['ref_min'] is not None else 'unresolved'
                  for r in cmi if not r['certified'])
    lines += ['', f'{method} uncertified runs by reference minimum (excluded from the rows above): '
              + ', '.join(f'{k} {v}' for k, v in sorted(unc.items())), '',
              f'{method} CPU split by certified level (share of the summed CPU; uncertified runs as one row):', '',
              f'| {method} certified level | ' + ' | '.join(CATEGORIES) + ' |', '|---|' + '---:|'*len(CATEGORIES)]
    groups = defaultdict(list)
    for r in cmi:
        groups[NAMES[r['minimum']] if r['certified'] else 'uncertified'].append(r)
    for name in ('0', '1', '2', '3', '4', 'none', 'uncertified'):
        if name not in groups:
            continue
        total = {c: sum(r['categories'].get(c, 0.) for r in groups[name]) for c in CATEGORIES}
        s = sum(total.values()) or 1
        lines.append(f'| {name} | ' + ' | '.join(f'{100*total[c]/s:.0f}%' for c in CATEGORIES) + ' |')
    lines.append('')


def evidence_sizes(store, group, budget, arm):
    out = {}
    root = store.path/group/f'arena_{budget:g}s'
    for path in sorted(root.glob('*.json.gz')):
        record = store.load(group, root.name, path.name[:-len('.json.gz')])
        out[record['instance']] = record['arms'][arm]['result'].get('evidence_size')
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    parser.add_argument('--strict', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--method', help='run of the CMI-mu arm; it becomes the method, frozen CMI an arm')
    args = parser.parse_args()
    store = Store(args.run, None, bind=False)
    instances, arenas, _ = load(store)
    _, strict, _ = load(Store(args.strict, None, bind=False))
    strict = {k: [r for r in v if r['arm'] == 'PH-strict'] for k, v in strict.items()}
    method, extra, sizes_store = 'CMI', {}, store
    if args.method:
        sizes_store = Store(args.method, None, bind=False)
        _, extra, _ = load(sizes_store)
        method, extra = 'CMI-mu', {k: [r for r in v if r['arm'] == 'CMI-mu'] for k, v in extra.items()}
    ref = pooled(instances, {k: v+strict.get(k, [])+extra.get(k, []) for k, v in arenas.items()})
    lines = ['# A1 and A3: Q1 by stratum and the Q3 cost profile', '',
             f'Run `{args.run}`; PH-strict from `{args.strict}` (FS only); method {method}'
             + (f' from `{args.method}`' if args.method else '') + '. Reference = frozen labels pooled with every '
             'replayed plan, PH-strict included. Scoring as in the final-study report. Differences are arm minus the method on '
             'instances where both returned a plan (95% interval over missions).', '']
    for group, budget in SETS:
        by_arm = defaultdict(list)
        for r in _attach(arenas.get((group, budget), [])+strict.get((group, budget), [])+extra.get((group, budget), []),
                         instances, ref):
            by_arm[r['arm']].append(r)
        lines += [f'## {group.upper()} at {budget:g} s', '', '### A1: decisions changed, by reference minimum', '']
        a1(by_arm, lines, method)
        lines += [f'### A3: {method} cost by certified level', '']
        a3(by_arm, evidence_sizes(sizes_store, group, budget, method), lines, method)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out/'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
