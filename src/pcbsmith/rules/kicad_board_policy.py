from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pcbsmith.rules.board_intelligence import PREFERRED_SEGMENT_ANGLES, segment_angle_degrees

KICAD_BOARD_POLICY_SCHEMA = "pcbsmith-kicad-board-policy-v1"
DEFAULT_PAD_KEEP_OUT_MM = 0.05


class KiCadBoardPolicySeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class KiCadBoardPolicyFinding:
    severity: KiCadBoardPolicySeverity
    code: str
    message: str
    location: str


@dataclass(frozen=True)
class KiCadBoardPolicyReport:
    findings: tuple[KiCadBoardPolicyFinding, ...]

    @property
    def exit_code(self) -> int:
        return (
            1
            if any(finding.severity is KiCadBoardPolicySeverity.ERROR for finding in self.findings)
            else 0
        )


@dataclass(frozen=True)
class _Segment:
    start: tuple[float, float]
    end: tuple[float, float]
    width_mm: float
    layer: str
    net_number: int


@dataclass(frozen=True)
class _Via:
    at: tuple[float, float]
    net_number: int


@dataclass(frozen=True)
class _SmdPad:
    footprint: str
    pad: str
    center: tuple[float, float]
    size: tuple[float, float]
    net_number: int


def inspect_kicad_board_policy(board_text: str) -> KiCadBoardPolicyReport:
    net_names = _parse_net_names(board_text)
    segments = _parse_segments(board_text)
    vias = _parse_vias(board_text)
    pads = _parse_smd_pads(board_text)

    findings: list[KiCadBoardPolicyFinding] = []
    findings.extend(_route_style_findings(segments, net_names))
    findings.extend(_trace_width_findings(segments, net_names))
    findings.extend(_via_pad_findings(vias, pads, net_names))
    return KiCadBoardPolicyReport(tuple(findings))


def write_kicad_board_policy_report(
    report: KiCadBoardPolicyReport,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(_report_data(report), indent=2) + "\n",
        encoding="utf-8",
    )


