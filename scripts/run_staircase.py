"""B5: escalation staircase, the certified minimum level k^F against wind strength (design doc, Section 19).

Missions: the 53 FS missions of the 60 s arena third (``final_study.stages.fs_long_missions``).
Each keeps its stored reference variant (t = 0), update cell and direction; only the strength
changes, alpha = j/20 of the slowest airspeed for j = 1..16 (wind components must be terminating
decimals). j = 8, 12, 16 are the FS strengths 2/5, 3/5, 4/5: those payloads must equal the stored
FS variants and keep their ids. U0 depends on the cell, not the strength, and is checked equal at
every strength. Labels: CMI at the label budget through ``final_study.arena.label``, replayed.

    python scripts/run_staircase.py --stage smoke --out results/staircase_smoke --workers 6
    python scripts/run_staircase.py --stage run --out results/staircase_2026_11_01 --workers 6
    python scripts/run_staircase.py --stage report --out results/staircase_2026_11_01
"""
import argparse
from collections import Counter
from copy import deepcopy
from fractions import Fraction
import json
import os
from pathlib import Path
import sys
import time

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
os.chdir(ROOT)

from env.local_scope import affected_uavs                              # noqa: E402
from env.scenario import Scenario                                      # noqa: E402
from env.wind_dependency import diagnose_wind_update                   # noqa: E402
from escalation_study.missions import _decimal_vector                  # noqa: E402
from final_study.analysis import _bracket                              # noqa: E402
from final_study.stages import _pool, fs_long_missions                 # noqa: E402
from final_study.store import Store                                    # noqa: E402

CONFIG = ROOT/'configs'/'final_study'/'staircase.json'
STEPS = range(1, 17)
FS_STEP = {8: 'r0', 12: 'r1', 16: 'r2'}     # j/20 = 2/5, 3/5, 4/5


def build(source, mission):
    """Mission record: per strength the instance id, U0, FS hash match, and the payload."""
    item = source.load('fs', 'missions', mission)
    ledger = item['ledger']
    v = item['variants'][mission+'_r1_t0']
    v_min = min(Fraction(str(u['airspeed_kmh'])) for u in v['mission']['vehicles'])
    direction = [Fraction(c) for c in ledger['direction']]
    out = dict(version='staircase-mission-v1', mission=mission, cell=ledger['cell'], direction=ledger['direction'],
               instances={}, payloads={})
    for j in STEPS:
        q = deepcopy(v)
        q['wind']['received']['values'][ledger['cell_index']][0] = _decimal_vector(
            tuple(Fraction(j, 20)*v_min*d for d in direction))
        vid = f'{mission}_{FS_STEP[j]}_t0' if j in FS_STEP else f'{mission}_s{j:02d}'
        q['benchmark_id'] = vid
        s = Scenario(q)
        info = dict(step=j, strength=f'{j}/20', u0=affected_uavs(s, diagnose_wind_update(s))['uavs'])
        if j in FS_STEP:
            info['fs_hash_match'] = s.content_hash() == ledger['variants'][vid]['scenario_hash']
        out['instances'][vid] = info
        out['payloads'][vid] = s.to_dict()
    return out


def code(level):
    return '∞' if level == 5 else str(level)


