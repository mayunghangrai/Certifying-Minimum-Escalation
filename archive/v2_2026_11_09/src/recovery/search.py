"""Bounded ascending recovery with explicit evidence and uncertainty."""
from dataclasses import dataclass, field
from fractions import Fraction
import hashlib
import json

from env.intervention_scope import release_sets, _level
from env.recovery_validation import validate_recovery_plan
from env.plan import coordinates
from env.scenario import Scenario
from env.wind_dependency import diagnose_wind_update
from .enumeration import enumerate_events
from .linear import solve_linear, verify_exclusion, rational
from .physics import UnsupportedArithmetic
from .transfers import build_transfer_problem, materialize, BranchRejected


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _releases(scenario,level,diagnostic):
    return release_sets(scenario,level,diagnostic.affected_tasks)


def _scope_key(releases):
    return tuple((a,tuple(sorted(keys))) for a,keys in sorted(releases.items()))


def verify_witness(scenario, library, plan, reserves, level, *, exact_transfers=None):
    """Check representation, original simulator predicates and exact LP primal.

Exact fractions are the certificate's transfer values; plan JSON carries their
float projections for the existing simulator. Their projections must agree.
"""
    library.validate(scenario)
    try:
        report = validate_recovery_plan(scenario,plan,level,reserve_paths=reserves)
        if report.status != 'witness':
            return dict(accepted=False,exact=False,reason=report.status)
        if not library.contains(plan,reserves):
            return dict(accepted=False,exact=False,reason='outside declared path representation')
        diagnostic = report.diagnostic
        exact = False
        try:
            c = build_transfer_problem(scenario,plan,reserves,_releases(scenario,level,diagnostic),exact=True)
            if exact_transfers is not None and set(exact_transfers) != set(c.problem.variables):
                return dict(accepted=False,exact=False,reason='wrong exact transfer coordinates')
            point = []
            for name,(uid,h,a) in zip(c.problem.variables,c.columns):
                value = plan['routes'][uid]['deliveries' if a=='x' else 'loads'][h]
                quantity = rational(value) if exact_transfers is None else Fraction(exact_transfers[name])
                if float(quantity) != value:
                    return dict(accepted=False,exact=False,reason='exact transfers disagree with plan')
                point.append(quantity)
            exact = c.problem.accepts(point)
        except (ArithmeticError,BranchRejected):
            pass
        membership = report.feasible_level_upper_bound
        if exact:
            reference, candidate = coordinates(scenario.data),coordinates(scenario.data,plan)
            candidate['L'] = {name:rational(value) for name,value in candidate['L'].items()}
            candidate['L'].update(zip(c.problem.variables,point))
            reference['L'] = {name:rational(value) for name,value in reference['L'].items()}
            membership = next(k for k in range(5) if all(
                candidate[a][name] == reference[a][name]
                for a,keys in _releases(scenario,k,diagnostic).items()
                for name in reference[a] if name not in keys))
        return dict(accepted=True,exact=exact,level=membership,
                    numerical_level=report.feasible_level_upper_bound,
                    scenario_hash=report.scenario_hash,candidate_hash=report.candidate_hash,
                    numerical_model='Simulator predicate tolerance 1e-9; exact flag requires rational primal checks.')
    except (ValueError,KeyError,TypeError,ArithmeticError) as error:
        return dict(accepted=False,exact=False,reason=str(error))


@dataclass
class SearchCursor:
    """Live continuation state; serialized counters are replay positions only."""
    scenario_hash: str
    library_hash: str
    level: int
    releases: dict
    iterator: object
    nodes: int = 0
    branches: int = 0
    complete: bool = False
    evidence: list = field(default_factory=list)
    witness: dict | None = None
    feasible: int = 0
    exact_feasible: int = 0
    budgets: list = field(default_factory=list)
    retry_branches: dict = field(default_factory=dict)
    retry_options: dict = field(default_factory=dict)
    retry_attempts: int = 0


