"""CMI ladder v2 and the progressive (proof-free) baseline PH.

CMI (plan Section 6): Level 0 first, then rounds over the open levels from the
lowest one up. In round r the lowest open level advances its full search for a slice
of ``base * 2**r`` CPU seconds, and every open level from Level 2 up (the lowest
included) advances a plan-only search for a quarter of that, so a level that cannot
be decided quickly leaves time for plan searches and is resumed later. A proof at level k closes
every level up to k; a plan at level j closes every level above j. The run stops
when the minimum is certified, no continuation is proven, no open level is left
or the CPU budget is spent. Every bound change is logged with its CPU time.

PH (comparison protocol, Section 3): the same plan searches with proofs switched
off, one level at a time from Level 0, each with a fixed share of the budget.
"""
from recovery.local_search import bounds
from .accounting import BudgetExpired, Clock
from .levels import Instance
from .metrics import plan_decisions

PH_SHARES = (0.05, 0.15, 0.2, 0.3, 0.3)


def _advance(generator, clock, until):
    """Run a search until it finishes or ``until`` CPU seconds; return its result or None."""
    while clock.cpu() < until:
        clock.check()
        try:
            with clock.charge('search'):
                next(generator)
        except StopIteration as stop:
            return stop.value
    return None


def _summary(instance, clock, excluded, upper, best, events, status, arm):
    result = dict(version='certify-v2-run', arm=arm, bounds=bounds(excluded, upper), events=events,
                  level_status=status, affected=instance.true_u0, mask_u0=instance.u0,
                  plan=None, plan_level=upper, clock=clock.summary(), effort=dict(instance.effort))
    if best is not None:
        result['plan'] = best
    levels = sorted(instance.contexts)
    contexts = [instance.shared] if instance.shared is not None else [instance.contexts[k] for k in levels]
    result['context_levels'] = None if instance.shared is not None else levels
    result['effort'].update(table={}, oracle={})
    for ctx in contexts:
        for key, value in ctx.table.effort.items():
            result['effort']['table'][key] = result['effort']['table'].get(key, 0)+value
        for key, value in ctx.oracle.effort.items():
            result['effort']['oracle'][key] = result['effort']['oracle'].get(key, 0)+value
    if instance.config['proofs']:
        result['evidence'] = [ctx.evidence.export() for ctx in contexts]
        result['records'] = instance.records
    return result


def _outside(scenario, best, instance):
    """UAVs outside U0 whose stops, paths or quantities the plan changes (mu)."""
    return plan_decisions(scenario, best['witness'], instance.true_u0)['uavs_changed_outside_u0']


