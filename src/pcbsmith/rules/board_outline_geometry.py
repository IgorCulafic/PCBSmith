from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from pcbsmith.core.board import Board, BoardEdgeLoop, BoardEdgeLoopRole, Layer, Trace
from pcbsmith.core.geom import Box, Point, mm_to_nm

MIN_EDGE_STROKE_WIDTH_NM = mm_to_nm(0.1)
DEFAULT_MIN_OUTLINE_SIZE_NM = mm_to_nm(5.0)
DEFAULT_COPPER_EDGE_CLEARANCE_NM = mm_to_nm(0.5)


class BoardOutlineGeometryRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: BoardEdgeLoopRole
    points: tuple[Point, ...] = Field(min_length=3)
    stroke_width: int = Field(default=100_000, gt=0)


@dataclass(frozen=True)
class BoardOutlinePreflightFrame:
    min_outline_size_mm: float = 5.0
    copper_edge_clearance_mm: float = 0.5

    @property
    def min_outline_size(self) -> int:
        return mm_to_nm(self.min_outline_size_mm)

    @property
    def copper_edge_clearance(self) -> int:
        return mm_to_nm(self.copper_edge_clearance_mm)


@dataclass(frozen=True)
class BoardOutlinePreflightFinding:
    code: str
    message: str
    location: str


@dataclass(frozen=True)
class BoardOutlinePreflightReport:
    findings: tuple[BoardOutlinePreflightFinding, ...]

    @property
    def passed(self) -> bool:
        return not self.findings


def inspect_board_outline_geometry(
    board: Board,
    requests: tuple[BoardOutlineGeometryRequest, ...],
    *,
    frame: BoardOutlinePreflightFrame,
) -> BoardOutlinePreflightReport:
    findings: list[BoardOutlinePreflightFinding] = []
    outlines = tuple(
        request for request in requests if request.role == BoardEdgeLoopRole.OUTLINE
    )
    outline_box = estimate_edge_loop_box(outlines[0]) if outlines else None
    if not outlines:
        findings.append(
            BoardOutlinePreflightFinding(
                code="missing_outline",
                message="Board outline geometry needs at least one outline loop",
                location="board outline",
            )
        )

    for index, request in enumerate(requests, start=1):
        location = f"{request.role.value} loop {index}"
        bounds = estimate_edge_loop_box(request)
        if request.stroke_width < MIN_EDGE_STROKE_WIDTH_NM:
            findings.append(
                BoardOutlinePreflightFinding(
                    code="edge_stroke_too_thin",
                    message="Edge.Cuts stroke width is below the reliable minimum",
                    location=location,
                )
            )
        if request.role == BoardEdgeLoopRole.OUTLINE and (
            bounds.right - bounds.left < frame.min_outline_size
            or bounds.bottom - bounds.top < frame.min_outline_size
        ):
            findings.append(
                BoardOutlinePreflightFinding(
                    code="outline_too_small",
                    message="Board outline is below the minimum practical board size",
                    location=location,
                )
            )
        if (
            request.role == BoardEdgeLoopRole.CUTOUT
            and outline_box is not None
            and not _contains_box(outline_box, bounds)
        ):
            findings.append(
                BoardOutlinePreflightFinding(
                    code="cutout_outside_outline",
                    message="Cutout geometry must stay inside the board outline",
                    location=location,
                )
            )

    if outline_box is not None and _copper_crowds_outline(
        board.traces,
        outline_box,
        frame.copper_edge_clearance,
    ):
        findings.append(
            BoardOutlinePreflightFinding(
                code="copper_edge_clearance",
                message="Copper is too close to the board edge for the selected profile",
                location="copper",
            )
        )

    return BoardOutlinePreflightReport(findings=tuple(findings))


def apply_board_outline_geometry(
    board: Board,
    requests: tuple[BoardOutlineGeometryRequest, ...],
    *,
    frame: BoardOutlinePreflightFrame,
) -> Board:
    report = inspect_board_outline_geometry(board, requests, frame=frame)
    if not report.passed:
        codes = ", ".join(finding.code for finding in report.findings)
        raise ValueError(f"board outline preflight failed: {codes}")

    edge_cuts = tuple(_request_to_edge_loop(request) for request in requests)
    return board.model_copy(update={"edge_cuts": (*board.edge_cuts, *edge_cuts)})


def estimate_edge_loop_box(request: BoardOutlineGeometryRequest | BoardEdgeLoop) -> Box:
    return Box(
        left=min(point.x for point in request.points),
        top=min(point.y for point in request.points),
        right=max(point.x for point in request.points),
        bottom=max(point.y for point in request.points),
    )


def board_outline_geometry_tool_contract() -> dict[str, object]:
    return {
        "schema": "pcbsmith-board-outline-geometry-tool-v1",
        "allowed_layer": Layer.EDGE_CUTS.value,
        "loop_roles": [role.value for role in BoardEdgeLoopRole],
        "preflight_checks": [
            "closed_edge_loop",
            "minimum_outline_size_mm",
            "minimum_stroke_width_mm",
            "cutout_inside_outline",
            "copper_edge_clearance",
        ],
        "instructions": [
            "Use board outline geometry for physical board shape, slots, and cutouts.",
            "Do not use this operation for silkscreen artwork.",
            "Keep Edge.Cuts geometry separate from copper, mask, and silkscreen layers.",
            "Run preflight before applying board outline geometry.",
        ],
    }


def board_outline_geometry_planner_rule_notes() -> list[str]:
    return [
        "Use Edge.Cuts only for physical board outlines and cutouts.",
        "Keep silkscreen logos/text in the silkscreen_artwork tool.",
        "Run board outline preflight before applying physical shape geometry.",
    ]


def _request_to_edge_loop(request: BoardOutlineGeometryRequest) -> BoardEdgeLoop:
    return BoardEdgeLoop(
        role=request.role,
        points=request.points,
        stroke_width=request.stroke_width,
    )


def _copper_crowds_outline(
    traces: tuple[Trace, ...],
    outline_box: Box,
    clearance: int,
) -> bool:
    copper_traces = tuple(
        trace for trace in traces if trace.layer in {Layer.F_CU, Layer.B_CU}
    )
    return any(
        not _contains_box(
            outline_box,
            _expanded_trace_segment_box(start, end, trace.width, clearance),
        )
        for trace in copper_traces
        for start, end in zip(trace.points, trace.points[1:], strict=False)
    )


def _expanded_trace_segment_box(
    start: Point,
    end: Point,
    trace_width: int,
    clearance: int,
) -> Box:
    expansion = (trace_width // 2) + clearance
    return Box(
        left=min(start.x, end.x) - expansion,
        top=min(start.y, end.y) - expansion,
        right=max(start.x, end.x) + expansion,
        bottom=max(start.y, end.y) + expansion,
    )


def _contains_box(container: Box, inner: Box) -> bool:
    return (
        container.left <= inner.left
        and inner.right <= container.right
        and container.top <= inner.top
        and inner.bottom <= container.bottom
    )


__all__ = [
    "BoardOutlineGeometryRequest",
    "BoardOutlinePreflightFinding",
    "BoardOutlinePreflightFrame",
    "BoardOutlinePreflightReport",
    "apply_board_outline_geometry",
    "board_outline_geometry_planner_rule_notes",
    "board_outline_geometry_tool_contract",
    "estimate_edge_loop_box",
    "inspect_board_outline_geometry",
]
