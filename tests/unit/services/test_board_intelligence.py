from __future__ import annotations

from pcbsmith.services.board_intelligence import (
    BoardPlacementFrame,
    NetRole,
    classify_net_role,
    mitered_route_points,
    recommended_trace_width_mm,
    route_segments,
    segment_angle_degrees,
)


def test_classify_net_role_uses_known_electrical_names() -> None:
    assert classify_net_role("VCC") is NetRole.POWER
    assert classify_net_role("5V") is NetRole.POWER
    assert classify_net_role("+3V3") is NetRole.POWER
    assert classify_net_role("GND") is NetRole.GROUND
    assert classify_net_role("TIMING") is NetRole.TIMING
    assert classify_net_role("LED_A") is NetRole.LED_STRING
    assert classify_net_role("CTRL") is NetRole.CONTROL
    assert classify_net_role("OUT") is NetRole.SIGNAL


def test_board_placement_frame_translates_local_points_to_page_points() -> None:
    frame = BoardPlacementFrame(origin_mm=(60.0, 35.0), size_mm=(94.0, 61.0))

    assert frame.point(0.0, 0.0) == (60.0, 35.0)
    assert frame.point(35.0, 25.0) == (95.0, 60.0)
    assert frame.outline_start_mm == (60.0, 35.0)
    assert frame.outline_end_mm == (154.0, 96.0)


def test_recommended_trace_width_uses_net_role_defaults() -> None:
    assert recommended_trace_width_mm(NetRole.POWER) == 0.45
    assert recommended_trace_width_mm(NetRole.GROUND) == 0.45
    assert recommended_trace_width_mm(NetRole.LED_STRING) == 0.35
    assert recommended_trace_width_mm(NetRole.SIGNAL) == 0.3


def test_mitered_route_points_replaces_right_angle_with_45_degree_bends() -> None:
    points = mitered_route_points(
        (
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 10.0),
        ),
        chamfer_mm=2.0,
    )

    assert points == (
        (0.0, 0.0),
        (8.0, 0.0),
        (10.0, 2.0),
        (10.0, 10.0),
    )
    assert [segment_angle_degrees(*segment) for segment in route_segments(points)] == [
        0,
        45,
        90,
    ]


def test_mitered_route_points_keeps_straight_routes_unchanged() -> None:
    points = mitered_route_points(
        (
            (0.0, 0.0),
            (10.0, 0.0),
        ),
        chamfer_mm=2.0,
    )

    assert points == ((0.0, 0.0), (10.0, 0.0))
    assert route_segments(points) == (((0.0, 0.0), (10.0, 0.0)),)


def test_mitered_route_points_preserves_declared_junction_points() -> None:
    points = mitered_route_points(
        (
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 10.0),
        ),
        chamfer_mm=2.0,
        preserved_points=((10.0, 0.0),),
    )

    assert points == (
        (0.0, 0.0),
        (10.0, 0.0),
        (10.0, 10.0),
    )
