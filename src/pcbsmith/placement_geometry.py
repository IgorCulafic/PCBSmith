"""Engine-neutral planar geometry for exact placement legality predicates.

Coordinates enter the public interchange as finite decimal floats.  Every
orientation, incidence, point-location, and squared-distance comparison in
this module converts those coordinates through ``Fraction(str(value))``.
Consequently the predicates are exact for the serialized decimal coordinates;
diagnostic distances returned as floats are not described as exact.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from itertools import combinations
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Point2d = tuple[float, float]
RationalPoint = tuple[Fraction, Fraction]

# Proven decimal enclosure of pi. The authority kernel uses rational range
# reduction and alternating-series bounds; libm trig remains diagnostic only.
_PI_LOWER = Fraction("3.141592653589793238462643383279502884197169399375105820974944")
_PI_UPPER = Fraction("3.141592653589793238462643383279502884197169399375105820974945")
_TRIG_KERNEL_ID: Final = "pcbsmith-rational-trig-pi60-taylor12-v1"


class PlanarGeometryModel(BaseModel):
    """Frozen, versioned geometry value with canonical semantic identity."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    def semantic_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def semantic_fingerprint(self) -> str:
        return hashlib.sha256(self.semantic_json().encode("utf-8")).hexdigest()


class ExactPlanarPolygon(PlanarGeometryModel):
    """One canonical simple outer boundary with zero or more exact voids."""

    schema_id: Literal["pcbsmith-exact-planar-polygon"] = "pcbsmith-exact-planar-polygon"
    schema_version: Literal[1] = 1
    outer: tuple[Point2d, ...] = Field(min_length=3)
    holes: tuple[tuple[Point2d, ...], ...] = ()

    @model_validator(mode="after")
    def geometry_is_canonical_and_valid(self) -> Self:
        outer = canonical_simple_polygon(self.outer, label="polygon outer")
        holes = tuple(
            sorted(
                (canonical_simple_polygon(hole, label="polygon hole") for hole in self.holes),
                key=_polygon_sort_key,
            )
        )
        outer_q = _rational_polygon(outer)
        for hole in holes:
            hole_q = _rational_polygon(hole)
            if _boundaries_intersect(outer_q, hole_q):
                raise ValueError("polygon hole cannot touch or cross its outer boundary")
            if any(
                _point_location_simple(point, outer_q) is not PointLocation.INSIDE
                for point in hole_q
            ):
                raise ValueError("polygon hole must be strictly inside its outer boundary")
        for first, second in combinations(holes, 2):
            first_q = _rational_polygon(first)
            second_q = _rational_polygon(second)
            if _boundaries_intersect(first_q, second_q):
                raise ValueError("polygon holes cannot touch or cross")
            if (
                _point_location_simple(first_q[0], second_q) is PointLocation.INSIDE
                or _point_location_simple(second_q[0], first_q) is PointLocation.INSIDE
            ):
                raise ValueError("polygon holes cannot overlap or contain one another")
        object.__setattr__(self, "outer", outer)
        object.__setattr__(self, "holes", holes)
        return self


class ExactPlanarCompound(PlanarGeometryModel):
    """Canonical union of disjoint exact polygon islands, retaining voids."""

    schema_id: Literal["pcbsmith-exact-planar-compound"] = "pcbsmith-exact-planar-compound"
    schema_version: Literal[1] = 1
    polygons: tuple[ExactPlanarPolygon, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def islands_are_canonical_and_disjoint(self) -> Self:
        polygons = tuple(sorted(self.polygons, key=lambda item: item.semantic_json()))
        if len({item.semantic_fingerprint() for item in polygons}) != len(polygons):
            raise ValueError("compound polygon islands must be unique")
        for first, second in combinations(polygons, 2):
            relation = polygon_relation(first, second)
            if relation is not PlanarRelation.DISJOINT:
                raise ValueError("compound polygon islands must be strictly disjoint")
        object.__setattr__(self, "polygons", polygons)
        return self


class PlacementTransform(PlanarGeometryModel):
    """One established KiCad placement transform."""

    schema_id: Literal["pcbsmith-placement-transform"] = "pcbsmith-placement-transform"
    schema_version: Literal[1] = 1
    anchor_x_mm: float
    anchor_y_mm: float
    rotation_deg: float
    side: Literal["front", "back"]

    @model_validator(mode="after")
    def rotation_is_canonical(self) -> Self:
        normalized = self.rotation_deg % 360.0
        object.__setattr__(
            self, "anchor_x_mm", 0.0 if self.anchor_x_mm == 0.0 else self.anchor_x_mm
        )
        object.__setattr__(
            self, "anchor_y_mm", 0.0 if self.anchor_y_mm == 0.0 else self.anchor_y_mm
        )
        object.__setattr__(self, "rotation_deg", 0.0 if normalized == 0.0 else normalized)
        return self


@dataclass(frozen=True)
class RationalInterval:
    """Closed rational interval used by the bounded transform authority."""

    lower: Fraction
    upper: Fraction

    def __post_init__(self) -> None:
        if self.lower > self.upper:
            raise ValueError("rational interval lower bound cannot exceed upper bound")

    @property
    def midpoint(self) -> Fraction:
        return (self.lower + self.upper) / 2

    def contains(self, value: float | Fraction) -> bool:
        rational = value if isinstance(value, Fraction) else Fraction(str(value))
        return self.lower <= rational <= self.upper


@dataclass(frozen=True)
class BoundedPointTransform:
    """Nominal serialized point plus a certified interval and Euclidean error cap."""

    point: Point2d
    x_interval: RationalInterval
    y_interval: RationalInterval
    maximum_error_mm: float
    exact: bool
    kernel_id: str = _TRIG_KERNEL_ID

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in self.point):
            raise ValueError("bounded transform nominal point must be finite")
        if not self.x_interval.contains(self.point[0]) or not self.y_interval.contains(
            self.point[1]
        ):
            raise ValueError("bounded transform nominal point must lie in its intervals")
        if not math.isfinite(self.maximum_error_mm) or self.maximum_error_mm < 0:
            raise ValueError("bounded transform maximum error must be finite and non-negative")
        if self.exact != (self.maximum_error_mm == 0):
            raise ValueError("bounded transform exactness and maximum error are incoherent")


