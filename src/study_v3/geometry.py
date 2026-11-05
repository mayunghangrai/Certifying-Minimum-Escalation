"""A3: random_pair geometry scaled to a 10 km region with 8 x 8 cells of 1,250 m."""
from .seeds import stable_rng

HALF = 5000          # region [-5000, 5000]^2 m
CELL = 1250
STEP = 500           # random_pair's 0.1 grid, scaled
AIRSPEEDS = (10, 12.5, 15)
PACKAGES = (1, 2, 3, 4, 5)      # 0.5 to 2.5 kg


def region():
    return [[-HALF, -HALF], [HALF, -HALF], [HALF, HALF], [-HALF, HALF]]


def cells():
    n = 2*HALF//CELL
    return [dict(id=f'C{x}{y}', polygon_xy=[[x*CELL-HALF, y*CELL-HALF], [(x+1)*CELL-HALF, y*CELL-HALF],
                                            [(x+1)*CELL-HALF, (y+1)*CELL-HALF], [x*CELL-HALF, (y+1)*CELL-HALF]])
            for x in range(n) for y in range(n)]


def layout(n, family, seed):
    """Task positions, demands (packages) and stock, as in random_pair."""
    if n < 1 or family not in ('uniform', 'clustered'):
        raise ValueError('invalid layout setting')
    rng = stable_rng(seed, 'geometry', n, family)
    k = HALF//STEP
    grid = [(x*STEP, y*STEP) for x in range(-k, k+1) for y in range(-k, k+1) if (x, y) != (0, 0)]
    if family == 'uniform':
        points = [rng.choice(grid) for _ in range(n)]
    else:
        # random_pair's clusters at (+-0.5, 0) of the unit region.
        def weight(p):
            x, y = p[0]/HALF, p[1]/HALF
            return (1 + 100*min((x+.5)**2 + y*y, (x-.5)**2 + y*y))**-2
        points = rng.choices(grid, weights=[weight(p) for p in grid], k=n)
    demands = [rng.choice(PACKAGES) for _ in range(n)]
    stock = int(sum(demands)*rng.choice((1, 1.25, 1.5)))      # whole packages
    return dict(positions=[list(p) for p in points], demands=demands, stock=stock)


def airspeeds(m):
    return [AIRSPEEDS[j % len(AIRSPEEDS)] for j in range(m)]
