"""Versioned local recovery and replayable evidence for the revised manuscript.

Every exclusion is confined to the declared finite path representation. The
independent physical proof layer can strengthen the full-domain lower bound.
Wall limits are checked between enumeration/LP operations (soft limits).
"""
from fractions import Fraction
import hashlib
import json
import math
from time import perf_counter

from env.fixed_plan import evaluate_plan
from env.local_scope import (require_v2, affected_uavs, scope_family,
                             patch_contains, scope_membership, change_metrics,preservation_metrics)
from env.plan import coordinates
from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update
from .enumeration import enumerate_events
from .linear import rational, solve_linear, verify_exclusion
from .physics import UnsupportedArithmetic
from .transfers import build_transfer_problem, materialize, BranchRejected


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _coordinate_point(scenario, plan, exact_quantities):
    candidate = coordinates(scenario.data,plan)
    candidate['L'] = {k:rational(v) for k,v in candidate['L'].items()}
    if exact_quantities is not None:
        candidate['L'].update({k:Fraction(v) for k,v in exact_quantities.items()})
    return candidate


def verify_local_witness(scenario, library, plan, reserves, level, *, exact_transfers=None,
                         _diagnostic=None):
    """Check Y, the patch union, numerical simulation, and a rational primal."""
    try:
        require_v2(scenario)
        if _diagnostic is None:
            library.validate(scenario)
        plan = scenario.validate_candidate(plan)
        reserves = scenario.validate_reserve_paths(plan,reserves)
        if not library.contains(plan,reserves):
            return dict(accepted=False,exact=False,reason='outside representation')
        diagnostic = _diagnostic or diagnose_wind_update(scenario)
        u0 = affected_uavs(scenario,diagnostic)['uavs']
        candidate = _coordinate_point(scenario,plan,exact_transfers)
        patches = [p for p in scope_family(scenario,level,u0) if patch_contains(scenario,candidate,p)]
        if not patches:
            return dict(accepted=False,exact=False,reason='outside scope union')
        simulation = evaluate_plan(scenario,plan,reserve_paths=reserves)
        if simulation.status != 'feasible':
            return dict(accepted=False,exact=False,reason=simulation.status)
        exact = False
        for patch in patches:
            try:
                compiled = build_transfer_problem(scenario,plan,reserves,patch.releases,exact=True)
                if exact_transfers is not None and set(exact_transfers) != set(compiled.problem.variables):
                    continue
                point = []
                for name,(uid,h,a) in zip(compiled.problem.variables,compiled.columns):
                    value = plan['routes'][uid]['deliveries' if a=='x' else 'loads'][h]
                    q = rational(value) if exact_transfers is None else Fraction(exact_transfers[name])
                    if float(q) != value:
                        raise ValueError('exact quantity differs from its plan projection')
                    point.append(q)
                if compiled.problem.accepts(point):
                    exact = True
                    break
            except (UnsupportedArithmetic,BranchRejected):
                continue
        # Supplying an invalid exact primal cannot silently downgrade a certificate.
        if exact_transfers is not None and not exact:
            return dict(accepted=False,exact=False,reason='invalid or unsupported exact primal')
        membership = next(k for k in range(5) if scope_membership(scenario,candidate,k,u0))
        return dict(accepted=True,exact=exact,level=membership,
                    scenario_hash=scenario.content_hash(),candidate_hash=digest(dict_plan(plan)),
                    participants=list(patch.participants),
                    numerical_tolerance=1e-9)
    except (ValueError,TypeError,KeyError,ArithmeticError,StopIteration) as error:
        return dict(accepted=False,exact=False,reason=str(error))


def dict_plan(plan):
    from env.scenario import _thaw
    return _thaw(plan)


def _branch(scenario,library,level,patch,event,diagnostic,lp_options):
    plan,reserves = event
    try:
        try:
            compiled = build_transfer_problem(scenario,plan,reserves,patch.releases,exact=True)
        except UnsupportedArithmetic:
            compiled = build_transfer_problem(scenario,plan,reserves,patch.releases,exact=False)
        lp = solve_linear(compiled.problem,**lp_options)
        if lp.status == 'EMPTY':
            return dict(outcome='EMPTY',exact=True,certificate=lp.certificate),None
        if lp.status != 'WITNESS':
            return dict(outcome='UNRESOLVED',exact=False,reason=lp.reason),None
        candidate = materialize(compiled,lp.values)
        fractions = dict(zip(compiled.problem.variables,map(str,lp.values))) if lp.exact else None
        validation = verify_local_witness(scenario,library,candidate,reserves,level,
                                         exact_transfers=fractions,_diagnostic=diagnostic)
        if not validation['accepted']:
            return dict(outcome='UNRESOLVED',exact=False,reason=validation['reason']),None
        return (dict(outcome='WITNESS',exact=validation['exact']),
                dict(plan=candidate,reserve_paths=reserves,exact=validation['exact'],
                     exact_transfers=fractions,validation=validation,certificate_level=level))
    except BranchRejected as error:
        return dict(outcome='REJECTED' if error.exact else 'UNRESOLVED',exact=error.exact,reason=str(error)),None
    except (ArithmeticError,ValueError) as error:
        return dict(outcome='UNRESOLVED',exact=False,reason=str(error)),None


