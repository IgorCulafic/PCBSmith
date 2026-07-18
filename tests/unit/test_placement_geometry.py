from __future__ import annotations

import math
from fractions import Fraction

import pytest

from pcbsmith.placement_geometry import (
    ExactPlanarCompound,
    ExactPlanarPolygon,
    PlacedCompoundTransform,
    PlacementTransform,
    PlacementTransformAuthority,
    PlanarRelation,
    compound_boundary_clearance_at_least,
    compound_clearance_at_least,
    compound_distance_witness,
    compound_inside_polygon,
    compound_minimum_squared_distance,
    compound_relation,
    compound_to_segment_distance_witness,
    transform_compound,
    transform_compound_bounded,
    transform_point,
    transform_point_bounded,
)


def _polygon(
    *points: tuple[float, float], holes: tuple[tuple[tuple[float, float], ...], ...] = ()
) -> ExactPlanarPolygon:
    return ExactPlanarPolygon(outer=points, holes=holes)


def _compound(*polygons: ExactPlanarPolygon) -> ExactPlanarCompound:
    return ExactPlanarCompound(polygons=polygons)


def _rect(x1: float, y1: float, x2: float, y2: float) -> ExactPlanarCompound:
    return _compound(_polygon((x1, y1), (x2, y1), (x2, y2), (x1, y2)))


def test_arbitrary_front_back_transform_is_pinned_but_not_called_analytic_exact() -> None:
    front = PlacementTransform(
        anchor_x_mm=10.0,
        anchor_y_mm=20.0,
        rotation_deg=37.0,
        side="front",
    )
    back = front.model_copy(update={"side": "back"})

    assert transform_point((2.0, -1.0), front) == pytest.approx(
        (10.995455996942537, 17.99773444364861), abs=1e-15
    )
    assert transform_point((2.0, -1.0), back) == pytest.approx(
        (7.800913956753366, 20.404994536256805), abs=1e-15
    )


def test_bounded_arbitrary_transform_contains_pinned_37_degree_nominals() -> None:
    expected = {
        "front": (10.995455996942537, 17.99773444364861),
        "back": (7.800913956753366, 20.404994536256805),
    }
    for side, nominal in expected.items():
        transformed = transform_point_bounded(
            (2.0, -1.0),
            PlacementTransform(
                anchor_x_mm=10.0,
                anchor_y_mm=20.0,
                rotation_deg=37.0,
                side=side,
            ),
        )

        assert transformed.point == pytest.approx(nominal, abs=1e-15)
        assert transformed.x_interval.contains(transformed.point[0])
        assert transformed.y_interval.contains(transformed.point[1])
        assert not transformed.exact
        assert math.isfinite(transformed.maximum_error_mm)
        assert transformed.maximum_error_mm > 0


def test_rational_trig_encloses_high_precision_reference_near_quadrant_endpoint() -> None:
    transformed = transform_point_bounded(
        (1.0, 0.0),
        PlacementTransform(
            anchor_x_mm=0.0,
            anchor_y_mm=0.0,
            rotation_deg=89.999,
            side="front",
        ),
    )
    reference_sine = Fraction(
        "0.9999999998476912901105120241781519606446597821718886270305326523363935"
    )
    reference_cosine = Fraction(
        "0.0000174532925190571996135491056851289696691387823732484358336702955020"
    )

    assert transformed.x_interval.contains(reference_cosine)
    assert transformed.y_interval.contains(-reference_sine)
    assert transformed.maximum_error_mm > 0


def test_bounded_arbitrary_transform_does_not_call_libm_trigonometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(_value: float) -> float:
        raise AssertionError("libm trigonometry cannot authorize bounded placement")

    monkeypatch.setattr("pcbsmith.placement_geometry.math.sin", forbidden)
    monkeypatch.setattr("pcbsmith.placement_geometry.math.cos", forbidden)
    transform = PlacementTransform(
        anchor_x_mm=2.0,
        anchor_y_mm=3.0,
        rotation_deg=37.0,
        side="front",
    )

    assert not transform_point_bounded((1.0, 2.0), transform).exact
    assert (
        transform_compound_bounded(_rect(-0.5, -0.5, 0.5, 0.5), transform).authority
        is PlacementTransformAuthority.BOUNDED_APPROXIMATION
    )


def test_quarter_turn_bounded_authority_uses_serialized_rational_anchor_addition() -> None:
    transform = PlacementTransform(
        anchor_x_mm=0.1,
        anchor_y_mm=0.2,
        rotation_deg=90.0,
        side="front",
    )
    transformed = transform_point_bounded((1.0, 0.2), transform)
    compound = transform_compound_bounded(_rect(-0.2, -0.1, 0.2, 0.1), transform)

    assert transformed.point == (0.3, -0.8)
    assert transformed.exact
    assert transformed.maximum_error_mm == 0
    assert transformed.x_interval.lower == transformed.x_interval.upper == Fraction("0.3")
    assert transformed.y_interval.lower == transformed.y_interval.upper == Fraction("-0.8")
    assert compound.authority is PlacementTransformAuthority.EXACT
    assert compound.maximum_error_mm is None


