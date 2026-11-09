"""Physically grounded case study 2: build, smoke control, labels and summary.

docs/PHYSICAL_CASE_STUDY_2_DESIGN_2026_10_21.md. Phases run in order; each can be repeated.
`label` refuses to run if the stored scenarios differ from the build record or from what the
current code builds.

    python scripts/run_physical_case2.py build
    python scripts/run_physical_case2.py smoke
    python scripts/run_physical_case2.py label --workers 6
    python scripts/run_physical_case2.py summary
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

from continuous.validation import previous_premise      # noqa: E402
from env.scenario import Scenario                       # noqa: E402
from final_study import physical_case as pc             # noqa: E402
from final_study import physical_case2 as c2            # noqa: E402

FS_RUN = ROOT/'results'/'final_study_2026_10_17'
SOURCES = ('src/final_study/physical_case.py', 'src/final_study/physical_case2.py', 'scripts/run_physical_case2.py')


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


def construct():
    """(nominal per profile, fallbacks, scenarios, smoke control) from the stored FS mission."""
    source = _read(FS_RUN/'fs'/'missions'/f'{c2.SOURCE}.json.gz')
    classes = source['ledger']['classes']
    base = c2.nominal_mission(source['variants'][c2.SOURCE_VARIANT], classes)
    nominal, fallbacks = {}, {}
    for profile in c2.PROFILES:
        nominal[profile], fallbacks[profile] = c2.with_profile(base, classes, profile)
    scenarios = {c2.condition_id(*c): c2.apply_update(nominal[c[0]], *c[1:], profile=c[0]) for c in c2.conditions()}
    return classes, nominal, fallbacks, scenarios, c2.smoke_control(nominal['P15'])


def build(out):
    classes, nominal, fallbacks, scenarios, smoke = construct()
    premise = {k: previous_premise(Scenario(p))['accepted'] for k, p in nominal.items()}
    report = {k: c2.nominal_report(p) for k, p in nominal.items()}
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    record = dict(source=c2.SOURCE_VARIANT, git_commit=commit,
                  source_sha256={f: hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in SOURCES},
                  classes=classes, previous_premise=premise, fallbacks=fallbacks, nominal=report,
                  energy_fit=pc.energy_fit(),
                  scenario_hashes={cid: Scenario(p).content_hash() for cid, p in scenarios.items()},
                  smoke_hash=Scenario(smoke).content_hash())
    _write(Path(out)/'scenarios.json.gz', dict(nominal=nominal, conditions=scenarios, smoke=smoke))
    (Path(out)/'build.json').write_text(json.dumps(record, indent=1))
    print('previous premise:', premise, '| fallbacks:', {k: len(v) for k, v in fallbacks.items()},
          '| scenarios:', len(scenarios))
    if not all(premise.values()):
        raise SystemExit('nominal mission infeasible under the previous forecast: the study stops here')


def checked(out):
    """Stored scenarios, after checking them against the build record and the current code."""
    record = json.loads((Path(out)/'build.json').read_text())
    stored = _read(Path(out)/'scenarios.json.gz')
    rebuilt = construct()[3]
    for cid, payload in stored['conditions'].items():
        if Scenario(payload).content_hash() != record['scenario_hashes'][cid] or \
                Scenario(rebuilt[cid]).content_hash() != record['scenario_hashes'][cid]:
            raise SystemExit(f'{cid}: scenario differs from the build record')
    if set(stored['conditions']) != set(record['scenario_hashes']):
        raise SystemExit('scenario set differs from the build record')
    if Scenario(stored['smoke']).content_hash() != record['smoke_hash']:
        raise SystemExit('smoke control differs from the build record')
    return stored, record


def smoke(out, budget, settings):
    stored, _ = checked(out)
    from final_study.arena import label
    r = label('PHY2_SMOKE_zero_change', stored['smoke'], budget, settings)
    _write(Path(out)/'smoke.json.gz', r)
    ok = r['result']['bounds']['minimum'] == 0 and r['audit']['ok']
    print('smoke control:', r['result']['bounds'], 'replay', r['audit']['ok'], '->', 'PASS' if ok else 'FAIL')
    if not ok:
        raise SystemExit('smoke control failed: the study stops for a fix')


def label_all(out, workers, budget, settings):
    stored, _ = checked(out)
    smoke_record = Path(out)/'smoke.json.gz'
    if not smoke_record.exists() or _read(smoke_record)['result']['bounds']['minimum'] != 0:
        raise SystemExit('run a passing smoke control first')
    scenarios = stored['conditions']
    todo = [cid for cid in scenarios if not (Path(out)/'labels'/f'{cid}.json.gz').exists()]
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('spawn')) as pool:
        futures = [pool.submit(_label, out, cid, scenarios[cid], budget, settings) for cid in todo]
        for i, f in enumerate(as_completed(futures), 1):
            print(f'{i}/{len(todo)} {f.result()}', flush=True)


def summary(out):
    stored, _ = checked(out)
    rows = []
    for cid, payload in stored['conditions'].items():
        r = _read(Path(out)/'labels'/f'{cid}.json.gz')
        res, b = r['result'], r['result']['bounds']
        profile, anchor, coverage, direction, strength = cid.split('_')[1:]
        first_plan = next((e['cpu_s'] for e in res['events'] if e['kind'] == 'plan'), None)
        # Certified when the plan at the minimum and every lower-level proof are in hand.
        minimum_plan = next((e['cpu_s'] for e in res['events']
                             if e['kind'] == 'plan' and e.get('level') == b['minimum']), None)
        last_proof = max((e['cpu_s'] for e in res['events'] if e['kind'] == 'proof'
                          and (b['minimum'] == 'infinity' or e['level'] < b['minimum'])), default=0)
        certified = b['status'] in ('minimum_certified', 'infeasible')
        rows.append(dict(
            condition=cid, profile=profile, anchor=anchor, coverage=coverage, direction=direction,
            strength_ms=int(strength[:-2]), **pc.diagnosis(payload), status=b['status'], minimum=b['minimum'],
            lower=b['lower'], upper=b['upper'], excluded=b['excluded_levels'], level_status=res['level_status'],
            decisions=r['decisions'], cpu_s=res['clock']['cpu_s'], first_plan_cpu_s=first_plan,
            certificate_cpu_s=(last_proof if b['status'] == 'infeasible' else max(minimum_plan or 0, last_proof))
            if certified else None,
            battery_margin_wh=c2.plan_battery_margin(payload, res['plan']['witness']) if res.get('plan') else None,
            replay_ok=r['audit']['ok']))
    (Path(out)/'summary.json').write_text(json.dumps(rows, indent=1))
    print(f'{len(rows)} instances summarized')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('build', 'smoke', 'label', 'summary'))
    parser.add_argument('--out', default=str(ROOT/'results'/'physical_case2_2026_10_21'))
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--budget', type=float, default=600)
    args = parser.parse_args()
    settings = json.loads((ROOT/'configs'/'final_study'/'final.json').read_text())['settings']
    if args.phase == 'build':
        build(args.out)
    elif args.phase == 'smoke':
        smoke(args.out, args.budget, settings)
    elif args.phase == 'label':
        label_all(args.out, args.workers, args.budget, settings)
    else:
        summary(args.out)


if __name__ == '__main__':
    main()
