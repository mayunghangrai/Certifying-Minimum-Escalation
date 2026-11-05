"""Replay and combine search evidence with separately stored cohort admission evidence.

Run each stage's `report` command first. This derived analysis leaves the frozen
search records intact and binds its own reporting source separately.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from continuous_benchmark.cli import _audit_sampling, _baseline, slots, _slot_id
from continuous_benchmark.records import audit_record, load_paired_bank, source_files
from final_benchmark.records import verify_archive
from recovery.local_search import bounds, digest


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def label(value):
    return 'unknown' if value is None else str(value)


def read_stage(path, stage):
    manifest = read_json(path / 'manifest.json')
    binding = {k: manifest[k] for k in ('config', 'source_hash', 'input_binding')}
    if (manifest['run_hash'] != digest(binding)
            or manifest['source_hash'] != digest(manifest['source_files'])
            or manifest['config']['stage'] != stage):
        raise ValueError('stage manifest binding failed')
    verify_archive(path / 'source.zip', manifest['source_files'])
    records = {}
    for file in sorted((path / 'records').glob('*.json')):
        record = read_json(file)
        if (file.stem != record['case_id'] or record['run_hash'] != manifest['run_hash']
                or record['request']['budget'] != manifest['config']['budget']
                or not audit_record(record)):
            raise ValueError('record binding or replay failed: ' + file.name)
        records[record['case_id']] = record
    summary = read_json(path / 'analysis/summary.json')
    counts = dict(Counter(label(r['result']['full_domain']['minimum']) for r in records.values()))
    if (summary['run_hash'] != manifest['run_hash'] or not summary['audit']['audit_passed']
            or summary['cases'] != len(records) or summary['minima'] != counts):
        raise ValueError('stage report differs from replayed records')
    return manifest, records, summary


def summarize(root, output):
    runs = {stage: read_stage(root / stage, stage) for stage in ('controlled', 'paired', 'cohort')}
    if any(m['source_hash'] != digest(source_files()) for m, _, _ in runs.values()):
        raise ValueError('current experiment source differs from the frozen runs')
    paired_manifest, paired, paired_summary = runs['paired']
    bank_path = Path(paired_manifest['config']['input_bank'])
    if not bank_path.is_absolute():
        bank_path = ROOT / bank_path
    original, bank = load_paired_bank(bank_path, audit=False)
    if bank != paired_manifest['input_binding'] or set(paired) != set(bank['records']):
        raise ValueError('paired bank binding or completeness failed')
    for old in original:
        new = paired[old['case_id']]
        if (new['scenario'] != old['scenario'] or new['baseline'] != _baseline(old)
                or new['request']['metadata'] != old['request']['metadata']):
            raise ValueError('paired fixed inputs changed')
    penalties = sorted(r['case_id'] for r in paired.values()
        if r['result']['full_domain']['upper'] is not None
        and (r['baseline']['represented']['minimum'] == 'infinity'
             or r['baseline']['represented']['lower'] is not None
             and r['result']['full_domain']['upper'] < r['baseline']['represented']['lower']))
    if penalties != sorted(paired_summary['rigorous_library_penalty_cases']):
        raise ValueError('paired penalty table differs from replayed evidence')

    manifest, cohort, search_summary = runs['cohort']
    expected = {_slot_id(*s): s for s in slots(manifest['config'])}
    sampling = {f.stem: read_json(f) for f in sorted((root / 'cohort/sampling').glob('*.json'))}
    if set(sampling) != set(expected):
        raise ValueError('cohort sampling slots incomplete')
    rows, case_ids, failures = [], set(), []
    for name, item in sampling.items():
        if item['slot'] != name or item['run_hash'] != manifest['run_hash']:
            raise ValueError('sampling run binding failed')
        n, m, family, seed = expected[name]
        if any(item['metadata'][k] != v for k, v in dict(n=n, m=m, family=family, seed=seed).items()):
            raise ValueError('sampling stratum changed')
        _audit_sampling(item, manifest['config'])
        if item['metadata']['status'] != 'accepted':
            failures.append(name)
            continue
        for case_id, scenario in sorted(item['scenarios'].items()):
            case_ids.add(case_id)
            record = cohort[case_id]
            if (record['scenario'] != scenario
                    or record['request']['metadata']['sampling_hash'] != item['binding_hash']):
                raise ValueError('cohort scenario binding failed')
            side = record['request']['metadata']['side']
            full = record['result']['full_domain']
            excluded = set(full['excluded_levels'])
            upper = full['upper']
            if side == 'below':
                # _audit_sampling independently replayed this all-path proof.
                excluded.update(range(item['metadata']['boundary_certificate']['excluded_through'] + 1))
                admission_lower, admission_upper = 2, None
                certificate = item['metadata']['boundary_certificate']
            elif side == 'above':
                # _audit_sampling independently checked the stored reference plan.
                certificate = item['metadata']['upper_validation']
                admission_lower, admission_upper = 0, certificate['level']
                upper = admission_upper if upper is None else min(upper, admission_upper)
            else:
                raise ValueError('invalid cohort side')
            combined = bounds(excluded, upper)
            rows.append(dict(case_id=case_id, base_mission=name, side=side,
                solver_lower=full['lower'], solver_upper=full['upper'], solver_minimum=label(full['minimum']),
                admission_lower=admission_lower, admission_upper=admission_upper,
                combined_lower=combined['lower'], combined_upper=combined['upper'],
                combined_minimum=label(combined['minimum']), combined_status=combined['status'],
                search_record_hash=record['record_hash'], sampling_hash=item['binding_hash'],
                admission_certificate_hash=digest(certificate)))
    if set(cohort) != case_ids:
        raise ValueError('cohort record count differs from the sampling ledger')
    combined_summary = dict(cases=len(rows),
        certified_minima=sum(r['combined_minimum'] != 'unknown' for r in rows),
        feasible_witnesses=sum(r['combined_upper'] is not None for r in rows),
        minima=dict(Counter(r['combined_minimum'] for r in rows)),
        by_side={side: dict(cases=len(group),
            minima=dict(Counter(r['combined_minimum'] for r in group)),
            feasible_witnesses=sum(r['combined_upper'] is not None for r in group))
            for side in ('below', 'above')
            for group in ([r for r in rows if r['side'] == side],)},
        changed_conclusions=[r['case_id'] for r in rows
            if (r['solver_lower'], r['solver_upper'], r['solver_minimum'])
            != (r['combined_lower'], r['combined_upper'], r['combined_minimum'])])
    summary = dict(version='continuous-combined-analysis-v1',
        stages={stage: {k: s[k] for k in ('cases', 'certified_minima', 'feasible_witnesses', 'minima')}
                for stage, (_, _, s) in runs.items()},
        rigorous_library_penalty_cases=penalties,
        cohort=dict(sampling=search_summary['sampling'], failed_slots=failures,
                    solver_only=search_summary['minima'], combined=combined_summary),
        interpretation='Combined cohort evidence reuses independently verified admission proofs and witnesses. '
                       'It is separate from the bounded search outcome and its measured runtime.')
    output.mkdir(parents=True, exist_ok=True)
    with (output / 'cohort_combined_evidence.csv').open('w', encoding='utf-8', newline='') as file:
        fields = ['case_id', 'base_mission', 'side', 'solver_lower', 'solver_upper', 'solver_minimum',
                  'admission_lower', 'admission_upper', 'combined_lower', 'combined_upper',
                  'combined_minimum', 'combined_status', 'search_record_hash', 'sampling_hash',
                  'admission_certificate_hash']
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    write_json(output / 'summary.json', summary)
    driver = Path(__file__).resolve()
    (output / driver.name).write_bytes(driver.read_bytes())
    analysis_binding = dict(version='continuous-derived-analysis-binding-v1',
        driver_sha256=hashlib.sha256(driver.read_bytes()).hexdigest(),
        runs={stage: dict(run_hash=m['run_hash'], source_hash=m['source_hash'],
              manifest_hash=digest(m), records={k: r['record_hash'] for k, r in records.items()},
              stage_summary_hash=digest(s)) for stage, (m, records, s) in runs.items()},
        sampling={name: item['binding_hash'] for name, item in sampling.items()},
        outputs={name: hashlib.sha256((output / name).read_bytes()).hexdigest()
                 for name in ('cohort_combined_evidence.csv', 'summary.json', driver.name)})
    write_json(output / 'analysis_manifest.json', analysis_binding)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True, help='Directory containing the three primary stages')
    parser.add_argument('--out', type=Path, help='Derived output directory; defaults to ROOT/analysis')
    args = parser.parse_args()
    result = summarize(args.root, args.out or args.root / 'analysis')
    print(json.dumps(result['cohort'], indent=2, sort_keys=True))