def test_bounded_transform_is_deterministic_and_error_scales_with_radius() -> None:
    transform = PlacementTransform(
        anchor_x_mm=11.0,
        anchor_y_mm=13.0,
        rotation_deg=37.0,
        side="back",
    )
    small = transform_point_bounded((1.0, 1.0), transform)
    large = transform_point_bounded((1000.0, 1000.0), transform)
    local = _compound(_polygon((0.0, 0.0), (2.0, 0.0), (1.5, 1.0), (0.0, 2.0)))
    reversed_local = _compound(_polygon(*tuple(reversed(local.polygons[0].outer))))
    first = transform_compound_bounded(local, transform)
    second = transform_compound_bounded(reversed_local, transform)

    assert math.isfinite(small.maximum_error_mm)
    assert math.isfinite(large.maximum_error_mm)
    assert 0 < small.maximum_error_mm < large.maximum_error_mm
    assert first == second
    assert first.semantic_fingerprint() == second.semantic_fingerprint()


def test_placed_compound_rejects_forged_bounded_error_on_json_revalidation() -> None:
    placed = transform_compound_bounded(
        _rect(-0.5, -0.5, 0.5, 0.5),
        PlacementTransform(
            anchor_x_mm=2.0,
            anchor_y_mm=3.0,
            rotation_deg=37.0,
            side="front",
        ),
    )
    forged = placed.model_copy(update={"maximum_error_mm": None})

    with pytest.raises(ValueError, match="bounded compound transform requires"):
        PlacedCompoundTransform.model_validate_json(forged.model_dump_json())


def test_reflection_recanonicalizes_winding_and_preserves_asymmetric_point_set() -> None:
    local = _compound(
        _polygon((1.0, 1.0), (4.0, 1.0), (4.0, 2.0), (2.0, 2.0), (2.0, 5.0), (1.0, 5.0))
    )
    placed = transform_compound(
        local,
        PlacementTransform(
            anchor_x_mm=0.0,
            anchor_y_mm=0.0,
            rotation_deg=0.0,
            side="back",
        ),
    )

    assert set(placed.polygons[0].outer) == {
        (-1.0, 1.0),
        (-4.0, 1.0),
        (-4.0, 2.0),
        (-2.0, 2.0),
        (-2.0, 5.0),
        (-1.0, 5.0),
    }
    assert placed.polygons[0].outer[0] == min(placed.polygons[0].outer)


def test_quarter_turns_have_no_trigonometric_residue() -> None:
    assert transform_point(
        (1e-20, 2.0),
        PlacementTransform(anchor_x_mm=-0.0, anchor_y_mm=0.0, rotation_deg=90.0, side="front"),
    ) == (2.0, -1e-20)
    assert transform_point(
        (1e-20, 2.0),
        PlacementTransform(anchor_x_mm=0.0, anchor_y_mm=-0.0, rotation_deg=90.0, side="back"),
    ) == (2.0, 1e-20)


def test_signed_zero_is_canonical_but_tiny_coordinate_is_not_snapped() -> None:
    first = _polygon((-0.0, 0.0), (1.0, -0.0), (1.0, 1e-20), (0.0, 1e-20))
    second = _polygon((0.0, -0.0), (1.0, 0.0), (1.0, 1e-20), (-0.0, 1e-20))

    assert first == second
    assert first.semantic_fingerprint() == second.semantic_fingerprint()
    assert any(point[1] == 1e-20 for point in first.outer)
    assert all(str(value) != "-0.0" for point in first.outer for value in point)


def test_boundary_touch_is_distinct_from_interior_overlap() -> None:
    first = _rect(0.0, 0.0, 1.0, 1.0)
    touching = _rect(1.0, 0.0, 2.0, 1.0)
    overlapping = _rect(0.999999999999, 0.0, 2.0, 1.0)

    assert compound_relation(first, touching) is PlanarRelation.BOUNDARY_TOUCH
    assert compound_relation(first, overlapping) is PlanarRelation.INTERIOR_OVERLAP
    assert compound_minimum_squared_distance(first, touching) == Fraction(0)


def test_contained_filled_sets_have_zero_set_distance() -> None:
    outer = _rect(0.0, 0.0, 10.0, 10.0)
    inner = _rect(4.0, 4.0, 6.0, 6.0)

    assert compound_relation(outer, inner) is PlanarRelation.INTERIOR_OVERLAP
    assert compound_minimum_squared_distance(outer, inner) == Fraction(0)
    assert not compound_clearance_at_least(outer, inner, 0.1)


def test_segment_wholly_contained_in_filled_compound_has_zero_set_distance() -> None:
    filled = _rect(0.0, 0.0, 10.0, 10.0)

    witness = compound_to_segment_distance_witness(filled, (2.0, 3.0), (8.0, 3.0))

    assert witness.squared_distance == 0
    assert witness.compound_point == witness.segment_point == (Fraction(2), Fraction(3))

    disjoint = compound_to_segment_distance_witness(filled, (12.0, 2.0), (12.0, 8.0))
    assert disjoint.squared_distance == 4
    assert disjoint.compound_point == (Fraction(10), Fraction(2))
    assert disjoint.segment_point == (Fraction(12), Fraction(2))


