"""Full-horizon cell-time wind with unique spatial and temporal ownership."""
from __future__ import annotations

from bisect import bisect_right
from fractions import Fraction
from shapely.geometry import LineString, Point

from .geometry import polygon, validate_path
from .units import time_field


def _line_parts(geometry):
    if geometry.is_empty:
        return
    if geometry.geom_type in ('LineString', 'LinearRing'):
        yield geometry
    elif hasattr(geometry, 'geoms'):
        for part in geometry.geoms:
            yield from _line_parts(part)


class WindField:
    def __init__(self, scenario, projection):
        if projection not in ('previous', 'received'):
            raise ValueError('projection must be previous or received')
        self.data = scenario.data['wind']
        packet = self.data[projection]
        self.values = tuple(tuple(tuple(float(Fraction(str(v))) for v in w) for w in row)
                            for row in packet['values'])
        self.knots = self.data[time_field(scenario.data, 'time_knots')]
        self.coverage = packet.get('coverage', ('forecast',)*(len(self.knots)-1))
        self.admissible = packet.get('admissible', ((True,)*(len(self.knots)-1),)*len(self.values))
        self.cells = tuple(polygon(c['polygon_xy']) for c in self.data['cells'])
        self.region = polygon(scenario.data['mission']['operating_region_xy'])
        self._ownership_order = sorted(range(len(self.cells)), key=lambda r: self.data['cells'][r]['id'])

    def cell_index(self, point):
        p = Point(point)
        for r in self._ownership_order:
            if self.cells[r].covers(p):
                return r
        raise ValueError('point lies outside the wind partition')

    def time_bin(self, time_h):
        if not self.knots[0] <= time_h <= self.knots[-1]:
            raise ValueError('wind is defined only on the remaining horizon')
        return min(bisect_right(self.knots, time_h)-1, len(self.knots)-2)

    def split_path(self, points):
        """Split at every crossed cell edge; boundary-aligned pieces have one owner."""
        points = validate_path(points, self.region)
        pieces = []
        for a,b in zip(points, points[1:]):
            segment = LineString([a,b])
            cuts = {0., 1.}
            coverage = []
            for r, cell in enumerate(self.cells):
                for part in _line_parts(segment.intersection(cell)):
                    left, right = sorted(segment.project(Point(point), normalized=True)
                                         for point in (part.coords[0], part.coords[-1]))
                    if right > left:
                        cuts.update((left, right))
                        coverage.append((left, right, r))
            cuts = sorted(cuts)
            for left,right in zip(cuts, cuts[1:]):
                if right <= left:
                    continue
                start = segment.interpolate(left, normalized=True)
                end = segment.interpolate(right, normalized=True)
                # Classify parameter intervals from the actual intersections.
                # Interpolating a midpoint can round off a slanted shared edge.
                middle = (left+right)/2
                owners = {r for lo,hi,r in coverage if lo <= middle <= hi}
                if not owners:
                    raise ValueError('path segment is not covered by wind cells')
                cell = next(r for r in self._ownership_order if r in owners)
                pieces.append((tuple(start.coords[0]), tuple(end.coords[0]), cell))
        return pieces
