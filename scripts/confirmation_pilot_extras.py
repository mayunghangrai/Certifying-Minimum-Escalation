"""Extras for the confirmation pilot, from one run directory (review of 15 October 2026).

1. Replays every saved label, arena result and XR chain from its proof file on disk,
   independently of the replay done when the result was produced; for a level-suite label
   pooled with its draw's construction witness, re-checks the witness and the pooled bounds.
2. Tabulates the LS draws by recipe: outcome of each draw and certified class.

    python scripts/confirmation_pilot_extras.py results/final_study_confirmation_pilot_2026_10_15

Writes ``analysis/confirmation_extras.json`` in the run directory and prints it.
"""
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import sys

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
os.chdir(ROOT)

from env.scenario import Scenario      # noqa: E402
from escalation_study.snapshots import build_snapshot      # noqa: E402
from final_study.arena import attach, audit_chain, replay_saved      # noqa: E402
from final_study.level4 import pool      # noqa: E402
from final_study.stages import p1_payloads      # noqa: E402
from final_study.store import Store      # noqa: E402


def payloads(store, config):
    """Scenario payload of every instance name the run can hold."""
    out = {}
    for path in store.all('fs', 'missions'):
        item = store.load('fs', 'missions', path.name[:-len('.json.gz')])
        out.update(item['variants'])
        ledger = item['ledger']
        for vid, info in ledger.get('variants', {}).items():
            if info['time_index'] != 0:
                base = item['variants'][vid.rsplit('_t', 1)[0]+'_t0']
                cell = ledger['cell_index']
                snap, _ = build_snapshot(base, info['time'], received_wind=(cell, base['wind']['received']['values'][cell][0]),
                                         rule='D1')
                snap['benchmark_id'] = vid+'_D1'
                out[vid+'_D1'] = Scenario(snap).to_dict()
    for path in store.all('ls', 'draws'):
        item = store.load('ls', 'draws', path.name[:-len('.json.gz')])
        if item['payload'] is not None:
            out[item['draw']] = item['payload']
    for path in store.all('scaling', 'missions'):
        item = store.load('scaling', 'missions', path.name[:-len('.json.gz')])
        if item['payload'] is not None:
            out[item['mission']] = item['payload']
    for case, payload in p1_payloads(config, [(p.name[:-len('.json.gz')], p.name[:-len('.json.gz')].rsplit('_r', 1)[0])
                                              for p in store.all('p1', 'labels')]):
        out[case] = payload
    return out


def replay(store, config):
    known = payloads(store, config)
    counts = defaultdict(Counter)
    failures = []
    for group in ('fs', 'ls', 'p1', 'fs_d1', 'scaling', 'contention', 'variance'):
        root = store.path/group
        if not root.exists():
            continue
        for directory in sorted(p for p in root.iterdir() if p.is_dir() and (p.name == 'labels' or p.name.startswith('arena_'))):
            for path in sorted(directory.glob('*.json.gz')):
                name = path.name[:-len('.json.gz')]
                record = store.load(group, directory.name, name)
                payload = known.get(record['instance'])
                key = f'{group}/{directory.name}'
                if payload is None:
                    counts[key]['no payload'] += 1
                    continue
                for arm, audit in replay_saved(payload, record, store.load_proofs(record)).items():
                    counts[key]['ok' if audit['ok'] else 'failed'] += 1
                    if not audit['ok']:
                        failures.append([key, name, arm, audit.get('error')])
                if record.get('pooled') is not None:
                    # Re-check the draw's construction witness and recompute the pooled bounds.
                    witness = store.load('ls', 'draws', name)['ledger']['construction']['witness']
                    again = json.loads(json.dumps(pool(payload, record, witness)))
                    counts['ls/pooled']['ok' if again == record['pooled'] else 'failed'] += 1
                    if again != record['pooled']:
                        failures.append(['ls/pooled', name, 'witness', again])
    for path in store.all('xr', 'chains'):
        record = store.load('xr', 'chains', path.name[:-len('.json.gz')])
        proofs = store.load_proofs(record) or {}
        cases = list(record['xr'])
        chain = [(case, known_p1(config, case), attach(record['xr'][case]['result'], proofs.get('xr/'+case)))
                 for case in cases]
        for case, audit in zip(cases, audit_chain(chain)):
            counts['xr/chains']['ok' if audit['ok'] else 'failed'] += 1
            if not audit['ok']:
                failures.append(['xr/chains', case, 'XR', audit.get('error')])
    return {k: dict(v) for k, v in counts.items()}, failures


def known_p1(config, case):
    return p1_payloads(config, [(case, case.rsplit('_r', 1)[0])])[0][1]


def ls_by_recipe(store):
    selection = store.load('ls', 'selection', 'selection')
    selected = {}
    if selection:
        for cls, names in selection['selection']['selected'].items():
            for n in names:
                selected[n] = cls
    table = defaultdict(Counter)
    level4 = []
    for path in store.all('ls', 'draws'):
        item = store.load('ls', 'draws', path.name[:-len('.json.gz')])
        ledger = item['ledger']
        key = f"{ledger['target']}|{ledger['recipe']}|m{ledger['fleet']}"
        table[key]['draws'] += 1
        table[key][ledger['reason'] or 'admitted'] += 1
        label = store.load('ls', 'labels', ledger['draw'])
        if label is not None:
            b = (label.get('pooled') or {}).get('bounds') or label['result']['bounds']
            table[key][f"label {b['minimum'] if b['minimum'] is not None else 'unresolved'}"] += 1
            if b['minimum'] == 4:
                level4.append(dict(draw=ledger['draw'], recipe=ledger['recipe'], fleet=ledger['fleet'],
                                   time=ledger['time'], affected=ledger.get('affected'),
                                   construction=ledger.get('construction'), selected=selected.get(ledger['draw']),
                                   audit=label['audit']['ok']))
    return {k: dict(v) for k, v in sorted(table.items())}, level4


def main(run):
    manifest = json.loads((Path(run)/'manifest.json').read_text(encoding='utf-8'))
    store = Store(run, manifest['config'], bind=False)
    counts, failures = replay(store, manifest['config'])
    table, level4 = ls_by_recipe(store)
    out = dict(run=str(run), run_hash=manifest['run_hash'], replay_from_disk=counts, replay_failures=failures,
               ls_by_recipe=table, ls_level4=level4)
    path = Path(run)/'analysis'/'confirmation_extras.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, default=str)+'\n', encoding='utf-8')
    print(json.dumps(out, indent=2, default=str))


if __name__ == '__main__':
    main(sys.argv[1])
