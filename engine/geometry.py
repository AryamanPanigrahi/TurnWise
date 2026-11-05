"""Geometry primitives for map-matching and wrong-way detection.

Pure functions, standard library only. Distances to a polyline use a flat local
projection (equirectangular) around the query point, which is accurate to well
under a metre over the few kilometres a route segment spans.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

EARTH_R_M = 6_371_008.8

LatLon = tuple[float, float]


def haversine_m(a: LatLon, b: LatLon) -> float:
    """Great-circle distance between two (lat, lon) points, in metres."""
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_M * math.asin(math.sqrt(h))


def bearing_deg(a: LatLon, b: LatLon) -> float:
    """Initial bearing from a to b, degrees in [0, 360), 0 = north, clockwise."""
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dl = math.radians(b[1] - a[1])
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def heading_diff_deg(h1: float, h2: float) -> float:
    """Smallest angle between two headings, in [0, 180]."""
    d = abs(h1 - h2) % 360.0
    return 360.0 - d if d > 180.0 else d


def destination(a: LatLon, bearing: float, distance_m: float) -> LatLon:
    """Point reached from a after travelling distance_m along a bearing."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    brg = math.radians(bearing)
    ang = distance_m / EARTH_R_M
    lat2 = math.asin(math.sin(lat1) * math.cos(ang) + math.cos(lat1) * math.sin(ang) * math.cos(brg))
    lon2 = lon1 + math.atan2(
        math.sin(brg) * math.sin(ang) * math.cos(lat1),
        math.cos(ang) - math.sin(lat1) * math.sin(lat2),
    )
    return (math.degrees(lat2), (math.degrees(lon2) + 540.0) % 360.0 - 180.0)


@dataclass(frozen=True)
class Projection:
    """Result of snapping a point onto a polyline."""

    distance_m: float   # perpendicular distance from the point to the line
    along_m: float      # distance travelled along the polyline to the snap point
    segment_index: int  # which segment (0 = between vertex 0 and 1)
    bearing_deg: float  # direction of travel of that segment
    snapped: LatLon     # the snap point


def project_to_polyline(point: LatLon, line: Sequence[LatLon]) -> Projection:
    """Closest point on a polyline (at least 2 vertices) to `point`."""
    if len(line) < 2:
        raise ValueError("polyline needs at least 2 vertices")

    m_per_deg_lat = math.radians(1.0) * EARTH_R_M
    m_per_deg_lon = m_per_deg_lat * math.cos(math.radians(point[0]))

    def xy(p: LatLon) -> tuple[float, float]:
        # metres east / north of the query point
        return ((p[1] - point[1]) * m_per_deg_lon, (p[0] - point[0]) * m_per_deg_lat)

    best: Projection | None = None
    travelled = 0.0
    for i in range(len(line) - 1):
        ax, ay = xy(line[i])
        bx, by = xy(line[i + 1])
        dx, dy = bx - ax, by - ay
        seg_len = math.hypot(dx, dy)
        # t = how far along the segment the closest point is (0..1); the query point is the origin
        t = 0.0 if seg_len == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / (seg_len * seg_len)))
        px, py = ax + t * dx, ay + t * dy
        dist = math.hypot(px, py)
        if best is None or dist < best.distance_m:
            best = Projection(
                distance_m=dist,
                along_m=travelled + t * seg_len,
                segment_index=i,
                bearing_deg=bearing_deg(line[i], line[i + 1]),
                snapped=(point[0] + py / m_per_deg_lat, point[1] + px / m_per_deg_lon),
            )
        travelled += seg_len
    assert best is not None
    return best
