"""Thermometer-shaped SHT31 + ESP32-C3 environmental display.

The user's brief: a board shaped like a classic glass thermometer — a
16-LED "mercury" column in the stem driven progressively from the
measured temperature, the sensor in the bulb with free airflow, two
OLED readouts above the bulb, USB-C power/programming at the bottom,
laboratory-thermometer silkscreen graduations that line up with the
LEDs.

Choices from the brief's option lists (each carried as evidence):
ESP32-C3-WROOM-02 module (native USB-Serial/JTAG = USB programming
with no bridge chip), SHT31-DIS, two SN74HC595 stages for the LED
column (3 GPIO), AP2112K-3.3 rail, two 0.49" SSD1306 I2C OLED modules
on 4-pin headers — one per I2C bus, because common modules are fixed
at address 0x3C. Omitted-by-decision: LiPo battery + charger (the
brief marks them optional) and a USB ESD array (finding).
"""

from __future__ import annotations

from pathlib import Path

from pcbsmith.calculators.electronics import solve_thermometer_display
from pcbsmith.circuit.models import (
    CircuitIntent,
    CircuitObject,
    ComponentRole,
    EvidenceRef,
    MathReport,
    TopologySelection,
)
from pcbsmith.core.board import Board
from pcbsmith.core.project import Project
from pcbsmith.core.schematic import Schematic
from pcbsmith.generation.blocks import register_module
from pcbsmith.reporting.review_pack import TestStep
from pcbsmith.services.project_io import save_board, save_project, save_schematic

SUPPORTED_TOPOLOGY_ID = "thermometer_env_display"

LED_COUNT = 16

SMD_R = "Resistor_SMD:R_0603_1608Metric"
SMD_C_0603 = "Capacitor_SMD:C_0603_1608Metric"
SMD_C_0805 = "Capacitor_SMD:C_0805_2012Metric"
SMD_LED = "LED_SMD:LED_0805_2012Metric"
HEADER4 = "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"
TESTPOINT = "TestPoint:TestPoint_THTPad_D2.0mm_Drill1.0mm"

OLED_MODULE_FINDING = (
    "OLED READOUTS ARE MODULES: the two 0.49-inch SSD1306 displays are "
    "carried as 4-pin header footprints (GND/VCC/SCL/SDA) because "
    "common modules are complete assemblies with a fixed I2C address "
    "(0x3C) - hence one module per I2C bus. Verify the ordered "
    "module's pin order against the header silk before soldering."
)

ANTENNA_FINDING = (
    "ANTENNA KEEPOUT: the ESP32-C3-WROOM-02 datasheet (p10) requires a "
    "copper keepout under and beyond the module antenna even though "
    "this design uses no radio by default; the layout places the "
    "antenna end over the board edge. Firmware should keep WiFi off - "
    "the LDO thermal margin is budgeted for display load (see the "
    "calculator's WiFi-burst warning)."
)

OMITTED_FINDING = (
    "OMITTED BY DECISION (optional in the brief): LiPo battery + "
    "charging IC (board is USB-powered), and a dedicated USB ESD "
    "array (the short chassis-to-jack distance and 27ohm-free "
    "USB-Serial/JTAG lines are acceptable for an indoor display; add "
    "USBLC6-2SC6 if the deployment is harsher)."
)


def _assumption(title: str, locator: str) -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef(kind="engineering_assumption", title=title, locator=locator),
    )


def _fact(title: str, locator: str) -> tuple[EvidenceRef, ...]:
    return (EvidenceRef(kind="datasheet_fact", title=title, locator=locator),)


def _resistor(
    reference: str, role: str, value: str,
    evidence: tuple[EvidenceRef, ...],
) -> ComponentRole:
    return ComponentRole(
        reference=reference, role=role, symbol_id="stdlib:R", value=value,
        support_status="needs_datasheet_review", footprint=SMD_R,
        evidence=evidence,
    )


def _capacitor(
    reference: str, role: str, value: str, footprint: str,
    evidence: tuple[EvidenceRef, ...],
) -> ComponentRole:
    return ComponentRole(
        reference=reference, role=role, symbol_id="stdlib:C", value=value,
        support_status="needs_datasheet_review", footprint=footprint,
        evidence=evidence,
    )