@dataclass(frozen=True)
class LevelResult:
    status: str
    cursor: SearchCursor
    _snapshot: dict = field(init=False,repr=False)

    def __post_init__(self):
        object.__setattr__(self,'_snapshot',self._capture())

    def to_dict(self):
        return json.loads(json.dumps(self._snapshot,allow_nan=False))

    def _capture(self):
        c = self.cursor
        return dict(version='recovery-level-v1',status=self.status,level=c.level,
                    scenario_hash=c.scenario_hash,representation_hash=c.library_hash,
                    enumeration_complete=c.complete,nodes=c.nodes,branches=c.branches,
                    retry_attempts=c.retry_attempts,
                    feasible_branches=c.feasible,exact_feasible_branches=c.exact_feasible,
                    excluded_branches=sum(e['outcome'] in ('EMPTY','REJECTED') for e in c.evidence),
                    unresolved_branches=sum(e['outcome']=='UNRESOLVED' for e in c.evidence),
                    cursor=dict(nodes=c.nodes,next_branch=c.branches,live_continuation_only=True),
                    budgets=list(c.budgets),branch_evidence=list(c.evidence),witness=c.witness)


def _process_branch(scenario,library,level,releases,plan,reserves,options):
    try:
        try:
            compiled = build_transfer_problem(scenario,plan,reserves,releases,exact=True)
        except UnsupportedArithmetic:
            compiled = build_transfer_problem(scenario,plan,reserves,releases,exact=False)
        lp = solve_linear(compiled.problem,**options)
        if lp.status == 'EMPTY':
            return dict(outcome='EMPTY',exact=True,certificate=lp.certificate),None
        if lp.status != 'WITNESS':
            return dict(outcome='UNRESOLVED',exact=False,reason=lp.reason),None
        candidate = materialize(compiled,lp.values)
        fractions = dict(zip(compiled.problem.variables,map(str,lp.values))) if lp.exact else None
        validation = verify_witness(scenario,library,candidate,reserves,level,exact_transfers=fractions)
        if not validation['accepted']:
            return dict(outcome='UNRESOLVED',exact=False,reason='candidate validation: '+validation['reason']),None
        witness = dict(plan=candidate,reserve_paths=reserves,exact=validation['exact'],
                       exact_transfers=fractions,validation=validation)
        return dict(outcome='WITNESS',exact=validation['exact']),witness
    except BranchRejected as error:
        return dict(outcome='REJECTED' if error.exact else 'UNRESOLVED',exact=error.exact,reason=str(error)),None
    except (ArithmeticError,ValueError) as error:
        return dict(outcome='UNRESOLVED',exact=False,reason=f'arithmetic or candidate unavailable: {error}'),None


