from __future__ import annotations

import math

import pytest

from pcbsmith.kicad.board_region import (
    BoardCutoutPolygon,
    canonical_simple_polygon,
    validate_cutouts,
)

OUTER = ((0.0, 0.0), (12.0, 0.0), (12.0, 10.0), (0.0, 10.0))


def _cutout(points: tuple[tuple[float, float], ...]) -> BoardCutoutPolygon:
    return BoardCutoutPolygon(points=points)


def test_cutout_winding_start_and_closing_point_are_canonical() -> None:
    one = _cutout(((2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)))
    two = _cutout(((4.0, 4.0), (4.0, 2.0), (2.0, 2.0), (2.0, 4.0), (4.0, 4.0)))

    assert one == two
    assert one.points[0] == (2.0, 2.0)
    assert one.semantic_fingerprint() == two.semantic_fingerprint()


@pytest.mark.parametrize(
    "points",
    (
        ((1.0, 1.0), (2.0, 2.0)),
        ((1.0, 1.0), (2.0, 2.0), (3.0, 3.0)),
        ((1.0, 1.0), (3.0, 3.0), (1.0, 3.0), (3.0, 1.0)),
        ((1.0, 1.0), (2.0, 1.0), (math.inf, 2.0)),
        ((1.0, 1.0), (2.0, 1.0), (1.0, 1.0), (1.0, 2.0)),
    ),
)
def test_invalid_polygon_geometry_is_rejected(
    points: tuple[tuple[float, float], ...],
) -> None:
    with pytest.raises(ValueError):
        BoardCutoutPolygon(points=points)


@pytest.mark.parametrize(
    "points",
    (
        ((0.0, 2.0), (2.0, 2.0), (2.0, 4.0), (0.0, 4.0)),
        ((10.0, 2.0), (13.0, 2.0), (13.0, 4.0), (10.0, 4.0)),
    ),
)
def test_cutout_touching_or_crossing_outer_boundary_is_rejected(
    points: tuple[tuple[float, float], ...],
) -> None:
    with pytest.raises(ValueError, match="strictly inside|touch or cross"):
        validate_cutouts(OUTER, (_cutout(points),))


@pytest.mark.parametrize(
    "second",
    (
        ((4.0, 3.0), (6.0, 3.0), (6.0, 5.0), (4.0, 5.0)),
        ((3.0, 3.0), (5.0, 3.0), (5.0, 5.0), (3.0, 5.0)),
        ((2.5, 2.5), (3.5, 2.5), (3.5, 3.5), (2.5, 3.5)),
    ),
)
def test_cutouts_touching_overlapping_or_contained_are_rejected(
    second: tuple[tuple[float, float], ...],
) -> None:
    first = _cutout(((2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)))
    with pytest.raises(ValueError, match="cannot touch"):
        validate_cutouts(OUTER, (first, _cutout(second)))


def test_disjoint_cutouts_are_canonical_and_order_independent() -> None:
    left = _cutout(((2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)))
    right = _cutout(((8.0, 6.0), (10.0, 6.0), (10.0, 8.0), (8.0, 8.0)))

    assert validate_cutouts(OUTER, (right, left)) == (left, right)
    with pytest.raises(ValueError, match="duplicate"):
        validate_cutouts(OUTER, (left, left))


def test_concave_outer_and_cutout_are_validated_exactly() -> None:
    outer = (
        (0.0, 0.0),
        (10.0, 0.0),
        (10.0, 10.0),
        (6.0, 10.0),
        (6.0, 4.0),
        (4.0, 4.0),
        (4.0, 10.0),
        (0.0, 10.0),
    )
    valid = _cutout(((1.0, 5.0), (3.0, 5.0), (3.0, 8.0), (1.0, 8.0)))
    in_notch = _cutout(((4.5, 5.0), (5.5, 5.0), (5.5, 7.0), (4.5, 7.0)))

    assert validate_cutouts(outer, (valid,)) == (valid,)
    with pytest.raises(ValueError, match="strictly inside"):
        validate_cutouts(outer, (in_notch,))


def test_outer_canonicalization_is_input_order_invariant() -> None:
    reverse_rotated = ((12.0, 10.0), (12.0, 0.0), (0.0, 0.0), (0.0, 10.0))
    assert canonical_simple_polygon(OUTER) == canonical_simple_polygon(reverse_rotated)