def test_segment_in_hole_remains_disjoint_and_uses_hole_boundary_distance() -> None:
    donut = _compound(
        _polygon(
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 10.0),
            (0.0, 10.0),
            holes=(((4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0)),),
        )
    )

    witness = compound_to_segment_distance_witness(donut, (4.5, 5.0), (5.5, 5.0))

    assert witness.squared_distance == Fraction(1, 4)
    assert witness.compound_point == (Fraction(4), Fraction(5))
    assert witness.segment_point == (Fraction(9, 2), Fraction(5))


def test_exact_distance_witness_reports_points_overlap_touch_and_hole_boundaries() -> None:
    first = _rect(0.0, 0.0, 1.0, 1.0)
    separated = _rect(2.0, 0.0, 3.0, 1.0)
    overlap = _rect(0.5, 0.5, 1.5, 1.5)
    touching = _rect(1.0, 0.0, 2.0, 1.0)
    distance = compound_distance_witness(first, separated)
    overlap_witness = compound_distance_witness(first, overlap)
    touch_witness = compound_distance_witness(first, touching)

    assert distance.relation is PlanarRelation.DISJOINT
    assert distance.squared_distance == Fraction(1)
    assert distance.first_point == (Fraction(1), Fraction(0))
    assert distance.second_point == (Fraction(2), Fraction(0))
    assert overlap_witness.relation is PlanarRelation.INTERIOR_OVERLAP
    assert (
        overlap_witness.first_point
        == overlap_witness.second_point
        == (
            Fraction(1, 2),
            Fraction(1, 2),
        )
    )
    assert touch_witness.relation is PlanarRelation.BOUNDARY_TOUCH
    assert (
        touch_witness.first_point
        == touch_witness.second_point
        == (
            Fraction(1),
            Fraction(0),
        )
    )

    donut = _compound(
        _polygon(
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 10.0),
            (0.0, 10.0),
            holes=(((4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0)),),
        )
    )
    inside_hole = _rect(4.5, 4.5, 5.5, 5.5)
    reversed_donut = _compound(
        _polygon(
            *tuple(reversed(donut.polygons[0].outer)),
            holes=tuple(tuple(reversed(hole)) for hole in donut.polygons[0].holes),
        )
    )
    hole_witness = compound_distance_witness(donut, inside_hole)

    assert hole_witness == compound_distance_witness(reversed_donut, inside_hole)
    assert hole_witness.squared_distance == Fraction(1, 4)
    assert hole_witness.first_point == (Fraction(4), Fraction(9, 2))
    assert hole_witness.second_point == (Fraction(9, 2), Fraction(9, 2))
    reversed_witness = compound_distance_witness(inside_hole, donut)
    assert reversed_witness.squared_distance == hole_witness.squared_distance
    assert reversed_witness.first_point == hole_witness.second_point
    assert reversed_witness.second_point == hole_witness.first_point


def test_near_collinear_clearance_uses_decimal_rationals() -> None:
    first = _rect(0.0, 0.0, 1.0, 1.0)
    second = _rect(1.000000000001, 0.0, 2.0, 1.0)

    assert compound_minimum_squared_distance(first, second) == Fraction(1, 10**24)
    assert compound_clearance_at_least(first, second, 1e-12)
    assert not compound_clearance_at_least(first, second, 1.000000000001e-12)


def test_concave_outline_rejects_edge_crossing_notch() -> None:
    allowed = _polygon(
        (0.0, 0.0),
        (8.0, 0.0),
        (8.0, 8.0),
        (5.0, 8.0),
        (5.0, 3.0),
        (3.0, 3.0),
        (3.0, 8.0),
        (0.0, 8.0),
    )

    assert compound_inside_polygon(_rect(0.5, 4.0, 2.5, 6.0), allowed)
    assert not compound_inside_polygon(_rect(2.0, 4.0, 6.0, 6.0), allowed)


def test_allowed_hole_cannot_be_covered_without_boundary_crossing() -> None:
    allowed = _polygon(
        (0.0, 0.0),
        (10.0, 0.0),
        (10.0, 10.0),
        (0.0, 10.0),
        holes=(((4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0)),),
    )

    assert not compound_inside_polygon(_rect(1.0, 1.0, 9.0, 9.0), allowed)
    assert compound_inside_polygon(_rect(1.0, 1.0, 3.0, 3.0), allowed)


def test_polygon_hole_is_empty_for_relations_and_counts_for_boundary_clearance() -> None:
    donut = _compound(
        _polygon(
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 10.0),
            (0.0, 10.0),
            holes=(((4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0)),),
        )
    )
    in_hole = _rect(4.5, 4.5, 5.5, 5.5)
    near_hole = _rect(3.0, 4.5, 3.9, 5.5)

    assert compound_relation(donut, in_hole) is PlanarRelation.DISJOINT
    assert compound_boundary_clearance_at_least(near_hole, donut.polygons[0], 0.1)
    assert not compound_boundary_clearance_at_least(near_hole, donut.polygons[0], 0.100000000001)
