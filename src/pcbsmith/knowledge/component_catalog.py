from __future__ import annotations

import re
from dataclasses import dataclass

from pcbsmith.core.catalog import (
    CatalogEntry,
    CatalogGroup,
    CatalogPreferences,
    CatalogSearchQuery,
    ComponentFamily,
    ComponentVariant,
    DeveloperLibraryProposal,
    KiCadPartBinding,
    MissingPartRequest,
)
from pcbsmith.knowledge.builtin_library import FOOTPRINTS, SYMBOLS

_SEARCH_SPLIT_PATTERN = re.compile(r"[\s-]+")


@dataclass(frozen=True)
class ComponentCatalog:
    groups: tuple[CatalogGroup, ...]
    entries: tuple[CatalogEntry, ...]


def _family(id: str, name: str) -> ComponentFamily:
    return ComponentFamily(id=id, name=name)


def builtin_catalog() -> ComponentCatalog:
    basic_group = CatalogGroup(
        id="basic-components",
        name="Basic Components",
        description="Common passive, power, connector, diode, and switch parts.",
        default_enabled=True,
    )
    common_group = CatalogGroup(
        id="common-building-blocks",
        name="Common Building Blocks",
        description="Common adjustable, magnetic, protection, sensor, switching, and IC parts.",
        default_enabled=True,
    )
    entries = (
        CatalogEntry(
            id="pcbs:resistor_0603",
            family=_family("resistor", "Resistor"),
            variant=ComponentVariant(
                name="Resistor 0603",
                package="0603",
                mounting="smd",
                default_value="10k",
            ),
            symbol_id="stdlib:R",
            footprint_id="stdlib:R_0603",
            kicad=KiCadPartBinding(
                symbol_id="Device:R",
                footprint_id="Resistor_SMD:R_0603_1608Metric",
            ),
            tags=("basic", "passive", "resistor", "smd", "0603"),
            aliases=("r", "chip resistor", "res 0603"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:capacitor_0603",
            family=_family("capacitor", "Capacitor"),
            variant=ComponentVariant(
                name="Capacitor 0603",
                package="0603",
                mounting="smd",
                default_value="100nF",
            ),
            symbol_id="stdlib:C",
            footprint_id="stdlib:C_0603",
            kicad=KiCadPartBinding(
                symbol_id="Device:C",
                footprint_id="Capacitor_SMD:C_0603_1608Metric",
            ),
            tags=("basic", "passive", "capacitor", "smd", "0603"),
            aliases=("c", "cap", "chip capacitor"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:led_0603",
            family=_family("led", "LED"),
            variant=ComponentVariant(name="LED 0603", package="0603", mounting="smd"),
            symbol_id="stdlib:LED",
            footprint_id="stdlib:LED_0603",
            kicad=KiCadPartBinding(
                symbol_id="Device:LED",
                footprint_id="LED_SMD:LED_0603_1608Metric",
            ),
            tags=("basic", "diode", "indicator", "smd", "0603"),
            aliases=("light emitting diode",),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:resistor_0805",
            family=_family("resistor", "Resistor"),
            variant=ComponentVariant(
                name="Resistor 0805",
                package="0805",
                mounting="smd",
                default_value="10k",
            ),
            symbol_id="stdlib:R",
            footprint_id="stdlib:R_0805",
            kicad=KiCadPartBinding(
                symbol_id="Device:R",
                footprint_id="Resistor_SMD:R_0805_2012Metric",
            ),
            tags=("basic", "passive", "resistor", "smd", "0805", "hand-solderable"),
            aliases=("chip resistor 0805", "res 0805"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:capacitor_0805",
            family=_family("capacitor", "Capacitor"),
            variant=ComponentVariant(
                name="Capacitor 0805",
                package="0805",
                mounting="smd",
                default_value="100nF",
            ),
            symbol_id="stdlib:C",
            footprint_id="stdlib:C_0805",
            kicad=KiCadPartBinding(
                symbol_id="Device:C",
                footprint_id="Capacitor_SMD:C_0805_2012Metric",
            ),
            tags=("basic", "passive", "capacitor", "smd", "0805", "hand-solderable"),
            aliases=("chip capacitor 0805", "cap 0805"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:led_0805",
            family=_family("led", "LED"),
            variant=ComponentVariant(name="LED 0805", package="0805", mounting="smd"),
            symbol_id="stdlib:LED",
            footprint_id="stdlib:LED_0805",
            kicad=KiCadPartBinding(
                symbol_id="Device:LED",
                footprint_id="LED_SMD:LED_0805_2012Metric",
            ),
            tags=("basic", "diode", "indicator", "smd", "0805", "hand-solderable"),
            aliases=("light emitting diode 0805",),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:diode_0603",
            family=_family("diode", "Diode"),
            variant=ComponentVariant(name="Diode 0603", package="0603", mounting="smd"),
            symbol_id="stdlib:D",
            footprint_id="stdlib:D_0603",
            kicad=KiCadPartBinding(
                symbol_id="Device:D",
                footprint_id="Diode_SMD:D_0603_1608Metric",
            ),
            tags=("basic", "diode", "smd", "0603"),
            aliases=("signal diode",),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:schottky_diode_sod323",
            family=_family("schottky-diode", "Schottky Diode"),
            variant=ComponentVariant(
                name="Schottky Diode SOD-323",
                package="SOD-323",
                mounting="smd",
            ),
            symbol_id="stdlib:D_SCHOTTKY",
            footprint_id="stdlib:D_SOD323",
            kicad=KiCadPartBinding(
                symbol_id="Device:D_Schottky",
                footprint_id="Diode_SMD:D_SOD-323",
            ),
            tags=("basic", "diode", "schottky", "protection", "smd", "sod-323"),
            aliases=("reverse polarity diode", "low drop diode"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:zener_0603",
            family=_family("zener-diode", "Zener Diode"),
            variant=ComponentVariant(
                name="Zener Diode 0603",
                package="0603",
                mounting="smd",
                default_value="3.3V",
            ),
            symbol_id="stdlib:D_ZENER",
            footprint_id="stdlib:D_ZENER_0603",
            kicad=KiCadPartBinding(
                symbol_id="Device:D_Zener",
                footprint_id="Diode_SMD:D_0603_1608Metric",
            ),
            tags=("basic", "diode", "zener", "protection", "smd", "0603"),
            aliases=("voltage clamp", "reference diode"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:fuse_0603",
            family=_family("fuse", "Fuse"),
            variant=ComponentVariant(
                name="Fuse 0603",
                package="0603",
                mounting="smd",
                default_value="500mA",
            ),
            symbol_id="stdlib:FUSE",
            footprint_id="stdlib:FUSE_0603",
            kicad=KiCadPartBinding(
                symbol_id="Device:Fuse",
                footprint_id="Fuse:Fuse_0603_1608Metric",
            ),
            tags=("basic", "protection", "fuse", "smd", "0603"),
            aliases=("polyfuse", "resettable fuse"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:inductor_0603",
            family=_family("inductor", "Inductor"),
            variant=ComponentVariant(
                name="Inductor 0603",
                package="0603",
                mounting="smd",
                default_value="10uH",
            ),
            symbol_id="stdlib:L",
            footprint_id="stdlib:L_0603",
            kicad=KiCadPartBinding(
                symbol_id="Device:L",
                footprint_id="Inductor_SMD:L_0603_1608Metric",
            ),
            tags=("basic", "passive", "inductor", "magnetic", "smd", "0603"),
            aliases=("coil", "choke"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:push_button_th",
            family=_family("push-button", "Push Button"),
            variant=ComponentVariant(
                name="Push Button Through Hole",
                package="TH",
                mounting="through-hole",
            ),
            symbol_id="stdlib:SW_PUSH",
            footprint_id="stdlib:SW_PUSH_TH",
            tags=("basic", "switch", "button", "through-hole"),
            aliases=("momentary switch", "pushbutton"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:tactile_switch_smd",
            family=_family("push-button", "Push Button"),
            variant=ComponentVariant(
                name="Tactile Switch SMD",
                package="SMD",
                mounting="smd",
            ),
            symbol_id="stdlib:SW_PUSH",
            footprint_id="stdlib:SW_PUSH_SMD",
            kicad=KiCadPartBinding(
                symbol_id="Switch:SW_Push",
                footprint_id="Button_Switch_SMD:SW_SPST_TL3305A",
            ),
            tags=("basic", "switch", "button", "tactile", "smd"),
            aliases=("momentary tactile switch", "smd pushbutton"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:photoresistor_th",
            family=_family("photoresistor", "Photoresistor"),
            variant=ComponentVariant(
                name="Photoresistor Through Hole",
                package="TH",
                mounting="through-hole",
                default_value="LDR",
            ),
            symbol_id="stdlib:LDR",
            footprint_id="stdlib:LDR_TH",
            tags=("sensor", "light", "photoresistor", "ldr", "resistor", "through-hole"),
            aliases=("light dependent resistor", "photo resistor"),
            group_ids=("common-building-blocks",),
        ),
        CatalogEntry(
            id="pcbs:potentiometer_3pin_smd",
            family=_family("potentiometer", "Potentiometer"),
            variant=ComponentVariant(
                name="Potentiometer 3-pin SMD",
                package="3-pin SMD",
                mounting="smd",
                default_value="100k",
            ),
            symbol_id="stdlib:POT",
            footprint_id="stdlib:POT_3PIN",
            tags=("adjustable", "potentiometer", "resistor", "smd", "3-pin"),
            aliases=("pot", "trimmer", "variable resistor"),
            group_ids=("common-building-blocks",),
        ),
        CatalogEntry(
            id="pcbs:potentiometer_3pin_th",
            family=_family("potentiometer", "Potentiometer"),
            variant=ComponentVariant(
                name="Potentiometer 3-pin Through Hole",
                package="3-pin TH",
                mounting="through-hole",
                default_value="100k",
            ),
            symbol_id="stdlib:POT",
            footprint_id="stdlib:POT_3PIN_TH",
            tags=("adjustable", "potentiometer", "resistor", "through-hole", "3-pin"),
            aliases=("pot", "trimmer", "variable resistor"),
            group_ids=("common-building-blocks",),
        ),
        CatalogEntry(
            id="pcbs:nmos_sot23",
            family=_family("mosfet", "MOSFET"),
            variant=ComponentVariant(
                name="N-MOSFET SOT-23",
                package="SOT-23",
                mounting="smd",
                default_value="2N7002",
            ),
            symbol_id="stdlib:NMOS",
            footprint_id="stdlib:NMOS_SOT23",
            tags=("transistor", "mosfet", "nmos", "switching", "smd", "sot-23"),
            aliases=("n-channel mosfet", "low-side switch"),
            group_ids=("common-building-blocks",),
        ),
        CatalogEntry(
            id="pcbs:npn_bjt_sot23",
            family=_family("bjt", "Bipolar Transistor"),
            variant=ComponentVariant(
                name="NPN BJT SOT-23",
                package="SOT-23",
                mounting="smd",
                default_value="BC847",
            ),
            symbol_id="stdlib:NPN_BJT",
            footprint_id="stdlib:BJT_SOT23",
            kicad=KiCadPartBinding(
                symbol_id="Transistor_BJT:Q_NPN_BEC",
                footprint_id="Package_TO_SOT_SMD:SOT-23",
            ),
            tags=("transistor", "bjt", "npn", "amplifier", "switching", "smd", "sot-23"),
            aliases=("npn transistor", "small signal npn", "bc847"),
            group_ids=("common-building-blocks",),
        ),
        CatalogEntry(
            id="pcbs:pnp_bjt_sot23",
            family=_family("bjt", "Bipolar Transistor"),
            variant=ComponentVariant(
                name="PNP BJT SOT-23",
                package="SOT-23",
                mounting="smd",
                default_value="BC857",
            ),
            symbol_id="stdlib:PNP_BJT",
            footprint_id="stdlib:BJT_SOT23",
            kicad=KiCadPartBinding(
                symbol_id="Transistor_BJT:Q_PNP_BEC",
                footprint_id="Package_TO_SOT_SMD:SOT-23",
            ),
            tags=("transistor", "bjt", "pnp", "amplifier", "switching", "smd", "sot-23"),
            aliases=("pnp transistor", "small signal pnp", "bc857"),
            group_ids=("common-building-blocks",),
        ),
        CatalogEntry(
            id="pcbs:lm393_soic8",
            family=_family("comparator", "Comparator"),
            variant=ComponentVariant(
                name="LM393 Dual Comparator SOIC-8",
                package="SOIC-8",
                mounting="smd",
                default_value="LM393",
            ),
            symbol_id="stdlib:LM393",
            footprint_id="stdlib:SOIC8",
            kicad=KiCadPartBinding(
                symbol_id="Comparator:LM393",
                footprint_id="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
            ),
            tags=("comparator", "threshold", "ic", "analog", "smd", "soic-8"),
            aliases=("dual comparator", "lm393"),
            group_ids=("common-building-blocks",),
        ),
        CatalogEntry(
            id="pcbs:lm358_soic8",
            family=_family("op-amp", "Op Amp"),
            variant=ComponentVariant(
                name="LM358 Dual Op Amp SOIC-8",
                package="SOIC-8",
                mounting="smd",
                default_value="LM358",
            ),
            symbol_id="stdlib:LM358",
            footprint_id="stdlib:SOIC8",
            kicad=KiCadPartBinding(
                symbol_id="Amplifier_Operational:LM358",
                footprint_id="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
            ),
            tags=("op-amp", "amplifier", "buffer", "ic", "analog", "smd", "soic-8"),
            aliases=("dual op amp", "lm358"),
            group_ids=("common-building-blocks",),
        ),
        CatalogEntry(
            id="pcbs:active_buzzer_th",
            family=_family("buzzer", "Buzzer"),
            variant=ComponentVariant(
                name="Active Buzzer Through Hole",
                package="12mm TH",
                mounting="through-hole",
                default_value="5V active buzzer",
            ),
            symbol_id="stdlib:BUZZER",
            footprint_id="stdlib:BUZZER_TH",
            kicad=KiCadPartBinding(
                symbol_id="Device:Buzzer",
                footprint_id="Buzzer_Beeper:Buzzer_12x9.5RM7.6",
            ),
            tags=("audio", "buzzer", "indicator", "through-hole", "polarized"),
            aliases=("piezo buzzer", "sounder"),
            group_ids=("common-building-blocks",),
        ),
        CatalogEntry(
            id="pcbs:terminal_block_1x02_p5mm",
            family=_family("terminal-block", "Terminal Block"),
            variant=ComponentVariant(
                name="Terminal Block 1x02 P5.00mm",
                package="1x02 P5.00mm",
                mounting="through-hole",
            ),
            symbol_id="stdlib:CONN_01X02",
            footprint_id="stdlib:TerminalBlock_1x02_P5.00mm",
            kicad=KiCadPartBinding(
                symbol_id="Connector:Conn_01x02_Pin",
                footprint_id=("TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm"),
            ),
            tags=("connector", "terminal-block", "power-entry", "through-hole", "p5.00mm"),
            aliases=("screw terminal", "power terminal", "2 pin terminal block"),
            group_ids=("common-building-blocks",),
        ),
        CatalogEntry(
            id="pcbs:ams1117_3v3_sot223",
            family=_family("linear-regulator", "Linear Regulator"),
            variant=ComponentVariant(
                name="AMS1117-3.3 SOT-223",
                package="SOT-223",
                mounting="smd",
                default_value="3.3V",
            ),
            symbol_id="stdlib:AMS1117",
            footprint_id="stdlib:SOT223_REG",
            kicad=KiCadPartBinding(
                symbol_id="Regulator_Linear:AMS1117-3.3",
                footprint_id="Package_TO_SOT_SMD:SOT-223-3_TabPin2",
            ),
            tags=("regulator", "ldo", "linear", "power", "smd", "sot-223"),
            aliases=("ams1117", "3v3 regulator", "linear regulator"),
            group_ids=("common-building-blocks",),
        ),
        CatalogEntry(
            id="pcbs:cr2032_battery_holder_smd",
            family=_family("battery-holder", "Battery Holder"),
            variant=ComponentVariant(
                name="CR2032 Battery Holder SMD",
                package="CR2032 SMD",
                mounting="smd",
                default_value="3V",
            ),
            symbol_id="stdlib:BATTERY_CELL",
            footprint_id="stdlib:BATTERY_CR2032_SMD",
            kicad=KiCadPartBinding(
                symbol_id="Device:Battery_Cell",
                footprint_id="Battery:BatteryHolder_LINX_BAT-HLD-012-SMT",
            ),
            tags=("battery", "power", "coin-cell", "cr2032", "smd"),
            aliases=("coin cell holder", "battery holder"),
            group_ids=("common-building-blocks",),
        ),
        CatalogEntry(
            id="pcbs:crystal_3225",
            family=_family("crystal", "Crystal"),
            variant=ComponentVariant(
                name="Crystal 3225",
                package="3225",
                mounting="smd",
                default_value="16MHz",
            ),
            symbol_id="stdlib:CRYSTAL",
            footprint_id="stdlib:CRYSTAL_3225",
            kicad=KiCadPartBinding(
                symbol_id="Device:Crystal",
                footprint_id="Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
            ),
            tags=("clock", "crystal", "oscillator", "smd", "3225"),
            aliases=("external crystal", "clock source"),
            group_ids=("common-building-blocks",),
        ),
        CatalogEntry(
            id="pcbs:attiny85_soic8",
            family=_family("microcontroller", "Microcontroller"),
            variant=ComponentVariant(
                name="ATtiny85 SOIC-8",
                package="SOIC-8",
                mounting="smd",
                default_value="ATtiny85",
            ),
            symbol_id="stdlib:ATTINY85",
            footprint_id="stdlib:SOIC8",
            kicad=KiCadPartBinding(
                symbol_id="MCU_Microchip_ATtiny:ATtiny85-20S",
                footprint_id="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
            ),
            tags=("microcontroller", "avr", "attiny", "attiny85", "ic", "smd", "soic-8"),
            aliases=("tiny85", "8 bit mcu", "small microcontroller"),
            group_ids=("common-building-blocks",),
        ),
        CatalogEntry(
            id="pcbs:ne555_soic8",
            family=_family("timer", "Timer IC"),
            variant=ComponentVariant(
                name="NE555 SOIC-8",
                package="SOIC-8",
                mounting="smd",
                default_value="NE555",
            ),
            symbol_id="stdlib:NE555",
            footprint_id="stdlib:SOIC8",
            tags=("timer", "ic", "oscillator", "pwm", "smd", "soic-8"),
            aliases=("555", "ne555", "timer ic"),
            group_ids=("common-building-blocks",),
        ),
        CatalogEntry(
            id="pcbs:relay_spdt_th",
            family=_family("relay", "Relay"),
            variant=ComponentVariant(
                name="Relay SPDT Through Hole",
                package="SPDT TH",
                mounting="through-hole",
                default_value="5V coil",
            ),
            symbol_id="stdlib:RELAY_SPDT",
            footprint_id="stdlib:RELAY_SPDT_TH",
            tags=(
                "electromechanical",
                "relay",
                "switching",
                "coil",
                "through-hole",
                "needs-safety-review",
            ),
            aliases=("spdt relay", "mechanical relay"),
            group_ids=("common-building-blocks",),
        ),
        CatalogEntry(
            id="pcbs:transformer_th",
            family=_family("transformer", "Transformer"),
            variant=ComponentVariant(
                name="Transformer Through Hole",
                package="TH",
                mounting="through-hole",
            ),
            symbol_id="stdlib:TRANSFORMER",
            footprint_id="stdlib:TRANSFORMER_TH",
            tags=(
                "magnetic",
                "transformer",
                "isolation",
                "through-hole",
                "needs-safety-review",
            ),
            aliases=("coupled inductor",),
            group_ids=("common-building-blocks",),
        ),
        CatalogEntry(
            id="pcbs:switch_spst_th",
            family=_family("switch", "Switch"),
            variant=ComponentVariant(
                name="Switch SPST Through Hole",
                package="TH",
                mounting="through-hole",
            ),
            symbol_id="stdlib:SW_SPST",
            footprint_id="stdlib:SW_SPST_TH",
            tags=("basic", "switch", "spst", "through-hole"),
            aliases=("toggle switch", "single pole single throw"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:pin_header_1x02_p2.54mm",
            family=_family("pin-header", "Pin Header"),
            variant=ComponentVariant(
                name="Pin Header 1x02 P2.54mm",
                package="1x02 P2.54mm",
                mounting="through-hole",
            ),
            symbol_id="stdlib:CONN_01X02",
            footprint_id="stdlib:PinHeader_1x02_P2.54mm",
            tags=("basic", "connector", "pin-header", "through-hole", "p2.54mm"),
            aliases=("header 2 pin", "connector 1x02"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:pin_header_1x06_p2.54mm",
            family=_family("pin-header", "Pin Header"),
            variant=ComponentVariant(
                name="Pin Header 1x06 P2.54mm",
                package="1x06 P2.54mm",
                mounting="through-hole",
            ),
            symbol_id="stdlib:CONN_01X06",
            footprint_id="stdlib:PinHeader_1x06_P2.54mm",
            kicad=KiCadPartBinding(
                symbol_id="Connector:Conn_01x06_Pin",
                footprint_id="Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical",
            ),
            tags=("basic", "connector", "pin-header", "programming", "through-hole", "p2.54mm"),
            aliases=("header 6 pin", "isp header", "programming header"),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:vcc_power",
            family=_family("power", "Power"),
            variant=ComponentVariant(
                name="VCC Power Flag",
                mounting="virtual",
                default_value="VCC",
            ),
            symbol_id="stdlib:VCC",
            kicad=KiCadPartBinding(symbol_id="power:VCC"),
            tags=("basic", "power", "vcc", "virtual"),
            aliases=("positive supply",),
            group_ids=("basic-components",),
        ),
        CatalogEntry(
            id="pcbs:gnd_power",
            family=_family("power", "Power"),
            variant=ComponentVariant(
                name="GND Power Flag",
                mounting="virtual",
                default_value="GND",
            ),
            symbol_id="stdlib:GND",
            kicad=KiCadPartBinding(symbol_id="power:GND"),
            tags=("basic", "power", "ground", "virtual"),
            aliases=("gnd", "0v"),
            group_ids=("basic-components",),
        ),
    )
    catalog = ComponentCatalog(groups=(basic_group, common_group), entries=entries)
    validate_catalog(catalog)
    return catalog


def validate_catalog(catalog: ComponentCatalog) -> None:
    group_ids: set[str] = set()
    for group in catalog.groups:
        if group.id in group_ids:
            raise ValueError(f"Duplicate catalog group id: {group.id}")
        group_ids.add(group.id)

    entry_ids: set[str] = set()
    for entry in catalog.entries:
        if entry.id in entry_ids:
            raise ValueError(f"Duplicate catalog entry id: {entry.id}")
        entry_ids.add(entry.id)

        if entry.symbol_id not in SYMBOLS:
            raise ValueError(f"Unknown symbol id for catalog entry {entry.id}: {entry.symbol_id}")
        if entry.footprint_id is not None and entry.footprint_id not in FOOTPRINTS:
            raise ValueError(
                f"Unknown footprint id for catalog entry {entry.id}: {entry.footprint_id}"
            )
        for group_id in entry.group_ids:
            if group_id not in group_ids:
                raise ValueError(f"Unknown group id for catalog entry {entry.id}: {group_id}")


def entry_by_id(catalog: ComponentCatalog, entry_id: str) -> CatalogEntry:
    for entry in catalog.entries:
        if entry.id == entry_id:
            return entry
    raise KeyError(f"Unknown catalog entry: {entry_id}")


def search_catalog(
    catalog: ComponentCatalog,
    query: CatalogSearchQuery,
    *,
    global_preferences: CatalogPreferences | None = None,
    project_preferences: CatalogPreferences | None = None,
) -> tuple[CatalogEntry, ...]:
    preferred_ids = _preferred_entry_ids(catalog, global_preferences, project_preferences)
    text_terms = tuple(term for term in query.text.split("-") if term)

    results: list[CatalogEntry] = []
    for entry in catalog.entries:
        if not entry.normal_user_visible:
            continue
        if query.preferred_only and entry.id not in preferred_ids:
            continue
        if query.group_ids and not (set(entry.group_ids) & set(query.group_ids)):
            continue
        if query.tags and not set(query.tags).issubset(entry.tags):
            continue

        search_tokens = _search_tokens(entry)
        if text_terms and not all(term in search_tokens for term in text_terms):
            continue
        results.append(entry)
    return tuple(results)


def _search_tokens(entry: CatalogEntry) -> set[str]:
    tokens: set[str] = set()
    values = (
        entry.family.name,
        entry.variant.name,
        entry.variant.package or "",
        *entry.tags,
        *entry.aliases,
    )
    for value in values:
        normalized = value.strip().lower().replace("_", "-")
        if not normalized:
            continue
        tokens.add(normalized)
        tokens.update(term for term in _SEARCH_SPLIT_PATTERN.split(normalized) if term)
    return tokens


def _preferred_entry_ids(
    catalog: ComponentCatalog,
    global_preferences: CatalogPreferences | None,
    project_preferences: CatalogPreferences | None,
) -> set[str]:
    enabled_group_ids = {group.id for group in catalog.groups if group.default_enabled}
    visible_entry_ids: set[str] = set()
    hidden_entry_ids: set[str] = set()

    for preferences in (global_preferences, project_preferences):
        if preferences is None:
            continue
        enabled_group_ids.update(preferences.enabled_group_ids)

        hidden_entry_ids.difference_update(preferences.visible_entry_ids)
        visible_entry_ids.update(preferences.visible_entry_ids)

        visible_entry_ids.difference_update(preferences.hidden_entry_ids)
        hidden_entry_ids.update(preferences.hidden_entry_ids)

    preferred_ids = {
        entry.id
        for entry in catalog.entries
        if entry.normal_user_visible and set(entry.group_ids).intersection(enabled_group_ids)
    }
    user_visible_ids = {entry.id for entry in catalog.entries if entry.normal_user_visible}
    preferred_ids.update(visible_entry_ids & user_visible_ids)
    preferred_ids.difference_update(hidden_entry_ids)
    return preferred_ids


def create_missing_part_request(
    requested_name: str, *, reason: str, tags: tuple[str, ...] = ()
) -> MissingPartRequest:
    return MissingPartRequest(
        requested_name=requested_name,
        reason=reason,
        requested_tags=tags,
    )


def create_developer_proposal(
    *,
    requested_name: str,
    proposed_entry_id: str,
    notes: str,
) -> DeveloperLibraryProposal:
    return DeveloperLibraryProposal(
        requested_name=requested_name,
        proposed_entry_id=proposed_entry_id,
        notes=notes,
    )
