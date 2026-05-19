from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from pcbsmith.circuit.models import CircuitObject

NM_PER_MM = 1_000_000
SUPPORTED_TOPOLOGY_ID = "divider_highpass_led_indicator"
KICAD_SCHEMATIC_VERSION = 20250114
KICAD_SYMBOL_LIBRARY_VERSION = 20250114
REQUIRED_COMPONENT_REFERENCES = ("R1", "R2", "C1", "R3", "D1")


def export_divider_highpass_led_to_kicad(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    project_name: str,
) -> dict[str, str]:
    if circuit.topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported circuit for KiCad export")

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


def _render_project() -> str:
    return '{\n  "meta": {"version": 1}\n}\n'


def _render_symbol_table() -> str:
    return """(sym_lib_table
  (version 7)
  (lib
    (name "PCBSmith")
    (type "KiCad")
    (uri "${KIPRJMOD}/PCBSmith.kicad_sym")
    (options "")
    (descr "PCBSmith generated symbols")
  )
)
"""


def _render_symbol_library() -> str:
    symbols = "\n\n".join(
        (
            _render_two_pin_box_library_symbol(
                "R",
                reference="R",
                value="R",
                description="Generic resistor",
                drawing=_resistor_symbol_drawing(),
                pin_length_mm="2.54",
            ),
            _render_two_pin_box_library_symbol(
                "C",
                reference="C",
                value="C",
                description="Generic capacitor",
                drawing=_capacitor_symbol_drawing(),
                pin_length_mm="4.318",
            ),
            _render_two_pin_box_library_symbol(
                "LED",
                reference="LED",
                value="LED",
                description="Generic LED",
                drawing=_led_symbol_drawing(),
                pin_length_mm="3.81",
            ),
            _render_connector_01x02_library_symbol(),
            _render_power_library_symbol(),
        )
    )
    return f"""(kicad_symbol_lib
  (version {KICAD_SYMBOL_LIBRARY_VERSION})
  (generator "PCBSmith")
  (generator_version "0.1")
{symbols}
)
"""