def _search_patch(scenario,library,level,patch,diagnostic,*,nodes,branches,seconds,lp_options):
    start = perf_counter()
    evidence, witness = [], None
    count = 0
    complete = False
    events = iter(enumerate_events(scenario,library,patch.releases))
    while count < nodes and len(evidence) < branches and (seconds is None or perf_counter()-start < seconds):
        try:
            event = next(events)
        except StopIteration:
            complete = True
            break
        count += 1
        if event is None:
            continue
        outcome,witness = _branch(scenario,library,level,patch,event,diagnostic,lp_options)
        evidence.append(dict(index=len(evidence),branch_hash=digest(event),**outcome))
        if witness is not None:
            break
    status = ('WITNESS' if witness else 'EMPTY' if complete and all(
        e['outcome'] in ('EMPTY','REJECTED') for e in evidence) else 'UNRESOLVED')
    return dict(patch=patch.to_dict(),status=status,enumeration_complete=complete,
                nodes=count,branches=len(evidence),branch_evidence=evidence,witness=witness,
                elapsed_s=perf_counter()-start)


def previous_premise(scenario):
    p = scenario.to_dict()
    p['wind']['received'] = {**p['wind']['previous'],'issued_at_h':p['mission']['epoch_h']}
    p['wind']['update_support'] = []
    previous = Scenario(p)
    try:
        c = build_transfer_problem(previous,p['incumbent'],p['reserve_paths'],
                                   scope_family(previous,0,())[0].releases,exact=True)
        return dict(exact_feasible=c.problem.accepts(()),reason=None)
    except BranchRejected as error:
        return dict(exact_feasible=False,reason=str(error))
    except ArithmeticError as error:
        return dict(exact_feasible=None,reason=str(error))


def bounds(excluded, upper, numerical_upper=None):
    excluded = sorted(excluded)
    lower = None if 4 in excluded else 1+max(excluded,default=-1)
    if upper is not None and (lower is None or upper < lower):
        raise ValueError('inconsistent exact witness and exclusion evidence')
    minimum = 'infinity' if 4 in excluded else upper if upper is not None and lower == upper else None
    status = ('infeasible' if minimum == 'infinity' else 'minimum_certified' if minimum is not None
              else 'witness_with_gap' if upper is not None else 'numerical_witness' if numerical_upper is not None
              else 'unresolved')
    return dict(status=status,minimum=minimum,lower=lower,upper=upper,
                numerical_upper=numerical_upper,excluded_levels=excluded)


