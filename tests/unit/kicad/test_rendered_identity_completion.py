"""Closed identity coverage for generated KiCad board artifacts."""

from __future__ import annotations

import os
import re
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNetlist,
    render_board_from_layout,
)
from pcbsmith.kicad.validate import run_kicad_drc

RESISTOR = "Resistor_SMD:R_0603_1608Metric"
UUID_PATTERN = re.compile(
    r'\(uuid\s+"?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-'
    r'[0-9a-f]{4}-[0-9a-f]{12})"?\)'
)


def _component(*, value: str = "10k") -> BoardComponent:
    return BoardComponent(
        reference="R1",
        value=value,
        footprint=RESISTOR,
        uuid_path="fixture/sheet/r1",
    )


def _layout(
    component: BoardComponent | None = None,
    *,
    graphics: tuple[str, ...] = (),
) -> BoardLayout:
    return BoardLayout(
        placements=() if component is None else ((component, 10.0),),
        segments=(),
        vias=(),
        width_mm=20.0,
        height_mm=20.0,
        parts_row_y_mm=10.0,
        graphics=graphics,
    )


def _graphic_uuids(text: str) -> tuple[str, ...]:
    return tuple(
        match.group(1)
        for match in re.finditer(
            r'\(gr_line\b.*?\(uuid\s+"?([0-9a-f-]{36})"?\)',
            text,
            flags=re.DOTALL,
        )
    )


def _property_uuid(text: str, name: str) -> str:
    match = re.search(
        rf'\(property "{re.escape(name)}".*?\(uuid\s+"([0-9a-f-]{{36}})"\)',
        text,
        flags=re.DOTALL,
    )
    assert match is not None
    return match.group(1)


def test_duplicate_footprints_and_raw_graphics_have_unique_uuid5_values() -> None:
    component = _component()
    graphic = (
        '(gr_line (start 2 2) (end 4 2) '
        '(stroke (width 0.2) (type solid)) (layer "F.SilkS"))'
    )
    layout = _layout(graphics=(graphic, graphic))
    layout = replace(layout, placements=((component, 7.0), (component, 13.0)))

    first = render_board_from_layout(BoardNetlist(components=(component,), nets=()), layout)
    second = render_board_from_layout(BoardNetlist(components=(component,), nets=()), layout)
    values = UUID_PATTERN.findall(first)

    assert first == second
    assert len(values) == len(set(values))
    assert all(UUID(value).version == 5 for value in values)
    assert len(_graphic_uuids(first)) == 2


def test_graphic_semantic_change_changes_only_its_semantic_identity() -> None:
    netlist = BoardNetlist(components=(), nets=())
    first = render_board_from_layout(
        netlist,
        _layout(
            graphics=(
                '(gr_line (start 2 2) (end 4 2) '
                '(stroke (width 0.2) (type solid)) (layer "F.SilkS"))',
            )
        ),
    )
    changed = render_board_from_layout(
        netlist,
        _layout(
            graphics=(
                '(gr_line (start 2 2) (end 5 2) '
                '(stroke (width 0.2) (type solid)) (layer "F.SilkS"))',
            )
        ),
    )

    assert _graphic_uuids(first) != _graphic_uuids(changed)


def test_footprint_property_semantic_change_changes_relevant_child_id() -> None:
    first_component = _component(value="10k")
    changed_component = _component(value="11k")
    first = render_board_from_layout(
        BoardNetlist(components=(first_component,), nets=()),
        _layout(first_component),
    )
    changed = render_board_from_layout(
        BoardNetlist(components=(changed_component,), nets=()),
        _layout(changed_component),
    )

    assert _property_uuid(first, "Reference") == _property_uuid(changed, "Reference")
    assert _property_uuid(first, "Value") != _property_uuid(changed, "Value")


@pytest.mark.skipif(
    os.environ.get("PCBSMITH_R5_KICAD_GOLDEN") != "1",
    reason="set PCBSMITH_R5_KICAD_GOLDEN=1 to exercise the installed KiCad CLI",
)
def test_real_kicad_clean_saves_are_byte_deterministic(tmp_path: Path) -> None:
    saved: list[str] = []
    reports = []
    for run in ("first", "second"):
        component = _component()
        netlist = BoardNetlist(components=(component,), nets=())
        rendered = render_board_from_layout(netlist, _layout(component))
        run_dir = tmp_path / run
        run_dir.mkdir()
        board_file = run_dir / "identity-golden.kicad_pcb"
        board_file.write_text(rendered, encoding="utf-8")
        reports.append(run_kicad_drc(board_file, schematic_parity=False))
        saved.append(board_file.read_text(encoding="utf-8"))

    assert all(report.status == "passed" for report in reports)
    assert saved[0] == saved[1]
    values = UUID_PATTERN.findall(saved[0])
    assert len(values) == len(set(values))
    assert all(UUID(value).version == 5 for value in values)
