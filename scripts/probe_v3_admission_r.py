"""Probe: would the empty MS slots fill if admission tested r = 0.8 instead of 0.6?

For every MS slot the fill count left empty, replay its logged draws in order
(same draw and geometry seeds) with admission at r = 0.8, and stop at the
first admitted draw or after --draws draws. Nothing in study_v3 is changed:
the admission strength is passed to `admit`. No label
is computed.

    python -P scripts/probe_v3_admission_r.py --workers 14 --draws 24
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import json
import multiprocessing
import os
from pathlib import Path
import sys
import time

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
os.chdir(ROOT)

FILL = Path('results/v3_phase_a/fill')
OUT = Path('results/v3_phase_a/probe_r08')


def probe(job):
    from study_v3 import admission
    from study_v3.missions import build_mission, configured_coefficients
    from study_v3.update import place_block
    cell, start, tried = job['cell'], time.time(), []
    for entry in job['log'][:job['draws']]:
        try:
            mission, _ = build_mission(entry['seed'], m=cell['m'], n=cell['n'], family=job['family'],
                                       slack=cell['slack'], beta=cell['beta'], coefficients=configured_coefficients(),
                                       geometry_seed=entry['geometry_seed'])
            decision = admission.admit(mission, place_block(mission, entry['seed'], cell['size']), job['r'])
        except ValueError as error:
            decision = dict(admitted=False, reason=str(error))
        tried.append(dict(draw=entry['draw'], admitted=decision['admitted'], reason=decision['reason'],
                          u0=decision.get('u0'), reason_r06=entry['reason']))
        if decision['admitted']:
            break
    record = dict(key=job['key'], cell=cell, family=job['family'], r=job['r'], draws=len(tried),
                  admitted=tried[-1]['admitted'], seconds=time.time() - start, log=tried)
    (OUT/(job['key'].replace('|', '_') + '.json')).write_text(json.dumps(record), encoding='utf-8')
    return job['key'], record['draws'], record['admitted']


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=14)
    parser.add_argument('--draws', type=int, default=24)
    parser.add_argument('--r', type=float, default=0.8)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = []
    for path in sorted(FILL.glob('MS_*.json.gz')):
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            r = json.load(f)
        if r['admitted'] or (OUT/(r['key'].replace('|', '_') + '.json')).exists():
            continue
        jobs.append(dict(key=r['key'], cell=r['cell'], family=r['family'], log=r['log'], draws=args.draws, r=args.r))
    print(f'probe: {len(jobs)} empty MS slots, up to {args.draws} draws each, r = {args.r}', flush=True)
    context = multiprocessing.get_context('spawn')
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=context) as pool:
        futures = [pool.submit(probe, job) for job in jobs]
        for i, future in enumerate(as_completed(futures), 1):
            print(i, future.result(), flush=True)
    records = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(OUT.glob('*.json'))]
    filled = [r for r in records if r['admitted']]
    print(json.dumps(dict(slots=len(records), filled=len(filled), draws_tried=sum(r['draws'] for r in records),
                          unfilled=[r['key'] for r in records if not r['admitted']]), indent=1), flush=True)