def recover_local(scenario,library,*,max_nodes=100000,max_branches=10000,max_seconds=None,
                  strategy='H',max_operations=10000,max_rows=2000,max_iterations=10000,
                  numerical=True):
    require_v2(scenario)
    for value in (max_nodes,max_branches):
        if isinstance(value,bool) or not isinstance(value,int) or value < 0:
            raise ValueError('work budgets must be nonnegative integers')
    if max_seconds is not None and (isinstance(max_seconds,bool) or not math.isfinite(max_seconds) or max_seconds < 0):
        raise ValueError('time budget must be finite and nonnegative')
    if strategy not in ('H','G'):
        raise ValueError('strategy must be H or G')
    start = perf_counter()
    library.validate(scenario)
    diagnostic = diagnose_wind_update(scenario)
    info = affected_uavs(scenario,diagnostic)
    u0 = info['uavs']
    premise = previous_premise(scenario)
    coverage_complete = 'missing' not in scenario.data['wind']['received']['coverage']
    records,excluded = [],set()
    physical_certificates = []
    witness = None
    upper = numerical_upper = first_witness = None
    used_nodes = used_branches = 0
    search_start = perf_counter()
    retention_screen = 'not_requested'
    if max_nodes and max_branches and coverage_complete:
        incumbent = scenario.to_dict()['incumbent']
        reserves = scenario.to_dict()['reserve_paths']
        check = verify_local_witness(scenario,library,incumbent,reserves,0,_diagnostic=diagnostic)
        used_nodes = used_branches = 1
        if check['accepted'] and check['exact']:
            upper = 0
            first_witness = perf_counter()-start
            witness = dict(plan=incumbent,reserve_paths=reserves,exact=True,exact_transfers=None,
                           validation=check,certificate_level=0,source='common_retention_screen')
            retention_screen = 'exact_witness'
        else:
            retention_screen = 'no_exact_witness'
            from .physical_proofs import physical_certificate
            certificate = physical_certificate(scenario,0)
            if certificate is not None:
                excluded.add(0)
                physical_certificates.append(certificate)
                retention_screen = 'physical_exclusion'
    weights = (.05,.15,.20,.35,.25) if strategy=='H' else (.05,.95)
    levels = range(5) if strategy=='H' else (0,4)
    cumulative = 0.
    lp_options = dict(max_operations=max_operations,max_rows=max_rows,
                      max_iterations=max_iterations,numerical=numerical)
    for level,weight in zip(levels,weights):
        if witness: break
        cumulative += weight
        if level == 0 and physical_certificates: continue
        node_limit = round(max_nodes*cumulative)
        branch_limit = round(max_branches*cumulative)
        stage_deadline = None if max_seconds is None else search_start+max_seconds*cumulative
        patches = scope_family(scenario,level,u0)
        patch_records = []
        for i,patch in enumerate(patches):
            remaining = len(patches)-i
            seconds = None if stage_deadline is None else max(0,stage_deadline-perf_counter())/remaining
            record = _search_patch(scenario,library,level,patch,diagnostic,
                nodes=max(0,node_limit-used_nodes)//remaining if coverage_complete else 0,
                branches=max(0,branch_limit-used_branches)//remaining,seconds=seconds,lp_options=lp_options)
            used_nodes += record['nodes']
            used_branches += record['branches']
            patch_records.append(record)
            if record['witness']:
                witness = record['witness']
                first_witness = perf_counter()-start
                k = witness['validation']['level']
                if witness['exact']:
                    upper = k
                else:
                    numerical_upper = k
                break
        empty = len(patch_records)==len(patches) and all(p['status']=='EMPTY' for p in patch_records)
        if empty:
            excluded.update(range(level+1))
        records.append(dict(level=level,status='EMPTY' if empty else 'WITNESS' if witness else 'UNRESOLVED',
                            required_patches=[p.to_dict() for p in patches],patches=patch_records))
        if witness:
            break
    represented = bounds(excluded,upper,numerical_upper)
    physical_excluded = {k for c in physical_certificates for k in range(c['excluded_through']+1)}
    full = bounds(physical_excluded,upper,numerical_upper)
    # A sufficient equality check; failure is not evidence of unequal domains.
    p3 = scope_family(scenario,3,u0)
    p4 = scope_family(scenario,4,u0)[0]
    collapse = any(p.releases==p4.releases for p in p3)
    elapsed = perf_counter()-start
    return dict(version='local-recovery-v2',formulation='2026-09-30',strategy=strategy,
        requested_evidence='minimum_scope' if strategy=='H' else 'feasible_recovery',
        scenario_hash=scenario.content_hash(),representation_hash=library.content_hash(),
        policy=dict(helper_budget=scenario.data['hierarchy']['helper_budget']),
        previous_premise=premise,affected=info,
        input_coverage_complete=coverage_complete,
        represented=represented,full_domain=full,physical_certificates=physical_certificates,levels=records,witness=witness,
        change=change_metrics(scenario,witness['plan'],u0,exact_quantities=witness['exact_transfers']) if witness else None,
        preservation=preservation_metrics(scenario,witness['plan'],witness['validation']['level'],u0,
                                          exact_quantities=witness['exact_transfers']) if witness else None,
        scope3_equals_scope4='certified_equal' if collapse else 'not_certified_equal',
        effort=dict(nodes=used_nodes,branches=used_branches,elapsed_s=elapsed,
                    setup_s=search_start-start,search_s=perf_counter()-search_start,
                    retention_screen=retention_screen,
                    first_witness_s=first_witness,
                    full_domain_certificate_s=elapsed if full['minimum'] is not None else None,
                    represented_certificate_s=elapsed if represented['minimum'] is not None else None),
        budget=dict(nodes=max_nodes,branches=max_branches,seconds=max_seconds,clock='soft_between_operations',**lp_options),
        claim='Represented exclusions apply only to the stored path library. Full-domain exclusions require independent physical certificates.')


def _verify_patch_empty(scenario,library,patch,record):
    if record['status'] != 'EMPTY' or not record['enumeration_complete']:
        return False
    nodes = count = 0
    entries = record['branch_evidence']
    for event in enumerate_events(scenario,library,patch.releases):
        nodes += 1
        if nodes > record['nodes']:
            return False
        if event is None:
            continue
        if count >= len(entries):
            return False
        e = entries[count]
        if e['index'] != count or not e['exact'] or e['branch_hash'] != digest(event):
            return False
        try:
            c = build_transfer_problem(scenario,*event,patch.releases,exact=True)
        except BranchRejected as error:
            if not error.exact or e['outcome'] != 'REJECTED' or e['reason'] != str(error):
                return False
        else:
            if e['outcome'] != 'EMPTY' or not verify_exclusion(c.problem,e['certificate']):
                return False
        count += 1
    return count == len(entries) == record['branches'] and nodes == record['nodes']


def verify_local_evidence(scenario,library,report):
    """Recompute scope coverage and replay every claimed exact exclusion."""
    try:
        library.validate(scenario)
        if (report['version'] != 'local-recovery-v2' or report['scenario_hash'] != scenario.content_hash()
                or report['representation_hash'] != library.content_hash()):
            return False
        diagnostic = diagnose_wind_update(scenario)
        info = affected_uavs(scenario,diagnostic)
        if info != report['affected'] or report['previous_premise'] != previous_premise(scenario):
            return False
        if report['policy'] != dict(helper_budget=scenario.data['hierarchy']['helper_budget']):
            return False
        u0,excluded = info['uavs'],set()
        collapse = any(p.releases == scope_family(scenario,4,u0)[0].releases
                       for p in scope_family(scenario,3,u0))
        if report['scope3_equals_scope4'] != ('certified_equal' if collapse else 'not_certified_equal'):
            return False
        for record in report['levels']:
            patches = scope_family(scenario,record['level'],u0)
            if record['required_patches'] != [p.to_dict() for p in patches] or len(record['patches']) > len(patches):
                return False
            for patch,p in zip(patches,record['patches']):
                if p['patch'] != patch.to_dict():
                    return False
                if p['status']=='EMPTY' and not _verify_patch_empty(scenario,library,patch,p):
                    return False
            if record['status']=='EMPTY':
                if len(record['patches']) != len(patches) or any(p['status']!='EMPTY' for p in record['patches']):
                    return False
                excluded.update(range(record['level']+1))
        upper = numerical = None
        if report['witness']:
            w = report['witness']
            check = verify_local_witness(scenario,library,w['plan'],w['reserve_paths'],w['certificate_level'],
                                        exact_transfers=w['exact_transfers'],_diagnostic=diagnostic)
            if not check['accepted'] or check['exact'] != w['exact'] or check['level'] != w['validation']['level']:
                return False
            if check['exact']: upper = check['level']
            else: numerical = check['level']
            if report['change'] != change_metrics(scenario,w['plan'],u0,exact_quantities=w['exact_transfers']):
                return False
            if 'preservation' in report and report['preservation'] != preservation_metrics(
                    scenario,w['plan'],check['level'],u0,exact_quantities=w['exact_transfers']):
                return False
        elif report['change'] is not None:
            return False
        if report['physical_certificates']:
            from .physical_proofs import verify_physical_certificate
            physical = set()
            for cert in report['physical_certificates']:
                if not verify_physical_certificate(scenario,cert): return False
                physical.update(range(cert['excluded_through']+1))
        else:
            physical = set()
        # Optional represented-only dominance certificates from the stationary
        # benchmark screen. Old records need no migration or new proof fields.
        from .static_paths import verify_static_certificate
        for cert in report.get('static_certificates', []):
            if not verify_static_certificate(scenario, library, cert): return False
            excluded.update(range(cert['level']+1))
        from .represented_proofs import verify_represented_certificate
        for cert in report.get('represented_certificates', []):
            if not verify_represented_certificate(scenario, library, cert): return False
            excluded.update(range(cert['excluded_through']+1))
        return (report['represented'] == bounds(excluded|physical,upper,numerical)
                and report['full_domain'] == bounds(physical,upper,numerical))
    except (ValueError,KeyError,TypeError,ArithmeticError):
        return False
