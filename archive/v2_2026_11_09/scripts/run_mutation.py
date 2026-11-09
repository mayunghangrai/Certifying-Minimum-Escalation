"""B3: mutation testing of the independent checker (design doc, Section 15).

Stored proofs are replayed unchanged (control), then once per mutation operator. Each operator
makes the proof claim more than it shows; the checker (``certify_v2.replay.verify_run``) must
reject the mutant. Digests are recomputed where a hash would otherwise reject the mutant before
its mathematics is checked. Sample: 50 proofs per class (600 s labels with minimum 1, 2, 3, 4 or
no continuation, half FS and half LS where possible; CMI-mu runs with allowance proofs).

    python scripts/run_mutation.py --stage smoke --out results/mutation_smoke --workers 6
    python scripts/run_mutation.py --stage run --out results/mutation_2026_11_01 --workers 6
    python scripts/run_mutation.py --stage report --out results/mutation_2026_11_01
"""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from fractions import Fraction
import json
import multiprocessing
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

from certify_v2.oracle import UavModel               # noqa: E402
from certify_v2.replay import Lookup, verify_run     # noqa: E402
from certify_v2.route import TICK                    # noqa: E402
from env.scenario import Scenario                    # noqa: E402
from final_study.arena import attach                 # noqa: E402
from final_study.store import Store                  # noqa: E402
from recovery.local_search import digest             # noqa: E402

SOURCE, CMI_MU = 'results/final_study_2026_10_17', 'results/cmi_mu_2026_11_01'
SEED, PER_CLASS, SMOKE = 76105, 50, 2
CLASSES = ('1', '2', '3', '4', 'infinity', 'CMI-mu')


