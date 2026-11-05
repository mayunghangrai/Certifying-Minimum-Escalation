"""A8: MS and SC mission generators (design 7.1-7.3, 9).

A slot is filled by draws: new geometry every 12 draws, up to 192 draws
(stages of 48, recorded), every draw logged, the slack ranges never changed.
A failed slot is kept and reported, never replaced. Block size follows a Latin
schedule over the four between-mission factors, so each size covers 27 of the
81 MS cells and is balanced against every factor.
"""
from fractions import Fraction as F
from itertools import product

from env.scenario import Scenario
from .admission import admit
from .missions import build_mission
from .seeds import stable_seed
from .snapshots import build_snapshot
from .update import apply_magnitude, place_block

FLEETS, TASKS_PER_UAV = (6, 9, 12), (2, 3, 4)
SLACKS, BETAS = ('tight', 'medium', 'loose'), ('tight', 'medium', 'ample')
LAYOUTS = ('uniform', 'uniform', 'clustered', 'clustered')
SIZES = (1, 4, 9)
RATIOS = (0.4, 0.6, 0.8)
MS_TIMES = (F(0), F(1, 4), F(1, 2))
SC_CELLS = ((48, 8), (48, 12), (48, 16), (64, 8), (64, 12), (64, 16), (96, 12), (96, 16))
GEOMETRY_EVERY, STAGE, MAX_DRAWS = 12, 48, 192


def ms_cells():
    cells = []
    for (a, m), (b, k), (c, slack), (d, beta) in product(*(enumerate(x) for x in (FLEETS, TASKS_PER_UAV, SLACKS, BETAS))):
        cells.append(dict(m=m, n=m*k, slack=slack, beta=beta, size=SIZES[(a + b + c + d) % 3],
                          key=f'MS|m{m}|k{k}|{slack}|{beta}'))
    return cells


def sc_cells():
    return [dict(m=m, n=n, slack='medium', beta='medium', key=f'SC|n{n}|m{m}') for n, m in SC_CELLS]


def fill_slot(base_seed, cell, slot, family, coefficients, *, iterations=2000, max_draws=MAX_DRAWS):
    """Draw until one mission is admitted or the draw limit is reached."""
    key = f"{cell['key']}|slot{slot}"
    log = []
    for draw in range(max_draws):
        seed = stable_seed(base_seed, 'draw', key, draw)
        entry = dict(draw=draw, stage=draw//STAGE + 1, seed=seed,
                     geometry_seed=stable_seed(base_seed, 'geometry', key, draw//GEOMETRY_EVERY))
        try:
            mission, info = build_mission(seed, m=cell['m'], n=cell['n'], family=family, slack=cell['slack'],
                                          beta=cell['beta'], coefficients=coefficients, iterations=iterations,
                                          geometry_seed=entry['geometry_seed'])
            block = place_block(mission, seed, cell['size'])
            entry.update(admit(mission, block))
        except ValueError as error:
            entry.update(admitted=False, reason=str(error))
        log.append(entry)
        if entry['admitted']:
            return dict(key=key, family=family, mission=mission, info=info, block=block, log=log)
    return dict(key=key, family=family, mission=None, log=log)


def variants(mission, block, ratios=RATIOS, times=MS_TIMES):
    """The paired (r, t_u) variants of one admitted mission; all share the block."""
    payload = mission.to_dict()
    out = []
    for r in ratios:
        for fraction in times:
            if fraction == 0:
                variant, provenance = Scenario(apply_magnitude(payload, block, r)).to_dict(), None
            else:
                variant, provenance = build_snapshot(payload, block, r, block['tau']*float(fraction))
            out.append(dict(r=r, t_u=str(fraction), payload=variant, provenance=provenance))
    return out


def ms_slots():
    """(cell, slot, family) for the 324 MS missions."""
    return [(cell, slot, family) for cell in ms_cells() for slot, family in enumerate(LAYOUTS)]


def sc_slots(missions_per_cell=15):
    """Within each size cell, block sizes 1/4/9 by mission index (5 each of 15)."""
    return [(dict(cell, size=SIZES[slot % 3]), slot, ('uniform', 'clustered')[slot % 2])
            for cell in sc_cells() for slot in range(missions_per_cell)]
