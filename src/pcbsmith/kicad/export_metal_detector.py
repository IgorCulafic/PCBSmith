"""KiCad schematic exporter for the metal detector (label-net style)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from pcbsmith.circuit.models import CircuitObject
from pcbsmith.kicad.export_divider_highpass_led import (
    KICAD_SCHEMATIC_VERSION,
    KICAD_SYMBOL_LIBRARY_VERSION,
    _capacitor_symbol_drawing,
    _generic_pin,
    _label,
    _library_property,
    _render_project,
    _render_symbol_table,
    _render_two_pin_box_library_symbol,
    _resistor_symbol_drawing,
    _symbol,
    _validate_project_name,
    _wire,
)
from pcbsmith.kicad.export_lm2596_buck import _inductor_symbol_drawing
from pcbsmith.kicad.export_mpu6050 import render_connector_library_symbol
from pcbsmith.kicad.metal_detector_board import P1_PIN_NETS

SUPPORTED_TOPOLOGY_ID = "metal_detector_coil"

STUB = 5.08

# Two-pin parts as label-net columns: (ref, lib, x, top net, bottom net).
PASSIVES = (
    ("R1", "PCBSmith:R", 55.88, "VCC", "BASE"),
    ("R2", "PCBSmith:R", 63.5, "BASE", "GND"),
    ("C5", "PCBSmith:C", 71.12, "BASE", "GND"),
    ("L1", "PCBSmith:L", 78.74, "VCC", "COL"),
    ("C1", "PCBSmith:C", 86.36, "COL", "EM"),
    ("C2", "PCBSmith:C", 93.98, "EM", "GND"),
    ("R3", "PCBSmith:R", 101.6, "EM", "GND"),
    ("C4", "PCBSmith:C", 109.22, "VCC", "GND"),
    ("C3", "PCBSmith:C", 116.84, "COL", "FO_A"),
    ("R4", "PCBSmith:R", 124.46, "FO_A", "FOUT"),
)
# The transistor: pin 1 base, pin 2 emitter, pin 3 collector (SOT-23).
Q1_PIN_NETS = {1: "BASE", 2: "EM", 3: "COL"}


def export_metal_detector_to_kicad(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    project_name: str,
) -> dict[str, str]:
    if circuit.topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported circuit for KiCad export")
    project_name = _validate_project_name(project_name)

    output_dir.mkdir(parents=True, exist_ok=True)
    project_file = output_dir / f"{project_name}.kicad_pro"
    schematic_file = output_dir / f"{project_name}.kicad_sch"
    symbol_library = output_dir / "PCBSmith.kicad_sym"
    symbol_table = output_dir / "sym-lib-table"

    project_file.write_text(_render_project(), encoding="utf-8")
    symbol_table.write_text(_render_symbol_table(), encoding="utf-8")
    symbol_library.write_text(_render_symbol_library(), encoding="utf-8")
    schematic_file.write_text(_render_schematic(circuit, project_name), encoding="utf-8")
    return {
        "project_file": str(project_file),
        "schematic_file": str(schematic_file),
        "symbol_library": str(symbol_library),
    }


def _render_schematic(circuit: CircuitObject, project_name: str) -> str:
    fields = {
        component.reference: (component.value, component.footprint or "")
        for component in circuit.components
    }

    def sym(lib: str, reference: str, x: float, y: float, rotation: int = 0) -> str:
        value, footprint = fields[reference]
        return _symbol(
            lib, reference, value, x, y, project_name,
            rotation=rotation, exclude_from_sim=True, footprint=footprint,
            # The coil exists only as copper; its net-tie footprint is
            # excluded from the BOM and the symbol must match (parity).
            in_bom=reference != "L1",
        )

    symbols = [
        sym("PCBSmith:CONN_01X03", "P1", 25.4, 55.88),
        sym("PCBSmith:NPN", "Q1", 58.42, 55.88),
    ]
    wires: list[str] = []
    labels: list[str] = []

    # Connector pins stack upward from the anchor: pin 1 (VCC) lowest.
    for index, connector_net in enumerate(P1_PIN_NETS):
        y = 55.88 - index * 2.54
        wires.append(_wire((25.4, y), (25.4 + STUB, y)))
        labels.append(_label(connector_net, 25.4 + STUB, y))

    # Transistor: base on the left, collector/emitter on the right.
    q_pins = ((1, -7.62, 0.0, -STUB), (3, 7.62, -2.54, STUB), (2, 7.62, 2.54, STUB))
    for pin, dx, dy, stub in q_pins:
        x, y = 58.42 + dx, 55.88 + dy
        wires.append(_wire((x, y), (x + stub, y)))
        labels.append(_label(Q1_PIN_NETS[pin], x + stub, y))

    for reference, lib, x, top_net, bottom_net in PASSIVES:
        y_center = 87.63
        symbols.append(sym(lib, reference, x, y_center, rotation=270))
        top_tip = y_center - STUB
        bottom_tip = y_center + STUB
        wires.append(_wire((x, top_tip), (x, top_tip - 2.54)))
        labels.append(_label(top_net, x, top_tip - 2.54))
        wires.append(_wire((x, bottom_tip), (x, bottom_tip + 2.54)))
        labels.append(_label(bottom_net, x, bottom_tip + 2.54))

    items = "\n".join((*symbols, *wires, *labels))
    return f"""(kicad_sch
  (version {KICAD_SCHEMATIC_VERSION})
  (generator "PCBSmith")
  (generator_version "0.1")
  (uuid {uuid4()})
  (paper "A4")

  (lib_symbols
{_render_library_symbols(name_prefix="PCBSmith:")}
  )
{items}
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""


def _render_symbol_library() -> str:
    return f"""(kicad_symbol_lib
  (version {KICAD_SYMBOL_LIBRARY_VERSION})
  (generator "PCBSmith")
  (generator_version "0.1")
{_render_library_symbols(name_prefix="")}
)
"""


def _render_library_symbols(*, name_prefix: str) -> str:
    return "\n\n".join(
        (
            _render_two_pin_box_library_symbol(
                f"{name_prefix}R",
                reference="R",
                value="R",
                description="Generic resistor",
                drawing=_resistor_symbol_drawing(),
                pin_length_mm="2.54",
            ),
            _render_two_pin_box_library_symbol(
                f"{name_prefix}C",
                reference="C",
                value="C",
                description="Ceramic capacitor",
                drawing=_capacitor_symbol_drawing(),
                pin_length_mm="4.318",
            ),
            _render_two_pin_box_library_symbol(
                f"{name_prefix}L",
                reference="L",
                value="L",
                description="PCB spiral sensing coil",
                drawing=_inductor_symbol_drawing(),
                pin_length_mm="2.54",
            ),
            _render_npn_library_symbol(f"{name_prefix}NPN"),
            render_connector_library_symbol(f"{name_prefix}CONN_01X03", pin_count=3),
        )
    )


def _render_npn_library_symbol(name: str) -> str:
    pins = "\n".join(
        (
            _generic_pin("1", "B", -7.62, 0.0, 0, "2.54"),
            _generic_pin("3", "C", 7.62, 2.54, 180, "2.54"),
            _generic_pin("2", "E", 7.62, -2.54, 180, "2.54"),
        )
    )
    return f"""  (symbol "{name}"
    (pin_numbers
      (hide no)
    )
    (pin_names
      (offset 0.762)
    )
    (exclude_from_sim yes)
    (in_bom yes)
    (on_board yes)
    {_library_property("Reference", "Q", 0, 6.35)}
    {_library_property("Value", "NPN", 0, -6.35)}
    {_library_property("Footprint", "", 0, 0, hidden=True)}
    {_library_property("Datasheet", "~", 0, 0, hidden=True)}
    {_library_property("Description", "NPN small-signal transistor", 0, 0, hidden=True)}
    (symbol "NPN_0_1"
      (rectangle
        (start -5.08 5.08)
        (end 5.08 -5.08)
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type background)
        )
      )
    )
    (symbol "NPN_1_1"
{pins}
    )
  )"""
