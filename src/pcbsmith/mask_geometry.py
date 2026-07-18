"""Engine-neutral solder-mask aperture geometry.

This module models physical openings in a solder-mask layer.  It deliberately
contains no KiCad parsing, copper-exposure, fabrication-policy, or electrical-
insulation logic.

All dimensions are nominal millimetres.  The exact kernel supports convex
polygons only; concave polygons are rejected instead of being approximated.
Compounds are exact finite unions of supported primitives.
"""

from __future__ import annotations

import hashlib
import json
import math
from enum import StrEnum
from typing import Annotated, Literal, Self, TypeAlias
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MASK_GEOMETRY_SCHEMA_ID: Literal["pcbsmith-mask-geometry"] = "pcbsmith-mask-geometry"
MASK_GEOMETRY_SCHEMA_VERSION: Literal[1] = 1
MASK_GEOMETRY_EPSILON_MM = 1e-9
MASK_SOURCE_NAMESPACE_V1 = UUID("921f36aa-a1cd-5dba-8dc8-aa292e927eef")


class MaskSide(StrEnum):
    FRONT = "front"
    BACK = "back"


class ViaMaskIntent(StrEnum):
    INHERIT = "inherit"
    OPEN = "open"
    TENTED = "tented"


class MaskSourceKind(StrEnum):
    PAD = "pad"
    VIA = "via"
    FOOTPRINT_GRAPHIC = "footprint_graphic"
    BOARD_GRAPHIC = "board_graphic"


class MaskVerification(StrEnum):
    EXACT = "exact"
    BOUNDED_APPROXIMATION = "bounded_approximation"
    UNSUPPORTED = "unsupported"


class ApertureRelation(StrEnum):
    SEPARATED = "separated"
    TOUCHING = "touching"
    OVERLAP = "overlap"
    IGNORED_SAME_PARENT = "ignored_same_parent"


class ContainmentProof(StrEnum):
    """Tri-state result for exact, conservative primitive containment proofs."""

    CONTAINED = "contained"
    NOT_CONTAINED = "not_contained"
    UNKNOWN = "unknown"


