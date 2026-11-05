"""Physically grounded FlyCart 30 case study: build, diagnose and label 36 fixed wind updates.

docs/PHYSICAL_CASE_STUDY_2026_10_21.md. Reads the source FS mission read-only, writes to a
new folder, and resumes: finished labels are kept.

    python scripts/run_physical_case.py --out results/physical_case_2026_10_21 --workers 6
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import hashlib
import json
import multiprocessing
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

from final_study import physical_case as pc     # noqa: E402

FS_RUN = ROOT/'results'/'final_study_2026_10_17'


def _read(path):
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        return json.load(f)


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    with gzip.open(tmp, 'wt', encoding='utf-8') as f:
        json.dump(value, f, sort_keys=True)
    tmp.replace(path)


def _label(out, cid, payload, budget, settings):
    sys.path.insert(0, str(ROOT/'src'))
    from final_study.arena import label
    path = Path(out)/'labels'/f'{cid}.json.gz'
    if not path.exists():
        _write(path, label(cid, payload, budget, settings))
    return cid


def build(out):
    source = _read(FS_RUN/'fs'/'missions'/f'{pc.SOURCE}.json.gz')
    classes = source['ledger']['classes']
    nominal = pc.with_deadlines(pc.nominal_mission(source['variants'][pc.SOURCE_VARIANT]), classes)
    premise = pc.previous_premise(pc.Scenario(nominal))['accepted']
    if not premise:
        raise SystemExit('nominal mission is infeasible under the previous forecast')
    scenarios = {pc.condition_id(*c): pc.apply_update(nominal, *c) for c in pc.conditions()}
    diagnoses = {cid: pc.diagnosis(p) for cid, p in scenarios.items()}
    sources = {f: hashlib.sha256((ROOT/f).read_bytes()).hexdigest()
               for f in ('src/final_study/physical_case.py', 'scripts/run_physical_case.py')}
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    _write(Path(out)/'scenarios.json.gz', dict(nominal=nominal, conditions=scenarios, classes=classes))
    (Path(out)/'diagnosis.json').write_text(json.dumps(dict(
        source=pc.SOURCE_VARIANT, git_commit=commit, source_sha256=sources, energy_fit=pc.energy_fit(),
        nominal_previous_premise=premise, conditions=diagnoses), indent=1))
    return scenarios


def summarize(out, scenarios):
    diagnoses = json.loads((Path(out)/'diagnosis.json').read_text())['conditions']
    rows = []
    for cid in scenarios:
        r = _read(Path(out)/'labels'/f'{cid}.json.gz')
        res, b = r['result'], r['result']['bounds']
        cert = next((e['cpu_s'] for e in res['events'] if e['kind'] in ('proof', 'plan')
                     and b['status'] == 'minimum_certified' and e.get('level') == b['lower']), None)
        rows.append(dict(condition=cid, **diagnoses[cid], status=b['status'], minimum=b['minimum'],
                         lower=b['lower'], upper=b['upper'], excluded=b['excluded_levels'],
                         level_status=res['level_status'], plan_level=res.get('plan_level'),
                         decisions=r['decisions'], cpu_s=res['clock']['cpu_s'], certificate_cpu_s=cert,
                         replay_ok=r['audit']['ok']))
    (Path(out)/'summary.json').write_text(json.dumps(rows, indent=1))
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default=str(ROOT/'results'/'physical_case_2026_10_21'))
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--budget', type=float, default=600)
    args = parser.parse_args()
    settings = json.loads((ROOT/'configs'/'final_study'/'final.json').read_text())['settings']
    scenarios = build(args.out)
    todo = [cid for cid in scenarios if not (Path(args.out)/'labels'/f'{cid}.json.gz').exists()]
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context('spawn')) as pool:
        futures = [pool.submit(_label, args.out, cid, scenarios[cid], args.budget, settings) for cid in todo]
        for i, f in enumerate(as_completed(futures), 1):
            print(f'{i}/{len(todo)} {f.result()}', flush=True)
    rows = summarize(args.out, scenarios)
    print(f'{len(rows)} conditions summarized')


if __name__ == '__main__':
    main()
