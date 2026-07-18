from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from pcbsmith.mask_geometry import (
    ApertureRelation,
    Capsule,
    Compound,
    Disc,
    GeometryTransform,
    MaskAperture,
    MaskSide,
    MaskSourceKind,
    MaskVerification,
    OrientedRect,
    Point,
    Polygon,
    RoundedRect,
    geometry_bounds,
    measure_apertures,
    measure_geometry,
    stable_mask_source_id,
    transform_geometry,
)


def point(x_mm: float, y_mm: float) -> Point:
    return Point(x_mm=x_mm, y_mm=y_mm)


def aperture(
    source_id: str,
    geometry: Disc | Compound,
    *,
    parent_source_id: str | None = None,
) -> MaskAperture:
    return MaskAperture(
        source_id=source_id,
        parent_source_id=parent_source_id,
        source_kind=MaskSourceKind.PAD,
        side=MaskSide.FRONT,
        geometry=geometry,
    )


def test_disc_gap_touch_and_overlap_are_distinct_and_symmetric() -> None:
    first = Disc(center=point(0.0, 0.0), radius_mm=1.0)
    separated = Disc(center=point(2.3, 0.0), radius_mm=1.0)
    touching = Disc(center=point(2.0, 0.0), radius_mm=1.0)
    overlapping = Disc(center=point(1.9, 0.0), radius_mm=1.0)

    forward = measure_geometry(first, separated)
    reverse = measure_geometry(separated, first)
    assert forward.relation is ApertureRelation.SEPARATED
    assert forward.web_mm == pytest.approx(0.3)
    assert forward == reverse
    assert measure_geometry(first, touching).relation is ApertureRelation.TOUCHING
    assert measure_geometry(first, overlapping).relation is ApertureRelation.OVERLAP


def test_rotated_capsule_uses_exact_segment_distance() -> None:
    diagonal = Capsule(a=point(-1.0, -1.0), b=point(1.0, 1.0), radius_mm=0.2)
    shifted = Capsule(a=point(-0.5, 0.5), b=point(1.5, 2.5), radius_mm=0.2)
    result = measure_geometry(diagonal, shifted)
    assert result.relation is ApertureRelation.SEPARATED
    assert result.web_mm == pytest.approx(math.sqrt(0.5) - 0.4)
    assert measure_geometry(shifted, diagonal) == result


def test_oriented_rect_overlap_and_bounds_are_exact() -> None:
    diamond = OrientedRect(center=point(0.0, 0.0), width_mm=2.0, height_mm=2.0, angle_deg=45.0)
    inside = Disc(center=point(0.0, 0.0), radius_mm=0.1)
    bounds = geometry_bounds(diamond)
    assert bounds.min_x_mm == pytest.approx(-math.sqrt(2.0))
    assert bounds.max_y_mm == pytest.approx(math.sqrt(2.0))
    assert measure_geometry(diamond, inside).relation is ApertureRelation.OVERLAP
    adjacent = OrientedRect(
        center=point(2.0 * math.sqrt(2.0), 0.0),
        width_mm=2.0,
        height_mm=2.0,
        angle_deg=45.0,
    )
    intruding = adjacent.model_copy(update={"center": point(2.7, 0.0)})
    assert measure_geometry(diamond, adjacent).relation is ApertureRelation.TOUCHING
    assert measure_geometry(diamond, intruding).relation is ApertureRelation.OVERLAP


def test_roundrect_preserves_non_quarter_corner_radius() -> None:
    rounded = RoundedRect(
        center=point(0.0, 0.0),
        width_mm=4.0,
        height_mm=2.0,
        corner_radius_mm=0.3,
        angle_deg=0.0,
    )
    probe = Disc(center=point(2.4, 0.0), radius_mm=0.1)
    result = measure_geometry(rounded, probe)
    assert result.relation is ApertureRelation.SEPARATED
    assert result.web_mm == pytest.approx(0.3)
    assert rounded.corner_radius_mm == 0.3


def test_polygon_rejects_self_intersection_concavity_and_degeneracy() -> None:
    square = Polygon(vertices=(point(0, 0), point(2, 0), point(2, 2), point(0, 2)))
    assert geometry_bounds(square).max_x_mm == 2.0

    with pytest.raises(ValidationError, match="simple"):
        Polygon(vertices=(point(0, 0), point(2, 2), point(0, 2), point(2, 0)))
    with pytest.raises(ValidationError, match="concave polygons are unsupported"):
        Polygon(vertices=(point(0, 0), point(2, 0), point(1, 0.5), point(2, 2), point(0, 2)))
    with pytest.raises(ValidationError):
        Polygon(vertices=(point(0, 0), point(1, 0), point(2, 0)))


def test_convex_polygon_distance_is_exact_and_symmetric() -> None:
    first = Polygon(vertices=(point(0, 0), point(2, 0), point(2, 2), point(0, 2)))
    second = Polygon(vertices=(point(3, 0), point(5, 0), point(5, 2), point(3, 2)))
    forward = measure_geometry(first, second)
    assert forward.relation is ApertureRelation.SEPARATED
    assert forward.web_mm == pytest.approx(1.0)
    assert measure_geometry(second, first) == forward