# ---- sample ------------------------------------------------------------------------------
def sample(per_class):
    """(class, store, group, tag, instance, arm) per proof, seeded; FS and LS halves where possible."""
    source, mu = Store(SOURCE, None, bind=False), Store(CMI_MU, None, bind=False)
    pools = {c: {'fs': [], 'ls': []} for c in CLASSES}
    for group in ('fs', 'ls'):
        for path in source.all(group, 'labels'):
            record = source.load(group, 'labels', path.name[:-len('.json.gz')])
            minimum = str(record['result']['bounds']['minimum'])
            if minimum in pools and record['audit']['ok']:
                pools[minimum][group].append((SOURCE, group, 'labels', record['instance'], 'CMI'))
        for tag in ('arena_10s', 'arena_60s'):
            for path in mu.all(group, tag):
                record = mu.load(group, tag, path.name[:-len('.json.gz')])
                entry = record['arms']['CMI-mu']
                if entry['result'].get('mu_proofs') and entry['audit']['ok']:
                    pools['CMI-mu'][group].append((CMI_MU, group, tag, record['instance'], 'CMI-mu'))
    rng = random.Random(SEED)
    out = []
    for c in CLASSES:
        fs, ls = sorted(pools[c]['fs']), sorted(pools[c]['ls'])
        n_fs = min(len(fs), per_class//2)
        n_ls = min(len(ls), per_class-n_fs)
        n_fs = min(len(fs), per_class-n_ls)
        out += [(c, *u) for u in rng.sample(fs, n_fs)+rng.sample(ls, n_ls)]
    return out


def payload(group, instance):
    source = Store(SOURCE, None, bind=False)
    if group == 'fs':
        return source.load('fs', 'missions', instance.rsplit('_r', 1)[0])['variants'][instance]
    return source.load('ls', 'draws', instance)['payload']


def full_result(store_path, group, tag, instance, arm):
    store = Store(store_path, None, bind=False)
    record = store.load(group, tag, instance)
    result = record['result'] if tag == 'labels' else record['arms'][arm]['result']
    return attach(result, store.load_proofs(record)[arm])


# ---- mutation operators: each returns a mutated copy, or None where it does not apply -----
def cited(result):
    """Proof records the bracket rests on (level and allowance proofs and their trees)."""
    records = {r['id']: r for r in result['records']}
    out = set()

    def walk(rid):
        out.add(rid)
        if records[rid]['kind'] in ('level3_patches_v2', 'allowance_patches_v1'):
            for tree in records[rid]['trees']:
                walk(tree)
    for rid in list(result.get('level_proofs', {}).values())+list(result.get('mu_proofs', {}).values()):
        walk(rid)
    return [records[i] for i in sorted(out)]


def o1_farkas_zero(scenario, m, rng):
    """Zero one nonzero Farkas multiplier of a fixed-route exclusion."""
    recs = [r for r in cited(m) if r['kind'] == 'fixed_route_lower_v2'
            and any(Fraction(v) for v in r.get('farkas', {}).values())]
    if not recs:
        return None
    r = rng.choice(recs)
    r['farkas'][rng.choice(sorted(k for k, v in r['farkas'].items() if Fraction(v)))] = '0'
    return m


def o2_leg_tick(scenario, m, rng):
    """Claim one leg of a fixed-route exclusion takes longer than proven: a released leg one tick
    above its certified bound (a record may cite a weaker bound than the block's final one, so
    +1 tick alone can stay valid), a fixed path one tick above its recomputed time."""
    recs = [r for r in cited(m) if r['kind'] == 'fixed_route_lower_v2' and r['legs']]
    if not recs:
        return None
    r = rng.choice(recs)
    i = rng.randrange(len(r['legs']))
    source = r['sources'][i]
    if source[0] == 'pair':
        ticks = Lookup(scenario, m['evidence'][0]).ticks(r['uid'], source[1], source[2])+1
        r['legs'][i] = str(Fraction(ticks, TICK))
    else:
        r['legs'][i] = str(Fraction(r['legs'][i])+Fraction(1, TICK))
    return m


def o3_lower_double(scenario, m, rng):
    """Double a travel-time lower bound and re-key its certificate (digest recomputed)."""
    options = [(b, k) for b, block in enumerate(m['evidence']) for k, c in sorted(block['certificates'].items())
               if Fraction(c['lower']) > 0]
    if not options:
        return None
    b, key = rng.choice(options)
    block = m['evidence'][b]
    cert = block['certificates'].pop(key)
    cert = dict(cert, lower=str(2*Fraction(cert['lower'])))
    new = digest(cert)
    block['certificates'][new] = cert
    for pair in block['pairs']:
        if pair[3] == key:
            pair[3] = new
    return m


def o4_matrix_above(scenario, m, rng):
    """Set one route-proof matrix entry one tick above its certified bound."""
    options = [(b, i) for b, block in enumerate(m['evidence']) for i, p in enumerate(block['proofs']) if p.get('matrix')]
    if not options:
        return None
    b, i = rng.choice(options)
    proof = m['evidence'][b]['proofs'][i]
    nodes = UavModel(scenario, proof['uid']).nodes(list(proof['tasks']))
    cells = [(x, y) for x in range(len(nodes)) for y in range(len(nodes)) if tuple(nodes[x]) != tuple(nodes[y])]
    if not cells:
        return None
    x, y = rng.choice(cells)
    proof['matrix'][x][y] = Lookup(scenario, m['evidence'][b]).ticks(proof['uid'], nodes[x], nodes[y])+1
    return m


def o5_skeleton_node(scenario, m, rng):
    """Delete one reachable node of a stop-sequence tree."""
    options = []
    for b, block in enumerate(m['evidence']):
        for i, p in enumerate(block['proofs']):
            if p['kind'] != 'skeleton_tree_v2':
                continue
            for key, node in p['tree'].items():
                for child in node.get('children', ()) if node['kind'] == 'branch' else ():
                    name = f'{key}|{child}' if key else child
                    if name in p['tree']:
                        options.append((b, i, name))
    if not options:
        return None
    b, i, name = rng.choice(sorted(options))
    del m['evidence'][b]['proofs'][i]['tree'][name]
    return m


def o6_assignment_node(scenario, m, rng):
    """Delete one non-root node of a cited assignment tree (an owner choice left unexamined)."""
    options = [(r['id'], k) for r in cited(m) if r['kind'] == 'assignment_tree_v2' for k in sorted(r['nodes']) if k]
    if not options:
        return None
    rid, key = rng.choice(options)
    del next(r for r in m['records'] if r['id'] == rid)['nodes'][key]
    return m


def o7_patch_drop(scenario, m, rng):
    """Drop one patch from a Level-3 or allowance exclusion."""
    recs = [r for r in cited(m) if r['kind'] in ('level3_patches_v2', 'allowance_patches_v1') and r['trees']]
    if not recs:
        return None
    r = rng.choice(recs)
    r['trees'].pop(rng.randrange(len(r['trees'])))
    return m


def o8_plan_level(scenario, m, rng):
    """Relabel the plan one level lower and claim that bracket."""
    if not m.get('plan') or m['plan']['level'] < 1:
        return None
    level = m['plan']['level']-1
    m['plan']['level'] = m['plan_level'] = level
    m['bounds'] = dict(m['bounds'], upper=level, minimum=level if m['bounds']['lower'] == level else None)
    return m


def o9_quantity_nudge(scenario, m, rng):
    """Raise one positive delivery of the plan by 1/1000 (plan re-hashed)."""
    if not m.get('plan'):
        return None
    w = m['plan']['witness']
    options = [i for i, c in enumerate(w['columns']) if c[2] == 'x' and Fraction(w['values'][i]) > 0]
    if not options:
        return None
    i = rng.choice(options)
    uid, h, _ = w['columns'][i]
    value = Fraction(w['values'][i])+Fraction(1, 1000)
    w['values'][i] = str(value)
    w['plan']['routes'][uid]['deliveries'][int(h)] = float(value)
    w['candidate_hash'] = digest(w['plan'])
    return m


def o10_promote(scenario, m, rng):
    """Cite the highest level exclusion as an exclusion of the next level."""
    proofs = m.get('level_proofs') or {}
    if not proofs or max(map(int, proofs)) >= 4:
        return None
    k = max(map(int, proofs))
    proofs[str(k+1)] = proofs[str(k)]
    lower = k+2
    m['bounds'] = dict(m['bounds'], lower=lower, excluded_levels=list(range(lower)),
                       minimum='infinity' if lower == 5 else m['bounds']['upper'] if m['bounds']['upper'] == lower else None)
    return m


OPERATORS = (o1_farkas_zero, o2_leg_tick, o3_lower_double, o4_matrix_above, o5_skeleton_node, o6_assignment_node,
             o7_patch_drop, o8_plan_level, o9_quantity_nudge, o10_promote)
# Operators whose mutant is invalid by construction; the others can leave a valid proof.
GUARANTEED = {'o2_leg_tick', 'o4_matrix_above', 'o5_skeleton_node', 'o6_assignment_node', 'o7_patch_drop',
              'o8_plan_level', 'o10_promote'}


def replay(scenario, result):
    start = time.process_time()
    try:
        verify_run(scenario, json.loads(json.dumps(result)))
        return dict(accepted=True, reason=None, cpu_s=time.process_time()-start)
    except Exception as error:      # any failure is a rejection; its type and message are recorded
        return dict(accepted=False, reason=f'{type(error).__name__}: {error}'[:160], cpu_s=time.process_time()-start)


def unit(item):
    cls, store_path, group, tag, instance, arm = item
    scenario = Scenario(payload(group, instance))
    result = full_result(store_path, group, tag, instance, arm)
    out = dict(cls=cls, store=store_path, group=group, tag=tag, instance=instance, arm=arm,
               control=replay(scenario, result), mutants={})
    for op in OPERATORS:
        rng = random.Random(f'{SEED}:{instance}:{tag}:{op.__name__}')
        mutant = op(scenario, deepcopy(result), rng)
        out['mutants'][op.__name__] = None if mutant is None else replay(scenario, mutant)
    return out


# ---- report ------------------------------------------------------------------------------
def report(out):
    rows = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(Path(out, 'units').glob('*.json'))]
    lines = ['# B3: mutation testing of the checker', '',
             f'Run `{out}`: {len(rows)} stored proofs; checker `certify_v2.replay.verify_run`. Each mutant claims more '
             'than its proof shows; a guaranteed operator cannot leave a valid proof.', '',
             'Controls (unchanged proofs) accepted: '
             f"{sum(r['control']['accepted'] for r in rows)} of {len(rows)}; by class: "
             + ', '.join(f"{c} {sum(r['cls'] == c for r in rows)}" for c in CLASSES), '',
             '| operator | guaranteed | applied | rejected | rejection rate | check that fired (top 3) |',
             '|---|---|---:|---:|---:|---|']
    accepted = []
    for op in OPERATORS:
        name = op.__name__
        done = [(r, r['mutants'][name]) for r in rows if r['mutants'].get(name)]
        rejected = [m for _, m in done if not m['accepted']]
        reasons = Counter(m['reason'].split(':')[0]+': '+m['reason'].split(': ', 1)[1][:40] for m in rejected)
        accepted += [(name, r['cls'], r['instance'], r['tag']) for r, m in done if m['accepted']]
        lines.append(f"| {name} | {'yes' if name in GUARANTEED else 'no'} | {len(done)} | {len(rejected)} | "
                     f"{100*len(rejected)/len(done) if done else 0:.1f}% | "
                     + '; '.join(f'{k} ({v})' for k, v in reasons.most_common(3)) + ' |')
    lines += ['', 'Applied mutants by class:', '', '| operator | ' + ' | '.join(CLASSES) + ' |',
              '|---|' + '---:|'*len(CLASSES)]
    for op in OPERATORS:
        lines.append(f'| {op.__name__} | ' + ' | '.join(
            str(sum(1 for r in rows if r['cls'] == c and r['mutants'].get(op.__name__))) for c in CLASSES) + ' |')
    lines += ['', f'Accepted mutants (to inspect by hand): {len(accepted)}', '']
    lines += [f'- {n} on {c} `{i}` ({t})' for n, c, i, t in accepted]
    Path(out, 'REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('\n'.join(lines))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=('smoke', 'run', 'report'), required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--workers', type=int, default=6)
    args = parser.parse_args()
    if args.stage == 'report':
        report(args.out)
        return
    items = sample(SMOKE if args.stage == 'smoke' else PER_CLASS)
    folder = Path(args.out, 'units')
    folder.mkdir(parents=True, exist_ok=True)
    name = lambda item: f'{item[0]}__{item[3]}__{item[4]}.json'
    todo = [i for i in items if not (folder/name(i)).exists()]
    print(f'{args.stage}: {len(items)} proofs, {len(todo)} to do, {args.workers} workers', flush=True)
    start = time.time()
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context('spawn')) as pool:
        futures = {pool.submit(unit, i): i for i in todo}
        for k, future in enumerate(as_completed(futures), 1):
            item = futures[future]
            try:
                (folder/name(item)).write_text(json.dumps(future.result()), encoding='utf-8')
            except Exception as error:      # a unit that crashes is logged and retried by the next run
                print(f'FAILED {item[4]}: {type(error).__name__}: {error}', flush=True)
            if k % 10 == 0 or k == len(todo):
                print(f'{k}/{len(todo)}, {(time.time()-start)/60:.1f} min', flush=True)
    report(args.out)


if __name__ == '__main__':
    main()
