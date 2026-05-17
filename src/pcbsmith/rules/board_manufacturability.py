from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from math import acos, degrees, hypot, isclose
from pathlib import Path

from pcbsmith.core.board import Board, Layer, Trace
from pcbsmith.core.geom import Point
from pcbsmith.core.project import DesignRules
from pcbsmith.rules.board_intelligence import (
    PREFERRED_SEGMENT_ANGLES,
    route_segments,
    segment_angle_degrees,
)

PREFERRED_TRACE_ANGLES = frozenset(PREFERRED_SEGMENT_ANGLES)
DEFAULT_MIN_TURN_DEGREES = 30
BOARD_MANUFACTURABILITY_SCHEMA = "pcbsmith-board-manufacturability-v1"


class ManufacturabilitySeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class BoardManufacturabilityFinding:
    severity: ManufacturabilitySeverity
    code: str
    message: str
    location: str


@dataclass(frozen=True)
class BoardManufacturabilityReport:
    findings: tuple[BoardManufacturabilityFinding, ...]

    @property
    def exit_code(self) -> int:
        return (
            1
            if any(finding.severity is ManufacturabilitySeverity.ERROR for finding in self.findings)
            else 0
        )


def inspect_board_manufacturability(
    board: Board,
    *,
    design_rules: DesignRules | None = None,
    min_turn_degrees: int = DEFAULT_MIN_TURN_DEGREES,
) -> BoardManufacturabilityReport:
    rules = design_rules or DesignRules()
    findings: list[BoardManufacturabilityFinding] = []
    copper_traces = tuple(
        trace for trace in board.traces if trace.layer in {Layer.F_CU, Layer.B_CU}
    )

    for trace_index, trace in enumerate(copper_traces, start=1):
        findings.extend(
            _trace_style_findings(trace, trace_index, min_turn_degrees=min_turn_degrees)
        )

    findings.extend(_trace_clearance_findings(copper_traces, rules))
    return BoardManufacturabilityReport(findings=tuple(findings))


def format_board_manufacturability_report(
    report: BoardManufacturabilityReport,
) -> list[str]:
    if not report.findings:
        return ["Board manufacturability: passed (0 findings)"]

    lines = [f"Board manufacturability: {len(report.findings)} finding(s)"]
    lines.extend(
        f"{finding.severity}: {finding.code}: {finding.message} ({finding.location})"
        for finding in report.findings
    )
    return lines


def write_board_manufacturability_report(
    report: BoardManufacturabilityReport,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(_report_data(report), indent=2) + "\n",
        encoding="utf-8",
    )


def _report_data(report: BoardManufacturabilityReport) -> dict[str, object]:
    errors = tuple(
        finding
        for finding in report.findings
        if finding.severity is ManufacturabilitySeverity.ERROR
    )
    warnings = tuple(
        finding
        for finding in report.findings
        if finding.severity is ManufacturabilitySeverity.WARNING
    )
    return {
        "schema": BOARD_MANUFACTURABILITY_SCHEMA,
        "summary": {
            "finding_count": len(report.findings),
            "error_count": len(errors),
            "warning_count": len(warnings),
        },
        "findings": [
            {
                "severity": finding.severity.value,
                "code": finding.code,
                "message": finding.message,
                "location": finding.location,
            }
            for finding in report.findings
        ],
    }


def _trace_style_findings(
    trace: Trace,
    trace_index: int,
    *,
    min_turn_degrees: int,
) -> tuple[BoardManufacturabilityFinding, ...]:
    points = tuple((_mm(point.x), _mm(point.y)) for point in trace.points)
    findings: list[BoardManufacturabilityFinding] = []
    for segment_index, (start, end) in enumerate(route_segments(points), start=1):
        angle = segment_angle_degrees(start, end)
        if angle not in PREFERRED_TRACE_ANGLES:
            findings.append(
                BoardManufacturabilityFinding(
                    severity=ManufacturabilitySeverity.WARNING,
                    code="non_preferred_trace_angle",
                    message=(
                        f"Trace {trace.net_name} uses {angle} degree routing; "
                        "prefer cardinal or 45-degree segments when practical"
                    ),
                    location=f"trace {trace_index} segment {segment_index}",
                )
            )

    for point_index in range(1, len(trace.points) - 1):
        turn_angle = _turn_angle_degrees(
            trace.points[point_index - 1],
            trace.points[point_index],
            trace.points[point_index + 1],
        )
        if 0 < turn_angle < min_turn_degrees:
            findings.append(
                BoardManufacturabilityFinding(
                    severity=ManufacturabilitySeverity.WARNING,
                    code="sharp_trace_turn",
                    message=(
                        f"Trace {trace.net_name} has a {turn_angle:.1f} degree turn; "
                        "avoid very sharp copper corners when practical"
                    ),
                    location=f"trace {trace_index} point {point_index + 1}",
                )
            )

    return tuple(findings)