@register_module(
    "usb-c-power-entry",
    "USB-C 2.0 sink: 16-pin receptacle, 5.1k CC pull-downs (USB Type-C "
    "spec sink advertisement), 500mA polyfuse on VBUS. D+/D- go to the "
    "MCU's native USB.",
    provides_roles=(
        "usb_c_receptacle", "vbus_polyfuse",
        "cc1_pulldown", "cc2_pulldown",
    ),
    proven_by="design-thermometer-authority",
)
def usb_c_power_entry() -> tuple[ComponentRole, ...]:
    return (
        ComponentRole(
            reference="J1", role="usb_c_receptacle",
            symbol_id="stdlib:USB_C", value="USB-C 2.0 16P",
            support_status="needs_datasheet_review",
            footprint=(
                "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P"
                "_TopMnt_Horizontal"
            ),
            evidence=_assumption(
                "GCT USB4105 16-pin USB 2.0 receptacle",
                "Official KiCad footprint; verify the ordered part "
                "matches USB4105-xx-A.",
            ),
        ),
        ComponentRole(
            reference="F1", role="vbus_polyfuse",
            symbol_id="stdlib:FUSE", value="500mA polyfuse",
            support_status="needs_datasheet_review",
            footprint="Fuse:Fuse_1206_3216Metric",
            evidence=_assumption(
                "Resettable fuse on VBUS",
                "Hold 500mA >= worst-case rail current from the "
                "calculator; protects the host port.",
            ),
        ),
        _resistor(
            "RCC1", "cc1_pulldown", "5.1k",
            _assumption(
                "CC1 pull-down advertises a USB default sink",
                "USB Type-C spec Rd = 5.1k.",
            ),
        ),
        _resistor(
            "RCC2", "cc2_pulldown", "5.1k",
            _assumption(
                "CC2 pull-down advertises a USB default sink",
                "USB Type-C spec Rd = 5.1k.",
            ),
        ),
    )


@register_module(
    "ldo-3v3-rail",
    "AP2112K-3.3 rail: 1uF X7R in/out per datasheet, EN tied to VIN, "
    "power LED with high-value resistor as the rail indicator.",
    provides_roles=(
        "ldo_regulator", "ldo_input_capacitor", "ldo_output_capacitor",
        "power_led", "power_led_resistor",
    ),
    proven_by="design-thermometer-authority",
)
def ldo_3v3_rail() -> tuple[ComponentRole, ...]:
    ap2112 = _fact(
        "AP2112K-3.3: 600mA min, SOT-25 pinout VIN/GND/EN/NC/VOUT, "
        "1uF X7R input and output capacitors",
        "ai_assets/datasheets/ap2112.pdf p1 (rating, pinout), p2 "
        "(pin table, application circuit note 4), p3 (VIN 2.5-6V)",
    )
    return (
        ComponentRole(
            reference="U5", role="ldo_regulator",
            symbol_id="stdlib:AP2112K", value="AP2112K-3.3",
            support_status="supported",
            footprint="Package_TO_SOT_SMD:SOT-23-5",
            evidence=ap2112,
        ),
        _capacitor("C5", "ldo_input_capacitor", "1uF X7R", SMD_C_0805, ap2112),
        _capacitor("C6", "ldo_output_capacitor", "1uF X7R", SMD_C_0805, ap2112),
        ComponentRole(
            reference="D17", role="power_led",
            symbol_id="stdlib:LED", value="RED-0805",
            support_status="needs_datasheet_review",
            footprint=SMD_LED,
            evidence=_fact(
                "Kingbright APT2012SRCPRV 0805 red",
                "ai_assets/datasheets/kingbright-apt2012srcprv.pdf p2",
            ),
        ),
        _resistor(
            "R17", "power_led_resistor", "1k",
            _assumption(
                "Dim always-on rail indicator",
                "(3.3-1.85)/1k ~ 1.5mA: visible, negligible load.",
            ),
        ),
    )


