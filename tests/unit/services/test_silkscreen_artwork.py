from __future__ import annotations

from pcbsmith.core.board import Board, Layer, Trace
from pcbsmith.core.geom import Point
from pcbsmith.services.silkscreen_artwork import (
    SilkscreenArtworkRequest,
    SilkscreenPreflightFrame,
    apply_silkscreen_artwork,
    inspect_silkscreen_artwork,
    silkscreen_artwork_tool_contract,
)


def test_silkscreen_artwork_request_accepts_front_and_back_silk_only() -> None:
    request = SilkscreenArtworkRequest(
        text="VIR LAB",
        layer=Layer.F_SILK,
        position=Point.from_mm(20, 10),
    )

    assert request.layer == Layer.F_SILK

    try:
        SilkscreenArtworkRequest(
            text="wrong layer",
            layer=Layer.EDGE_CUTS,
            position=Point.from_mm(20, 10),
        )
    except ValueError as exc:
        assert "silkscreen artwork must target F.SilkS or B.SilkS" in str(exc)
    else:
        raise AssertionError("Expected non-silkscreen layer to be rejected")


def test_silkscreen_preflight_rejects_tiny_unreadable_text() -> None:
    report = inspect_silkscreen_artwork(
        Board(id="demo"),
        (
            SilkscreenArtworkRequest(
                text="too small",
                layer=Layer.F_SILK,
                position=Point.from_mm(20, 10),
                size=500_000,
                thickness=60_000,
            ),
        ),
        frame=SilkscreenPreflightFrame(width_mm=50, height_mm=30),
    )

    assert [finding.code for finding in report.findings] == [
        "silkscreen_text_too_small",
        "silkscreen_stroke_too_thin",
    ]


def test_silkscreen_preflight_rejects_artwork_outside_board_outline() -> None:
    report = inspect_silkscreen_artwork(
        Board(id="demo"),
        (
            SilkscreenArtworkRequest(
                text="LONG EDGE LABEL",
                layer=Layer.F_SILK,
                position=Point.from_mm(48, 29),
                size=1_500_000,
            ),
        ),
        frame=SilkscreenPreflightFrame(width_mm=50, height_mm=30),
    )

    assert len(report.findings) == 1
    assert report.findings[0].code == "silkscreen_outside_board"


def test_silkscreen_preflight_flags_copper_overlap() -> None:
    board = Board(
        id="demo",
        traces=(
            Trace(
                net_name="VCC",
                layer=Layer.F_CU,
                points=(Point.from_mm(8, 10), Point.from_mm(30, 10)),
                width=500_000,
            ),
        ),
    )

    report = inspect_silkscreen_artwork(
        board,
        (
            SilkscreenArtworkRequest(
                text="VCC BUS",
                layer=Layer.F_SILK,
                position=Point.from_mm(12, 10),
                size=1_500_000,
            ),
        ),
        frame=SilkscreenPreflightFrame(width_mm=50, height_mm=30),
    )

    assert [finding.code for finding in report.findings] == ["silkscreen_copper_overlap"]


def test_apply_silkscreen_artwork_adds_board_text_after_clean_preflight() -> None:
    board = apply_silkscreen_artwork(
        Board(id="demo"),
        (
            SilkscreenArtworkRequest(
                text="VIR LAB",
                layer=Layer.F_SILK,
                position=Point.from_mm(20, 10),
                size=1_500_000,
            ),
        ),
        frame=SilkscreenPreflightFrame(width_mm=50, height_mm=30),
    )

    assert len(board.texts) == 1
    assert board.texts[0].text == "VIR LAB"
    assert board.texts[0].layer == Layer.F_SILK


def test_apply_silkscreen_artwork_refuses_failed_preflight() -> None:
    try:
        apply_silkscreen_artwork(
            Board(id="demo"),
            (
                SilkscreenArtworkRequest(
                    text="too small",
                    layer=Layer.F_SILK,
                    position=Point.from_mm(20, 10),
                    size=500_000,
                ),
            ),
            frame=SilkscreenPreflightFrame(width_mm=50, height_mm=30),
        )
    except ValueError as exc:
        assert "silkscreen preflight failed" in str(exc)
    else:
        raise AssertionError("Expected failed preflight to block artwork")


def test_silkscreen_artwork_tool_contract_is_ai_facing() -> None:
    contract = silkscreen_artwork_tool_contract()

    assert contract["schema"] == "pcbsmith-silkscreen-artwork-tool-v1"
    assert contract["allowed_layers"] == ["F.SilkS", "B.SilkS"]
    assert "minimum_text_size_mm" in contract["preflight_checks"]
