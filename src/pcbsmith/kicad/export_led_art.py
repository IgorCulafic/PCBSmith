"""KiCad schematic exporter for the LED text-matrix topology.

The schematic shows the electrical structure, not the art: every glyph-column
string is drawn as one vertical branch (resistor, then its LEDs) between the
VIN rail on top and the GND rail on the bottom. The board layout is where the
glyph geometry appears.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from pcbsmith.circuit.models import CircuitObject
from pcbsmith.generation.led_art import LedArtPlan
from pcbsmith.kicad.export_divider_highpass_led import (
    KICAD_SCHEMATIC_VERSION,
    KICAD_SYMBOL_LIBRARY_VERSION,
    _label,
    _led_symbol_drawing,
    _render_connector_01x02_library_symbol,
    _render_project,
    _render_symbol_table,
    _render_two_pin_box_library_symbol,
    _resistor_symbol_drawing,
    _symbol,
    _validate_project_name,
    _wire,
)

SUPPORTED_TOPOLOGY_ID = "led_text_matrix"

COLUMN_PITCH_MM = 10.16
FIRST_COLUMN_X_MM = 25.4
ELEMENT_PITCH_MM = 12.7
FIRST_ELEMENT_Y_MM = 35.56
PIN_TIP_OFFSET_MM = 5.08
VIN_RAIL_Y_MM = 25.4
GND_RAIL_Y_MM = 114.3
CONNECTOR_X_MM = 15.24
CONNECTOR_Y_MM = 50.8
CONNECTOR_VIN_STUB_X_MM = 17.78
CONNECTOR_GND_STUB_X_MM = 12.7
# Probing the exported netlist showed rotation 90 puts pin 1 (the LED anode)
# at the BOTTOM; rotation 270 puts it at the TOP so current flows
# rail -> pin 1 -> pin 2 -> next element and every anode faces supply.
ELEMENT_ROTATION = 270


def export_led_art_to_kicad(
    circuit: CircuitObject,
    plan: LedArtPlan,
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
    schematic_file.write_text(
        _render_schematic(circuit, plan, project_name), encoding="utf-8"
    )
    return {
        "project_file": str(project_file),
        "schematic_file": str(schematic_file),
        "symbol_library": str(symbol_library),
    }


def _render_schematic(
    circuit: CircuitObject,
    plan: LedArtPlan,
    project_name: str,
) -> str:
    fields = {
        component.reference: (component.value, component.footprint or "")
        for component in circuit.components
    }
    missing = [
        reference
        for string in plan.strings
        for reference in (string.resistor_ref, *string.led_refs)
        if reference not in fields
    ]
    if "P1" not in fields:
        missing.append("P1")
    if missing:
        raise ValueError(
            "KiCad export missing required components: " + ", ".join(missing)
        )

    def sym(lib: str, reference: str, x_mm: float, y_mm: float, rotation: int) -> str:
        value, footprint = fields[reference]
        return _symbol(
            lib,
            reference,
            value,
            x_mm,
            y_mm,
            project_name,
            rotation=rotation,
            exclude_from_sim=True,
            footprint=footprint,
        )

    symbols: list[str] = [
        sym("PCBSmith:CONN_01X02", "P1", CONNECTOR_X_MM, CONNECTOR_Y_MM, 0)
    ]
    wires: list[str] = [
        # Connector pin 1 detours right, then up to the VIN rail, staying clear
        # of the pin-2 tip directly above the anchor.
        _wire((CONNECTOR_X_MM, CONNECTOR_Y_MM), (CONNECTOR_VIN_STUB_X_MM, CONNECTOR_Y_MM)),
        _wire(
            (CONNECTOR_VIN_STUB_X_MM, CONNECTOR_Y_MM),
            (CONNECTOR_VIN_STUB_X_MM, VIN_RAIL_Y_MM),
        ),
        _wire(
            (CONNECTOR_X_MM, CONNECTOR_Y_MM - 2.54),
            (CONNECTOR_GND_STUB_X_MM, CONNECTOR_Y_MM - 2.54),
        ),
        _wire(
            (CONNECTOR_GND_STUB_X_MM, CONNECTOR_Y_MM - 2.54),
            (CONNECTOR_GND_STUB_X_MM, GND_RAIL_Y_MM),
        ),
    ]
    labels: list[str] = []
    vin_taps: list[float] = [CONNECTOR_VIN_STUB_X_MM]
    gnd_taps: list[float] = [CONNECTOR_GND_STUB_X_MM]

    for index, string in enumerate(plan.strings):
        x = FIRST_COLUMN_X_MM + index * COLUMN_PITCH_MM
        vin_taps.append(x)
        gnd_taps.append(x)
        elements = (string.resistor_ref, *string.led_refs)
        for position, reference in enumerate(elements):
            y = FIRST_ELEMENT_Y_MM + position * ELEMENT_PITCH_MM
            lib = "PCBSmith:R" if position == 0 else "PCBSmith:LED"
            symbols.append(sym(lib, reference, x, y, ELEMENT_ROTATION))
        first_top = FIRST_ELEMENT_Y_MM - PIN_TIP_OFFSET_MM
        wires.append(_wire((x, VIN_RAIL_Y_MM), (x, first_top)))
        for position in range(len(elements) - 1):
            upper_bottom = (
                FIRST_ELEMENT_Y_MM + position * ELEMENT_PITCH_MM + PIN_TIP_OFFSET_MM
            )
            lower_top = (
                FIRST_ELEMENT_Y_MM
                + (position + 1) * ELEMENT_PITCH_MM
                - PIN_TIP_OFFSET_MM
            )
            wires.append(_wire((x, upper_bottom), (x, lower_top)))
            # Every series junction gets a label: kicad-cli silently drops
            # UNLABELLED nets from both ERC connectivity and the exported
            # netlist (discovered by probing; see docs/ai-rule-suggestions.md),
            # and named nets also read better on the board.
            labels.append(
                _label(f"S{index + 1}_{position + 1}", x, (upper_bottom + lower_top) / 2)
            )
        last_bottom = (
            FIRST_ELEMENT_Y_MM
            + (len(elements) - 1) * ELEMENT_PITCH_MM
            + PIN_TIP_OFFSET_MM
        )
        wires.append(_wire((x, last_bottom), (x, GND_RAIL_Y_MM)))

    # Rails segmented at every tap so KiCad connectivity sees T junctions.
    for taps, rail_y in ((vin_taps, VIN_RAIL_Y_MM), (gnd_taps, GND_RAIL_Y_MM)):
        ordered = sorted(set(taps))
        for left, right in zip(ordered, ordered[1:], strict=False):
            wires.append(_wire((left, rail_y), (right, rail_y)))

    labels.append(
        _label("VIN", (CONNECTOR_VIN_STUB_X_MM + FIRST_COLUMN_X_MM) / 2, VIN_RAIL_Y_MM)
    )
    labels.append(
        _label("GND", (CONNECTOR_GND_STUB_X_MM + FIRST_COLUMN_X_MM) / 2, GND_RAIL_Y_MM)
    )
    items = "\n".join((*symbols, *wires, *labels))
    return f"""(kicad_sch
  (version {KICAD_SCHEMATIC_VERSION})
  (generator "PCBSmith")
  (generator_version "0.1")
  (uuid {uuid4()})
  (paper "A3")

  {_render_embedded_symbol_library()}
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


def _render_embedded_symbol_library() -> str:
    return f"""(lib_symbols
{_render_library_symbols(name_prefix="PCBSmith:")}
  )"""


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
                description="Matrix LED",
                drawing=_led_symbol_drawing(),
                pin_length_mm="3.81",
            ),
            _render_connector_01x02_library_symbol(f"{name_prefix}CONN_01X02"),
        )
    )