class PlacementTransformAuthority(StrEnum):
    EXACT = "exact"
    BOUNDED_APPROXIMATION = "bounded_approximation"


class PlacedCompoundTransform(PlanarGeometryModel):
    """Placed polygon geometry with exact or conservative transform authority."""

    schema_id: Literal["pcbsmith-placed-compound-transform"] = "pcbsmith-placed-compound-transform"
    schema_version: Literal[1] = 1
    compound: ExactPlanarCompound
    authority: PlacementTransformAuthority
    maximum_error_mm: float | None
    kernel_id: Literal["pcbsmith-rational-trig-pi60-taylor12-v1"] = _TRIG_KERNEL_ID

    @model_validator(mode="after")
    def authority_and_error_are_coherent(self) -> Self:
        if self.authority is PlacementTransformAuthority.EXACT:
            if self.maximum_error_mm is not None:
                raise ValueError("exact compound transform cannot declare error")
        elif (
            self.maximum_error_mm is None
            or not math.isfinite(self.maximum_error_mm)
            or self.maximum_error_mm <= 0
        ):
            raise ValueError("bounded compound transform requires positive finite error")
        return self


class PointLocation(StrEnum):
    OUTSIDE = "outside"
    BOUNDARY = "boundary"
    INSIDE = "inside"


class PlanarRelation(StrEnum):
    DISJOINT = "disjoint"
    BOUNDARY_TOUCH = "boundary_touch"
    INTERIOR_OVERLAP = "interior_overlap"


@dataclass(frozen=True)
class ExactCompoundDistanceWitness:
    """Exact set-distance witness for serialized decimal polygon coordinates."""

    relation: PlanarRelation
    squared_distance: Fraction
    first_point: RationalPoint
    second_point: RationalPoint

    def __post_init__(self) -> None:
        if self.squared_distance < 0:
            raise ValueError("distance witness cannot carry negative squared distance")
        if (self.relation is PlanarRelation.DISJOINT) != (self.squared_distance > 0):
            raise ValueError("distance witness relation and squared distance are incoherent")
        if self.squared_distance == 0 and self.first_point != self.second_point:
            raise ValueError("zero-distance witness points must coincide")


@dataclass(frozen=True)
class ExactSegmentDistanceWitness:
    """Exact distance from a filled compound to one non-degenerate segment."""

    squared_distance: Fraction
    compound_point: RationalPoint
    segment_point: RationalPoint

    def __post_init__(self) -> None:
        if self.squared_distance < 0:
            raise ValueError("segment distance witness cannot carry negative distance")
        if self.squared_distance == 0 and self.compound_point != self.segment_point:
            raise ValueError("zero-distance segment witness points must coincide")


@dataclass(frozen=True)
class ExactSegmentMaximumDistanceWitness:
    """Exact farthest boundary-vertex distance from a compound to one segment."""

    squared_distance: Fraction
    compound_point: RationalPoint
    segment_point: RationalPoint

    def __post_init__(self) -> None:
        if self.squared_distance < 0:
            raise ValueError("maximum segment distance cannot be negative")


def canonical_simple_polygon(
    points: tuple[Point2d, ...], *, label: str = "polygon"
) -> tuple[Point2d, ...]:
    """Validate and canonicalize one finite simple polygon using rational predicates."""

    raw = tuple(points[:-1] if len(points) > 1 and points[0] == points[-1] else points)
    opened = tuple(
        (0.0 if x_value == 0.0 else x_value, 0.0 if y_value == 0.0 else y_value)
        for x_value, y_value in raw
    )
    if len(opened) < 3:
        raise ValueError(f"{label} requires at least three vertices")
    if any(not math.isfinite(value) for point in opened for value in point):
        raise ValueError(f"{label} vertices must be finite")
    if len(set(opened)) != len(opened):
        raise ValueError(f"{label} cannot repeat vertices")
    rational = _rational_polygon(opened)
    area = _twice_signed_area(rational)
    if area == 0:
        raise ValueError(f"{label} must have non-zero area")
    edges = _edges(rational)
    for first, (a, b) in enumerate(edges):
        for second in range(first + 1, len(edges)):
            if second in {first, (first + 1) % len(edges)} or first == (second + 1) % len(edges):
                continue
            if _segments_intersect(a, b, *edges[second]):
                raise ValueError(f"{label} must be a simple polygon")
    ordered = opened if area > 0 else tuple(reversed(opened))
    start = min(range(len(ordered)), key=lambda index: ordered[index])
    return ordered[start:] + ordered[:start]