class MaskGeometryModel(BaseModel):
    """Frozen base with deterministic, explicitly versioned serialization."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    schema_id: Literal["pcbsmith-mask-geometry"] = MASK_GEOMETRY_SCHEMA_ID
    schema_version: Literal[1] = MASK_GEOMETRY_SCHEMA_VERSION

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


class Point(MaskGeometryModel):
    x_mm: float
    y_mm: float


class Bounds(MaskGeometryModel):
    min_x_mm: float
    min_y_mm: float
    max_x_mm: float
    max_y_mm: float

    @model_validator(mode="after")
    def axes_are_ordered(self) -> Self:
        if self.min_x_mm > self.max_x_mm or self.min_y_mm > self.max_y_mm:
            raise ValueError("bounds minimums must not exceed maximums")
        return self


class Disc(MaskGeometryModel):
    kind: Literal["disc"] = "disc"
    center: Point
    radius_mm: float = Field(gt=0)


class Capsule(MaskGeometryModel):
    kind: Literal["capsule"] = "capsule"
    a: Point
    b: Point
    radius_mm: float = Field(gt=0)

    @model_validator(mode="after")
    def endpoints_are_distinct(self) -> Self:
        if _point_distance(self.a, self.b) <= MASK_GEOMETRY_EPSILON_MM:
            raise ValueError("capsule endpoints must be distinct; use Disc for a circle")
        return self


class OrientedRect(MaskGeometryModel):
    kind: Literal["oriented_rect"] = "oriented_rect"
    center: Point
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    angle_deg: float = 0.0

    @field_validator("angle_deg")
    @classmethod
    def normalize_angle(cls, value: float) -> float:
        return _normalized_angle(value)


class RoundedRect(MaskGeometryModel):
    kind: Literal["rounded_rect"] = "rounded_rect"
    center: Point
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    corner_radius_mm: float = Field(ge=0)
    angle_deg: float = 0.0

    @field_validator("angle_deg")
    @classmethod
    def normalize_angle(cls, value: float) -> float:
        return _normalized_angle(value)

    @model_validator(mode="after")
    def corner_radius_fits(self) -> Self:
        if self.corner_radius_mm > min(self.width_mm, self.height_mm) / 2.0:
            raise ValueError("rounded-rectangle corner radius exceeds half its minor axis")
        return self


class Polygon(MaskGeometryModel):
    kind: Literal["polygon"] = "polygon"
    vertices: tuple[Point, ...]

    @model_validator(mode="after")
    def polygon_is_simple_and_convex(self) -> Self:
        _validate_polygon(self.vertices)
        return self


MaskPrimitive: TypeAlias = Annotated[
    Disc | Capsule | OrientedRect | RoundedRect | Polygon,
    Field(discriminator="kind"),
]


class Compound(MaskGeometryModel):
    """Exact union of supported convex mask primitives."""

    kind: Literal["compound"] = "compound"
    parts: tuple[MaskPrimitive, ...] = Field(min_length=1)


MaskGeometry: TypeAlias = Annotated[
    Disc | Capsule | OrientedRect | RoundedRect | Polygon | Compound,
    Field(discriminator="kind"),
]


class GeometryTransform(MaskGeometryModel):
    """Mirror local X, then rotate, then translate into the destination frame."""

    translate_x_mm: float = 0.0
    translate_y_mm: float = 0.0
    rotation_deg: float = 0.0
    mirror_x: bool = False

    @field_validator("rotation_deg")
    @classmethod
    def normalize_rotation(cls, value: float) -> float:
        return _normalized_angle(value)


class MaskAperture(MaskGeometryModel):
    source_id: str = Field(min_length=1)
    parent_source_id: str | None = None
    source_kind: MaskSourceKind
    side: MaskSide
    geometry: MaskGeometry | None = None
    owner_ref: str | None = None
    copper_source_ids: tuple[str, ...] = ()
    merge_group_id: str | None = None
    verification: MaskVerification = MaskVerification.EXACT
    maximum_error_mm: float | None = Field(default=None, gt=0)
    unsupported_reason: str | None = None

    @model_validator(mode="after")
    def verification_fields_are_coherent(self) -> Self:
        if len(set(self.copper_source_ids)) != len(self.copper_source_ids):
            raise ValueError("copper_source_ids must be unique")
        if self.parent_source_id == "":
            raise ValueError("parent_source_id must be non-empty when supplied")
        if self.merge_group_id == "":
            raise ValueError("merge_group_id must be non-empty when supplied")
        if self.verification is MaskVerification.EXACT:
            if self.geometry is None:
                raise ValueError("exact aperture verification requires geometry")
            if self.maximum_error_mm is not None or self.unsupported_reason is not None:
                raise ValueError("exact aperture verification cannot carry approximation metadata")
        elif self.verification is MaskVerification.BOUNDED_APPROXIMATION:
            if self.geometry is None or self.maximum_error_mm is None:
                raise ValueError("bounded approximation requires geometry and maximum_error_mm")
            if self.unsupported_reason is not None:
                raise ValueError("bounded approximation cannot carry an unsupported reason")
        else:
            if not self.unsupported_reason:
                raise ValueError("unsupported aperture verification requires a reason")
            if self.maximum_error_mm is not None:
                raise ValueError("unsupported aperture cannot carry maximum_error_mm")
        return self


class ApertureMeasurement(MaskGeometryModel):
    relation: ApertureRelation
    web_mm: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def web_matches_relation(self) -> Self:
        if self.relation is ApertureRelation.IGNORED_SAME_PARENT:
            if self.web_mm is not None:
                raise ValueError("ignored aperture pairs cannot report a web")
        elif self.web_mm is None:
            raise ValueError("evaluated aperture pairs require a web")
        elif self.relation is not ApertureRelation.SEPARATED and self.web_mm != 0.0:
            raise ValueError("touching and overlapping aperture pairs have zero web")
        elif self.relation is ApertureRelation.SEPARATED and self.web_mm <= 0.0:
            raise ValueError("separated aperture pairs require a positive web")
        return self


def stable_mask_source_id(*identity: str) -> str:
    """Return a UUID5 from a boundary-safe, versioned semantic identity tuple."""
    if not identity:
        raise ValueError("a stable mask source ID requires at least one identity part")
    if any(not isinstance(part, str) for part in identity):
        raise TypeError("stable mask source identity parts must be strings")
    canonical = json.dumps(
        {
            "schema_id": MASK_GEOMETRY_SCHEMA_ID,
            "schema_version": MASK_GEOMETRY_SCHEMA_VERSION,
            "identity": identity,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return str(uuid5(MASK_SOURCE_NAMESPACE_V1, canonical))


def geometry_bounds(geometry: MaskGeometry) -> Bounds:
    parts = _primitive_parts(geometry)
    bounds = [_primitive_bounds(part) for part in parts]
    return Bounds(
        min_x_mm=min(item.min_x_mm for item in bounds),
        min_y_mm=min(item.min_y_mm for item in bounds),
        max_x_mm=max(item.max_x_mm for item in bounds),
        max_y_mm=max(item.max_y_mm for item in bounds),
    )


def transform_geometry(geometry: MaskGeometry, transform: GeometryTransform) -> MaskGeometry:
    if isinstance(geometry, Compound):
        return Compound(
            parts=tuple(_transform_primitive(part, transform) for part in geometry.parts)
        )
    return _transform_primitive(geometry, transform)


def measure_geometry(first: MaskGeometry, second: MaskGeometry) -> ApertureMeasurement:
    """Return the exact minimum web and closed-region relation for two unions."""
    best_web = math.inf
    saw_touching = False
    for left in _primitive_parts(first):
        for right in _primitive_parts(second):
            relation, web = _measure_primitive(left, right)
            if relation is ApertureRelation.OVERLAP:
                return ApertureMeasurement(relation=relation, web_mm=0.0)
            if relation is ApertureRelation.TOUCHING:
                saw_touching = True
            else:
                best_web = min(best_web, web)
    if saw_touching:
        return ApertureMeasurement(relation=ApertureRelation.TOUCHING, web_mm=0.0)
    return ApertureMeasurement(relation=ApertureRelation.SEPARATED, web_mm=best_web)


def geometry_has_interior_overlap(first: MaskGeometry, second: MaskGeometry) -> bool:
    """Return whether two exact geometries have positive-area interior overlap."""
    return measure_geometry(first, second).relation is ApertureRelation.OVERLAP


def primitive_contains(container: MaskPrimitive, candidate: MaskPrimitive) -> ContainmentProof:
    """Conservatively prove whether one exact primitive contains another.

    A result of ``UNKNOWN`` means this kernel has no complete proof for the
    primitive combination. Callers must never interpret it as non-containment.
    Boundary contact, including internal tangency, counts as containment.
    """
    if container == candidate:
        return ContainmentProof.CONTAINED

    candidate_core_radius = _disc_or_capsule_core(candidate)
    if candidate_core_radius is None:
        return ContainmentProof.UNKNOWN
    candidate_core, candidate_radius = candidate_core_radius

    if isinstance(container, Disc):
        maximum_distance = max(_point_distance(container.center, point) for point in candidate_core)
        return _closed_containment_proof(maximum_distance + candidate_radius, container.radius_mm)

    if isinstance(container, Capsule):
        maximum_distance = max(
            _point_segment_distance(point, container.a, container.b) for point in candidate_core
        )
        return _closed_containment_proof(maximum_distance + candidate_radius, container.radius_mm)

    if isinstance(container, OrientedRect):
        vertices = _rectangle_vertices(
            container.center,
            container.width_mm,
            container.height_mm,
            container.angle_deg,
        )
        return _convex_polygon_contains_core_with_margin(vertices, candidate_core, candidate_radius)

    if isinstance(container, Polygon):
        return _convex_polygon_contains_core_with_margin(
            container.vertices, candidate_core, candidate_radius
        )

    if isinstance(container, RoundedRect):
        if container.corner_radius_mm == 0.0:
            vertices = _rectangle_vertices(
                container.center,
                container.width_mm,
                container.height_mm,
                container.angle_deg,
            )
            return _convex_polygon_contains_core_with_margin(
                vertices, candidate_core, candidate_radius
            )
        if candidate_radius <= container.corner_radius_mm + MASK_GEOMETRY_EPSILON_MM:
            core = _rectangle_vertices(
                container.center,
                container.width_mm - 2.0 * container.corner_radius_mm,
                container.height_mm - 2.0 * container.corner_radius_mm,
                container.angle_deg,
            )
            maximum_distance = max(
                _point_to_convex_core_distance(point, core) for point in candidate_core
            )
            if (
                maximum_distance + candidate_radius
                <= container.corner_radius_mm + MASK_GEOMETRY_EPSILON_MM
            ):
                return ContainmentProof.CONTAINED
        return ContainmentProof.UNKNOWN

    return ContainmentProof.UNKNOWN


def measure_apertures(first: MaskAperture, second: MaskAperture) -> ApertureMeasurement:
    """Measure exact same-side apertures, ignoring children of one logical parent."""
    same_parent = first.source_id == second.source_id or (
        first.parent_source_id is not None and first.parent_source_id == second.parent_source_id
    )
    if same_parent:
        return ApertureMeasurement(relation=ApertureRelation.IGNORED_SAME_PARENT)
    if first.side is not second.side:
        raise ValueError("mask apertures on different sides cannot form a mask web")
    if first.verification is not MaskVerification.EXACT:
        raise ValueError("exact aperture measurement requires exact verification")
    if second.verification is not MaskVerification.EXACT:
        raise ValueError("exact aperture measurement requires exact verification")
    if first.geometry is None or second.geometry is None:  # narrowed by model invariants
        raise ValueError("exact aperture measurement requires geometry")
    return measure_geometry(first.geometry, second.geometry)


def _normalized_angle(value: float) -> float:
    if not math.isfinite(value):
        return value  # Pydantic's allow_inf_nan=False reports the validation error.
    result = value % 360.0
    return 0.0 if result == 0.0 else result


def _point_distance(first: Point, second: Point) -> float:
    return math.hypot(first.x_mm - second.x_mm, first.y_mm - second.y_mm)


def _cross(a: Point, b: Point, c: Point) -> float:
    return (b.x_mm - a.x_mm) * (c.y_mm - a.y_mm) - (b.y_mm - a.y_mm) * (c.x_mm - a.x_mm)


def _validate_polygon(vertices: tuple[Point, ...]) -> None:
    if len(vertices) < 3:
        raise ValueError("polygon requires at least three vertices")
    if any(
        _point_distance(vertices[index], vertices[(index + 1) % len(vertices)])
        <= MASK_GEOMETRY_EPSILON_MM
        for index in range(len(vertices))
    ):
        raise ValueError("polygon has repeated or zero-length consecutive vertices")

    edge_count = len(vertices)
    for first_index in range(edge_count):
        first_a = vertices[first_index]
        first_b = vertices[(first_index + 1) % edge_count]
        for second_index in range(first_index + 1, edge_count):
            if second_index in {
                first_index,
                (first_index + 1) % edge_count,
                (first_index - 1) % edge_count,
            }:
                continue
            second_a = vertices[second_index]
            second_b = vertices[(second_index + 1) % edge_count]
            if _segments_intersect(first_a, first_b, second_a, second_b):
                raise ValueError("polygon must be simple and non-self-intersecting")

    area_twice = sum(
        vertex.x_mm * vertices[(index + 1) % len(vertices)].y_mm
        - vertex.y_mm * vertices[(index + 1) % len(vertices)].x_mm
        for index, vertex in enumerate(vertices)
    )
    if abs(area_twice) <= MASK_GEOMETRY_EPSILON_MM:
        raise ValueError("polygon area must be non-zero")

    turns = [
        _cross(
            vertices[index], vertices[(index + 1) % edge_count], vertices[(index + 2) % edge_count]
        )
        for index in range(edge_count)
    ]
    significant = [turn for turn in turns if abs(turn) > MASK_GEOMETRY_EPSILON_MM]
    if not significant:
        raise ValueError("polygon area must be non-zero")
    if any(turn * significant[0] < -MASK_GEOMETRY_EPSILON_MM for turn in significant[1:]):
        raise ValueError("concave polygons are unsupported; use an explicit convex Compound")


def _primitive_parts(geometry: MaskGeometry) -> tuple[MaskPrimitive, ...]:
    return geometry.parts if isinstance(geometry, Compound) else (geometry,)


def _rotate_translate(point: Point, transform: GeometryTransform) -> Point:
    x_value = -point.x_mm if transform.mirror_x else point.x_mm
    radians = math.radians(transform.rotation_deg)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    return Point(
        x_mm=x_value * cosine - point.y_mm * sine + transform.translate_x_mm,
        y_mm=x_value * sine + point.y_mm * cosine + transform.translate_y_mm,
    )


def _transformed_angle(angle_deg: float, transform: GeometryTransform) -> float:
    local = 180.0 - angle_deg if transform.mirror_x else angle_deg
    return _normalized_angle(local + transform.rotation_deg)


def _transform_primitive(primitive: MaskPrimitive, transform: GeometryTransform) -> MaskPrimitive:
    if isinstance(primitive, Disc):
        return Disc(
            center=_rotate_translate(primitive.center, transform), radius_mm=primitive.radius_mm
        )
    if isinstance(primitive, Capsule):
        return Capsule(
            a=_rotate_translate(primitive.a, transform),
            b=_rotate_translate(primitive.b, transform),
            radius_mm=primitive.radius_mm,
        )
    if isinstance(primitive, OrientedRect):
        return OrientedRect(
            center=_rotate_translate(primitive.center, transform),
            width_mm=primitive.width_mm,
            height_mm=primitive.height_mm,
            angle_deg=_transformed_angle(primitive.angle_deg, transform),
        )
    if isinstance(primitive, RoundedRect):
        return RoundedRect(
            center=_rotate_translate(primitive.center, transform),
            width_mm=primitive.width_mm,
            height_mm=primitive.height_mm,
            corner_radius_mm=primitive.corner_radius_mm,
            angle_deg=_transformed_angle(primitive.angle_deg, transform),
        )
    return Polygon(
        vertices=tuple(_rotate_translate(point, transform) for point in primitive.vertices)
    )


def _primitive_bounds(primitive: MaskPrimitive) -> Bounds:
    core, radius = _convex_core(primitive)
    return Bounds(
        min_x_mm=min(point.x_mm for point in core) - radius,
        min_y_mm=min(point.y_mm for point in core) - radius,
        max_x_mm=max(point.x_mm for point in core) + radius,
        max_y_mm=max(point.y_mm for point in core) + radius,
    )


def _rectangle_vertices(
    center: Point, width_mm: float, height_mm: float, angle_deg: float
) -> tuple[Point, ...]:
    radians = math.radians(angle_deg)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    points: list[Point] = []
    for x_value, y_value in (
        (-width_mm / 2.0, -height_mm / 2.0),
        (width_mm / 2.0, -height_mm / 2.0),
        (width_mm / 2.0, height_mm / 2.0),
        (-width_mm / 2.0, height_mm / 2.0),
    ):
        points.append(
            Point(
                x_mm=center.x_mm + x_value * cosine - y_value * sine,
                y_mm=center.y_mm + x_value * sine + y_value * cosine,
            )
        )
    return _unique_points(tuple(points))


def _unique_points(points: tuple[Point, ...]) -> tuple[Point, ...]:
    result: list[Point] = []
    for point in points:
        if not any(
            _point_distance(point, existing) <= MASK_GEOMETRY_EPSILON_MM for existing in result
        ):
            result.append(point)
    return tuple(result)


def _convex_core(primitive: MaskPrimitive) -> tuple[tuple[Point, ...], float]:
    if isinstance(primitive, Disc):
        return (primitive.center,), primitive.radius_mm
    if isinstance(primitive, Capsule):
        return (primitive.a, primitive.b), primitive.radius_mm
    if isinstance(primitive, OrientedRect):
        return (
            _rectangle_vertices(
                primitive.center, primitive.width_mm, primitive.height_mm, primitive.angle_deg
            ),
            0.0,
        )
    if isinstance(primitive, RoundedRect):
        return (
            _rectangle_vertices(
                primitive.center,
                primitive.width_mm - 2.0 * primitive.corner_radius_mm,
                primitive.height_mm - 2.0 * primitive.corner_radius_mm,
                primitive.angle_deg,
            ),
            primitive.corner_radius_mm,
        )
    return primitive.vertices, 0.0


def _disc_or_capsule_core(
    primitive: MaskPrimitive,
) -> tuple[tuple[Point, ...], float] | None:
    if isinstance(primitive, Disc):
        return (primitive.center,), primitive.radius_mm
    if isinstance(primitive, Capsule):
        return (primitive.a, primitive.b), primitive.radius_mm
    return None


def _closed_containment_proof(actual_extent: float, available_extent: float) -> ContainmentProof:
    if actual_extent <= available_extent + MASK_GEOMETRY_EPSILON_MM:
        return ContainmentProof.CONTAINED
    return ContainmentProof.NOT_CONTAINED


def _convex_polygon_contains_core_with_margin(
    polygon: tuple[Point, ...], candidate_core: tuple[Point, ...], margin_mm: float
) -> ContainmentProof:
    area_twice = sum(
        vertex.x_mm * polygon[(index + 1) % len(polygon)].y_mm
        - vertex.y_mm * polygon[(index + 1) % len(polygon)].x_mm
        for index, vertex in enumerate(polygon)
    )
    orientation = 1.0 if area_twice > 0.0 else -1.0
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        edge_length = _point_distance(start, end)
        for point in candidate_core:
            inward_distance = orientation * _cross(start, end, point) / edge_length
            if inward_distance < margin_mm - MASK_GEOMETRY_EPSILON_MM:
                return ContainmentProof.NOT_CONTAINED
    return ContainmentProof.CONTAINED


def _point_to_convex_core_distance(point: Point, core: tuple[Point, ...]) -> float:
    return _convex_core_distance((point,), core)


def _measure_primitive(
    first: MaskPrimitive, second: MaskPrimitive
) -> tuple[ApertureRelation, float]:
    first_core, first_radius = _convex_core(first)
    second_core, second_radius = _convex_core(second)
    core_distance = _convex_core_distance(first_core, second_core)
    radius_sum = first_radius + second_radius
    difference = core_distance - radius_sum
    if difference > MASK_GEOMETRY_EPSILON_MM:
        return ApertureRelation.SEPARATED, difference
    if abs(difference) <= MASK_GEOMETRY_EPSILON_MM:
        if radius_sum == 0.0 and len(first_core) >= 3 and len(second_core) >= 3:
            relation = _polygon_contact_relation(first_core, second_core)
            return relation, 0.0
        return ApertureRelation.TOUCHING, 0.0
    return ApertureRelation.OVERLAP, 0.0


def _core_segments(core: tuple[Point, ...]) -> tuple[tuple[Point, Point], ...]:
    if len(core) == 1:
        return ()
    if len(core) == 2:
        return ((core[0], core[1]),)
    return tuple((core[index], core[(index + 1) % len(core)]) for index in range(len(core)))


def _convex_core_distance(first: tuple[Point, ...], second: tuple[Point, ...]) -> float:
    if len(first) >= 3 and any(_point_in_convex(point, first) for point in second):
        return 0.0
    if len(second) >= 3 and any(_point_in_convex(point, second) for point in first):
        return 0.0
    first_segments = _core_segments(first)
    second_segments = _core_segments(second)
    if any(
        _segments_intersect(first_a, first_b, second_a, second_b)
        for first_a, first_b in first_segments
        for second_a, second_b in second_segments
    ):
        return 0.0

    distances: list[float] = []
    if not first_segments and not second_segments:
        return _point_distance(first[0], second[0])
    for point in first:
        if second_segments:
            distances.extend(_point_segment_distance(point, a, b) for a, b in second_segments)
        else:
            distances.append(_point_distance(point, second[0]))
    for point in second:
        if first_segments:
            distances.extend(_point_segment_distance(point, a, b) for a, b in first_segments)
        else:
            distances.append(_point_distance(point, first[0]))
    return min(distances)


def _point_segment_distance(point: Point, start: Point, end: Point) -> float:
    dx = end.x_mm - start.x_mm
    dy = end.y_mm - start.y_mm
    length_squared = dx * dx + dy * dy
    if length_squared == 0.0:
        return _point_distance(point, start)
    parameter = ((point.x_mm - start.x_mm) * dx + (point.y_mm - start.y_mm) * dy) / length_squared
    parameter = min(1.0, max(0.0, parameter))
    projection = Point(x_mm=start.x_mm + parameter * dx, y_mm=start.y_mm + parameter * dy)
    return _point_distance(point, projection)


def _orientation(a: Point, b: Point, c: Point) -> int:
    value = _cross(a, b, c)
    if abs(value) <= MASK_GEOMETRY_EPSILON_MM:
        return 0
    return 1 if value > 0.0 else -1


def _on_segment(point: Point, start: Point, end: Point) -> bool:
    return (
        min(start.x_mm, end.x_mm) - MASK_GEOMETRY_EPSILON_MM
        <= point.x_mm
        <= max(start.x_mm, end.x_mm) + MASK_GEOMETRY_EPSILON_MM
        and min(start.y_mm, end.y_mm) - MASK_GEOMETRY_EPSILON_MM
        <= point.y_mm
        <= max(start.y_mm, end.y_mm) + MASK_GEOMETRY_EPSILON_MM
    )


def _segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    first = _orientation(a, b, c)
    second = _orientation(a, b, d)
    third = _orientation(c, d, a)
    fourth = _orientation(c, d, b)
    if first * second < 0 and third * fourth < 0:
        return True
    return (
        (first == 0 and _on_segment(c, a, b))
        or (second == 0 and _on_segment(d, a, b))
        or (third == 0 and _on_segment(a, c, d))
        or (fourth == 0 and _on_segment(b, c, d))
    )


def _point_in_convex(point: Point, polygon: tuple[Point, ...]) -> bool:
    signs = [
        _orientation(polygon[index], polygon[(index + 1) % len(polygon)], point)
        for index in range(len(polygon))
    ]
    nonzero = [sign for sign in signs if sign]
    return not nonzero or all(sign == nonzero[0] for sign in nonzero)


def _polygon_contact_relation(
    first: tuple[Point, ...], second: tuple[Point, ...]
) -> ApertureRelation:
    touching = False
    for polygon in (first, second):
        for index in range(len(polygon)):
            start = polygon[index]
            end = polygon[(index + 1) % len(polygon)]
            axis_x = -(end.y_mm - start.y_mm)
            axis_y = end.x_mm - start.x_mm
            first_projection = [point.x_mm * axis_x + point.y_mm * axis_y for point in first]
            second_projection = [point.x_mm * axis_x + point.y_mm * axis_y for point in second]
            overlap = min(max(first_projection), max(second_projection)) - max(
                min(first_projection), min(second_projection)
            )
            if overlap < -MASK_GEOMETRY_EPSILON_MM:
                return ApertureRelation.SEPARATED
            if overlap <= MASK_GEOMETRY_EPSILON_MM:
                touching = True
    return ApertureRelation.TOUCHING if touching else ApertureRelation.OVERLAP
