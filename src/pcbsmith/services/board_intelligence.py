from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from math import atan2, degrees, isclose


class NetRole(StrEnum):
    POWER = "power"
    GROUND = "ground"
    SIGNAL = "signal"
    TIMING = "timing"
    LED_STRING = "led_string"
    CONTROL = "control"


class RoutingStyle(StrEnum):
    ORTHOGONAL = "orthogonal"
    PREFER_45 = "prefer_45"


@dataclass(frozen=True)
class RouteStylePolicy:
    style: RoutingStyle = RoutingStyle.PREFER_45
    chamfer_mm: float = 1.5


DEFAULT_ROUTE_STYLE_POLICY = RouteStylePolicy()
PREFERRED_SEGMENT_ANGLES = (0, 45, 90, 135, 180)


@dataclass(frozen=True)
class BoardRoutingRules:
    route_style_policy: RouteStylePolicy = DEFAULT_ROUTE_STYLE_POLICY
    preferred_segment_angles: tuple[int, ...] = PREFERRED_SEGMENT_ANGLES


DEFAULT_BOARD_ROUTING_RULES = BoardRoutingRules()


@dataclass(frozen=True)
class RoutedTraceSegment:
    start: tuple[float, float]
    end: tuple[float, float]
    width_mm: float


@dataclass(frozen=True)
class BoardPlacementFrame:
    origin_mm: tuple[float, float]
    size_mm: tuple[float, float]

    @property
    def outline_start_mm(self) -> tuple[float, float]:
        return self.origin_mm

    @property
    def outline_end_mm(self) -> tuple[float, float]:
        return (
            self.origin_mm[0] + self.size_mm[0],
            self.origin_mm[1] + self.size_mm[1],
        )

    def point(self, local_x_mm: float, local_y_mm: float) -> tuple[float, float]:
        return (self.origin_mm[0] + local_x_mm, self.origin_mm[1] + local_y_mm)


def classify_net_role(net_name: str) -> NetRole:
    normalized = net_name.strip().upper()
    if normalized in {"GND", "GROUND", "VSS", "0V"}:
        return NetRole.GROUND
    if (
        normalized in {"VCC", "VDD", "VIN", "VBAT"}
        or normalized.endswith("V")
        or re.fullmatch(r"\+?\d+V\d*", normalized) is not None
    ):
        return NetRole.POWER
    if "TIM" in normalized or normalized in {"DISCH", "THRESH", "TRIG"}:
        return NetRole.TIMING
    if normalized.startswith("LED") or "_LED" in normalized:
        return NetRole.LED_STRING
    if normalized in {"CTRL", "CONTROL", "RESET", "EN", "ENABLE"}:
        return NetRole.CONTROL
    return NetRole.SIGNAL


def recommended_trace_width_mm(role: NetRole) -> float:
    return {
        NetRole.POWER: 0.45,
        NetRole.GROUND: 0.45,
        NetRole.LED_STRING: 0.35,
        NetRole.TIMING: 0.3,
        NetRole.CONTROL: 0.3,
        NetRole.SIGNAL: 0.3,
    }[role]


def board_routing_rules_summary(
    rules: BoardRoutingRules = DEFAULT_BOARD_ROUTING_RULES,
) -> dict[str, object]:
    return {
        "routing_style": "prefer_45_mitered",
        "preferred_segment_angles": list(rules.preferred_segment_angles),
        "routing_style_authority": "cad_polish_preference",
        "drc_authority": "hard_rule",
        "trace_width_strategy": "classify_net_role_then_apply_default_width",
        "notes": [
            "Prefer cardinal or 45-degree trace segments when practical.",
            "Avoid very sharp trace turns; DRC and manufacturability checks win over style.",
        ],
    }


def ai_planner_routing_rule_notes() -> list[str]:
    return [
        "Prefer 45-degree/mitered PCB routing for CAD polish when practical.",
        "Do not treat 45-degree routing as an electrical hard rule; DRC wins.",
    ]


def routed_trace_segments(
    points: tuple[tuple[float, float], ...],
    *,
    net_name: str,
    width_mm: float | None = None,
    rules: BoardRoutingRules = DEFAULT_BOARD_ROUTING_RULES,
    preserved_points: tuple[tuple[float, float], ...] = (),
) -> tuple[RoutedTraceSegment, ...]:
    trace_width_mm = width_mm or recommended_trace_width_mm(classify_net_role(net_name))
    routed_points = styled_route_points(
        _insert_preferred_doglegs(
            points,
            preferred_angles=rules.preferred_segment_angles,
        ),
        policy=rules.route_style_policy,
        preserved_points=preserved_points,
    )
    return tuple(
        RoutedTraceSegment(start=start, end=end, width_mm=trace_width_mm)
        for start, end in route_segments(routed_points)
    )


def tap_trace_segments(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    net_name: str,
    width_mm: float | None = None,
    side: int = 1,
    rules: BoardRoutingRules = DEFAULT_BOARD_ROUTING_RULES,
) -> tuple[RoutedTraceSegment, ...]:
    return routed_trace_segments(
        tap_route_points(start, end, side=side, policy=rules.route_style_policy),
        net_name=net_name,
        width_mm=width_mm,
        rules=rules,
    )


