"""R2.4 serialized-KiCad authority gate for negotiated routing.

This is intentionally a compact serialization/DRC fixture, not the adversarial
R2.3b maze proof.  The live test is opt-in because it executes the installed
KiCad CLI and KiCad rewrites the temporary board during DRC.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import fields
from pathlib import Path

import pytest

from pcbsmith.kicad.board import (
    BOARD_SHEET_ORIGIN_MM,
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    render_board_from_layout,
)
from pcbsmith.kicad.board_diff import parse_board_placements
from pcbsmith.kicad.cli import find_kicad_cli, run_kicad_process
from pcbsmith.kicad.library import parse_sexpr
from pcbsmith.kicad.negotiated_board import (
    NegotiatedBoardRouteResult,
    route_board_negotiated,
)
from pcbsmith.kicad.validate import run_kicad_drc

KICAD_AUTHORITY_VERSION = "10.0.3"
R2_BOARD_SHA256 = "57a7a75093b056971ca37651d6227806d896b02da56c9a062cef0738fe2bb505"
RESISTOR = "Resistor_SMD:R_0603_1608Metric"


def _fixture() -> tuple[BoardLayout, BoardNetlist]:
    components = (
        BoardComponent("R1", "1k", RESISTOR, "r2-golden-r1"),
        BoardComponent("R2", "1k", RESISTOR, "r2-golden-r2"),
    )
    netlist = BoardNetlist(
        components=components,
        nets=(
            BoardNet("/A", (("R1", "1"),)),
            BoardNet("/B", (("R2", "2"),)),
            BoardNet("/SIG", (("R1", "2"), ("R2", "1"))),
        ),
    )
    layout = BoardLayout(
        placements=((components[0], 5.0), (components[1], 25.0)),
        segments=(),
        vias=(),
        width_mm=30.0,
        height_mm=12.0,
        parts_row_y_mm=6.0,
        part_y_mm=(("R1", 6.0), ("R2", 6.0)),
        hide_references=("R2",),
        part_reference_at=(("R1", (0.0, -1.5, 0.0)),),
    )
    return layout, netlist


def _route_fixture() -> tuple[BoardLayout, BoardNetlist, NegotiatedBoardRouteResult]:
    layout, netlist = _fixture()
    result = route_board_negotiated(
        layout,
        netlist,
        target_nets=("/SIG",),
        net_order=("/SIG",),
        grid_mm=0.5,
        default_width_mm=0.4,
        max_passes=2,
        max_stagnant_passes=1,
        max_expansions=20_000,
        max_expansions_per_net=20_000,
    )
    assert result.run_result.success
    assert result.run_result.resource_overuse == ()
    return layout, netlist, result


def _serialized_fixture() -> tuple[BoardLayout, BoardNetlist, bytes]:
    layout, netlist, result = _route_fixture()
    board_text = render_board_from_layout(netlist, result.layout)
    return layout, netlist, board_text.encode("utf-8")


def test_negotiated_board_serialization_is_deterministic_and_readable() -> None:
    source_layout, netlist, first = _serialized_fixture()
    _source_layout, _netlist, repeated = _serialized_fixture()
    _layout, _same_netlist, result = _route_fixture()

    assert first == repeated
    assert hashlib.sha256(first).hexdigest() == R2_BOARD_SHA256
    assert first.endswith(b")\n")
    tree = parse_sexpr(first.decode("utf-8"))
    assert tree[0] == "kicad_pcb"

    placements = parse_board_placements(first.decode("utf-8"))
    assert placements == {
        "R1": (25.0, 26.0, 0.0, "F.Cu"),
        "R2": (45.0, 26.0, 0.0, "F.Cu"),
    }
    assert first.count(b"  (segment ") == len(result.layout.segments)
    assert first.count(b"  (via ") == len(result.layout.vias)

    # R2 may replace only route geometry.  All placement, outline, process,
    # graphic, and side metadata must survive board-level negotiation exactly.
    for field in fields(BoardLayout):
        if field.name not in {"segments", "vias"}:
            assert getattr(result.layout, field.name) == getattr(source_layout, field.name)
    assert result.layout.segments
    assert {segment.net_name for segment in result.layout.segments} == {"/SIG"}
    assert netlist == _same_netlist
    assert BOARD_SHEET_ORIGIN_MM == 20.0


def _live_kicad_reason() -> str | None:
    if not os.environ.get("PCBSMITH_R2_KICAD_GOLDEN"):
        return "set PCBSMITH_R2_KICAD_GOLDEN=1 to run the live R2 KiCad DRC gate"
    install = find_kicad_cli()
    if install is None:
        return "kicad-cli is unavailable"
    version = run_kicad_process((install.path, "version"))
    if version.returncode != 0:
        return "kicad-cli version could not be read"
    if version.stdout.strip() != KICAD_AUTHORITY_VERSION:
        return (
            f"authority fixture is pinned to KiCad {KICAD_AUTHORITY_VERSION}; "
            f"found {version.stdout.strip() or 'unknown'}"
        )
    return None


@pytest.mark.golden
def test_negotiated_board_passes_live_kicad_drc(tmp_path: Path) -> None:
    reason = _live_kicad_reason()
    if reason is not None:
        pytest.skip(reason)

    _layout, _netlist, board_bytes = _serialized_fixture()
    board_file = tmp_path / "R2-negotiated-serialization-golden.kicad_pcb"
    board_file.write_bytes(board_bytes)

    report = run_kicad_drc(board_file, schematic_parity=False)

    assert report.status == "passed", report.findings
    # KiCad parses and saves the board during DRC.  Exercise the strongest
    # read-back APIs currently available after that authoritative rewrite.
    saved_text = board_file.read_text(encoding="utf-8")
    assert parse_sexpr(saved_text)[0] == "kicad_pcb"
    assert set(parse_board_placements(saved_text)) == {"R1", "R2"}
