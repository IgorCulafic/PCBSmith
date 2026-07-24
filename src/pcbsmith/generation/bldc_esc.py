"""Circuit authority for the 3S-6S, 60 A target BLDC ESC prototype.

This module is intentionally schematic-stage authority.  It fixes exact core
MPNs, pin/package identities, component roles, and every named net, while
retaining the architecture's staged 30 A bring-up limit.  The 60 A continuous
rating remains conditional on layout, thermal, ripple-current, and motor tests.
"""

from __future__ import annotations

from pcbsmith.circuit.models import (
    CircuitIntent,
    CircuitObject,
    ComponentRole,
    EvidenceRef,
    MathReport,
    TopologySelection,
)

SUPPORTED_TOPOLOGY_ID = "bldc_esc_3phase_60a_r001"

R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
C1210 = "Capacitor_SMD:C_1210_3225Metric"


def _source(
    title: str,
    locator: str,
    *,
    source_id: str,
    sha256: str,
    url: str,
) -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef(
            kind="manufacturer_document",
            title=title,
            locator=locator,
            source_id=source_id,
            official_url=url,
            local_sha256=sha256,
            source_status="pinned",
            locator_status="figure_verified",
            applicability_status="confirmed",
        ),
    )


def _engineering(title: str, locator: str) -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef(
            kind="engineering_assumption",
            title=title,
            locator=locator,
            source_status="unknown",
            locator_status="unverified",
            applicability_status="conditional",
        ),
    )


MOSFET = _source(
    "Infineon IPTC011N08NM5 final datasheet Rev. 2.0",
    "pp. 1, 10-11: pins 1-7 source, pin 8 gate, pins 9-16 and tab drain; "
    "PG-HDSOP-16 outline and manufacturer land pattern",
    source_id="part:Infineon:IPTC011N08NM5ATMA1:datasheet",
    sha256="e30473eeb2699eb28ad595b93dac5846efee85ad0364b56eeffd3a42da8a0222",
    url="https://www.infineon.com/dgdl/Infineon-IPTC011N08NM5-DataSheet-v02_00-EN.pdf",
)
DRIVER = _source(
    "Texas Instruments DRV8353 datasheet Rev. A",
    "pp. 6-7, 98-99: DRV8353S RTA 40-pin map, charge-pump support parts, "
    "and RTA0040B WQFN land pattern",
    source_id="part:Texas-Instruments:DRV8353SRTAT:datasheet",
    sha256="f440d3fae4c79d04078679ee6f3122d9aae2e169833a577fd993780204c3849e",
    url="https://www.ti.com/lit/ds/symlink/drv8353.pdf",
)
MCU = _source(
    "STMicroelectronics STM32G431x6/x8/xB datasheet Rev. 6",
    "pp. 45-61, 170-172: LQFP48 pin functions and recommended footprint",
    source_id="part:STMicroelectronics:STM32G431CBT6:datasheet",
    sha256="c2e903e3de4b05c0b5d77e5bfda037ce65e8652c41f7a4fe092f6893c870f6e9",
    url="https://www.st.com/resource/en/datasheet/stm32g431cb.pdf",
)
SHUNT = _source(
    "Vishay WSLP2726 datasheet Rev. 29-Jun-2026",
    "pp. 1-2: 0.5 mOhm ordering code, 12 W class, two-terminal construction, "
    "dimensions, and solder-pad geometry",
    source_id="part:Vishay:WSLP2726L5000FEA:datasheet",
    sha256="1c3385e4b14f07808333c026393b88e0da1c23671fbb30e66a3fb86e3960a337",
    url="https://www.vishay.com/docs/30179/wslp2726.pdf",
)
BULK = _source(
    "KEMET A781 hybrid polymer capacitor datasheet",
    "A781MS157M1HLAV028 ordering row and 10 x 12.4 mm anti-vibration case data",
    source_id="part:KEMET:A781MS157M1HLAV028:datasheet",
    sha256="cbcf034aa661b3089074f6689273edc4147a4e6e242e811dfc709bc2c57ee0a9",
    url="https://content.kemet.com/datasheets/KEM_A4112_A781.pdf",
)
TVS = _source(
    "Vishay 7KPD10A through 7KPD43A datasheet",
    "7KPD26A row and SMPD package: 26 V standoff, 42.1 V max clamp class",
    source_id="part:Vishay:7KPD26A-M3-I:datasheet",
    sha256="6b6ac7931656bd87412967f26e2d71455f3f4e578513ea395c639240fea91c90",
    url="https://www.vishay.com/docs/98774/7kpd10a_thru_7kpd43a.pdf",
)
BUCK = _source(
    "Texas Instruments LM5164 datasheet Rev. D",
    "pp. 3, 16-19, 29: DDA pin map, design equations, hot-loop guidance, and DDA0008B land pattern",
    source_id="part:Texas-Instruments:LM5164DDAR:datasheet",
    sha256="57b8634d43198312f2be8746b1c13b7a9399c57cb13c919940046bfbe3276f03",
    url="https://www.ti.com/lit/ds/symlink/lm5164.pdf",
)
LDO = _source(
    "Texas Instruments TLV767-Q1 datasheet Rev. A",
    "p. 3 and package pages: fixed DRB pin map and WSON exposed-pad guidance",
    source_id="part:Texas-Instruments:TLV76733QWDRBRQ1:datasheet",
    sha256="8ad69f4ad6ad8eb577d8b8e1f81de2af50732dc248f42ef4ffcdc3ca110e0a0c",
    url="https://www.ti.com/lit/ds/symlink/tlv767-q1.pdf",
)
TERMINAL = _source(
    "Wurth Elektronik 7461057 datasheet",
    "six-pin 100 A M3 press-fit terminal, controlled-hole and 3 mm clearance data",
    source_id="part:Wurth-Elektronik:7461057:datasheet",
    sha256="081a908ca074d23811d5729e24784e3d8caa762e375e30f806e3dd883448a4db",
    url="https://www.we-online.com/components/products/datasheet/7461057.pdf",
)


