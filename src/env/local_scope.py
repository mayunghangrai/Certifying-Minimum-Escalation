"""Revised scope contract: directed affected fleet and a union of helper patches.

Shared resource predicates constrain every candidate, but never grant permission
to edit another UAV. Reserve witnesses are auxiliary and are absent from A/S/P/L.
"""
from dataclasses import dataclass
from itertools import combinations
from fractions import Fraction

from .intervention_scope import _level
from .plan import COMPONENTS, coordinates


def require_v2(scenario):
    if scenario.data['schema_version'] not in ('wind-benchmark-v2', 'wind-benchmark-v3'):
        raise ValueError('local scope requires wind-benchmark-v2 or v3')


@dataclass(frozen=True)
class ScopePatch:
    participants: tuple
    releases: dict

    def to_dict(self):
        return dict(participants=list(self.participants),
                    releases={a:sorted(v) for a,v in self.releases.items()})


def scope_family(scenario, level, u0, helper_budget=None):
    """Maximal patches cover every eligible smaller patch by set inclusion.

    Exhausting one patch cannot exclude the union. Even b=0 permits assignment
    changes among U0; the helper policy is independent of assignment permission.
    ``helper_budget`` overrides the scenario's allowance b at Level 3 (CMI-mu refinement).
    """
    require_v2(scenario)
    level = _level(level)
    data = scenario.data
    fleet, u0 = set(data['state']['fleet']), set(u0)
    if not u0 <= fleet:
        raise ValueError('unknown affected UAV')
    if level == 4:
        groups = [fleet]
    elif level == 3:
        outsiders = sorted(fleet-u0)
        b = min(data['hierarchy']['helper_budget'] if helper_budget is None else helper_budget, len(outsiders))
        groups = [u0 | set(extra) for extra in combinations(outsiders, b)]
    else:
        groups = [u0 if level else set()]
    old = coordinates(data)
    mutable = {a:set(old[a])-set(data['commitments'][a]) for a in COMPONENTS}
    family = []
    for participants in groups:
        released = {a:frozenset() for a in COMPONENTS}
        for a in ('P',) if level == 1 else ('S','P','L') if level >= 2 else ():
            released[a] = frozenset(k for k in mutable[a] if k.split(':')[0] in participants)
        if level >= 3:
            released['A'] = frozenset(i for i in mutable['A']
                                      if old['A'][i] is None or old['A'][i] in participants)
        family.append(ScopePatch(tuple(sorted(participants)),released))
    return tuple(family)


def patch_contains(scenario, candidate_coordinates, patch):
    old = coordinates(scenario.data)
    def equal(a,k):
        if a == 'L':
            return Fraction(str(candidate_coordinates[a][k])) == Fraction(str(old[a][k]))
        return candidate_coordinates[a][k] == old[a][k]
    return all(equal(a,k)
               for a in COMPONENTS for k in old[a] if k not in patch.releases[a])


def scope_membership(scenario, candidate_coordinates, level, u0):
    """Coordinate membership only; callers must check the common domain Y."""
    return any(patch_contains(scenario,candidate_coordinates,p)
               for p in scope_family(scenario,level,u0))


def affected_uavs(scenario, diagnostic):
    """Trace one directed changed-atom path to an owned evaluation per UAV."""
    require_v2(scenario)
    paths, traces, counts = {}, {}, {}
    for key,node in diagnostic.graph.nodes.items():
        if key in diagnostic.changed_atoms:
            paths[key] = [key]
        elif key in diagnostic.structural_closure:
            parent = next((p for p in node.parents if p in paths), None)
            if parent is not None:
                paths[key] = paths[parent]+[key]
        if key in diagnostic.structural_closure and node.leg is not None:
            uid = node.leg.split(':')[0]
            if key not in paths:
                raise ValueError('affected owned node lacks a changed-atom trace')
            traces.setdefault(uid, paths[key])
            counts[uid] = counts.get(uid,0)+1
    fleet = len(scenario.data['state']['fleet'])
    return dict(uavs=sorted(traces), count=len(traces), fraction=len(traces)/fleet,
                traces=traces, owned_closure_counts=counts,
                structural_nodes=len(diagnostic.structural_closure),
                material_nodes=len(diagnostic.material_support),
                rule='directed_incumbent_union')


def change_metrics(scenario, plan, u0, *, exact_quantities=None):
    old, new = coordinates(scenario.data), coordinates(scenario.data, plan)
    if exact_quantities:
        from fractions import Fraction
        old['L'] = {k:Fraction(str(v)) for k,v in old['L'].items()}
        new['L'] = {k:Fraction(str(v)) for k,v in new['L'].items()}
        new['L'].update({k:Fraction(v) for k,v in exact_quantities.items()})
    changed = {a:sorted(k for k in old[a] if old[a][k] != new[a][k]) for a in COMPONENTS}
    uavs = {k.split(':')[0] for a in 'SPL' for k in changed[a]}
    fleet = len(scenario.data['state']['fleet'])
    return dict(changed_coordinates=changed, changed_uavs=sorted(uavs),
                changed_uav_count=len(uavs), outside_changed=len(uavs-set(u0)),
                preserved_uavs=fleet-len(uavs), preserved_fraction=(fleet-len(uavs))/fleet,
                assignment_changes=len(changed['A']))


def preservation_metrics(scenario,plan,level,u0,*,exact_quantities=None):
    """Count whole UAV plans fixed by a containing patch's mutable mask.

    Commits are subtracted by scope_family. Report the patch itself so scope
    permission and actual changed plans remain independently inspectable.
    """
    point = coordinates(scenario.data,plan)
    if exact_quantities:
        point['L'].update({k:Fraction(v) for k,v in exact_quantities.items()})
    patch = next(p for p in scope_family(scenario,level,u0) if patch_contains(scenario,point,p))
    released = {key.split(':')[0] for a in 'SPL' for key in patch.releases[a]}
    fixed = set(scenario.data['state']['fleet'])-released
    return dict(level=level,patch=patch.to_dict(),released_uavs=sorted(released),held_fixed_uavs=sorted(fixed),
                held_fixed_count=len(fixed),held_fixed_fraction=len(fixed)/len(scenario.data['state']['fleet']))
