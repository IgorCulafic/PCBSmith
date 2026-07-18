"""Canonical exact polygon contracts for KiCad board routing regions."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass

Point = tuple[float, float]
Polygon = tuple[Point, ...]
_EPSILON = 1e-9


@dataclass(frozen=True)
class BoardCutoutPolygon:
    """One exact simple board cutout with canonical semantic geometry."""

    points: Polygon

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "points",
            canonical_simple_polygon(self.points, label="board cutout"),
        )

    def semantic_fingerprint(self) -> str:
        return polygon_fingerprint(self.points)


def polygon_fingerprint(polygon: Sequence[Point]) -> str:
    canonical = canonical_simple_polygon(polygon)
    payload = json.dumps(
        {
            "schema_id": "pcbsmith-simple-polygon",
            "schema_version": 1,
            "points": canonical,
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonical_simple_polygon(
    raw: Sequence[Point],
    *,
    label: str = "polygon",
) -> Polygon:
    """Validate a finite simple polygon and canonicalize winding/start."""
    points = tuple(raw[:-1] if len(raw) > 1 and raw[0] == raw[-1] else raw)
    if len(points) < 3:
        raise ValueError(f"{label} requires at least three vertices")
    if any(not math.isfinite(value) for point in points for value in point):
        raise ValueError(f"{label} vertices must be finite")
    if len(set(points)) != len(points):
        raise ValueError(f"{label} cannot repeat vertices")
    signed_area_twice = sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )
    if abs(signed_area_twice) <= _EPSILON:
        raise ValueError(f"{label} must have non-zero area")
    edges = _polygon_edges(points)
    for first, (a, b) in enumerate(edges):
        for second in range(first + 1, len(edges)):
            if second in {first, (first + 1) % len(edges)} or first == (second + 1) % len(edges):
                continue
            if _segments_intersect(a, b, *edges[second]):
                raise ValueError(f"{label} must be a simple polygon")
    ordered = points if signed_area_twice > 0 else tuple(reversed(points))
    start = min(range(len(ordered)), key=lambda index: ordered[index])
    return ordered[start:] + ordered[:start]


def validate_cutouts(
    outer: Sequence[Point],
    cutouts: Sequence[BoardCutoutPolygon],
) -> tuple[BoardCutoutPolygon, ...]:
    """Validate exact cutouts against one outer polygon and each other."""
    canonical_outer = canonical_simple_polygon(outer, label="board outline")
    canonical_cutouts = tuple(sorted(cutouts, key=lambda item: item.points))
    identities: dict[str, Polygon] = {}
    for index, cutout in enumerate(canonical_cutouts):
        if index and cutout.points == canonical_cutouts[index - 1].points:
            raise ValueError("duplicate board cutout polygon")
        fingerprint = cutout.semantic_fingerprint()
        previous = identities.get(fingerprint)
        if previous is not None and previous != cutout.points:
            raise ValueError("board cutout semantic identity collision")
        identities[fingerprint] = cutout.points
        if not all(_point_strictly_inside(point, canonical_outer) for point in cutout.points):
            raise ValueError("board cutout must be strictly inside the board outline")
        if _boundaries_intersect(cutout.points, canonical_outer):
            raise ValueError("board cutout cannot touch or cross the board outline")
    for index, first in enumerate(canonical_cutouts):
        for second in canonical_cutouts[index + 1 :]:
            if (
                _boundaries_intersect(first.points, second.points)
                or _point_strictly_inside(first.points[0], second.points)
                or _point_strictly_inside(second.points[0], first.points)
            ):
                raise ValueError("board cutouts cannot touch, intersect, overlap, or contain")
    return canonical_cutouts


def point_strictly_inside_polygon(point: Point, polygon: Sequence[Point]) -> bool:
    """Public strict-inside predicate used by conservative adapters."""
    return _point_strictly_inside(point, canonical_simple_polygon(polygon))


def polygon_edges(polygon: Sequence[Point]) -> tuple[tuple[Point, Point], ...]:
    """Return canonical polygon edges."""
    return _polygon_edges(canonical_simple_polygon(polygon))


def segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    """Closed-segment intersection, including boundary touching."""
    return _segments_intersect(a, b, c, d)


def _polygon_edges(polygon: Sequence[Point]) -> tuple[tuple[Point, Point], ...]:
    return tuple(
        (polygon[index], polygon[(index + 1) % len(polygon)]) for index in range(len(polygon))
    )


def _boundaries_intersect(first: Polygon, second: Polygon) -> bool:
    return any(
        _segments_intersect(a, b, c, d)
        for a, b in _polygon_edges(first)
        for c, d in _polygon_edges(second)
    )


def _point_strictly_inside(point: Point, polygon: Polygon) -> bool:
    if any(_point_segment_distance(point, a, b) <= _EPSILON for a, b in _polygon_edges(polygon)):
        return False
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in _polygon_edges(polygon):
        if (y1 > y) != (y2 > y):
            crossing = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if crossing > x:
                inside = not inside
    return inside


def _segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    def orientation(p: Point, q: Point, r: Point) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    values = (
        orientation(a, b, c),
        orientation(a, b, d),
        orientation(c, d, a),
        orientation(c, d, b),
    )
    if values[0] * values[1] < -_EPSILON and values[2] * values[3] < -_EPSILON:
        return True
    return any(
        abs(value) <= _EPSILON and _point_on_segment(point, start, end)
        for value, point, start, end in (
            (values[0], c, a, b),
            (values[1], d, a, b),
            (values[2], a, c, d),
            (values[3], b, c, d),
        )
    )


def _point_on_segment(point: Point, a: Point, b: Point) -> bool:
    return (
        min(a[0], b[0]) - _EPSILON <= point[0] <= max(a[0], b[0]) + _EPSILON
        and min(a[1], b[1]) - _EPSILON <= point[1] <= max(a[1], b[1]) + _EPSILON
    )


def _point_segment_distance(point: Point, a: Point, b: Point) -> float:
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return math.dist(point, a)
    t = max(
        0.0,
        min(
            1.0,
            ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length_squared,
        ),
    )
    return math.dist(point, (a[0] + t * dx, a[1] + t * dy))