def search_level(scenario,library,level, *, max_nodes=100000,max_branches=2000,
                 max_operations=10000,max_rows=2000,max_iterations=10000,numerical=True,
                 exhaustive=False,cursor=None,_diagnostic=None):
    level = int(_level(level))
    budgets = dict(max_nodes=max_nodes,max_branches=max_branches,max_operations=max_operations,
                   max_rows=max_rows,max_iterations=max_iterations)
    if any(isinstance(v,bool) or not isinstance(v,int) or v<0 for v in budgets.values()):
        raise ValueError('search budgets must be nonnegative integers')
    library.validate(scenario)
    diagnostic = diagnose_wind_update(scenario) if _diagnostic is None else _diagnostic
    releases = _releases(scenario,level,diagnostic)
    if cursor is None:
        cursor = SearchCursor(scenario.content_hash(),library.content_hash(),level,releases,
                              iter(enumerate_events(scenario,library,releases)))
    elif (not isinstance(cursor,SearchCursor) or cursor.scenario_hash != scenario.content_hash()
          or cursor.library_hash != library.content_hash() or cursor.level != level
          or cursor.releases != releases):
        raise ValueError('cursor does not match this scenario, representation and level')
    cursor.budgets.append({**budgets,'numerical':numerical,'exhaustive':exhaustive})
    start_nodes = cursor.nodes
    attempts = retries = 0
    options = dict(max_operations=max_operations,max_rows=max_rows,max_iterations=max_iterations,numerical=numerical)
    option_key = tuple(options.items())

    def process(index,event):
        plan,reserves = event
        evidence,witness = _process_branch(scenario,library,level,releases,plan,reserves,options)
        record = dict(index=index,branch_hash=_hash(event),**evidence)
        if index < len(cursor.evidence):
            cursor.evidence[index] = record
        else:
            cursor.evidence.append(record)
        if evidence['outcome']=='UNRESOLVED':
            cursor.retry_branches[index] = event
            cursor.retry_options[index] = option_key
        else:
            cursor.retry_branches.pop(index,None)
            cursor.retry_options.pop(index,None)
        if witness is not None:
            cursor.feasible += 1
            cursor.exact_feasible += int(witness['exact'])
            if cursor.witness is None or (witness['exact'] and not cursor.witness['exact']):
                cursor.witness = witness

    # Retry when LP settings change. Repeating an identical unsuccessful attempt
    # would let a permanently irrational branch starve unexamined branches.
    for index,event in tuple(cursor.retry_branches.items()):
        if cursor.retry_options[index] == option_key:
            continue
        if retries >= max_nodes or attempts >= max_branches or (not exhaustive and cursor.witness is not None):
            break
        process(index,event)
        retries += 1
        attempts += 1
        cursor.retry_attempts += 1
    while not cursor.complete and (exhaustive or cursor.witness is None):
        if cursor.nodes-start_nodes+retries >= max_nodes or attempts >= max_branches:
            break
        try:
            event = next(cursor.iterator)
        except StopIteration:
            cursor.complete = True
            break
        cursor.nodes += 1
        if event is None:
            continue
        process(cursor.branches,event)
        cursor.branches += 1
        attempts += 1
    status = ('WITNESS' if cursor.witness is not None else 'EMPTY'
              if cursor.complete and all(e['outcome'] in ('EMPTY','REJECTED') for e in cursor.evidence)
              else 'UNRESOLVED')
    return LevelResult(status,cursor)


def verify_level_evidence(scenario,library,report):
    """Replay enumeration and verify every exact exclusion, without trusting LP status."""
    try:
        if (report['status'] != 'EMPTY' or not report['enumeration_complete']
            or report['scenario_hash'] != scenario.content_hash()
            or report['representation_hash'] != library.content_hash()):
            return False
        diagnostic = diagnose_wind_update(scenario)
        releases = _releases(scenario,report['level'],diagnostic)
        records = report['branch_evidence']
        count = nodes = 0
        for event in enumerate_events(scenario,library,releases):
            nodes += 1
            if nodes > report['nodes']:
                return False
            if event is None:
                continue
            if count >= len(records):
                return False
            record = records[count]
            if record['index'] != count or record['branch_hash'] != _hash(event) or not record['exact']:
                return False
            plan,reserves = event
            try:
                c = build_transfer_problem(scenario,plan,reserves,releases,exact=True)
            except BranchRejected as error:
                if record['outcome'] != 'REJECTED' or record['reason'] != str(error):
                    return False
            else:
                if record['outcome'] != 'EMPTY' or not verify_exclusion(c.problem,record['certificate']):
                    return False
            count += 1
        return count == len(records) == report['branches'] and nodes == report['nodes']
    except (ValueError,KeyError,TypeError,ArithmeticError):
        return False


def _previous_premise(scenario):
    """Distinguish the simulator's input premise from exact-decimal feasibility."""
    payload = scenario.to_dict()
    payload['wind']['received']['values'] = payload['wind']['previous']['values']
    payload['wind']['update_support'] = []
    previous = Scenario.from_dict(payload)
    try:
        c = build_transfer_problem(previous,payload['incumbent'],payload['reserve_paths'],
                                   release_sets(previous,0),exact=True)
        feasible = c.problem.accepts(())
        reason = None if feasible else 'Incumbent violates an exact normalized-decimal resource constraint.'
    except BranchRejected as error:
        feasible,reason = False,str(error)
    except ArithmeticError as error:
        feasible,reason = None,str(error)
    return dict(numerical_feasible=True,exact_feasible=feasible,reason=reason)


