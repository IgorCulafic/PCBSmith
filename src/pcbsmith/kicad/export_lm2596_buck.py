from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from pcbsmith.circuit.models import CircuitObject
from pcbsmith.kicad.export_divider_highpass_led import (
    KICAD_SCHEMATIC_VERSION,
    KICAD_SYMBOL_LIBRARY_VERSION,
    _capacitor_symbol_drawing,
    _diode_symbol_drawing,
    _label,
    _led_symbol_drawing,
    _library_property,
    _render_connector_01x02_library_symbol,
    _render_project,
    _render_symbol_table,
    _render_two_pin_box_library_symbol,
    _resistor_symbol_drawing,
    _symbol,
    _validate_project_name,
    _wire,
)

SUPPORTED_TOPOLOGY_ID = "lm2596_buck_regulator"
REQUIRED_COMPONENT_REFERENCES = (
    "P1",
    "CIN",
    "CIN2",
    "U1",
    "D1",
    "L1",
    "COUT",
    "COUT2",
    "RFB1",
    "RFB2",
    "RLED",
    "D2",
    "P2",
)


def export_lm2596_buck_to_kicad(
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


def _components(circuit: CircuitObject) -> dict[str, tuple[str, str]]:
    by_reference = {component.reference: component for component in circuit.components}
    missing = tuple(
        reference
        for reference in REQUIRED_COMPONENT_REFERENCES
        if reference not in by_reference
    )
    if missing:
        raise ValueError(f"KiCad export missing required components: {', '.join(missing)}")
    return {
        reference: (by_reference[reference].value, by_reference[reference].footprint or "")
        for reference in REQUIRED_COMPONENT_REFERENCES
    }


def _render_schematic(circuit: CircuitObject, project_name: str) -> str:
    fields = _components(circuit)

    def sym(
        lib: str,
        reference: str,
        x_mm: float,
        y_mm: float,
        *,
        rotation: int = 0,
        pin_count: int = 2,
    ) -> str:
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
            pin_count=pin_count,
            footprint=footprint,
        )

    symbols = (
        sym("PCBSmith:CONN_01X02", "P1", 25.4, 50.8),
        sym("PCBSmith:CP", "CIN", 35.56, 55.88, rotation=90),
        sym("PCBSmith:C", "CIN2", 40.64, 55.88, rotation=90),
        sym("PCBSmith:LM2596", "U1", 55.88, 55.88, pin_count=5),
        sym("PCBSmith:D_SCHOTTKY", "D1", 68.58, 63.5),
        sym("PCBSmith:L", "L1", 78.74, 50.8),
        sym("PCBSmith:CP", "COUT", 91.44, 55.88, rotation=90),
        sym("PCBSmith:C", "COUT2", 86.36, 55.88, rotation=90),
        sym("PCBSmith:R", "RFB1", 99.06, 55.88, rotation=90),
        sym("PCBSmith:R", "RFB2", 99.06, 66.04, rotation=90),
        sym("PCBSmith:R", "RLED", 106.68, 63.5),
        sym("PCBSmith:LED", "D2", 116.84, 63.5),
        sym("PCBSmith:CONN_01X02", "P2", 109.22, 50.8),
    )
    wires = (
        # VIN rail with bulk and HF capacitor taps, ending at the VIN pin tip.
        _wire((25.4, 50.8), (35.56, 50.8)),
        _wire((35.56, 50.8), (40.64, 50.8)),
        _wire((40.64, 50.8), (43.18, 50.8)),
        _wire((35.56, 60.96), (35.56, 76.2)),
        _wire((40.64, 60.96), (40.64, 76.2)),
        # Input connector return to ground.
        _wire((25.4, 48.26), (20.32, 48.26)),
        _wire((20.32, 48.26), (20.32, 76.2)),
        _wire((20.32, 76.2), (25.4, 76.2)),
        # ON/OFF pin tied to ground (regulator always enabled).
        _wire((43.18, 55.88), (41.91, 55.88)),
        _wire((41.91, 55.88), (41.91, 76.2)),
        # Regulator ground pin.
        _wire((55.88, 68.58), (55.88, 76.2)),
        # Switch node: OUT pin to catch diode tap and inductor.
        _wire((68.58, 50.8), (73.66, 50.8)),
        # Catch diode: cathode up to the switch node, anode down to ground.
        _wire((73.66, 63.5), (73.66, 50.8)),
        _wire((63.5, 63.5), (63.5, 76.2)),
        # Output rail with HF/bulk capacitor, feedback, and indicator taps.
        _wire((83.82, 50.8), (86.36, 50.8)),
        _wire((86.36, 50.8), (91.44, 50.8)),
        _wire((91.44, 50.8), (99.06, 50.8)),
        _wire((99.06, 50.8), (101.6, 50.8)),
        _wire((101.6, 50.8), (109.22, 50.8)),
        _wire((86.36, 60.96), (86.36, 76.2)),
        _wire((91.44, 60.96), (91.44, 76.2)),
        # Power-on indicator branch: VOUT -> RLED -> LED -> GND.
        _wire((101.6, 50.8), (101.6, 63.5)),
        _wire((121.92, 63.5), (121.92, 76.2)),
        # Feedback sense wire from the divider midpoint back to the FB pin.
        _wire((68.58, 55.88), (96.52, 55.88)),
        _wire((96.52, 55.88), (96.52, 60.96)),
        _wire((96.52, 60.96), (99.06, 60.96)),
        # Feedback divider lower leg to ground.
        _wire((99.06, 71.12), (99.06, 76.2)),
        # Output connector return to ground.
        _wire((109.22, 48.26), (114.3, 48.26)),
        _wire((114.3, 48.26), (114.3, 76.2)),
        # Ground rail, segmented at every tap point.
        _wire((25.4, 76.2), (35.56, 76.2)),
        _wire((35.56, 76.2), (40.64, 76.2)),
        _wire((40.64, 76.2), (41.91, 76.2)),
        _wire((41.91, 76.2), (55.88, 76.2)),
        _wire((55.88, 76.2), (63.5, 76.2)),
        _wire((63.5, 76.2), (86.36, 76.2)),
        _wire((86.36, 76.2), (91.44, 76.2)),
        _wire((91.44, 76.2), (99.06, 76.2)),
        _wire((99.06, 76.2), (114.3, 76.2)),
        _wire((114.3, 76.2), (121.92, 76.2)),
    )
    labels = (
        _label("VIN", 30.48, 50.8),
        _label("SW", 69.85, 50.8),
        _label("VOUT", 93.98, 50.8),
        _label("FB", 78.74, 55.88),
        _label("GND", 50.8, 76.2),
    )
    items = "\n".join((*symbols, *wires, *labels))
    return f"""(kicad_sch
  (version {KICAD_SCHEMATIC_VERSION})
  (generator "PCBSmith")
  (generator_version "0.1")
  (uuid {uuid4()})
  (paper "A4")

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
                f"{name_prefix}C",
                reference="C",
                value="C",
                description="Ceramic capacitor",
                drawing=_capacitor_symbol_drawing(),
                pin_length_mm="4.318",
            ),
            _render_two_pin_box_library_symbol(
                f"{name_prefix}CP",
                reference="C",
                value="CP",
                description="Polarized capacitor",
                drawing=_polarized_capacitor_symbol_drawing(),
                pin_length_mm="4.318",
                pin_one_at="right",
            ),
            _render_two_pin_box_library_symbol(
                f"{name_prefix}LED",
                reference="D",
                value="LED",
                description="Indicator LED",
                drawing=_led_symbol_drawing(),
                pin_length_mm="3.81",
                pin_one_at="right",
            ),
            _render_two_pin_box_library_symbol(
                f"{name_prefix}L",
                reference="L",
                value="L",
                description="Power inductor",
                drawing=_inductor_symbol_drawing(),
                pin_length_mm="2.54",
            ),
            _render_two_pin_box_library_symbol(
                f"{name_prefix}D_SCHOTTKY",
                reference="D",
                value="D_SCHOTTKY",
                description="Schottky catch diode",
                drawing=_diode_symbol_drawing("D_SCHOTTKY_0_1"),
                pin_length_mm="3.81",
                pin_one_at="right",
            ),
            _render_lm2596_library_symbol(f"{name_prefix}LM2596"),
            _render_connector_01x02_library_symbol(f"{name_prefix}CONN_01X02"),
        )
    )


_CP_PLUS_MARK = """      (polyline
        (pts
          (xy 3.175 1.905) (xy 4.445 1.905)
        )
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type none)
        )
      )
      (polyline
        (pts
          (xy 3.81 1.27) (xy 3.81 2.54)
        )
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type none)
        )
      )"""


def _polarized_capacitor_symbol_drawing() -> str:
    """Capacitor plates plus a "+" on the pin-1 side (KiCad C_Polarized)."""
    base = _capacitor_symbol_drawing().replace('"C_0_1"', '"CP_0_1"')
    body, separator, tail = base.rpartition("\n    )")
    if not separator or tail:
        raise ValueError("Capacitor symbol drawing changed shape unexpectedly.")
    return body + "\n" + _CP_PLUS_MARK + "\n    )"


def _inductor_symbol_drawing() -> str:
    return """    (symbol "L_0_1"
      (rectangle
        (start -2.54 -1.016)
        (end 2.54 1.016)
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type none)
        )
      )
    )"""


def _render_lm2596_library_symbol(name: str) -> str:
    return f"""  (symbol "{name}"
    (pin_numbers
      (hide yes)
    )
    (pin_names
      (offset 0.762)
    )
    (exclude_from_sim yes)
    (in_bom yes)
    (on_board yes)
    {_library_property("Reference", "U", 0, 9.652)}
    {_library_property("Value", "LM2596", 0, -11.43)}
    {_library_property("Footprint", "", 0, 0, hidden=True)}
    {_library_property("Datasheet", "~", 0, 0, hidden=True)}
    {_library_property("Description", "LM2596 step-down regulator", 0, 0, hidden=True)}
    (symbol "LM2596_0_1"
      (rectangle
        (start -10.16 8.89)
        (end 10.16 -10.16)
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type background)
        )
      )
    )
    (symbol "LM2596_1_1"
{_named_pin("1", "VIN", -12.7, 5.08, 0)}
{_named_pin("2", "OUT", 12.7, 5.08, 180)}
{_named_pin("3", "GND", 0, -12.7, 90)}
{_named_pin("4", "FB", 12.7, 0, 180)}
{_named_pin("5", "ON/OFF", -12.7, 0, 0)}
    )
  )"""


def _named_pin(number: str, name: str, x_mm: float, y_mm: float, direction: int) -> str:
    return f"""      (pin passive line
        (at {x_mm:g} {y_mm:g} {direction})
        (length 2.54)
        (name "{name}"
          (effects
            (font
              (size 1.27 1.27)
            )
          )
        )
        (number "{number}"
          (effects
            (font
              (size 1.27 1.27)
            )
          )
        )
      )"""
