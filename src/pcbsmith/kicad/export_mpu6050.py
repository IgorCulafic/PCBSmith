"""KiCad schematic exporter for the MPU-6050 IMU breakout.

Uses label-net style: every used pin gets a short stub wire ending in a net
label (labels join nets without drawn routing, and rule 7.2 requires every
net to be labelled anyway); every unused pin gets an explicit no-connect
marker so ERC accounts for all 24 QFN pins.
"""

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
from pcbsmith.kicad.symbols import (
    load_symbol,
    pin_stub,
    render_symbol_for_schematic,
)

SUPPORTED_TOPOLOGY_ID = "mpu6050_imu"

# Pin map from the datasheet (PS-MPU-6000A-00 rev 3.4, section 7.1, p21).
MPU6050_PIN_NAMES = {
    1: "CLKIN",
    6: "AUX_DA",
    7: "AUX_CL",
    8: "VLOGIC",
    9: "AD0",
    10: "REGOUT",
    11: "FSYNC",
    12: "INT",
    13: "VDD",
    18: "GND",
    19: "RESV",
    20: "CPOUT",
    21: "RESV",
    22: "RESV",
    23: "SCL",
    24: "SDA",
}
# Net bound to each used pin; everything else gets a no-connect marker.
MPU6050_PIN_NETS = {
    1: "GND",     # CLKIN: connect to GND if unused (p21)
    6: "XDA",     # auxiliary I2C master data, broken out (GY-521 style)
    7: "XCL",     # auxiliary I2C master clock, broken out
    8: "VDD",     # VLOGIC tied to VDD (p12: 1.8V+/-5% or VDD)
    9: "AD0",
    10: "REGOUT",
    11: "GND",    # FSYNC: connect to GND if unused (p21)
    12: "INT",    # interrupt output, broken out
    13: "VDD",
    18: "GND",
    20: "CPOUT",
    23: "SCL",
    24: "SDA",
}
# Breakout header order matches the ubiquitous GY-521 module.
HEADER_NETS = ("VDD", "GND", "SCL", "SDA", "XDA", "XCL", "AD0", "INT")

U1_X = 88.9
U1_Y = 63.5
U1_TIP_DX = 12.7
STUB_MM = 5.08


