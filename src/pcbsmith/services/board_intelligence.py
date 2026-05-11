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