def _part(
    reference: str,
    role: str,
    value: str,
    footprint: str,
    evidence: tuple[EvidenceRef, ...],
    *,
    symbol_id: str,
    supported: bool = True,
) -> ComponentRole:
    return ComponentRole(
        reference=reference,
        role=role,
        symbol_id=symbol_id,
        value=value,
        support_status="supported" if supported else "needs_datasheet_review",
        footprint=footprint,
        evidence=evidence,
    )


def compose_bldc_esc() -> CircuitObject:
    """Return the schematic-stage authority for BLDC ESC R001."""
    intent = CircuitIntent(
        raw_request="Compact high-current three-phase BLDC ESC, 3S-6S, 60 A target",
        intent_id=SUPPORTED_TOPOLOGY_ID,
        status="supported",
        assumptions={
            "battery_min_v": 9.0,
            "battery_normal_max_v": 25.2,
            "prototype_current_limit_a": 30.0,
            "target_continuous_current_a": 60.0,
            "target_peak_current_a": 100.0,
            "target_peak_duration_s": 10.0,
            "pcb_layers": 4.0,
            "board_width_mm": 140.0,
            "board_height_mm": 90.0,
        },
    )
    topology = TopologySelection(
        topology_id=SUPPORTED_TOPOLOGY_ID,
        title="STM32G431 + DRV8353S + three single-MOSFET half bridges",
        status="selected",
        evidence=(*MOSFET, *DRIVER, *MCU, *SHUNT, *BULK, *TVS, *BUCK, *LDO, *TERMINAL),
        warnings=(
            "The 60 A continuous rating is not released by schematic completion.",
            "The DRV8353 uses a charge pump and has no per-phase bootstrap pins; "
            "generic bootstrap-capacitor guidance does not apply.",
            "Hall/control connector and brake-chopper mating interfaces remain provisional.",
        ),
    )

    parts: list[ComponentRole] = [
        _part(
            "U1",
            "motor_control_mcu",
            "STM32G431CBT6",
            "Package_QFP:LQFP-48_7x7mm_P0.5mm",
            MCU,
            symbol_id="stdlib:STM32G431CBTx",
        ),
        _part(
            "U2",
            "three_phase_gate_driver",
            "DRV8353SRTAT",
            "PCBSmith_Power:Texas_RTA0040B_WQFN-40-1EP",
            DRIVER,
            symbol_id="pcbsmith:DRV8353SRTAT",
        ),
        _part(
            "U3",
            "battery_to_5v_buck",
            "LM5164DDAR",
            "Package_SO:SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.95x4.9mm_Mask2.71x3.4mm",
            BUCK,
            symbol_id="stdlib:LM5164DDA",
        ),
        _part(
            "U4",
            "five_to_three_volt_ldo",
            "TLV76733QWDRBRQ1",
            "Package_DFN_QFN:DFN-8-1EP_3x3mm_P0.5mm_EP1.65x2.38mm",
            LDO,
            symbol_id="stdlib:TLV76733QWDRBxQ1",
        ),
        _part(
            "D1",
            "battery_transient_tvs",
            "7KPD26A-M3/I",
            "PCBSmith_Power:Vishay_SMPD_TO-263AC",
            TVS,
            symbol_id="pcbsmith:7KPD_SMPD",
        ),
    ]

    for index in range(1, 7):
        parts.append(
            _part(
                f"Q{index}",
                "half_bridge_power_mosfet",
                "IPTC011N08NM5ATMA1",
                "PCBSmith_Power:Infineon_PG-HDSOP-16_TOLT",
                MOSFET,
                symbol_id="pcbsmith:IPTC011N08NM5",
            )
        )
    for index in range(1, 4):
        parts.append(
            _part(
                f"RSH{index}",
                "phase_shunt_with_kelvin_routing",
                "WSLP2726L5000FEA 0.5mR",
                "PCBSmith_Power:Vishay_WSLP2726",
                SHUNT,
                symbol_id="stdlib:R",
            )
        )
    for index, role in enumerate(
        ("battery_positive", "battery_negative", "phase_u", "phase_v", "phase_w"), start=1
    ):
        parts.append(
            _part(
                f"J{index}",
                f"{role}_power_terminal",
                "Wurth 7461057",
                "REDCUBE_THT_Wurth:MP_Wurth_WP-BUTR_7461057",
                TERMINAL,
                symbol_id="stdlib:Conn_01x01",
            )
        )
    for index in range(1, 9):
        parts.append(
            _part(
                f"CB{index}",
                "distributed_dc_link_bulk",
                "A781MS157M1HLAV028 150uF 50V",
                "PCBSmith_Power:KEMET_A781_10x12.4mm_AntiVibration",
                BULK,
                symbol_id="stdlib:C_Polarized",
            )
        )

    resistor_values = {
        **{f"RG{i}": ("gate_series", "4.7R") for i in range(1, 7)},
        **{f"RGS{i}": ("gate_source_pulldown", "100k") for i in range(1, 7)},
        "RFAULT1": ("driver_fault_pullup", "10k"),
        "RSDO1": ("driver_sdo_pullup", "10k"),
        "REN1": ("driver_enable_pulldown", "100k"),
        "RRON1": ("buck_on_time", "41.2k 1%"),
        "RFB1": ("buck_feedback_high", "316k 1%"),
        "RFB2": ("buck_feedback_low", "100k 1%"),
        "RRA1": ("buck_type3_ripple", "316k 1%"),
        "RUV1": ("buck_uvlo_high", "1M 1%"),
        "RUV2": ("buck_uvlo_low", "150k 1%"),
        "RBRAKE1": ("brake_command_pulldown", "10k"),
        "RAGND1": ("analog_ground_star_link", "0R"),
        "RNRST1": ("mcu_reset_pullup", "10k"),
        "RLED1": ("status_led_series", "1k"),
    }
    for phase in "UVW":
        resistor_values.update(
            {
                f"R{phase}H1": (f"phase_{phase.lower()}_sense_high_1", "150k 1%"),
                f"R{phase}H2": (f"phase_{phase.lower()}_sense_high_2", "150k 1%"),
                f"R{phase}L1": (f"phase_{phase.lower()}_sense_low", "24.9k 1%"),
            }
        )
    resistor_values.update(
        {
            "RBATH1": ("battery_sense_high_1", "150k 1%"),
            "RBATH2": ("battery_sense_high_2", "150k 1%"),
            "RBATL1": ("battery_sense_low", "24.9k 1%"),
        }
    )
    for index, phase in enumerate("UVW", start=1):
        resistor_values[f"RNTC{index}"] = (f"phase_{phase.lower()}_ntc_bias", "10k 1%")
    for reference, (role, value) in resistor_values.items():
        parts.append(
            _part(reference, role, value, R0603, _engineering(role, value), symbol_id="stdlib:R")
        )

    capacitor_values = {
        "CCP1": ("driver_charge_pump_flying", "47nF 100V", C0805),
        "CVCP1": ("driver_charge_pump_reservoir", "1uF 100V", C1210),
        "CVGLS1": ("driver_gate_supply_bypass", "1uF 25V", C0805),
        "CDVDD1": ("driver_digital_supply_bypass", "1uF 10V", C0603),
        "CVREF1": ("driver_csa_reference_bypass", "100nF", C0603),
        "CVM1": ("driver_vm_high_frequency", "100nF 50V", C0805),
        "CVM2": ("driver_vm_local_bulk", "10uF 50V", C1210),
        **{f"CHF{i}": ("half_bridge_local_dc_link", "4.7uF 50V X7R", C1210) for i in range(1, 7)},
        "CIN1": ("buck_input_bypass", "2.2uF 50V X7R", C1210),
        "CIN2": ("buck_input_bypass", "2.2uF 50V X7R", C1210),
        "CBST1": ("buck_bootstrap", "2.2nF 50V", C0603),
        "CRA1": ("buck_type3_ripple", "1.5nF", C0603),
        "CRB1": ("buck_type3_coupling", "56pF C0G", C0603),
        "COUT1": ("buck_output", "22uF 10V X7R", C1210),
        "COUT2": ("buck_output", "22uF 10V X7R", C1210),
        "CLDOIN1": ("ldo_input", "4.7uF 10V X7R", C0805),
        "CLDOOUT1": ("ldo_output", "4.7uF 10V X7R", C0805),
        "CM1": ("mcu_vdd_bypass", "100nF", C0603),
        "CM2": ("mcu_vdd_bypass", "100nF", C0603),
        "CM3": ("mcu_vdd_bypass", "100nF", C0603),
        "CM4": ("mcu_local_bulk", "4.7uF", C0805),
        "CMA1": ("mcu_analog_bypass", "1uF", C0603),
        "CMA2": ("mcu_vref_bypass", "100nF", C0603),
        "CNRST1": ("mcu_reset_filter", "100nF", C0603),
    }
    for index, phase in enumerate("UVW", start=1):
        capacitor_values[f"CSENSE{index}"] = (
            f"phase_{phase.lower()}_adc_filter",
            "470pF C0G",
            C0603,
        )
        capacitor_values[f"CNTC{index}"] = (f"phase_{phase.lower()}_ntc_filter", "10nF", C0603)
    capacitor_values["CBATS1"] = ("battery_adc_filter", "470pF C0G", C0603)
    for reference, (role, value, footprint) in capacitor_values.items():
        parts.append(
            _part(
                reference, role, value, footprint, _engineering(role, value), symbol_id="stdlib:C"
            )
        )

    parts.extend(
        (
            _part(
                "L1",
                "buck_inductor",
                "100uH >=1.5A",
                "Inductor_SMD:L_Coilcraft_MSS1246-XXX",
                _engineering(
                    "LM5164 5 V / 0.3 A inductor",
                    "100 uH gives approximately 40% ripple near the 22.2 V nominal input; "
                    "exact ordered inductor requires saturation and thermal confirmation.",
                ),
                symbol_id="stdlib:L",
                supported=False,
            ),
            _part(
                "FB1",
                "mcu_analog_supply_bead",
                "600R@100MHz",
                "Inductor_SMD:L_0603_1608Metric_Pad1.05x0.95mm_HandSolder",
                _engineering("VDDA isolation bead", "Confirm impedance and DC resistance."),
                symbol_id="stdlib:L",
                supported=False,
            ),
            _part(
                "NTC1",
                "phase_u_temperature_sensor",
                "100k NTC",
                "Resistor_SMD:R_0603_1608Metric",
                _engineering("MOSFET-bank NTC", "Calibrate on hardware."),
                symbol_id="stdlib:Thermistor",
                supported=False,
            ),
            _part(
                "NTC2",
                "phase_v_temperature_sensor",
                "100k NTC",
                "Resistor_SMD:R_0603_1608Metric",
                _engineering("MOSFET-bank NTC", "Calibrate on hardware."),
                symbol_id="stdlib:Thermistor",
                supported=False,
            ),
            _part(
                "NTC3",
                "phase_w_temperature_sensor",
                "100k NTC",
                "Resistor_SMD:R_0603_1608Metric",
                _engineering("MOSFET-bank NTC", "Calibrate on hardware."),
                symbol_id="stdlib:Thermistor",
                supported=False,
            ),
            _part(
                "J6",
                "swd_header",
                "Cortex Debug 10-pin",
                "Connector_PinHeader_1.27mm:PinHeader_2x05_P1.27mm_Vertical",
                _engineering("SWD programming", "Standard Cortex 10-pin mapping."),
                symbol_id="stdlib:Conn_02x05",
            ),
            _part(
                "J7",
                "hall_control_header_provisional",
                "HALL/CTRL 1x06",
                "Connector_JST:JST_GH_BM06B-GHS-TBT_1x06-1MP_P1.25mm_Vertical",
                _engineering(
                    "Provisional Hall connector",
                    "Mating harness must be confirmed before PCB release.",
                ),
                symbol_id="stdlib:Conn_01x06",
                supported=False,
            ),
            _part(
                "D2",
                "status_led",
                "GREEN",
                "LED_SMD:LED_0603_1608Metric",
                _engineering("Bring-up status LED", "Firmware-controlled."),
                symbol_id="stdlib:LED",
            ),
            _part(
                "J8",
                "logic_expansion_header",
                "LOGIC DEBUG 1x08",
                "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical",
                _engineering(
                    "Logic expansion and power-good header",
                    "Bring-up interface; not a motor harness connector.",
                ),
                symbol_id="stdlib:Conn_01x08",
            ),
        )
    )

    for index, net in enumerate(("BAT_P", "PGND", "5V", "3V3A", "AGND"), start=1):
        parts.append(
            _part(
                f"PF{index}",
                f"erc_power_flag_{net.lower()}",
                "PWR_FLAG",
                "",
                _engineering("ERC power authority", net),
                symbol_id="stdlib:PWR_FLAG",
            )
        )

    nets = (
        "BAT_P",
        "PGND",
        "AGND",
        "5V",
        "3V3",
        "3V3A",
        "VREF_3V3",
        "PHASE_U",
        "PHASE_V",
        "PHASE_W",
        "USHUNT_H",
        "VSHUNT_H",
        "WSHUNT_H",
        "GATE_UH",
        "GATE_UL",
        "GATE_VH",
        "GATE_VL",
        "GATE_WH",
        "GATE_WL",
        "DRV_GH_U",
        "DRV_GL_U",
        "DRV_GH_V",
        "DRV_GL_V",
        "DRV_GH_W",
        "DRV_GL_W",
        "PWM_UH",
        "PWM_UL",
        "PWM_VH",
        "PWM_VL",
        "PWM_WH",
        "PWM_WL",
        "DRV_EN",
        "DRV_NFAULT",
        "DRV_NSCS",
        "DRV_SCLK",
        "DRV_SDI",
        "DRV_SDO",
        "DRV_CPH",
        "DRV_CPL",
        "DRV_VCP",
        "DRV_VGLS",
        "DRV_DVDD",
        "DRV_VREF",
        "CSA_U",
        "CSA_V",
        "CSA_W",
        "VBUS_SENSE",
        "PHASE_U_SENSE",
        "PHASE_V_SENSE",
        "PHASE_W_SENSE",
        "VBUS_DIV_MID",
        "PHASE_U_DIV_MID",
        "PHASE_V_DIV_MID",
        "PHASE_W_DIV_MID",
        "NTC_U",
        "NTC_V",
        "NTC_W",
        "SWDIO",
        "SWCLK",
        "NRST",
        "HALL_U",
        "HALL_V",
        "HALL_W",
        "UART_TX",
        "UART_RX",
        "I2C_SCL",
        "I2C_SDA",
        "BUCK_SW",
        "BUCK_BST",
        "BUCK_FB",
        "BUCK_RON",
        "BUCK_EN",
        "BUCK_PGOOD",
        "BUCK_RIPPLE",
        "STATUS_LED",
        "BRAKE_CMD",
        "AUX1",
        "AUX2",
        "AUX3",
    )
    return CircuitObject(
        intent=intent,
        topology=topology,
        components=tuple(parts),
        nets=nets,
        math=MathReport(
            status="warning",
            calculations={
                "phase_shunt_v_at_60a": 0.03,
                "phase_shunt_w_at_60a": 1.8,
                "phase_shunt_v_at_100a": 0.05,
                "phase_shunt_w_at_100a": 5.0,
                "buck_target_v": 5.0,
                "buck_target_load_a": 0.3,
                "buck_nominal_frequency_hz": 300000.0,
                "buck_inductor_h": 100e-6,
                "adc_divider_v_at_42_1v": 42.1 * 24.9 / (300.0 + 24.9),
            },
            findings=(
                "Initial firmware battery-current limit remains 30 A.",
                "DRV8353 has no bootstrap pins; only its CPH-CPL flying capacitor and "
                "VCP-VDRAIN/VGLS/DVDD/VM/VREF support capacitors are fitted.",
                "The LM5164 5 V section is a calculated starting point and needs bench "
                "load/line/transient validation before it is treated as released.",
                "No external crystal is required in R001; firmware uses HSI16/PLL and must "
                "validate clock-fault behavior during bring-up.",
                "WSLP2726 is a two-terminal shunt.  Kelvin sense traces must leave the "
                "inner edges of its two pads independently and carry no load current.",
            ),
        ),
    )