def _report_data(report: KiCadBoardPolicyReport) -> dict[str, object]:
    errors = tuple(
        finding
        for finding in report.findings
        if finding.severity is KiCadBoardPolicySeverity.ERROR
    )
    warnings = tuple(
        finding
        for finding in report.findings
        if finding.severity is KiCadBoardPolicySeverity.WARNING
    )
    return {
        "schema": KICAD_BOARD_POLICY_SCHEMA,
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


def _route_style_findings(
    segments: tuple[_Segment, ...],
    net_names: dict[int, str],
) -> tuple[KiCadBoardPolicyFinding, ...]:
    preferred_angles = frozenset(PREFERRED_SEGMENT_ANGLES)
    findings: list[KiCadBoardPolicyFinding] = []
    for index, segment in enumerate(segments, start=1):
        angle = segment_angle_degrees(segment.start, segment.end)
        if angle in preferred_angles:
            continue
        findings.append(
            KiCadBoardPolicyFinding(
                severity=KiCadBoardPolicySeverity.WARNING,
                code="non_preferred_trace_angle",
                message=(
                    f"{_net_label(segment.net_number, net_names)} uses {angle} degree "
                    "routing; prefer straight, cardinal, or 45-degree segments when practical"
                ),
                location=f"segment {index} on {segment.layer}",
            )
        )
    return tuple(findings)


def _trace_width_findings(
    segments: tuple[_Segment, ...],
    net_names: dict[int, str],
) -> tuple[KiCadBoardPolicyFinding, ...]:
    widths_by_net: dict[int, set[float]] = {}
    for segment in segments:
        widths_by_net.setdefault(segment.net_number, set()).add(round(segment.width_mm, 3))

    findings: list[KiCadBoardPolicyFinding] = []
    for net_number, widths in sorted(widths_by_net.items()):
        if len(widths) <= 1:
            continue
        formatted = ", ".join(f"{width:g} mm" for width in sorted(widths))
        findings.append(
            KiCadBoardPolicyFinding(
                severity=KiCadBoardPolicySeverity.WARNING,
                code="inconsistent_trace_width",
                message=(
                    f"{_net_label(net_number, net_names)} uses multiple trace widths "
                    f"({formatted}); require a net-class or fanout reason"
                ),
                location=f"net {net_number}",
            )
        )
    return tuple(findings)


def _via_pad_findings(
    vias: tuple[_Via, ...],
    pads: tuple[_SmdPad, ...],
    net_names: dict[int, str],
) -> tuple[KiCadBoardPolicyFinding, ...]:
    findings: list[KiCadBoardPolicyFinding] = []
    for via_index, via in enumerate(vias, start=1):
        for pad in pads:
            if _point_inside_pad_keepout(via.at, pad):
                findings.append(
                    KiCadBoardPolicyFinding(
                        severity=KiCadBoardPolicySeverity.ERROR,
                        code="via_in_smd_pad_keepout",
                        message=(
                            f"Via on {_net_label(via.net_number, net_names)} sits inside "
                            f"or too close to SMD pad {pad.footprint}.{pad.pad}; use a "
                            "fanout via beside the pad unless via-in-pad fabrication is explicit"
                        ),
                        location=f"via {via_index} at {via.at[0]:g},{via.at[1]:g}",
                    )
                )
    return tuple(findings)


def _point_inside_pad_keepout(point: tuple[float, float], pad: _SmdPad) -> bool:
    half_width = (pad.size[0] / 2.0) + DEFAULT_PAD_KEEP_OUT_MM
    half_height = (pad.size[1] / 2.0) + DEFAULT_PAD_KEEP_OUT_MM
    return (
        pad.center[0] - half_width <= point[0] <= pad.center[0] + half_width
        and pad.center[1] - half_height <= point[1] <= pad.center[1] + half_height
    )


def _parse_net_names(board_text: str) -> dict[int, str]:
    return {
        int(match.group("number")): match.group("name")
        for match in re.finditer(
            r'\(net\s+(?P<number>\d+)\s+"(?P<name>[^"]*)"\)',
            board_text,
        )
    }


def _parse_segments(board_text: str) -> tuple[_Segment, ...]:
    pattern = re.compile(
        r"\(segment\s+"
        r"\(start (?P<start_x>-?\d+(?:\.\d+)?) (?P<start_y>-?\d+(?:\.\d+)?)\)\s+"
        r"\(end (?P<end_x>-?\d+(?:\.\d+)?) (?P<end_y>-?\d+(?:\.\d+)?)\)\s+"
        r"\(width (?P<width>\d+(?:\.\d+)?)\)\s+"
        r'\(layer "(?P<layer>[^"]+)"\)\s+'
        r"\(net (?P<net>\d+)\)",
        re.MULTILINE,
    )
    return tuple(
        _Segment(
            start=(float(match.group("start_x")), float(match.group("start_y"))),
            end=(float(match.group("end_x")), float(match.group("end_y"))),
            width_mm=float(match.group("width")),
            layer=match.group("layer"),
            net_number=int(match.group("net")),
        )
        for match in pattern.finditer(board_text)
    )


def _parse_vias(board_text: str) -> tuple[_Via, ...]:
    pattern = re.compile(
        r"\(via\s+"
        r"\(at (?P<x>-?\d+(?:\.\d+)?) (?P<y>-?\d+(?:\.\d+)?)\).*?"
        r"\(net (?P<net>\d+)\)",
        re.MULTILINE | re.DOTALL,
    )
    return tuple(
        _Via(
            at=(float(match.group("x")), float(match.group("y"))),
            net_number=int(match.group("net")),
        )
        for match in pattern.finditer(board_text)
    )


def _parse_smd_pads(board_text: str) -> tuple[_SmdPad, ...]:
    pads: list[_SmdPad] = []
    for footprint_text in _extract_blocks(board_text, "(footprint"):
        if "(attr smd)" not in footprint_text:
            continue
        footprint_name = _quoted_after(footprint_text, "footprint") or "unknown"
        footprint_at = _first_xy(footprint_text, "at") or (0.0, 0.0)
        for pad_text in _extract_blocks(footprint_text, "(pad"):
            if re.search(r'\(pad\s+"[^"]+"\s+smd\b', pad_text) is None:
                continue
            pad_name = _quoted_after(pad_text, "pad") or "unknown"
            pad_at = _first_xy(pad_text, "at") or (0.0, 0.0)
            pad_size = _first_xy(pad_text, "size") or (0.0, 0.0)
            net_match = re.search(r"\(net\s+(\d+)", pad_text)
            if net_match is None:
                continue
            pads.append(
                _SmdPad(
                    footprint=footprint_name,
                    pad=pad_name,
                    center=(
                        footprint_at[0] + pad_at[0],
                        footprint_at[1] + pad_at[1],
                    ),
                    size=pad_size,
                    net_number=int(net_match.group(1)),
                )
            )
    return tuple(pads)


def _extract_blocks(text: str, opener: str) -> tuple[str, ...]:
    blocks: list[str] = []
    start = 0
    while True:
        block_start = text.find(opener, start)
        if block_start < 0:
            return tuple(blocks)
        depth = 0
        for index in range(block_start, len(text)):
            char = text[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    blocks.append(text[block_start : index + 1])
                    start = index + 1
                    break
        else:
            return tuple(blocks)


def _quoted_after(text: str, symbol: str) -> str | None:
    match = re.search(rf"\({re.escape(symbol)}\s+\"([^\"]+)\"", text)
    return None if match is None else match.group(1)


def _first_xy(text: str, symbol: str) -> tuple[float, float] | None:
    match = re.search(
        rf"\({re.escape(symbol)}\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)",
        text,
    )
    if match is None:
        return None
    return (float(match.group(1)), float(match.group(2)))


def _net_label(net_number: int, net_names: dict[int, str]) -> str:
    name = net_names.get(net_number)
    return f"net {net_number} ({name})" if name else f"net {net_number}"


__all__ = [
    "KICAD_BOARD_POLICY_SCHEMA",
    "KiCadBoardPolicyFinding",
    "KiCadBoardPolicyReport",
    "KiCadBoardPolicySeverity",
    "inspect_kicad_board_policy",
    "write_kicad_board_policy_report",
]