def _render_schematic(circuit: CircuitObject, project_name: str) -> str:
    component_values = _component_values(circuit)
    symbols = (
        _symbol("PCBSmith:CONN_01X02", "P1", "5V input", 20, 40, project_name),
        _symbol("PCBSmith:R", "R1", component_values["R1"], 45, 40, project_name),
        _symbol("PCBSmith:R", "R2", component_values["R2"], 55, 55, project_name, rotation=90),
        _symbol("PCBSmith:C", "C1", component_values["C1"], 80, 40, project_name),
        _symbol("PCBSmith:R", "RLOAD", "10k", 105, 55, project_name, rotation=90),
        _symbol("PCBSmith:R", "R3", component_values["R3"], 130, 40, project_name),
        _symbol("PCBSmith:LED", "D1", component_values["D1"], 155, 40, project_name),
        _symbol("PCBSmith:GND", "#PWR01", "GND", 20, 70, project_name),
    )
    wires = (
        _wire((20, 40), (39.92, 40)),
        _wire((50.08, 40), (74.92, 40)),
        _wire((55, 40), (55, 49.92)),
        _wire((55, 60.08), (55, 70)),
        _wire((85.08, 40), (124.92, 40)),
        _wire((105, 40), (105, 49.92)),
        _wire((105, 60.08), (105, 70)),
        _wire((135.08, 40), (149.92, 40)),
        _wire((160.08, 40), (160.08, 70)),
        _wire((20, 42.54), (20, 70)),
    )
    labels = (
        _label("VIN", 30, 40),
        _label("DIV_OUT", 65, 40),
        _label("DIV_OUT", 55, 49.92),
        _label("HP_OUT", 115, 40),
        _label("HP_OUT", 105, 49.92),
        _label("GND", 55, 70),
        _label("GND", 105, 70),
        _label("GND", 160.08, 70),
        _label("GND", 20, 70),
    )
    items = "\n".join((*symbols, *wires, *labels, _spice_directives()))
    return f"""(kicad_sch
  (version {KICAD_SCHEMATIC_VERSION})
  (generator "PCBSmith")
  (generator_version "0.1")
  (uuid {uuid4()})
  (paper "A4")

  (lib_symbols)
{items}
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""


def _symbol(
    lib_id: str,
    reference: str,
    value: str,
    x_mm: float,
    y_mm: float,
    project_name: str,
    *,
    rotation: int = 0,
) -> str:
    return f"""  (symbol
    (lib_id "{lib_id}")
    (at {_format_mm(x_mm)} {_format_mm(y_mm)} {rotation})
    (unit 1)
    (exclude_from_sim no)
    (in_bom yes)
    (on_board yes)
    (dnp no)
    (uuid "{uuid4()}")
    {_property("Reference", reference, x_mm, y_mm - 2.54, hidden=reference.startswith("#"))}
    {_property("Value", value, x_mm, y_mm + 2.54)}
    {_property("Footprint", "", x_mm, y_mm, hidden=True)}
    {_property("Datasheet", "~", x_mm, y_mm, hidden=True)}
    (pin "1"
      (uuid "{uuid4()}")
    )
    (pin "2"
      (uuid "{uuid4()}")
    )
    (instances
      (project "{_escape(project_name)}"
        (path "/"
          (reference "{_escape(reference)}")
          (unit 1)
        )
      )
    )
  )"""


def _wire(start: tuple[float, float], end: tuple[float, float]) -> str:
    return f"""  (wire
    (pts
      (xy {_format_mm(start[0])} {_format_mm(start[1])})
      (xy {_format_mm(end[0])} {_format_mm(end[1])})
    )
    (stroke
      (width 0)
      (type solid)
    )
    (uuid "{uuid4()}")
  )"""


def _label(name: str, x_mm: float, y_mm: float) -> str:
    return f"""  (label "{_escape(name)}"
    (at {_format_mm(x_mm)} {_format_mm(y_mm)} 0)
    (effects
      (font
        (size 1.27 1.27)
      )
    )
    (uuid "{uuid4()}")
  )"""


def _spice_directives() -> str:
    directives = ".op\n.ac dec 20 10 100k\n.print ac v(HP_OUT)"
    return f"""  (text "{_escape(directives)}"
    (at 20 85 0)
    (effects
      (font
        (size 1.27 1.27)
      )
    )
    (uuid "{uuid4()}")
  )"""


def _component_values(circuit: CircuitObject) -> dict[str, str]:
    component_values = {component.reference: component.value for component in circuit.components}
    missing = tuple(
        reference
        for reference in REQUIRED_COMPONENT_REFERENCES
        if reference not in component_values
    )
    if missing:
        raise ValueError(f"KiCad export missing required components: {', '.join(missing)}")
    return component_values


def _property(
    name: str,
    value: str,
    x_mm: float,
    y_mm: float,
    *,
    hidden: bool = False,
) -> str:
    hide = "\n        (hide yes)" if hidden else ""
    return f"""(property "{_escape(name)}" "{_escape(value)}"
      (at {_format_mm(x_mm)} {_format_mm(y_mm)} 0)
      (effects
        (font
          (size 1.27 1.27)
        ){hide}
      )
    )"""


def _render_two_pin_box_library_symbol(
    name: str,
    *,
    reference: str,
    value: str,
    description: str,
    drawing: str,
    pin_length_mm: str,
) -> str:
    return f"""  (symbol "{name}"
    (pin_numbers
      (hide yes)
    )
    (pin_names
      (offset 0)
    )
    (exclude_from_sim no)
    (in_bom yes)
    (on_board yes)
    {_library_property("Reference", reference, 0, -2.54)}
    {_library_property("Value", value, 0, 2.54)}
    {_library_property("Footprint", "", 0, 0, hidden=True)}
    {_library_property("Datasheet", "~", 0, 0, hidden=True)}
    {_library_property("Description", description, 0, 0, hidden=True)}
{drawing}
    (symbol "{value}_1_1"
{_generic_pin("1", "1", -5.08, 0, 0, pin_length_mm)}
{_generic_pin("2", "2", 5.08, 0, 180, pin_length_mm)}
    )
  )"""


def _render_connector_01x02_library_symbol() -> str:
    return f"""  (symbol "CONN_01X02"
    (pin_numbers
      (hide no)
    )
    (pin_names
      (offset 0.762)
    )
    (exclude_from_sim no)
    (in_bom yes)
    (on_board yes)
    {_library_property("Reference", "J", 3.81, -2.54)}
    {_library_property("Value", "Conn_01x02", 3.81, 5.08)}
    {_library_property("Footprint", "", 0, 0, hidden=True)}
    {_library_property("Datasheet", "~", 0, 0, hidden=True)}
    {_library_property("Description", "Generic two-pin connector", 0, 0, hidden=True)}
    (symbol "CONN_01X02_0_1"
      (rectangle
        (start 1.27 -1.27)
        (end 5.08 3.81)
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type none)
        )
      )
    )
    (symbol "CONN_01X02_1_1"
{_generic_pin("1", "Pin_1", 0, 0, 0, "2.54")}
{_generic_pin("2", "Pin_2", 0, -2.54, 0, "2.54")}
    )
  )"""


def _render_power_library_symbol() -> str:
    return f"""  (symbol "GND"
    (power)
    (pin_numbers
      (hide yes)
    )
    (pin_names
      (offset 0)
      (hide yes)
    )
    (exclude_from_sim no)
    (in_bom yes)
    (on_board yes)
    {_library_property("Reference", "#PWR", 0, -3.81, hidden=True)}
    {_library_property("Value", "GND", 0, -2.54)}
    {_library_property("Footprint", "", 0, 0, hidden=True)}
    {_library_property("Datasheet", "", 0, 0, hidden=True)}
    {_library_property("Description", "Ground power symbol", 0, 0, hidden=True)}
{_gnd_symbol_drawing()}
    (symbol "GND_1_1"
      (pin power_out line
        (at 0 0 270)
        (length 0)
        (name "GND"
          (effects
            (font
              (size 1.27 1.27)
            )
          )
        )
        (number "1"
          (effects
            (font
              (size 1.27 1.27)
            )
          )
        )
      )
    )
  )"""


def _generic_pin(
    number: str,
    name: str,
    x_mm: float,
    y_mm: float,
    direction: int,
    length_mm: str,
) -> str:
    return f"""      (pin passive line
        (at {_format_mm(x_mm)} {_format_mm(y_mm)} {direction})
        (length {length_mm})
        (name "{_escape(name)}"
          (effects
            (font
              (size 1.27 1.27)
            )
          )
        )
        (number "{_escape(number)}"
          (effects
            (font
              (size 1.27 1.27)
            )
          )
        )
      )"""


def _resistor_symbol_drawing() -> str:
    return """    (symbol "R_0_1"
      (rectangle
        (start -2.54 -1.27)
        (end 2.54 1.27)
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type none)
        )
      )
    )"""


def _capacitor_symbol_drawing() -> str:
    return """    (symbol "C_0_1"
      (polyline
        (pts
          (xy -0.762 1.905) (xy -0.762 -1.905)
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
          (xy 0.762 1.905) (xy 0.762 -1.905)
        )
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type none)
        )
      )
    )"""


def _led_symbol_drawing() -> str:
    return f"""{_diode_symbol_drawing("LED_0_1")}
    (symbol "LED_0_2"
      (polyline
        (pts
          (xy 1.524 1.524) (xy 2.794 2.794)
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
          (xy 2.032 0.508) (xy 3.302 1.778)
        )
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type none)
        )
      )
    )"""


def _diode_symbol_drawing(symbol_name: str) -> str:
    return f"""    (symbol "{symbol_name}"
      (polyline
        (pts
          (xy -1.27 1.905) (xy -1.27 -1.905) (xy 1.27 0) (xy -1.27 1.905)
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
          (xy 1.27 1.905) (xy 1.27 -1.905)
        )
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type none)
        )
      )
    )"""


def _gnd_symbol_drawing() -> str:
    return """    (symbol "GND_0_1"
      (polyline
        (pts
          (xy 0 0) (xy 0 -1.27) (xy 1.27 -1.27)
          (xy 0 -2.54) (xy -1.27 -1.27) (xy 0 -1.27)
        )
        (stroke
          (width 0)
          (type default)
        )
        (fill
          (type none)
        )
      )
    )"""


def _library_property(
    name: str,
    value: str,
    x_mm: float,
    y_mm: float,
    *,
    hidden: bool = False,
) -> str:
    hide = "\n        (hide yes)" if hidden else ""
    return f"""(property "{_escape(name)}" "{_escape(value)}"
      (at {_format_mm(x_mm)} {_format_mm(y_mm)} 0)
      (effects
        (font
          (size 1.27 1.27)
        ){hide}
      )
    )"""


def _format_mm(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
