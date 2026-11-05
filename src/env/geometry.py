"""Polygonal geometry and normalized-arclength path identity."""
from __future__ import annotations

import math
from shapely.geometry import LineString, Point, Polygon


def canonical_path(points):
    """Remove repeated vertices and forward collinear subdivisions, not turns."""
    out = []
    for point in points:
        p = tuple(point)
        if out and p == out[-1]:
            continue
        while len(out) >= 2:
            a, b = out[-2:]
            ab = (b[0] - a[0], b[1] - a[1])
            bc = (p[0] - b[0], p[1] - b[1])
            cross = ab[0] * bc[1] - ab[1] * bc[0]
            # Only exact collinearity identifies the same represented curve.
            if cross != 0 or ab[0] * bc[0] + ab[1] * bc[1] < 0:
                break
            out.pop()
        out.append(p)
    return tuple(out)


def path_geometry(points):
    points = canonical_path(points)
    return Point(points[0]) if len(points) == 1 else LineString(points)


def validate_path(points, region, start=None, end=None):
    if not points or any(len(p) != 2 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in p) for p in points):
        raise ValueError('path must contain finite XY points')
    path = canonical_path(points)
    if start is not None and path[0] != tuple(start):
        raise ValueError('path start differs from observed/preceding position')
    if end is not None and path[-1] != tuple(end):
        raise ValueError('path end differs from stop position')
    if not region.covers(path_geometry(path)):
        raise ValueError('path leaves the operating region')
    return path


def polygon(points):
    p = Polygon(points)
    if not p.is_valid or p.is_empty or p.area <= 0:
        raise ValueError('polygon must be simple with positive area')
    return p
