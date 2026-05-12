from __future__ import annotations

from pcbsmith.core.board import Board, Layer, Trace
from pcbsmith.core.geom import Point
from pcbsmith.core.project import DesignRules
from pcbsmith.services.board_manufacturability import (
    ManufacturabilitySeverity,
    format_board_manufacturability_report,
    inspect_board_manufacturability,
    write_board_manufacturability_report,
)


def test_board_manufacturability_warns_on_non_preferred_trace_angle() -> None:
    board = Board(
        id="main",
        traces=(
            Trace(
                net_name="SIG",
                layer=Layer.F_CU,
                points=(Point.from_mm(0, 0), Point.from_mm(10, 3)),
                width=300_000,
            ),
        ),
    )

    report = inspect_board_manufacturability(board)

    assert [(finding.severity, finding.code) for finding in report.findings] == [
        (ManufacturabilitySeverity.WARNING, "non_preferred_trace_angle")
    ]
    assert report.exit_code == 0


def test_board_manufacturability_warns_on_sharp_turn() -> None:
    board = Board(
        id="main",
        traces=(
            Trace(
                net_name="SIG",
                layer=Layer.F_CU,
                points=(
                    Point.from_mm(0, 0),
                    Point.from_mm(10, 0),
                    Point.from_mm(11, 0.2),
                ),
                width=300_000,
            ),
        ),
    )

    report = inspect_board_manufacturability(board)

    assert "sharp_trace_turn" in {finding.code for finding in report.findings}
    assert report.exit_code == 0


def test_board_manufacturability_errors_on_same_layer_clearance_risk() -> None:
    board = Board(
        id="main",
        traces=(
            Trace(
                net_name="A",
                layer=Layer.F_CU,
                points=(Point.from_mm(0, 0), Point.from_mm(10, 0)),
                width=400_000,
            ),
            Trace(
                net_name="B",
                layer=Layer.F_CU,
                points=(Point.from_mm(0, 0.8), Point.from_mm(10, 0.8)),
                width=400_000,
            ),
        ),
    )

    report = inspect_board_manufacturability(
        board,
        design_rules=DesignRules(min_clearance=500_000),
    )

    assert [(finding.severity, finding.code) for finding in report.findings] == [
        (ManufacturabilitySeverity.ERROR, "trace_clearance_risk")
    ]
    assert report.exit_code == 1


def test_board_manufacturability_allows_clean_preferred_routes() -> None:
    board = Board(
        id="main",
        traces=(
            Trace(
                net_name="A",
                layer=Layer.F_CU,
                points=(
                    Point.from_mm(0, 0),
                    Point.from_mm(5, 0),
                    Point.from_mm(10, 5),
                    Point.from_mm(10, 10),
                ),
                width=300_000,
            ),
            Trace(
                net_name="B",
                layer=Layer.F_CU,
                points=(Point.from_mm(0, 20), Point.from_mm(10, 20)),
                width=300_000,
            ),
        ),
    )

    report = inspect_board_manufacturability(board)

    assert report.findings == ()
    assert format_board_manufacturability_report(report) == [
        "Board manufacturability: passed (0 findings)"
    ]


def test_write_board_manufacturability_report_writes_structured_json(tmp_path) -> None:  # type: ignore[no-untyped-def]
    board = Board(
        id="main",
        traces=(
            Trace(
                net_name="SIG",
                layer=Layer.F_CU,
                points=(Point.from_mm(0, 0), Point.from_mm(10, 3)),
                width=300_000,
            ),
        ),
    )

    report = inspect_board_manufacturability(board)
    output = tmp_path / "manufacturability.json"

    write_board_manufacturability_report(report, output)

    assert output.read_text(encoding="utf-8") == (
        "{\n"
        '  "schema": "pcbsmith-board-manufacturability-v1",\n'
        '  "summary": {\n'
        '    "finding_count": 1,\n'
        '    "error_count": 0,\n'
        '    "warning_count": 1\n'
        "  },\n"
        '  "findings": [\n'
        "    {\n"
        '      "severity": "warning",\n'
        '      "code": "non_preferred_trace_angle",\n'
        '      "message": "Trace SIG uses 17 degree routing; prefer cardinal or '
        '45-degree segments when practical",\n'
        '      "location": "trace 1 segment 1"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )
