"""Float leg times for the incumbent search (Q17).

The same walk as `continuous.binned`: legs are split exactly at cell edges once
per ordered pair of points, then flown bin by bin. Only + - * / and square
root are used, in a fixed order, so results are bit-identical across
platforms. Wind beyond the last generated bin is drawn lazily from F0.
"""
import math
from types import SimpleNamespace

from continuous.physics import split_static_path


class FloatLegs:
    def __init__(self, region, cells, wind, bin_s):
        """`wind(cell_index, bin_index)` returns an exact (x, y) vector in m/s."""
        self._shape = SimpleNamespace(data=dict(mission=dict(operating_region_xy=region),
                                                wind=dict(cells=cells)))
        self._wind, self._bin = wind, float(bin_s)
        self._pieces, self._winds = {}, {}

    def _wind_at(self, cell, j):
        key = cell, j
        if key not in self._winds:
            x, y = self._wind(cell, j)
            self._winds[key] = float(x), float(y)
        return self._winds[key]

    def pieces(self, a, b):
        key = tuple(a), tuple(b)
        if key not in self._pieces:
            self._pieces[key] = tuple(
                (float(q[0]-p[0]), float(q[1]-p[1]), cell)
                for p, q, cell in split_static_path(self._shape, [list(a), list(b)]) if p != q)
        return self._pieces[key]

    def duration(self, speed, a, b, departure):
        speed = float(speed)
        t = departure
        for dx, dy, cell in self.pieces(a, b):
            q = 1.0
            while q > 0.0:
                j = int(t // self._bin)
                wx, wy = self._wind_at(cell, j)
                along = wx*dx + wy*dy
                delta = speed*speed - (wx*wx + wy*wy)
                full = (math.sqrt(along*along + delta*(dx*dx + dy*dy)) - along)/delta
                knot = (j + 1)*self._bin
                if t + q*full <= knot:
                    t += q*full
                    q = 0.0
                else:
                    q -= (knot - t)/full
                    t = knot
        return t - departure