def _interval_add(first: RationalInterval, second: RationalInterval) -> RationalInterval:
    return RationalInterval(first.lower + second.lower, first.upper + second.upper)


def _interval_negate(value: RationalInterval) -> RationalInterval:
    return RationalInterval(-value.upper, -value.lower)


def _interval_scale(value: RationalInterval, scalar: Fraction) -> RationalInterval:
    first = value.lower * scalar
    second = value.upper * scalar
    return RationalInterval(min(first, second), max(first, second))


def _alternating_trig_bounds(value: Fraction, *, cosine: bool) -> tuple[Fraction, Fraction]:
    """Bound sin/cos on [0, pi/2] with fixed alternating partial sums."""

    if value < 0 or value > _PI_UPPER / 2:
        raise ValueError("first-quadrant trig input is outside the certified interval")
    term = Fraction(1) if cosine else value
    total = term
    lower = total
    upper = total
    for index in range(1, 13):
        if cosine:
            denominator = (2 * index - 1) * (2 * index)
        else:
            denominator = (2 * index) * (2 * index + 1)
        term = -term * value * value / denominator
        total += term
        if index == 11:
            lower = total
        elif index == 12:
            upper = total
    if lower > upper:
        raise ValueError("alternating trig enclosure is incoherent")
    return lower, upper


def _first_quadrant_trig_bounds(
    residual_degrees: Fraction,
) -> tuple[RationalInterval, RationalInterval]:
    radians_lower = residual_degrees * _PI_LOWER / 180
    radians_upper = residual_degrees * _PI_UPPER / 180
    sin_lower = _alternating_trig_bounds(radians_lower, cosine=False)[0]
    sin_upper = _alternating_trig_bounds(radians_upper, cosine=False)[1]
    cos_lower = _alternating_trig_bounds(radians_upper, cosine=True)[0]
    cos_upper = _alternating_trig_bounds(radians_lower, cosine=True)[1]
    return (
        RationalInterval(sin_lower, sin_upper),
        RationalInterval(cos_lower, cos_upper),
    )


