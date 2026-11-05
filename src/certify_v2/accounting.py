"""CPU-time budget and exclusive per-category accounting.

Budgets follow the comparison protocol (F2): process CPU time, checked between
operations; the overrun of the last operation is recorded, never hidden.
"""
from contextlib import contextmanager
from time import perf_counter, process_time

CATEGORIES = ('setup', 'bounds', 'paths', 'route', 'search', 'exact', 'other')


class BudgetExpired(RuntimeError):
    pass


class Clock:
    """One CPU budget per run; categories are exclusive (a nested call pauses its parent)."""

    def __init__(self, budget_s=None):
        self.budget_s = budget_s
        self.start_cpu, self.start_wall = process_time(), perf_counter()
        self.spent = dict.fromkeys(CATEGORIES, 0.)
        self._stack = []
        self._mark = self.start_cpu

    def cpu(self):
        return process_time()-self.start_cpu

    def wall(self):
        return perf_counter()-self.start_wall

    def remaining(self):
        return None if self.budget_s is None else self.budget_s-self.cpu()

    def expired(self):
        return self.budget_s is not None and self.cpu() >= self.budget_s

    def check(self):
        if self.expired():
            raise BudgetExpired()

    def _switch(self):
        now = process_time()
        if self._stack:
            self.spent[self._stack[-1]] += now-self._mark
        else:
            self.spent['other'] += now-self._mark
        self._mark = now

    @contextmanager
    def charge(self, category):
        self._switch()
        self._stack.append(category)
        try:
            yield
        finally:
            self._switch()
            self._stack.pop()

    def summary(self):
        self._switch()
        return dict(cpu_s=self.cpu(), wall_s=self.wall(), budget_s=self.budget_s,
                    overrun_s=max(0., self.cpu()-self.budget_s) if self.budget_s is not None else 0.,
                    categories=dict(self.spent))
