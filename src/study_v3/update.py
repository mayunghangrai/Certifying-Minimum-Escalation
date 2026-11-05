"""A6: the magnitude update F1 (design 4.2; front kinds removed, Q1).

A block of 1, 4 or 9 cells over a run of three bins takes wind of strength
r x 10 m/s (r of the slowest airspeed) in a new direction. The block is placed
on a piece of an incumbent leg into a delivery that the UAV enters at or after
tau/2 under F0, so every update time (0, tau/4, tau/2) still has the
disruption ahead. The nine
(r, t_u) variants of a mission share one block.
"""
from copy import deepcopy
from fractions import Fraction as F

from env.fixed_plan import evaluate_plan
from .seeds import stable_rng
from .wind_model import DIRECTIONS, wire

SLOWEST_MPS = 10
RUN_BINS = 3
GRID = 8


def makespan(scenario):
    evaluation = evaluate_plan(scenario, projection='previous')
    return max(s['time_h'] for s in evaluation.final_states.values()), evaluation


def place_block(scenario, seed, size):
    """Block cells, bins and direction; deterministic for (seed, size)."""
    if size not in (1, 4, 9):
        raise ValueError('block size must be 1, 4 or 9 cells')
    tau, evaluation = makespan(scenario)
    candidates = []
    for uid in sorted(evaluation.records, key=lambda u: int(u[1:])):
        for record in evaluation.records[uid][1:]:
            if record['site'] != 'DEPOT':
                candidates.extend((uid, record['slot'], q['cell_id'], q['bin_index'])
                                  for q in record['wind_queries'] if q['start_h'] >= tau/2)
    if not candidates:
        raise ValueError('no delivery leg is flown after tau/2')
    rng = stable_rng(seed, 'block', size)
    uid, slot, cell, j = rng.choice(candidates)
    side = {1: 1, 4: 2, 9: 3}[size]
    x, y = int(cell[1]), int(cell[2])
    left = min(max(x - rng.randrange(side), 0), GRID - side)
    bottom = min(max(y - rng.randrange(side), 0), GRID - side)
    n_bins = len(scenario.data['wind']['time_knots_s']) - 1
    return dict(cells=[f'C{a}{b}' for a in range(left, left+side) for b in range(bottom, bottom+side)],
                bins=list(range(j, min(j + RUN_BINS, n_bins))), direction=rng.randrange(len(DIRECTIONS)),
                leg=[uid, slot], tau=tau)


def block_vector(block, r):
    dx, dy = DIRECTIONS[block['direction']]
    strength = F(str(r))*SLOWEST_MPS
    return [wire(strength*dx), wire(strength*dy)]


def apply_magnitude(payload, block, r, *, first_bin=0, bin_offset=0):
    """Received wind = previous with the block's bins >= first_bin replaced.

    `bin_offset` maps original bin indices to the payload's (after a snapshot
    has cut the knots at t_u).
    """
    p = deepcopy(payload)
    rows = {c['id']: i for i, c in enumerate(p['wind']['cells'])}
    vector = block_vector(block, r)
    support = []
    for cell in block['cells']:
        for j in block['bins']:
            if j < first_bin:
                continue
            jj = j - bin_offset
            p['wind']['received']['values'][rows[cell]][jj] = list(vector)
            support.append([cell, jj])
    p['wind']['update_support'] = support
    return p


def legs_changing_bin(scenario):
    """Incumbent legs whose bin sequence differs between F0 and F1 (recorded only)."""
    before = evaluate_plan(scenario, projection='previous')
    after = evaluate_plan(scenario, projection='received')
    count = 0
    for uid, records in before.records.items():
        for a, b in zip(records[1:], after.records[uid][1:]):
            if [q['bin_index'] for q in a['wind_queries']] != [q['bin_index'] for q in b['wind_queries']]:
                count += 1
    return count
