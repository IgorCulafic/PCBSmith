"""KiCad schematic exporter for the pear LED-ring board (label-net style).

One bank per ring: a row of series resistors (top net L{k}) over a row of
LEDs (bottom net GND), joined column-wise by the branch nets D{n}_A.
"""

from __future__ import annotations

from pathlib import Path

from pcbsmith.circuit.models import CircuitObject
from pcbsmith.kicad.export_divider_highpass_led import (
    KICAD_SCHEMATIC_VERSION,
    KICAD_SYMBOL_LIBRARY_VERSION,
    _label,
    _led_symbol_drawing,
    _render_project,
    _render_symbol_table,
    _render_two_pin_box_library_symbol,
    _resistor_symbol_drawing,
    _symbol,
    _validate_project_name,
    _wire,
)
from pcbsmith.kicad.export_mpu6050 import render_connector_library_symbol
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.pear_board import P1_PIN_NETS, ring_unit_counts

SUPPORTED_TOPOLOGY_ID = "pear_led_rings"

COLUMN_PITCH = 7.62
BANK_X0 = 30.48
BANK_Y0 = 38.1
BANK_PITCH = 80.01
LED_ROW_OFFSET = 30.48
STUB = 5.08


def export_pear_to_kicad(
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
        )

    symbols = [sym("PCBSmith:CONN_01X04", "P1", 12.7, 40.64)]
    wires: list[str] = []
    labels: list[str] = []

    # Connector pins stack upward from the anchor: pin 1 (GND) lowest.
    for index, connector_net in enumerate(P1_PIN_NETS):
        y = 40.64 - index * 2.54
        wires.append(_wire((12.7, y), (12.7 + STUB, y)))
        labels.append(_label(connector_net, 12.7 + STUB, y))

    unit = 0
    for ring, count in enumerate(ring_unit_counts()):
        resistor_y = BANK_Y0 + ring * BANK_PITCH
        led_y = resistor_y + LED_ROW_OFFSET
        for column in range(count):
            unit += 1
            x = BANK_X0 + column * COLUMN_PITCH
            branch = f"D{unit}_A"
            symbols.append(sym("PCBSmith:R", f"R{unit}", x, resistor_y, rotation=270))
            symbols.append(sym("PCBSmith:LED", f"D{unit}", x, led_y, rotation=270))
            for y_center, top_net, bottom_net in (
                (resistor_y, f"L{ring + 1}", branch),
                (led_y, branch, "GND"),
            ):
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
  (uuid {stable_kicad_uuid(
      "schematic-root",
      "machine",
      project_name,
      circuit.topology.topology_id,
  )})
  (paper "A3")

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
                f"{name_prefix}LED",
                reference="D",
                value="LED",
                description="Ring LED",
                drawing=_led_symbol_drawing(),
                pin_length_mm="3.81",
                pin_one_at="right",
            ),
            render_connector_library_symbol(f"{name_prefix}CONN_01X04", pin_count=4),
        )
    )
