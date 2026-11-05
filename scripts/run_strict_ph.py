"""Rerun PH as the protocol defines it (PH-strict) next to PH as run and CMI.

PH as run left Levels 0-1 on CMI's lower-bound exclusions (docs/EXPERIMENT_REDESIGN_RAL_2026_10_30.md,
Section 10). PH-strict leaves every level only when its time share ends or its plan search is
exhausted. The frozen FS instances are read from the final-study run without changing it; every
arm runs through ``final_study.arena.run_instance`` (random arm order, CPU budget, replay).

    python scripts/run_strict_ph.py --stage smoke --out results/strict_ph_smoke --workers 6
    python scripts/run_strict_ph.py --stage short --out results/strict_ph_2026_10_30 --workers 6
    python scripts/run_strict_ph.py --stage long --out results/strict_ph_2026_10_30 --workers 6
    python scripts/run_strict_ph.py --stage report --out results/strict_ph_2026_10_30

Schedule test (Section 12): add ``--config configs/final_study/strict_ph_schedules.json`` and a new ``--out``.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import random
import statistics
import sys
import time

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
os.chdir(ROOT)

from final_study.analysis import (_attach, _certificate_vs_first_plan, _paired_all, _paired_rates,  # noqa: E402
                                  load, pooled, quantile)
from final_study.stages import _pool, fs_instances, fs_long_missions  # noqa: E402
from final_study.store import Store                                  # noqa: E402

CONFIG = ROOT/'configs'/'final_study'/'strict_ph.json'


def stage_arms(config, stage):
    return config.get('arms_long' if stage == 'long' else 'arms_short', config['arms'])


def units(source, source_config, config, stage):
    """``subset: third`` restricts the 10 s stage to the 60 s third as well."""
    instances = fs_instances(source)
    if stage == 'smoke':
        rng = random.Random(config['smoke']['seed'])
        instances = rng.sample(instances, config['smoke']['instances'])
    elif stage == 'long' or config.get('subset') == 'third':
        third = fs_long_missions(source, source_config)
        instances = [i for i in instances if i[2]['mission'] in third]
    budget = config['budget_long'] if stage == 'long' else config['budget_short']
    tag = f'arena_{budget}s'
    return [('fs', tag, vid, payload, budget, stage_arms(config, stage)) for vid, payload, _ in instances]


def pp(p):
    if p['lo'] is None:
        return f"{100*(p['difference'] or 0):+.1f}"
    return f"{100*p['difference']:+.1f} [{100*p['lo']:+.1f}, {100*p['hi']:+.1f}]"


def exits(row):
    out = Counter()
    for e in row['events']:
        if e['kind'] == 'escalate':
            reason = e['reason']
            out[f"L{e['level']}:" + ('proof' if isinstance(reason, int) else 'share' if reason == 'share spent'
                                      else 'no_plan')] += 1
    return out


def skipped(row):
    """Escalations from a level PH spent under 0.02 s at."""
    start, count = row['categories'].get('setup', 0.), 0
    for e in row['events']:
        if e['kind'] in ('escalate', 'plan'):
            count += e['kind'] == 'escalate' and e['cpu_s']-start < .02
            start = e['cpu_s']
    return count


def report(source, out):
    instances, source_arenas, _ = load(source)
    _, arenas, _ = load(Store(out, None, bind=False))
    merged = {k: v+arenas.get(k, []) for k, v in source_arenas.items()}
    ref = pooled(instances, merged)
    lines = ['# Strict PH rerun', '', f'Run `{out}`; reference = frozen labels pooled with every replayed plan '
             '(frozen and new). Scoring as in the final-study report (returned plan, events at cpu_s <= budget).', '']
    for (group, budget), raw in sorted(arenas.items()):
        rows = _attach(raw, instances, ref)
        lines += [f'## {group.upper()} at {budget:g} s', '',
                  '| arm | n | replays | plan at minimum | recovery | certified | first plan CPU, median / p90 (s) | '
                  'plan below reference lower bound |', '|---|---:|---:|---:|---:|---:|---:|---:|']
        by_arm = {}
        for r in rows:
            by_arm.setdefault(r['arm'], []).append(r)
        for arm, rs in sorted(by_arm.items()):
            n = len(rs)
            plans = [r for r in rs if r['plan_level'] is not None]
            below = sum(1 for r in plans if r['ref_lower'] is not None and r['plan_level'] < r['ref_lower'])
            lines.append(f"| {arm} | {n} | {sum(r['audit_ok'] for r in rs)} | {sum(r['at_min'] for r in rs)} | "
                         f"{len(plans)} | {sum(r['certified'] for r in rs)} | "
                         f"{quantile([r['first_plan_cpu'] for r in plans], .5) or 0:.2f} / "
                         f"{quantile([r['first_plan_cpu'] for r in plans], .9) or 0:.2f} | {below} |")
        ph_arms = [a for a in sorted(by_arm) if a.startswith('PH')]
        for arm in ph_arms:
            total = Counter()
            for r in by_arm[arm]:
                total.update(exits(r))
            lines += ['', f'{arm} level exits: ' + (', '.join(f'{k} {v}' for k, v in sorted(total.items())) or '-'),
                      f'{arm} levels left with under 0.02 s spent there (share already used by an earlier overrun): '
                      f'{sum(skipped(r) for r in by_arm[arm])}']
        for r in rows:
            r['has_plan'] = r['plan_level'] is not None
        strict = [a for a in ph_arms if a.startswith('PH-strict')]
        best = max(strict, key=lambda a: sum(r['at_min'] for r in by_arm[a])) if strict else None
        pairs = [('CMI', a) for a in ph_arms]+([('PH', 'PH-strict')] if {'PH', 'PH-strict'} <= set(by_arm) else [])
        lines += ['', 'Paired rates on the same instances (left minus right, 95% interval over missions):', '',
                  '| left | right | metric | n | left | right | difference (pp) |', '|---|---|---|---:|---:|---:|---:|']
        for left, right in pairs:
            for key, label in (('at_min', 'plan at minimum'), ('has_plan', 'recovery')):
                p = _paired_rates(by_arm.get(left, []), by_arm.get(right, []), key)
                lines.append(f"| {left} | {right} | {label} | {p['n']} | {p['left_count']} | {p['right_count']} | "
                             f"{pp(p)} |")
        if best:
            lines += ['', f'Best PH-strict schedule by plan at minimum (chosen in hindsight on these instances): {best}.']
        lines += ['', 'CMI CPU to certificate over the arm\'s CPU to its first plan (H3 statistic, ratio of medians '
                  'on instances where CMI certified and the arm found a plan):', '']
        for arm in ph_arms:
            h = _certificate_vs_first_plan(by_arm.get('CMI', []), by_arm[arm])
            lines.append(f"- {arm}: {h['cert_median'] or 0:.2f} s / {h['first_median'] or 0:.2f} s = {h['point'] or 0:.2f}x "
                         f"[{h['lo'] or 0:.2f}, {h['hi'] or 0:.2f}], n = {h['n']}; CMI uncertified {h['cmi_uncertified']}, "
                         f"{arm} no plan {h['ph_no_plan']}")
        reference = 'PH' if 'PH' in by_arm else 'PH-strict'
        for arm in strict:
            if arm == reference:
                continue
            first = _paired_all(by_arm, arm, lambda a, b: b['first_plan_cpu']-a['first_plan_cpu'],
                                statistic=statistics.median, reference=reference,
                                keep=lambda a, b: a['first_plan_cpu'] is not None and b['first_plan_cpu'] is not None)
            lines.append(f"- {arm} minus {reference}, first-plan CPU, median paired difference: {first[0] or 0:+.2f} s "
                         f"[{first[1] or 0:+.2f}, {first[2] or 0:+.2f}], n = {first[3]}")
        lines += ['', 'Plan at the minimum by reference minimum (Levels 0-4):', '',
                  '| reference minimum | n | ' + ' | '.join(sorted(by_arm)) + ' |',
                  '|---:|---:|' + '---:|'*len(by_arm)]
        for level in (0, 1, 2, 3, 4):
            names = {r['instance'] for r in rows if r['ref_min'] == level}
            counts = [sum(r['at_min'] for r in by_arm[a] if r['instance'] in names) for a in sorted(by_arm)]
            lines.append(f"| {level} | {len(names)} | " + ' | '.join(map(str, counts)) + ' |')
        frozen = {(r['instance'], r['arm']): r for r in source_arenas.get((group, budget), [])}
        for arm in ('PH', 'CMI'):
            matched = [(r, frozen[(r['instance'], arm)]) for r in raw if r['arm'] == arm and (r['instance'], arm) in frozen]
            same = sum((a['lower'], a['upper']) == (b['lower'], b['upper']) for a, b in matched)
            if matched:
                lines.append(f'\nReproducibility: rerun {arm} has the frozen bracket (lower, upper) on {same} of '
                             f'{len(matched)}.')
        lines.append('')
    Path(out, 'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=('smoke', 'short', 'long', 'report'), required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--config', default=str(CONFIG))
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    source = Store(config['source_run'], None, bind=False)
    if args.stage == 'report':
        report(source, args.out)
        return
    store = Store(args.out, config, workers=args.workers)
    log_path = Path(args.out)/'run.log'

    def log(message):
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
        print(line, flush=True)
        with log_path.open('a', encoding='utf-8') as stream:
            stream.write(line+'\n')
    todo = [u for u in units(source, source.manifest['config'], config, args.stage)
            if not store.exists(u[0], u[1], u[2])]
    log(f'{args.stage}: {len(todo)} units, arms {stage_arms(config, args.stage)}, {args.workers} workers')
    _pool('arena', store.path, config, todo, args.workers, log, args.stage)
    report(source, args.out)


if __name__ == '__main__':
    main()