def export_mpu6050_to_kicad(
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

    def sym(
        lib: str, reference: str, x: float, y: float, *, pin_count: int,
        in_bom: bool = True, on_board: bool = True,
    ) -> str:
        value, footprint = fields.get(reference, ("", ""))
        if reference.startswith("#"):
            value, footprint = reference.lstrip("#FLG0") or "flag", ""
            value = "PWR_FLAG"
        return _symbol(
            lib, reference, value, x, y, project_name,
            exclude_from_sim=True, footprint=footprint,
            in_bom=in_bom, on_board=on_board, pin_count=pin_count,
        )

    mpu = load_symbol("Sensor_Motion:MPU-6050")
    connector = load_symbol("Connector_Generic:Conn_01x08")
    resistor = load_symbol("Device:R")
    capacitor = load_symbol("Device:C")
    flag = load_symbol("power:PWR_FLAG")

    symbols: list[str] = [
        sym("Connector_Generic:Conn_01x08", "P1", 30.48, 76.2, pin_count=8),
        sym("Sensor_Motion:MPU-6050", "U1", U1_X, U1_Y, pin_count=24),
    ]
    wires: list[str] = []
    labels: list[str] = []

    for index, connector_net in enumerate(HEADER_NETS):
        tip, endpoint = pin_stub(connector, str(index + 1), (30.48, 76.2))
        wires.append(_wire(tip, endpoint))
        labels.append(_label(connector_net, *endpoint))

    # Sensor pins: nets from the datasheet-derived table; every unused pin
    # on the official symbol is NC/RESV typed no_connect, which ERC
    # enforces natively (rule 7.3's schematic-side twin).
    for pin_number, net in MPU6050_PIN_NETS.items():
        tip, endpoint = pin_stub(mpu, str(pin_number), (U1_X, U1_Y))
        wires.append(_wire(tip, endpoint))
        labels.append(_label(net, *endpoint))

    # Support passives (Device parts are natively vertical, pin 1 up).
    passives = (
        ("C1", capacitor, "Device:C", 35.56, "REGOUT", "GND"),
        ("C2", capacitor, "Device:C", 45.72, "VDD", "GND"),
        ("C3", capacitor, "Device:C", 55.88, "CPOUT", "GND"),
        ("C4", capacitor, "Device:C", 66.04, "VDD", "GND"),
        ("R1", resistor, "Device:R", 116.84, "VDD", "SDA"),
        ("R2", resistor, "Device:R", 129.54, "VDD", "SCL"),
        ("R3", resistor, "Device:R", 142.24, "AD0", "GND"),
    )
    passive_y = 99.06
    for reference, imported, lib, x, top_net, bottom_net in passives:
        symbols.append(sym(lib, reference, x, passive_y, pin_count=2))
        for pin_name, net in (("1", top_net), ("2", bottom_net)):
            tip, endpoint = pin_stub(imported, pin_name, (x, passive_y))
            wires.append(_wire(tip, endpoint))
            labels.append(_label(net, *endpoint))

    # Power flags: the sensor's VDD/VLOGIC/GND pins are power_in; the
    # header pins are passive, so ERC needs an explicit source marker.
    for index, net in enumerate(("VDD", "GND")):
        x = 35.56 + index * 12.7
        symbols.append(
            sym("power:PWR_FLAG", f"#FLG0{index + 1}", x, 116.84,
                pin_count=1, in_bom=False, on_board=False)
        )
        tip, _out = pin_stub(flag, "1", (x, 116.84))
        endpoint = (tip[0], tip[1] + 2.54)
        wires.append(_wire(tip, endpoint))
        labels.append(_label(net, *endpoint))

    lib_symbols = "\n".join(
        render_symbol_for_schematic(load_symbol(lib_id))
        for lib_id in (
            "Device:R", "Device:C", "Sensor_Motion:MPU-6050",
            "Connector_Generic:Conn_01x08", "power:PWR_FLAG",
        )
    )
    items = "\n".join((*symbols, *wires, *labels))
    return f"""(kicad_sch
  (version {KICAD_SCHEMATIC_VERSION})
  (generator "PCBSmith")
  (generator_version "0.1")
  (uuid {uuid4()})
  (paper "A3")

  (lib_symbols
{lib_symbols}
  )
{items}
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""


def _no_connect(x_mm: float, y_mm: float) -> str:
    from uuid import uuid4 as _uuid4

    return f"""  (no_connect
    (at {x_mm:g} {y_mm:g})
    (uuid "{_uuid4()}")
  )"""


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
            _render_mpu6050_library_symbol(f"{name_prefix}MPU6050"),
            render_connector_library_symbol(f"{name_prefix}CONN_01X08", pin_count=8),
        )
    )


def _render_mpu6050_library_symbol(name: str) -> str:
    pins: list[str] = []
    for pin in range(1, 13):
        # Left column, pin 1 at the top; symbol y axis points up.
        local_y = 15.24 - pin * 2.54
        pins.append(
            _generic_pin(str(pin), MPU6050_PIN_NAMES.get(pin, "NC"), -12.7, local_y, 0, "2.54")
        )
    for pin in range(13, 25):
        # Right column, pin 13 at the bottom (counter-clockwise QFN order).
        local_y = -15.24 + (pin - 13) * 2.54
        pins.append(
            _generic_pin(str(pin), MPU6050_PIN_NAMES.get(pin, "NC"), 12.7, local_y, 180, "2.54")
        )
    rendered_pins = "\n".join(pins)
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
    {_library_property("Reference", "U", 0, 17.78)}
    {_library_property("Value", "MPU-6050", 0, -19.05)}
    {_library_property("Footprint", "", 0, 0, hidden=True)}
    {_library_property("Datasheet", "~", 0, 0, hidden=True)}
    {_library_property("Description", "InvenSense 6-axis IMU, I2C", 0, 0, hidden=True)}
    (symbol "MPU6050_0_1"
      (rectangle
        (start -10.16 16.51)
        (end 10.16 -17.78)
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type background)
        )
      )
    )
    (symbol "MPU6050_1_1"
{rendered_pins}
    )
  )"""


def render_connector_library_symbol(name: str, *, pin_count: int) -> str:
    """Generic 1xN pin-header symbol: pin 1 at the anchor, pins stack up."""
    bare = name.split(":")[-1]
    pins = "\n".join(
        _generic_pin(str(pin), f"Pin_{pin}", 0, (pin - 1) * 2.54, 0, "2.54")
        for pin in range(1, pin_count + 1)
    )
    top = (pin_count - 1) * 2.54 + 1.27
    return f"""  (symbol "{name}"
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
    {_library_property("Value", bare, 3.81, top + 1.27)}
    {_library_property("Footprint", "", 0, 0, hidden=True)}
    {_library_property("Datasheet", "~", 0, 0, hidden=True)}
    {_library_property("Description", "Generic pin header", 0, 0, hidden=True)}
    (symbol "{bare}_0_1"
      (rectangle
        (start 1.27 -1.27)
        (end 5.08 {top:g})
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type none)
        )
      )
    )
    (symbol "{bare}_1_1"
{pins}
    )
  )"""
