from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pcbsmith.core.board import Board, BoardText, Layer, Trace
from pcbsmith.core.geom import Box, Point, mm_to_nm

MIN_TEXT_SIZE_NM = mm_to_nm(0.8)
MIN_STROKE_WIDTH_NM = mm_to_nm(0.1)
DEFAULT_EDGE_MARGIN_NM = mm_to_nm(1.0)
DEFAULT_COPPER_KEEP_OUT_NM = mm_to_nm(0.2)


class SilkscreenMode(StrEnum):
    PROFESSIONAL = "professional"
    SHOWCASE = "showcase"


class SilkscreenArtworkRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1)
    layer: Layer = Layer.F_SILK
    position: Point
    rotation_deg: int = 0
    size: int = Field(default=1_500_000, gt=0)
    thickness: int = Field(default=150_000, gt=0)
    mode: SilkscreenMode = SilkscreenMode.PROFESSIONAL

    @model_validator(mode="after")
    def only_silkscreen_layers(self) -> SilkscreenArtworkRequest:
        if self.layer not in {Layer.F_SILK, Layer.B_SILK}:
            raise ValueError("silkscreen artwork must target F.SilkS or B.SilkS")
        return self


@dataclass(frozen=True)
class SilkscreenPreflightFrame:
    width_mm: float
    height_mm: float
    edge_margin_mm: float = 1.0
    copper_keepout_mm: float = 0.2

    @property
    def board_box(self) -> Box:
        margin = mm_to_nm(self.edge_margin_mm)
        return Box(
            left=margin,
            top=margin,
            right=mm_to_nm(self.width_mm) - margin,
            bottom=mm_to_nm(self.height_mm) - margin,
        )

    @property
    def copper_keepout(self) -> int:
        return mm_to_nm(self.copper_keepout_mm)


@dataclass(frozen=True)
class SilkscreenPreflightFinding:
    code: str
    message: str
    location: str


@dataclass(frozen=True)
class SilkscreenPreflightReport:
    findings: tuple[SilkscreenPreflightFinding, ...]

    @property
    def passed(self) -> bool:
        return not self.findings


def inspect_silkscreen_artwork(
    board: Board,
    requests: tuple[SilkscreenArtworkRequest, ...],
    *,
    frame: SilkscreenPreflightFrame,
) -> SilkscreenPreflightReport:
    findings: list[SilkscreenPreflightFinding] = []
    copper_traces = tuple(
        trace for trace in board.traces if trace.layer in {Layer.F_CU, Layer.B_CU}
    )
    for index, request in enumerate(requests, start=1):
        location = f"silkscreen artwork {index}"
        bounds = estimate_silkscreen_text_box(request)
        if request.size < MIN_TEXT_SIZE_NM:
            findings.append(
                SilkscreenPreflightFinding(
                    code="silkscreen_text_too_small",
                    message="Silkscreen text is below the readable minimum size",
                    location=location,
                )
            )
        if request.thickness < MIN_STROKE_WIDTH_NM:
            findings.append(
                SilkscreenPreflightFinding(
                    code="silkscreen_stroke_too_thin",
                    message="Silkscreen stroke is below the reliable minimum width",
                    location=location,
                )
            )
        if not _contains_box(frame.board_box, bounds):
            findings.append(
                SilkscreenPreflightFinding(
                    code="silkscreen_outside_board",
                    message="Silkscreen artwork crosses the board outline or edge margin",
                    location=location,
                )
            )
        if _overlaps_copper(bounds, copper_traces, frame.copper_keepout):
            findings.append(
                SilkscreenPreflightFinding(
                    code="silkscreen_copper_overlap",
                    message="Silkscreen artwork overlaps or crowds exposed copper",
                    location=location,
                )
            )
    return SilkscreenPreflightReport(findings=tuple(findings))


def apply_silkscreen_artwork(
    board: Board,
    requests: tuple[SilkscreenArtworkRequest, ...],
    *,
    frame: SilkscreenPreflightFrame,
) -> Board:
    report = inspect_silkscreen_artwork(board, requests, frame=frame)
    if not report.passed:
        codes = ", ".join(finding.code for finding in report.findings)
        raise ValueError(f"silkscreen preflight failed: {codes}")

    texts = tuple(_request_to_board_text(request) for request in requests)
    return board.model_copy(update={"texts": (*board.texts, *texts)})


def estimate_silkscreen_text_box(request: SilkscreenArtworkRequest) -> Box:
    width = max(1, int(len(request.text) * request.size * 0.6))
    height = request.size
    if request.rotation_deg % 180:
        width, height = height, width
    return Box(
        left=request.position.x,
        top=request.position.y - height,
        right=request.position.x + width,
        bottom=request.position.y,
    )


def silkscreen_artwork_tool_contract() -> dict[str, object]:
    return {
        "schema": "pcbsmith-silkscreen-artwork-tool-v1",
        "allowed_layers": [Layer.F_SILK.value, Layer.B_SILK.value],
        "modes": [mode.value for mode in SilkscreenMode],
        "preflight_checks": [
            "inside_board_outline",
            "edge_margin",
            "minimum_text_size_mm",
            "minimum_stroke_width_mm",
            "copper_keepout",
        ],
        "instructions": [
            "Use silkscreen artwork for printed labels, logos, notes, and decorative text.",
            "Do not use this operation for physical board outlines or cutouts.",
            "Run preflight before applying artwork to a board.",
        ],
    }


def silkscreen_artwork_planner_rule_notes() -> list[str]:
    return [
        "Run silkscreen artwork preflight before applying printed text or logos.",
        "Keep silkscreen away from copper, pads, board edges, and component labels.",
        "Use professional mode for minimal production boards and showcase mode for demo artwork.",
    ]


def _request_to_board_text(request: SilkscreenArtworkRequest) -> BoardText:
    return BoardText(
        text=request.text,
        layer=request.layer,
        position=request.position,
        rotation_deg=request.rotation_deg,
        size=request.size,
        thickness=request.thickness,
    )


def _contains_box(container: Box, inner: Box) -> bool:
    return (
        container.left <= inner.left
        and inner.right <= container.right
        and container.top <= inner.top
        and inner.bottom <= container.bottom
    )


def _overlaps_copper(
    bounds: Box,
    traces: tuple[Trace, ...],
    keepout: int,
) -> bool:
    return any(
        _expanded_trace_segment_box(start, end, trace.width, keepout).intersects(bounds)
        for trace in traces
        for start, end in zip(trace.points, trace.points[1:], strict=False)
    )


def _expanded_trace_segment_box(
    start: Point,
    end: Point,
    trace_width: int,
    keepout: int,
) -> Box:
    expansion = (trace_width // 2) + keepout
    return Box(
        left=min(start.x, end.x) - expansion,
        top=min(start.y, end.y) - expansion,
        right=max(start.x, end.x) + expansion,
        bottom=max(start.y, end.y) + expansion,
    )


__all__ = [
    "SilkscreenArtworkRequest",
    "SilkscreenMode",
    "SilkscreenPreflightFinding",
    "SilkscreenPreflightFrame",
    "SilkscreenPreflightReport",
    "apply_silkscreen_artwork",
    "estimate_silkscreen_text_box",
    "inspect_silkscreen_artwork",
    "silkscreen_artwork_planner_rule_notes",
    "silkscreen_artwork_tool_contract",
]
