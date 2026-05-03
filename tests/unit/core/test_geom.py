from __future__ import annotations

from hypothesis import given, strategies as st

from pcbsmith.core.geom import Box, Point, Vec, mm_to_nm, nm_to_mm, snap


def test_point_from_mm_round_trips_to_nm() -> None:
    assert Point.from_mm(12.7, 0.0) == Point(12_700_000, 0)


def test_mm_nm_rounding_policy() -> None:
    assert mm_to_nm(0.0000005) == 1
    assert mm_to_nm(0.0000004) == 0
    assert nm_to_mm(1_000_000) == 1.0


@given(
    x=st.integers(-10**12, 10**12),
    y=st.integers(-10**12, 10**12),
    dx=st.integers(-10**12, 10**12),
    dy=st.integers(-10**12, 10**12),
)
def test_point_add_sub_inverse(x: int, y: int, dx: int, dy: int) -> None:
    point = Point(x, y)
    vector = Vec(dx, dy)
    assert (point + vector) - point == vector


@given(x=st.integers(0, 10**9), y=st.integers(0, 10**9))
def test_snap_is_idempotent(x: int, y: int) -> None:
    grid = 1_270_000
    point = Point(x, y)
    once = snap(point, grid)
    twice = snap(once, grid)
    assert once == twice
    assert once.x % grid == 0
    assert once.y % grid == 0


def test_box_contains_closed_edges() -> None:
    box = Box(0, 0, 1000, 1000)
    assert box.contains(Point(0, 0))
    assert box.contains(Point(1000, 1000))
    assert not box.contains(Point(1001, 1000))


def test_box_intersection_counts_touching_edges() -> None:
    left = Box(0, 0, 100, 100)
    right = Box(100, 0, 200, 100)
    far = Box(101, 0, 200, 100)
    assert left.intersects(right)
    assert not left.intersects(far)
