"""B2: planted-minimum instances with ground truth independent of CMI (design doc, Section 17).

Each instance is one of the analytic gadgets of ``final_benchmark.controlled`` (C0 -> 0,
C1 -> 1, C2 -> 2, C3 -> 3, C4 -> 4 at b = 1 and 3 at b = 2, Cinf -> no continuation) plus a
background of n <= 3 UAVs that is isolated from it by deadlines alone. Background UAV B_j serves
one task N_j far north or south of the depot, in the unchanged west cell, with a deadline 0.2%
above its own flight time. Under the v1 all-path travel bound (``recovery.physical_proofs``):
- no gadget UAV reaches N_j by its deadline (background UAVs are 2-3 times faster);
- a background UAV serving a gadget task first misses its own deadline (the detour exceeds the
  0.2% slack), and serving N_j first misses every gadget deadline (N_j is far);
- no background UAV serves two background tasks (placement in ``embed``).
So the gadget's minimum is the instance's. An instance is admitted only if (1) the affected
fleet is the gadget's, (2) these inequalities hold under the v1 bound, (3) the supplied plan
(gadget recovery, background unchanged) passes the v1 exact check at the planted level, and
(4) the v1 relaxation proves every lower level infeasible (``physical_certificate``, code
independent of ``certify_v2``). Every arm then runs through ``final_study.arena.run_instance``.

    python scripts/run_planted.py --stage smoke --out results/planted_smoke --workers 6
    python scripts/run_planted.py --stage run --out results/planted_2026_11_01 --workers 6
    python scripts/run_planted.py --stage report --out results/planted_2026_11_01
"""
import argparse
from collections import Counter
from fractions import Fraction
import json
import os
from pathlib import Path
import random
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
from final_benchmark.controlled import controlled_case, make_plan      # noqa: E402
from final_study.stages import _pool                                   # noqa: E402
from final_study.store import Store                                    # noqa: E402
from recovery.local_search import verify_local_witness                 # noqa: E402
from recovery.physical_proofs import physical_certificate, travel_lower_bound, verify_physical_certificate  # noqa: E402
from recovery.physics import flight_duration                           # noqa: E402
from recovery.representation import PathLibrary                        # noqa: E402

CONFIG = ROOT/'configs'/'final_study'/'planted.json'
GADGETS = (('C0', 1, 0), ('C1', 1, 1), ('C2', 1, 2), ('C3', 1, 3), ('C4', 1, 4), ('C4', 2, 3), ('Cinf', 1, 5))
SLACK = Fraction(1, 500)        # background deadline = own flight time x (1 + SLACK)
PLACEMENT = (((81, 3280, 3281), 1), ((81, 3280, 3281), -1), ((13, 84, 85), 1))


def embed(name, b, n_bg, seed):
    """(payload, candidate plan, candidate reserves, C1 bypass paths) for one instance."""
    case = controlled_case(name, helper_budget=b)
    p = case.scenario.to_dict()
    rng = random.Random(f'B2:{name}:{b}:{n_bg}:{seed}')
    gadget = list(p['mission']['vehicles'])
    v_bg = round(max(v['airspeed_kmh'] for v in gadget)*rng.uniform(2, 3), 3)
    longest = max(t['deadline_h'] for t in p['mission']['tasks'])
    # N_j = s(-a, +-b) on a Pythagorean triple (rational flight time): N1 near due north, N2 near
    # due south, N3 north of N1 and 0.13 x its distance further west, so that under the axis-wise
    # bound no background UAV can serve both northern tasks.
    sites, first = [], None
    for j, (triple, sign) in enumerate(PLACEMENT[:n_bg]):
        a, b_, _ = triple
        reach = first*1.05 if j == 2 else v_bg*longest*rng.uniform(.8, 1.2)
        s = Fraction(str(round(reach/b_, 6)))
        sites.append((float(-s*a), float(sign*s*b_)))
        first = sites[0][1]
    top, bottom = max(y for _, y in sites)+1, min([y for _, y in sites]+[0])-1
    lift = lambda poly: [[-3 if x == -2 else x, top if y == 3 else bottom if y == -1 else y] for x, y in poly]
    p['mission']['operating_region_xy'] = lift(p['mission']['operating_region_xy'])
    for cell in p['wind']['cells']:
        cell['polygon_xy'] = lift(cell['polygon_xy'])
    for j, (x, y) in enumerate(sites, 1):
        p['mission']['vehicles'].append(dict(id=f'B{j}', airspeed_kmh=v_bg, empty_mass_kg=1,
                                             energy_coefficient_wh_per_kg_km=1, battery_capacity_wh=200, reserve_wh=1,
                                             payload_capacity_kg=1, slot_bound=2))
        p['mission']['tasks'].append(dict(id=f'N{j}', position_xy=[x, y], demand=1, mandatory=1, deadline_h=p['mission']['horizon_h']))
        p['state']['fleet'][f'B{j}'] = dict(position_xy=[0, 0], battery_wh=200, onboard=0, mode='idle', residual_operation=None)
        p['state']['cumulative_delivered'][f'N{j}'] = 0
    p['state']['depot_stock'] += n_bg
    p['mission']['horizon_h'] = max(p['mission']['horizon_h'], 20)
    background, reserves = make_plan(p, {f'B{j}': [f'N{j}'] for j in range(1, n_bg+1)})
    bg_ids = [f'B{j}' for j in range(1, n_bg+1)]
    for uid in bg_ids:
        p['incumbent']['routes'][uid] = background['routes'][uid]
        p['reserve_paths'][uid] = reserves[uid]
        p['incumbent']['assignment'][f'N{uid[1:]}'] = uid
    # Background deadlines: own exact flight time to N_j, plus SLACK.
    probe = Scenario(p)
    for j, uid in enumerate(bg_ids, 1):
        duration = flight_duration(probe, uid, p['incumbent']['routes'][uid]['paths'][0], Fraction(0), exact=True)
        next(t for t in p['mission']['tasks'] if t['id'] == f'N{j}')['deadline_h'] = float(duration*(1+SLACK))
    p['benchmark_id'] = f'P_{name}_b{b}_bg{n_bg}_s{seed}'
    candidate = reserves_c = None
    if case.witness_plan is not None:
        candidate = json.loads(json.dumps(case.witness_plan))
        reserves_c = json.loads(json.dumps(case.witness_reserves))
        for uid in bg_ids:
            candidate['routes'][uid] = background['routes'][uid]
            reserves_c[uid] = reserves[uid]
            candidate['assignment'][f'N{uid[1:]}'] = uid
    bypass = [candidate['routes']['U1']['paths'][0]] if name == 'C1' else []
    return Scenario(p).to_dict(), candidate, reserves_c, bypass