def compose_thermometer(
    intent: CircuitIntent,
    topology: TopologySelection,
) -> CircuitObject:
    if intent.intent_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported intent for thermometer composition")
    if topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported topology for thermometer composition")

    design = solve_thermometer_display(
        vbus_v=float(intent.assumptions["vbus_v"]),
        vcc_v=float(intent.assumptions["vcc_v"]),
        led_count=int(intent.assumptions["led_count"]),
        scale_min_c=float(intent.assumptions["scale_min_c"]),
        scale_max_c=float(intent.assumptions["scale_max_c"]),
    )
    if design["status"] == "error":
        raise ValueError("; ".join(design["errors"]))
    out = design["outputs"]

    esp = _fact(
        "ESP32-C3-WROOM-02 pinout, 3.0-3.6V supply, USB-Serial/JTAG on "
        "GPIO18/19, strapping pins GPIO2/8/9",
        "ai_assets/datasheets/esp32-c3-wroom-02.pdf p3, p10-11, "
        "p12-13, p19",
    )
    sht = _fact(
        "SHT31-DIS pin assignment and I2C address",
        "ai_assets/datasheets/sht3x-dis.pdf p8 (Table 7), p9 (0x44), "
        "p6 (supply)",
    )
    hc595 = _fact(
        "SN74HC595 pinout and 2-6V range",
        "ai_assets/datasheets/sn74hc595.pdf p3 (pin table), p1",
    )
    led = _fact(
        "APT2012SRCPRV 0805 red, Vf 1.85V typ at 20mA",
        "ai_assets/datasheets/kingbright-apt2012srcprv.pdf p2, p3 "
        "(V-I curve)",
    )

    mercury = []
    for index in range(1, LED_COUNT + 1):
        mercury.append(
            _resistor(
                f"R{index}", "led_series_resistor", "270R",
                led,
            )
        )
        mercury.append(
            ComponentRole(
                reference=f"D{index}", role="mercury_led",
                symbol_id="stdlib:LED", value="RED-0805",
                support_status="needs_datasheet_review",
                footprint=SMD_LED,
                evidence=led,
            )
        )

    components = (
        *usb_c_power_entry(),
        *ldo_3v3_rail(),
        ComponentRole(
            reference="U1", role="mcu_module",
            symbol_id="stdlib:ESP32C3WROOM02", value="ESP32-C3-WROOM-02",
            support_status="supported",
            footprint="RF_Module:ESP32-C3-WROOM-02",
            evidence=esp,
        ),
        _capacitor("C1", "module_bulk_capacitor", "10uF", SMD_C_0805, esp),
        _capacitor("C2", "module_bypass_capacitor", "100n", SMD_C_0603, esp),
        _resistor("REN1", "enable_pullup", "10k", esp),
        _capacitor("CEN1", "enable_capacitor", "100n", SMD_C_0603, esp),
        _resistor("RS1", "strap_pullup", "10k", esp),
        _resistor("RS2", "strap_pullup", "10k", esp),
        ComponentRole(
            reference="U2", role="led_shift_register",
            symbol_id="stdlib:74HC595", value="74HC595",
            support_status="supported",
            footprint="Package_SO:TSSOP-16_4.4x5mm_P0.65mm",
            evidence=hc595,
        ),
        ComponentRole(
            reference="U3", role="led_shift_register",
            symbol_id="stdlib:74HC595", value="74HC595",
            support_status="supported",
            footprint="Package_SO:TSSOP-16_4.4x5mm_P0.65mm",
            evidence=hc595,
        ),
        _capacitor("C3", "register_bypass_capacitor", "100n", SMD_C_0603, hc595),
        _capacitor("C4", "register_bypass_capacitor", "100n", SMD_C_0603, hc595),
        _resistor(
            "ROE1", "oe_pullup", "10k",
            _fact(
                "OE pulled high blanks the column until firmware "
                "drives it",
                "ai_assets/datasheets/sn74hc595.pdf p3 (OE, active low)",
            ),
        ),
        ComponentRole(
            reference="U4", role="humidity_temperature_sensor",
            symbol_id="stdlib:SHT31", value="SHT31-DIS",
            support_status="supported",
            footprint=(
                "Sensor_Humidity:Sensirion_DFN-8-1EP_2.5x2.5mm_P0.5mm"
                "_EP1.1x1.7mm"
            ),
            evidence=sht,
        ),
        _capacitor("C7", "sensor_bypass_capacitor", "100n", SMD_C_0603, sht),
        _resistor("RI1", "i2c_pullup", "4.7k", sht),
        _resistor("RI2", "i2c_pullup", "4.7k", sht),
        _resistor("RI3", "i2c_pullup", "4.7k", sht),
        _resistor("RI4", "i2c_pullup", "4.7k", sht),
        ComponentRole(
            reference="J2", role="oled_header",
            symbol_id="stdlib:CONN_01X04", value="OLED 0.49in TEMP",
            support_status="needs_datasheet_review",
            footprint=HEADER4,
            evidence=_assumption(
                "0.49-inch SSD1306 I2C module on a 4-pin header",
                "Module pin order GND/VCC/SCL/SDA assumed; verify "
                "against the ordered module (finding).",
            ),
        ),
        ComponentRole(
            reference="J3", role="oled_header",
            symbol_id="stdlib:CONN_01X04", value="OLED 0.49in HUM",
            support_status="needs_datasheet_review",
            footprint=HEADER4,
            evidence=_assumption(
                "0.49-inch SSD1306 I2C module on a 4-pin header",
                "Module pin order GND/VCC/SCL/SDA assumed; verify "
                "against the ordered module (finding).",
            ),
        ),
        *mercury,
        ComponentRole(
            reference="TP1", role="test_point",
            symbol_id="stdlib:TESTPOINT", value="TP 3V3",
            support_status="needs_datasheet_review",
            footprint=TESTPOINT,
            evidence=_assumption("Rail probe point", "Bring-up aid."),
        ),
        ComponentRole(
            reference="TP2", role="test_point",
            symbol_id="stdlib:TESTPOINT", value="TP GND",
            support_status="needs_datasheet_review",
            footprint=TESTPOINT,
            evidence=_assumption("Ground probe point", "Bring-up aid."),
        ),
    )

    thresholds = ", ".join(
        f"LED{index}>={value:g}C"
        for index, value in enumerate(out["led_on_thresholds_c"], start=1)
    )
    findings = (
        *(str(w) for w in design["warnings"]),
        OLED_MODULE_FINDING,
        ANTENNA_FINDING,
        OMITTED_FINDING,
        "FIRMWARE CONTRACT (from the calculator, the same numbers the "
        f"silk ticks use): {thresholds}.",
    )
    calculations = {
        key: float(value)
        for key, value in out.items()
        if isinstance(value, (int, float))
    }
    return CircuitObject(
        intent=intent,
        topology=topology,
        components=components,
        nets=(
            "VBUS", "VBUSF", "VCC", "GND", "CC1", "CC2", "DP", "DM",
            "EN", "IO2", "IO8", "SER", "SRCLK", "RCLK", "OE", "CAS",
            "SDA1", "SCL1", "SDA2", "SCL2", "PWLED",
            *(f"SEG{i}" for i in range(1, LED_COUNT + 1)),
            *(f"LK{i}" for i in range(1, LED_COUNT + 1)),
        ),
        math=MathReport(
            status="warning" if design["warnings"] else "ok",
            calculations=calculations,
            findings=findings,
        ),
    )


def write_thermometer_project(
    circuit: CircuitObject,
    project_dir: Path,
    *,
    project_name: str,
) -> None:
    if circuit.topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported circuit for project generation")
    project = Project(name=project_name)
    save_project(project_dir, project)
    save_schematic(project_dir, project.schematics[0], Schematic(id="main"))
    save_board(project_dir, project.boards[0], Board(id="main"))


def thermometer_test_steps(outputs: dict[str, object]) -> tuple[TestStep, ...]:
    """Bench plan derived from the calculator's design point."""
    led_ma = float(outputs["led_current_typ_ma"])  # type: ignore[arg-type]
    rail_ma = float(outputs["rail_current_worst_ma"])  # type: ignore[arg-type]
    return (
        TestStep(
            name="Rail bring-up",
            procedure=(
                "Connect USB-C; measure TP1 (3V3) against TP2 (GND) "
                "with the module unprogrammed."
            ),
            expected="3.3V +/- 2%; power LED lit dim",
            safety="USB power only.",
        ),
        TestStep(
            name="USB programming",
            procedure=(
                "esptool chip_id over the native USB-Serial/JTAG; no "
                "BOOT button is fitted - esptool resets into download "
                "mode through the same interface."
            ),
            expected="ESP32-C3 detected, flash id read",
            safety="USB power only.",
        ),
        TestStep(
            name="Sensor readout",
            procedure=(
                "Firmware reads SHT31 at 0x44 on I2C bus 1; log "
                "temperature and humidity."
            ),
            expected="Plausible ambient values; CRC valid",
            safety="USB power only.",
        ),
        TestStep(
            name="Mercury column",
            procedure=(
                "Walk the LED column 1..16 via the 74HC595 chain; "
                "measure one series resistor's voltage drop."
            ),
            expected=(
                f"Each LED ~{led_ma:.1f}mA (0.27k x drop); column "
                "aligns with the printed scale ticks"
            ),
            safety="USB power only.",
        ),
        TestStep(
            name="Displays",
            procedure=(
                "OLED on bus 1 shows temperature, bus 2 shows "
                "humidity; verify both at 0x3C."
            ),
            expected="Both readouts update once per second",
            safety="USB power only.",
        ),
        TestStep(
            name="Thermal check",
            procedure=(
                "All LEDs on, displays active, WiFi OFF; measure the "
                "AP2112 case temperature after 10 minutes."
            ),
            expected=(
                f"Rail current well under {rail_ma:.0f}mA worst-case; "
                "LDO warm, not hot (< 60C case)"
            ),
            safety="USB power only.",
        ),
    )