def _trace_clearance_findings(
    traces: tuple[Trace, ...],
    rules: DesignRules,
) -> tuple[BoardManufacturabilityFinding, ...]:
    findings: list[BoardManufacturabilityFinding] = []
    for left_index, left in enumerate(traces, start=1):
        for right_index, right in enumerate(traces[left_index:], start=left_index + 1):
            if left.layer != right.layer or left.net_name == right.net_name:
                continue
            clearance = _trace_pair_clearance(left, right)
            if clearance < rules.min_clearance:
                findings.append(
                    BoardManufacturabilityFinding(
                        severity=ManufacturabilitySeverity.ERROR,
                        code="trace_clearance_risk",
                        message=(
                            f"{left.net_name} and {right.net_name} clearance is "
                            f"{_format_mm(clearance)} mm; required "
                            f"{_format_mm(rules.min_clearance)} mm"
                        ),
                        location=f"trace {left_index} to trace {right_index} on {left.layer}",
                    )
                )
    return tuple(findings)


def _trace_pair_clearance(left: Trace, right: Trace) -> float:
    left_segments = tuple(zip(left.points, left.points[1:], strict=False))
    right_segments = tuple(zip(right.points, right.points[1:], strict=False))
    centerline_distance = min(
        _segment_distance(left_start, left_end, right_start, right_end)
        for left_start, left_end in left_segments
        for right_start, right_end in right_segments
    )
    return centerline_distance - (left.width / 2) - (right.width / 2)


def _segment_distance(a: Point, b: Point, c: Point, d: Point) -> float:
    if _segments_intersect(a, b, c, d):
        return 0.0
    return min(
        _point_segment_distance(a, c, d),
        _point_segment_distance(b, c, d),
        _point_segment_distance(c, a, b),
        _point_segment_distance(d, a, b),
    )


def _point_segment_distance(point: Point, start: Point, end: Point) -> float:
    dx = end.x - start.x
    dy = end.y - start.y
    if dx == 0 and dy == 0:
        return hypot(point.x - start.x, point.y - start.y)

    raw_t = ((point.x - start.x) * dx + (point.y - start.y) * dy) / ((dx * dx) + (dy * dy))
    t = max(0.0, min(1.0, raw_t))
    projection_x = start.x + t * dx
    projection_y = start.y + t * dy
    return hypot(point.x - projection_x, point.y - projection_y)


def _segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    o1 = _orientation(a, b, c)
    o2 = _orientation(a, b, d)
    o3 = _orientation(c, d, a)
    o4 = _orientation(c, d, b)

    if o1 != o2 and o3 != o4:
        return True
    return (
        (o1 == 0 and _on_segment(a, c, b))
        or (o2 == 0 and _on_segment(a, d, b))
        or (o3 == 0 and _on_segment(c, a, d))
        or (o4 == 0 and _on_segment(c, b, d))
    )


def _orientation(a: Point, b: Point, c: Point) -> int:
    value = ((b.y - a.y) * (c.x - b.x)) - ((b.x - a.x) * (c.y - b.y))
    if value == 0:
        return 0
    return 1 if value > 0 else 2


def _on_segment(a: Point, b: Point, c: Point) -> bool:
    return (
        min(a.x, c.x) <= b.x <= max(a.x, c.x)
        and min(a.y, c.y) <= b.y <= max(a.y, c.y)
    )


def _turn_angle_degrees(previous: Point, current: Point, following: Point) -> float:
    incoming = (current.x - previous.x, current.y - previous.y)
    outgoing = (following.x - current.x, following.y - current.y)
    incoming_length = hypot(*incoming)
    outgoing_length = hypot(*outgoing)
    if isclose(incoming_length, 0.0) or isclose(outgoing_length, 0.0):
        return 0.0

    dot = (incoming[0] * outgoing[0]) + (incoming[1] * outgoing[1])
    cosine = max(-1.0, min(1.0, dot / (incoming_length * outgoing_length)))
    return degrees(acos(cosine))


def _mm(value_nm: int) -> float:
    return value_nm / 1_000_000


def _format_mm(value_nm: float) -> str:
    return f"{_mm(round(value_nm)):.3f}"
