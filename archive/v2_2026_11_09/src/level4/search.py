"""One global assignment tree using the shared certified search kernel."""
from level3.search import _search_assignments


def search_level4(scenario, *, max_seconds=60, max_nodes=100000, refinements=(2, 4),
                  digits=18, initial_bounds=(), max_operations=100000, max_rows=10000, cache=None):
    return _search_assignments(scenario, 4, max_seconds=max_seconds, max_nodes=max_nodes,
        refinements=refinements, digits=digits, initial_bounds=initial_bounds,
        max_operations=max_operations, max_rows=max_rows, cache=cache)
