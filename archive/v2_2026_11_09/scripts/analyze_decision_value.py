"""A2 of docs/EXPERIMENT_REDESIGN_RAL_2026_10_30.md: what the certificate changes for the operator.

Read-only re-analysis of a final-study run. Scoring is the report's own (``analysis.load``,
``pooled`` and ``_attach``: returned plan, events at cpu_s <= budget, pooled reference).

1. Outcome classes per arm: certified answer, plan without certificate, nothing; and, for
   "nothing", what the reference says the instance really was.
2. Escalation justification: positive-level plans proven necessary by the arm's own evidence,
   at the reference minimum without proof, or above it.
3. PH time at levels the reference proves infeasible, and how PH left them.

Usage: PYTHONPATH=src python scripts/analyze_decision_value.py --run results/final_study_2026_10_17
       --out results/a2_decision_value_2026_10_30
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from final_study.analysis import _attach, load, pooled, quantile
from final_study.store import Store

SETS = (('fs', 10.0), ('fs', 60.0), ('ls', 10.0), ('ls', 60.0))
ARMS = ('CMI', 'PH', 'LR', 'GR-c', 'GR', 'noAF', 'noER')


def truth(r):
    if r['ref_min'] == 5:
        return 'unrecoverable'
    if r['ref_upper'] is not None:
        return 'recoverable'
    return 'unresolved'


def outcomes(rows):
    out = Counter()
    for r in rows:
        if r['certified']:
            out['certified_none' if r['minimum'] == 5 else 'certified_level0' if r['minimum'] == 0
                else 'certified_positive'] += 1
        elif r['plan_level'] is not None:
            out['plan_uncertified'] += 1
        else:
            out['nothing_'+truth(r)] += 1
    return dict(out, n=len(rows))


def escalations(rows):
    out = Counter()
    for r in rows:
        if r['plan_level'] is None or r['plan_level'] == 0:
            continue
        out['n'] += 1
        if r['lower'] >= r['plan_level']:
            out['proven_by_own_evidence'] += 1
        elif r['ref_min'] is None or r['ref_min'] == 5:
            out['reference_unknown'] += 1
        elif r['plan_level'] == r['ref_min']:
            out['at_minimum_unproven'] += 1
        else:
            out['above_minimum'] += 1
    return dict(out)


def ph_levels(r):
    """[(level, start, end, exit)] from PH's events; exit 'proof' when the reason is a record id."""
    start, out, end_cpu = r['categories'].get('setup', 0.), [], min(r['cpu'], r['budget'])
    level = 0
    for e in r['events']:
        if e['kind'] == 'escalate':
            reason = e['reason']
            kind = 'proof' if isinstance(reason, int) else 'share' if reason == 'share spent' else 'no_plan'
            out.append((e['level'], start, e['cpu_s'], kind))
            start, level = e['cpu_s'], e['level']+1
        elif e['kind'] == 'plan':
            out.append((level, start, e['cpu_s'], 'plan'))
            return out
    if level <= 4 and start < end_cpu:
        out.append((level, start, end_cpu, 'budget'))
    return out


def cmi_exclusion_cpu(r, below):
    """CPU at which CMI proved every level < ``below`` infeasible, or None."""
    times = [e['cpu_s'] for e in r['events'] if e['kind'] == 'proof' and e['level'] >= below-1]
    return min(times) if times else None


def impossible_levels(ph_rows, cmi_rows):
    cmi = {r['instance']: r for r in cmi_rows}
    exits, by_lower = Counter(), {}
    wasted_no_plan = []
    for r in ph_rows:
        low = r['ref_lower'] or 0
        if low == 0:
            continue
        spans = ph_levels(r)
        at_impossible = sum(e-s for k, s, e, _ in spans if k < low)
        for k, s, e, kind in spans:
            if k < low:
                exits[k, kind] += 1
        reached = next((s for k, s, e, _ in spans if k == min(low, 4)), None) if low <= 4 else None
        c = cmi.get(r['instance'])
        d = by_lower.setdefault(min(low, 5), dict(n=0, ph_cpu_at_impossible=[], ph_reached=[], cmi_excluded=[]))
        d['n'] += 1
        d['ph_cpu_at_impossible'].append(at_impossible)
        if reached is not None:
            d['ph_reached'].append(reached)
        if c is not None:
            t = cmi_exclusion_cpu(c, min(low, 5))
            if t is not None:
                d['cmi_excluded'].append(t)
        if r['plan_level'] is None:
            wasted_no_plan.append(at_impossible/r['budget'])
    summary = {}
    for low, d in sorted(by_lower.items()):
        summary[low] = dict(n=d['n'],
                            ph_cpu_at_impossible_median=quantile(d['ph_cpu_at_impossible'], .5),
                            ph_cpu_at_impossible_p90=quantile(d['ph_cpu_at_impossible'], .9),
                            ph_cpu_at_impossible_total=sum(d['ph_cpu_at_impossible']),
                            ph_reached_count=len(d['ph_reached']),
                            ph_reached_median=quantile(d['ph_reached'], .5),
                            cmi_excluded_count=len(d['cmi_excluded']),
                            cmi_excluded_median=quantile(d['cmi_excluded'], .5))
    return dict(by_reference_lower=summary,
                exits={f'level{k}_{kind}': v for (k, kind), v in sorted(exits.items())},
                no_plan_runs=len(wasted_no_plan),
                no_plan_budget_share_at_impossible_median=quantile(wasted_no_plan, .5))


