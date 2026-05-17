from __future__ import annotations

from pcbsmith.core.board import Board, BoardEdgeLoopRole, Layer, Trace
from pcbsmith.core.geom import Point
from pcbsmith.services.board_outline_geometry import (
    BoardOutlineGeometryRequest,
    BoardOutlinePreflightFrame,
    apply_board_outline_geometry,
    board_outline_geometry_planner_rule_notes,
    board_outline_geometry_tool_contract,
    inspect_board_outline_geometry,
)


def _outline_request() -> BoardOutlineGeometryRequest:
    return BoardOutlineGeometryRequest(
        role=BoardEdgeLoopRole.OUTLINE,
        points=(
            Point.from_mm(0, 0),
            Point.from_mm(40, 0),
            Point.from_mm(40, 20),
            Point.from_mm(0, 20),
        ),
    )


def test_board_outline_contract_keeps_physical_geometry_on_edge_cuts() -> None:
    contract = board_outline_geometry_tool_contract()

    assert contract["schema"] == "pcbsmith-board-outline-geometry-tool-v1"
    assert contract["allowed_layer"] == "Edge.Cuts"
    assert contract["loop_roles"] == ["outline", "cutout"]
    assert "closed_edge_loop" in contract["preflight_checks"]
    assert "Do not use this operation for silkscreen artwork." in contract["instructions"]


def test_board_outline_planner_notes_separate_shape_from_artwork() -> None:
    notes = board_outline_geometry_planner_rule_notes()

    assert "Use Edge.Cuts only for physical board outlines and cutouts." in notes
    assert "Keep silkscreen logos/text in the silkscreen_artwork tool." in notes


def test_board_outline_preflight_rejects_too_small_outline() -> None:
    report = inspect_board_outline_geometry(
        Board(id="demo"),
        (
            BoardOutlineGeometryRequest(
                role=BoardEdgeLoopRole.OUTLINE,
                points=(
                    Point.from_mm(0, 0),
                    Point.from_mm(2, 0),
                    Point.from_mm(2, 2),
                    Point.from_mm(0, 2),
                ),
            ),
        ),
        frame=BoardOutlinePreflightFrame(),
    )

    assert [finding.code for finding in report.findings] == ["outline_too_small"]


def test_board_outline_preflight_flags_copper_too_close_to_edge() -> None:
    board = Board(
        id="demo",
        traces=(
            Trace(
                net_name="VCC",
                layer=Layer.F_CU,
                points=(Point.from_mm(0.4, 10), Point.from_mm(30, 10)),
                width=250_000,
            ),
        ),
    )

    report = inspect_board_outline_geometry(
        board,
        (_outline_request(),),
        frame=BoardOutlinePreflightFrame(copper_edge_clearance_mm=0.5),
    )

    assert [finding.code for finding in report.findings] == ["copper_edge_clearance"]


def test_board_outline_preflight_rejects_cutout_outside_outline() -> None:
    report = inspect_board_outline_geometry(
        Board(id="demo"),
        (
            _outline_request(),
            BoardOutlineGeometryRequest(
                role=BoardEdgeLoopRole.CUTOUT,
                points=(
                    Point.from_mm(45, 5),
                    Point.from_mm(50, 5),
                    Point.from_mm(50, 10),
                    Point.from_mm(45, 10),
                ),
            ),
        ),
        frame=BoardOutlinePreflightFrame(),
    )

    assert [finding.code for finding in report.findings] == ["cutout_outside_outline"]


def test_apply_board_outline_geometry_adds_edge_cut_loops_after_preflight() -> None:
    board = apply_board_outline_geometry(
        Board(id="demo"),
        (_outline_request(),),
        frame=BoardOutlinePreflightFrame(),
    )

    assert len(board.edge_cuts) == 1
    assert board.edge_cuts[0].role == BoardEdgeLoopRole.OUTLINE
    assert board.edge_cuts[0].points[0] == Point.from_mm(0, 0)


def test_apply_board_outline_geometry_refuses_failed_preflight() -> None:
    try:
        apply_board_outline_geometry(
            Board(id="demo"),
            (
                BoardOutlineGeometryRequest(
                    role=BoardEdgeLoopRole.OUTLINE,
                    points=(
                        Point.from_mm(0, 0),
                        Point.from_mm(2, 0),
                        Point.from_mm(2, 2),
                        Point.from_mm(0, 2),
                    ),
                ),
            ),
            frame=BoardOutlinePreflightFrame(),
        )
    except ValueError as exc:
        assert "board outline preflight failed" in str(exc)
    else:
        raise AssertionError("Expected failed outline preflight to block geometry")
