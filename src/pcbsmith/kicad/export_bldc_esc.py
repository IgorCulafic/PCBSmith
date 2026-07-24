# ruff: noqa: E501 -- exact KiCad S-expression records are intentionally kept whole.
"""KiCad machine-schematic exporter for BLDC ESC R001.

Every connected pin receives an explicit net label.  The two custom symbols
preserve the manufacturer's package pin numbers for the DRV8353S RTA and the
16-lead Infineon TOLT MOSFET; this prevents a visually plausible three-pin
MOSFET abstraction from hiding a package-pad mapping error.
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path

from pcbsmith.circuit.models import CircuitObject
from pcbsmith.kicad.bldc_esc_models import generate_bldc_esc_proxy_models
from pcbsmith.kicad.export_divider_highpass_led import (
    KICAD_SCHEMATIC_VERSION,
    KICAD_SYMBOL_LIBRARY_VERSION,
    _generic_pin,
    _label,
    _library_property,
    _render_project,
    _render_symbol_table,
    _symbol,
    _validate_project_name,
    _wire,
)
from pcbsmith.kicad.export_mpu6050 import _no_connect
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.symbols import load_symbol, pin_stub, render_symbol_for_schematic

SUPPORTED_TOPOLOGY_ID = "bldc_esc_3phase_60a_r001"

MCU = "MCU_ST_STM32G4:STM32G431CBTx"
LM5164 = "Regulator_Switching:LM5164DDA"
TLV767 = "Regulator_Linear:TLV76733QWDRBxQ1"
RESISTOR = "Device:R"
CAPACITOR = "Device:C"
CAP_POLARIZED = "Device:C_Polarized"
INDUCTOR = "Device:L"
THERMISTOR = "Device:Thermistor"
LED = "Device:LED"
CONNECTOR_1 = "Connector_Generic:Conn_01x01"
CONNECTOR_6 = "Connector_Generic:Conn_01x06"
CONNECTOR_8 = "Connector_Generic:Conn_01x08"
CONNECTOR_10 = "Connector_Generic:Conn_02x05_Odd_Even"
PWR_FLAG = "power:PWR_FLAG"

DRV8353 = "PCBSmith:DRV8353SRTAT"
TOLT_MOSFET = "PCBSmith:IPTC011N08NM5"
SMPD_TVS = "PCBSmith:7KPD_SMPD"

MCU_PIN_NETS = {
    "1": "3V3",
    "2": "HALL_U",
    "3": "HALL_V",
    "4": "HALL_W",
    "7": "NRST",
    "8": "CSA_U",
    "9": "CSA_V",
    "10": "CSA_W",
    "11": "VBUS_SENSE",
    "12": "PHASE_U_SENSE",
    "13": "PHASE_V_SENSE",
    "14": "PHASE_W_SENSE",
    "15": "NTC_U",
    "16": "NTC_V",
    "17": "NTC_W",
    "18": "DRV_EN",
    "19": "AGND",
    "20": "3V3A",
    "21": "3V3A",
    "22": "UART_TX",
    "23": "PGND",
    "24": "3V3",
    "25": "UART_RX",
    "26": "DRV_NFAULT",
    "27": "PWM_UL",
    "28": "PWM_VL",
    "29": "PWM_WL",
    "30": "PWM_UH",
    "31": "PWM_VH",
    "32": "PWM_WH",
    "35": "PGND",
    "33": "AUX2",
    "34": "AUX3",
    "36": "3V3",
    "37": "SWDIO",
    "38": "SWCLK",
    "39": "DRV_NSCS",
    "40": "DRV_SCLK",
    "41": "DRV_SDO",
    "42": "DRV_SDI",
    "43": "BRAKE_CMD",
    "44": "AUX1",
    "45": "I2C_SCL",
    "46": "I2C_SDA",
    "47": "PGND",
    "48": "3V3",
}
MCU_NO_CONNECTS = ("5", "6")

DRV_PIN_NETS = {
    "1": "DRV_CPL",
    "2": "DRV_CPH",
    "3": "BAT_P",
    "4": "BAT_P",
    "5": "DRV_VCP",
    "6": "DRV_GH_U",
    "7": "PHASE_U",
    "8": "DRV_GL_U",
    "9": "USHUNT_H",
    "10": "PGND",
    "11": "PGND",
    "12": "VSHUNT_H",
    "13": "DRV_GL_V",
    "14": "PHASE_V",
    "15": "DRV_GH_V",
    "16": "DRV_GH_W",
    "17": "PHASE_W",
    "18": "DRV_GL_W",
    "19": "WSHUNT_H",
    "20": "PGND",
    "21": "CSA_W",
    "22": "CSA_V",
    "23": "CSA_U",
    "24": "3V3A",
    "25": "AGND",
    "26": "DRV_NFAULT",
    "27": "DRV_SDO",
    "28": "DRV_SDI",
    "29": "DRV_SCLK",
    "30": "DRV_NSCS",
    "31": "DRV_EN",
    "32": "PWM_UH",
    "33": "PWM_UL",
    "34": "PWM_VH",
    "35": "PWM_VL",
    "36": "PWM_WH",
    "37": "PWM_WL",
    "38": "DRV_DVDD",
    "39": "PGND",
    "40": "DRV_VGLS",
    "41": "PGND",
}


def _mosfet_nets(index: int) -> dict[str, str]:
    phase = "UVW"[(index - 1) // 2]
    high_side = index % 2 == 1
    source = f"PHASE_{phase}" if high_side else f"{phase}SHUNT_H"
    drain = "BAT_P" if high_side else f"PHASE_{phase}"
    gate = f"GATE_{phase}{'H' if high_side else 'L'}"
    return {
        **{str(pin): source for pin in range(1, 8)},
        "8": gate,
        **{str(pin): drain for pin in range(9, 17)},
    }


def _instances() -> tuple[tuple[str, str, float, float, dict[str, str]], ...]:
    result: list[tuple[str, str, float, float, dict[str, str]]] = []
    # Power entry and distributed DC link.
    for index, net in enumerate(("BAT_P", "PGND", "PHASE_U", "PHASE_V", "PHASE_W"), start=1):
        result.append((f"J{index}", CONNECTOR_1, 20.32 + (index - 1) * 17.78, 30.48, {"1": net}))
    result.append(("D1", SMPD_TVS, 116.84, 30.48, {"1": "PGND", "2": "PGND", "K": "BAT_P"}))
    for index in range(1, 9):
        column = (index - 1) % 4
        row = (index - 1) // 4
        result.append(
            (
                f"CB{index}",
                CAP_POLARIZED,
                144.78 + column * 55.88,
                25.4 + row * 25.4,
                {"1": "BAT_P", "2": "PGND"},
            )
        )
    for index in range(1, 7):
        column = (index - 1) % 3
        row = (index - 1) // 3
        result.append(
            (
                f"CHF{index}",
                CAPACITOR,
                370.84 + column * 40.64,
                25.4 + row * 25.4,
                {"1": "BAT_P", "2": "PGND"},
            )
        )

    # Controllers and their power support.
    result.extend(
        (
            ("U1", MCU, 76.2, 104.14, MCU_PIN_NETS),
            ("U2", DRV8353, 210.82, 104.14, DRV_PIN_NETS),
            (
                "U3",
                LM5164,
                337.82,
                88.9,
                {
                    "1": "PGND",
                    "2": "BAT_P",
                    "3": "BUCK_EN",
                    "4": "BUCK_RON",
                    "5": "BUCK_FB",
                    "6": "BUCK_PGOOD",
                    "7": "BUCK_BST",
                    "8": "BUCK_SW",
                    "9": "PGND",
                },
            ),
            (
                "U4",
                TLV767,
                401.32,
                88.9,
                {
                    "1": "3V3",
                    "3": "3V3",
                    "4": "PGND",
                    "5": "5V",
                    "6": "PGND",
                    "8": "5V",
                    "9": "PGND",
                },
            ),
        )
    )

    # Three physical half bridges and two-terminal shunts.  The PCB must take
    # independent Kelvin traces from the inner edge of each shunt land.
    for index in range(1, 7):
        result.append(
            (f"Q{index}", TOLT_MOSFET, 35.56 + (index - 1) * 55.88, 187.96, _mosfet_nets(index))
        )
    for index, phase in enumerate("UVW", start=1):
        result.append(
            (
                f"RSH{index}",
                RESISTOR,
                63.5 + (index - 1) * 111.76,
                231.14,
                {
                    "1": f"{phase}SHUNT_H",
                    "2": "PGND",
                },
            )
        )

    # Gate networks.
    gate_outputs = ("DRV_GH_U", "DRV_GL_U", "DRV_GH_V", "DRV_GL_V", "DRV_GH_W", "DRV_GL_W")
    gate_nodes = ("GATE_UH", "GATE_UL", "GATE_VH", "GATE_VL", "GATE_WH", "GATE_WL")
    source_nodes = ("PHASE_U", "USHUNT_H", "PHASE_V", "VSHUNT_H", "PHASE_W", "WSHUNT_H")
    for index, (output, gate, source) in enumerate(
        zip(gate_outputs, gate_nodes, source_nodes, strict=True), start=1
    ):
        x = 35.56 + (index - 1) * 45.72
        result.append((f"RG{index}", RESISTOR, x, 269.24, {"1": output, "2": gate}))
        result.append((f"RGS{index}", RESISTOR, x, 287.02, {"1": gate, "2": source}))

    support = (
        ("CCP1", CAPACITOR, {"1": "DRV_CPH", "2": "DRV_CPL"}),
        ("CVCP1", CAPACITOR, {"1": "DRV_VCP", "2": "BAT_P"}),
        ("CVGLS1", CAPACITOR, {"1": "DRV_VGLS", "2": "PGND"}),
        ("CDVDD1", CAPACITOR, {"1": "DRV_DVDD", "2": "PGND"}),
        ("CVREF1", CAPACITOR, {"1": "3V3A", "2": "AGND"}),
        ("CVM1", CAPACITOR, {"1": "BAT_P", "2": "PGND"}),
        ("CVM2", CAPACITOR, {"1": "BAT_P", "2": "PGND"}),
        ("RFAULT1", RESISTOR, {"1": "3V3", "2": "DRV_NFAULT"}),
        ("RSDO1", RESISTOR, {"1": "3V3", "2": "DRV_SDO"}),
        ("REN1", RESISTOR, {"1": "DRV_EN", "2": "PGND"}),
        ("RBRAKE1", RESISTOR, {"1": "BRAKE_CMD", "2": "PGND"}),
        ("RAGND1", RESISTOR, {"1": "AGND", "2": "PGND"}),
        ("RNRST1", RESISTOR, {"1": "3V3", "2": "NRST"}),
        ("CNRST1", CAPACITOR, {"1": "NRST", "2": "PGND"}),
        ("CM1", CAPACITOR, {"1": "3V3", "2": "PGND"}),
        ("CM2", CAPACITOR, {"1": "3V3", "2": "PGND"}),
        ("CM3", CAPACITOR, {"1": "3V3", "2": "PGND"}),
        ("CM4", CAPACITOR, {"1": "3V3", "2": "PGND"}),
        ("FB1", INDUCTOR, {"1": "3V3", "2": "3V3A"}),
        ("CMA1", CAPACITOR, {"1": "3V3A", "2": "AGND"}),
        ("CMA2", CAPACITOR, {"1": "3V3A", "2": "AGND"}),
    )
    for offset, (ref, lib, pins) in enumerate(support):
        result.append(
            (ref, lib, 20.32 + (offset % 10) * 38.1, 325.12 + (offset // 10) * 25.4, pins)
        )

    buck = (
        ("RUV1", RESISTOR, {"1": "BAT_P", "2": "BUCK_EN"}),
        ("RUV2", RESISTOR, {"1": "BUCK_EN", "2": "PGND"}),
        ("RRON1", RESISTOR, {"1": "BUCK_RON", "2": "PGND"}),
        ("L1", INDUCTOR, {"1": "BUCK_SW", "2": "5V"}),
        ("CBST1", CAPACITOR, {"1": "BUCK_BST", "2": "BUCK_SW"}),
        ("RFB1", RESISTOR, {"1": "5V", "2": "BUCK_FB"}),
        ("RFB2", RESISTOR, {"1": "BUCK_FB", "2": "PGND"}),
        ("RRA1", RESISTOR, {"1": "BUCK_SW", "2": "BUCK_RIPPLE"}),
        ("CRA1", CAPACITOR, {"1": "BUCK_RIPPLE", "2": "5V"}),
        ("CRB1", CAPACITOR, {"1": "BUCK_RIPPLE", "2": "BUCK_FB"}),
        ("CIN1", CAPACITOR, {"1": "BAT_P", "2": "PGND"}),
        ("CIN2", CAPACITOR, {"1": "BAT_P", "2": "PGND"}),
        ("COUT1", CAPACITOR, {"1": "5V", "2": "PGND"}),
        ("COUT2", CAPACITOR, {"1": "5V", "2": "PGND"}),
        ("CLDOIN1", CAPACITOR, {"1": "5V", "2": "PGND"}),
        ("CLDOOUT1", CAPACITOR, {"1": "3V3", "2": "PGND"}),
    )
    for offset, (ref, lib, pins) in enumerate(buck):
        result.append((ref, lib, 20.32 + (offset % 8) * 48.26, 414.02 + (offset // 8) * 25.4, pins))

    # Scaled phase/bus sensing and thermistors.
    for offset, (phase, raw, sense) in enumerate(
        (
            ("BAT", "BAT_P", "VBUS_SENSE"),
            ("U", "PHASE_U", "PHASE_U_SENSE"),
            ("V", "PHASE_V", "PHASE_V_SENSE"),
            ("W", "PHASE_W", "PHASE_W_SENSE"),
        )
    ):
        prefix = "RBAT" if phase == "BAT" else f"R{phase}"
        mid = "VBUS_DIV_MID" if phase == "BAT" else f"PHASE_{phase}_DIV_MID"
        h1 = f"{prefix}H1" if phase == "BAT" else f"{prefix}H1"
        h2 = f"{prefix}H2" if phase == "BAT" else f"{prefix}H2"
        low = "RBATL1" if phase == "BAT" else f"R{phase}L1"
        cap = "CBATS1" if phase == "BAT" else f"CSENSE{offset}"
        x = 20.32 + offset * 101.6
        result.extend(
            (
                (h1, RESISTOR, x, 482.6, {"1": raw, "2": mid}),
                (h2, RESISTOR, x + 25.4, 482.6, {"1": mid, "2": sense}),
                (low, RESISTOR, x + 50.8, 482.6, {"1": sense, "2": "AGND"}),
                (cap, CAPACITOR, x + 76.2, 482.6, {"1": sense, "2": "AGND"}),
            )
        )
    for offset, phase in enumerate("UVW", start=1):
        x = 20.32 + offset * 76.2
        result.extend(
            (
                (f"RNTC{offset}", RESISTOR, x, 523.24, {"1": "3V3A", "2": f"NTC_{phase}"}),
                (f"NTC{offset}", THERMISTOR, x + 25.4, 523.24, {"1": f"NTC_{phase}", "2": "AGND"}),
                (f"CNTC{offset}", CAPACITOR, x + 50.8, 523.24, {"1": f"NTC_{phase}", "2": "AGND"}),
            )
        )

    result.extend(
        (
            (
                "J6",
                CONNECTOR_10,
                294.64,
                523.24,
                {
                    "1": "3V3",
                    "2": "SWDIO",
                    "3": "PGND",
                    "4": "SWCLK",
                    "5": "PGND",
                    "6": "AUX1",
                    "7": "NRST",
                    "8": "AUX2",
                    "9": "PGND",
                    "10": "PGND",
                },
            ),
            (
                "J7",
                CONNECTOR_6,
                347.98,
                523.24,
                {
                    "1": "5V",
                    "2": "PGND",
                    "3": "HALL_U",
                    "4": "HALL_V",
                    "5": "HALL_W",
                    "6": "BRAKE_CMD",
                },
            ),
            (
                "J8",
                CONNECTOR_8,
                388.62,
                523.24,
                {
                    "1": "3V3",
                    "2": "PGND",
                    "3": "UART_TX",
                    "4": "UART_RX",
                    "5": "I2C_SCL",
                    "6": "I2C_SDA",
                    "7": "AUX3",
                    "8": "BUCK_PGOOD",
                },
            ),
            ("RLED1", RESISTOR, 426.72, 523.24, {"1": "3V3", "2": "STATUS_LED"}),
            ("D2", LED, 452.12, 523.24, {"1": "PGND", "2": "STATUS_LED"}),
        )
    )
    for index, net in enumerate(("BAT_P", "PGND", "5V", "3V3A", "AGND"), start=1):
        result.append((f"PF{index}", PWR_FLAG, 449.58, 469.9 + (index - 1) * 12.7, {"1": net}))
    return tuple(result)


INSTANCES = _instances()

_CUSTOM_SYMBOLS = (
    (DRV8353, "TI DRV8353SRTAT 40-pin three-phase smart gate driver"),
    (TOLT_MOSFET, "Infineon IPTC011N08NM5 PG-HDSOP-16 top-side-cooled MOSFET"),
    (SMPD_TVS, "Vishay 7KPD unidirectional TVS in three-terminal SMPD package"),
)


def _custom_pin_positions(lib: str) -> dict[str, tuple[float, float, float]]:
    if lib == DRV8353:
        positions = {str(pin): (-15.24, 24.13 - (pin - 1) * 2.54, 180.0) for pin in range(1, 21)}
        positions.update(
            {str(pin): (15.24, -24.13 + (pin - 21) * 2.54, 0.0) for pin in range(21, 41)}
        )
        positions["41"] = (0.0, -27.94, 270.0)
        return positions
    if lib == TOLT_MOSFET:
        positions = {str(pin): (-10.16, 8.89 - (pin - 1) * 2.54, 180.0) for pin in range(1, 8)}
        positions["8"] = (-10.16, -11.43, 180.0)
        positions.update({str(pin): (10.16, -8.89 + (pin - 9) * 2.54, 0.0) for pin in range(9, 17)})
        return positions
    if lib == SMPD_TVS:
        return {
            "1": (-7.62, 2.54, 180.0),
            "2": (-7.62, -2.54, 180.0),
            "K": (7.62, 0.0, 0.0),
        }
    raise KeyError(lib)


def _custom_symbol_library_entry(lib: str, description: str) -> str:
    bare = lib.split(":")[-1]
    names: dict[int | str, str]
    if lib == DRV8353:
        names = {
            1: "CPL",
            2: "CPH",
            3: "VM",
            4: "VDRAIN",
            5: "VCP",
            6: "GHA",
            7: "SHA",
            8: "GLA",
            9: "SPA",
            10: "SNA",
            11: "SNB",
            12: "SPB",
            13: "GLB",
            14: "SHB",
            15: "GHB",
            16: "GHC",
            17: "SHC",
            18: "GLC",
            19: "SPC",
            20: "SNC",
            21: "SOC",
            22: "SOB",
            23: "SOA",
            24: "VREF",
            25: "AGND",
            26: "nFAULT",
            27: "SDO",
            28: "SDI",
            29: "SCLK",
            30: "nSCS",
            31: "ENABLE",
            32: "INHA",
            33: "INLA",
            34: "INHB",
            35: "INLB",
            36: "INHC",
            37: "INLC",
            38: "DVDD",
            39: "GND",
            40: "VGLS",
            41: "EP",
        }
        body = (-12.7, 26.67, 12.7, -26.67)
    elif lib == TOLT_MOSFET:
        names = {**{pin: "S" for pin in range(1, 8)}, 8: "G", **{pin: "D" for pin in range(9, 17)}}
        body = (-7.62, 10.16, 7.62, -10.16)
    else:
        names = {1: "A1", 2: "A2", "K": "K"}
        body = (-5.08, 5.08, 5.08, -5.08)
    pins = []
    for number, (x, y, outward) in _custom_pin_positions(lib).items():
        key = int(number) if number.isdigit() else number
        pins.append(_generic_pin(number, names[key], x, y, int(outward + 180) % 360, "2.54"))
    rendered = "\n".join(pins)
    x1, y1, x2, y2 = body
    return f"""  (symbol "{lib}"
    (pin_numbers (hide no))
    (pin_names (offset 0.762))
    (exclude_from_sim yes)
    (in_bom yes)
    (on_board yes)
    {_library_property("Reference", "U" if lib == DRV8353 else ("Q" if lib == TOLT_MOSFET else "D"), 0, y1 + 2.54)}
    {_library_property("Value", bare, 0, y2 - 2.54)}
    {_library_property("Footprint", "", 0, 0, hidden=True)}
    {_library_property("Datasheet", "~", 0, 0, hidden=True)}
    {_library_property("Description", description, 0, 0, hidden=True)}
    (symbol "{bare}_0_1"
      (rectangle (start {x1} {y1}) (end {x2} {y2})
        (stroke (width 0.254) (type default)) (fill (type background)))
    )
    (symbol "{bare}_1_1"
{rendered}
    )
  )"""


def _render_symbol_library() -> str:
    entries = "\n\n".join(_custom_symbol_library_entry(lib, desc) for lib, desc in _CUSTOM_SYMBOLS)
    return f"""(kicad_symbol_lib
  (version {KICAD_SYMBOL_LIBRARY_VERSION})
  (generator "PCBSmith")
  (generator_version "0.1")
{entries}
)
"""


def export_bldc_esc_to_kicad(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    project_name: str,
) -> dict[str, str]:
    if circuit.topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported circuit for BLDC ESC KiCad export")
    project_name = _validate_project_name(project_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    project_file = output_dir / f"{project_name}.kicad_pro"
    schematic_file = output_dir / f"{project_name}.kicad_sch"
    symbol_library = output_dir / "PCBSmith.kicad_sym"
    symbol_table = output_dir / "sym-lib-table"
    footprint_table = output_dir / "fp-lib-table"
    project_file.write_text(_render_project(min_through_hole_mm=0.2), encoding="utf-8")
    symbol_table.write_text(_render_symbol_table(), encoding="utf-8")
    symbol_library.write_text(_render_symbol_library(), encoding="utf-8")
    _write_footprint_libraries(output_dir)
    footprint_table.write_text(_render_footprint_table(), encoding="utf-8")
    schematic_file.write_text(_render_schematic(circuit, project_name), encoding="utf-8")
    return {
        "project_file": str(project_file),
        "schematic_file": str(schematic_file),
        "symbol_library": str(symbol_library),
        "footprint_table": str(footprint_table),
    }


def _render_footprint_table() -> str:
    return """(fp_lib_table
  (version 7)
  (lib (name "PCBSmith_Power")(type "KiCad")(uri "${KIPRJMOD}/PCBSmith_Power.pretty")(options "")(descr "Exact BLDC ESC R001 power packages"))
  (lib (name "REDCUBE_THT_Wurth")(type "KiCad")(uri "${KIPRJMOD}/REDCUBE_THT_Wurth.pretty")(options "")(descr "Wurth 7461057 official footprint rev26b"))
)
"""


def _write_footprint_libraries(output_dir: Path) -> None:
    power = output_dir / "PCBSmith_Power.pretty"
    redcube = output_dir / "REDCUBE_THT_Wurth.pretty"
    models = output_dir / "models"
    power.mkdir(parents=True, exist_ok=True)
    redcube.mkdir(parents=True, exist_ok=True)
    models.mkdir(parents=True, exist_ok=True)
    generate_bldc_esc_proxy_models(output_dir)
    for name, text in _power_footprints().items():
        (power / f"{name}.kicad_mod").write_text(text, encoding="utf-8")

    repo = Path(__file__).resolve().parents[3]
    terminal_source = (
        repo
        / ".pcbsmith-private"
        / "kicad-assets"
        / "footprints"
        / "REDCUBE_THT_Wurth__MP_Wurth_WP-BUTR_7461057.kicad_mod"
    )
    model_source = (
        repo
        / ".pcbsmith-private"
        / "kicad-assets"
        / "models"
        / "wurth-7461057-model-rev1-74770b311869.step"
    )
    terminal_target = redcube / "MP_Wurth_WP-BUTR_7461057.kicad_mod"
    if not terminal_source.exists() or not model_source.exists():
        raise FileNotFoundError("Verified Wurth 7461057 footprint/model assets are not installed")
    terminal_text = terminal_source.read_text(encoding="utf-8").replace(
        "${WE_3DMODEL_DIR}/REDCUBE_THT_Wurth.3dshapes/MP_Wurth_WP-BUTR_7461057.step",
        "${KIPRJMOD}/models/wurth-7461057-model-rev1-74770b311869.step",
    )
    terminal_target.write_text(terminal_text, encoding="utf-8")
    shutil.copyfile(model_source, models / model_source.name)


def _footprint_header(name: str, description: str) -> str:
    return f"""(footprint "{name}"
  (version 20241229)
  (generator "PCBSmith")
  (layer "F.Cu")
  (descr "{description}")
  (attr smd)
"""


def _pad(
    number: str,
    x: float,
    y: float,
    sx: float,
    sy: float,
    *,
    rotation: int = 0,
    layers: str = '"F.Cu" "F.Paste" "F.Mask"',
) -> str:
    rotate = f" {rotation}" if rotation else ""
    return f'  (pad "{number}" smd rect (at {x:.4f} {y:.4f}{rotate}) (size {sx:.4f} {sy:.4f}) (layers {layers}))'


def _reference_text(x: float, y: float) -> str:
    """Visible assembly reference for generated high-risk power footprints."""
    return (
        f'  (fp_text reference "REF**" (at {x:.3f} {y:.3f}) '
        '(layer "F.SilkS") '
        '(effects (font (size 1 1) (thickness 0.15))))'
    )


def _proxy_model(filename: str) -> str:
    return f"""  (model "${{KIPRJMOD}}/models/{filename}"
    (offset (xyz 0 0 0))
    (scale (xyz 1 1 1))
    (rotate (xyz 0 0 0))
  )"""


def _power_footprints() -> dict[str, str]:
    # TI RTA0040B: 0.5 mm pitch, 0.22 x 0.60 mm lands, 4.15 mm EP.
    rta = [
        _footprint_header(
            "Texas_RTA0040B_WQFN-40-1EP",
            "TI RTA0040B WQFN-40, datasheet 4219112/A, no optional thermal vias",
        ),
        _reference_text(0.0, -4.2),
    ]
    axis = [-2.25 + 0.5 * i for i in range(10)]
    for i, pos in enumerate(axis, start=1):
        rta.append(_pad(str(i), -2.9, -pos, 0.6, 0.22))
    for i, pos in enumerate(axis, start=11):
        rta.append(_pad(str(i), pos, 2.9, 0.22, 0.6))
    for i, pos in enumerate(axis, start=21):
        rta.append(_pad(str(i), 2.9, pos, 0.6, 0.22))
    for i, pos in enumerate(reversed(axis), start=31):
        rta.append(_pad(str(i), pos, -2.9, 0.22, 0.6))
    rta.append(_pad("41", 0, 0, 4.15, 4.15, layers='"F.Cu" "F.Mask"'))
    for px in (-1.35, 0.0, 1.35):
        for py in (-1.35, 0.0, 1.35):
            rta.append(_pad("", px, py, 1.05, 1.05, layers='"F.Paste"'))
    rta.extend(
        (
            '  (fp_rect (start -3.15 -3.15) (end 3.15 3.15) (stroke (width 0.15) (type default)) (fill none) (layer "F.Fab"))',
            '  (fp_circle (center -3.55 -3.05) (end -3.35 -3.05) (stroke (width 0.2) (type default)) (fill none) (layer "F.SilkS"))',
            '  (fp_rect (start -3.35 -3.35) (end 3.35 3.35) (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))',
            _proxy_model("drv8353-rta-envelope.wrl"),
            ")\n",
        )
    )

    # Infineon Figure 2: 1.2 mm lead pitch, 0.8 x 3.375 mm lands,
    # 10.2 x 7 mm drain copper.  Pad 9 is repeated for the exposed drain.
    tolt = [
        _footprint_header(
            "Infineon_PG-HDSOP-16_TOLT",
            "Infineon PG-HDSOP-16-U01/TOLT, IPTC011N08NM5 datasheet Rev 2.0 Figure 2",
        ),
        _reference_text(6.3, 0.0),
    ]
    xs = [-4.2 + 1.2 * i for i in range(8)]
    for i, x in enumerate(xs, start=1):
        tolt.append(_pad(str(i), x, 7.187, 0.8, 3.375))
    for i, x in enumerate(reversed(xs), start=9):
        tolt.append(_pad(str(i), x, -7.187, 0.8, 3.375))
    tolt.append(_pad("9", 0, 0, 10.2, 7.0))
    tolt.extend(
        (
            '  (fp_rect (start -5.15 -7.6) (end 5.15 7.6) (stroke (width 0.2) (type default)) (fill none) (layer "F.Fab"))',
            '  (fp_circle (center -5.6 6.8) (end -5.35 6.8) (stroke (width 0.2) (type default)) (fill none) (layer "F.SilkS"))',
            '  (fp_rect (start -5.7 -9.1) (end 5.7 9.1) (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))',
            _proxy_model("iptc011n08-tolt-envelope.wrl"),
            ")\n",
        )
    )

    # Vishay WSLP2726 recommended land: 2.69 x 5.71 mm pads in a
    # 7.62 mm overall span (4.93 mm center spacing).
    shunt = [
        _footprint_header(
            "Vishay_WSLP2726",
            "Vishay WSLP2726 two-terminal shunt, datasheet Document 30179",
        ),
        _reference_text(0.0, -4.3),
    ]
    shunt.extend(
        (
            _pad("1", -2.465, 0, 2.69, 5.71),
            _pad("2", 2.465, 0, 2.69, 5.71),
            '  (fp_line (start -3.55 -3.4) (end 3.55 -3.4) (stroke (width 0.2) (type default)) (layer "F.SilkS"))',
            '  (fp_line (start -3.55 3.4) (end 3.55 3.4) (stroke (width 0.2) (type default)) (layer "F.SilkS"))',
            '  (fp_rect (start -4.0 -3.65) (end 4.0 3.65) (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))',
            _proxy_model("wslp2726-envelope.wrl"),
            ")\n",
        )
    )

    # KEMET/Yageo A781 anti-vibration 10 mm landing pad: A=4.5,
    # B=4.4, C=4.6 mm.  Pad centers are +/- (A+B)/2.
    bulk = [
        _footprint_header(
            "KEMET_A781_10x12.4mm_AntiVibration",
            "KEMET A781 10 mm anti-vibration case, datasheet A4112_A781 pp.3,12",
        ),
        _reference_text(0.0, -6.3),
    ]
    bulk.extend(
        (
            _pad("1", -4.45, 0, 4.4, 4.6),
            _pad("2", 4.45, 0, 4.4, 4.6),
            '  (fp_circle (center 0 0) (end 5.2 0) (stroke (width 0.2) (type default)) (fill none) (layer "F.Fab"))',
            '  (fp_line (start -5.6 -4.8) (end -4.6 -4.8) (stroke (width 0.4) (type default)) (layer "F.SilkS"))',
            '  (fp_rect (start -5.8 -5.7) (end 5.8 5.7) (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))',
            _proxy_model("a781-10x12p4-envelope.wrl"),
            ")\n",
        )
    )

    # Vishay SMPD mounting pad: 10.66 x 8.38 mm cathode land and two
    # 2.67 x 3.05 mm anode lands at 5.08 mm pitch.
    tvs = [
        _footprint_header(
            "Vishay_SMPD_TO-263AC",
            "Vishay SMPD (TO-263AC), 7KPD datasheet Document 98774 p.5",
        ),
        _reference_text(0.0, -9.3),
    ]
    tvs.extend(
        (
            _pad("K", 0, -4.19, 10.66, 8.38),
            _pad("1", -2.54, 5.425, 2.67, 3.05),
            _pad("2", 2.54, 5.425, 2.67, 3.05),
            '  (fp_rect (start -5.2 -6.5) (end 5.2 6.5) (stroke (width 0.2) (type default)) (fill none) (layer "F.Fab"))',
            '  (fp_rect (start -5.6 -8.6) (end 5.6 7.2) (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))',
            _proxy_model("7kpd-smpd-envelope.wrl"),
            ")\n",
        )
    )

    return {
        "Texas_RTA0040B_WQFN-40-1EP": "\n".join(rta),
        "Infineon_PG-HDSOP-16_TOLT": "\n".join(tolt),
        "Vishay_WSLP2726": "\n".join(shunt),
        "KEMET_A781_10x12.4mm_AntiVibration": "\n".join(bulk),
        "Vishay_SMPD_TO-263AC": "\n".join(tvs),
    }


def _render_schematic(circuit: CircuitObject, project_name: str) -> str:
    fields = {
        component.reference: (component.value, component.footprint or "")
        for component in circuit.components
    }
    symbols: list[str] = []
    wires: list[str] = []
    labels: list[str] = []
    custom_libs = {lib for lib, _desc in _CUSTOM_SYMBOLS}
    for reference, lib_id, x, y, pin_nets in INSTANCES:
        value, footprint = fields[reference]
        if lib_id in custom_libs:
            positions = _custom_pin_positions(lib_id)
            pin_count = len(positions)
        else:
            imported = load_symbol(lib_id)
            pin_count = len(imported.pins)
        symbols.append(
            _symbol(
                lib_id,
                reference,
                value,
                x,
                y,
                project_name,
                exclude_from_sim=True,
                footprint=footprint,
                pin_count=pin_count,
                pin_numbers=tuple(pin_nets) if lib_id in custom_libs else None,
                in_bom=not reference.startswith("PF"),
            )
        )
        for pin_number, net in pin_nets.items():
            if lib_id in custom_libs:
                px, py, outward = positions[pin_number]
                tip = (x + px, y - py)
                radians = math.radians(outward)
                endpoint = (
                    round(tip[0] + 2.54 * math.cos(radians), 4),
                    round(tip[1] - 2.54 * math.sin(radians), 4),
                )
            else:
                tip, endpoint = pin_stub(imported, pin_number, (x, y))
            wires.append(_wire(tip, endpoint))
            labels.append(_label(net, *endpoint))
        if reference == "U1":
            for pin_number in MCU_NO_CONNECTS:
                tip, _endpoint = pin_stub(imported, pin_number, (x, y))
                symbols.append(_no_connect(*tip))
        if reference == "U4":
            for pin_number in ("2", "7"):
                tip, _endpoint = pin_stub(imported, pin_number, (x, y))
                symbols.append(_no_connect(*tip))

    official_libs = tuple(
        dict.fromkeys(
            lib_id for _ref, lib_id, _x, _y, _nets in INSTANCES if lib_id not in custom_libs
        )
    )
    official = "\n".join(
        render_symbol_for_schematic(load_symbol(lib_id)) for lib_id in official_libs
    )
    custom = "\n".join(_custom_symbol_library_entry(lib, desc) for lib, desc in _CUSTOM_SYMBOLS)
    items = "\n".join((*symbols, *wires, *labels))
    return f"""(kicad_sch
  (version {KICAD_SCHEMATIC_VERSION})
  (generator "PCBSmith")
  (generator_version "0.1")
  (uuid {stable_kicad_uuid("schematic-root", "machine", project_name, circuit.topology.topology_id)})
  (paper "A1")

  (lib_symbols
{official}
{custom}
  )
{items}
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""