def styled_route_points(
    points: tuple[tuple[float, float], ...],
    *,
    policy: RouteStylePolicy = DEFAULT_ROUTE_STYLE_POLICY,
    preserved_points: tuple[tuple[float, float], ...] = (),
) -> tuple[tuple[float, float], ...]:
    if policy.style is RoutingStyle.ORTHOGONAL:
        return _dedupe_points(points)
    return mitered_route_points(
        points,
        chamfer_mm=policy.chamfer_mm,
        preserved_points=preserved_points,
    )


def tap_route_points(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    side: int = 1,
    policy: RouteStylePolicy = DEFAULT_ROUTE_STYLE_POLICY,
) -> tuple[tuple[float, float], ...]:
    if policy.style is RoutingStyle.ORTHOGONAL:
        return _dedupe_points((start, end))

    side_multiplier = -1 if side < 0 else 1
    if isclose(start[0], end[0]):
        vertical_distance = abs(end[1] - start[1])
        offset = min(policy.chamfer_mm, vertical_distance / 2.0)
        direction = 1 if end[1] > start[1] else -1
        side_x = _clean_float(start[0] + side_multiplier * offset)
        return _dedupe_points(
            (
                start,
                (side_x, _clean_float(start[1] + direction * offset)),
                (side_x, _clean_float(end[1] - direction * offset)),
                end,
            )
        )

    if isclose(start[1], end[1]):
        horizontal_distance = abs(end[0] - start[0])
        offset = min(policy.chamfer_mm, horizontal_distance / 2.0)
        direction = 1 if end[0] > start[0] else -1
        side_y = _clean_float(start[1] + side_multiplier * offset)
        return _dedupe_points(
            (
                start,
                (_clean_float(start[0] + direction * offset), side_y),
                (_clean_float(end[0] - direction * offset), side_y),
                end,
            )
        )

    return styled_route_points((start, end), policy=policy)


def mitered_route_points(
    points: tuple[tuple[float, float], ...],
    *,
    chamfer_mm: float = 1.5,
    preserved_points: tuple[tuple[float, float], ...] = (),
) -> tuple[tuple[float, float], ...]:
    if len(points) < 3:
        return _dedupe_points(points)

    preserved = set(preserved_points)
    route: list[tuple[float, float]] = [points[0]]
    for index in range(1, len(points) - 1):
        previous = points[index - 1]
        current = points[index]
        following = points[index + 1]
        if current in preserved:
            route.append(current)
            continue
        if not _is_axis_aligned_turn(previous, current, following):
            route.append(current)
            continue

        incoming = _axis_distance(previous, current)
        outgoing = _axis_distance(current, following)
        actual_chamfer = min(chamfer_mm, incoming / 2.0, outgoing / 2.0)
        if actual_chamfer <= 0:
            route.append(current)
            continue

        route.append(_point_toward(current, previous, actual_chamfer))
        route.append(_point_toward(current, following, actual_chamfer))

    route.append(points[-1])
    return _dedupe_points(tuple(route))


def route_segments(
    points: tuple[tuple[float, float], ...],
) -> tuple[tuple[tuple[float, float], tuple[float, float]], ...]:
    return tuple(
        (start, end)
        for start, end in zip(points, points[1:], strict=False)
        if start != end
    )


def segment_angle_degrees(
    start: tuple[float, float],
    end: tuple[float, float],
) -> int:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    angle = round(degrees(atan2(dy, dx)))
    while angle < 0:
        angle += 180
    while angle > 180:
        angle -= 180
    return angle


def _is_axis_aligned_turn(
    previous: tuple[float, float],
    current: tuple[float, float],
    following: tuple[float, float],
) -> bool:
    incoming_horizontal = isclose(previous[1], current[1])
    incoming_vertical = isclose(previous[0], current[0])
    outgoing_horizontal = isclose(current[1], following[1])
    outgoing_vertical = isclose(current[0], following[0])
    return (incoming_horizontal and outgoing_vertical) or (
        incoming_vertical and outgoing_horizontal
    )


def _insert_preferred_doglegs(
    points: tuple[tuple[float, float], ...],
    *,
    preferred_angles: tuple[int, ...],
) -> tuple[tuple[float, float], ...]:
    if len(points) < 2:
        return points

    routed: list[tuple[float, float]] = [points[0]]
    for end in points[1:]:
        start = routed[-1]
        if start == end:
            continue
        if segment_angle_degrees(start, end) not in preferred_angles:
            bend = _dogleg_bend(start, end)
            if bend != start and bend != end:
                routed.append(bend)
        routed.append(end)
    return _dedupe_points(tuple(routed))


def _dogleg_bend(
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[float, float]:
    dx = abs(end[0] - start[0])
    dy = abs(end[1] - start[1])
    if dx >= dy:
        return (end[0], start[1])
    return (start[0], end[1])


def _axis_distance(
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    return abs(end[0] - start[0]) + abs(end[1] - start[1])


def _point_toward(
    start: tuple[float, float],
    end: tuple[float, float],
    distance_mm: float,
) -> tuple[float, float]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if not isclose(dx, 0.0):
        return (_clean_float(start[0] + (distance_mm if dx > 0 else -distance_mm)), start[1])
    return (start[0], _clean_float(start[1] + (distance_mm if dy > 0 else -distance_mm)))


def _dedupe_points(
    points: tuple[tuple[float, float], ...],
) -> tuple[tuple[float, float], ...]:
    deduped: list[tuple[float, float]] = []
    for point in points:
        if deduped and deduped[-1] == point:
            continue
        deduped.append(point)
    return tuple(deduped)


def _clean_float(value: float) -> float:
    rounded = round(value, 6)
    return int(rounded) if rounded.is_integer() else rounded
