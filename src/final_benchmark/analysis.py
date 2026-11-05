"""Summaries retain unknowns and keep represented/full-domain labels separate."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import random
import statistics

from .records import audit_record,record_hash

LEVELS = [0,1,2,3,4,'infinity']


def recoverability_membership(bound,level):
    """Classify D_{<=level} using exact evidence, including incomplete minima."""
    if bound['upper'] is not None and bound['upper'] <= level:
        return 'inside'
    if any(k >= level for k in bound['excluded_levels']):
        return 'outside'
    return 'unresolved'


def load_records(path,*,audit=True):
    result = []
    for p in sorted((Path(path)/'records').glob('*.json')):
        record = json.loads(p.read_text(encoding='utf-8'))
        if record_hash(record) != record.get('record_hash'):
            raise ValueError('record hash mismatch: '+str(p))
        if audit and not audit_record(record): raise ValueError('record audit failed: '+str(p))
        result.append(record)
    return result


def possible(bound,k):
    if bound['minimum'] is not None: return bound['minimum']==k
    if k=='infinity': return bound['upper'] is None
    return k >= (bound['lower'] or 0) and (bound['upper'] is None or k<=bound['upper'])


def distribution(records,field):
    n = len(records)
    counts = Counter(r['result'][field]['minimum'] for r in records)
    return dict(n=n,certified={str(k):counts[k] for k in LEVELS},unresolved=counts[None],
        identification_intervals={str(k):[counts[k]/n if n else None,
            sum(possible(r['result'][field],k) for r in records)/n if n else None] for k in LEVELS})


def _stats(values):
    values = sorted(values)
    if not values: return dict(n=0)
    return dict(n=len(values),median=statistics.median(values),minimum=values[0],maximum=values[-1],
                mean=statistics.mean(values))


def summarize(records):
    primary = [r for r in records if r['request']['strategy']=='H']
    witness = [r for r in primary if r['result']['witness']]
    groups = defaultdict(list)
    for r in primary:
        meta = r['request']['metadata']
        groups[meta.get('base_mission',r['case_id'])].append(r)
    # Confidence intervals describe the frequency of *certified observations*.
    # Identification intervals above also account for unresolved classifications.
    rng = random.Random(17029)
    clusters = list(groups.values())
    samples = {str(k):[] for k in [*LEVELS,None]}
    for _ in range(2000 if clusters else 0):
        selected = [r for _ in clusters for r in rng.choice(clusters)]
        count = Counter(r['result']['represented']['minimum'] for r in selected)
        for k in [*LEVELS,None]: samples[str(k)].append(count[k]/len(selected))
    ci = {k:[sorted(v)[int(.025*len(v))],sorted(v)[min(len(v)-1,int(.975*len(v)))]]
          for k,v in samples.items() if v}
    return dict(records=len(records),primary_updates=len(primary),base_missions=len(groups),
        represented=distribution(primary,'represented'),full_domain=distribution(primary,'full_domain'),
        represented_certified_frequency_cluster_bootstrap_95=ci,
        affected_fraction=_stats([r['result']['affected']['fraction'] for r in primary]),
        unaffected_updates=sum(r['result']['affected']['count']==0 for r in primary),
        full_fleet_affected=sum(r['result']['affected']['fraction']==1 for r in primary),
        previous_exact=sum(r['result']['previous_premise']['exact_feasible'] is True for r in primary),
        changed_uavs_among_witnesses=_stats([r['result']['change']['changed_uav_count'] for r in witness]),
        preserved_fraction_among_witnesses=_stats([r['result']['change']['preserved_fraction'] for r in witness]),
        local_witnesses=sum(r['result']['witness']['validation']['level']<=3 for r in witness),
        scope3_scope4_certified_equal=sum(r['result']['scope3_equals_scope4']=='certified_equal' for r in primary),
        search_seconds=_stats([r['timing']['solve_s'] for r in primary]),
        audit_seconds=_stats([r['timing']['audit_s'] for r in primary]),
        nodes=_stats([r['result']['effort']['nodes'] for r in primary]),
        branches=_stats([r['result']['effort']['branches'] for r in primary]),
        exact_witnesses=sum(r['result']['witness']['exact'] for r in witness),
        numerical_witnesses=sum(not r['result']['witness']['exact'] for r in witness),
        scope_note='k_R uses the stored finite path library; full-domain exclusions require physical certificates. Unresolved observations remain in every denominator.',
        intervention_note='Changed sets describe the returned witness. A minimum scope certificate does not minimize the number of changed coordinates within that scope.',
        inference_note='Randomized A/B updates share a base mission; bootstrap resamples whole base missions. Certified frequencies are not an unbiased estimate of unknown level frequencies.')


def write_summary(path):
    p = Path(path)
    result = summarize(load_records(p))
    (p/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result
