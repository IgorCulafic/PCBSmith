from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.divider_highpass_led import compose_divider_highpass_led
from pcbsmith.kicad.export_divider_highpass_led import (
    export_divider_highpass_led_to_kicad,
)

KICAD_CONNECTION_GRID_MM = 2.54


def _circuit():
    intent = classify_circuit_intent("voltage divider high-pass LED indicator")
    return compose_divider_highpass_led(intent, select_topology(intent))


def test_exports_kicad_project_schematic_and_symbol_library(tmp_path: Path) -> None:
    result = export_divider_highpass_led_to_kicad(
        _circuit(),
        tmp_path,
        project_name="Slice",
    )

    schematic_text = (tmp_path / "Slice.kicad_sch").read_text(encoding="utf-8")
    symbol_table_text = (tmp_path / "sym-lib-table").read_text(encoding="utf-8")

    assert result == {
        "project_file": str(tmp_path / "Slice.kicad_pro"),
        "schematic_file": str(tmp_path / "Slice.kicad_sch"),
        "symbol_library": str(tmp_path / "PCBSmith.kicad_sym"),
    }
    assert (tmp_path / "PCBSmith.kicad_sym").exists()
    assert "PCBSmith:R" in schematic_text
    assert "PCBSmith:C" in schematic_text
    assert "PCBSmith:LED" in schematic_text
    for required_text in (
        "P1",
        "R1",
        "R2",
        "C1",
        "RLOAD",
        "R3",
        "D1",
        "GND",
        "VIN",
        "DIV_OUT",
        "HP_OUT",
        ".op",
        ".ac dec 20 10 100k",
        ".print ac v(HP_OUT)",
    ):
        assert required_text in schematic_text
    assert "${KIPRJMOD}/PCBSmith.kicad_sym" in symbol_table_text


def test_exports_kicad_loadable_schematic_scaffold(tmp_path: Path) -> None:
    export_divider_highpass_led_to_kicad(
        _circuit(),
        tmp_path,
        project_name="Slice",
    )

    schematic_text = (tmp_path / "Slice.kicad_sch").read_text(encoding="utf-8")

    assert "(version 20250114)" in schematic_text
    assert "(lib_symbols" in schematic_text
    assert '(symbol "PCBSmith:R"' in schematic_text
    assert '(symbol "PCBSmith:C"' in schematic_text
    assert '(symbol "PCBSmith:LED"' in schematic_text
    assert "(sheet_instances" in schematic_text
    assert '(text ".op\\n.ac dec 20 10 100k\\n.print ac v(HP_OUT)"' in schematic_text
    assert '(text ".op\n.ac dec 20 10 100k\n.print ac v(HP_OUT)"' not in schematic_text


def test_exports_connection_points_on_kicad_grid(tmp_path: Path) -> None:
    export_divider_highpass_led_to_kicad(
        _circuit(),
        tmp_path,
        project_name="Slice",
    )

    schematic_text = (tmp_path / "Slice.kicad_sch").read_text(encoding="utf-8")
    schematic_symbols = re.findall(
        r'\(symbol\s+\(lib_id "[^"]+"\)\s+\(at ([\d.]+) ([\d.]+) ',
        schematic_text,
    )
    wire_blocks = re.findall(r"\(wire\s+\(pts\s+(.*?)\n    \)", schematic_text, re.DOTALL)
    wire_points = [
        point
        for block in wire_blocks
        for point in re.findall(r"\(xy ([\d.]+) ([\d.]+)\)", block)
    ]
    label_positions = re.findall(r'\(label "[^"]+"\s+\(at ([\d.]+) ([\d.]+) ', schematic_text)

    assert schematic_symbols
    assert wire_points
    assert label_positions
    for x_text, y_text in (*schematic_symbols, *wire_points, *label_positions):
        assert _is_on_kicad_grid(float(x_text)), x_text
        assert _is_on_kicad_grid(float(y_text)), y_text


def test_rejects_missing_required_components(tmp_path: Path) -> None:
    circuit = _circuit()
    circuit = circuit.model_copy(
        update={
            "components": tuple(
                component for component in circuit.components if component.reference != "R3"
            )
        }
    )

    with pytest.raises(ValueError, match="missing required components: R3"):
        export_divider_highpass_led_to_kicad(circuit, tmp_path, project_name="Slice")


def test_rejects_project_names_that_escape_output_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Project name must be a file stem"):
        export_divider_highpass_led_to_kicad(
            _circuit(),
            tmp_path,
            project_name="bad/name",
        )


def test_rejects_other_topologies(tmp_path: Path) -> None:
    circuit = _circuit().model_copy(
        update={"topology": _circuit().topology.model_copy(update={"topology_id": "other"})}
    )

    with pytest.raises(ValueError, match="Unsupported circuit"):
        export_divider_highpass_led_to_kicad(circuit, tmp_path, project_name="Slice")


def _is_on_kicad_grid(value: float) -> bool:
    nearest = round(value / KICAD_CONNECTION_GRID_MM) * KICAD_CONNECTION_GRID_MM
    return math.isclose(value, nearest, rel_tol=0.0, abs_tol=1e-6)