def _trig_bounds(rotation_deg: float) -> tuple[RationalInterval, RationalInterval]:
    angle = Fraction(str(rotation_deg))
    quadrant = int(angle // 90)
    residual = angle - 90 * quadrant
    sine, cosine = _first_quadrant_trig_bounds(residual)
    if quadrant == 0:
        return sine, cosine
    if quadrant == 1:
        return cosine, _interval_negate(sine)
    if quadrant == 2:
        return _interval_negate(sine), _interval_negate(cosine)
    if quadrant == 3:
        return _interval_negate(cosine), sine
    raise ValueError("normalized placement rotation escaped [0, 360)")


def _upper_float(value: Fraction) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("bounded transform error cannot be represented as a finite float")
    while Fraction.from_float(result) < value:
        result = math.nextafter(result, math.inf)
    return result


def _nominal_interval(value: RationalInterval) -> tuple[float, RationalInterval]:
    nominal = float(value.midpoint)
    if not math.isfinite(nominal):
        raise ValueError("bounded transform nominal coordinate must be finite")
    serialized = Fraction(str(nominal))
    return nominal, RationalInterval(
        min(value.lower, serialized),
        max(value.upper, serialized),
    )


def transform_point_bounded(point: Point2d, transform: PlacementTransform) -> BoundedPointTransform:
    """Transform a point with exact quarter turns or certified rational trig bounds."""

    if transform.rotation_deg in {0.0, 90.0, 180.0, 270.0}:
        x_value, y_value = (Fraction(str(value)) for value in point)
        quarter_turn = int(transform.rotation_deg)
        front = {
            0: (x_value, y_value),
            90: (y_value, -x_value),
            180: (-x_value, -y_value),
            270: (-y_value, x_value),
        }[quarter_turn]
        vector = (
            front
            if transform.side == "front"
            else {
                0: (-x_value, y_value),
                90: (y_value, x_value),
                180: (x_value, -y_value),
                270: (-y_value, -x_value),
            }[quarter_turn]
        )
        exact_x = Fraction(str(transform.anchor_x_mm)) + vector[0]
        exact_y = Fraction(str(transform.anchor_y_mm)) + vector[1]
        nominal = (float(exact_x), float(exact_y))
        if not all(math.isfinite(value) for value in nominal):
            raise ValueError("quarter-turn transform coordinate must be finite")
        nominal = (
            0.0 if nominal[0] == 0.0 else nominal[0],
            0.0 if nominal[1] == 0.0 else nominal[1],
        )
        serialized_x = Fraction(str(nominal[0]))
        serialized_y = Fraction(str(nominal[1]))
        return BoundedPointTransform(
            point=nominal,
            x_interval=RationalInterval(serialized_x, serialized_x),
            y_interval=RationalInterval(serialized_y, serialized_y),
            maximum_error_mm=0.0,
            exact=True,
        )

    x_value, y_value = (Fraction(str(value)) for value in point)
    sine, cosine = _trig_bounds(transform.rotation_deg)
    x_cosine = _interval_scale(cosine, x_value)
    y_sine = _interval_scale(sine, y_value)
    x_sine = _interval_scale(sine, x_value)
    y_cosine = _interval_scale(cosine, y_value)
    if transform.side == "front":
        x_interval = _interval_add(x_cosine, y_sine)
        y_interval = _interval_add(_interval_negate(x_sine), y_cosine)
    else:
        x_interval = _interval_add(_interval_negate(x_cosine), y_sine)
        y_interval = _interval_add(x_sine, y_cosine)
    x_anchor = Fraction(str(transform.anchor_x_mm))
    y_anchor = Fraction(str(transform.anchor_y_mm))
    x_interval = _interval_add(x_interval, RationalInterval(x_anchor, x_anchor))
    y_interval = _interval_add(y_interval, RationalInterval(y_anchor, y_anchor))
    nominal_x, x_interval = _nominal_interval(x_interval)
    nominal_y, y_interval = _nominal_interval(y_interval)
    nominal_x_fraction = Fraction(str(nominal_x))
    nominal_y_fraction = Fraction(str(nominal_y))
    x_error = max(
        nominal_x_fraction - x_interval.lower,
        x_interval.upper - nominal_x_fraction,
    )
    y_error = max(
        nominal_y_fraction - y_interval.lower,
        y_interval.upper - nominal_y_fraction,
    )
    maximum_error = _upper_float(x_error + y_error)
    return BoundedPointTransform(
        point=(0.0 if nominal_x == 0.0 else nominal_x, 0.0 if nominal_y == 0.0 else nominal_y),
        x_interval=x_interval,
        y_interval=y_interval,
        maximum_error_mm=maximum_error,
        exact=maximum_error == 0,
    )


def transform_compound_bounded(
    compound: ExactPlanarCompound, transform: PlacementTransform
) -> PlacedCompoundTransform:
    """Place polygonal geometry with bounded, not analytic-exact, authority.

    Arcs and circles must first enter as separately bounded polygonal geometry;
    this kernel does not claim exact curved-primitive transforms.
    """

    point_results: list[BoundedPointTransform] = []
    polygons: list[ExactPlanarPolygon] = []
    for polygon in compound.polygons:
        outer_results = tuple(transform_point_bounded(point, transform) for point in polygon.outer)
        hole_results = tuple(
            tuple(transform_point_bounded(point, transform) for point in hole)
            for hole in polygon.holes
        )
        point_results.extend(outer_results)
        point_results.extend(item for hole in hole_results for item in hole)
        polygons.append(
            ExactPlanarPolygon(
                outer=tuple(item.point for item in outer_results),
                holes=tuple(tuple(item.point for item in hole) for hole in hole_results),
            )
        )
    exact = all(item.exact for item in point_results)
    maximum_error = None if exact else max(item.maximum_error_mm for item in point_results)
    return PlacedCompoundTransform(
        compound=ExactPlanarCompound(polygons=tuple(polygons)),
        authority=(
            PlacementTransformAuthority.EXACT
            if exact
            else PlacementTransformAuthority.BOUNDED_APPROXIMATION
        ),
        maximum_error_mm=maximum_error,
    )


def transform_point(point: Point2d, transform: PlacementTransform) -> Point2d:
    """Apply the legacy diagnostic transform; arbitrary angles are not hard authority."""

    x_value, y_value = transform_vector(point, transform)
    return (
        _clean_float(transform.anchor_x_mm + x_value),
        _clean_float(transform.anchor_y_mm + y_value),
    )


def transform_vector(vector: Point2d, transform: PlacementTransform) -> Point2d:
    """Transform a vector without translation using the same side convention."""

    x_value, y_value = vector
    quarter_turn = (
        int(transform.rotation_deg) if transform.rotation_deg in {0.0, 90.0, 180.0, 270.0} else None
    )
    if quarter_turn is not None:
        front = {
            0: (x_value, y_value),
            90: (y_value, -x_value),
            180: (-x_value, -y_value),
            270: (-y_value, x_value),
        }[quarter_turn]
        if transform.side == "front":
            return (_clean_float(front[0]), _clean_float(front[1]))
        back = {
            0: (-x_value, y_value),
            90: (y_value, x_value),
            180: (x_value, -y_value),
            270: (-y_value, -x_value),
        }[quarter_turn]
        return (_clean_float(back[0]), _clean_float(back[1]))
    radians = math.radians(transform.rotation_deg)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    if transform.side == "front":
        return (
            _clean_float(x_value * cosine + y_value * sine),
            _clean_float(-x_value * sine + y_value * cosine),
        )
    # mirror_x(rotate_offset(local, -rotation))
    return (
        _clean_float(-x_value * cosine + y_value * sine),
        _clean_float(x_value * sine + y_value * cosine),
    )


def transform_compound(
    compound: ExactPlanarCompound, transform: PlacementTransform
) -> ExactPlanarCompound:
    """Place diagnostic geometry; use transform_compound_bounded for authority."""

    return ExactPlanarCompound(
        polygons=tuple(
            ExactPlanarPolygon(
                outer=tuple(transform_point(point, transform) for point in polygon.outer),
                holes=tuple(
                    tuple(transform_point(point, transform) for point in hole)
                    for hole in polygon.holes
                ),
            )
            for polygon in compound.polygons
        )
    )


def polygon_relation(first: ExactPlanarPolygon, second: ExactPlanarPolygon) -> PlanarRelation:
    """Classify filled-interior overlap separately from boundary-only contact."""

    first_boundaries = _polygon_boundaries(first)
    second_boundaries = _polygon_boundaries(second)
    touched = False
    for first_boundary in first_boundaries:
        for second_boundary in second_boundaries:
            for a, b in _edges(first_boundary):
                for c, d in _edges(second_boundary):
                    if _segments_properly_cross(a, b, c, d):
                        return PlanarRelation.INTERIOR_OVERLAP
                    touched = touched or _segments_intersect(a, b, c, d)
    for point in _boundary_vertices(first):
        if _point_location_polygon(point, second) is PointLocation.INSIDE:
            return PlanarRelation.INTERIOR_OVERLAP
    for point in _boundary_vertices(second):
        if _point_location_polygon(point, first) is PointLocation.INSIDE:
            return PlanarRelation.INTERIOR_OVERLAP
    first_witness = _interior_witness(first)
    second_witness = _interior_witness(second)
    if _point_location_polygon(first_witness, second) is PointLocation.INSIDE:
        return PlanarRelation.INTERIOR_OVERLAP
    if _point_location_polygon(second_witness, first) is PointLocation.INSIDE:
        return PlanarRelation.INTERIOR_OVERLAP
    if _shared_interior_witness(first, second):
        return PlanarRelation.INTERIOR_OVERLAP
    return PlanarRelation.BOUNDARY_TOUCH if touched else PlanarRelation.DISJOINT


def compound_relation(first: ExactPlanarCompound, second: ExactPlanarCompound) -> PlanarRelation:
    """Return the strongest relation across disjoint compound islands."""

    touched = False
    for first_polygon in first.polygons:
        for second_polygon in second.polygons:
            relation = polygon_relation(first_polygon, second_polygon)
            if relation is PlanarRelation.INTERIOR_OVERLAP:
                return relation
            touched = touched or relation is PlanarRelation.BOUNDARY_TOUCH
    return PlanarRelation.BOUNDARY_TOUCH if touched else PlanarRelation.DISJOINT


def _vector_cross(first: RationalPoint, second: RationalPoint) -> Fraction:
    return first[0] * second[1] - first[1] * second[0]


def _segment_intersection_point(
    a: RationalPoint, b: RationalPoint, c: RationalPoint, d: RationalPoint
) -> RationalPoint:
    candidates = tuple(
        sorted(
            {
                point
                for point in (a, b, c, d)
                if _point_on_segment(point, a, b) and _point_on_segment(point, c, d)
            }
        )
    )
    if candidates:
        return candidates[0]
    first_vector = (b[0] - a[0], b[1] - a[1])
    second_vector = (d[0] - c[0], d[1] - c[1])
    denominator = _vector_cross(first_vector, second_vector)
    if denominator == 0:
        raise ValueError("intersecting collinear segments lost their shared endpoint")
    offset = (c[0] - a[0], c[1] - a[1])
    parameter = _vector_cross(offset, second_vector) / denominator
    return (
        a[0] + parameter * first_vector[0],
        a[1] + parameter * first_vector[1],
    )


def _point_segment_distance_witness(
    point: RationalPoint, start: RationalPoint, end: RationalPoint
) -> tuple[Fraction, RationalPoint, RationalPoint]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        projection = start
    else:
        parameter = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared
        parameter = min(Fraction(1), max(Fraction(0), parameter))
        projection = (start[0] + parameter * dx, start[1] + parameter * dy)
    squared = (point[0] - projection[0]) ** 2 + (point[1] - projection[1]) ** 2
    return squared, point, projection


def _segment_distance_witness(
    a: RationalPoint, b: RationalPoint, c: RationalPoint, d: RationalPoint
) -> tuple[Fraction, RationalPoint, RationalPoint]:
    if _segments_intersect(a, b, c, d):
        point = _segment_intersection_point(a, b, c, d)
        return Fraction(0), point, point
    first_a = _point_segment_distance_witness(a, c, d)
    first_b = _point_segment_distance_witness(b, c, d)
    second_c = _point_segment_distance_witness(c, a, b)
    second_d = _point_segment_distance_witness(d, a, b)
    candidates = (
        first_a,
        first_b,
        (second_c[0], second_c[2], second_c[1]),
        (second_d[0], second_d[2], second_d[1]),
    )
    return min(candidates, key=lambda item: (item[0], item[1], item[2]))


def _compound_shared_point(
    first: ExactPlanarCompound, second: ExactPlanarCompound
) -> RationalPoint:
    candidates: set[RationalPoint] = set()
    first_boundaries = tuple(
        boundary for polygon in first.polygons for boundary in _polygon_boundaries(polygon)
    )
    second_boundaries = tuple(
        boundary for polygon in second.polygons for boundary in _polygon_boundaries(polygon)
    )
    for boundary in first_boundaries:
        for point in boundary:
            if _point_location_compound(point, second) is not PointLocation.OUTSIDE:
                candidates.add(point)
    for boundary in second_boundaries:
        for point in boundary:
            if _point_location_compound(point, first) is not PointLocation.OUTSIDE:
                candidates.add(point)
    for first_boundary in first_boundaries:
        for second_boundary in second_boundaries:
            for a, b in _edges(first_boundary):
                for c, d in _edges(second_boundary):
                    if _segments_intersect(a, b, c, d):
                        candidates.add(_segment_intersection_point(a, b, c, d))
    for polygon in first.polygons:
        witness = _interior_witness(polygon)
        if _point_location_compound(witness, second) is not PointLocation.OUTSIDE:
            candidates.add(witness)
    for polygon in second.polygons:
        witness = _interior_witness(polygon)
        if _point_location_compound(witness, first) is not PointLocation.OUTSIDE:
            candidates.add(witness)
    if not candidates:
        raise ValueError("overlapping compounds have no discoverable exact shared point")
    return min(candidates)


def compound_distance_witness(
    first: ExactPlanarCompound, second: ExactPlanarCompound
) -> ExactCompoundDistanceWitness:
    """Return exact squared set distance and deterministic responsible points."""

    relation = compound_relation(first, second)
    if relation is not PlanarRelation.DISJOINT:
        point = _compound_shared_point(first, second)
        return ExactCompoundDistanceWitness(
            relation=relation,
            squared_distance=Fraction(0),
            first_point=point,
            second_point=point,
        )
    candidates = tuple(
        _segment_distance_witness(a, b, c, d)
        for first_polygon in first.polygons
        for second_polygon in second.polygons
        for first_boundary in _polygon_boundaries(first_polygon)
        for second_boundary in _polygon_boundaries(second_polygon)
        for a, b in _edges(first_boundary)
        for c, d in _edges(second_boundary)
    )
    if not candidates:
        raise ValueError("cannot measure empty geometry")
    squared, first_point, second_point = min(
        candidates, key=lambda item: (item[0], item[1], item[2])
    )
    return ExactCompoundDistanceWitness(
        relation=relation,
        squared_distance=squared,
        first_point=first_point,
        second_point=second_point,
    )


def compound_to_segment_distance_witness(
    compound: ExactPlanarCompound,
    segment_start: Point2d,
    segment_end: Point2d,
) -> ExactSegmentDistanceWitness:
    """Return an exact deterministic witness to an actual outline segment."""

    start = _rational_point(segment_start)
    end = _rational_point(segment_end)
    if start == end:
        raise ValueError("distance segment must be non-degenerate")
    shared_points: set[RationalPoint] = {
        point
        for point in (start, end)
        if _point_location_compound(point, compound) is not PointLocation.OUTSIDE
    }
    for polygon in compound.polygons:
        for boundary in _polygon_boundaries(polygon):
            for a, b in _edges(boundary):
                if _segments_intersect(a, b, start, end):
                    shared_points.add(_segment_intersection_point(a, b, start, end))
    if shared_points:
        point = min(shared_points)
        return ExactSegmentDistanceWitness(Fraction(0), point, point)
    candidates = tuple(
        _segment_distance_witness(a, b, start, end)
        for polygon in compound.polygons
        for boundary in _polygon_boundaries(polygon)
        for a, b in _edges(boundary)
    )
    if not candidates:
        raise ValueError("cannot measure empty geometry")
    squared, compound_point, segment_point = min(
        candidates, key=lambda item: (item[0], item[1], item[2])
    )
    return ExactSegmentDistanceWitness(squared, compound_point, segment_point)


def compound_to_segment_maximum_distance_witness(
    compound: ExactPlanarCompound,
    segment_start: Point2d,
    segment_end: Point2d,
) -> ExactSegmentMaximumDistanceWitness:
    """Return the exact farthest boundary-vertex distance to a segment.

    Squared distance to a closed line segment is convex, so its maximum over
    each polygon edge occurs at an endpoint.  Inspecting every outer and hole
    boundary vertex therefore gives the exact maximum for polygonal geometry.
    """

    start = _rational_point(segment_start)
    end = _rational_point(segment_end)
    if start == end:
        raise ValueError("distance segment must be non-degenerate")
    candidates = tuple(
        _point_segment_distance_witness(point, start, end)
        for polygon in compound.polygons
        for boundary in _polygon_boundaries(polygon)
        for point in boundary
    )
    if not candidates:
        raise ValueError("cannot measure empty geometry")
    squared, compound_point, segment_point = max(
        candidates, key=lambda item: (item[0], item[1], item[2])
    )
    return ExactSegmentMaximumDistanceWitness(
        squared_distance=squared,
        compound_point=compound_point,
        segment_point=segment_point,
    )


def compound_minimum_squared_distance(
    first: ExactPlanarCompound, second: ExactPlanarCompound
) -> Fraction:
    """Exact squared set distance for the serialized decimal coordinates."""

    if compound_relation(first, second) is not PlanarRelation.DISJOINT:
        return Fraction(0)
    return compound_boundary_minimum_squared_distance(first, second)


def compound_boundary_minimum_squared_distance(
    first: ExactPlanarCompound,
    second: ExactPlanarCompound,
) -> Fraction:
    """Exact squared boundary distance, even when one filled set contains another."""

    minimum: Fraction | None = None
    for first_polygon in first.polygons:
        for second_polygon in second.polygons:
            for first_boundary in _polygon_boundaries(first_polygon):
                for second_boundary in _polygon_boundaries(second_polygon):
                    for a, b in _edges(first_boundary):
                        for c, d in _edges(second_boundary):
                            distance = _segment_squared_distance(a, b, c, d)
                            minimum = distance if minimum is None else min(minimum, distance)
    if minimum is None:  # structurally unreachable for validated polygons
        raise ValueError("cannot measure empty geometry")
    return minimum


def compound_clearance_at_least(
    first: ExactPlanarCompound,
    second: ExactPlanarCompound,
    clearance_mm: float,
) -> bool:
    """Compare boundary clearance without a binary-float square root."""

    if not math.isfinite(clearance_mm) or clearance_mm < 0:
        raise ValueError("clearance_mm must be finite and non-negative")
    required = _q(clearance_mm)
    return compound_minimum_squared_distance(first, second) >= required * required


def compound_inside_polygon(compound: ExactPlanarCompound, allowed: ExactPlanarPolygon) -> bool:
    """Prove every occupied island lies in the closed filled allowed polygon."""

    allowed_boundaries = _polygon_boundaries(allowed)
    for polygon in compound.polygons:
        for boundary in _polygon_boundaries(polygon):
            for start, end in _edges(boundary):
                if _point_location_polygon(start, allowed) is PointLocation.OUTSIDE:
                    return False
                midpoint = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
                if _point_location_polygon(midpoint, allowed) is PointLocation.OUTSIDE:
                    return False
                if any(
                    _segments_properly_cross(start, end, edge_start, edge_end)
                    for allowed_boundary in allowed_boundaries
                    for edge_start, edge_end in _edges(allowed_boundary)
                ):
                    return False
        if _point_location_polygon(_interior_witness(polygon), allowed) is PointLocation.OUTSIDE:
            return False
    for hole in allowed.holes:
        hole_polygon = ExactPlanarPolygon(outer=hole)
        if (
            _point_location_compound(_interior_witness(hole_polygon), compound)
            is not PointLocation.OUTSIDE
        ):
            return False
    return True


def compound_boundary_clearance_at_least(
    compound: ExactPlanarCompound,
    boundary_polygon: ExactPlanarPolygon,
    clearance_mm: float,
) -> bool:
    """Compare occupied geometry to every outer/hole boundary exactly."""

    if not math.isfinite(clearance_mm) or clearance_mm < 0:
        raise ValueError("clearance_mm must be finite and non-negative")
    boundary_compounds = tuple(
        ExactPlanarCompound(polygons=(ExactPlanarPolygon(outer=boundary),))
        for boundary in (boundary_polygon.outer, *boundary_polygon.holes)
    )
    minimum = min(
        compound_boundary_minimum_squared_distance(compound, boundary)
        for boundary in boundary_compounds
    )
    required = _q(clearance_mm)
    return minimum >= required * required


def diagnostic_distance_mm(squared_distance: Fraction) -> float:
    """Return a clearly diagnostic (binary-float) distance."""

    if squared_distance < 0:
        raise ValueError("squared distance cannot be negative")
    return math.sqrt(float(squared_distance))


def _clean_float(value: float) -> float:
    return 0.0 if value == 0.0 else value


def _q(value: float | Fraction) -> Fraction:
    return value if isinstance(value, Fraction) else Fraction(str(value))


def _rational_point(point: Point2d) -> RationalPoint:
    return (_q(point[0]), _q(point[1]))


def _rational_polygon(polygon: tuple[Point2d, ...]) -> tuple[RationalPoint, ...]:
    return tuple(_rational_point(point) for point in polygon)


def _polygon_sort_key(polygon: tuple[Point2d, ...]) -> str:
    return json.dumps(polygon, separators=(",", ":"), allow_nan=False)


def _twice_signed_area(polygon: tuple[RationalPoint, ...]) -> Fraction:
    return sum(
        (
            polygon[index][0] * polygon[(index + 1) % len(polygon)][1]
            - polygon[(index + 1) % len(polygon)][0] * polygon[index][1]
            for index in range(len(polygon))
        ),
        Fraction(0),
    )


def _edges(polygon: tuple[RationalPoint, ...]) -> tuple[tuple[RationalPoint, RationalPoint], ...]:
    return tuple(
        (polygon[index], polygon[(index + 1) % len(polygon)]) for index in range(len(polygon))
    )


def _orientation(a: RationalPoint, b: RationalPoint, c: RationalPoint) -> Fraction:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _point_on_segment(point: RationalPoint, start: RationalPoint, end: RationalPoint) -> bool:
    return (
        _orientation(start, end, point) == 0
        and min(start[0], end[0]) <= point[0] <= max(start[0], end[0])
        and min(start[1], end[1]) <= point[1] <= max(start[1], end[1])
    )


def _segments_properly_cross(
    a: RationalPoint, b: RationalPoint, c: RationalPoint, d: RationalPoint
) -> bool:
    first = _orientation(a, b, c)
    second = _orientation(a, b, d)
    third = _orientation(c, d, a)
    fourth = _orientation(c, d, b)
    return first * second < 0 and third * fourth < 0


def _segments_intersect(
    a: RationalPoint, b: RationalPoint, c: RationalPoint, d: RationalPoint
) -> bool:
    if _segments_properly_cross(a, b, c, d):
        return True
    return any(
        orientation == 0 and _point_on_segment(point, start, end)
        for orientation, point, start, end in (
            (_orientation(a, b, c), c, a, b),
            (_orientation(a, b, d), d, a, b),
            (_orientation(c, d, a), a, c, d),
            (_orientation(c, d, b), b, c, d),
        )
    )


def _boundaries_intersect(
    first: tuple[RationalPoint, ...], second: tuple[RationalPoint, ...]
) -> bool:
    return any(_segments_intersect(a, b, c, d) for a, b in _edges(first) for c, d in _edges(second))


def _point_location_simple(
    point: RationalPoint, polygon: tuple[RationalPoint, ...]
) -> PointLocation:
    if any(_point_on_segment(point, start, end) for start, end in _edges(polygon)):
        return PointLocation.BOUNDARY
    x_value, y_value = point
    inside = False
    for (x1, y1), (x2, y2) in _edges(polygon):
        if (y1 > y_value) != (y2 > y_value):
            crossing = x1 + (y_value - y1) * (x2 - x1) / (y2 - y1)
            if crossing > x_value:
                inside = not inside
    return PointLocation.INSIDE if inside else PointLocation.OUTSIDE


def _point_location_polygon(point: RationalPoint, polygon: ExactPlanarPolygon) -> PointLocation:
    outer = _point_location_simple(point, _rational_polygon(polygon.outer))
    if outer is not PointLocation.INSIDE:
        return outer
    for hole in polygon.holes:
        location = _point_location_simple(point, _rational_polygon(hole))
        if location is PointLocation.BOUNDARY:
            return PointLocation.BOUNDARY
        if location is PointLocation.INSIDE:
            return PointLocation.OUTSIDE
    return PointLocation.INSIDE


def _point_location_compound(point: RationalPoint, compound: ExactPlanarCompound) -> PointLocation:
    touched = False
    for polygon in compound.polygons:
        location = _point_location_polygon(point, polygon)
        if location is PointLocation.INSIDE:
            return location
        touched = touched or location is PointLocation.BOUNDARY
    return PointLocation.BOUNDARY if touched else PointLocation.OUTSIDE


def _polygon_boundaries(polygon: ExactPlanarPolygon) -> tuple[tuple[RationalPoint, ...], ...]:
    return (_rational_polygon(polygon.outer), *(_rational_polygon(hole) for hole in polygon.holes))


def _boundary_vertices(polygon: ExactPlanarPolygon) -> tuple[RationalPoint, ...]:
    return tuple(point for boundary in _polygon_boundaries(polygon) for point in boundary)


def _shared_interior_witness(
    first: ExactPlanarPolygon,
    second: ExactPlanarPolygon,
) -> bool:
    vertices = (*_boundary_vertices(first), *_boundary_vertices(second))
    candidates = (((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in combinations(vertices, 2))
    return any(
        _point_location_polygon(candidate, first) is PointLocation.INSIDE
        and _point_location_polygon(candidate, second) is PointLocation.INSIDE
        for candidate in candidates
    )


def _interior_witness(polygon: ExactPlanarPolygon) -> RationalPoint:
    outer = _rational_polygon(polygon.outer)
    candidates: list[RationalPoint] = []
    candidates.append(
        (
            sum((point[0] for point in outer), Fraction(0)) / len(outer),
            sum((point[1] for point in outer), Fraction(0)) / len(outer),
        )
    )
    for first, second in combinations(outer, 2):
        candidates.append(((first[0] + second[0]) / 2, (first[1] + second[1]) / 2))
    for first, second, third in combinations(outer, 3):
        candidates.append(
            (
                (first[0] + second[0] + third[0]) / 3,
                (first[1] + second[1] + third[1]) / 3,
            )
        )
    for candidate in candidates:
        if _point_location_polygon(candidate, polygon) is PointLocation.INSIDE:
            return candidate
    raise ValueError("polygon has no discoverable exact interior witness")


def _point_segment_squared_distance(
    point: RationalPoint, start: RationalPoint, end: RationalPoint
) -> Fraction:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return (point[0] - start[0]) ** 2 + (point[1] - start[1]) ** 2
    parameter = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared
    parameter = min(Fraction(1), max(Fraction(0), parameter))
    projection = (start[0] + parameter * dx, start[1] + parameter * dy)
    return (point[0] - projection[0]) ** 2 + (point[1] - projection[1]) ** 2


def _segment_squared_distance(
    a: RationalPoint, b: RationalPoint, c: RationalPoint, d: RationalPoint
) -> Fraction:
    if _segments_intersect(a, b, c, d):
        return Fraction(0)
    return min(
        _point_segment_squared_distance(a, c, d),
        _point_segment_squared_distance(b, c, d),
        _point_segment_squared_distance(c, a, b),
        _point_segment_squared_distance(d, a, b),
    )
