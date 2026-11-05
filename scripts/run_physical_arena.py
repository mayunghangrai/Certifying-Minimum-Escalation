"""10 s method comparison on the disrupted instances of both physical case studies.

Arms CMI, PH, LR, GR-c and GR, run and replayed by `final_study.arena.run_instance` with the final
study settings; outcomes scored by the FS rule (`analysis._within_budget`: the returned plan counts
only if it replays and was returned by the CPU cutoff). Disrupted = reference minimum above 0.

    python scripts/run_physical_arena.py --workers 3
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import json
import multiprocessing
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

CASES = {'case1': ROOT/'results'/'physical_case_2026_10_21', 'case2': ROOT/'results'/'physical_case2_2026_10_21'}
ARMS = ('GR', 'GR-c', 'LR', 'PH', 'CMI')
BUDGET = 10


def _read(path):
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        return json.load(f)


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    with gzip.open(tmp, 'wt', encoding='utf-8') as f:
        json.dump(value, f, sort_keys=True)
    tmp.replace(path)


def _run(path, cid, payload, settings, budget):
    sys.path.insert(0, str(ROOT/'src'))
    from final_study.arena import run_instance
    if not Path(path).exists():
        _write(Path(path), run_instance(cid, payload, budget, ARMS, settings))
    return cid


def disrupted():
    """(case, instance id, payload, reference minimum) for every reference minimum above 0."""
    out = []
    for case, root in CASES.items():
        scenarios = _read(root/'scenarios.json.gz')['conditions']
        for row in json.loads((root/'summary.json').read_text()):
            if row['minimum'] != 0:
                out.append((case, row['condition'], scenarios[row['condition']], row['minimum']))
    return out


def _dest(case, out):
    """Output folder of a case: its results folder, or `out/<case>` when --out is given."""
    return CASES[case] if out is None else Path(out)/case


def summarize(units, out=None, budget=BUDGET):
    from final_study.analysis import _arena_row, _within_budget
    rows = []
    for case, cid, _, reference in units:
        record = _read(_dest(case, out)/f'arena_{budget}s'/f'{cid}.json.gz')
        for arm, entry in record['arms'].items():
            r = _within_budget(_arena_row(record, arm, entry))
            ref = 5 if reference == 'infinity' else reference
            rows.append(dict(case=case, instance=cid, arm=arm, reference_minimum=reference,
                             plan_level=r['plan_level'], at_minimum=r['plan_level'] == ref if ref <= 4 else None,
                             certified=r['certified'], certified_minimum=r['minimum'],
                             first_plan_cpu_s=r['first_plan_cpu'], certificate_cpu_s=r['certificate_cpu'],
                             uavs_changed=r.get('d_uavs_changed'), tasks_reassigned=r.get('d_tasks_reassigned'),
                             replay_ok=r['audit_ok'], overrun_s=r['overrun'],
                             unreturned_better_plan=r['unreturned_better_plan']))
    for case in CASES:
        (_dest(case, out)/f'arena_{budget}s_summary.json').write_text(
            json.dumps([r for r in rows if r['case'] == case], indent=1))
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--out', help='write to OUT/case1 and OUT/case2 instead of the case results folders')
    parser.add_argument('--budget', type=int, default=BUDGET, help='CPU seconds per arm (default 10)')
    args = parser.parse_args()
    settings = json.loads((ROOT/'configs'/'final_study'/'final.json').read_text())['settings']
    units = disrupted()
    todo = [(str(_dest(c, args.out)/f'arena_{args.budget}s'/f'{cid}.json.gz'), cid, p) for c, cid, p, _ in units]
    todo = [t for t in todo if not Path(t[0]).exists()]
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context('spawn')) as pool:
        futures = [pool.submit(_run, path, cid, payload, settings, args.budget) for path, cid, payload in todo]
        for i, f in enumerate(as_completed(futures), 1):
            print(f'{i}/{len(todo)} {f.result()}', flush=True)
    print(f'{len(summarize(units, args.out, args.budget))} arm results summarized for {len(units)} instances')


if __name__ == '__main__':
    main()