def test_compound_uses_minimum_cross_part_distance() -> None:
    first = Compound(
        parts=(
            Disc(center=point(0.0, 0.0), radius_mm=0.5),
            Disc(center=point(10.0, 0.0), radius_mm=0.5),
        )
    )
    second = Compound(
        parts=(
            Disc(center=point(3.0, 0.0), radius_mm=0.5),
            Disc(center=point(20.0, 0.0), radius_mm=0.5),
        )
    )
    result = measure_geometry(first, second)
    assert result.relation is ApertureRelation.SEPARATED
    assert result.web_mm == pytest.approx(2.0)


def test_same_parent_aperture_children_are_ignored() -> None:
    first = aperture(
        "child:a", Disc(center=point(0.0, 0.0), radius_mm=1.0), parent_source_id="opening:1"
    )
    second = aperture(
        "child:b", Disc(center=point(4.0, 0.0), radius_mm=1.0), parent_source_id="opening:1"
    )
    result = measure_apertures(first, second)
    assert result.relation is ApertureRelation.IGNORED_SAME_PARENT
    assert result.web_mm is None


def test_transform_is_repeatable_and_mirror_aware() -> None:
    original = RoundedRect(
        center=point(2.0, 1.0),
        width_mm=4.0,
        height_mm=2.0,
        corner_radius_mm=0.2,
        angle_deg=30.0,
    )
    transform = GeometryTransform(
        translate_x_mm=10.0, translate_y_mm=-3.0, rotation_deg=90.0, mirror_x=True
    )
    first = transform_geometry(original, transform)
    second = transform_geometry(original, transform)
    assert first == second
    assert first.semantic_json() == second.semantic_json()
    assert isinstance(first, RoundedRect)
    assert first.center.x_mm == pytest.approx(9.0)
    assert first.center.y_mm == pytest.approx(-5.0)
    assert first.angle_deg == pytest.approx(240.0)


def test_source_id_and_fingerprint_repeat_and_change_semantically() -> None:
    first_id = stable_mask_source_id("pad", "U1", "1", "front")
    assert first_id == "f5850e2a-5074-5903-8b7e-f3ac2b23d435"
    assert first_id == stable_mask_source_id("pad", "U1", "1", "front")
    assert first_id != stable_mask_source_id("pad", "U1", "1", "back")
    first = aperture(first_id, Disc(center=point(0.0, 0.0), radius_mm=1.0))
    repeated = MaskAperture.model_validate_json(first.semantic_json())
    changed = aperture(first_id, Disc(center=point(0.0, 0.0), radius_mm=1.1))
    assert first == repeated
    assert first.semantic_fingerprint() == repeated.semantic_fingerprint()
    assert first.semantic_fingerprint() != changed.semantic_fingerprint()
    assert '"schema_version":1' in first.semantic_json()


def test_aperture_serialization_round_trip_preserves_discriminated_compound() -> None:
    original = MaskAperture(
        source_id="board-opening:1",
        source_kind=MaskSourceKind.BOARD_GRAPHIC,
        side=MaskSide.BACK,
        geometry=Compound(
            parts=(
                Disc(center=point(0.0, 0.0), radius_mm=1.0),
                OrientedRect(center=point(2.0, 0.0), width_mm=1.0, height_mm=2.0, angle_deg=15.0),
            )
        ),
        merge_group_id="gang:1",
    )
    restored = MaskAperture.model_validate_json(original.semantic_json())
    assert restored == original
    assert isinstance(restored.geometry, Compound)


def test_invalid_nonfinite_and_verification_combinations_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Point(x_mm=math.inf, y_mm=0.0)
    with pytest.raises(ValidationError):
        Disc(center=point(0.0, 0.0), radius_mm=0.0)
    with pytest.raises(ValidationError, match="corner radius"):
        RoundedRect(
            center=point(0.0, 0.0),
            width_mm=2.0,
            height_mm=1.0,
            corner_radius_mm=0.6,
        )
    with pytest.raises(ValidationError, match="requires a reason"):
        MaskAperture(
            source_id="unknown:1",
            source_kind=MaskSourceKind.VIA,
            side=MaskSide.FRONT,
            verification=MaskVerification.UNSUPPORTED,
        )
    bounded = MaskAperture(
        source_id="approx:1",
        source_kind=MaskSourceKind.FOOTPRINT_GRAPHIC,
        side=MaskSide.FRONT,
        geometry=Disc(center=point(0.0, 0.0), radius_mm=1.0),
        verification=MaskVerification.BOUNDED_APPROXIMATION,
        maximum_error_mm=0.01,
    )
    with pytest.raises(ValueError, match="exact aperture measurement"):
        measure_apertures(bounded, aperture("exact:1", Disc(center=point(3, 0), radius_mm=1)))