def recover(scenario,library, *, exhaustive=False,total_nodes=500000,
            total_branches=None,strategy='ascending',**budgets):
    """Search ascending scopes or Level 4 under shared work ceilings.

    ``max_branches`` remains a per-scope cap for backward compatibility;
    ``total_branches`` additionally caps all actual branch attempts together.
    """
    if isinstance(total_nodes,bool) or not isinstance(total_nodes,int) or total_nodes<0:
        raise ValueError('total_nodes must be a nonnegative integer')
    if total_branches is not None and (isinstance(total_branches,bool)
            or not isinstance(total_branches,int) or total_branches<0):
        raise ValueError('total_branches must be a nonnegative integer or None')
    if strategy not in ('ascending','level4'):
        raise ValueError('strategy must be ascending or level4')
    library.validate(scenario)
    diagnostic = diagnose_wind_update(scenario)
    levels,seen = [],{}
    witness = None
    empty,upper,numerical_upper = set(),None,None
    remaining = total_nodes
    branches_used = 0
    for level in (range(5) if strategy=='ascending' else (4,)):
        key = _scope_key(_releases(scenario,level,diagnostic))
        if key in seen:
            original = seen[key]
            r = {**original,'level':level,'equivalent_to':original['level']}
        else:
            options = {**budgets,'max_nodes':min(remaining,budgets.get('max_nodes',100000))}
            if total_branches is not None:
                options['max_branches'] = min(total_branches-branches_used,budgets.get('max_branches',2000))
            result = search_level(scenario,library,level,exhaustive=exhaustive,_diagnostic=diagnostic,**options)
            r = result.to_dict()
            remaining -= r['nodes']
            branches_used += r['branches']
            seen[key] = r
        levels.append(r)
        if r['status'] == 'EMPTY':
            empty.update(range(level+1))
        if r['witness'] is not None:
            w = r['witness']
            k = w['validation']['level']
            if w['exact']:
                if upper is None or k<upper:
                    upper,witness = k,w
            else:
                numerical_upper = k if numerical_upper is None else min(k,numerical_upper)
                if witness is None:
                    witness = w
            if not exhaustive:
                break
    lower = None if 4 in empty else 1+max(empty,default=-1)
    if upper is not None:
        status = 'MINIMUM_CERTIFIED_R' if lower==upper else 'WITNESS_WITH_GAP_R'
    elif numerical_upper is not None:
        status = 'NUMERICAL_WITNESS_R'
    elif 4 in empty:
        status = 'NO_CONTINUATION_R'
    else:
        status = 'UNRESOLVED_R'
    return dict(version='recovery-search-v1',status=status,strategy=strategy,scenario_hash=scenario.content_hash(),
                representation_hash=library.content_hash(),representation=library.to_dict(),
                previous_premise=_previous_premise(scenario),
                affected_tasks=sorted(diagnostic.affected_tasks),neighborhood=sorted(diagnostic.neighborhood),
                total_node_budget=total_nodes,nodes_used=total_nodes-remaining,
                total_branch_budget=total_branches,branches_used=branches_used,
                lower_bound=lower,upper_bound=upper,numerical_upper_bound=numerical_upper,
                certified_empty_levels=sorted(empty),levels=levels,witness=witness,
                claim='Exact bounds concern this finite path representation and the fixed operation protocol. '
                      'They concern received-wind feasible sets; previous_premise separately reports whether '
                      'the incumbent qualifies as an exact feasible-before-update benchmark. '
                      'Numerical witnesses use simulator tolerances and do not certify an exact upper bound.',
                arithmetic='Normalized JSON decimals interpreted as rationals; unsupported radicals use numerical proposals.')
