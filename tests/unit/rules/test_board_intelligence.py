from __future__ import annotations

from pcbsmith.rules.board_intelligence import (
    BoardPlacementFrame,
    BoardRoutingRules,
    NetRole,
    RouteStylePolicy,
    RoutingStyle,
    ai_planner_routing_rule_notes,
    board_routing_rules_summary,
    classify_net_role,
    mitered_route_points,
    recommended_trace_width_mm,
    route_segments,
    routed_trace_segments,
    segment_angle_degrees,
    styled_route_points,
    tap_route_points,
    tap_trace_segments,
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


def test_default_board_routing_rules_capture_preferred_trace_style() -> None:
    rules = BoardRoutingRules()

    assert rules.route_style_policy.style is RoutingStyle.PREFER_45
    assert rules.preferred_segment_angles == (0, 45, 90, 135, 180)


def test_board_routing_rules_summary_is_ai_facing_best_practice_contract() -> None:
    assert board_routing_rules_summary() == {
        "routing_style": "prefer_45_mitered",
        "preferred_segment_angles": [0, 45, 90, 135, 180],
        "routing_style_authority": "cad_polish_preference",
        "drc_authority": "hard_rule",
        "trace_width_strategy": "classify_net_role_then_apply_default_width",
        "same_net_topology_preference": "shared_trunk_with_short_branches",
        "notes": [
            "Prefer cardinal or 45-degree trace segments when practical.",
            "Avoid very sharp trace turns; DRC and manufacturability checks win over style.",
            "Prefer shared trunks with short branches for nearby same-net endpoints "
            "when it stays clear and DRC-clean.",
            "Avoid via-in-pad on SMD pads unless an advanced fabrication profile "
            "explicitly allows it.",
        ],
    }


def test_ai_planner_routing_rule_notes_share_the_same_routing_contract() -> None:
    assert ai_planner_routing_rule_notes() == [
        "Prefer 45-degree/mitered PCB routing for CAD polish when practical.",
        "Do not treat 45-degree routing as an electrical hard rule; DRC wins.",
        "Prefer shared same-net trunks with short branches over redundant parallel traces.",
        "Use fanout vias beside SMD pads; via-in-pad requires explicit fabrication support.",
    ]


def test_routed_trace_segments_applies_central_45_degree_preference() -> None:
    segments = routed_trace_segments(
        (
            (0.0, 0.0),
            (6.0, 4.0),
        ),
        net_name="LED_A",
    )

    assert [(segment.start, segment.end) for segment in segments] == [
        ((0.0, 0.0), (4.5, 0.0)),
        ((4.5, 0.0), (6.0, 1.5)),
        ((6.0, 1.5), (6.0, 4.0)),
    ]
    assert [segment.width_mm for segment in segments] == [0.35, 0.35, 0.35]
    assert [segment_angle_degrees(segment.start, segment.end) for segment in segments] == [
        0,
        45,
        90,
    ]


def test_tap_trace_segments_uses_same_central_rules() -> None:
    segments = tap_trace_segments(
        (10.0, 0.0),
        (10.0, 8.0),
        net_name="GND",
        side=-1,
    )

    assert [segment.width_mm for segment in segments] == [0.45, 0.45, 0.45]
    assert [segment_angle_degrees(segment.start, segment.end) for segment in segments] == [
        135,
        90,
        45,
    ]


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


def test_styled_route_points_can_keep_orthogonal_routing() -> None:
    points = styled_route_points(
        (
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 10.0),
        ),
        policy=RouteStylePolicy(style=RoutingStyle.ORTHOGONAL),
    )

    assert points == ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0))


def test_tap_route_points_uses_45_degree_preference_when_enabled() -> None:
    points = tap_route_points(
        (10.0, 0.0),
        (10.0, 8.0),
        side=-1,
        policy=RouteStylePolicy(style=RoutingStyle.PREFER_45, chamfer_mm=1.5),
    )

    assert points == (
        (10.0, 0.0),
        (8.5, 1.5),
        (8.5, 6.5),
        (10.0, 8.0),
    )
    assert [segment_angle_degrees(*segment) for segment in route_segments(points)] == [
        135,
        90,
        45,
    ]


def test_tap_route_points_can_keep_direct_orthogonal_taps() -> None:
    points = tap_route_points(
        (10.0, 0.0),
        (10.0, 8.0),
        side=-1,
        policy=RouteStylePolicy(style=RoutingStyle.ORTHOGONAL),
    )

    assert points == ((10.0, 0.0), (10.0, 8.0))
