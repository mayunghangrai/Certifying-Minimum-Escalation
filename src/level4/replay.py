"""Independent Level-4 replay against the one original global scope mask."""
from level3.replay import _replay_assignments


def replay_tree(scenario, report):
    """Verify all global assignment children and every attached sequence proof."""
    return _replay_assignments(scenario, report, 4)


def verify_tree(scenario, report):
    return replay_tree(scenario, report)['valid']


replay_level4 = replay_tree
verify_level4 = verify_tree
