"""Phase A checks before Phase B: the fill count and Gate A.

fill: one slot per (MS cell, layout family) and per (SC cell, block size),
filled with the real draw loop (up to 192 draws). Only draw counts and
rejection reasons are summarised; no label is computed.

gate (Q13): on 200 generated missions, check
- determinism: the mission, block and admission rebuild identically from the seed;
- incumbent feasibility: the incumbent is certified at Level 0 under F0;
- admission rule (admitted missions): |U0| in [1, ceil(m/3)], Level 0 rejected
  under F1 at r = 0.6, and the optimistic pass finds a certain violation;
- conservation (admitted missions): all nine variants validate and conserve
  stock + onboard + delivered;
- rescaling: under (L, T) = (2, 1/2) or (1/2, 2) the mission validates, the
  premise outcome and U0 are unchanged, float-evaluator finish times scale by
  T, and the incumbent rebuilt in the rescaled units is the same plan.

Seeds: base 90001, a development seed outside every study range (Q8).
"""
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import Counter
from fractions import Fraction as F
import gzip
import json
import math
import multiprocessing
from pathlib import Path
import time

from continuous.validation import certify_witness, previous_premise
from env.fixed_plan import evaluate_plan
from env.local_scope import affected_uavs
from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update
from . import wind_model
from .admission import ADMISSION_R, admit, certain_violations
from .generate import MAX_DRAWS, fill_slot, ms_cells, sc_cells, variants
from .missions import build_mission, configured_coefficients
from .rescale import incumbent_routes, rebuild_incumbent, rescale
from .snapshots import conservation
from .update import apply_magnitude, place_block

BASE_SEED = 90001
FACTORS = ((F(2), F(1, 2)), (F(1, 2), F(2)))
GATE_MISSIONS = 200


def fill_slots():
    out = [(cell, slot, family) for cell in ms_cells() for slot, family in ((0, 'uniform'), (2, 'clustered'))]
    out += [(dict(cell, size=size), slot, ('uniform', 'clustered')[slot % 2])
            for cell in sc_cells() for slot, size in enumerate((1, 4, 9))]
    return out


def _name(cell, slot):
    return f"{cell['key']}|slot{slot}".replace('|', '_')


def fill_one(job):
    cell, slot, family, root = job
    start = time.time()
    result = fill_slot(BASE_SEED, cell, slot, family, configured_coefficients())
    record = dict(key=result['key'], cell=cell, slot=slot, family=family, seconds=time.time() - start,
                  draws=len(result['log']), admitted=result['mission'] is not None, log=result['log'])
    if result['mission'] is not None:
        record.update(mission=result['mission'].to_dict(), block=result['block'],
                      info={k: v for k, v in result['info'].items()})
    path = Path(root)/'fill'/(_name(cell, slot) + '.json.gz')
    with gzip.open(path, 'wt', encoding='utf-8') as f:
        json.dump(record, f)
    return record['key'], record['draws'], record['admitted'], record['seconds']


def _pool(function, jobs, workers, log):
    context = multiprocessing.get_context('spawn')
    done = 0
    with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
        futures = [pool.submit(function, job) for job in jobs]
        for future in as_completed(futures):
            done += 1
            log(f'{done}/{len(jobs)} {future.result()}')


def run_fill(root, workers, log=print):
    (Path(root)/'fill').mkdir(parents=True, exist_ok=True)
    jobs = [(c, s, f, str(root)) for c, s, f in fill_slots()
            if not (Path(root)/'fill'/(_name(c, s) + '.json.gz')).exists()]
    log(f'fill: {len(jobs)} slots to run')
    _pool(fill_one, jobs, workers, log)
    return summarize_fill(root)


def load_fill(root):
    records = []
    for path in sorted((Path(root)/'fill').glob('*.json.gz')):
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            records.append(json.load(f))
    return records


def summarize_fill(root):
    rows = []
    for r in load_fill(root):
        reasons = Counter(e['reason'].split(':')[0] for e in r['log'] if not e['admitted'])
        rows.append(dict(key=r['key'], draws=r['draws'], admitted=r['admitted'],
                         stage=r['log'][-1]['stage'], seconds=round(r['seconds'], 1), reasons=dict(reasons)))
    summary = dict(slots=len(rows), filled=sum(r['admitted'] for r in rows),
                   unfilled=[r['key'] for r in rows if not r['admitted']],
                   beyond_48=[r['key'] for r in rows if r['draws'] > 48],
                   draws_total=sum(r['draws'] for r in rows), max_draws=MAX_DRAWS, rows=rows)
    (Path(root)/'fill_summary.json').write_text(json.dumps(summary, indent=1), encoding='utf-8')
    return summary