def admit(name, b, planted, payload, candidate, reserves, bypass):
    """(admitted, reasons, checks) by the four admission conditions."""
    scenario = Scenario(payload)
    d = scenario.data
    reasons = []
    u0 = affected_uavs(scenario, diagnose_wind_update(scenario))['uavs']
    if u0 != ['U1']:
        reasons.append(f'affected fleet {u0}')
    tasks = {t['id']: t for t in d['mission']['tasks']}
    depot = d['mission']['depot_xy']
    gadget_tasks = [i for i in tasks if not i.startswith('N')]
    lb = lambda uid, a, c: travel_lower_bound(scenario, uid, a, c)
    pos = lambda i: tasks[i]['position_xy']
    for uid in d['state']['fleet']:
        for j in (t for t in tasks if t.startswith('N')):
            deadline_j = Fraction(tasks[j]['deadline_h'])
            if uid.startswith('U'):
                if lb(uid, depot, pos(j)) <= deadline_j:
                    reasons.append(f'{uid} can reach {j}')
            elif uid == 'B'+j[1:]:
                for i in gadget_tasks:
                    if lb(uid, depot, pos(i))+lb(uid, pos(i), pos(j)) <= deadline_j:
                        reasons.append(f'{uid} can serve {i} before {j}')
                    if lb(uid, depot, pos(j))+lb(uid, pos(j), pos(i)) <= Fraction(tasks[i]['deadline_h']):
                        reasons.append(f'{uid} can serve {i} after {j}')
            if uid.startswith('B'):
                for k in (t for t in tasks if t.startswith('N') and t != j):
                    if lb(uid, depot, pos(j))+lb(uid, pos(j), pos(k)) <= Fraction(tasks[k]['deadline_h']):
                        reasons.append(f'{uid} can serve {j} then {k}')
    checks = {}
    library = PathLibrary.build(scenario, nominal_paths=bypass)
    if planted != 5:
        v = verify_local_witness(scenario, library, candidate, reserves, 4)
        checks['witness_level'] = v.get('level') if v['accepted'] and v.get('exact') else None
        if checks['witness_level'] != planted:
            reasons.append(f"witness level {checks['witness_level']} (accepted {v['accepted']})")
    target = 4 if planted == 5 else planted-1
    if target >= 0:
        cert = physical_certificate(scenario, target, max_assignments=10**5)
        checks['exclusion'] = cert is not None and verify_physical_certificate(scenario, cert)
        if not checks['exclusion']:
            reasons.append(f'v1 relaxation does not exclude Levels 0-{target}')
    return not reasons, reasons, checks


def build(out, sizes, seeds, log):
    """Generate and admit candidates; the ledger lists every candidate and why it was refused."""
    ledger_path = Path(out)/'ledger.json'
    ledger = json.loads(ledger_path.read_text(encoding='utf-8')) if ledger_path.exists() else {}
    folder = Path(out)/'payloads'
    folder.mkdir(parents=True, exist_ok=True)
    for name, b, planted in GADGETS:
        for n_bg in sizes:
            for seed in seeds:
                key = f'P_{name}_b{b}_bg{n_bg}_s{seed}'
                if key in ledger:
                    continue
                start = time.process_time()
                try:
                    payload, candidate, reserves, bypass = embed(name, b, n_bg, seed)
                    ok, reasons, checks = admit(name, b, planted, payload, candidate, reserves, bypass)
                except Exception as error:      # a candidate that cannot be built is refused and logged
                    ok, reasons, checks, payload = False, [f'{type(error).__name__}: {error}'[:200]], {}, None
                ledger[key] = dict(gadget=name, b=b, planted=planted, background=n_bg, seed=seed, admitted=ok,
                                   reasons=reasons, checks=checks, cpu_s=time.process_time()-start)
                if ok:
                    (folder/f'{key}.json').write_text(json.dumps(payload), encoding='utf-8')
                log(f"{key}: {'admitted' if ok else 'refused: '+'; '.join(reasons)}")
                ledger_path.write_text(json.dumps(ledger, indent=1), encoding='utf-8')
    return ledger


