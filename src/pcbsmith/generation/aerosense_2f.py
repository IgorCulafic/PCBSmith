"""Circuit authority for the AeroSense-2F dual-fan environment monitor."""

from __future__ import annotations

from pcbsmith.circuit.models import (
    CircuitIntent,
    CircuitObject,
    ComponentRole,
    EvidenceRef,
    MathReport,
    TopologySelection,
)

SUPPORTED_TOPOLOGY_ID = "aerosense_2f_r001"
R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"


def _evidence(title: str, url: str, locator: str) -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef(
            kind="manufacturer_document",
            title=title,
            locator=locator,
            official_url=url,
            source_status="unpinned",
            locator_status="figure_verified",
            applicability_status="confirmed",
        ),
    )


RP2040_EVIDENCE = _evidence(
    "Hardware design with RP2040",
    "https://datasheets.raspberrypi.com/rp2040/hardware-design-with-rp2040.pdf",
    "Minimal design, USB, QSPI, crystal, supply decoupling and exposed-pad guidance.",
)
TYPEC_EVIDENCE = _evidence(
    "TUSB320LAI datasheet",
    "https://www.ti.com/lit/ds/symlink/tusb320lai.pdf",
    "UFP GPIO mode, internal Rd terminations and source-current advertisement decoding.",
)
FAN_SWITCH_EVIDENCE = _evidence(
    "TPS2553 datasheet",
    "https://www.ti.com/lit/ds/symlink/tps2553.pdf",
    "Adjustable current limit, active-high enable and active-low open-drain fault.",
)


def _part(
    reference: str,
    role: str,
    value: str,
    footprint: str,
    *,
    symbol_id: str,
    evidence: tuple[EvidenceRef, ...] = RP2040_EVIDENCE,
) -> ComponentRole:
    return ComponentRole(
        reference=reference,
        role=role,
        symbol_id=symbol_id,
        value=value,
        support_status="supported",
        footprint=footprint,
        evidence=evidence,
    )