def gate_jobs(root):
    """All admitted fill missions, topped up to 200 with first draws rebuilt from the logs."""
    records = load_fill(root)
    jobs = [dict(kind='admitted', cell=r['cell'], family=r['family'], entry=r['log'][-1], block=r['block'])
            for r in records if r['admitted']]
    for r in records:
        if len(jobs) >= GATE_MISSIONS:
            break
        entry = r['log'][0]
        if not entry['admitted'] and ('u0' in entry or entry['reason'].startswith('previous premise')):
            jobs.append(dict(kind='drawn', cell=r['cell'], family=r['family'], entry=entry, block=None))
    for i, job in enumerate(jobs[:GATE_MISSIONS]):
        job['factors'] = [str(x) for x in FACTORS[i % 2]]
        job['root'] = str(root)
        job['index'] = i
    return jobs[:GATE_MISSIONS]


def _build(job):
    cell, entry = job['cell'], job['entry']
    return build_mission(entry['seed'], m=cell['m'], n=cell['n'], family=job['family'], slack=cell['slack'],
                         beta=cell['beta'], coefficients=configured_coefficients(),
                         geometry_seed=entry['geometry_seed'])


def _finish_times(scenario, projection):
    evaluation = evaluate_plan(scenario, projection=projection)
    return {u: s['time_h'] for u, s in evaluation.final_states.items()}


def _u0(payload):
    s = Scenario(payload)
    return affected_uavs(s, diagnose_wind_update(s))['uavs']


def gate_one(job):
    checks, start = {}, time.time()
    mission, info = _build(job)
    payload = mission.to_dict()
    entry, cell = job['entry'], job['cell']

    # Determinism: a second build from the seed is identical.
    again, _ = _build(job)
    checks['determinism_mission'] = again.to_dict() == payload

    # Incumbent feasibility under F0.
    premise = previous_premise(mission)
    checks['incumbent_feasible_f0'] = premise['accepted']

    block = job['block'] if job['block'] is not None else place_block(mission, entry['seed'], cell['size'])
    if job['kind'] == 'admitted':
        checks['determinism_block'] = place_block(mission, entry['seed'], cell['size']) == job['block']
        decision = json.loads(json.dumps(admit(mission, block)))
        checks['determinism_admission'] = all(decision.get(k) == entry.get(k) for k in ('admitted', 'reason', 'u0', 'violations'))
        updated = Scenario(apply_magnitude(payload, block, ADMISSION_R))
        u0 = _u0(updated.to_dict())
        m = len(payload['mission']['vehicles'])
        checks['admission_u0_range'] = 1 <= len(u0) <= math.ceil(m/3)
        checks['admission_level0_rejected'] = not certify_witness(updated, payload['incumbent'],
                                                                  payload['reserve_paths'], 0)['accepted']
        checks['admission_certain_violation'] = bool(certain_violations(updated))
        ok = True
        for v in variants(mission, block):
            Scenario(v['payload'])
            ok = ok and conservation(payload, v['payload'])
        checks['conservation_nine_variants'] = ok

    # Rescaling.
    L, T = (F(x) for x in job['factors'])
    scaled = rescale(payload, L, T)
    checks['rescale_premise'] = previous_premise(Scenario(scaled))['accepted'] == premise['accepted']
    updated = apply_magnitude(payload, block, ADMISSION_R)
    scaled_updated = rescale(updated, L, T)
    checks['rescale_u0'] = _u0(scaled_updated) == _u0(updated)
    ratio_ok = True
    for projection in ('previous', 'received'):
        a, b = _finish_times(Scenario(updated), projection), _finish_times(Scenario(scaled_updated), projection)
        ratio_ok = ratio_ok and all(math.isclose(b[u], float(T)*a[u], rel_tol=1e-9, abs_tol=1e-9) for u in a)
    checks['rescale_float_times'] = ratio_ok
    seed, V = info['seed'], L/T

    def wind(r, j):
        return tuple(x*V for x in wind_model.f0_value(seed, r, j))
    checks['rescale_incumbent'] = rebuild_incumbent(scaled, wind) == incumbent_routes(payload)

    record = dict(index=job['index'], kind=job['kind'], key=cell['key'], seed=entry['seed'], factors=job['factors'],
                  checks=checks, passed=all(checks.values()), seconds=time.time() - start)
    (Path(job['root'])/'gate'/f"{job['index']:03d}.json").write_text(json.dumps(record), encoding='utf-8')
    return job['index'], record['passed'], round(record['seconds'], 1)


def run_gate(root, workers, log=print):
    (Path(root)/'gate').mkdir(parents=True, exist_ok=True)
    jobs = [j for j in gate_jobs(root) if not (Path(root)/'gate'/f"{j['index']:03d}.json").exists()]
    log(f'gate: {len(jobs)} missions to check')
    _pool(gate_one, jobs, workers, log)
    return summarize_gate(root)


def summarize_gate(root):
    records = [json.loads(p.read_text(encoding='utf-8')) for p in sorted((Path(root)/'gate').glob('*.json'))]
    failures = Counter(name for r in records for name, ok in r['checks'].items() if not ok)
    summary = dict(missions=len(records), passed=sum(r['passed'] for r in records),
                   admitted=sum(r['kind'] == 'admitted' for r in records),
                   failures=dict(failures), failed=[(r['index'], r['key'], r['seed']) for r in records if not r['passed']])
    (Path(root)/'gate_summary.json').write_text(json.dumps(summary, indent=1), encoding='utf-8')
    return summary
