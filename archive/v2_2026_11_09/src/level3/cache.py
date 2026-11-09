"""Scenario-scoped immutable continuous evidence with per-search views.

Lower certificates depend only on canonical requests, never on assignment or
cache insertion order. Numerical curves are generated separately. Every caller
receives copies and every view records only the query evidence it consumed.
"""
from copy import deepcopy
from fractions import Fraction
from time import perf_counter

from continuous.oracle import ContinuousOracle, verify_query
from continuous.potential import propose_potential, uniform_certificate, verify_potential
from recovery.local_search import digest


def _effort():
    return dict(queries=0, cache_hits=0, path_s=0., bound_s=0., conic_paths=0, potential_fields=0)


class SharedContinuousCache:
    def __init__(self, scenario, *, refinements=(2, 4), digits=18, initial_bounds=()):
        self.scenario = scenario
        self.scenario_hash = scenario.content_hash()
        self.refinements, self.digits = tuple(refinements), digits
        self._oracle = ContinuousOracle(scenario, refinements, digits)
        self._lower, self._queries, self._seeds = {}, {}, {}
        self.effort = _effort()
        d = scenario.data
        self._warm = {uid: [*d['incumbent']['routes'][uid]['paths'], *d['reserve_paths'].get(uid, {}).values()]
                      for uid in d['state']['fleet']}
        for q in initial_bounds:
            if not verify_query(scenario, q, digits):
                raise ValueError('invalid continuous cache seed')
            key = self._key(q['uid'], q['start'], q['goal'])
            self._seeds.setdefault(key, {})[digest(q)] = deepcopy(q)

    def check_scenario(self, scenario):
        if scenario.content_hash() != self.scenario_hash:
            raise ValueError('shared cache belongs to a different original scenario')

    def _key(self, uid, start, goal):
        if uid not in self.scenario.data['state']['fleet']:
            raise ValueError('unknown cache UAV')
        return uid, tuple(start), tuple(goal)

    def lower(self, uid, start, goal):
        key = self._key(uid, start, goal)
        if key not in self._lower:
            begin = perf_counter()
            candidates = [(Fraction(0), '', None)]
            for q in self._seeds.get(key, {}).values():
                if q['lower_certificate'] is not None:
                    candidates.append((Fraction(q['lower']), digest(q['lower_certificate']), q['lower_certificate']))
            if tuple(start) != tuple(goal):
                try:
                    if self._oracle.uniform:
                        fields = [uniform_certificate(self.scenario, uid, start, goal, self.digits)]
                    else:
                        fields = []
                        for r in self.refinements:
                            try:
                                fields.append(propose_potential(self.scenario, uid, start, goal, r, self.digits))
                                self.effort['potential_fields'] += 1
                            except (ValueError, ArithmeticError):
                                pass
                    for field in fields:
                        if verify_potential(self.scenario, uid, field):
                            candidates.append((Fraction(field['lower']), digest(field), field))
                except (ValueError, ArithmeticError):
                    pass
            lower, _, field = max(candidates, key=lambda item: (item[0], item[1]))
            self._lower[key] = dict(kind='global_leg_lower_v1', uid=uid, start=list(start), goal=list(goal),
                                    lower=str(lower), lower_certificate=deepcopy(field))
            self.effort['bound_s'] += perf_counter()-begin
        return deepcopy(self._lower[key])

    def _query(self, uid, start, goal):
        key = self._key(uid, start, goal)
        self.effort['queries'] += 1
        hit = key in self._queries
        if hit:
            self.effort['cache_hits'] += 1
        else:
            begin = perf_counter()
            seeds = [q['path'] for _, q in sorted(self._seeds.get(key, {}).items())]
            # Warm paths are canonical original inputs, independent of other
            # assignments and of which unrelated request was evaluated first.
            q = self._oracle.query(uid, start, goal, [*self._warm[uid], *seeds], bound=False)
            b = self.lower(uid, start, goal)
            q.update(lower=b['lower'], lower_certificate=b['lower_certificate'], bound_attempted=True,
                     gap=str(Fraction(q['upper'])-Fraction(b['lower'])))
            if not verify_query(self.scenario, q, self.digits):
                raise ArithmeticError('shared query failed independent evidence replay')
            self._queries[key] = deepcopy(q)
            self.effort['path_s'] += perf_counter()-begin
        return deepcopy(self._queries[key]), hit

    def view(self):
        return _EvidenceView(self)


class _EvidenceView:
    def __init__(self, parent):
        self._parent = parent
        self.scenario, self.refinements, self.digits = parent.scenario, parent.refinements, parent.digits
        self.cache, self.effort = {}, _effort()

    def query(self, uid, start, goal, warm_paths=(), *, bound=True):
        before = deepcopy(self._parent.effort)
        q, hit = self._parent._query(uid, start, goal)
        for k in self.effort:
            self.effort[k] += self._parent.effort[k]-before[k]
        key = uid, tuple(start), tuple(goal)
        self.cache[key] = deepcopy(q)
        return deepcopy(q)