def report(out):
    ledger = json.loads(Path(out, 'ledger.json').read_text(encoding='utf-8'))
    store = Store(out, None, bind=False)
    planted = {k: v['planted'] for k, v in ledger.items() if v['admitted']}
    lines = ['# B2: planted-minimum instances', '', f'Run `{out}`. Ground truth: gadget analysis, admitted only when the '
             'v1 exact check accepts the planted plan and the v1 relaxation excludes every lower level (code independent '
             'of certify_v2). Level 5 = no continuation.', '', '| gadget | b | planted | candidates | admitted | refusals |',
             '|---|---:|---:|---:|---:|---|']
    for name, b, level in GADGETS:
        rows = [v for v in ledger.values() if v['gadget'] == name and v['b'] == b]
        refusals = Counter(r for v in rows for r in v['reasons'])
        lines.append(f"| {name} | {b} | {level} | {len(rows)} | {sum(v['admitted'] for v in rows)} | "
                     + ('; '.join(f'{k} ({n})' for k, n in refusals.most_common(4)) or '-') + ' |')
    for tag in ('arena_10s', 'arena_60s'):
        records = [store.load('planted', tag, p.name[:-len('.json.gz')]) for p in store.all('planted', tag)]
        if not records:
            continue
        lines += ['', f'## {tag[6:]}', '', '| arm | n | replays | certified | certified = planted | certified != planted '
                  '| plan below planted | plan at planted | plan above planted | certified by planted level 0/1/2/3/4/none |',
                  '|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
        arms = sorted({a for r in records for a in r['arms']})
        for arm in arms:
            rows = [(planted[r['instance']], r['arms'][arm]) for r in records if arm in r['arms']]
            code = lambda m: 5 if m == 'infinity' else m
            cert = [(t, code(e['result']['bounds']['minimum'])) for t, e in rows if e['result']['bounds']['minimum'] is not None]
            plans = [(t, e['result']['plan_level']) for t, e in rows if e['result']['plan_level'] is not None]
            by = Counter(t for t, m in cert if m == t)
            total = Counter(t for t, _ in rows)
            lines.append(f"| {arm} | {len(rows)} | {sum(e['audit']['ok'] for _, e in rows)} | {len(cert)} | "
                         f"{sum(m == t for t, m in cert)} | **{sum(m != t for t, m in cert)}** | "
                         f"**{sum(p < t for t, p in plans)}** | {sum(p == t for t, p in plans)} | {sum(p > t for t, p in plans)} | "
                         + ' / '.join(f'{by.get(k, 0)}/{total.get(k, 0)}' for k in range(6)) + ' |')
        mu = Counter()
        for r in records:
            e = r['arms'].get('CMI-mu')
            if e and e['result'].get('mu_bounds'):
                g = ledger[r['instance']]
                mu[(g['gadget'], g['b'], str(e['result']['mu_bounds']['minimum']))] += 1
        if mu:
            lines += ['', 'CMI-mu certified mu* by gadget (expected from the construction: C3 1, C4 2):',
                      ', '.join(f'{g} b={b}: mu*={m} x{n}' for (g, b, m), n in sorted(mu.items()))]
    Path(out, 'REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('\n'.join(lines))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=('smoke', 'run', 'report'), required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--config', default=str(CONFIG))
    args = parser.parse_args()
    if args.stage == 'report':
        report(args.out)
        return
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    smoke = args.stage == 'smoke'
    store = Store(args.out, config, workers=args.workers)
    log_path = Path(args.out)/'run.log'

    def log(message):
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
        print(line, flush=True)
        with log_path.open('a', encoding='utf-8') as stream:
            stream.write(line+'\n')
    sizes = config['smoke']['backgrounds'] if smoke else config['backgrounds']
    seeds = range(config['smoke']['seeds'] if smoke else config['seeds'])
    ledger = build(args.out, sizes, seeds, log)
    units = []
    for key, entry in sorted(ledger.items()):
        if not entry['admitted']:
            continue
        payload = json.loads((Path(args.out)/'payloads'/f'{key}.json').read_text(encoding='utf-8'))
        for budget, arms in ((10, config['arms_short']), (60, config['arms_long'])):
            if not store.exists('planted', f'arena_{budget}s', key):
                units.append(('planted', f'arena_{budget}s', key, payload, budget, arms))
    log(f'{args.stage}: {sum(v["admitted"] for v in ledger.values())} of {len(ledger)} admitted, {len(units)} arena units')
    _pool('arena', store.path, config, units, args.workers, log, args.stage)
    report(args.out)


if __name__ == '__main__':
    main()