def report(out, config):
    store = Store(out, None, bind=False)
    source = Store(config['source_run'], None, bind=False)
    records = [store.load('st', 'missions', p.name[:-len('.json.gz')]) for p in store.all('st', 'missions')]
    labels = {}
    for p in store.all('st', 'labels'):
        r = store.load('st', 'labels', p.name[:-len('.json.gz')])
        labels[r['instance']] = r
    fs_match = [i['fs_hash_match'] for r in records for i in r['instances'].values() if 'fs_hash_match' in i]
    same_bounds = []
    for r in records:
        for vid, i in r['instances'].items():
            if 'fs_hash_match' in i and vid in labels:
                stored = source.load('fs', 'labels', vid)
                same_bounds.append(stored is not None and stored['result']['bounds'] == labels[vid]['result']['bounds'])
    u0_constant = sum(len({tuple(i['u0']) for i in r['instances'].values()}) == 1 for r in records)
    lines = ['# B5: escalation staircase', '', f'Run `{out}`, labels CMI at {config["label_budget_s"]} s. Strength alpha = j/20 '
             'of the slowest airspeed; j = 8, 12, 16 are the FS strengths 2/5, 3/5, 4/5. Level 5 (∞) = no continuation.', '',
             '## Integrity', '', f'- Missions: {len(records)}; labels: {len(labels)}; replays: '
             f'{sum(r["audit"]["ok"] for r in labels.values())}/{len(labels)}.',
             f'- Payloads at the FS strengths equal the stored FS variants: {sum(fs_match)}/{len(fs_match)}.',
             f'- Labels at the FS strengths give the stored FS label bounds: {sum(same_bounds)}/{len(same_bounds)}.',
             f'- U0 is the same at every strength: {u0_constant}/{len(records)} missions.', '',
             '## Certified minimum by strength', '', '| j | alpha | n | certified | 0 / 1 / 2 / 3 / 4 / ∞ |',
             '|---:|---:|---:|---:|---|']
    rows = {}
    for r in records:
        for vid, i in r['instances'].items():
            if vid in labels:
                rows[r['mission'], i['step']] = _bracket(labels[vid]['result']['bounds'])
    for j in STEPS:
        brackets = [b for (m, s), b in rows.items() if s == j]
        cert = Counter(lo for lo, hi in brackets if lo == hi)
        lines.append(f'| {j} | {j/20:.2f} | {len(brackets)} | {sum(cert.values())} | '
                     + ' / '.join(str(cert.get(k, 0)) for k in range(6)) + ' |')
    lines += ['', '## Staircases', '', 'Per mission, k^F at j = 1..16 (lo-hi = uncertified bracket, hi ? = no plan known).',
              '', '| mission | U0 | direction | staircase | shape |', '|---|---:|---|---|---|']
    shapes, violations = Counter(), []
    for r in sorted(records, key=lambda r: r['mission']):
        b = [rows.get((r['mission'], j)) for j in STEPS]
        if any(x is None for x in b):
            continue
        cells = [code(lo) if lo == hi else f"{code(lo)}-{'?' if hi is None else code(hi)}" for lo, hi in b]
        certified = all(lo == hi for lo, hi in b)
        found = [(i+1, j+1, b[i][0], b[j][1]) for i in range(16) for j in range(i+1, 16)
                 if b[j][1] is not None and b[i][0] > b[j][1]]
        violations += [(r['mission'], *f) for f in found]
        if found:
            shape = 'certified non-monotone'
        elif certified:
            shape = 'monotone' + (', constant' if len({lo for lo, _ in b}) == 1 else '')
        else:
            shape = 'no certified violation, uncertified points'
        shapes[shape] += 1
        lines.append(f"| {r['mission']} | {len(next(iter(r['instances'].values()))['u0'])} | {r['direction']} | "
                     f"{' '.join(cells)} | {shape} |")
    lines += ['', 'Shapes: ' + ', '.join(f'{k} {n}' for k, n in shapes.most_common()), '',
              f'Certified violations (weaker wind needs a strictly higher level; lower bound at j_1 > upper at j_2): '
              f'{len(violations)} pairs on {len({v[0] for v in violations})} missions.']
    for m, i, j, lo, hi in violations[:40]:
        lines.append(f'- {m}: j = {i} needs >= {code(lo)}, j = {j} has a level-{code(hi)} plan')
    thresholds = Counter()
    for r in records:
        b = [rows.get((r['mission'], j)) for j in STEPS]
        if any(x is None or x[0] != x[1] for x in b):
            continue
        for k in range(5):
            above = [j for j, (lo, _) in zip(STEPS, b) if lo > k]
            if above and all(lo > k for lo, _ in b[above[0]-1:]):
                thresholds[k, above[0]] += 1
    lines += ['', 'Thresholds alpha*_k on monotone or eventually-above missions: first j at which k^F > k and stays above '
              '(alpha*_k lies in ((j-1)/20, j/20]):', '']
    for k in range(5):
        hits = sorted((j, n) for (kk, j), n in thresholds.items() if kk == k)
        if hits:
            lines.append(f'- k = {k}: ' + ', '.join(f'j={j} x{n}' for j, n in hits))
    Path(out, 'REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
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
        report(args.out, json.loads(Path(args.out, 'manifest.json').read_text(encoding='utf-8'))['config'])
        return
    source = Store(config['source_run'], None, bind=False)
    store = Store(args.out, config, workers=args.workers)
    log_path = Path(args.out)/'run.log'

    def log(message):
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
        print(line, flush=True)
        with log_path.open('a', encoding='utf-8') as stream:
            stream.write(line+'\n')
    names = sorted(fs_long_missions(source, source.manifest['config']))[:config.get('missions')]
    units = []
    for name in names:
        record = store.load('st', 'missions', name)
        if record is None:
            record = store.save(build(source, name), 'st', 'missions', name)
            log(f'build: {name}')
        units += [('st', vid, payload) for vid, payload in sorted(record['payloads'].items())
                  if not store.exists('st', 'labels', vid)]
    log(f'{args.stage}: {len(names)} missions, {len(units)} labels')
    _pool('label', store.path, config, units, args.workers, log, args.stage)
    report(args.out, config)


if __name__ == '__main__':
    main()
