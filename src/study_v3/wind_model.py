"""A2: previous forecast F0 on 8 x 8 cells and 900 s bins (design 4.1).

One prevailing direction (of 12 rational unit vectors) and speed in {0..4} m/s
per mission. Each (cell, bin) scales it by a factor in {1/2, 3/4, 1, 5/4} and
may turn it to a neighbouring direction. Every (cell, bin) draws from its own
seed, so F0 over a longer horizon extends a shorter one unchanged.
"""
from fractions import Fraction as F

from .seeds import stable_rng

# The 12 rational unit vectors in angular order: axes and (3/5, 4/5) turns.
DIRECTIONS = ((F(1), F(0)), (F(4, 5), F(3, 5)), (F(3, 5), F(4, 5)), (F(0), F(1)),
              (F(-3, 5), F(4, 5)), (F(-4, 5), F(3, 5)), (F(-1), F(0)), (F(-4, 5), F(-3, 5)),
              (F(-3, 5), F(-4, 5)), (F(0), F(-1)), (F(3, 5), F(-4, 5)), (F(4, 5), F(-3, 5)))
FACTORS = (F(1, 2), F(3, 4), F(1), F(5, 4))
SPEEDS = (0, 1, 2, 3, 4)
BIN_S = 900


def prevailing(seed):
    rng = stable_rng(seed, 'prevailing')
    return rng.randrange(len(DIRECTIONS)), rng.choice(SPEEDS)


def f0_value(seed, cell, bin_index):
    direction, speed = prevailing(seed)
    rng = stable_rng(seed, 'f0', cell, bin_index)
    factor, turn = rng.choice(FACTORS), rng.choice((-1, 0, 1))
    dx, dy = DIRECTIONS[(direction + turn) % len(DIRECTIONS)]
    return speed*factor*dx, speed*factor*dy


def f0_table(seed, n_cells, n_bins):
    """values[cell][bin] as exact (x, y) in m/s."""
    return [[f0_value(seed, r, j) for j in range(n_bins)] for r in range(n_cells)]


def knots(horizon_s):
    if horizon_s % BIN_S:
        raise ValueError('horizon must be a whole number of 900 s bins')
    return [j*BIN_S for j in range(horizon_s//BIN_S + 1)]


def wire(value):
    """Exact JSON encoding: int, or a 'p/q' string."""
    value = F(value)
    return value.numerator if value.denominator == 1 else f'{value.numerator}/{value.denominator}'
