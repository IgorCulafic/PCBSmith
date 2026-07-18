from __future__ import annotations

from typing import cast

from pcbsmith.mask_geometry import (
    Capsule,
    Compound,
    ContainmentProof,
    Disc,
    MaskPrimitive,
    OrientedRect,
    Point,
    Polygon,
    RoundedRect,
    geometry_has_interior_overlap,
    primitive_contains,
)


def point(x_mm: float, y_mm: float) -> Point:
    return Point(x_mm=x_mm, y_mm=y_mm)


def test_disc_contains_disc_with_internal_tangency() -> None:
    container = Disc(center=point(0.0, 0.0), radius_mm=2.0)
    smaller = Disc(center=point(0.25, 0.0), radius_mm=0.5)
    internally_tangent = Disc(center=point(1.0, 0.0), radius_mm=1.0)

    assert primitive_contains(container, smaller) is ContainmentProof.CONTAINED
    assert primitive_contains(container, internally_tangent) is ContainmentProof.CONTAINED


def test_disc_rejects_capsule_whose_far_end_crosses_boundary() -> None:
    container = Disc(center=point(0.0, 0.0), radius_mm=2.0)
    contained = Capsule(a=point(-1.0, 0.0), b=point(1.0, 0.0), radius_mm=1.0)
    crossing = Capsule(a=point(-1.0, 0.0), b=point(1.01, 0.0), radius_mm=1.0)

    assert primitive_contains(container, contained) is ContainmentProof.CONTAINED
    assert primitive_contains(container, crossing) is ContainmentProof.NOT_CONTAINED


def test_capsule_contains_coaxial_capsule_and_rejects_side_offset() -> None:
    container = Capsule(a=point(-2.0, 0.0), b=point(2.0, 0.0), radius_mm=1.0)
    coaxial = Capsule(a=point(-1.5, 0.0), b=point(1.5, 0.0), radius_mm=0.5)
    side_offset = Capsule(a=point(-1.5, 0.51), b=point(1.5, 0.51), radius_mm=0.5)

    assert primitive_contains(container, coaxial) is ContainmentProof.CONTAINED
    assert primitive_contains(container, side_offset) is ContainmentProof.NOT_CONTAINED


def test_rectangle_and_clockwise_polygon_apply_inward_radius_margin() -> None:
    candidate = Capsule(a=point(-1.0, 0.0), b=point(1.0, 0.0), radius_mm=0.5)
    shifted = Capsule(a=point(-1.0, 0.51), b=point(1.0, 0.51), radius_mm=0.5)
    rectangle = OrientedRect(center=point(0.0, 0.0), width_mm=4.0, height_mm=1.0, angle_deg=0.0)
    clockwise_polygon = Polygon(
        vertices=(point(-2.0, -0.5), point(-2.0, 0.5), point(2.0, 0.5), point(2.0, -0.5))
    )

    assert primitive_contains(rectangle, candidate) is ContainmentProof.CONTAINED
    assert primitive_contains(rectangle, shifted) is ContainmentProof.NOT_CONTAINED
    assert primitive_contains(clockwise_polygon, candidate) is ContainmentProof.CONTAINED
    assert primitive_contains(clockwise_polygon, shifted) is ContainmentProof.NOT_CONTAINED


def test_positive_area_overlap_excludes_external_touching() -> None:
    first = Disc(center=point(0.0, 0.0), radius_mm=1.0)
    touching = Disc(center=point(2.0, 0.0), radius_mm=1.0)
    overlapping = Disc(center=point(1.99, 0.0), radius_mm=1.0)

    assert not geometry_has_interior_overlap(first, touching)
    assert geometry_has_interior_overlap(first, overlapping)


def test_unsupported_combinations_are_unknown_but_semantic_equality_is_contained() -> None:
    disc = Disc(center=point(0.0, 0.0), radius_mm=2.0)
    rectangle = OrientedRect(center=point(0.0, 0.0), width_mm=1.0, height_mm=1.0)
    polygon = Polygon(vertices=(point(-1, -1), point(1, -1), point(1, 1), point(-1, 1)))

    assert primitive_contains(disc, rectangle) is ContainmentProof.UNKNOWN
    assert primitive_contains(polygon, polygon.model_copy()) is ContainmentProof.CONTAINED


def test_rounded_rectangle_only_reports_mathematically_proven_cases() -> None:
    container = RoundedRect(
        center=point(0.0, 0.0),
        width_mm=4.0,
        height_mm=2.0,
        corner_radius_mm=0.4,
    )
    proven = Capsule(a=point(-1.4, 0.0), b=point(1.4, 0.0), radius_mm=0.4)
    unsupported = Capsule(a=point(-1.0, 0.0), b=point(1.0, 0.0), radius_mm=0.5)

    assert primitive_contains(container, proven) is ContainmentProof.CONTAINED
    assert primitive_contains(container, unsupported) is ContainmentProof.UNKNOWN


def test_compound_union_containment_is_not_invented_from_overlapping_parts() -> None:
    compound = Compound(
        parts=(
            Disc(center=point(-0.5, 0.0), radius_mm=1.0),
            Disc(center=point(0.5, 0.0), radius_mm=1.0),
        )
    )
    candidate = Capsule(a=point(-0.75, 0.0), b=point(0.75, 0.0), radius_mm=0.6)

    assert primitive_contains(cast(MaskPrimitive, compound), candidate) is ContainmentProof.UNKNOWN