def pct(a, n):
    return '-' if not n else f'{100*a/n:.1f}%'


def fmt(v):
    return '-' if v is None else f'{v:.2f}'


def report(results):
    lines = ['# A2: what the certificate changes (re-analysis of stored records)', '',
             'Scoring as in the final-study report: the returned plan if it replays and was returned by the '
             'budget; proofs logged by the budget; reference = 600 s CMI label pooled with every replayed plan. '
             'No solver was run.', '']
    for key, res in results.items():
        o = res['outcomes']
        lines += [f'## {key}', '', '### 1. What each arm tells the operator', '',
                  '| arm | n | certified: positive level | certified: no continuation | certified: Level 0 | '
                  'plan, not certified | nothing, really recoverable | nothing, really unrecoverable | '
                  'nothing, reference unresolved | share of "nothing" that is unrecoverable |',
                  '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
        for arm in ARMS:
            if arm not in o:
                continue
            c = o[arm]
            nothing = sum(v for k, v in c.items() if k.startswith('nothing_'))
            lines.append(f"| {arm} | {c['n']} | {c.get('certified_positive', 0)} | {c.get('certified_none', 0)} | "
                         f"{c.get('certified_level0', 0)} | {c.get('plan_uncertified', 0)} | "
                         f"{c.get('nothing_recoverable', 0)} | {c.get('nothing_unrecoverable', 0)} | "
                         f"{c.get('nothing_unresolved', 0)} | {pct(c.get('nothing_unrecoverable', 0), nothing)} |")
        lines += ['', '### 2. Escalations (returned plans above Level 0)', '',
                  '| arm | plans | proven necessary by own evidence | at reference minimum, unproven | '
                  'above reference minimum | reference minimum unknown |', '|---|---:|---:|---:|---:|---:|']
        for arm in ARMS:
            e = res['escalations'].get(arm)
            if e is None:
                continue
            n = e.get('n', 0)
            lines.append(f"| {arm} | {n} | {pct(e.get('proven_by_own_evidence', 0), n)} | "
                         f"{pct(e.get('at_minimum_unproven', 0), n)} | {pct(e.get('above_minimum', 0), n)} | "
                         f"{pct(e.get('reference_unknown', 0), n)} |")
        imp = res['impossible']
        lines += ['', '### 3. PH at levels the reference proves infeasible', '',
                  'Grouped by the reference lower bound (5 = no continuation). "PH reached" is the CPU at which PH '
                  'started the first level not proven infeasible; "CMI excluded" is the CPU of the CMI proof that '
                  'closed every such level. Each is over the runs where it happened within the budget.', '',
                  '| reference lower bound | n | PH CPU at infeasible levels, median / p90 (s) | PH reached (n, median s) | '
                  'CMI excluded (n, median s) |', '|---:|---:|---:|---:|---:|']
        for low, d in imp['by_reference_lower'].items():
            lines.append(f"| {low} | {d['n']} | {fmt(d['ph_cpu_at_impossible_median'])} / "
                         f"{fmt(d['ph_cpu_at_impossible_p90'])} | {d['ph_reached_count']}, {fmt(d['ph_reached_median'])} | "
                         f"{d['cmi_excluded_count']}, {fmt(d['cmi_excluded_median'])} |")
        lines += ['', 'How PH left infeasible levels (proof = a Level-0/1 lower-bound exclusion the shared '
                  'search computes even with proofs off; share = its time share ran out; no_plan = the plan '
                  'search ended; budget = still there at the cutoff):', '',
                  ', '.join(f'{k}: {v}' for k, v in imp['exits'].items()) or '-', '',
                  f"PH runs with no plan: {imp['no_plan_runs']}; median share of the budget spent at infeasible "
                  f"levels: {fmt(imp['no_plan_budget_share_at_impossible_median'])}.", '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    store = Store(args.run, {}, bind=False)
    instances, arenas, _ = load(store)
    ref = pooled(instances, arenas)
    results = {}
    for group, budget in SETS:
        rows = _attach(arenas.get((group, budget), []), instances, ref)
        by_arm = {arm: [r for r in rows if r['arm'] == arm] for arm in ARMS}
        by_arm = {a: v for a, v in by_arm.items() if v}
        results[f'{group.upper()} at {budget:g} s'] = dict(
            outcomes={a: outcomes(v) for a, v in by_arm.items()},
            escalations={a: escalations(v) for a, v in by_arm.items()},
            impossible=impossible_levels(by_arm['PH'], by_arm['CMI']))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out/'summary.json').write_text(json.dumps(dict(run=args.run, run_hash=store.run_hash, results=results),
                                               indent=1, default=str), encoding='utf-8')
    (out/'REPORT.md').write_text(report(results), encoding='utf-8')


if __name__ == '__main__':
    main()