def run_cmi(scenario, budget_s, config=None, *, u0=None, arm='CMI', base_slice=0.25, table=None, excluded=None,
            explore=0.25, mu_refine=False):
    """``table`` and ``excluded`` serve the XR study only: a flight-time table of the same
    wind and exclusions transferred from a looser deadline variant of the same mission.

    ``mu_refine`` (CMI-mu): once the minimum is certified at Level 3 or 4, the remaining budget
    lowers mu, the UAVs outside U0 the plan changes. Level 3 is searched at helper allowances
    b = lower, lower+1, ... below the plan's mu (lower = 0 at Level 3; at Level 4 the scenario's
    allowance plus one, since Level 3 is excluded there). A plan at b replaces the returned one
    (same level, mu <= b) and ends the step; a proof raises the lower bound to b+1; an open
    search ends the step. ``mu_bounds`` is the resulting bracket on the minimum mu."""
    clock = Clock(budget_s)
    transferred = sorted(excluded or ())
    excluded, upper, best, events = set(transferred), None, None, []
    if transferred:
        events.append(dict(kind='transfer', level=max(transferred), cpu_s=0.))
    status = {k: 'pending' for k in range(5)}
    proofs, mu, mu_proofs = {}, None, {}
    try:
        with clock.charge('setup'):
            instance = Instance(scenario, clock, config, u0=u0, table=table)
    except BudgetExpired:
        raise
    searches = {}

    def lower():
        return next((k for k in range(5) if k not in excluded), 5)

    def handle(k, outcome):
        nonlocal upper, best
        kind, value = outcome
        if kind == 'proof':
            status[k] = 'proof'
            proofs[k] = value
            for j in range(k+1):
                excluded.add(j)
            events.append(dict(kind='proof', level=k, cpu_s=clock.cpu(), wall_s=clock.wall()))
        elif kind == 'plan':
            witness, level = value
            # The plan must lie in a patch of the searching level (this run's masks); its
            # level is scored with the true U0, so under noAF it can be higher than k.
            if level is None or witness['patch']['level'] > k:
                raise ValueError('plan outside the level that produced it')
            if level in excluded:
                raise ValueError(f'plan at level {level} contradicts a proof')
            status[k] = 'plan'
            events.append(dict(kind='plan', level=level, cpu_s=clock.cpu(), wall_s=clock.wall()))
            if upper is None or level < upper:
                upper, best = level, dict(witness=witness, level=level, found_by=k, cpu_s=clock.cpu())
        else:
            status[k] = 'open'
            events.append(dict(kind='open', level=k, reason=value, cpu_s=clock.cpu()))

    rounds = 0
    plan_only = {}      # plan searches above the lowest open level (no proofs, as PH)
    try:
        # Level 0 to completion first: it is one exact check and one bound check.
        if 0 not in excluded:
            searches[0] = instance.search(0)
            outcome = _advance(searches[0], clock, float('inf'))
            handle(0, outcome)
        while True:
            low = lower()
            if low == 5 or (upper is not None and upper <= low):
                break
            active = [k for k in range(low, 5 if upper is None else upper) if status[k] in ('pending', 'running')]
            if not active:
                break
            slice_s = base_slice*2**min(rounds, 30)
            worked = False
            for k in active:
                if k in excluded or (upper is not None and k >= upper) or status[k] not in ('pending', 'running'):
                    continue
                status[k] = 'running'
                first = next((j for j in range(lower(), 5) if status[j] in ('pending', 'running')), None)
                if k >= 2 and instance.config['proofs'] and plan_only.get(k) != 'done':
                    # Plans only, a quarter of the slice, so an upper bound appears early; also at the
                    # lowest open level, whose full search reaches plans only after its route checks.
                    if k not in plan_only:
                        plan_only[k] = instance.search(k, proofs=False)
                    outcome = _advance(plan_only[k], clock, clock.cpu()+slice_s*explore)
                    worked = True
                    if outcome is not None:
                        if outcome[0] == 'plan':
                            handle(k, outcome)
                        else:
                            plan_only[k] = 'done'
                            events.append(dict(kind='plan_search_exhausted', level=k, cpu_s=clock.cpu()))
                if (k == first or k <= 1 or not instance.config['proofs']) and status[k] == 'running':
                    # The lowest level still being decided: its full search (proofs and plans), the whole slice.
                    if k not in searches:
                        searches[k] = instance.search(k)
                    outcome = _advance(searches[k], clock, clock.cpu()+slice_s)
                    worked = True
                    if outcome is not None:
                        handle(k, outcome)
            if not worked:
                break
            rounds += 1
        if mu_refine and upper in (3, 4) and lower() == upper:
            outside = len(set(instance.fleet)-set(instance.u0))
            mu = dict(lower=0 if upper == 3 else min(scenario.data['hierarchy']['helper_budget'], outside)+1,
                      upper=_outside(scenario, best, instance))
            if mu['upper'] < mu['lower']:
                raise ValueError('plan changes fewer outside UAVs than the excluded allowance permits')
            for b in range(mu['lower'], mu['upper']):
                kind, value = _advance(instance.level3(allowance=b), clock, float('inf'))
                if kind == 'proof':
                    mu_proofs[b] = value
                    mu['lower'] = b+1
                    events.append(dict(kind='mu_proof', allowance=b, cpu_s=clock.cpu()))
                elif kind == 'plan':
                    witness, level = value
                    if level != upper:
                        raise ValueError('allowance plan outside the certified level')
                    best = dict(witness=witness, level=level, found_by='mu', allowance=b, cpu_s=clock.cpu())
                    mu['upper'] = _outside(scenario, best, instance)
                    if mu['upper'] < mu['lower']:
                        raise ValueError('allowance plan contradicts an allowance proof')
                    events.append(dict(kind='mu_plan', allowance=b, cpu_s=clock.cpu(), wall_s=clock.wall()))
                    break
                else:
                    events.append(dict(kind='mu_open', allowance=b, reason=value, cpu_s=clock.cpu()))
                    break
    except BudgetExpired:
        pass
    for k in range(5):
        if status[k] in ('running', 'pending'):
            status[k] = ('excluded' if k in excluded else 'above_plan' if upper is not None and k > upper
                         else 'budget' if status[k] == 'running' else 'not_started')
    result = _summary(instance, clock, excluded, upper, best, events, status, arm)
    result['level_proofs'] = proofs
    if mu is not None:
        result['mu_bounds'] = dict(mu, minimum=mu['lower'] if mu['lower'] == mu['upper'] else None)
        result['mu_proofs'] = mu_proofs
    if transferred:
        result['transferred'] = transferred
    if table is not None or arm == 'XR':
        result['_table'] = instance.context(0).table
    return result


def run_ph(scenario, budget_s, config=None, *, shares=PH_SHARES, arm='PH', guaranteed=False):
    """Progressive search without proofs: Levels 0-4 in order, fixed CPU shares.

    PH-strict passes ``fixed_exclusions=False``, so Levels 0-1 are also left without proofs.
    Shares are cumulative deadlines; with ``guaranteed`` every level also runs for at least its
    own share from its start, so an earlier overrun cannot leave it no time."""
    clock = Clock(budget_s)
    config = {**(config or {}), 'proofs': False}
    excluded, upper, best, events = set(), None, None, []
    status = {k: 'pending' for k in range(5)}
    with clock.charge('setup'):
        instance = Instance(scenario, clock, config)
    end = 0.
    try:
        for k in range(5):
            end += shares[k]*budget_s
            search = instance.search(k)
            status[k] = 'running'
            floor = clock.cpu()+shares[k]*budget_s if guaranteed else clock.cpu()
            outcome = _advance(search, clock, max(end, floor))
            if outcome is None:
                status[k] = 'share'
                events.append(dict(kind='escalate', level=k, reason='share spent', cpu_s=clock.cpu()))
                continue
            kind, value = outcome
            if kind == 'plan':
                witness, level = value
                status[k] = 'plan'
                upper, best = level, dict(witness=witness, level=level, found_by=k, cpu_s=clock.cpu())
                events.append(dict(kind='plan', level=level, cpu_s=clock.cpu(), wall_s=clock.wall()))
                break
            status[k] = 'exhausted'
            events.append(dict(kind='escalate', level=k, reason=value, cpu_s=clock.cpu()))
    except BudgetExpired:
        pass
    return _summary(instance, clock, excluded, upper, best, events, status, arm)
