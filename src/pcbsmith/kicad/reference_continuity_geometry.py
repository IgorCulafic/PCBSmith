"""Exact integer/rational geometry for straight reference-continuity paths."""

from __future__ import annotations

from fractions import Fraction

Point = tuple[int, int]
Contour = tuple[Point, ...]
Polygon = tuple[Contour, tuple[Contour, ...]]


def _point_on_segment(point: tuple[Fraction, Fraction], start: Point, end: Point) -> bool:
    px, py = point
    ax, ay = start
    bx, by = end
    return (
        (px - ax) * (by - ay) == (py - ay) * (bx - ax)
        and min(ax, bx) <= px <= max(ax, bx)
        and min(ay, by) <= py <= max(ay, by)
    )


def _point_in_contour(point: tuple[Fraction, Fraction], contour: Contour) -> tuple[bool, bool]:
    if len(contour) < 3:
        return False, False
    inside = False
    px, py = point
    for index, start in enumerate(contour):
        end = contour[(index + 1) % len(contour)]
        if _point_on_segment(point, start, end):
            return True, True
        ax, ay = start
        bx, by = end
        if (ay > py) == (by > py):
            continue
        crossing_x = Fraction(ax) + Fraction((py - ay) * (bx - ax), by - ay)
        if crossing_x > px:
            inside = not inside
    return inside, False


def _covered(point: tuple[Fraction, Fraction], polygons: tuple[Polygon, ...]) -> bool:
    for outline, holes in polygons:
        inside, boundary = _point_in_contour(point, outline)
        if not inside:
            continue
        if boundary:
            return True
        rejected = False
        for hole in holes:
            in_hole, on_hole = _point_in_contour(point, hole)
            if on_hole:
                return True
            if in_hole:
                rejected = True
                break
        if not rejected:
            return True
    return False


def _cross(a: Point, b: Point) -> int:
    return a[0] * b[1] - a[1] * b[0]


def _boundary_parameters(start: Point, end: Point, contour: Contour) -> set[Fraction]:
    parameters: set[Fraction] = set()
    direction = (end[0] - start[0], end[1] - start[1])
    denominator_axis = 0 if abs(direction[0]) >= abs(direction[1]) else 1
    for index, boundary_start in enumerate(contour):
        boundary_end = contour[(index + 1) % len(contour)]
        boundary_direction = (
            boundary_end[0] - boundary_start[0],
            boundary_end[1] - boundary_start[1],
        )
        offset = (boundary_start[0] - start[0], boundary_start[1] - start[1])
        denominator = _cross(direction, boundary_direction)
        if denominator:
            t = Fraction(_cross(offset, boundary_direction), denominator)
            u = Fraction(_cross(offset, direction), denominator)
            if 0 <= t <= 1 and 0 <= u <= 1:
                parameters.add(t)
            continue
        if _cross(offset, direction) or direction == (0, 0):
            continue
        axis_delta = direction[denominator_axis]
        for point in (boundary_start, boundary_end):
            t = Fraction(point[denominator_axis] - start[denominator_axis], axis_delta)
            if 0 <= t <= 1:
                parameters.add(t)
    return parameters


def segment_fully_covered(start: Point, end: Point, polygons: tuple[Polygon, ...]) -> bool:
    """Prove continuous centerline coverage across a polygon union and its holes."""

    if start == end:
        return _covered((Fraction(start[0]), Fraction(start[1])), polygons)
    parameters: set[Fraction] = {Fraction(0), Fraction(1)}
    for outline, holes in polygons:
        parameters.update(_boundary_parameters(start, end, outline))
        for hole in holes:
            parameters.update(_boundary_parameters(start, end, hole))
    ordered = sorted(parameters)

    def point_at(t: Fraction) -> tuple[Fraction, Fraction]:
        return (
            Fraction(start[0]) + t * (end[0] - start[0]),
            Fraction(start[1]) + t * (end[1] - start[1]),
        )

    if any(not _covered(point_at(t), polygons) for t in ordered):
        return False
    return all(
        _covered(point_at((left + right) / 2), polygons)
        for left, right in zip(ordered, ordered[1:], strict=False)
        if left != right
    )