def compose_aerosense_2f() -> CircuitObject:
    parts: list[ComponentRole] = [
        _part(
            "U1",
            "environment_monitor_mcu",
            "RP2040",
            "Package_DFN_QFN:QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm_ThermalVias",
            symbol_id="stdlib:RP2040",
        ),
        _part(
            "U2",
            "qspi_boot_flash",
            "W25Q16JVSSIQ",
            "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
            symbol_id="stdlib:W25Q16JVSS",
        ),
        _part(
            "U3",
            "3v3_ldo",
            "AP2112K-3.3TRG1",
            "Package_TO_SOT_SMD:SOT-23-5",
            symbol_id="stdlib:AP2112K-3.3",
        ),
        _part(
            "U4",
            "type_c_current_detector",
            "TUSB320LAIRWBR",
            "PCBSmith_AeroSense:TUSB320_X2QFN12",
            symbol_id="stdlib:TUSB320",
            evidence=TYPEC_EVIDENCE,
        ),
        *(
            _part(
                f"U{index}",
                f"fan_{index - 4}_current_limited_switch",
                "TPS2553DBVR",
                "Package_TO_SOT_SMD:SOT-23-6",
                symbol_id="stdlib:Conn_01x06",
                evidence=FAN_SWITCH_EVIDENCE,
            )
            for index in (5, 6)
        ),
        _part(
            "U7",
            "usb_data_esd",
            "USBLC6-2SC6",
            "Package_TO_SOT_SMD:SOT-23-6",
            symbol_id="stdlib:USBLC6-2SC6",
        ),
        _part(
            "U8",
            "temperature_humidity_sensor",
            "SHT45-AD1B-R3",
            "PCBSmith_AeroSense:Sensirion_SHT45_NoCentralPad",
            symbol_id="stdlib:SHT4x",
        ),
        _part(
            "U9",
            "vbus_esd",
            "TPD1E10B06DPYR",
            "PCBSmith_AeroSense:TPD1E10B06_DPY2",
            symbol_id="stdlib:D_TVS",
        ),
        _part(
            "U10",
            "cc_esd",
            "TPD2EUSB30DRTR",
            "Package_TO_SOT_SMD:Texas_DRT-3",
            symbol_id="stdlib:TPD2EUSB30",
        ),
        _part(
            "U11",
            "microsd_esd",
            "TPD4E05U06DQAR",
            "Package_SON:USON-10_2.5x1.0mm_P0.5mm",
            symbol_id="stdlib:TPD4E05U06DQA",
        ),
        _part(
            "J1",
            "usb_c_receptacle",
            "USB4105-GF-A",
            "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal",
            symbol_id="stdlib:USB_C",
        ),
        _part(
            "DS1",
            "oled_module",
            "Adafruit 4440 OLED",
            "PCBSmith_AeroSense:Adafruit_4440_OLED_Module",
            symbol_id="stdlib:Conn_01x06",
        ),
        _part(
            "J3",
            "microsd_socket",
            "DM3AT-SF-PEJM5",
            "Connector_Card:microSD_HC_Hirose_DM3AT-SF-PEJM5",
            symbol_id="stdlib:Micro_SD_Card_Det_Hirose_DM3AT",
        ),
        *(
            _part(
                f"J{index}",
                f"fan_{index - 3}_connector",
                "Molex 47053-1000",
                "Connector:FanPinHeader_1x04_P2.54mm_Vertical",
                symbol_id="stdlib:Conn_01x04",
            )
            for index in (4, 5)
        ),
        _part(
            "J6",
            "swd_probe",
            "TC2030-IDC-NL",
            "Connector:Tag-Connect_TC2030-IDC-NL_2x03_P1.27mm_Vertical",
            symbol_id="stdlib:Conn_02x03",
        ),
        _part(
            "Y1",
            "mcu_crystal",
            "ABM8-272-T3 12MHz",
            "Crystal:Crystal_SMD_Abracon_ABM8G-4Pin_3.2x2.5mm",
            symbol_id="stdlib:Crystal_GND24",
        ),
        _part(
            "FB1",
            "adc_supply_filter",
            "600R@100MHz",
            "Inductor_SMD:L_0603_1608Metric",
            symbol_id="stdlib:FerriteBead",
        ),
    ]
    for index in (1, 2):
        parts.append(
            _part(
                f"Q{index}",
                f"fan_{index}_open_drain_pwm",
                "2N7002,215",
                "Package_TO_SOT_SMD:SOT-23",
                symbol_id="stdlib:2N7002",
            )
        )
    for index, function, mpn in (
        (1, "PWR_USB_GREEN", "150060GS75000"),
        (2, "FAN_FAULT_AMBER", "150060YS75000"),
        (3, "SD_LOG_BLUE", "150060BS75000"),
    ):
        parts.append(
            _part(
                f"D{index}",
                function.lower(),
                mpn,
                "LED_SMD:LED_0603_1608Metric",
                symbol_id="stdlib:LED",
            )
        )
    for index, value in enumerate(("MODE", "SELECT_ACK", "LOG"), start=1):
        parts.append(
            _part(
                f"SW{index}",
                f"{value.lower()}_button",
                f"B3F-1000 {value}",
                "Button_Switch_THT:SW_PUSH_6mm_H4.3mm",
                symbol_id="stdlib:SW_Push",
            )
        )
    for index, value in ((4, "BOOTSEL"), (5, "RESET")):
        parts.append(
            _part(
                f"SW{index}",
                f"{value.lower()}_button",
                f"B3U-1000P {value}",
                "Button_Switch_SMD:SW_SPST_B3U-1000P",
                symbol_id="stdlib:SW_Push",
            )
        )
    test_points = {
        "TP1": ("vbus_test_point", "VBUS"),
        "TP2": ("3v3_test_point", "3V3"),
        "TP3": ("fan1_rail_test_point", "FAN1_5V"),
        "TP4": ("fan2_rail_test_point", "FAN2_5V"),
        "TP5": ("ground_test_point", "GND"),
        "TP6": ("fan1_tach_test_point", "FAN1_TACH"),
        "TP7": ("fan2_tach_test_point", "FAN2_TACH"),
    }
    for reference, (role, net) in test_points.items():
        parts.append(
            _part(
                reference,
                role,
                f"{net} probe pad",
                "TestPoint:TestPoint_Pad_D1.0mm",
                symbol_id="stdlib:TestPoint",
            )
        )

    resistor_values = {
        "R1": ("usb_dm_series", "27R"),
        "R2": ("usb_dp_series", "27R"),
        "R3": ("crystal_series", "1k"),
        "R4": ("qspi_ss_pullup", "10k"),
        "R5": ("run_pullup", "10k"),
        "R6": ("typec_out1_pullup", "10k"),
        "R7": ("typec_out2_pullup", "10k"),
        "R8": ("typec_vbus_detect", "900k"),
        "R9": ("fan1_ilim", "59k 1%"),
        "R10": ("fan2_ilim", "59k 1%"),
        "R11": ("fan1_enable_pulldown", "100k"),
        "R12": ("fan2_enable_pulldown", "100k"),
        "R13": ("fan1_fault_pullup", "10k"),
        "R14": ("fan2_fault_pullup", "10k"),
        "R15": ("fan1_tach_pullup", "10k"),
        "R16": ("fan2_tach_pullup", "10k"),
        "R17": ("fan1_tach_series", "1k"),
        "R18": ("fan2_tach_series", "1k"),
        "R19": ("fan1_pwm_gate_series", "100R"),
        "R20": ("fan2_pwm_gate_series", "100R"),
        "R21": ("fan1_pwm_gate_pulldown", "100k"),
        "R22": ("fan2_pwm_gate_pulldown", "100k"),
        "R23": ("mode_pullup", "10k"),
        "R24": ("select_pullup", "10k"),
        "R25": ("log_pullup", "10k"),
        "R26": ("pwr_led_series", "1k"),
        "R27": ("fault_led_series", "1k"),
        "R28": ("log_led_series", "1k"),
        "R29": ("sd_cs_pullup", "10k"),
        "R30": ("sd_cs_series", "22R"),
        "R31": ("sd_mosi_series", "22R"),
        "R32": ("sd_clk_series", "22R"),
        "R33": ("sd_detect_pullup", "10k"),
        "R34": ("bootsel_series", "1k"),
    }
    for reference, (role, value) in resistor_values.items():
        parts.append(
            _part(
                reference,
                role,
                value,
                R0603,
                symbol_id="stdlib:R",
            )
        )

    capacitor_values = {
        "C1": ("vbus_bulk", "10uF", C0805),
        "C2": ("ldo_input", "1uF", C0805),
        "C3": ("ldo_output", "1uF", C0805),
        **{
            f"C{index}": ("rp2040_3v3_bypass", "100nF", C0603)
            for index in range(4, 12)
        },
        "C12": ("rp2040_1v1_bypass", "1uF", C0603),
        "C13": ("rp2040_adc_bypass", "100nF", C0603),
        "C14": ("flash_bypass", "100nF", C0603),
        "C15": ("crystal_load", "15pF C0G", C0603),
        "C16": ("crystal_load", "15pF C0G", C0603),
        "C17": ("typec_bypass", "100nF", C0603),
        "C18": ("fan1_input_bypass", "100nF", C0603),
        "C19": ("fan2_input_bypass", "100nF", C0603),
        "C20": ("fan1_output_bulk", "47uF", C0805),
        "C21": ("fan2_output_bulk", "47uF", C0805),
        "C22": ("fan1_output_hf", "100nF", C0603),
        "C23": ("fan2_output_hf", "100nF", C0603),
        "C24": ("sht45_bypass", "100nF", C0603),
        "C25": ("microsd_bypass", "100nF", C0603),
        "C26": ("microsd_bulk", "10uF", C0805),
        "C27": ("oled_local", "1uF", C0603),
        "C28": ("3v3_bulk", "10uF", C0805),
        "C29": ("fan1_tach_filter", "1nF", C0603),
        "C30": ("fan2_tach_filter", "1nF", C0603),
    }
    for reference, (role, value, footprint) in capacitor_values.items():
        parts.append(
            _part(
                reference,
                role,
                value,
                footprint,
                symbol_id="stdlib:C",
            )
        )

    nets = (
        "VBUS",
        "3V3",
        "1V1",
        "ADC_3V3",
        "GND",
        "CC1",
        "CC2",
        "TYPEC_OUT1",
        "TYPEC_OUT2",
        "USB_DP_CONN",
        "USB_DM_CONN",
        "USB_DP_ESD",
        "USB_DM_ESD",
        "USB_DP_MCU",
        "USB_DM_MCU",
        "XIN",
        "XOUT_RAW",
        "XOUT",
        "RUN",
        "SWCLK",
        "SWDIO",
        "QSPI_SCLK",
        "QSPI_SD0",
        "QSPI_SD1",
        "QSPI_SD2",
        "QSPI_SD3",
        "QSPI_SS",
        "BOOT_BTN",
        "I2C_SDA",
        "I2C_SCL",
        "OLED_RESET",
        "FAN1_EN",
        "FAN2_EN",
        "FAN1_FAULT_N",
        "FAN2_FAULT_N",
        "FAN1_5V",
        "FAN2_5V",
        "FAN1_PWM_GPIO",
        "FAN2_PWM_GPIO",
        "FAN1_PWM_GATE",
        "FAN2_PWM_GATE",
        "FAN1_PWM",
        "FAN2_PWM",
        "FAN1_TACH_RAW",
        "FAN2_TACH_RAW",
        "FAN1_TACH",
        "FAN2_TACH",
        "SW_MODE",
        "SW_SELECT",
        "SW_LOG",
        "LED_PWR_A",
        "LED_FAULT_A",
        "LED_LOG_A",
        "SD_CS_MCU",
        "SD_MOSI_MCU",
        "SD_SCLK_MCU",
        "SD_CS_CARD",
        "SD_MOSI_CARD",
        "SD_SCLK_CARD",
        "SD_MISO",
        "SD_DETECT",
    )
    return CircuitObject(
        intent=CircuitIntent(
            raw_request="USB-C dual-fan temperature/humidity monitor with OLED and microSD",
            intent_id=SUPPORTED_TOPOLOGY_ID,
            status="supported",
            assumptions={
                "pcb_layers": 2.0,
                "board_width_mm": 70.0,
                "board_height_mm": 50.0,
                "fan_channel_design_current_a": 0.5,
                "selected_fan_max_current_a": 0.1,
                "usb_vbus_v": 5.0,
                "logic_supply_v": 3.3,
            },
        ),
        topology=TopologySelection(
            topology_id=SUPPORTED_TOPOLOGY_ID,
            title="RP2040 USB-C environment monitor with two protected PWM fan channels",
            status="selected",
            evidence=(*RP2040_EVIDENCE, *TYPEC_EVIDENCE, *FAN_SWITCH_EVIDENCE),
            warnings=(
                "Fan rails default off through 100-kohm enable pulldowns and "
                "require firmware qualification of Type-C current state.",
                "The selected fans draw 0.10 A maximum each; each connector "
                "path is nevertheless laid out for the 0.50 A interface envelope.",
                "The Adafruit 4440 onboard 10-kohm I2C pull-ups are the only "
                "default host-bus pull-ups.",
            ),
        ),
        components=tuple(parts),
        nets=nets,
        math=MathReport(
            status="warning",
            calculations={
                "selected_fans_total_max_a": 0.2,
                "fan_connector_envelope_total_a": 1.0,
                "logic_reserve_a": 0.2,
                "tps2553_rilim_nominal_kohm": 59.0,
                "fan_pwm_frequency_hz": 25_000.0,
                "microsd_max_spi_hz": 25_000_000.0,
            },
            findings=(
                "A 59-kohm 1% ILIM resistor retains the TPS2553 upper-limit "
                "target at approximately 0.5 A; production limits remain subject "
                "to the datasheet tolerance equation and bench trip-current "
                "measurement.",
                "The two selected 0.10 A fans fit the advertised 1.5 A Type-C "
                "state with the stated logic reserve; default-current firmware "
                "must keep both fan rails disabled.",
                "PCB acceptance does not imply firmware enumeration, logging "
                "integrity, fan stall behavior or thermal correlation.",
            ),
        ),
    )
